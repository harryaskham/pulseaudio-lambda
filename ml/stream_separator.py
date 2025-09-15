#!/usr/bin/env python3
"""
Real-time audio stem separation using HS-TasNet.
Reads audio from stdin, processes in chunks, applies volume controls, and outputs to stdout.
Compatible with PulseAudio Lambda bridge.
"""

from typing import List
import dataclasses
import datetime
import pathlib
import json
import sys
import os
import argparse
import torch
import struct
import logging
import time
import threading
import queue

from buffer_hs_tasnet import BufferHSTasNet, SampleSpec

# Set up logging to stderr (stdout is for audio)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

@dataclasses.dataclass
class Args:
    checkpoint: str
    chunk_secs: float
    gains: List[str]
    device: str

    @classmethod
    def combined(cls):
        """Parse command line arguments for volume controls and chunk size."""
        parser = argparse.ArgumentParser(description='Real-time audio stem separation')

        # Config JSON file
        # Overridden temporarily by any provided command line args
        # Defaults to the env variable $PA_LAMBDA_CONFIG_DIR or ~/.config/pulseaudio-lambda if not set
        parser.add_argument('--config-dir', type=str, help='Path to config dir')

        # Checkpoint
        parser.add_argument('--save-config', action='store_true',
                            help='If set, persist the current settings combination')

        # Checkpoint
        parser.add_argument('--checkpoint', type=str,
                            help='Path to model checkpoint')

        # Chunk size in seconds
        parser.add_argument('--chunk-secs', type=float,
                            help='Chunk size in seconds')

        # Volume controls for each stem or m to mute
        parser.add_argument('--gains', type=str,
                            help='Stem gain change for drums,bass,vocals,other (e.g. 50,m,100,m to mute bass and other, with half volume drums and full volume vocals)')

        # Device selection
        parser.add_argument('--device', type=str,
                            help='Device to use (cuda/cpu)')

        args = parser.parse_args()
        logging.debug(f"CLI args: {args}")

        # Defaults to the env variable $PA_LAMBDA_CONFIG_DIR or ~/.config/pulseaudio-lambda if not set
        config_dir = (
            args.config_dir if args.config_dir is not None
            else os.environ.get('PA_LAMBDA_CONFIG_DIR',
                                os.path.expanduser("~/.config/pulseaudio-lambda")))
        logging.debug(f"Using config dir: {config_dir}")
        pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
        config_json_path = os.path.join(config_dir, "stream_separator_config.json")
        config_args = {}
        if os.path.exists(config_json_path):
            with open(config_json_path, 'r') as f:
                config_args = Args(**(json.load(f)))
        logging.debug(f"Loaded config args: {config_args}")

        gains = (
            [ 0.0 if x.strip() == "m" else float(x.strip())
              for x in args.gains.split(",") ]
            if args.gains is not None
            else config_args.gains)
        checkpoint = (
            os.path.expandvars(
                os.path.expanduser(
                    args.checkpoint
                    if args.checkpoint is not None
                    else config_args.checkpoint)))

        combined = cls(
            gains=gains,
            checkpoint=checkpoint,
            chunk_secs=args.chunk_secs if args.chunk_secs is not None else config_args.chunk_secs,
            device=args.device if args.device is not None else config_args.device
        )
        logging.debug(f"Combined config/CLI args: {combined}")

        if args.save_config:
            with open(config_json_path, 'w') as f:
                json.dump(dataclasses.asdict(combined), f, indent=4)
            logging.info(f"Saved config to {config_json_path}")

        return combined


def queue_audio_chunk(audio_tensor, channels, bits, audio_queue):
    """Convert processed audio tensor to bytes and queue for output."""
    logging.debug(f"queue_audio_chunk input shape: {audio_tensor.shape}")
    
    # Ensure tensor is on CPU and in correct format
    if audio_tensor.is_cuda:
        audio_tensor = audio_tensor.cpu()
    
    ## Remove batch dimension if present
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

def audio_input_thread(input_queue, sample_spec, chunk_secs):
    try:
        while True:
            # Read chunk from stdin
            num_samples = chunk_secs * sample_spec.sample_rate
            audio_tensor = sample_spec.read_chunk(sys.stdin.buffer, num_samples)
            if audio_tensor is None:
                break
            input_queue.put(audio_tensor)

    except Exception as e:
        logging.error(f"Processing error: {e}")
        sys.exit(1)

def audio_inference_thread(input_queue, output_queue, checkpoint, sample_spec, device, gains):
    # Set up device
    device = torch.device(device)
    logging.info(f"Using device: {device}")

    # Load model
    logging.info("Loading HS-TasNet model...")
    model = BufferHSTasNet(sample_spec).to(device)
    model.load(checkpoint)
    logging.info(f"Checkpoint {checkpoint} loaded successfully")

    while True:
        audio_tensor = input_queue.get()

        logging.debug("Starting model processing...")
        processed = process_audio_tensor(model, audio_tensor, gains)
        logging.debug("Model processing complete, queueing output...")

        # Queue processed audio for output thread
        queue_audio_chunk(processed, sample_spec.channels, sample_spec.bits, output_queue)
        logging.debug("Output queued, continuing loop...")

def audio_output_thread(output_queue, sample_spec):
    """Output thread that writes queued audio at regular intervals."""
    buffer_size = int(os.environ.get('PA_LAMBDA_BUFFER_SIZE', '1024'))
    buffer_duration = buffer_size / sample_spec.sample_rate  # 23.2ms for 1024 samples at 44.1kHz
    
    logging.info(f"Output thread starting - {buffer_duration*1000:.1f}ms per buffer")
    
    try:
        while True:
            try:
                chunk_data = output_queue.get()
                
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

def apply_gain(tensor, gain_db):
    """Apply volume scaling to audio tensor using torchaudio."""
    # TODO: move back to percent naming
    return tensor * (gain_db / 100.0)
    #return torchaudio.functional.gain(tensor, gain_db)

def log_stem_range(stems, names, label):
    for name, stem in zip(names, stems):
        logging.debug(f"{name} range {label}: [{stem.min().item():.3f}, {stem.max().item():.3f}]")

def log_stem_ranges(drums, bass, vocals, other, label):
    log_stem_range([drums, bass, vocals, other], ["Drums", "Bass", "Vocals", "Others"], label)

def process_audio_tensor(model, audio_tensor, gains):
    """Process a single audio chunk through the model."""
    separated_audios = model.process_audio_tensor(audio_tensor)

    logging.debug(f"Separated output shape: {separated_audios.shape}")
    logging.debug(f"Separated output type: {separated_audios.dtype}")
    
    # Extract stems: (batch, 4, channels, samples)
    drums = separated_audios[0, :, :]
    bass = separated_audios[1, :, :] # swapped?
    vocals = separated_audios[2, :, :] # swapped?
    other = separated_audios[3, :, :]
    
    # Apply volume controls using proper audio gain
    logging.debug(f"Applying gain transform: {gains}")
    log_stem_ranges(drums, bass, vocals, other, "before")
    drums = apply_gain(drums, gains[0])
    bass = apply_gain(bass, gains[1])
    vocals = apply_gain(vocals, gains[2])
    other = apply_gain(other, gains[3])
    log_stem_ranges(drums, bass, vocals, other, "after")
    
    # Mix stems back together with proper audio mixing (sum and normalize)
    mixed = drums + bass + vocals + other

    # Normalize mixed audio to prevent clipping artifacts
    # Find peak and scale if needed
    # peak = torch.max(torch.abs(mixed))
    # if peak > 1.0:
    #     mixed = mixed / peak
    #     logging.debug(f"Normalized mixed audio by factor {peak:.3f}")
    
    logging.debug(f"Mixed peak level: {torch.max(torch.abs(mixed)):.3f}")
    
    logging.debug(f"Mixed output shape: {mixed.shape}")
    logging.debug(f"Mixed output samples: {mixed.shape[-1] if len(mixed.shape) > 0 else 0}")
    return mixed

def main():
    """Main processing loop."""
    args = Args.combined()

    checkpoint = args.checkpoint
    sample_spec = SampleSpec.from_env()
    device = args.device

    # Set up audio output queue and thread
    input_queue = queue.Queue(maxsize=100)
    output_queue = queue.Queue(maxsize=100)

    input_thread = threading.Thread(target=audio_input_thread, args=(input_queue, sample_spec, int(args.chunk_secs)))
    inference_thread = threading.Thread(target=audio_inference_thread, args=(input_queue, output_queue, checkpoint, sample_spec, args.device, args.gains))
    output_thread = threading.Thread(target=audio_output_thread, args=(output_queue, sample_spec))

    time.sleep(datetime.datetime.now().microsecond / 1_000_000)  # Align to next second boundary
    input_thread.start()
    inference_thread.start()
    output_thread.start()
    
    # Processing loop
    logging.info("Starting audio processing...")
    
    try:
        input_thread.join()
        inference_thread.join()
        output_thread.join()
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
