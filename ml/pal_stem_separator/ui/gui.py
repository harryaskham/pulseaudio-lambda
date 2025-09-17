#!/usr/bin/env python3
"""
GUI for the stream separator config using tkinter (built-in to Python).
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import os
import time

from pal_stem_separator.stream_separator_args import Args

class StreamSeparatorGUI:
    """GUI for stream separator configuration."""
    
    def __init__(self):
        self.config = Args.read()
        self.last_save_time = 0
        self.save_delay = 200  # Throttle saves to max once per 200ms
        self.pending_save = None  # Track pending save timer
        
        # Create main window
        self.root = tk.Tk()
        self.root.title("Stream Separator Configuration")
        self.root.geometry("600x700")
        
        # Configure style
        style = ttk.Style()
        style.theme_use('clam')
        
        # Create UI
        self.create_widgets()
        
        # Set initial values
        self.load_config_to_ui()
    
    def create_widgets(self):
        """Create all UI widgets."""
        # Main frame with padding
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        
        # Configure grid weights
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main_frame.columnconfigure(1, weight=1)
        
        row = 0
        
        # Title
        title = ttk.Label(main_frame, text="Stream Separator Configuration", 
                         font=('TkDefaultFont', 14, 'bold'))
        title.grid(row=row, column=0, columnspan=2, pady=(0, 20))
        row += 1
        
        # Volume Controls Section
        volume_frame = ttk.LabelFrame(main_frame, text="Volume Controls", padding="10")
        volume_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        volume_frame.columnconfigure(1, weight=1)
        row += 1
        
        # Create sliders for each stem
        self.gain_vars = []
        self.gain_labels = []
        self.mute_vars = []
        self.solo_vars = []
        stems = ["Drums", "Bass", "Vocals", "Other"]
        
        for i, stem in enumerate(stems):
            # Label
            label = ttk.Label(volume_frame, text=f"{stem}:")
            label.grid(row=i*3, column=0, sticky=tk.W, pady=5)
            
            # Value label
            value_label = ttk.Label(volume_frame, text="100%")
            value_label.grid(row=i*3, column=2, sticky=tk.E, pady=5)
            self.gain_labels.append(value_label)
            
            # Slider
            var = tk.DoubleVar(value=100.0)
            slider = ttk.Scale(volume_frame, from_=0, to=200, orient=tk.HORIZONTAL,
                              variable=var, command=lambda v, idx=i: self.on_gain_change(idx, v))
            slider.grid(row=i*3, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 10))
            self.gain_vars.append(var)
            
            # Mute/Solo buttons
            button_frame = ttk.Frame(volume_frame)
            button_frame.grid(row=i*3+1, column=1, sticky=tk.W, pady=(0, 5))
            
            mute_var = tk.BooleanVar()
            mute_check = ttk.Checkbutton(button_frame, text="Mute", variable=mute_var,
                                        command=lambda idx=i: self.on_mute_change(idx))
            mute_check.pack(side=tk.LEFT, padx=(0, 10))
            self.mute_vars.append(mute_var)
            
            solo_var = tk.BooleanVar()
            solo_check = ttk.Checkbutton(button_frame, text="Solo", variable=solo_var,
                                        command=lambda idx=i: self.on_solo_change(idx))
            solo_check.pack(side=tk.LEFT)
            self.solo_vars.append(solo_var)
        
        # Reset button in volume controls
        reset_btn = ttk.Button(volume_frame, text="Reset All Volumes", command=self.reset_all_volumes)
        reset_btn.grid(row=len(stems)*3, column=0, columnspan=3, pady=(20, 10))
        
        # Processing Settings Section
        processing_frame = ttk.LabelFrame(main_frame, text="Processing Settings", padding="10")
        processing_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        processing_frame.columnconfigure(1, weight=1)
        row += 1
        
        # Chunk size slider
        ttk.Label(processing_frame, text="Chunk Size (sec):").grid(row=0, column=0, sticky=tk.W, pady=5)
        self.chunk_label = ttk.Label(processing_frame, text="2.0")
        self.chunk_label.grid(row=0, column=2, sticky=tk.E, pady=5)
        
        self.chunk_var = tk.DoubleVar(value=2.0)
        chunk_slider = ttk.Scale(processing_frame, from_=0.1, to=30.0, orient=tk.HORIZONTAL,
                                 variable=self.chunk_var, command=self.on_chunk_change)
        chunk_slider.grid(row=0, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 10))
        
        # Overlap slider
        ttk.Label(processing_frame, text="Overlap (sec):").grid(row=1, column=0, sticky=tk.W, pady=5)
        self.overlap_label = ttk.Label(processing_frame, text="0.5")
        self.overlap_label.grid(row=1, column=2, sticky=tk.E, pady=5)
        
        self.overlap_var = tk.DoubleVar(value=0.5)
        overlap_slider = ttk.Scale(processing_frame, from_=0.0, to=5.0, orient=tk.HORIZONTAL,
                                   variable=self.overlap_var, command=self.on_overlap_change)
        overlap_slider.grid(row=1, column=1, sticky=(tk.W, tk.E), pady=5, padx=(10, 10))
        
        # Empty Queues button
        empty_btn = ttk.Button(processing_frame, text="Empty Queues", command=self.empty_queues)
        empty_btn.grid(row=2, column=0, columnspan=3, pady=(10, 0))
        
        # Device selection
        device_frame = ttk.LabelFrame(main_frame, text="Device", padding="10")
        device_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        row += 1
        
        self.device_var = tk.StringVar(value="cpu")
        ttk.Radiobutton(device_frame, text="CPU", variable=self.device_var, 
                       value="cpu", command=self.on_device_change).grid(row=0, column=0, padx=10)
        ttk.Radiobutton(device_frame, text="CUDA (GPU)", variable=self.device_var, 
                       value="cuda", command=self.on_device_change).grid(row=0, column=1, padx=10)
        
        # Normalize checkbox
        self.normalize_var = tk.BooleanVar(value=False)
        normalize_check = ttk.Checkbutton(device_frame, text="Normalize output volume", 
                                        variable=self.normalize_var, command=self.on_normalize_change)
        normalize_check.grid(row=1, column=0, columnspan=2, pady=(10, 0))
        
        # Checkpoint path
        checkpoint_frame = ttk.LabelFrame(main_frame, text="Model Checkpoint", padding="10")
        checkpoint_frame.grid(row=row, column=0, columnspan=2, sticky=(tk.W, tk.E), pady=10)
        checkpoint_frame.columnconfigure(0, weight=1)
        row += 1
        
        self.checkpoint_var = tk.StringVar()
        checkpoint_entry = ttk.Entry(checkpoint_frame, textvariable=self.checkpoint_var)
        checkpoint_entry.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=5)
        checkpoint_entry.bind('<FocusOut>', lambda e: self.on_checkpoint_change())
        checkpoint_entry.bind('<Return>', lambda e: self.on_checkpoint_change())
        
        browse_btn = ttk.Button(checkpoint_frame, text="Browse...", command=self.browse_checkpoint)
        browse_btn.grid(row=0, column=1, padx=(5, 0))
        
        
        # Status bar
        self.status_label = ttk.Label(self.root, text="Ready", relief=tk.SUNKEN, anchor=tk.W)
        self.status_label.grid(row=1, column=0, sticky=(tk.W, tk.E))
    
    def load_config_to_ui(self):
        """Load the current configuration into the UI."""
        # Set gain sliders
        for i, var in enumerate(self.gain_vars):
            if i < len(self.config.gains):
                var.set(self.config.gains[i])
                self.gain_labels[i].config(text=f"{self.config.gains[i]:.0f}%")
        
        # Set mute/solo state
        for i, var in enumerate(self.mute_vars):
            if i < len(self.config.muted):
                var.set(self.config.muted[i])
        
        for i, var in enumerate(self.solo_vars):
            if i < len(self.config.soloed):
                var.set(self.config.soloed[i])
        
        # Set processing settings
        self.chunk_var.set(self.config.chunk_secs)
        self.chunk_label.config(text=f"{self.config.chunk_secs:.1f}")
        
        self.overlap_var.set(self.config.overlap_secs)
        self.overlap_label.config(text=f"{self.config.overlap_secs:.1f}")
        
        # Set device
        self.device_var.set(self.config.device)
        
        # Set normalize checkbox
        self.normalize_var.set(self.config.normalize)
        
        # Set checkpoint path
        self.checkpoint_var.set(self.config.checkpoint)
    
    def on_gain_change(self, index, value):
        """Handle gain slider change."""
        val = float(value)
        self.gain_labels[index].config(text=f"{val:.0f}%")
        if index < len(self.config.gains):
            self.config.gains[index] = val
        
        self.save_config_throttled()
    
    def on_chunk_change(self, value):
        """Handle chunk size slider change."""
        val = float(value)
        self.chunk_label.config(text=f"{val:.1f}")
        self.config.chunk_secs = val
        
        self.save_config_throttled()
    
    def on_overlap_change(self, value):
        """Handle overlap slider change."""
        val = float(value)
        self.overlap_label.config(text=f"{val:.1f}")
        self.config.overlap_secs = val
        
        self.save_config_throttled()
    
    def on_device_change(self):
        """Handle device selection change."""
        self.config.device = self.device_var.get()
        
        self.save_config_throttled()
    
    def on_normalize_change(self):
        """Handle normalize checkbox change."""
        self.config.normalize = self.normalize_var.get()
        
        self.save_config_throttled()
    
    def on_checkpoint_change(self):
        """Handle checkpoint path change."""
        self.config.checkpoint = self.checkpoint_var.get()
        
        self.save_config_throttled()
    
    def on_mute_change(self, index):
        """Handle mute checkbox change."""
        self.config.toggle_mute(index)
        
        # Update solo checkboxes if needed
        for i, var in enumerate(self.solo_vars):
            var.set(self.config.soloed[i])
        
        self.save_config_throttled()
    
    def on_solo_change(self, index):
        """Handle solo checkbox change."""
        self.config.toggle_solo(index)
        
        # Update all mute/solo checkboxes
        for i, var in enumerate(self.mute_vars):
            var.set(self.config.muted[i])
        for i, var in enumerate(self.solo_vars):
            var.set(self.config.soloed[i])
        
        self.save_config_throttled()
    
    def reset_all_volumes(self):
        """Reset all volumes to 100% and clear mute/solo state."""
        self.config.reset_volumes()
        self.load_config_to_ui()
        self.save_config()
        
        self.status_label.config(text="All volumes reset to 100%")
        # Clear status after 3 seconds
        self.root.after(3000, lambda: self.status_label.config(text="Ready"))
    
    def empty_queues(self):
        """Request emptying of audio processing queues."""
        self.config.request_empty_queues()
        self.status_label.config(text="Queue emptying requested")
        # Clear status after 3 seconds
        self.root.after(3000, lambda: self.status_label.config(text="Ready"))
    
    def browse_checkpoint(self):
        """Open file browser for checkpoint selection."""
        # Get initial directory from current path
        current = self.checkpoint_var.get()
        if current and current.startswith("~"):
            current = os.path.expanduser(current)
        
        initial_dir = os.path.dirname(current) if current and os.path.exists(os.path.dirname(current)) else os.path.expanduser("~")
        
        filename = filedialog.askopenfilename(
            title="Select Checkpoint File",
            initialdir=initial_dir,
            filetypes=[("PyTorch Checkpoints", "*.pt *.pth"), ("All Files", "*.*")]
        )
        
        if filename:
            # Convert to relative path with ~ if in home directory
            home = os.path.expanduser("~")
            if filename.startswith(home):
                filename = "~" + filename[len(home):]
            
            self.checkpoint_var.set(filename)
            self.on_checkpoint_change()
    
    def save_config_throttled(self):
        """Save config with throttling to prevent excessive writes during slider drags."""
        current_time = time.time() * 1000  # Convert to milliseconds for tkinter
        
        # Cancel any pending save
        if self.pending_save:
            self.root.after_cancel(self.pending_save)
            self.pending_save = None
        
        if current_time - self.last_save_time >= self.save_delay:
            self.save_config()
            self.last_save_time = current_time
        else:
            # Schedule a delayed save
            delay = int(self.save_delay - (current_time - self.last_save_time))
            self.pending_save = self.root.after(delay, self.save_config)
    
    def save_config(self):
        """Save the current configuration."""
        try:
            self.config.save()
            self.last_save_time = time.time() * 1000
            self.status_label.config(text="Configuration saved")
            # Clear status after 3 seconds
            self.root.after(3000, lambda: self.status_label.config(text="Ready"))
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to save configuration: {e}")
            self.status_label.config(text=f"Save failed: {e}")
    
    def run(self):
        """Run the GUI."""
        self.root.mainloop()


if __name__ == "__main__":
    app = StreamSeparatorGUI()
    app.run()
