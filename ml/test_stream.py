#!/usr/bin/env python3
"""
Test script for debugging the stream separator.
Generates test audio and verifies the processing pipeline.
"""

import sys
import os
import struct
import numpy as np

def generate_test_audio(duration_seconds=5, sample_rate=44100, channels=2, bits=16):
    """Generate test audio data (sine wave)."""
    num_samples = int(duration_seconds * sample_rate)
    
    # Generate sine wave at 440 Hz (A4 note)
    t = np.linspace(0, duration_seconds, num_samples)
    frequency = 440
    amplitude = 0.5
    
    audio = amplitude * np.sin(2 * np.pi * frequency * t)
    
    # Make stereo if needed
    if channels == 2:
        # Different frequency in right channel
        audio_r = amplitude * np.sin(2 * np.pi * frequency * 1.5 * t)
        audio = np.vstack([audio, audio_r])
    else:
        audio = audio.reshape(1, -1)
    
    # Convert to integer format
    max_val = 2**(bits-1) - 1
    audio_int = (audio * max_val).astype(np.int16 if bits == 16 else np.int32)
    
    # Interleave channels
    if channels == 2:
        audio_int = audio_int.T.flatten()
    else:
        audio_int = audio_int.flatten()
    
    # Pack to bytes
    format_char = 'h' if bits == 16 else 'i'
    data = struct.pack(f'<{len(audio_int)}{format_char}', *audio_int)
    
    return data

def test_read_write():
    """Test basic read/write functionality."""
    print("Testing basic I/O...", file=sys.stderr)
    
    # Set environment variables
    os.environ['PA_LAMBDA_SAMPLE_RATE'] = '44100'
    os.environ['PA_LAMBDA_CHANNELS'] = '2'
    os.environ['PA_LAMBDA_BITS'] = '16'
    
    # Generate test data
    test_data = generate_test_audio(0.1)  # 100ms of audio
    
    print(f"Generated {len(test_data)} bytes of test audio", file=sys.stderr)
    
    # Try to read it back
    bytes_per_sample = 2  # 16 bits
    channels = 2
    bytes_per_frame = channels * bytes_per_sample
    num_frames = len(test_data) // bytes_per_frame
    
    # Unpack
    format_char = 'h'
    samples = struct.unpack(f'<{num_frames * channels}{format_char}', test_data)
    audio_np = np.array(samples, dtype=np.int16)
    
    # Reshape
    audio_np = audio_np.reshape(-1, channels).T
    
    print(f"Successfully unpacked audio: shape {audio_np.shape}", file=sys.stderr)
    print(f"Audio range: [{audio_np.min()}, {audio_np.max()}]", file=sys.stderr)
    
    # Test normalization
    audio_float = audio_np.astype(np.float32) / 32768
    print(f"Normalized range: [{audio_float.min():.3f}, {audio_float.max():.3f}]", file=sys.stderr)
    
    return True

def test_stdin_buffer():
    """Test stdin.buffer access."""
    print("\nTesting stdin.buffer access...", file=sys.stderr)
    
    try:
        # Check if sys.stdin has buffer attribute
        stdin_buffer = sys.stdin.buffer
        print(f"sys.stdin.buffer type: {type(stdin_buffer)}", file=sys.stderr)
        print(f"sys.stdin type: {type(sys.stdin)}", file=sys.stderr)
        
        # Try reading from it (will be empty in test, but shouldn't error)
        stdin_buffer.read(0)
        print("Successfully accessed stdin.buffer", file=sys.stderr)
        
        return True
    except AttributeError as e:
        print(f"Error accessing stdin.buffer: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        return False

if __name__ == "__main__":
    print("=== Stream Separator Test ===", file=sys.stderr)
    
    # Run tests
    success = True
    success &= test_stdin_buffer()
    success &= test_read_write()
    
    if success:
        print("\n✓ All tests passed!", file=sys.stderr)
    else:
        print("\n✗ Some tests failed", file=sys.stderr)
        sys.exit(1)