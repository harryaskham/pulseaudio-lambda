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
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from buffer_hs_tasnet import BufferHSTasNet, SampleSpec

_args = None  # Global to hold parsed args
_args_lock = threading.Lock()

def expand_path(path):
    return os.path.expandvars(os.path.expanduser(path))

def refresh_args():
    global _args
    with _args_lock:
        try:
            _args = Args.combined(first_load=False, silent=True)
            logging.debug("Refreshed args")
        except Exception as e:
            logging.error(f"Error refreshing args: {e}")
        return _args

class ArgsEventHandler(FileSystemEventHandler):
    def refresh(self, event):
        args = get_args()
        if event.src_path == expand_path(args.config_path):
            args = refresh_args()
            logging.info("Reloaded config after change: %s", args)

    def on_modified(self, event):
        super().on_modified(event)
        self.refresh(event)

    def on_moved(self, event):
        super().on_moved(event)
        self.refresh(event)

def get_args():
    global _args
    with _args_lock:
        if _args is None:
            _args = Args.combined(first_load=True, silent=False)
        return _args

@dataclasses.dataclass
class Args:
    checkpoint: str
    chunk_secs: float
    overlap_secs: float
    gains: List[float]
    muted: List[bool]
    soloed: List[bool]
    normalize: bool
    device: str
    watch: bool = False

    config_dir: str = dataclasses.field(default=None, repr=False, compare=False)
    config_path: str = dataclasses.field(default=None, repr=False, compare=False)

    def get_effective_gains(self) -> List[float]:
        """Get the actual gains to apply, considering mute/solo state."""
        effective_gains = []
        any_soloed = any(self.soloed)

        for i in range(len(self.gains)):
            if self.muted[i]:
                # Muted stems get 0 gain
                effective_gains.append(0.0)
            elif any_soloed and not self.soloed[i]:
                # If any stems are soloed and this one isn't, mute it
                effective_gains.append(0.0)
            else:
                # Use the configured gain
                effective_gains.append(self.gains[i])

        return effective_gains

    @classmethod
    def combined(cls, first_load, silent):
        """Parse command line arguments for volume controls and chunk size."""

        def maybe_debug(*args, **kwargs):
            if not silent:
                logging.debug(*args, **kwargs)

        parser = argparse.ArgumentParser(description='Real-time audio stem separation')

        parser.add_argument('--debug', action='store_true',
                            help='Enable debug logging')

        # Config JSON file
        # Overridden temporarily by any provided command line args
        # Defaults to the env variable $PA_LAMBDA_CONFIG_DIR or ~/.config/pulseaudio-lambda if not set
        parser.add_argument('--config-dir', type=str, help='Path to config dir')

        parser.add_argument('--save-config', action='store_true',
                            help='If set, persist the current settings combination')

        parser.add_argument('--watch', action='store_true',
                            help='If set, watch the config file for changes and reload dynamically')

        # Checkpoint
        parser.add_argument('--checkpoint', type=str,
                            help='Path to model checkpoint')

        # Chunk size in seconds
        parser.add_argument('--chunk-secs', type=float,
                            help='Chunk size in seconds')

        # Overlap size in seconds
        parser.add_argument('--overlap-secs', type=float,
                            help='Overlap size in seconds')

        # Volume controls for each stem or m to mute
        parser.add_argument('--gains', type=str,
                            help='Stem gain change for drums,bass,vocals,other (e.g. 50,m,100,m to mute bass and other, with half volume drums and full volume vocals)')

        # Normalization
        parser.add_argument('--normalize', action='store_true',
                            help='Normalize output volume to match input intensity after applying gains')

        # Device selection
        parser.add_argument('--device', type=str,
                            help='Device to use (cuda/cpu)')

        args = parser.parse_args()

        # Set up logging to stderr (stdout is for audio)
        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            stream=sys.stderr
        )

        maybe_debug(f"CLI args: {args}")

        # Defaults to the env variable $PA_LAMBDA_CONFIG_DIR or ~/.config/pulseaudio-lambda if not set
        config_dir = (
            args.config_dir if args.config_dir is not None
            else os.environ.get('PA_LAMBDA_CONFIG_DIR',
                                expand_path("~/.config/pulseaudio-lambda")))
        maybe_debug(f"Using config dir: {config_dir}")
        pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
        config_json_path = os.path.join(config_dir, "stream_separator_config.json")
        config_args = {}
        if os.path.exists(config_json_path):
            with open(config_json_path, 'r') as f:
                config_args = Args(
                    config_dir=config_dir,
                    config_path=config_json_path,
                    **(json.load(f)))
        maybe_debug(f"Loaded config args: {config_args}")

        gains = (
            [ 0.0 if x.strip() == "m" else float(x.strip())
              for x in args.gains.split(",") ]
            if args.gains is not None
            else config_args.gains)
        muted = (
            [ x.strip() == "m" for x in args.gains.split(",") ]
            if args.gains is not None
            else config_args.muted)
        soloed = (
            [ x.strip() == "s" for x in args.gains.split(",") ]
            if args.gains is not None
            else config_args.soloed)

        combined = cls(
            gains=gains,
            muted=muted,
            soloed=soloed,
            checkpoint=args.checkpoint if args.checkpoint is not None else config_args.checkpoint,
            chunk_secs=args.chunk_secs if args.chunk_secs is not None else config_args.chunk_secs,
            overlap_secs=args.overlap_secs if args.overlap_secs is not None else config_args.overlap_secs,
            device=args.device if args.device is not None else config_args.device,
            watch=args.watch or config_args.watch,
            normalize=args.normalize or config_args.normalize,
            config_dir=config_dir,
            config_path=config_json_path
        )
        maybe_debug(f"Combined config/CLI args: {combined}")

        if args.save_config and first_load:
            with open(config_json_path, 'w') as f:
                json.dump(dataclasses.asdict(combined), f, indent=4)
            logging.info(f"Saved config to {config_json_path}")

        return combined

@dataclasses.dataclass
class Chunk:
    sample_spec: SampleSpec
    remove_overlap_start: float
    remove_overlap_end: float
    input_audio_tensor: torch.Tensor
    processed_audio_tensor: torch.Tensor | None = None
    truncated_audio_tensor: torch.Tensor | None = None
    gains_applied: List[float] | None = None

    received_at: datetime.datetime = dataclasses.field(default_factory=datetime.datetime.now, init=False)
    processing_started_at: datetime.datetime = None
    processing_completed_at: datetime.datetime = None
    output_started_at: datetime.datetime = None
    output_completed_at: datetime.datetime = None

    @property
    def processed_duration_secs(self):
        return self.sample_spec.samples_to_secs(self.processed_audio_tensor.shape[-1])

    @property
    def truncated_duration_secs(self):
        return self.sample_spec.samples_to_secs(self.truncated_audio_tensor.shape[-1])

    @property
    def latency_secs(self):
        if self.output_completed_at is None:
            return None
        return (self.output_completed_at - self.received_at).total_seconds()

    def log_timing(self):
        logging.debug(f"Chunk timing: received at {self.received_at}, "
                      f"processing started at {self.processing_started_at}, "
                      f"processing completed at {self.processing_completed_at}, "
                      f"output started at {self.output_started_at}, "
                      f"output completed at {self.output_completed_at}")
        logging.info(f"Chunk completed: gains {self.gains_applied}, processed {self.processed_duration_secs:.2f} s / truncated {self.truncated_duration_secs:.2f}, latency {self.latency_secs:.1f} s")

def audio_input_thread(input_queue, sample_spec):
    try:
        last_input_audio_tensor = None
        while True:
            args = get_args()

            # Read chunk from stdin
            num_bytes = sample_spec.secs_to_bytes(args.chunk_secs + args.overlap_secs)
            input_audio_tensor = sample_spec.read_chunk(sys.stdin.buffer, num_bytes)
            if input_audio_tensor is None:
                break

            # If not the first chunk, add the overlap from the end of the last chunk
            # This avoids the artefacts and popping we get at the edges of chunks
            # We drop these segments after processing before output
            remove_overlap_start = 0.0
            remove_overlap_end = args.overlap_secs
            if last_input_audio_tensor is not None and args.overlap_secs > 0:
                remove_overlap_start = args.overlap_secs
                overlap_samples_per_channel = sample_spec.secs_to_samples(args.overlap_secs)
                overlap_segment = last_input_audio_tensor[:, -overlap_samples_per_channel:]
                logging.debug(f"Before overlap: {input_audio_tensor.shape}")
                input_audio_tensor = torch.cat((overlap_segment, input_audio_tensor), dim=-1)
                logging.debug(f"Added overlap of {overlap_samples_per_channel} samples from last chunk")
            last_input_audio_tensor = input_audio_tensor

            input_queue.put(
                Chunk(sample_spec=sample_spec,
                      input_audio_tensor=input_audio_tensor,
                      remove_overlap_start=remove_overlap_start,
                      remove_overlap_end=remove_overlap_end))

    except Exception as e:
        logging.error(f"Processing error: {e}")
        sys.exit(1)

def audio_inference_thread(input_queue, output_queue, checkpoint, sample_spec):
    init_args = get_args()

    # Set up device
    device = torch.device(init_args.device)
    logging.info(f"Using device: {device}")

    # Load model
    logging.info("Loading HS-TasNet model...")
    model = BufferHSTasNet(sample_spec).to(device)
    checkpoint_path = expand_path(checkpoint)
    model.load(checkpoint_path)
    logging.info(f"Checkpoint {checkpoint_path} loaded successfully")

    while True:
        args = get_args()
        chunk = input_queue.get()

        logging.debug("Starting model processing...")
        process_chunk(args, model, chunk)
        logging.debug("Model processing complete, queueing output...")

        # Queue processed audio for output thread
        # We queue this up in frames of the PA buffer size
        # TODO: move this work out of the inference thread
        queue_output_chunk(chunk, sample_spec.channels, sample_spec.bits, output_queue)
        logging.debug("Output queued, continuing loop...")

def audio_output_thread(output_queue, sample_spec):
    """Output thread that writes queued audio at regular intervals."""
    buffer_size = int(os.environ.get('PA_LAMBDA_BUFFER_SIZE', '1024'))
    buffer_duration = buffer_size / sample_spec.sample_rate  # 23.2ms for 1024 samples at 44.1kHz
    
    logging.info(f"Output thread starting - {buffer_duration*1000:.1f}ms per buffer")
    
    try:
        while True:
            try:
                chunk_or_data = output_queue.get()
                if isinstance(chunk_or_data, Chunk):
                    logging.debug("Chunk completed")
                    chunk_or_data.output_completed_at = datetime.datetime.now()
                    chunk_or_data.log_timing()
                    continue

                # Write to stdout
                sys.stdout.buffer.write(chunk_or_data)
                sys.stdout.buffer.flush()
                
                # Rate limit to match PulseAudio's expected timing
                #time.sleep(buffer_duration)
                
            except queue.Empty:
                # Check if we should continue (main thread sets a flag)
                continue
                
    except Exception as e:
        logging.error(f"Output thread error: {e}")
    
    logging.info("Output thread stopping")

def queue_output_chunk(chunk, channels, bits, output_queue):
    """Convert processed audio tensor to bytes and queue for output."""
    chunk.output_started_at = datetime.datetime.now()
    audio_tensor = chunk.truncated_audio_tensor
    logging.debug(f"queue_output_chunk input shape: {audio_tensor.shape}")

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
            segment = audio_int[:, start_sample:end_sample].T.flatten()
        else:
            segment = audio_int[start_sample:end_sample]

        # Pack only this small chunk and queue it
        segment_data = struct.pack(f'<{len(segment)}{format_char}', *segment)
        output_queue.put(segment_data)

    output_queue.put(chunk)  # Indicate chunk is fully queued

    logging.debug(f"Finished queueing {total_samples} samples")


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

def process_chunk(args, model, chunk):
    """Process a single audio chunk through the model."""
    chunk.processing_started_at = datetime.datetime.now()

    chunk.processed_audio_tensor = model.process_audio_tensor(chunk.input_audio_tensor)
    separated_audios = chunk.processed_audio_tensor
    logging.debug(f"Got processed stems: {separated_audios.shape}")

    # Drop the overlap segment at the start and end if present
    if chunk.remove_overlap_start + chunk.remove_overlap_end > 0:
        overlap_samples_start = chunk.sample_spec.secs_to_samples_1ch(chunk.remove_overlap_start)
        overlap_samples_end = chunk.sample_spec.secs_to_samples_1ch(chunk.remove_overlap_end)
        separated_audios = separated_audios[:, :, overlap_samples_start:-overlap_samples_end]
        logging.debug(f"Dropped {overlap_samples_start + overlap_samples_end} samples of overlap, new shape: {separated_audios.shape}")

    # Extract stems: (batch, 4, channels, samples)
    drums = separated_audios[0, :, :]
    bass = separated_audios[1, :, :] # swapped?
    vocals = separated_audios[2, :, :] # swapped?
    other = separated_audios[3, :, :]
    
    # Apply volume controls using proper audio gain
    gains = args.get_effective_gains()
    logging.debug(f"Applying effective gain transform: {gains}")
    log_stem_ranges(drums, bass, vocals, other, "before")
    drums = apply_gain(drums, gains[0])
    bass = apply_gain(bass, gains[1])
    vocals = apply_gain(vocals, gains[2])
    other = apply_gain(other, gains[3])
    log_stem_ranges(drums, bass, vocals, other, "after")
    chunk.gains_applied = gains
    
    # Mix stems back together with proper audio mixing (sum and normalize)
    mixed = drums + bass + vocals + other
    logging.debug(f"Mixed: peak={torch.max(torch.abs(mixed)):.3f}, samples={mixed.shape[-1] if len(mixed.shape) > 0 else 0}")

    # Apply normalization if enabled
    if args.normalize and torch.max(torch.abs(mixed)) > 0:
        # Calculate RMS of original input
        original_rms = torch.sqrt(torch.mean(chunk.input_audio_tensor ** 2))
        # Calculate RMS of mixed output
        mixed_rms = torch.sqrt(torch.mean(mixed ** 2))
        
        if mixed_rms > 0:
            # Calculate normalization factor to match original intensity
            normalization_factor = original_rms / mixed_rms
            mixed = mixed * normalization_factor
            logging.debug(f"Normalized: original_rms={original_rms:.6f}, mixed_rms={mixed_rms:.6f}, factor={normalization_factor:.3f}")

    chunk.processing_completed_at = datetime.datetime.now()
    chunk.truncated_audio_tensor = mixed
    return chunk

def main():
    """Main processing loop."""
    args = get_args()

    observer = None
    if args.watch:
        event_handler = ArgsEventHandler()
        observer = Observer()
        observer.schedule(event_handler, expand_path(args.config_dir))
        observer.start()

    checkpoint = args.checkpoint
    sample_spec = SampleSpec.from_env()

    # Set up audio output queue and thread
    input_queue = queue.Queue(maxsize=100)
    output_queue = queue.Queue(maxsize=100)

    input_thread = threading.Thread(
        target=audio_input_thread,
        args=(input_queue, sample_spec),
        daemon=True)
    inference_thread = threading.Thread(
        target=audio_inference_thread,
        args=(input_queue, output_queue, checkpoint, sample_spec),
        daemon=True)
    output_thread = threading.Thread(
        target=audio_output_thread,
        args=(output_queue, sample_spec),
        daemon=True)

    time.sleep((1_000_000 - datetime.datetime.now().microsecond) / 1_000_000)  # Align to next second boundary
    input_thread.start()
    inference_thread.start()
    output_thread.start()


    # Processing loop
    logging.info("Starting audio processing...")
    
    try:
        input_thread.join()
        inference_thread.join()
        output_thread.join()
        if observer is not None:
            observer.join()
    except BrokenPipeError:
        # Clean shutdown when pipeline closes
        logging.info("Pipeline closed, shutting down")
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        if observer is not None:
            observer.stop()
    except Exception as e:
        logging.error(f"Processing error: {e}")
        sys.exit(1)
    
    logging.info("Processing complete")

if __name__ == "__main__":
    main()
