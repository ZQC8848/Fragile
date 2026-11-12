# Task 2 results (status 2026-11-12)

Numbers behind the M2 part of the midterm report. All scores are against the teacher's labels (review v1,
deepseek-flash) on the frozen test split `test_v1`: **129 turns from 5 held-out games**. The training data
for every row below is the first data set (1136 train / 111 val turns from 40 + 5 games). The raw run
outputs (`metrics.json`, `train_log.jsonl`) and the per-batch reports live in the handoff repo, not here.

## Midterm report table (`tab:m2`)

| System | Acts µF1 | Topics µF1 | Addr. acc | Nora acc | Seg. char-F1 |
|---|---|---|---|---|---|
| Rung 0, majority class | 0.433 | 0.590 | 0.340 | 0.259 | 0.609 |
| Rung 0, keyword rules | 0.431 | 0.509 | 0.538 | 0.370 | 0.712 |
| Rung 1, TF-IDF + LR | 0.607 | 0.740 | **0.764** | 0.407 | 0.832 |
| Rung 2, frozen multilingual-e5-base + LR | 0.590 | 0.763 | 0.642 | 0.630 | — |
| Rung 4, multi-head mDeBERTa-v3-base (3 seeds) | **0.727** | **0.769** | 0.667 | **0.654** | **0.956** |
| Teacher self-agreement (upper bound) | 0.856 | 0.891 | 0.94 | 0.98 | — |

- Rung 4 is the main configuration: turn heads read [CLS] concatenated with the mean of the player-text
  subwords (`--turn-pool both`), 20 epochs, equal loss weights; mean over seeds 0, 1, 2.
- Teacher self-agreement: 300 turns, the original label against two relabels at temperature 0.7. Acts and
  topics are the same set-µF1 as the systems; addressee and Nora are plain agreement rates. It is measured on
  its own sample, not on `test_v1`.
- Rung 2 has no token-level output, so no segmentation score.
- Spread across seeds is large for the single-label turn heads (addressee 0.660 to 0.679, Nora 0.556 to
  0.704); with 129 turns, 0.07 is about 9 turns.

## The [CLS] observation the report asks to confirm

Confirmed. With turn heads reading only [CLS] (batch 2, 3 seeds), the turn-level outputs trailed the frozen
embedding baseline while the mean-pooled unit heads beat it:

| Turn pooling | Acts µF1 | Topics µF1 | Claims µF1 | Addr. acc | Nora acc |
|---|---|---|---|---|---|
| Rung 2, frozen e5 | 0.590 | 0.763 | 0.770 | 0.642 | 0.630 |
| `cls` | 0.710 | 0.733 | 0.587 | 0.468 | 0.568 |
| `both` (10 epochs) | 0.713 | 0.751 | 0.724 | 0.610 | 0.617 |
| `both` (20 epochs, main) | 0.727 | 0.769 | 0.748 | 0.667 | 0.654 |

Pooling the player-text subwords fixed claims and most of addressee; acts and segmentation did not move.

## Other findings

- Gold spans instead of the model's own segmentation raise acts µF1 by only about 0.01: the errors are in
  classification, not segmentation.
- Single-task acts (0.703) and multi-task (0.719) are close; multi-task does not hurt it.
- Data size 10 / 25 / 50 / 100 % gives acts µF1 0.608 / 0.604 / 0.677 / 0.706, still rising.
- Addressee is limited by generalisation, not training: train loss reaches 0.05 while val accuracy stays at
  0.60 to 0.67. TF-IDF wins on it with literal name cues. Weighting the addressee loss ×3 buys 0.06
  addressee for losses on acts, claims and suspicion, so it is not used.
- Rules collapse on Chinese (acts µF1 0.224); the learned models do not (rung 2: zh 0.593 / en 0.587).
- Teacher: exact act sequence agreement is only 34 % (first act 64 %); the 27 act classes have fuzzy
  borders, which caps every student.

## Open

- **Scaled data (batch 5) not run yet.** `examples_v2`: 7374 turns from 250 games (train 5957 / val 699 /
  test 609 from 204 / 25 / 21 games), split stratified by language, `test_v1` kept frozen inside it. Queued:
  rungs 0 to 2 again, the main configuration over 3 seeds, data-size points at 20 % and 50 %.
- Round `r1-haosen` (20 all-Claude sessions, `backend/data/selfplay/r1-haosen/`) is not in any training
  set yet.
- `TrainedEncoderPath` (wiring the model back into the engine) is not started.
