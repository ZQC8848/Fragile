"""Train and evaluate the multi-head mDeBERTa model (rung 4), and its ablations.

    python -m ml.task2.train.train --data DATA --out RUNS --name rung4_mdeberta_s0 --seed 0          (Windows / laptop)
    python -m task2.train.train   --data $DATA --out $RUNS --name rung4_mdeberta_s0 --seed 0          (CARC)

Ablation switches: --heads (single-task runs), --uncertainty (learned loss weights), --train-frac (scaling
curve), --no-context, --turn-pool (what the turn-level heads read), --loss-weight (scale one head's loss),
--freeze-embeddings (saves memory),
--smoke (tiny random model, CPU, code check only).

Writes <out>/<name>/metrics.json in the same format as the baselines (scored with predicted segmentation),
<out>/<name>_goldspans/metrics.json (unit heads scored on the teacher's unit spans, to separate
segmentation errors from classification errors), train_log.jsonl, and the best checkpoint (model.pt).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import time
from pathlib import Path

import torch
import transformers
from transformers import AutoConfig, AutoModel, AutoTokenizer, get_linear_schedule_with_warmup

from ..common.labels import ACTS, CLAIMS, NORA_ANSWERS, TOPICS
from .baselines.common import evaluate, load_splits
from .data import targets
from .encode import build_item, char_tags_from_logits, collate, spans_from_char_tags, spans_from_segments
from .metrics import score_system
from .model import ADDRESSEE_LABELS, HEADS, NONE, SIDE_LABELS, TARGET_LABELS, TURN_POOLS, VERB_LABELS, MultiHeadEncoder


def set_seed(seed: int) -> None:
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def build_model(args, tok) -> MultiHeadEncoder:
    if args.smoke:
        cfg = AutoConfig.from_pretrained(args.model)
        cfg.update({"num_hidden_layers": 2, "hidden_size": 64, "num_attention_heads": 2, "intermediate_size": 128,
                    "pooler_hidden_size": 64, "embedding_size": 64})
        enc = AutoModel.from_config(cfg)
    else:
        # transformers 5.x loads mDeBERTa in float16 by default; AdamW on float16 weights goes NaN in the first epoch.
        # Weights stay float32 here and bf16 comes only from autocast.
        enc = AutoModel.from_pretrained(args.model).float()
    model = MultiHeadEncoder(enc, heads=tuple(args.heads), dropout=args.dropout, uncertainty=args.uncertainty,
                             turn_pool=args.turn_pool, loss_weights=args.loss_weights)
    if args.freeze_embeddings:
        for p in model.encoder.embeddings.parameters():
            p.requires_grad = False
    return model


def to_device(batch: dict, device) -> dict:
    return {k: v.to(device) if torch.is_tensor(v) else v for k, v in batch.items()}


@torch.no_grad()
def predict(model, tok, exs, args, device, gold_spans: bool = False):
    """Turn-level predictions (same format as the baselines) and per-character segmentation."""
    model.eval()
    use_bf16 = device.type == "cuda" and torch.cuda.is_bf16_supported()
    preds, segs = [], []
    for i in range(0, len(exs), args.eval_batch):
        chunk = exs[i:i + args.eval_batch]
        # pass 1: segmentation and turn-level heads
        items = [build_item(tok, ex, args.max_length, use_context=not args.no_context, spans=[]) for ex in chunk]
        batch = to_device(collate(items, tok.pad_token_id), device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
            out = model(batch["input_ids"], batch["attention_mask"], batch["unit_pool"], batch["unit_batch"],
                        player_mask=batch["player_mask"])
        ctags_all, span_lists = [], []
        for b, ex in enumerate(chunk):
            ct = char_tags_from_logits(items[b], out["seg"][b].float().cpu(), ex["text"])
            ctags_all.append(ct)
            if gold_spans and ex["mask"]["units"]:
                spans = [(u["channel"], u["start"], u["end"]) for u in ex["units"] if u["start"] is not None]
            elif ex["mode"] == "channels":
                spans = spans_from_segments(ex)  # the player filled the channels: segmentation is known
            else:
                spans = spans_from_char_tags(ex["text"], ct)
            span_lists.append(spans)
        # pass 2: unit heads pooled over the (predicted or gold) unit spans
        items2 = [build_item(tok, ex, args.max_length, use_context=not args.no_context, spans=sp) for ex, sp in zip(chunk, span_lists)]
        batch2 = to_device(collate(items2, tok.pad_token_id), device)
        with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
            out2 = model(batch2["input_ids"], batch2["attention_mask"], batch2["unit_pool"], batch2["unit_batch"],
                         player_mask=batch2["player_mask"])
        ub = batch2["unit_batch"].tolist()
        acts = out2["act"].float().argmax(-1).tolist()
        topics = (out2["topics"].float().sigmoid() > 0.5).tolist()
        verbs = out2["verb"].float().argmax(-1).tolist()
        tgts = out2["target"].float().argmax(-1).tolist()
        k = 0
        unit_info = [[] for _ in chunk]
        for b, it in enumerate(items2):
            for u in it["units"]:
                unit_info[ub[k]].append((u["channel"], acts[k], topics[k], verbs[k], tgts[k]))
                k += 1
        for b, ex in enumerate(chunk):
            us = unit_info[b]
            action = "none"
            for ch, _, _, v, t in us:
                if ch == "action" and VERB_LABELS[v] != NONE:
                    action = f"{VERB_LABELS[v]}:{TARGET_LABELS[t]}"
                    break
            preds.append({
                "act_set": sorted({ACTS[a] for _, a, _, _, _ in us}),
                "topics": sorted({TOPICS[j] for _, _, tp, _, _ in us for j, on in enumerate(tp) if on}),
                "claims": [CLAIMS[j] for j, on in enumerate((out["claims"][b].float().sigmoid() > 0.5).tolist()) if on],
                "addressee": ADDRESSEE_LABELS[int(out["addressee"][b].float().argmax())],
                "action": action,
                "suspicion": float(out["suspicion"][b].float().clamp(0, 3)),
                "nora": NORA_ANSWERS[int(out["nora"][b].float().argmax())],
                "side": SIDE_LABELS[int(out["side"][b].float().argmax())],
            })
            segs.append(ctags_all[b])
    return preds, segs


SELECTION_PRIMARY = ("act", "topics", "addressee", "seg")
SELECTION_FALLBACK = ("claims", "nora", "suspicion")


def selection_metrics(m: dict, heads) -> list[float]:
    """Val metrics behind model selection: the primary heads that are trained (all four for the full model, as in
    batches 2-3). A run training none of them uses its own turn-level heads instead. Untrained heads never count:
    their random outputs would decide early stopping."""
    value = {"act": m["act_set"]["micro_f1"], "topics": m["topics"]["micro_f1"], "addressee": m["addressee"]["accuracy"],
             "seg": m["seg"]["char_f1"] if "seg" in m else None, "claims": m["claims"]["micro_f1"],
             "nora": m["nora"]["accuracy"] if m["nora"]["n"] else None, "suspicion": m["suspicion"]["qwk"]}
    for group in (SELECTION_PRIMARY, SELECTION_FALLBACK):
        vals = [value[h] for h in group if h in heads and value[h] is not None]
        if vals:
            return vals
    return [0.0]


def val_score(model, tok, val, args, device) -> tuple[float, dict[str, float]]:
    """Model-selection score (mean of selection_metrics) and per-head val metrics."""
    preds, segs = predict(model, tok, val, args, device)
    m = score_system(val, preds, segs, ci=False)
    parts = selection_metrics(m, args.heads)
    detail = {"acts": m["act_set"]["micro_f1"], "topics": m["topics"]["micro_f1"], "claims": m["claims"]["micro_f1"],
              "addressee": m["addressee"]["accuracy"], "nora": m["nora"]["accuracy"], "suspicion_qwk": m["suspicion"]["qwk"],
              "seg": m.get("seg", {}).get("char_f1")}
    return sum(parts) / len(parts), {k: round(v, 4) for k, v in detail.items() if v is not None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--name", default="rung4_mdeberta")
    ap.add_argument("--model", default="microsoft/mdeberta-v3-base")
    ap.add_argument("--heads", nargs="+", default=list(HEADS), choices=list(HEADS))
    ap.add_argument("--epochs", type=int, default=None, help="default 10 (2 with --smoke)")
    ap.add_argument("--batch", type=int, default=16)
    ap.add_argument("--eval-batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--head-lr", type=float, default=1e-3)
    ap.add_argument("--warmup", type=float, default=0.1)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--dropout", type=float, default=0.1)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--context-dropout", type=float, default=0.3)
    ap.add_argument("--patience", type=int, default=3)
    ap.add_argument("--train-frac", type=float, default=1.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--uncertainty", action="store_true")
    ap.add_argument("--no-context", action="store_true")
    ap.add_argument("--turn-pool", default="cls", choices=TURN_POOLS,
                    help="input of the turn-level heads: [CLS], mean of the player-text tokens, or both concatenated")
    ap.add_argument("--loss-weight", action="append", default=[], metavar="HEAD=W",
                    help="multiply one head's loss by W, e.g. --loss-weight addressee=3 (repeatable)")
    ap.add_argument("--freeze-embeddings", action="store_true")
    ap.add_argument("--smoke", action="store_true", help="tiny random encoder, 2 epochs, CPU: checks the code path only")
    ap.add_argument("--save-model", action="store_true", help="keep model.pt (about 1.1 GB for mDeBERTa-base)")
    args = ap.parse_args()
    args.loss_weights = {}
    for spec in args.loss_weight:
        head, _, w = spec.partition("=")
        if head not in HEADS or not w:
            ap.error(f"--loss-weight wants HEAD=W with HEAD in {HEADS}, got {spec!r}")
        args.loss_weights[head] = float(w)
    if args.epochs is None:
        args.epochs = 2 if args.smoke else 10
    set_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() and not args.smoke else "cpu")
    use_bf16 = device.type == "cuda" and torch.cuda.is_bf16_supported()
    splits = load_splits(args.data)
    train = splits["train"]
    if args.train_frac < 1.0:
        rng = random.Random(args.seed)
        train = rng.sample(train, max(1, int(len(train) * args.train_frac)))
    tok = AutoTokenizer.from_pretrained(args.model)
    model = build_model(args, tok).to(device)
    enc_params = [p for p in model.encoder.parameters() if p.requires_grad]
    head_params = [p for n, p in model.named_parameters() if not n.startswith("encoder.") and p.requires_grad]
    opt = torch.optim.AdamW([{"params": enc_params, "lr": args.lr}, {"params": head_params, "lr": args.head_lr}],
                            weight_decay=args.weight_decay)
    steps_per_epoch = math.ceil(len(train) / args.batch)
    sched = get_linear_schedule_with_warmup(opt, int(args.warmup * steps_per_epoch * args.epochs), steps_per_epoch * args.epochs)
    out_dir = Path(args.out) / args.name
    out_dir.mkdir(parents=True, exist_ok=True)
    log = (out_dir / "train_log.jsonl").open("w", encoding="utf-8")
    rng = random.Random(args.seed)
    best, best_state, bad = -1.0, None, 0
    t0 = time.time()
    for epoch in range(args.epochs):
        model.train()
        order = list(range(len(train)))
        rng.shuffle(order)
        tot, n = 0.0, 0
        head_tot: dict[str, float] = {}
        head_n: dict[str, int] = {}
        for i in range(0, len(order), args.batch):
            exs = [train[j] for j in order[i:i + args.batch]]
            items = [build_item(tok, ex, args.max_length, args.context_dropout, not args.no_context, rng=rng) for ex in exs]
            batch = to_device(collate(items, tok.pad_token_id), device)
            with torch.autocast(device.type, dtype=torch.bfloat16, enabled=use_bf16):
                out = model(batch["input_ids"], batch["attention_mask"], batch["unit_pool"], batch["unit_batch"],
                            player_mask=batch["player_mask"])
            loss, parts = model.loss(out, batch)
            if not torch.isfinite(loss):
                raise RuntimeError(f"non-finite loss at epoch {epoch + 1}, step {n + 1}: {parts}. "
                                   f"Encoder dtype {next(model.encoder.parameters()).dtype}, transformers {transformers.__version__}.")
            opt.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            tot += float(loss.detach())
            n += 1
            for h, v in parts.items():
                head_tot[h] = head_tot.get(h, 0.0) + v
                head_n[h] = head_n.get(h, 0) + 1
        score, val_heads = val_score(model, tok, splits["val"], args, device) if splits.get("val") else (-tot, {})
        rec = {"epoch": epoch + 1, "train_loss": tot / max(1, n), "val_score": score, "elapsed_s": round(time.time() - t0, 1),
               "max_mem_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2) if device.type == "cuda" else None,
               "head_loss": {h: round(head_tot[h] / head_n[h], 4) for h in head_tot}, "val": val_heads}
        if model.uncertainty:
            rec["log_vars"] = {h: round(float(v), 3) for h, v in model.log_vars.items()}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print(json.dumps(rec), flush=True)
        if score > best:
            best, bad = score, 0
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
    extra = {"rung": 4, "method": f"{'tiny random encoder (smoke)' if args.smoke else args.model} multi-head fine-tuned",
             "n_train": len(train), "args": {k: v for k, v in vars(args).items()}, "best_val_score": best,
             "versions": {"torch": torch.__version__, "transformers": transformers.__version__},
             "train_time_s": round(time.time() - t0, 1)}
    evaluate(args.name, splits, lambda exs: predict(model, tok, exs, args, device), args.out, extra)
    evaluate(f"{args.name}_goldspans", splits, lambda exs: predict(model, tok, exs, args, device, gold_spans=True), args.out,
             {**extra, "method": extra["method"] + " (unit heads on teacher spans)"})


if __name__ == "__main__":
    main()
