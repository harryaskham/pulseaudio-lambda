import torch
from hs_tasnet import HSTasNet

model = HSTasNet()


audio = torch.randn(1, 2, 204800) # ~5 seconds of stereo

separated_audios, _ = model(audio)

assert separated_audios.shape == (1, 4, 2, 204800)
drums = separated_audios[:, 0, :, :]
bass = separated_audios[:, 1, :, :]
vocals = separated_audios[:, 2, :, :]
other = separated_audios[:, 3, :, :]
