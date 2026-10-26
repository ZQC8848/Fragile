"""Turn examples into model tensors, and model outputs back into turn-level predictions.

Input = (player text, scene context) as a sentence pair, truncating only the context. Segmentation labels
are on the player tokens only; units are pooled over the tokens that overlap their character span.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

import torch

from ..common.align import split_sentences
from ..common.labels import ACTS, CLAIMS, NORA_ANSWERS, SEG_TAGS, TOPICS
from .data import char_tags, chars_from_tokens, token_tags
from .model import ADDRESSEE_LABELS, NONE, SIDE_LABELS, TARGET_LABELS, VERB_LABELS

SEG_ID = {t: i for i, t in enumerate(SEG_TAGS)}
ACT_ID = {a: i for i, a in enumerate(ACTS)}
VERB_ID = {v: i for i, v in enumerate(VERB_LABELS)}
TARGET_ID = {t: i for i, t in enumerate(TARGET_LABELS)}
ADDR_ID = {a: i for i, a in enumerate(ADDRESSEE_LABELS)}
NORA_ID = {a: i for i, a in enumerate(NORA_ANSWERS)}
SIDE_ID = {a: i for i, a in enumerate(SIDE_LABELS)}
CHANNEL_OF_TAG = {"S": "speech", "A": "action", "E": "expression"}


@dataclass
class Encoded:
    input_ids: list[int]
    attention_mask: list[int]
    offsets: list[tuple[int, int]]   # character offsets into the player text; (0, 0) for context and special tokens
    player_mask: list[bool]


def encode_text(tok, text: str, context: str, max_length: int) -> Encoded:
    enc = tok(text, context or None, truncation="only_second" if context else True, max_length=max_length, return_offsets_mapping=True)
    seq = enc.sequence_ids()
    offs = [tuple(o) if s == 0 else (0, 0) for o, s in zip(enc["offset_mapping"], seq)]
    return Encoded(enc["input_ids"], enc["attention_mask"], offs, [s == 0 for s in seq])


def pool_weights(enc: Encoded, start: int, end: int) -> list[float]:
    w = [1.0 if pm and o[1] > start and o[0] < end else 0.0 for pm, o in zip(enc.player_mask, enc.offsets)]
    s = sum(w)
    return [x / s for x in w] if s else w


def build_item(tok, ex: dict[str, Any], max_length: int, context_dropout: float = 0.0, use_context: bool = True,
               spans: list[tuple[str, int, int]] | None = None, rng: random.Random | None = None) -> dict[str, Any]:
    """Tensors-to-be for one example. `spans` overrides the units to pool (for inference on predicted segments)."""
    rng = rng or random
    ctx = ex["context_text"] if use_context and rng.random() >= context_dropout else ""
    enc = encode_text(tok, ex["text"], ctx, max_length)
    item: dict[str, Any] = {"input_ids": enc.input_ids, "attention_mask": enc.attention_mask, "enc": enc}
    # segmentation labels on player tokens
    if ex["mask"]["seg"]:
        ct = char_tags(ex["text"], ex["segments"])
        player_offs = [o for o, pm in zip(enc.offsets, enc.player_mask) if pm]
        tt = iter(token_tags(player_offs, ct, ex["text"]))
        item["seg_labels"] = [SEG_ID[next(tt)] if pm else -100 for pm in enc.player_mask]
    else:
        item["seg_labels"] = [-100] * len(enc.input_ids)
    # units
    units = []
    if spans is None:
        if ex["mask"]["units"]:
            for u in ex["units"]:
                if u["start"] is None or u["act"] not in ACT_ID:
                    continue
                act = u.get("action") or {}
                units.append({
                    "pool": pool_weights(enc, u["start"], u["end"]), "act": ACT_ID[u["act"]],
                    "topics": [1.0 if t in (u.get("topics") or []) else 0.0 for t in TOPICS],
                    "verb": VERB_ID.get(act.get("verb", NONE), 0), "target": TARGET_ID.get(act.get("target", NONE), 0),
                    "implausible": 1.0 if u.get("implausible") else 0.0,
                })
    else:
        for ch, s, e in spans:
            units.append({"pool": pool_weights(enc, s, e), "channel": ch, "start": s, "end": e,
                          "act": 0, "topics": [0.0] * len(TOPICS), "verb": 0, "target": 0, "implausible": 0.0})
    item["units"] = [u for u in units if sum(u["pool"]) > 0]
    t = ex["turn_labels"]
    item.update({
        "addressee": ADDR_ID.get(t.get("addressee") or NONE, 0), "m_addressee": bool(ex["mask"]["addressee"]),
        "nora": NORA_ID.get(t.get("nora_answer") or "none", NORA_ID.get("none", 0)), "m_nora": bool(ex["mask"]["nora"]),
        "side": SIDE_ID.get(t.get("side_answer") or NONE, 0), "m_side": bool(ex["mask"]["side"]),
        "claims": [1.0 if c in (t.get("claims") or []) else 0.0 for c in CLAIMS],
        "suspicion": float(t.get("suspicion") or 0.0),
    })
    return item


def collate(items: list[dict[str, Any]], pad_id: int) -> dict[str, torch.Tensor]:
    T = max(len(i["input_ids"]) for i in items)
    B = len(items)
    ids = torch.full((B, T), pad_id, dtype=torch.long)
    att = torch.zeros((B, T), dtype=torch.long)
    seg = torch.full((B, T), -100, dtype=torch.long)
    pools, ub, ua, ut, uv, utg, ui = [], [], [], [], [], [], []
    for b, it in enumerate(items):
        n = len(it["input_ids"])
        ids[b, :n] = torch.tensor(it["input_ids"])
        att[b, :n] = torch.tensor(it["attention_mask"])
        seg[b, :n] = torch.tensor(it["seg_labels"])
        for u in it["units"]:
            p = torch.zeros(T)
            p[:n] = torch.tensor(u["pool"])
            pools.append(p)
            ub.append(b)
            ua.append(u["act"]); ut.append(u["topics"]); uv.append(u["verb"]); utg.append(u["target"]); ui.append(u["implausible"])
    return {
        "input_ids": ids, "attention_mask": att, "seg_labels": seg,
        "unit_pool": torch.stack(pools) if pools else torch.zeros((0, T)),
        "unit_batch": torch.tensor(ub, dtype=torch.long),
        "unit_act": torch.tensor(ua, dtype=torch.long), "unit_topics": torch.tensor(ut, dtype=torch.float).reshape(-1, len(TOPICS)),
        "unit_verb": torch.tensor(uv, dtype=torch.long), "unit_target": torch.tensor(utg, dtype=torch.long),
        "unit_implausible": torch.tensor(ui, dtype=torch.float),
        "addressee": torch.tensor([i["addressee"] for i in items]), "m_addressee": torch.tensor([i["m_addressee"] for i in items]),
        "nora": torch.tensor([i["nora"] for i in items]), "m_nora": torch.tensor([i["m_nora"] for i in items]),
        "side": torch.tensor([i["side"] for i in items]), "m_side": torch.tensor([i["m_side"] for i in items]),
        "claims": torch.tensor([i["claims"] for i in items], dtype=torch.float),
        "suspicion": torch.tensor([i["suspicion"] for i in items], dtype=torch.float),
    }


def spans_from_char_tags(text: str, ctags: list[str]) -> list[tuple[str, int, int]]:
    """Predicted units: each speech sentence is a unit; all action characters form one unit, all expression one."""
    runs: list[tuple[str, int, int]] = []
    i = 0
    while i < len(text):
        t = ctags[i]
        j = i
        while j < len(text) and (ctags[j] == t or (text[j].isspace() and j + 1 < len(text) and ctags[j + 1] == t)):
            j += 1
        if t != "O":
            runs.append((t, i, j))
        i = j
    units: list[tuple[str, int, int]] = []
    for t, s, e in runs:
        if t == "S":
            units += [("speech", a, b) for a, b in split_sentences(text, s, e)] or [("speech", s, e)]
    for tag, ch in (("A", "action"), ("E", "expression")):
        rs = [(s, e) for t, s, e in runs if t == tag]
        if rs:
            units.append((ch, rs[0][0], rs[-1][1]))
    return units


def spans_from_segments(ex: dict[str, Any]) -> list[tuple[str, int, int]]:
    return spans_from_char_tags(ex["text"], char_tags(ex["text"], ex["segments"]))


def char_tags_from_logits(item: dict[str, Any], seg_logits: torch.Tensor, text: str) -> list[str]:
    enc: Encoded = item["enc"]
    pred = seg_logits.argmax(-1).tolist()
    player_offs = [o for o, pm in zip(enc.offsets, enc.player_mask) if pm]
    tags = [SEG_TAGS[p] for p, pm in zip(pred, enc.player_mask) if pm]
    return chars_from_tokens(len(text), player_offs, tags, text)
