"""Self-play (selfplay.md): player personas, model profiles, the round manifest and its shards, the runner,
pack and check. Entry point: `uv run python -m selfplay --help`."""

from .persona import Persona, PersonaGenerator

__all__ = ["Persona", "PersonaGenerator"]
