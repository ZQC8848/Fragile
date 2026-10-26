"""Rung 4: one multilingual encoder (mDeBERTa-v3-base) with heads at three levels.

  token level   segmentation of the player text: O / S / A / E               cross-entropy
  unit level    mean-pooled over each unit's character span:
                  act (27), topics (6, multi-label), verb (27 + none),
                  target (+ none), implausible                                 CE / sigmoid BCE
  turn level    on the first token ([CLS]), the mean of the player-text tokens, or both concatenated (--turn-pool):
                  addressee (5 + none), suspicion (0-3), claims (10, multi-label),
                  nora answer (3), side answer (julian / mia / none)          CE / BCE / MSE

Every head's loss is masked where its label is absent (e.g. nora_answer outside a call with Nora).
The losses are summed with equal weight, or with learned uncertainty weights (Kendall et al. 2018).
"""

from __future__ import annotations

from dataclasses import dataclass

import torch
import torch.nn as nn
import torch.nn.functional as F
from transformers import AutoModel

from ..common.labels import ACTION_TABLE, ACTS, ADDRESSEES, CLAIMS, NORA_ANSWERS, SEG_TAGS, SIDE_ANSWERS, TOPICS, VERBS

NONE = "none"
VERB_LABELS = [NONE, *VERBS]
TARGET_LABELS = [NONE, *sorted(ACTION_TABLE["target_rooms"])]
ADDRESSEE_LABELS = [NONE, *ADDRESSEES]
SIDE_LABELS = [NONE, *SIDE_ANSWERS]
HEADS = ("seg", "act", "topics", "verb", "target", "implausible", "addressee", "suspicion", "claims", "nora", "side")


@dataclass
class HeadSizes:
    seg: int = len(SEG_TAGS)
    act: int = len(ACTS)
    topics: int = len(TOPICS)
    verb: int = len(VERB_LABELS)
    target: int = len(TARGET_LABELS)
    addressee: int = len(ADDRESSEE_LABELS)
    claims: int = len(CLAIMS)
    nora: int = len(NORA_ANSWERS)
    side: int = len(SIDE_LABELS)


TURN_POOLS = ("cls", "mean", "both")


def _mlp(d: int, out: int, dropout: float, d_in: int | None = None) -> nn.Module:
    return nn.Sequential(nn.Dropout(dropout), nn.Linear(d_in or d, d), nn.GELU(), nn.Dropout(dropout), nn.Linear(d, out))


class MultiHeadEncoder(nn.Module):
    def __init__(self, encoder: nn.Module, heads: tuple[str, ...] = HEADS, dropout: float = 0.1, uncertainty: bool = False,
                 turn_pool: str = "cls"):
        super().__init__()
        self.encoder = encoder
        d = encoder.config.hidden_size
        dt = 2 * d if turn_pool == "both" else d  # input size of the turn-level heads
        self.turn_pool = turn_pool
        s = HeadSizes()
        self.heads = set(heads)
        self.seg = nn.Sequential(nn.Dropout(dropout), nn.Linear(d, s.seg))
        self.act, self.topics = _mlp(d, s.act, dropout), _mlp(d, s.topics, dropout)
        self.verb, self.target = _mlp(d, s.verb, dropout), _mlp(d, s.target, dropout)
        self.implausible = _mlp(d, 1, dropout)
        self.addressee, self.claims = _mlp(d, s.addressee, dropout, dt), _mlp(d, s.claims, dropout, dt)
        self.nora, self.side = _mlp(d, s.nora, dropout, dt), _mlp(d, s.side, dropout, dt)
        self.suspicion = _mlp(d, 1, dropout, dt)
        self.uncertainty = uncertainty
        if uncertainty:  # log sigma^2 per head (Kendall, Gal & Cipolla 2018)
            self.log_vars = nn.ParameterDict({h: nn.Parameter(torch.zeros(())) for h in HEADS})

    @classmethod
    def from_pretrained(cls, name: str, **kw) -> "MultiHeadEncoder":
        return cls(AutoModel.from_pretrained(name), **kw)

    def forward(self, input_ids, attention_mask, unit_pool, unit_batch, token_type_ids=None, player_mask=None):
        """unit_pool: (n_units, seq) weights summing to 1 over each unit's tokens; unit_batch: (n_units,) example index;
        player_mask: (B, seq) True on the player-text tokens, needed unless turn_pool is "cls"."""
        kw = {"input_ids": input_ids, "attention_mask": attention_mask}
        if token_type_ids is not None:
            kw["token_type_ids"] = token_type_ids
        h = self.encoder(**kw).last_hidden_state  # (B, T, d)
        turn = h[:, 0]
        if self.turn_pool != "cls":
            w = player_mask.to(h.dtype)
            mean = torch.einsum("bt,btd->bd", w, h) / w.sum(1, keepdim=True).clamp(min=1)
            turn = mean if self.turn_pool == "mean" else torch.cat([turn, mean], -1)
        out = {
            "seg": self.seg(h),
            "addressee": self.addressee(turn), "claims": self.claims(turn), "nora": self.nora(turn),
            "side": self.side(turn), "suspicion": self.suspicion(turn).squeeze(-1),
        }
        if unit_pool.shape[0]:
            u = torch.einsum("nt,ntd->nd", unit_pool.to(h.dtype), h[unit_batch])
        else:
            u = h.new_zeros((0, h.shape[-1]))
        out.update({"act": self.act(u), "topics": self.topics(u), "verb": self.verb(u), "target": self.target(u),
                    "implausible": self.implausible(u).squeeze(-1)})
        return out

    def loss(self, out: dict, batch: dict) -> tuple[torch.Tensor, dict[str, float]]:
        parts: dict[str, torch.Tensor] = {}
        if "seg" in self.heads and (batch["seg_labels"] != -100).any():
            parts["seg"] = F.cross_entropy(out["seg"].float().flatten(0, 1), batch["seg_labels"].flatten(), ignore_index=-100)
        if batch["unit_act"].numel():
            if "act" in self.heads:
                parts["act"] = F.cross_entropy(out["act"].float(), batch["unit_act"])
            if "topics" in self.heads:
                parts["topics"] = F.binary_cross_entropy_with_logits(out["topics"].float(), batch["unit_topics"])
            if "verb" in self.heads:
                parts["verb"] = F.cross_entropy(out["verb"].float(), batch["unit_verb"])
            if "target" in self.heads:
                parts["target"] = F.cross_entropy(out["target"].float(), batch["unit_target"])
            if "implausible" in self.heads:
                parts["implausible"] = F.binary_cross_entropy_with_logits(out["implausible"].float(), batch["unit_implausible"])
        for head, lab, m in (("addressee", "addressee", "m_addressee"), ("nora", "nora", "m_nora"), ("side", "side", "m_side")):
            if head in self.heads and batch[m].any():
                parts[head] = F.cross_entropy(out[head].float()[batch[m]], batch[lab][batch[m]])
        if "claims" in self.heads:
            parts["claims"] = F.binary_cross_entropy_with_logits(out["claims"].float(), batch["claims"])
        if "suspicion" in self.heads:
            parts["suspicion"] = F.mse_loss(out["suspicion"].float(), batch["suspicion"]) / 3.0
        total = out["seg"].new_zeros((), dtype=torch.float32)
        for h, l in parts.items():
            if self.uncertainty:
                lv = self.log_vars[h]
                total = total + torch.exp(-lv) * l + lv
            else:
                total = total + l
        return total, {h: float(l.detach()) for h, l in parts.items()}
