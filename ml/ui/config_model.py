#!/usr/bin/env python3
"""
Shared config model for reading/writing the stream separator configuration.
"""

import json
import os
import dataclasses
from pathlib import Path
from typing import List, Optional
import logging

@dataclasses.dataclass
class StreamSeparatorConfig:
    """Configuration for the stream separator."""
    gains: List[float] = dataclasses.field(default_factory=lambda: [100.0, 100.0, 100.0, 100.0])
    muted: List[bool] = dataclasses.field(default_factory=lambda: [False, False, False, False])
    soloed: List[bool] = dataclasses.field(default_factory=lambda: [False, False, False, False])
    device: str = "cpu"
    chunk_secs: float = 2.0
    overlap_secs: float = 0.5
    checkpoint: str = "~/cosmos/projects/pulseaudio-lambda/ml/checkpoint.pt"
    watch: bool = False
    
    @classmethod
    def get_config_path(cls) -> Path:
        """Get the config file path, checking environment variable first."""
        # Check environment variable
        env_dir = os.environ.get('PA_LAMBDA_CONFIG_DIR')
        if env_dir:
            config_path = Path(env_dir) / 'stream_separator_config.json'
        else:
            # Default to ~/.config/pulseaudio-lambda/
            config_path = Path.home() / '.config' / 'pulseaudio-lambda' / 'stream_separator_config.json'
        
        # Ensure directory exists
        config_path.parent.mkdir(parents=True, exist_ok=True)
        return config_path
    
    @classmethod
    def load(cls) -> 'StreamSeparatorConfig':
        """Load config from file, creating default if it doesn't exist."""
        config_path = cls.get_config_path()
        
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    data = json.load(f)
                    return cls(**data)
            except Exception as e:
                logging.warning(f"Failed to load config from {config_path}: {e}")
                return cls()
        else:
            # Create default config
            config = cls()
            config.save()
            return config
    
    def save(self) -> None:
        """Save config to file."""
        config_path = self.get_config_path()
        
        try:
            with open(config_path, 'w') as f:
                json.dump(dataclasses.asdict(self), f, indent=4)
            logging.debug(f"Saved config to {config_path}")
            
        except Exception as e:
            logging.error(f"Failed to save config to {config_path}: {e}")
    
    def get_stem_name(self, index: int) -> str:
        """Get the name of a stem by index."""
        names = ["Drums", "Bass", "Vocals", "Other"]
        return names[index] if 0 <= index < len(names) else f"Stem {index}"
    
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