#!/usr/bin/env python3
"""
Simple passthrough test to verify stdin/stdout audio streaming.
"""

import sys
import os
import logging

# Set up logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

def main():
    # Get audio format from environment
    sample_rate = int(os.environ.get('PA_LAMBDA_SAMPLE_RATE', '44100'))
    channels = int(os.environ.get('PA_LAMBDA_CHANNELS', '2'))
    bits = int(os.environ.get('PA_LAMBDA_BITS', '16'))
    buffer_size = int(os.environ.get('PA_LAMBDA_BUFFER_SIZE', '1024'))
    
    logging.info(f"Audio format: {sample_rate}Hz, {channels} channels, {bits} bits")
    logging.info(f"Buffer size: {buffer_size} samples")
    
    # Calculate bytes per buffer
    bytes_per_sample = bits // 8
    bytes_per_frame = channels * bytes_per_sample
    bytes_per_buffer = buffer_size * bytes_per_frame
    
    logging.info(f"Reading {bytes_per_buffer} bytes per buffer")
    
    try:
        total_bytes = 0
        buffer_count = 0
        
        while True:
            # Read from stdin
            data = sys.stdin.buffer.read(bytes_per_buffer)
            
            if not data:
                logging.info("End of stream")
                break
            
            # Write to stdout immediately (passthrough)
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
            
            total_bytes += len(data)
            buffer_count += 1
            
            if buffer_count % 100 == 0:
                logging.info(f"Processed {buffer_count} buffers, {total_bytes} bytes")
                
    except BrokenPipeError:
        logging.info("Pipe broken, shutting down")
    except KeyboardInterrupt:
        logging.info("Interrupted")
    except Exception as e:
        logging.error(f"Error: {e}")
        raise
    
    logging.info(f"Total processed: {buffer_count} buffers, {total_bytes} bytes")

if __name__ == "__main__":
    main()