#!/usr/bin/env python3
"""
Optimized real-time audio stem separation with overlapping windows and buffering.
Reduces artifacts at chunk boundaries.
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
from collections import deque
import threading
import queue

# Set up logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

class AudioStreamProcessor:
    """Handles buffered audio processing with overlapping windows."""
    
    def __init__(self, model, sample_rate, channels, bits, chunk_size, overlap=0.5, device='cuda'):
        self.model = model
        self.sample_rate = sample_rate
        self.channels = channels
        self.bits = bits
        self.device = device
        
        # Calculate chunk parameters
        self.chunk_samples = int(chunk_size * sample_rate)
        self.overlap_samples = int(self.chunk_samples * overlap)
        self.hop_samples = self.chunk_samples - self.overlap_samples
        
        # Buffers for overlapping windows
        self.input_buffer = deque(maxlen=self.chunk_samples)
        self.output_buffer = deque()
        self.crossfade_buffer = np.zeros((channels, self.overlap_samples))
        
        # Initialize input buffer with zeros
        zeros = np.zeros((channels, self.chunk_samples))
        for i in range(self.chunk_samples):
            self.input_buffer.append(zeros[:, i:i+1])
        
        logging.info(f"Initialized processor - chunk: {self.chunk_samples}, overlap: {self.overlap_samples}, hop: {self.hop_samples}")
    
    def read_samples(self, num_samples):
        """Read samples from stdin."""
        bytes_per_sample = self.bits // 8
        bytes_per_frame = self.channels * bytes_per_sample
        bytes_to_read = num_samples * bytes_per_frame
        
        try:
            data = sys.stdin.buffer.read(bytes_to_read)
            if not data:
                return None
            
            # Handle partial reads
            actual_samples = len(data) // bytes_per_frame
            if actual_samples < num_samples:
                # Pad with zeros
                data += b'\x00' * ((num_samples - actual_samples) * bytes_per_frame)
            
            # Convert to numpy
            format_char = 'h' if self.bits == 16 else 'i'
            samples = struct.unpack(f'<{num_samples * self.channels}{format_char}', data)
            audio_np = np.array(samples, dtype=np.int16 if self.bits == 16 else np.int32)
            
            # Reshape and normalize
            if self.channels == 2:
                audio_np = audio_np.reshape(-1, self.channels).T
            else:
                audio_np = audio_np.reshape(1, -1)
            
            max_val = 2**(self.bits-1)
            audio_float = audio_np.astype(np.float32) / max_val
            
            return audio_float
            
        except Exception as e:
            logging.error(f"Error reading samples: {e}")
            return None
    
    def write_samples(self, audio_np):
        """Write samples to stdout."""
        # Clip and convert to int
        audio_np = np.clip(audio_np, -1.0, 1.0)
        max_val = 2**(self.bits-1) - 1
        audio_int = (audio_np * max_val).astype(np.int16 if self.bits == 16 else np.int32)
        
        # Interleave channels
        if self.channels == 2 and audio_int.shape[0] == 2:
            audio_int = audio_int.T.flatten()
        else:
            audio_int = audio_int.flatten()
        
        # Pack and write
        format_char = 'h' if self.bits == 16 else 'i'
        data = struct.pack(f'<{len(audio_int)}{format_char}', *audio_int)
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    
    def process_chunk(self, chunk_array, volumes):
        """Process a chunk through the model."""
        # Convert to tensor
        audio_tensor = torch.from_numpy(chunk_array).unsqueeze(0).to(self.device)
        
        # Ensure stereo for model
        if audio_tensor.shape[1] == 1:
            audio_tensor = audio_tensor.repeat(1, 2, 1)
        
        # Run model
        with torch.no_grad():
            separated_audios, _ = self.model(audio_tensor)
        
        # Apply volumes and mix
        mixed = torch.zeros_like(audio_tensor)
        for i, vol in enumerate(volumes):
            mixed += separated_audios[:, i, :, :] * (vol / 100.0)
        
        return mixed[0].cpu().numpy()
    
    def apply_window(self, audio, window_type='hann'):
        """Apply window function for smooth crossfading."""
        window = np.hanning(audio.shape[-1])
        return audio * window
    
    def crossfade(self, prev_chunk, curr_chunk):
        """Crossfade between overlapping chunks."""
        fade_len = self.overlap_samples
        
        # Create fade curves
        fade_out = np.linspace(1, 0, fade_len)
        fade_in = np.linspace(0, 1, fade_len)
        
        # Apply crossfade
        result = np.copy(curr_chunk)
        if prev_chunk is not None:
            for ch in range(self.channels):
                result[ch, :fade_len] = (prev_chunk[ch, -fade_len:] * fade_out + 
                                         curr_chunk[ch, :fade_len] * fade_in)
        
        return result
    
    def process_stream(self, volumes):
        """Main processing loop with overlapping windows."""
        prev_output = None
        
        while True:
            # Read hop_samples of new audio
            new_audio = self.read_samples(self.hop_samples)
            if new_audio is None:
                break
            
            # Update input buffer
            for i in range(self.hop_samples):
                self.input_buffer.append(new_audio[:, i:i+1])
            
            # Get current chunk from buffer
            chunk = np.hstack(list(self.input_buffer))
            
            # Process chunk
            processed = self.process_chunk(chunk, volumes)
            
            # Apply crossfade with previous output
            if prev_output is not None:
                processed = self.crossfade(prev_output, processed)
            
            # Output the non-overlapping portion
            if prev_output is not None:
                self.write_samples(processed[:, :self.hop_samples])
            else:
                # First chunk - output everything
                self.write_samples(processed)
            
            prev_output = processed

def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description='Optimized real-time stem separation')
    
    parser.add_argument('--chunk-size', type=float, default=2.0,
                        help='Chunk size in seconds')
    parser.add_argument('--overlap', type=float, default=0.25,
                        help='Overlap ratio (0.0-0.5)')
    parser.add_argument('--drums-volume', type=int, default=100)
    parser.add_argument('--bass-volume', type=int, default=100)
    parser.add_argument('--vocals-volume', type=int, default=100)
    parser.add_argument('--other-volume', type=int, default=100)
    parser.add_argument('--device', type=str, default='cuda' if torch.cuda.is_available() else 'cpu')
    
    return parser.parse_args()

def main():
    """Main entry point."""
    args = parse_arguments()
    
    # Get audio format
    sample_rate = int(os.environ.get('PA_LAMBDA_SAMPLE_RATE', '44100'))
    channels = int(os.environ.get('PA_LAMBDA_CHANNELS', '2'))
    bits = int(os.environ.get('PA_LAMBDA_BITS', '16'))
    
    logging.info(f"Audio: {sample_rate}Hz, {channels}ch, {bits}bit")
    logging.info(f"Volumes - D:{args.drums_volume} B:{args.bass_volume} V:{args.vocals_volume} O:{args.other_volume}")
    
    # Load model
    device = torch.device(args.device)
    logging.info(f"Loading model on {device}...")
    model = HSTasNet().to(device)
    model.eval()
    
    # Create processor
    processor = AudioStreamProcessor(
        model, sample_rate, channels, bits,
        args.chunk_size, args.overlap, device
    )
    
    # Process audio
    volumes = [args.drums_volume, args.bass_volume, args.vocals_volume, args.other_volume]
    
    try:
        processor.process_stream(volumes)
    except BrokenPipeError:
        logging.info("Pipeline closed")
    except KeyboardInterrupt:
        logging.info("Interrupted")
    except Exception as e:
        logging.error(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()