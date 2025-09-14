import os
import logging
import torch
import torchaudio
from hs_tasnet import HSTasNet

sample_rate = int(os.environ.get('PA_LAMBDA_SAMPLE_RATE', '44100'))
channels = int(os.environ.get('PA_LAMBDA_CHANNELS', '2'))
bits = int(os.environ.get('PA_LAMBDA_BITS', '16'))
buffer_size = int(os.environ.get('PA_LAMBDA_BUFFER_SIZE', '1024'))

class BufferHSTasNet(HSTasNet):
   def process_buffer(
        self,
        input_buffer,
        return_reduced_sources: list[int],
        auto_convert_to_stereo = True,
        overwrite = False
    ):
        if isinstance(input_file, str):
            input_file = Path(input_file)

        assert len(return_reduced_sources) > 0
        assert input_file.exists(), f'{str(input_file)} not found'

        audio_tensor, sample_rate = torchaudio.load(input_file)

        # resample if need be

        if sample_rate != self.sample_rate:
            audio_tensor = resample(audio_tensor, sample_rate, self.sample_rate)

        # curtail to divisible segment lens

        audio_len = audio_tensor.shape[-1]
        rounded_down_len = round_down_to_multiple(audio_len, self.segment_len)

        audio_tensor = audio_tensor[..., :rounded_down_len]

        # add batch

        audio_tensor = rearrange(audio_tensor, '... -> 1 ...')

        # maybe mono to stereo

        mono_to_stereo = self.stereo and auto_convert_to_stereo and audio_tensor.shape[0] == 1

        if mono_to_stereo:
            audio_tensor = repeat(audio_tensor, '1 1 n -> 1 s n', s = 2)

        # transform

        audio_tensor = audio_tensor.to(self.device)

        with torch.no_grad():
            self.eval()
            transformed, _ = self.forward(audio_tensor, return_reduced_sources = return_reduced_sources)

        # remove batch

        transformed = rearrange(transformed, '1 ... -> ...')

        # maybe stereo to mono

        if mono_to_stereo:
            transformed = reduce(transformed, 's n -> 1 n', 'mean')

        # save output file

        if not exists(output_file):
            output_file = Path(input_file.parents[-2] / f'{input_file.stem}-out.mp3')

        assert output_file != input_file

        self.save_tensor_to_file(str(output_file), transformed.cpu(), overwrite = overwrite)

logging.debug(f"loading model on device")
device = torch.device('cuda')
model = HSTasNet(sample_rate=sample_rate).to(device)
logging.debug(f"starting stream")
model.sounddevice_stream(
    channels=2,
    device=device,
    print_latency=True,
    return_reduced_sources=[0],
    blocksize=buffer_size
)
logging.debug(f"processing file")
model.process_audio_file('test.mp3', return_reduced_sources=[0], output_file='drums.mp3')
