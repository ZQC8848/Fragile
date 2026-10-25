"""Label sets for task 2, read from labels.json (exported from schemas/llm/review.json by gen/export_meta.py).

Standard library only: this module is imported both by the generator (uv, Python 3.12+) and by the
training code on CARC (Python 3.11, no engine).
"""

from __future__ import annotations

import json
from pathlib import Path

_HERE = Path(__file__).resolve().parent

#: bump when the raw-record or example format changes
SCHEMA_VERSION = 1

_LABELS = json.loads((_HERE / "labels.json").read_text(encoding="utf-8"))
ACTS: list[str] = _LABELS["acts"]
ADDRESSEES: list[str] = _LABELS["addressees"]
TOPICS: list[str] = _LABELS["topics"]
VERBS: list[str] = _LABELS["verbs"]
CHANNELS: list[str] = _LABELS["channels"]
CLAIMS: list[str] = _LABELS["claims"]
VALIDITY: list[str] = _LABELS["validity"]
NORA_ANSWERS: list[str] = _LABELS["nora_answer"]
SIDE_ANSWERS: list[str] = _LABELS["side_answer"]

#: the 10 acts that only exist in this story; the rare classes the CLIP-style head is for
STORY_ACTS = [a for a in ACTS if a.startswith(("ask_about_", "mention_", "accuse_")) or a in ("threaten_to_tell", "promise_silence")]

ACTION_TABLE = json.loads((_HERE / "action_table.json").read_text(encoding="utf-8"))
#: segmentation tags; quotation marks and whitespace between segments are "O"
SEG_TAGS = ["O", "S", "A", "E"]
CHANNEL_TAG = {"speech": "S", "action": "A", "expression": "E"}
TAG_CHANNEL = {v: k for k, v in CHANNEL_TAG.items()}

#: the fixed label of a silent turn (no teacher call is made for silence)
SILENCE_UNIT = {"channel": "speech", "text": "", "act": "silence", "addressee": None, "topics": [], "action": None, "implausible": False}
