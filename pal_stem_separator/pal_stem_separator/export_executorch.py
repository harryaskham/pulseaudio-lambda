#!/usr/bin/env python3
"""
Export HS‑TasNet style stem separator to ExecuTorch (.pte) for Android.

This mirrors export_torchscript.py but uses torch.export + ExecuTorch.

Requirements (installed in your Python env):
  - torch >= 2.1 (matching your training/export env; you used 2.8.0)
  - executorch (pip or from source, matching torch major/minor)

Usage example:
  python -m pal_stem_separator.export_executorch \
    --checkpoint /path/to/checkpoint.ckpt \
    --output separation.pte \
    --stereo --example-len 8192

Notes:
  - Input shape expected by the Android app: [1, 2, T] with T=8192 by default.
  - Output can remain a 4‑stem representation inside the model; the app mixes stems.
  - Backend partitioning uses XNNPACK if available; otherwise saves generic ExecuTorch program.
"""

import argparse
import logging
import sys
from pathlib import Path

import torch

from .export_torchscript import load_model_from_checkpoint  # reuse loader + hparam parsing


def build_argparser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Export checkpoint to ExecuTorch (.pte)")
    ap.add_argument("--checkpoint", required=True, help="Path to model checkpoint (.pt/.ckpt)")
    ap.add_argument("--output", default="separation.pte", help="Output ExecuTorch package file (.pte)")
    ap.add_argument("--stereo", action="store_true", help="Export stereo model (default true)")
    ap.add_argument("--mono", dest="stereo", action="store_false", help="Export mono model")
    ap.add_argument("--example-len", type=int, default=8192, help="Example T dimension for export")
    ap.add_argument("--device", default="cpu", help="Export device for example inputs (cpu)")
    ap.set_defaults(stereo=True)
    return ap


def export_executorch(model: torch.nn.Module, example: torch.Tensor, out_path: Path) -> None:
    try:
        from torch.export import export as ts_export
    except Exception as e:
        raise RuntimeError("torch.export is unavailable; need PyTorch 2.1+") from e

    logging.info("Exporting to torch.export ExportedProgram...")
    with torch.inference_mode():
        ep = ts_export(model, (example,))

    # Try the modern ExecuTorch API first
    try:
        from executorch.exir import to_edge, save_program
        logging.info("Lowering to ExecuTorch edge dialect...")
        edge = to_edge(ep)

        # Optional: partition for XNNPACK backend if available
        try:
            logging.info("Attempting XNNPACK partition...")
            # API location may vary across versions
            try:
                from executorch.backends.xnnpack import partition as xnnpack_partition
                backend_prog = xnnpack_partition(edge)
            except Exception:
                from executorch.backends.xnnpack.partition import partition as xnnpack_partition  # type: ignore
                backend_prog = xnnpack_partition(edge)
            logging.info("XNNPACK partition successful")
        except Exception as be:
            logging.warning("XNNPACK partition failed; saving generic edge program (%s)", be)
            backend_prog = edge

        logging.info("Saving ExecuTorch program to %s", out_path)
        save_program(backend_prog, str(out_path))
        return
    except Exception as e:
        logging.warning("Modern ExecuTorch API failed (%s); trying legacy path...", e)

    # Legacy fallback path for older ExecuTorch snapshots
    try:
        from executorch.exir import EdgeProgramManager
        logging.info("Lowering via EdgeProgramManager (legacy)...")
        pm = EdgeProgramManager(ep)
        et_prog = pm.to_executorch()
        et_prog.save(str(out_path))
        return
    except Exception as le:
        raise RuntimeError("ExecuTorch export failed; update executorch and/or adjust API paths") from le


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    ap = build_argparser()
    args = ap.parse_args(argv)

    # Reuse TorchScript exporter’s loader to assemble the model from a checkpoint
    logging.info("Loading model from checkpoint: %s", args.checkpoint)
    try:
        model = load_model_from_checkpoint(args)
    except Exception as e:
        logging.error("Failed to construct model from checkpoint: %s", e)
        return 2

    c = 2 if args.stereo else 1
    example = torch.randn(1, c, int(args.example_len), device=args.device)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        export_executorch(model, example, out_path)
    except Exception as e:
        logging.error("ExecuTorch export failed: %s", e)
        return 3

    logging.info("Export complete: %s", out_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())

