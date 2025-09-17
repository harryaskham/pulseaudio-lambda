#!/usr/bin/env python3
import argparse
import torch
import sys
import logging
import inspect
from pathlib import Path

def _install_sounddevice_stub():
    try:
        import sounddevice  # type: ignore
        return
    except Exception:
        pass
    import types, sys
    sd = types.ModuleType("sounddevice")
    # Provide no-op placeholders commonly referenced
    def _noop(*args, **kwargs):
        return None
    sd.default = types.SimpleNamespace()
    sd.play = _noop
    sd.stop = _noop
    sd.Stream = object
    sys.modules["sounddevice"] = sd


def load_model_from_checkpoint(hparams):
    # Avoid importing heavy native deps that aren't needed for export
    _install_sounddevice_stub()
    from hs_tasnet import HSTasNet

    model = HSTasNet(
        stereo=hparams.stereo,
        small=hparams.small,
    )

    ckpt_path = Path(hparams.checkpoint)
    logging.info(f"Loading checkpoint from {ckpt_path}")

    # Detect Git LFS pointer files and bail with instructions
    try:
        with ckpt_path.open('rb') as f:
            head = f.read(64)
        if head.startswith(b'version https://git-lfs.github.com/spec/v1'):
            logging.error(
                "Checkpoint appears to be a Git LFS pointer file, not the real weights.\n"
                "Run one of the following in the repo to fetch large files:\n"
                "  git lfs install && git lfs pull\n"
                "  git lfs fetch --all && git lfs checkout\n"
                f"File: {ckpt_path}"
            )
            sys.exit(1)
    except Exception:
        pass
    # PyTorch >= 2.6 defaults weights_only=True which breaks many trainer checkpoints.
    # Force weights_only=False first; fall back if older torch doesn't accept it.
    obj = None
    try:
        obj = torch.load(str(ckpt_path), map_location='cpu', weights_only=False)
    except TypeError:
        # Older torch without weights_only kwarg
        obj = torch.load(str(ckpt_path), map_location='cpu')
    except Exception as e:
        logging.error(
            "Failed to load checkpoint even with weights_only=False. If this persists, "
            "ensure the checkpoint is from a trusted source and compatible with your PyTorch version.\n"
            f"Original error: {e}"
        )
        sys.exit(1)

    state = None
    if isinstance(obj, dict):
        # Common keys by trainer frameworks
        for k in ['state_dict', 'model', 'ema_model', 'model_state_dict']:
            if k in obj and isinstance(obj[k], dict):
                state = obj[k]
                break
        if state is None:
            # Might already be a state_dict (tensor dict)
            tensor_values = [v for v in obj.values() if torch.is_tensor(v) or (isinstance(v, dict) and all(torch.is_tensor(x) for x in v.values()))]
            state = obj if tensor_values else None
    if state is None:
        logging.error("Could not find a state_dict in the checkpoint. Provide a checkpoint containing model weights.")
        sys.exit(1)

    # Strip any "module." prefixes if present (from DataParallel)
    def strip_prefix(d):
        return { (k[7:] if k.startswith('module.') else k): v for k, v in d.items() }

    state = strip_prefix(state)
    missing, unexpected = model.load_state_dict(state, strict=False)
    if missing:
        logging.warning(f"Missing keys when loading: {missing}")
    if unexpected:
        logging.warning(f"Unexpected keys when loading: {unexpected}")

    model.eval()
    return model


def main():
    ap = argparse.ArgumentParser(description='Export HS-TasNet checkpoint to TorchScript for Android')
    ap.add_argument('--checkpoint', required=True, help='Path to checkpoint containing state_dict')
    ap.add_argument('--output', default='separation.pt', help='Output TorchScript file')
    ap.add_argument('--stereo', action='store_true', help='Export for stereo model (default)')
    ap.add_argument('--mono', dest='stereo', action='store_false', help='Export for mono model')
    ap.set_defaults(stereo=True)
    ap.add_argument('--small', action='store_true', help='Construct small HSTasNet variant if used during training')
    ap.add_argument('--trace', action='store_true', help='Use tracing instead of scripting')
    ap.add_argument('--example-len', type=int, default=8192, help='Example T length for tracing input')
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

    model = load_model_from_checkpoint(args)

    def do_trace():
        c = 2 if args.stereo else 1
        example = torch.randn(1, c, args.example_len)
        logging.info(f"Tracing model with example input shape={(1, c, args.example_len)}...")
        return torch.jit.trace(model, example)

    if args.trace:
        scripted = do_trace()
    else:
        logging.info("Scripting model...")
        try:
            scripted = torch.jit.script(model)
        except Exception as e:
            logging.warning(f"Scripting failed ({e}); falling back to tracing. Use --trace to force trace mode.")
            scripted = do_trace()

    logging.info(f"Saving TorchScript to {args.output}")
    scripted.save(args.output)
    logging.info("Done")

if __name__ == '__main__':
    main()
