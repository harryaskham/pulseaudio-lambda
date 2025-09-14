import torch
from dataclasses import dataclass
import os
import logging
import struct
import sys
import torchaudio
from torchaudio.functional import resample
from einops import rearrange, repeat, reduce
from hs_tasnet import HSTasNet
import numpy as np

def round_down_to_multiple(num, mult):
    return (num // mult) * mult

@dataclass
class SampleSpec:
   sample_rate: int
   channels: int
   bits: int

   @classmethod
   def from_env(cls):
      r = cls(
         sample_rate=int(os.environ.get('PA_LAMBDA_SAMPLE_RATE', '44100')),
         channels=int(os.environ.get('PA_LAMBDA_CHANNELS', '2')),
         bits=int(os.environ.get('PA_LAMBDA_BITS', '16')))
      logging.info(f"Audio format: {r.sample_rate}Hz, {r.channels} channels, {r.bits} bits")
      return r

   @property
   def bytes_per_sample(self):
      return self.bits // 8

   @property
   def stereo(self):
      return self.channels == 2

   def read_chunk(self, buf, num_samples):
      """Read a chunk of audio from stdin and convert to torch tensor format."""
      try:
         chunk_bytes = num_samples * self.bytes_per_sample
         logging.debug(f"Attempting to read {chunk_bytes} bytes ({num_samples} samples at {self.bytes_per_sample} bytes/sample)")
         data = buf.read(chunk_bytes)
         logging.debug(f"Read {len(data) if data else 0} bytes")
         if not data:
               return None

         # Handle partial reads - pad with zeros if needed
         if len(data) < chunk_bytes:
               data += b'\x00' * (chunk_bytes - len(data))

         # Convert bytes to numpy array based on bit depth
         if self.bits == 16:
               dtype = np.int16
               format_char = 'h'
         elif self.bits == 32:
               dtype = np.int32
               format_char = 'i'
         else:
               raise ValueError(f"Unsupported bit depth: {self.bits}")

         # Unpack bytes to samples
         num_samples = len(data) // self.bytes_per_sample
         samples = struct.unpack(f'<{num_samples}{format_char}', data)

         audio_np = np.array(samples, dtype=dtype)

         # Reshape to (channels, samples) - torchcodec/torchaudio format
         if self.stereo:
               # Interleaved stereo: L R L R -> [[L L], [R R]]
               audio_np = audio_np.reshape(-1, 2).T
         else:
               audio_np = audio_np.reshape(1, -1)

         # Normalize to [-1, 1] and convert to torch tensor (proper format)
         max_val = 2**(self.bits-1)
         audio_float = audio_np.astype(np.float32) / max_val
         audio_tensor = torch.from_numpy(audio_float)

         return audio_tensor

      except Exception as e:
         logging.error(f"Error reading audio chunk: {e}")
         return None


class BufferHSTasNet(HSTasNet):
   """Variant of HSTasNet with a method to process audio from a BytesIO."""

   def __init__(self, sample_spec, *args, **kwargs):
      self.sample_spec = sample_spec
      super().__init__(
         sample_rate=self.sample_spec.sample_rate,
         stereo=(self.sample_spec.channels == 2),
         *args, **kwargs)

   def process_audio_tensor(
        self,
        audio_tensor: torch.Tensor,
        return_reduced_sources: list[int] | None = None,
        auto_convert_to_stereo = True,
        overwrite = False
    ):
        logging.error(f"Processing audio of shape {audio_tensor.shape}")

        # curtail to divisible segment lens

        audio_len = audio_tensor.shape[-1]
        rounded_down_len = round_down_to_multiple(audio_len, self.segment_len)

        audio_tensor = audio_tensor[..., :rounded_down_len]

        # add batch
        audio_tensor = rearrange(audio_tensor, '... -> 1 ...')

        # maybe mono to stereo
        mono_to_stereo = self.stereo and auto_convert_to_stereo and audio_tensor.shape[1] == 1
        if mono_to_stereo:
           logging.debug("Converting mono to stereo by duplicating channel")
           audio_tensor = repeat(audio_tensor, '1 1 n -> 1 s n', s = 2)

        # inference
        logging.debug(f"Running model inference on audio tensor {audio_tensor.shape}")
        audio_tensor = audio_tensor.to(self.device)
        with torch.no_grad():
            self.eval()
            transformed, _ = self.forward(
               audio_tensor,
               return_reduced_sources=return_reduced_sources)

        # remove batch

        transformed = rearrange(transformed, '1 ... -> ...')

        # maybe stereo to mono

        if mono_to_stereo:
            transformed = reduce(transformed, 's n -> 1 n', 'mean')

        return transformed
