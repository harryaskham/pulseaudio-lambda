#!/usr/bin/env python3
"""
TUI (Terminal User Interface) for the stream separator config.
Uses Textual for a modern TUI with mouse support.
"""

from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical, ScrollableContainer
from textual.widgets import Header, Footer, Label, Input, Button, Static, RadioSet, RadioButton, Checkbox
from textual.widget import Widget
from textual.reactive import reactive
from textual import events
from textual.message import Message
import asyncio
import time

from stream_separator_args import Args

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


class StemControl(Container):
    """A complete stem control with slider, mute, and solo buttons."""
    
    def __init__(self, stem_name: str, value: float = 100.0, muted: bool = False, 
                 soloed: bool = False, stem_index: int = 0, **kwargs):
        super().__init__(**kwargs)
        self.stem_name = stem_name
        self.stem_index = stem_index
        self.slider = SliderWithLabel(
            stem_name,
            value=value,
            min_value=0.0,
            max_value=200.0,
            step=1.0,
            format_str="{:.0f}%"
        )
        
    def compose(self) -> ComposeResult:
        with Vertical():
            yield self.slider
            with Horizontal():
                yield Button("M", variant="error" if self.muted else "default", 
                           id=f"mute_{self.stem_index}")
                yield Button("S", variant="warning" if self.soloed else "default", 
                           id=f"solo_{self.stem_index}")
    
    @property
    def value(self) -> float:
        return self.slider.value
    
    @value.setter 
    def value(self, val: float) -> None:
        self.slider.value = val
    
    @property
    def muted(self) -> bool:
        return getattr(self, '_muted', False)
    
    @muted.setter
    def muted(self, val: bool) -> None:
        self._muted = val
        mute_btn = self.query_one(f"#mute_{self.stem_index}")
        mute_btn.variant = "error" if val else "default"
    
    @property
    def soloed(self) -> bool:
        return getattr(self, '_soloed', False)
    
    @soloed.setter
    def soloed(self, val: bool) -> None:
        self._soloed = val
        solo_btn = self.query_one(f"#solo_{self.stem_index}")
        solo_btn.variant = "warning" if val else "default"


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
    ]
    
    def __init__(self):
        super().__init__()
        self.config = Args.read()
        self.stem_controls = {}
        self.sliders = {}
        self.device_radio = None
        self.checkpoint_input = None
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
                    stem_control = StemControl(
                        stem,
                        value=self.config.gains[i],
                        muted=self.config.muted[i],
                        soloed=self.config.soloed[i],
                        stem_index=i,
                        id=f"stem_{i}"
                    )
                    self.stem_controls[f"stem_{i}"] = stem_control
                    yield stem_control
                
                # Reset button
                yield Button("Reset All Volumes", variant="primary", id="reset-volumes")
            
            # Processing settings section
            with Container(classes="section"):
                yield Label("Processing Settings", classes="section-title")
                
                # Chunk size slider
                chunk_slider = SliderWithLabel(
                    "Chunk Size (sec)",
                    value=self.config.chunk_secs,
                    min_value=0.1,
                    max_value=30.0,
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
                
                # Normalize checkbox
                yield Checkbox("Normalize output volume", value=self.config.normalize, id="normalize")
            
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
    
    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle checkbox changes."""
        if event.checkbox.id == "normalize":
            self.config.normalize = event.value
            if self.auto_save:
                self.save_config_throttled()
    
    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "save-button":
            self.save_config()
            self.notify("Configuration saved!")
        elif event.button.id == "reset-volumes":
            self.reset_all_volumes()
        elif event.button.id.startswith("mute_"):
            stem_index = int(event.button.id.split("_")[1])
            self.toggle_mute(stem_index)
        elif event.button.id.startswith("solo_"):
            stem_index = int(event.button.id.split("_")[1])
            self.toggle_solo(stem_index)
    
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
        # Update gains from stem controls
        for i in range(4):
            stem_id = f"stem_{i}"
            if stem_id in self.stem_controls:
                self.config.gains[i] = self.stem_controls[stem_id].value
        
        # Update other settings from sliders
        if "chunk_secs" in self.sliders:
            self.config.chunk_secs = self.sliders["chunk_secs"].value
        if "overlap_secs" in self.sliders:
            self.config.overlap_secs = self.sliders["overlap_secs"].value
        
        # Save to file
        self.config.save()
        self.last_save_time = time.time()
    
    def reset_all_volumes(self) -> None:
        """Reset all volumes to 100% and clear mute/solo state."""
        self.config.reset_volumes()
        
        # Update UI to reflect changes
        for i in range(4):
            stem_id = f"stem_{i}"
            if stem_id in self.stem_controls:
                stem_control = self.stem_controls[stem_id]
                stem_control.value = 100.0
                stem_control.muted = False
                stem_control.soloed = False
        
        self.save_config()
        self.notify("All volumes reset to 100%")
    
    def toggle_mute(self, stem_index: int) -> None:
        """Toggle mute state for a stem."""
        self.config.toggle_mute(stem_index)
        
        # Update UI
        stem_id = f"stem_{stem_index}"
        if stem_id in self.stem_controls:
            self.stem_controls[stem_id].muted = self.config.muted[stem_index]
            self.stem_controls[stem_id].soloed = self.config.soloed[stem_index]
        
        self.save_config()
    
    def toggle_solo(self, stem_index: int) -> None:
        """Toggle solo state for a stem."""
        self.config.toggle_solo(stem_index)
        
        # Update UI for all stems (solo affects all other stems)
        for i in range(4):
            stem_id = f"stem_{i}"
            if stem_id in self.stem_controls:
                self.stem_controls[stem_id].muted = self.config.muted[i]
                self.stem_controls[stem_id].soloed = self.config.soloed[i]
        
        self.save_config()
    
    def action_quit(self) -> None:
        """Quit the application."""
        self.save_config()
        self.exit()


if __name__ == "__main__":
    app = StreamSeparatorTUI()
    app.run()
