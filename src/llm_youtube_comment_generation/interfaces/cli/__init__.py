"""The command line interface."""

__all__ = ["main"]


def main(*args, **kwargs):
    """Load the command module only when the compatibility function is used."""

    from .main import main as run

    return run(*args, **kwargs)
