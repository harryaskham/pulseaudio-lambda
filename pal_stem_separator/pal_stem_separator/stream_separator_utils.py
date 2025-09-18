import os

def expand_path(path):
    return os.path.expandvars(os.path.expanduser(path))

def get_stem_name(self, index: int) -> str:
    """Get the name of a stem by index."""
    names = ["Drums", "Bass", "Vocals", "Other"]
    return names[index] if 0 <= index < len(names) else f"Stem {index}"
