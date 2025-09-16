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
    normalize: bool = False
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
    
