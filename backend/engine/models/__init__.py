"""Runtime adapters for the four trainable modules (backend-design.md §7.1-7.2): each has rule, llm and
trained paths behind one interface, chosen by MODEL_<MODULE>, with optional shadow mode."""

from .base import PATHS, SlotRun, path_from_env, shadow_from_env
from .encoder import Encoder, EncoderOutput
from .guard import Guard, GuardContext
from .scorer import Candidate, ScoreResult, ScoringContext, make_scorers
from .tension import TensionEstimator

__all__ = [
    "PATHS",
    "Candidate",
    "Encoder",
    "EncoderOutput",
    "Guard",
    "GuardContext",
    "ScoreResult",
    "ScoringContext",
    "SlotRun",
    "TensionEstimator",
    "make_scorers",
    "path_from_env",
    "shadow_from_env",
]
