from hs_tasnet import HSTasNet, Trainer, MusDB18HQ
import os
import fire
import sys
import torch
import logging

def train(
    small = False,
    stereo = True,
    cpu = False,
    batch_size = 16,
    max_steps = 50_000,
    max_epochs = 20,
    max_audio_length_seconds = 5,
    use_wandb = True,
    wandb_project = 'HS-TasNet',
    wandb_run_name = None,
    clear_folders = False,
    musdb18hq_root = "./data/musdb18hq",
    split_dataset_for_eval = True,
    split_dataset_eval_frac = 0.05,
    checkpoint_folder = './checkpoints',
    eval_results_folder = './eval-results',
):

    model = HSTasNet(
        small = small,
        stereo = stereo
    )

    dataset = MusDB18HQ(musdb18hq_root, max_audio_length_seconds=max_audio_length_seconds)

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
        eval_results_folder = eval_results_folder,
        cpu = cpu,
    )

    if clear_folders:
        trainer.clear_folders()

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
