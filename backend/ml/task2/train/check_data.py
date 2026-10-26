"""Check that character spans survive the round trip to subword-token tags and back (needed for the token head).

For every single-box example with segmentation labels: tag each mDeBERTa token by the channel covering most
of its characters, then turn the token tags back into character spans and compare with the original spans
(both trimmed of spaces and quotes). Reports the share of examples that round-trip exactly.

    python -m task2.train.check_data --examples DATA/examples/train.jsonl --tokenizer microsoft/mdeberta-v3-base
"""

from __future__ import annotations

import argparse

from transformers import AutoTokenizer

from .data import EDGE_CHARS, char_tags, chars_from_tokens, load_jsonl, token_tags


def canon(text, tags):
    return ["O" if text[i] in EDGE_CHARS else t for i, t in enumerate(tags)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--examples", required=True)
    ap.add_argument("--tokenizer", default="microsoft/mdeberta-v3-base")
    args = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(args.tokenizer)
    exs = [e for e in load_jsonl(args.examples) if e["mask"]["seg"]]
    ok, bad = 0, []
    lens = []
    for e in exs:
        text = e["text"]
        ct = char_tags(text, e["segments"])
        enc = tok(text, return_offsets_mapping=True, add_special_tokens=False)
        lens.append(len(enc["input_ids"]))
        offs = enc["offset_mapping"]
        rt = chars_from_tokens(len(text), offs, token_tags(offs, ct, text), text)
        if canon(text, rt) == canon(text, ct):
            ok += 1
        else:
            bad.append(e)
    n = len(exs)
    print(f"{n} segmented examples; exact round trip {ok}/{n} = {ok / n:.1%}" if n else "no segmented examples")
    if lens:
        lens.sort()
        print(f"player-text tokens: median {lens[len(lens) // 2]}, p95 {lens[int(0.95 * (len(lens) - 1))]}, max {lens[-1]}")
    for e in bad[:10]:
        print("  mismatch:", e["ex_id"], repr(e["text"][:120]))


if __name__ == "__main__":
    main()
