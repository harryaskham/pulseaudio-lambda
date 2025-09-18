from typing import List
import dataclasses
import datetime
import torch
import logging

from pal_stem_separator.buffer_hs_tasnet import SampleSpec

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
