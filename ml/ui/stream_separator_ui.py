#!/usr/bin/env python3
"""
Main entry point for the stream separator UI.
Can launch either GUI or TUI mode.
"""

import sys
import argparse
import logging

def main():
    parser = argparse.ArgumentParser(description="Stream Separator Configuration UI")
    parser.add_argument(
        "--mode", 
        choices=["gui", "tui", "auto"],
        default="auto",
        help="UI mode: gui (graphical), tui (terminal), or auto (detect)"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging"
    )
    
    args = parser.parse_args()
    
    # Set up logging
    log_level = logging.DEBUG if args.debug else logging.INFO
    logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Determine which UI to use
    mode = args.mode
    
    if mode == "auto":
        # Try to detect if we can use GUI
        try:
            import tkinter
            # Try to create a test window to see if display is available
            test = tkinter.Tk()
            test.withdraw()
            test.destroy()
            mode = "gui"
            logging.debug("Auto-detected GUI mode")
        except Exception as e:
            mode = "tui"
            logging.debug(f"Auto-detected TUI mode (GUI not available: {e})")
    
    # Launch the appropriate UI
    if mode == "gui":
        try:
            from gui import StreamSeparatorGUI
            logging.info("Starting GUI mode...")
            app = StreamSeparatorGUI()
            app.run()
        except ImportError as e:
            logging.error(f"Failed to import GUI module: {e}")
            logging.info("Falling back to TUI mode...")
            mode = "tui"
        except Exception as e:
            logging.error(f"Failed to start GUI: {e}")
            logging.info("Falling back to TUI mode...")
            mode = "tui"
    
    if mode == "tui":
        try:
            from tui import StreamSeparatorTUI
            logging.info("Starting TUI mode...")
            app = StreamSeparatorTUI()
            app.run()
        except ImportError as e:
            logging.error(f"Failed to import TUI module: {e}")
            logging.error("Please install textual: pip install textual")
            sys.exit(1)
        except Exception as e:
            logging.error(f"Failed to start TUI: {e}")
            sys.exit(1)


if __name__ == "__main__":
    main()