#!/usr/bin/env python3

import datetime
import sys
import os
import torch
import struct
import logging
import threading
import queue
import libtmux

from pal_stem_separator.stream_separator_args import Args
from pal_stem_separator.stream_separator_utils import expand_path
from pal_stem_separator.ui.stream_separator_ui import run as run_ui
from pal_stem_separator.chunk import Chunk
from pal_stem_separator.buffer_hs_tasnet import BufferHSTasNet, SampleSpec
from pal_stem_separator import export_executorch

def check_and_empty_queues(args, input_queue, output_queue):
    """Check if queue emptying was requested and empty queues if needed."""

    if args.empty_queues_requested and args.empty_queues_requested != args.queues_last_emptied_at:
        # Empty both queues
        while not input_queue.empty():
            try:
                input_queue.get_nowait()
            except:
                break
        
        while not output_queue.empty():
            try:
                output_queue.get_nowait()
            except:
                break
        
        # Update the timestamp
        args.queues_last_emptied_at = args.empty_queues_requested
        args.save()
        
        logging.info(f"Emptied queues at {args.queues_last_emptied_at}")
        return True
    return False

def audio_input_thread(input_queue, sample_spec):
    try:
        last_input_audio_tensor = None
        while True:
            args = Args.get_live()

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

def audio_inference_thread(input_queue, output_queue, sample_spec):
    loaded_checkpoint = None
    loaded_device = None

    def reload_device(args):
        device = torch.device(args.device)
        logging.info(f"Using device: {device}")
        return device

    def reload_model(args):
        logging.info("Loading HS-TasNet model...")
        model = BufferHSTasNet(sample_spec)
        checkpoint_path = expand_path(args.checkpoint)
        model.load(checkpoint_path)
        logging.info(f"Checkpoint {checkpoint_path} loaded successfully")
        return model

    device = None
    model = None

    while True:
        args = Args.get_live()
        
        # Check if queue emptying was requested
        if check_and_empty_queues(args, input_queue, output_queue):
            # Skip processing for this iteration if queues were emptied
            continue

        move_model = False
        if args.device != loaded_device:
            device = reload_device(args)
            loaded_device = args.device
            move_model = True

        if args.checkpoint != loaded_checkpoint:
            model = reload_model(args)
            loaded_checkpoint = args.checkpoint
            move_model = True

        if move_model:
            model = model.to(device)
            move_model = False

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

def run_ui_thread():
    args = Args.get_live()
    if args.gui:
        run_ui("gui")
    elif args.tui:
        logging.info(f"Running TUI in tmux session with name: {args.tui_tmux_session_name}")
        server = libtmux.Server()
        session = server.sessions.get(session_name=args.tui_tmux_session_name)
        if session is None:
            session = server.new_session(session_name=args.tui_tmux_session_name)
        debug = " --debug" if args.debug else ""
        command = f"{sys.executable} {sys.argv[0]} --tui --ui-only{debug}"
        logging.debug(f"Running command in tmux: {command}")
        session.active_window.active_pane.send_keys(command)
        logging.info("TUI running in tmux session, exiting UI thread")
    else:
        logging.error("No UI mode specified")
        sys.exit(1)

def main():
    """Main processing loop."""
    args = Args.read()

    if args.executorch_run_export:
        logging.info("Running Executorch export")
        return export_executorch.run_export(args)

    # Start live args watcher
    args = Args.get_live()

    if args.ui_only:
        if args.gui:
            logging.info("Running GUI only")
            run_ui("gui")
        elif args.tui:
            logging.info("Running TUI only (no tmux)")
            run_ui("tui")
        return 

    ui_thread = None
    if args.gui or args.tui:
        ui_thread = threading.Thread(
            target=run_ui_thread,
            daemon=True)
        logging.info("Starting UI thread...")
        ui_thread.start()

        if args.ui_only:
            logging.debug("Only running UI (joining UI thread)")
            ui_thread.join()
            logging.debug("Exiting after UI thread joined")
            return

    sample_spec = SampleSpec.from_env()

    # Set up audio output queue and thread
    input_queue = queue.Queue()
    output_queue = queue.Queue()

    input_thread = threading.Thread(
        target=audio_input_thread,
        args=(input_queue, sample_spec),
        daemon=True)
    inference_thread = threading.Thread(
        target=audio_inference_thread,
        args=(input_queue, output_queue, sample_spec),
        daemon=True)
    output_thread = threading.Thread(
        target=audio_output_thread,
        args=(output_queue, sample_spec),
        daemon=True)

    logging.info("Starting I/O threads...")
    input_thread.start()
    inference_thread.start()
    output_thread.start()

    try:
        logging.info("Awaiting stream completion...")
        input_thread.join()
        inference_thread.join()
        output_thread.join()
        args.join()
        if ui_thread is not None:
            ui_thread.join()
    except BrokenPipeError:
        # Clean shutdown when pipeline closes
        logging.info("Pipeline closed, shutting down")
    except KeyboardInterrupt:
        logging.info("Interrupted by user")
        args.stop()
    except Exception as e:
        logging.error(f"Processing error: {e}")
        sys.exit(1)
    
    logging.info("Stream complete")

if __name__ == "__main__":
    main()
