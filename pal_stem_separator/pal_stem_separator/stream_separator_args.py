from typing import List
import dataclasses
import pathlib
import json
import sys
import os
import argparse
import logging
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from pal_stem_separator.stream_separator_utils import expand_path

# Live global args singletons for auto-refresh
_args = None  # Global to hold parsed args
_args_lock = threading.Lock()

class ArgsWatcher(FileSystemEventHandler):
    def refresh(self, event):
        if event.src_path == expand_path(Args.get_live().config_path):
            logging.info("Reloaded config after change: %s", Args.refresh())

    def on_modified(self, event):
        super().on_modified(event)
        self.refresh(event)

    def on_moved(self, event):
        super().on_moved(event)
        self.refresh(event)

@dataclasses.dataclass
class Args:
    checkpoint: str
    chunk_secs: float
    overlap_secs: float
    gains: List[float]
    muted: List[bool]
    soloed: List[bool]
    normalize: bool
    device: str
    watch: bool
    debug: bool = False
    empty_queues_requested: str | None = None
    queues_last_emptied_at: str | None = None
    tui_tmux_session_name: str | None = "stem_separator_tui"

    # CLI-only or inferred args
    gui: bool | None = dataclasses.field(default=False, repr=False, compare=False)
    tui: bool | None = dataclasses.field(default=False, repr=False, compare=False)
    ui_only: bool | None = dataclasses.field(default=False, repr=False, compare=False)
    config_dir: str | None = dataclasses.field(default=None, repr=False, compare=False)
    config_path: str | None = dataclasses.field(default=None, repr=False, compare=False)
    stats_path: str | None = dataclasses.field(default=None, repr=False, compare=False)
    observer: Observer | None = dataclasses.field(default=None, repr=False, compare=False)

    # Export args
    executorch_run_export: bool = False
    executorch_output: str = "export/separation.pte"
    executorch_example_len: int = 8192

    @classmethod
    def get_config_dir(cls, args=None):
        config_dir = (
            args.config_dir if args is not None and args.config_dir is not None
            else os.environ.get('PA_LAMBDA_CONFIG_DIR',
                                expand_path("~/.config/pulseaudio-lambda")))
        pathlib.Path(config_dir).mkdir(parents=True, exist_ok=True)
        logging.info(f"Using config dir: {config_dir}")
        return config_dir

    @classmethod
    def get_config_json_path(cls, config_dir=None, args=None):
        if config_dir is None:
            config_dir = cls.get_config_dir(args)
        return os.path.join(config_dir, "stream_separator_config.json")

    @classmethod
    def get_stats_json_path(cls, config_dir=None, args=None):
        if config_dir is None:
            config_dir = cls.get_config_dir(args)
        return os.path.join(config_dir, "stream_separator_stats.json")

    @classmethod
    def refresh(cls):
        global _args
        with _args_lock:
            try:
                _args = cls._load_live(first_load=False, prev_args=_args, silent=False)
                logging.debug("Refreshed args")
            except Exception as e:
                logging.error(f"Error refreshing args: {e}")
            return _args

    @classmethod
    def get_live(cls):
        global _args
        with _args_lock:
            if _args is None:
                _args = Args._load_live(first_load=True, prev_args=None, silent=False)
            return _args

    @classmethod
    def _load_live(cls, first_load, prev_args, silent):
        """Get a live view of the args, merging CLI args and config file."""

        parser = argparse.ArgumentParser(description='Real-time audio stem separation')

        parser.add_argument('--debug', action='store_true',
                            help='Enable debug logging')

        # Config JSON file
        # Overridden temporarily by any provided command line args
        # Defaults to the env variable $PA_LAMBDA_CONFIG_DIR or ~/.config/pulseaudio-lambda if not set
        parser.add_argument('--config-dir', type=str, help='Path to config dir')

        parser.add_argument('--save-config', action='store_true',
                            help='If set, persist the current settings combination')

        parser.add_argument('--watch', action='store_true',
                            help='If set, watch the config file for changes and reload dynamically')

        parser.add_argument('--gui', action='store_true',
                            help='If set, also launch the gui')
        parser.add_argument('--tui', action='store_true',
                            help='If set, also launch the tui')
        parser.add_argument('--tui-tmux-session-name', type=str,
                            help='If set, also launch the tui in a tmux session with the given name')
        parser.add_argument('--ui-only', action='store_true',
                            help='If set, only launch the UI and exit')

        # Checkpoint
        parser.add_argument('--checkpoint', type=str,
                            help='Path to model checkpoint')

        # Chunk size in seconds
        parser.add_argument('--chunk-secs', type=float,
                            help='Chunk size in seconds')

        # Overlap size in seconds
        parser.add_argument('--overlap-secs', type=float,
                            help='Overlap size in seconds')

        # Volume controls for each stem or m to mute
        parser.add_argument('--gains', type=str,
                            help='Stem gain change for drums,bass,vocals,other (e.g. 50,m,100,m to mute bass and other, with half volume drums and full volume vocals)')

        # Normalization
        parser.add_argument('--normalize', action='store_true',
                            help='Normalize output volume to match input intensity after applying gains')

        # Device selection
        parser.add_argument('--device', type=str,
                            help='Device to use (cuda/cpu)')

        parser.add_argument("--executorch-run-export", action='store_true', help="Output ExecuTorch package file (.pte)")
        parser.add_argument("--executorch-output", default="exports/separation.pte", help="Output ExecuTorch package file (.pte)")
        parser.add_argument("--executorch-example-len", type=int, default=8192, help="Example T dimension for export")

        args = parser.parse_args()

        # Set up logging to stderr (stdout is for audio)
        logging.basicConfig(
            level=logging.DEBUG if args.debug else logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            stream=sys.stderr
        )

        logging.debug(f"CLI args: {args}")

        config_dir = Args.get_config_dir(args)
        config_json_path = Args.get_config_json_path(config_dir=config_dir, args=args)
        stats_json_path = Args.get_stats_json_path(config_dir=config_dir, args=args)
        config_args = Args.read(config_dir=config_dir)

        observer = prev_args.observer if prev_args is not None else None
        watch = args.watch or config_args.watch
        debug = args.debug or config_args.debug
        logging.info(f"Watch config for changes: {watch} (existing observer={observer})")
        if watch and (observer is None):
            logging.info(f"Setting up config file watcher for {config_dir}")
            event_handler = ArgsWatcher()
            observer = Observer()
            observer.schedule(event_handler, expand_path(config_dir))
            observer.start()
            logging.info("Started config file watcher")
        elif not watch and prev_args is not None and prev_args.observer is not None:
            logging.info("Stopping config file watcher")
            prev_args.observer.stop()
            observer = None

        combined = cls(
            gains=(
                [ 0.0 if x.strip() == "m" else float(x.strip())
                  for x in args.gains.split(",") ]
                if args.gains is not None
                else config_args.gains),
            muted = (
                [ x.strip() == "m" for x in args.gains.split(",") ]
                if args.gains is not None
                else config_args.muted),
            soloed = (
                [ x.strip() == "s" for x in args.gains.split(",") ]
                if args.gains is not None
                else config_args.soloed),
            checkpoint=args.checkpoint if args.checkpoint is not None else config_args.checkpoint,
            chunk_secs=args.chunk_secs if args.chunk_secs is not None else config_args.chunk_secs,
            overlap_secs=args.overlap_secs if args.overlap_secs is not None else config_args.overlap_secs,
            device=args.device if args.device is not None else config_args.device,
            normalize=args.normalize or config_args.normalize,
            debug=debug,
            config_dir=config_dir,
            config_path=config_json_path,
            stats_path=stats_json_path,
            watch=watch,
            observer=observer,
            empty_queues_requested=config_args.empty_queues_requested,
            queues_last_emptied_at=config_args.queues_last_emptied_at,
            gui=args.gui or config_args.gui,
            tui=args.tui or config_args.tui,
            ui_only=args.ui_only or config_args.ui_only,
            tui_tmux_session_name=args.tui_tmux_session_name or config_args.tui_tmux_session_name,
            # Export
            executorch_run_export=args.executorch_run_export or config_args.executorch_run_export,
            executorch_output=args.executorch_output or config_args.executorch_output,
            executorch_example_len=args.executorch_example_len or config_args.executorch_example_len
        )
        logging.info(f"Configuration: {combined}")

        if args.save_config and first_load:
            combined.save()

        return combined

    @classmethod
    def read(cls, config_dir=None):
        """Read the config only, don't set up watching or merge with CLI args."""
        config_json_path = cls.get_config_json_path(config_dir=config_dir)
        if not os.path.exists(config_json_path):
            raise FileNotFoundError(f"Config file not found: {config_json_path}")
        stats_json_path = cls.get_stats_json_path(config_dir=config_dir)
        with open(config_json_path, 'r') as f:
            args = cls(
                config_dir=config_dir,
                config_path=config_json_path,
                stats_path=stats_json_path,
                **(json.load(f)))
            logging.info(f"Loaded config args: {args}")
            return args

    def save(self):
        try:
            observer = self.observer
            self.observer = None  # Temporarily remove observer for serialization
            data = dataclasses.asdict(self)
            self.observer = observer

            del data['config_dir']
            del data['config_path']
            del data['stats_path']
            del data['gui']
            del data['tui']
            del data['ui_only']
            del data['observer']
            del data['executorch_run_export']
            del data['executorch_output']
            del data['executorch_example_len']
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=4)
            logging.info(f"Saved config {data} to {self.config_path}")
        except Exception as e:
            logging.error(f"Failed to save config to {self.config_path}: {e}")
    
    def request_empty_queues(self):
        """Request queue emptying by setting the timestamp."""
        import datetime
        self.empty_queues_requested = datetime.datetime.now().isoformat()
        self.save()

    def join(self):
        if self.observer is not None:
            self.observer.join()

    def stop(self):
        if self.observer is not None:
            self.observer.stop()
            self.observer.join()
            self.observer = None

    def get_effective_gains(self) -> List[float]:
        """Get the actual gains to apply, considering mute/solo state."""
        effective_gains = []
        any_soloed = any(self.soloed)

        for i in range(len(self.gains)):
            if self.muted[i]:
                # Muted stems get 0 gain
                effective_gains.append(0.0)
            elif any_soloed and not self.soloed[i]:
                # If any stems are soloed and this one isn't, mute it
                effective_gains.append(0.0)
            else:
                # Use the configured gain
                effective_gains.append(self.gains[i])

        return effective_gains

    def reset_volumes(self):
        """Reset all volumes to 100% and clear mute/solo state."""
        self.gains = [100.0, 100.0, 100.0, 100.0]
        self.muted = [False, False, False, False]
        self.soloed = [False, False, False, False]

    def toggle_mute(self, index: int):
        """Toggle mute state for a stem."""
        if 0 <= index < len(self.muted):
            self.muted[index] = not self.muted[index]
            # Clear solo when muting
            if self.muted[index]:
                self.soloed[index] = False

    def toggle_solo(self, index: int):
        """Toggle solo state for a stem."""
        if 0 <= index < len(self.soloed):
            self.soloed[index] = not self.soloed[index]
            # Clear mute when soloing
            if self.soloed[index]:
                self.muted[index] = False
