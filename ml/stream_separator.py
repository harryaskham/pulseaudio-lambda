#!/usr/bin/env python3
"""
Real-time audio stem separation using HS-TasNet.
Reads audio from stdin, processes in chunks, applies volume controls, and outputs to stdout.
Compatible with PulseAudio Lambda bridge.
"""

import sys
import os
import argparse
import numpy as np
import torch
import torchaudio
from hs_tasnet import HSTasNet
import struct
import logging
import time
import threading
import queue
from torchcodec.decoders import AudioDecoder

# Set up logging to stderr (stdout is for audio)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

def parse_arguments():
    """Parse command line arguments for volume controls and chunk size."""
    parser = argparse.ArgumentParser(description='Real-time audio stem separation')
    
    # Chunk size in seconds
    parser.add_argument('--chunk-size', type=float, default=2.0,
                        help='Chunk size in seconds (default: 2.0)')
    
    # Volume controls for each stem (0-100, where 100 is unchanged)
    parser.add_argument('--drums-volume', type=int, default=100,
                        help='Drums volume 0-100 (default: 100)')
    parser.add_argument('--bass-volume', type=int, default=100,
                        help='Bass volume 0-100 (default: 100)')
    parser.add_argument('--vocals-volume', type=int, default=100,
                        help='Vocals volume 0-100 (default: 100)')
    parser.add_argument('--other-volume', type=int, default=100,
                        help='Other instruments volume 0-100 (default: 100)')
    
    # Device selection
    parser.add_argument('--device', type=str, default='cuda' if torch.cuda.is_available() else 'cpu',
                        help='Device to use (cuda/cpu)')
    
    return parser.parse_args()

def get_audio_format_from_env():
    """Get audio format from PulseAudio Lambda environment variables."""
    sample_rate = int(os.environ.get('PA_LAMBDA_SAMPLE_RATE', '44100'))
    channels = int(os.environ.get('PA_LAMBDA_CHANNELS', '2'))
    bits = int(os.environ.get('PA_LAMBDA_BITS', '16'))
    
    return sample_rate, channels, bits

def read_audio_chunk(chunk_samples, channels, bits):
    """Read a chunk of audio from stdin and convert to torch tensor format."""
    bytes_per_sample = bits // 8
    bytes_per_frame = channels * bytes_per_sample
    chunk_bytes = chunk_samples * bytes_per_frame
    
    logging.debug(f"Attempting to read {chunk_bytes} bytes ({chunk_samples} samples)")
    
    try:
        data = sys.stdin.buffer.read(chunk_bytes)
        logging.debug(f"Read {len(data) if data else 0} bytes")
        if not data:
            return None
            
        # Handle partial reads - pad with zeros if needed
        if len(data) < chunk_bytes:
            data += b'\x00' * (chunk_bytes - len(data))
            
        # Convert bytes to numpy array based on bit depth
        if bits == 16:
            dtype = np.int16
            format_char = 'h'
        elif bits == 32:
            dtype = np.int32
            format_char = 'i'
        else:
            raise ValueError(f"Unsupported bit depth: {bits}")
            
        # Unpack bytes to samples
        num_samples = len(data) // bytes_per_sample
        samples = struct.unpack(f'<{num_samples}{format_char}', data)
        audio_np = np.array(samples, dtype=dtype)
        
        # Reshape to (channels, samples) - torchcodec/torchaudio format
        if channels == 2:
            # Interleaved stereo: L R L R -> [[L L], [R R]]
            audio_np = audio_np.reshape(-1, channels).T
        else:
            audio_np = audio_np.reshape(1, -1)
            
        # Normalize to [-1, 1] and convert to torch tensor (proper format)
        max_val = 2**(bits-1)
        audio_float = audio_np.astype(np.float32) / max_val
        audio_tensor = torch.from_numpy(audio_float)
        
        return audio_tensor
        
    except Exception as e:
        logging.error(f"Error reading audio chunk: {e}")
        return None

def queue_audio_chunk(audio_tensor, channels, bits, audio_queue):
    """Convert processed audio tensor to bytes and queue for output."""
    logging.debug(f"queue_audio_chunk input shape: {audio_tensor.shape}")
    
    # Ensure tensor is on CPU and in correct format
    if audio_tensor.is_cuda:
        audio_tensor = audio_tensor.cpu()
    
    # Remove batch dimension if present
    if audio_tensor.ndim == 3:
        audio_tensor = audio_tensor[0]
    
    # Ensure we have the right number of channels
    if audio_tensor.shape[0] != channels:
        raise ValueError(f"Wrong number of channels in output: {audio_tensor.shape[0]}")

    # Ensure audio is properly bounded and convert to correct format
    audio_clamped = torch.clamp(audio_tensor, -1.0, 1.0)
    
    # Convert to integer format using proper audio quantization
    if bits == 16:
        # Convert to 16-bit PCM using torchaudio's proper quantization
        audio_int = (audio_clamped * 32767).round().to(torch.int16).numpy()
    elif bits == 32:
        audio_int = (audio_clamped * 2147483647).round().to(torch.int32).numpy()
    else:
        raise ValueError(f"Unsupported bit depth: {bits}")
    
    logging.debug(f"Converted audio range: [{audio_int.min()}, {audio_int.max()}]")
    
    # Convert to buffer-sized chunks and queue them
    buffer_size = int(os.environ.get('PA_LAMBDA_BUFFER_SIZE', '1024'))
    samples_per_buffer = buffer_size # 1024 samples per buffer
    total_samples = audio_int.shape[-1]
    format_char = 'h' if bits == 16 else 'i'
    
    logging.debug(f"Queueing {total_samples} samples in {samples_per_buffer}-sample buffers")
    
    for start_sample in range(0, total_samples, samples_per_buffer):
        end_sample = min(start_sample + samples_per_buffer, total_samples)
        
        # Extract buffer-sized chunk
        if channels == 2 and audio_int.shape[0] == 2:
            # [[L L], [R R]] -> get samples [start:end] -> interleave to [L R L R]
            chunk = audio_int[:, start_sample:end_sample].T.flatten()
        else:
            chunk = audio_int[start_sample:end_sample]
        
        # Pack only this small chunk and queue it
        chunk_data = struct.pack(f'<{len(chunk)}{format_char}', *chunk)
        audio_queue.put(chunk_data)
    
    logging.debug(f"Finished queueing {total_samples} samples")

def audio_output_thread(audio_queue, sample_rate):
    """Output thread that writes queued audio at regular intervals."""
    buffer_size = int(os.environ.get('PA_LAMBDA_BUFFER_SIZE', '1024'))
    buffer_duration = buffer_size / sample_rate  # 23.2ms for 1024 samples at 44.1kHz
    
    logging.info(f"Output thread starting - {buffer_duration*1000:.1f}ms per buffer")
    
    try:
        while True:
            try:
                # Get next buffer from queue (timeout to handle shutdown)
                chunk_data = audio_queue.get(timeout=1.0)
                
                # Write to stdout
                sys.stdout.buffer.write(chunk_data)
                sys.stdout.buffer.flush()
                
                # Rate limit to match PulseAudio's expected timing
                #time.sleep(buffer_duration)
                
            except queue.Empty:
                # Check if we should continue (main thread sets a flag)
                continue
                
    except Exception as e:
        logging.error(f"Output thread error: {e}")
    
    logging.info("Output thread stopping")

def apply_volume(tensor, volume_percent):
    """Apply volume scaling to audio tensor using torchaudio."""
    if volume_percent == 0:
        return torch.zeros_like(tensor)
    elif volume_percent == 100:
        return tensor
    else:
        # Use proper audio gain with dB conversion for better quality
        gain_db = 20 * np.log10(volume_percent / 100.0) if volume_percent > 0 else -60
        return torchaudio.functional.gain(tensor, gain_db)

def process_chunk(model, audio_tensor, args, device):
    """Process a single audio chunk through the model."""
    # Add batch dimension and move to device
    audio_batch = audio_tensor.unsqueeze(0).to(device)
    
    # Ensure stereo input for model (duplicate mono if needed)
    if audio_batch.shape[1] == 1:
        audio_batch = audio_batch.repeat(1, 2, 1)
    
    logging.debug(f"Input tensor shape: {audio_batch.shape}")
    
    # Run separation model
    with torch.no_grad():
        separated_audios, _ = model(audio_batch)
    
    logging.debug(f"Separated output shape: {separated_audios.shape}")
    logging.debug(f"Separated output type: {separated_audios.dtype}")
    
    # Extract stems: (batch, 4, channels, samples)
    drums = separated_audios[:, 0, :, :]
    bass = separated_audios[:, 1, :, :] # swapped?
    vocals = separated_audios[:, 2, :, :] # swapped?
    other = separated_audios[:, 3, :, :]
    
    # Apply volume controls using proper audio gain
    drums = apply_volume(drums, args.drums_volume)
    bass = apply_volume(bass, args.bass_volume)
    vocals = apply_volume(vocals, args.vocals_volume)
    other = apply_volume(other, args.other_volume)
    
    # Mix stems back together with proper audio mixing (sum and normalize)
    mixed = drums + bass + vocals + other

    # Normalize mixed audio to prevent clipping artifacts
    # Find peak and scale if needed
    peak = torch.max(torch.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak
        logging.debug(f"Normalized mixed audio by factor {peak:.3f}")
    
    logging.debug(f"Mixed peak level: {torch.max(torch.abs(mixed)):.3f}")
    
    logging.debug(f"Mixed output shape: {mixed.shape}")
    logging.debug(f"Mixed output samples: {mixed.shape[-1] if len(mixed.shape) > 0 else 0}")
    return mixed

def main():
    """Main processing loop."""
    args = parse_arguments()
    logging.debug(f"Arguments: chunk_size={args.chunk_size}, drums_volume={args.drums_volume}")
    
    # Get audio format from environment
    sample_rate, channels, bits = get_audio_format_from_env()
    chunk_samples = int(args.chunk_size * sample_rate)
    
    logging.info(f"Audio format: {sample_rate}Hz, {channels} channels, {bits} bits")
    logging.info(f"Chunk size: {args.chunk_size}s ({chunk_samples} samples)")
    logging.info(f"Volume settings - Drums: {args.drums_volume}%, Bass: {args.bass_volume}%, "
                 f"Vocals: {args.vocals_volume}%, Other: {args.other_volume}%")
    
    # Set up device
    device = torch.device(args.device)
    logging.info(f"Using device: {device}")
    
    # Load model
    logging.info("Loading HS-TasNet model...")
    # TODO: Tweak parameters
    model = HSTasNet(sample_rate=sample_rate).to(device)
    logging.info("Model loaded successfully")
    
    # Use binary stdin/stdout for real-time processing
    # Note: sys.stdin.buffer and sys.stdout.buffer are already BufferedReader/Writer
    
    # Set up audio output queue and thread
    audio_queue = queue.Queue(maxsize=100)  # Buffer up to 100 audio chunks
    output_thread = threading.Thread(target=audio_output_thread, args=(audio_queue, sample_rate), daemon=True)
    output_thread.start()
    
    # Processing loop
    logging.info("Starting audio processing...")
    
    try:
        while True:
            # Read chunk from stdin
            audio_tensor = read_audio_chunk(chunk_samples, channels, bits)
            if audio_tensor is None:
                break
            
            logging.debug("Starting model processing...")
            # Process through model
            processed = process_chunk(model, audio_tensor, args, device)
            logging.debug("Model processing complete, queueing output...")
            
            # Queue processed audio for output thread
            queue_audio_chunk(processed, channels, bits, audio_queue)
            logging.debug("Output queued, continuing loop...")
            
    except BrokenPipeError:
        # Clean shutdown when pipeline closes
        logging.info("Pipeline closed, shutting down")
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
    except Exception as e:
        logging.error(f"Processing error: {e}")
        sys.exit(1)
    
    logging.info("Processing complete")

if __name__ == "__main__":
    main()
