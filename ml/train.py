from hs_tasnet import HSTasNet, Trainer, MusDB18HQ
import torchaudio
import fire
import sys
import logging

class MaxMusDB18HQ(MusDB18HQ):
    """Set the max length to the shortest audio."""
    def __init__(
        self,
        dataset_path,
        sep_filenames = ('drums', 'bass', 'vocals', 'other'),
        max_audio_length_seconds = None,
    ):
        if max_audio_length_seconds is not None:
            super().__init__(dataset_path, sep_filenames=sep_filenames, max_audio_length_seconds=max_audio_length_seconds)
        else:
            def len_secs(i):
                audio, sample_rate = torchaudio.load(f"{self.paths[i]}/mixture.wav")
                return audio.shape[-1] // sample_rate
            super().__init__(dataset_path, sep_filenames=sep_filenames)
            self.max_audio_length_seconds = min(len_secs(i) for i in range(0, len(self)))
            logging.info(f"Max audio length set to shortest audio: {self.max_audio_length_seconds} seconds.")

def train(
    experiment_name,
    small = False,
    stereo = True,
    cpu = False,
    batch_size = 32,
    max_steps = 100_000,
    max_epochs = 10000,
    max_audio_length_seconds = None,
    use_ema = False,
    use_wandb = True,
    wandb_project = 'HS-TasNet',
    musdb18hq_root = "./data/musdb18hq",
    split_dataset_for_eval = True,
    split_dataset_eval_frac = 0.01,
    checkpoint_every = 25,
    eval_sdr = False,
    decay_lr_if_not_improved_steps = 10,
    early_stop_if_not_improved_steps = 20,
):
    wandb_run_name = experiment_name
    checkpoint_folder = f"./experiments/{experiment_name}/checkpoints"
    eval_results_folder = f"./experiments/{experiment_name}/eval-results"

    model = HSTasNet(
        small = small,
        stereo = stereo
    )

    dataset = MaxMusDB18HQ(musdb18hq_root, max_audio_length_seconds=max_audio_length_seconds)

    trainer = Trainer(
        model,
        dataset = dataset,
        concat_musdb_dataset = False,
        batch_size = batch_size,
        max_steps = max_steps,
        max_epochs = max_epochs,
        use_wandb = use_wandb,
        experiment_project = wandb_project,
        experiment_run_name = wandb_run_name,
        random_split_dataset_for_eval_frac = 0. if not split_dataset_for_eval else split_dataset_eval_frac,
        checkpoint_folder = checkpoint_folder,
        checkpoint_every = checkpoint_every,
        eval_results_folder = eval_results_folder,
        cpu = cpu,
        use_ema = use_ema,
        eval_sdr = eval_sdr
    )

    trainer()

# fire cli
# --small for small model

if __name__ == '__main__':
    # Set up logging to stderr (stdout is for audio)
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr)
    fire.Fire(train)
