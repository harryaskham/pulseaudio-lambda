import torch
from hs_tasnet import HSTasNet

model = HSTasNet()

audio = torch.randn(1, 2, 204800) # ~5 seconds of stereo

separated_audios, _ = model(audio)

assert separated_audios.shape == (1, 4, 2, 204800) # second dimension is the separated tracks
