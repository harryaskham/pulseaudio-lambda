import logging
from pal_stem_separator.ui.web import StreamSeparatorWebGUI
from pal_stem_separator.ui.tui import StreamSeparatorTUI

def run_gui():
    logging.info("Starting GUI mode...")
    StreamSeparatorWebGUI().run()

def run_tui():
    logging.info("Starting TUI mode...")
    StreamSeparatorTUI().run()
