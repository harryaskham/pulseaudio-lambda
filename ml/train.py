from hs_tasnet import HSTasNet, Trainer, MusDB18HQ
import torchaudio
import fire
import sys
import logging
import numpy as np
import termplotlib as tpl

def mixture_length_secs(path):
    audio, sample_rate = torchaudio.load(f"{path}/mixture.wav")
    return audio.shape[-1] / sample_rate

class MaxMusDB18HQ(MusDB18HQ):
    """Set the max length to the shortest audio."""
    def __init__(
        self,
        dataset_path,
        sep_filenames = ('drums', 'bass', 'vocals', 'other'),
        max_audio_length_seconds = None,
        paths = None,
    ):
        # Override init if paths explicitly given
        if paths is not None:
            self.paths = paths
            self.sep_filenames = sep_filenames
        else:
            super().__init__(dataset_path, sep_filenames=sep_filenames)

        # Common setup
        self.dataset_path = dataset_path
        self.sep_filenames = sep_filenames
        self.orignal_max_audio_length_seconds = max_audio_length_seconds
        self.mixture_lengths_secs = [
            mixture_length_secs(path) for path in self.paths]

        # If unset, set to shortest audio in dataset
        if max_audio_length_seconds is None:
            self.max_audio_length_seconds = (
                int(min(self.mixture_lengths_secs))
                if max_audio_length_seconds is None
                else max_audio_length_seconds)

        logging.info(f"Max audio length set to shortest audio: {self.max_audio_length_seconds} seconds.")

    def length_hist(self):
        ls = np.array(self.mixture_lengths_secs)
        counts, bin_edges = np.histogram(ls.astype('int'), bins=40)
        fig = tpl.figure()
        fig.hist(
            counts,
            bin_edges,
            orientation='horizontal',
            force_ascii=True)
        return fig

    def split(self, length_boundary_secs):
        """Return two new datasets split by whether the audio is longer/shorter."""
        def split_by(p):
            return MaxMusDB18HQ(
                self.dataset_path,
                sep_filenames = self.sep_filenames,
                paths = [
                    path
                    for path, length_secs
                    in zip(self.paths, self.mixture_lengths_secs)
                    if p(length_secs)],
                max_audio_length_seconds = self.orignal_max_audio_length_seconds)
        return (
            split_by(lambda secs: secs <= length_boundary_secs),
            split_by(lambda secs: secs > length_boundary_secs))

def train(
    experiment_name=None,
    inspect = False,
    small = False,
    stereo = True,
    cpu = False,
    batch_size = 8,
    max_steps = 50_000,
    max_epochs = 1000,
    max_audio_length_seconds = None,
    use_ema = False,
    use_wandb = True,
    wandb_project = 'HS-TasNet',
    musdb18hq_root = "./data/musdb18hq",
    split_dataset_eval_secs = 30,
    split_dataset_eval_frac = None,
    checkpoint_every = 10,
    eval_sdr = False,
    decay_lr_if_not_improved_steps = 10,
    early_stop_if_not_improved_steps = 20,
):
    dataset = MaxMusDB18HQ(
        musdb18hq_root,
        max_audio_length_seconds=max_audio_length_seconds)

    if split_dataset_eval_secs is not None:
        assert split_dataset_eval_frac is None, "Can only split by seconds or fraction, not both."
        eval_dataset, train_dataset = dataset.split(split_dataset_eval_secs)
        random_split_dataset_for_eval_frac = 0.

    if split_dataset_eval_frac is not None:
        assert split_dataset_eval_secs is None, "Can only split by seconds or fraction, not both."
        train_dataset = dataset
        eval_dataset = None
        random_split_dataset_for_eval_frac = split_dataset_eval_frac

    if inspect:
        for k, dataset in {"train": train_dataset, "eval": eval_dataset}.items():
            if dataset is None:
                continue
            logging.info(f"Dataset {k} mixture lengths:")
            for i, (item, mixture_length_secs) in enumerate(zip(dataset, dataset.mixture_lengths_secs)):
                audio, targets = item
                logging.info(f"{k}: Audio {i}: {mixture_length_secs:.2f} seconds")
                logging.info(f"{k}: Audio {i}: {audio.shape[-1]} samples")
                for j, target in enumerate(targets):
                    logging.info(f"{k}: Audio {i} - Target {j}: {target.shape[-1]} samples")
            logging.info("{k}: Histogram")
            dataset.length_hist().show()
        return

    if experiment_name is None:
        logging.error("Please provide an experiment name.")
        return

    wandb_run_name = experiment_name
    checkpoint_folder = f"./experiments/{experiment_name}/checkpoints"
    eval_results_folder = f"./experiments/{experiment_name}/eval-results"

    model = HSTasNet(
        small = small,
        stereo = stereo
    )

    trainer = Trainer(
        model,
        dataset = train_dataset,
        eval_dataset = eval_dataset,
        concat_musdb_dataset = False,
        batch_size = batch_size,
        max_steps = max_steps,
        max_epochs = max_epochs,
        use_wandb = use_wandb,
        experiment_project = wandb_project,
        experiment_run_name = wandb_run_name,
        random_split_dataset_for_eval_frac = random_split_dataset_for_eval_frac,
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
