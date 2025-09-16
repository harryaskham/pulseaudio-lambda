#!/usr/bin/env python3
"""
TUI (Terminal User Interface) for the stream separator config.
Uses Textual for a modern TUI with mouse support.
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Label, Input, Button, Static, RadioSet, RadioButton
from textual.widget import Widget
from textual.reactive import reactive
from textual import events
from textual.message import Message
import asyncio
import time
from config_model import StreamSeparatorConfig

class Slider(Widget):
    """A custom slider widget with mouse support."""
    
    value = reactive(50.0)
    min_value = reactive(0.0)
    max_value = reactive(100.0)
    step = reactive(1.0)
    
    class Changed(Message):
        """Message sent when slider value changes."""
        def __init__(self, value: float) -> None:
            super().__init__()
            self.value = value
    
    def __init__(self, value: float = 50.0, min_value: float = 0.0, 
                 max_value: float = 100.0, step: float = 1.0, **kwargs):
        super().__init__(**kwargs)
        self.value = value
        self.min_value = min_value
        self.max_value = max_value
        self.step = step
    
    def render(self) -> str:
        """Render the slider."""
        width = self.size.width - 2
        if width <= 0:
            return ""
        
        # Calculate position
        range_val = self.max_value - self.min_value
        if range_val == 0:
            pos = 0
        else:
            pos = int((self.value - self.min_value) / range_val * width)
        pos = max(0, min(width - 1, pos))
        
        # Build slider string
        bar = "─" * width
        bar = bar[:pos] + "●" + bar[pos+1:]
        return f"[{bar}]"
    
    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Handle mouse click on slider."""
        if event.button == 1:  # Left button
            self._update_from_mouse(event.x)
    
    def on_mouse_move(self, event: events.MouseMove) -> None:
        """Handle mouse drag on slider."""
        if event.button == 1:  # Left button pressed
            self._update_from_mouse(event.x)
    
    def _update_from_mouse(self, x: int) -> None:
        """Update value from mouse position."""
        width = self.size.width - 2
        if width <= 0:
            return
        
        # Calculate value from position
        x = max(1, min(width, x - 1))
        range_val = self.max_value - self.min_value
        new_value = self.min_value + (x / width) * range_val
        
        # Round to step
        if self.step > 0:
            new_value = round(new_value / self.step) * self.step
        
        # Clamp and set
        self.value = max(self.min_value, min(self.max_value, new_value))
        self.post_message(self.Changed(self.value))
    
    def on_key(self, event: events.Key) -> None:
        """Handle keyboard input."""
        if event.key == "left":
            self.value = max(self.min_value, self.value - self.step)
            self.post_message(self.Changed(self.value))
        elif event.key == "right":
            self.value = min(self.max_value, self.value + self.step)
            self.post_message(self.Changed(self.value))


class SliderWithLabel(Container):
    """A slider with a label showing its value."""
    
    def __init__(self, label: str, value: float = 50.0, min_value: float = 0.0,
                 max_value: float = 100.0, step: float = 1.0, format_str: str = "{:.0f}",
                 **kwargs):
        super().__init__(**kwargs)
        self.label_text = label
        self.format_str = format_str
        self.slider = Slider(value=value, min_value=min_value, 
                            max_value=max_value, step=step)
        self.label = Label(f"{label}: {format_str.format(value)}")
    
    def compose(self) -> ComposeResult:
        with Horizontal():
            yield self.label
            yield self.slider
    
    def on_slider_changed(self, message: Slider.Changed) -> None:
        """Update label when slider changes."""
        self.label.update(f"{self.label_text}: {self.format_str.format(message.value)}")
    
    @property
    def value(self) -> float:
        return self.slider.value
    
    @value.setter
    def value(self, val: float) -> None:
        self.slider.value = val
        self.label.update(f"{self.label_text}: {self.format_str.format(val)}")


class StreamSeparatorTUI(App):
    """TUI for stream separator configuration."""
    
    CSS = """
    Screen {
        background: $surface;
    }
    
    #container {
        padding: 1 2;
        background: $surface;
    }
    
    .section {
        height: auto;
        margin: 1 0;
        padding: 1;
        border: solid $primary;
    }
    
    .section-title {
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    
    SliderWithLabel {
        height: 3;
        margin: 0 0 1 0;
    }
    
    SliderWithLabel Label {
        width: 20;
        padding: 1 0;
    }
    
    SliderWithLabel Slider {
        width: 1fr;
        padding: 1 0;
        background: $panel;
    }
    
    Slider:focus {
        background: $panel-lighten-1;
    }
    
    RadioSet {
        height: auto;
        margin: 1 0;
    }
    
    Input {
        margin: 1 0;
    }
    
    #save-button {
        dock: bottom;
        height: 3;
        background: $success;
        color: $text;
        margin: 1 0;
    }
    
    #save-button:hover {
        background: $success-lighten-1;
    }
    """
    
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("s", "save", "Save"),
    ]
    
    def __init__(self):
        super().__init__()
        self.config = StreamSeparatorConfig.load()
        self.sliders = {}
        self.device_radio = None
        self.checkpoint_input = None
        self.auto_save = True
        self.last_save_time = 0
        self.save_delay = 0.2  # Throttle saves to max once per 200ms
    
    def compose(self) -> ComposeResult:
        """Create the UI layout."""
        yield Header(show_clock=True)
        yield Footer()
        
        with ScrollableContainer(id="container"):
            # Volume controls section
            with Container(classes="section"):
                yield Label("Volume Controls", classes="section-title")
                
                stems = ["Drums", "Bass", "Vocals", "Other"]
                for i, stem in enumerate(stems):
                    slider = SliderWithLabel(
                        stem,
                        value=self.config.gains[i],
                        min_value=0.0,
                        max_value=200.0,
                        step=1.0,
                        format_str="{:.0f}%",
                        id=f"gain_{i}"
                    )
                    self.sliders[f"gain_{i}"] = slider
                    yield slider
            
            # Processing settings section
            with Container(classes="section"):
                yield Label("Processing Settings", classes="section-title")
                
                # Chunk size slider
                chunk_slider = SliderWithLabel(
                    "Chunk Size (sec)",
                    value=self.config.chunk_secs,
                    min_value=0.1,
                    max_value=60.0,
                    step=0.1,
                    format_str="{:.1f}",
                    id="chunk_secs"
                )
                self.sliders["chunk_secs"] = chunk_slider
                yield chunk_slider
                
                # Overlap slider
                overlap_slider = SliderWithLabel(
                    "Overlap (sec)",
                    value=self.config.overlap_secs,
                    min_value=0.0,
                    max_value=5.0,
                    step=0.1,
                    format_str="{:.1f}",
                    id="overlap_secs"
                )
                self.sliders["overlap_secs"] = overlap_slider
                yield overlap_slider
                
                # Device selection
                yield Label("Device:")
                with RadioSet(id="device"):
                    yield RadioButton("CPU", value=self.config.device == "cpu")
                    yield RadioButton("CUDA", value=self.config.device == "cuda")
            
            # Checkpoint path section
            with Container(classes="section"):
                yield Label("Model Checkpoint", classes="section-title")
                self.checkpoint_input = Input(
                    value=self.config.checkpoint,
                    placeholder="Path to checkpoint file",
                    id="checkpoint"
                )
                yield self.checkpoint_input
            
            # Save button
            yield Button("Save Configuration", variant="success", id="save-button")
    
    def on_slider_changed(self, message: Slider.Changed) -> None:
        """Handle slider value changes."""
        if self.auto_save:
            self.save_config_throttled()
    
    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Handle device selection change."""
        if event.radio_set.id == "device":
            self.config.device = "cuda" if event.index == 1 else "cpu"
            if self.auto_save:
                self.save_config_throttled()
    
    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle input field changes."""
        if event.input.id == "checkpoint":
            self.config.checkpoint = event.value
            if self.auto_save:
                self.save_config_throttled()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-button":
            self.save_config()
            self.notify("Configuration saved!")
    
    def save_config_throttled(self) -> None:
        """Save config with throttling to prevent excessive writes during slider drags."""
        current_time = time.time()
        if current_time - self.last_save_time >= self.save_delay:
            self.save_config()
            self.last_save_time = current_time
        else:
            # Schedule a delayed save
            self.set_timer(self.save_delay, self._delayed_save)
    
    def _delayed_save(self) -> None:
        """Callback for delayed save timer."""
        self.save_config()
    
    def save_config(self) -> None:
        """Save the current configuration."""
        # Update gains from sliders
        for i in range(4):
            slider_id = f"gain_{i}"
            if slider_id in self.sliders:
                self.config.gains[i] = self.sliders[slider_id].value
        
        # Update other settings from sliders
        if "chunk_secs" in self.sliders:
            self.config.chunk_secs = self.sliders["chunk_secs"].value
        if "overlap_secs" in self.sliders:
            self.config.overlap_secs = self.sliders["overlap_secs"].value
        
        # Save to file atomically
        self.config.save()
        self.last_save_time = time.time()
    
    def action_save(self) -> None:
        """Save action from keybinding."""
        self.save_config()
        self.notify("Configuration saved!")
    
    def action_quit(self) -> None:
        """Quit the application."""
        self.save_config()
        self.exit()


if __name__ == "__main__":
    app = StreamSeparatorTUI()
    app.run()