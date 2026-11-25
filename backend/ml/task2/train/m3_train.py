"""Train and evaluate the M3 guard perception model: one mDeBERTa encoder, three heads, plus offending-span tagging.

Input per segment: "[kind:speaker] text" </s> "player: ... || scene: ... || before: ..." (m3_data.context_text).
Heads, on [CLS] concatenated with the mean of the segment's tokens:
  facts          10-way multi-label: which secret facts the segment states            BCE
  overreach      the segment speaks or acts for the player beyond their input          BCE, positive weight
  contradiction  the segment contradicts the scene, the setting or the previous passage BCE, positive weight
and per token of the segment: in the overreach span / in the contradiction span (BCE, positives of that head only).
The game's verdict comes from these by rule (m3_data.compose); the model never sees the allowed facts.

    python -m ml.task2.train.m3_train --data DATA --out RUNS --name m3_rung4_s0 --seed 0 [--save-model]
    python -m ml.task2.train.m3_train --data DATA --out RUNS --name smoke --smoke        (tiny random encoder, CPU)
Model selection on val: mean of facts micro-F1, overreach AP and contradiction AP.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
import torch.nn as nn
import torch.nn.functional as F
import transformers
from transformers import AutoConfig, AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

from .m3_data import BINARY, FACTS, context_text, load_splits, seg_text
from .m3_metrics import average_precision, evaluate, score

HEADS = ("facts", "overreach", "contradiction", "span")


def _mlp(d_in: int, d: int, out: int, p: float) -> nn.Module:
    return nn.Sequential(nn.Dropout(p), nn.Linear(d_in, d), nn.GELU(), nn.Dropout(p), nn.Linear(d, out))


class GuardEncoder(nn.Module):
    def __init__(self, encoder: nn.Module, dropout: float = 0.1, pos_weight: dict[str, float] | None = None,
                 heads: tuple[str, ...] = HEADS):
        super().__init__()
        self.encoder = encoder
        d = encoder.config.hidden_size
        self.heads = set(heads)
        self.facts = _mlp(2 * d, d, len(FACTS), dropout)
        self.overreach = _mlp(2 * d, d, 1, dropout)
        self.contradiction = _mlp(2 * d, d, 1, dropout)
        self.span = nn.Sequential(nn.Dropout(dropout), nn.Linear(d, 2))  # [overreach, contradiction]
        self.pos_weight = dict(pos_weight or {})

    def forward(self, input_ids, attention_mask, seg_mask):
        h = self.encoder(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
        w = seg_mask.to(h.dtype)
        mean = torch.einsum("bt,btd->bd", w, h) / w.sum(1, keepdim=True).clamp(min=1)
        z = torch.cat([h[:, 0], mean], -1)
        return {"facts": self.facts(z), "overreach": self.overreach(z).squeeze(-1),
                "contradiction": self.contradiction(z).squeeze(-1), "span": self.span(h)}

    def loss(self, out, b) -> tuple[torch.Tensor, dict[str, float]]:
        parts = {}
        if "facts" in self.heads:
            parts["facts"] = F.binary_cross_entropy_with_logits(out["facts"].float(), b["facts"])
        for j, hd in enumerate(BINARY):
            if hd in self.heads:
                pw = torch.tensor(self.pos_weight.get(hd, 1.0), device=b[hd].device)
                parts[hd] = F.binary_cross_entropy_with_logits(out[hd].float(), b[hd], pos_weight=pw)
            m = b["span_labels"][..., j] != -100
            if "span" in self.heads and m.any():
                parts[f"span_{hd}"] = F.binary_cross_entropy_with_logits(out["span"][..., j].float()[m], b["span_labels"][..., j][m].float())
        total = sum(parts.values()) if parts else out["facts"].new_zeros(())
        return total, {k: float(v.detach()) for k, v in parts.items()}


def encode(tok, ex: dict, max_length: int) -> dict:
    s = seg_text(ex)
    prefix = len(s) - len(ex["text"])
    enc = tok(s, context_text(ex), truncation="only_second", max_length=max_length, return_offsets_mapping=True)
    seq = enc.sequence_ids()
    seg_mask = [sid == 0 for sid in seq]
    offs = [(a - prefix, b - prefix) if sid == 0 else (0, 0) for (a, b), sid in zip(enc["offset_mapping"], seq)]
    lab = ex["labels"]
    span_labels = []
    for (a, b_), on in zip(offs, seg_mask):
        row = []
        for hd in BINARY:
            sp = lab.get(f"{hd}_span") if lab[hd] else None
            if not on or not lab[hd] or sp is None or b_ <= 0:
                row.append(-100 if not (on and lab[hd] and sp is not None) else 0)
            else:
                row.append(int(a < sp[1] and b_ > sp[0]))
        span_labels.append(row)
    return {"input_ids": enc["input_ids"], "seg_mask": seg_mask, "offs": offs, "span_labels": span_labels,
            "facts": [float(f in lab["facts"]) for f in FACTS], "overreach": float(lab["overreach"]),
            "contradiction": float(lab["contradiction"])}


def collate(items: list[dict], pad: int) -> dict:
    T = max(len(i["input_ids"]) for i in items)
    def padded(key, fill):
        return [i[key] + [fill] * (T - len(i[key])) for i in items]
    return {
        "input_ids": torch.tensor(padded("input_ids", pad)),
        "attention_mask": torch.tensor([[1] * len(i["input_ids"]) + [0] * (T - len(i["input_ids"])) for i in items]),
        "seg_mask": torch.tensor(padded("seg_mask", False)),
        "span_labels": torch.tensor([i["span_labels"] + [[-100, -100]] * (T - len(i["span_labels"])) for i in items]),
        "facts": torch.tensor([i["facts"] for i in items]),
        "overreach": torch.tensor([i["overreach"] for i in items]),
        "contradiction": torch.tensor([i["contradiction"] for i in items]),
    }


def spans_from_probs(item: dict, probs: list[float], text_len: int, thr: float = 0.5) -> list[list[int]]:
    out: list[list[int]] = []
    for (a, b), on, p in zip(item["offs"], item["seg_mask"], probs):
        if not on or b <= 0 or p < thr:
            continue
        a = max(0, a)
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], min(b, text_len))
        else:
            out.append([a, min(b, text_len)])
    return out


@torch.no_grad()
def predict(model, tok, exs, args, device) -> list[dict]:
    model.eval()
    use_bf16 = device.type == "cuda" and torch.cuda.is_bf16_supported()
    preds = []
    for i in range(0, len(exs), args.eval_batch):
        chunk = exs[i:i + args.eval_batch]
        items = [encode(tok, e, args.max_length) for e in chunk]
        b = {k: v.to(device) for k, v in collate(items, tok.pad_token_id).items()}
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
            out = model(b["input_ids"], b["attention_mask"], b["seg_mask"])
        pf = out["facts"].float().sigmoid().cpu()
        po, pc = out["overreach"].float().sigmoid().cpu(), out["contradiction"].float().sigmoid().cpu()
        ps = out["span"].float().sigmoid().cpu()
        for k, (e, it) in enumerate(zip(chunk, items)):
            n = len(it["input_ids"])
            preds.append({
                "facts": [f for j, f in enumerate(FACTS) if pf[k, j] >= 0.5], "p_facts": [round(float(x), 4) for x in pf[k]],
                "p_overreach": float(po[k]), "p_contradiction": float(pc[k]),
                "overreach_span": spans_from_probs(it, ps[k, :n, 0].tolist(), len(e["text"])),
                "contradiction_span": spans_from_probs(it, ps[k, :n, 1].tolist(), len(e["text"])),
            })
    return preds


def selection(m: dict) -> float:
    vals = [m["facts"]["micro_f1"]] + [m[h]["ap"] for h in BINARY if m[h].get("ap") is not None]
    return sum(vals) / len(vals)


def build_model(args, pos_weight) -> GuardEncoder:
    if args.smoke:
        cfg = AutoConfig.from_pretrained(args.model)
        cfg.update({"num_hidden_layers": 2, "hidden_size": 64, "num_attention_heads": 2, "intermediate_size": 128,
                    "pooler_hidden_size": 64, "embedding_size": 64})
        enc = AutoModel.from_config(cfg)
    else:
        # transformers 5.x loads mDeBERTa in float16 by default and AdamW on float16 weights goes NaN:
        # weights stay float32, bf16 comes only from autocast.
        enc = AutoModel.from_pretrained(args.model).float()
    return GuardEncoder(enc, args.dropout, pos_weight, tuple(args.heads))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="m3_rung4")
    ap.add_argument("--model", default="microsoft/mdeberta-v3-base")
    ap.add_argument("--heads", nargs="+", default=list(HEADS), choices=list(HEADS))
    ap.add_argument("--sources", nargs="+", default=["selfplay", "synth", "logged"],
                    help="training sources to use (ablation: --sources selfplay)")
    ap.add_argument("--epochs", type=int, default=None, help="default 10 (2 with --smoke)")
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--eval-batch", type=int, default=16)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--head-lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=float, default=0.1)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--max-length", type=int, default=512)
    ap.add_argument("--pos-weight-power", type=float, default=0.5,
                    help="positive weight of the binary heads = (neg/pos) ** power, capped at 20")
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--save-model", action="store_true")
    args = ap.parse_args()
    if args.epochs is None:
        args.epochs = 2 if args.smoke else 10
    random.seed(args.seed); torch.manual_seed(args.seed); torch.cuda.manual_seed_all(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.smoke else "cpu")
    use_bf16 = device.type == "cuda" and torch.cuda.is_bf16_supported()
    splits = load_splits(args.data)
    train = [e for e in splits["train"] if e["source"] in args.sources]
    if args.smoke:
        rng0 = random.Random(0)
        pos = [e for e in train if e["labels"]["overreach"] or e["labels"]["contradiction"] or e["labels"]["facts"]]
        train = rng0.sample(pos, min(48, len(pos))) + rng0.sample(train, 80)
        splits = {k: v[:120] for k, v in splits.items()}
    pos_weight = {}
    for h in BINARY:
        p = sum(e["labels"][h] for e in train)
        pos_weight[h] = min(20.0, ((len(train) - p) / max(1, p)) ** args.pos_weight_power)
    tok = AutoTokenizer.from_pretrained(args.model)
    model = build_model(args, pos_weight).to(device)
    enc_p = [p for p in model.encoder.parameters() if p.requires_grad]
    head_p = [p for n, p in model.named_parameters() if not n.startswith("encoder.")]
    opt = torch.optim.AdamW([{"params": enc_p, "lr": args.lr}, {"params": head_p, "lr": args.head_lr}], weight_decay=args.weight_decay)
    steps = math.ceil(len(train) / args.batch)
    sched = get_linear_schedule_with_warmup(opt, int(args.warmup * steps * args.epochs), steps * args.epochs)
    out_dir = Path(args.out) / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (out_dir / "train_log.jsonl").open("w", encoding="utf-8")
    rng = random.Random(args.seed)
    cache = {}  # tokenisation per example (training items do not change between epochs)
    best, best_state, bad, t0 = -1.0, None, 0, time.time()
    for epoch in range(args.epochs):
        model.train()
        order = list(range(len(train)))
        rng.shuffle(order)
        tot, n, parts_sum = 0.0, 0, {}
        for i in range(0, len(order), args.batch):
            items = []
            for j in order[i:i + args.batch]:
                if j not in cache:
                    cache[j] = encode(tok, train[j], args.max_length)
                items.append(cache[j])
            b = {k: v.to(device) for k, v in collate(items, tok.pad_token_id).items()}
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
                out = model(b["input_ids"], b["attention_mask"], b["seg_mask"])
            loss, parts = model.loss(out, b)
            if not torch.isfinite(loss):
                raise RuntimeError(f"non-finite loss at epoch {epoch + 1}, step {n + 1}: {parts}; "
                                   f"encoder dtype {next(model.encoder.parameters()).dtype}, transformers {transformers.__version__}")
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); sched.step()
            tot += float(loss.detach()); n += 1
            for k, v in parts.items():
                parts_sum[k] = parts_sum.get(k, 0.0) + v
        m = score(splits["val"], predict(model, tok, splits["val"], args, device))
        sc = selection(m)
        rec = {"epoch": epoch + 1, "train_loss": tot / max(1, n), "val_score": sc, "elapsed_s": round(time.time() - t0, 1),
               "max_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2) if device.type == "cuda" else None,
               "head_loss": {k: round(v / n, 4) for k, v in parts_sum.items()},
               "val": {"facts_microF1": round(m["facts"]["micro_f1"], 4),
                       **{f"{h}_AP": round(m[h]["ap"], 4) for h in BINARY if m[h].get("ap") is not None},
                       **{f"{h}_F1": round(m[h]["f1"], 4) for h in BINARY}}}
        log.write(json.dumps(rec) + "\n"); log.flush()
        print(json.dumps(rec), flush=True)
        if sc > best:
            best, bad = sc, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= args.patience:
                break
    log.close()
    if best_state is not None:
        model.load_state_dict(best_state)
    if args.save_model:
        torch.save(model.state_dict(), out_dir / "model.pt")
    extra = {"rung": 4, "method": f"{'tiny random encoder (smoke)' if args.smoke else args.model}, 3 heads + span tagging",
             "n_train": len(train), "pos_weight": pos_weight, "args": vars(args), "best_val_score": best,
             "versions": {"torch": torch.__version__, "transformers": transformers.__version__},
             "train_time_s": round(time.time() - t0, 1)}
    evaluate(args.name, splits, lambda exs: predict(model, tok, exs, args, device), args.out, extra)


if __name__ == "__main__":
    main()
