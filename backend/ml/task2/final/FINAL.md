# Task 2 final write-up: M2 input understanding + compliance, M3 narration guard

Status 2026-11-25. Training is finished; nothing here is wired into the engine yet.
Owner: Haosen Cao (branch `m3-guard`). Written for the poster and the final report.

| File | What it is |
|---|---|
| `figures.html` | All figures, self-contained (open it in a browser). Each figure has a one-line claim, a caption saying exactly what is plotted, a "Numbers" table and a "Download SVG" button for the poster. |
| `figures_data.json` | Every number in the figures, machine-readable (also embedded in `figures.html` as `#figure-data`). |
| `build_figures.py` | Rebuilds both from the run outputs: `python -m ml.task2.final.build_figures --runs <handoff>/runs --data <m3 examples>` (run from `backend/`). |
| `../RESULTS.md` | Earlier M2 results (batch 5, midterm report). |

Run outputs (`metrics.json`, `train_log.jsonl`, per-segment `preds_*.jsonl`) and per-batch run reports live in the
owner's handoff repo, not here. Training data lives outside both repos (`$TASK2_DATA`). Model weights (`model.pt`,
about 1.1 GB each) are on the training PC: M3 `m3_r9_s0..s2`, M2 `rung4_full_e30_s0..s2`.

---

## 1. What we built, in one paragraph

Every game turn calls an LLM twice for checking: once to understand and police the player's input (review), and
once to check the narrator's draft (guard). We distilled both checks into small local encoders. **M2** reads the
player's turn and outputs its segmentation, dialogue acts, addressee, topics, claims, suspicion, Nora/side answers,
and whether the input is a violation (10 classes plus a character span). **M3** reads each narration segment and
outputs which secret facts it states, whether it speaks or acts for the player (overreach), and whether it
contradicts the scene (contradiction), plus the offending span. The game's own deterministic rules turn M3's
perceptions into the guard's verdicts, in the guard's existing output format.

## 2. Poster claims (each backed by a figure in `figures.html`)

1. **M3 beats the LLM guard it would replace.** Our self-play-only guard sends back 5.5% of clean passages and
   catches 66.5% of passages the teacher would send back; the DeepSeek guard sends back 8.3% and catches 41.2%.
   Premature leaks caught: 81.9% vs 32.9%. (Fig. 2, 3)
2. **Perception + rules.** The model only learns *what a segment says*; *whether that is allowed yet* is read from
   the story state by rules. The allowed list changes as the story moves, so this split avoids retraining. (Fig. 1)
3. **Synthetic violations matter on real failures.** Adding DeepSeek rewrites (verified by the teacher) and the
   game's logged blocked drafts lifts verdict macro-F1 on real blocked drafts from 0.41 to 0.71. The price is more
   false rejects on clean passages (17.0% vs 5.5%): the two models are two operating points. (Fig. 2, 5)
4. **It says where the problem is.** In 94% of correctly sent-back passages it names a right segment; the
   violation type is right 97% of the time, the leaked secret 99%. (Fig. 6)
5. **Ensembling three seeds** beats the average seed on every measure. (Fig. 7)
6. **M2 compliance** rejects 1.4% of valid inputs and misses 18.7% of violations (AUROC 0.95); keyword rules miss
   67.1%. (Fig. 8) **M2 understanding** leads all baselines on 6 of 7 heads. (Fig. 9)

Honest negatives for the same poster: contradiction is not learned (Fig. 4); M2 compliance does not transfer to
the seed set (Fig. 8, right). See §7.

---

## 3. Data

### 3.1 Self-play

An LLM plays the whole game as the player; the engine, narrator and the existing LLM guard run as in production,
and everything is logged (player input, scene state, every narration segment, the guard's verdicts).

| | Sessions | Unit | Train | Val | Test | Other test |
|---|---|---|---|---|---|---|
| M2 (`examples_v3`) | 250 (204 / 25 / 21) | player turn | 5,957 | 699 | 609 | seed set: 103 |
| M3 (`m3/examples`) | 54 (29 / 5 / 20) | narration segment | 7,311 | 1,313 | 4,148 (530 turns) | `test_logged`: 131 |

Splits are by session (no session in two splits). M2 is 83% English, 10% Chinese, 8% mixed and is stratified by
language. M3 test is a later self-play round (`r1`, 20 sessions, an all-Claude player) that no training set touches.
`test_logged` is the guard's own flags in those 20 test sessions.

### 3.2 Teacher labels

- **M2**: the game's review teacher (DeepSeek, `deepseek-flash`, review prompt v1) labels every turn; the
  `nora_answer` labels were re-labelled by Claude under review v2 (batch 7). Compliance labels (`validity`: `ok` or
  one of 9 violations, plus span) come from the same review output: train 545 / val 69 / test 73 violations.
- **M3**: Claude Sonnet labels all 1,533 logged turns, one call per turn, every segment in a fixed JSON schema:
  `{facts[], overreach, overreach_span, contradiction, contradiction_span, note}`. The schema asks only for
  perception (which facts are *stated*), never for allowed/not-allowed.
- **Teacher ceiling**: Claude Opus re-labels 150 test turns (1,150 segments) with the same prompt; Sonnet scored
  against Opus gives facts micro-F1 0.89, overreach F1 0.45, contradiction F1 0.32, leak recall 0.98. No student can
  be expected to agree with Sonnet more than Opus does.

### 3.3 Rare positives for M3

Clean segments dominate (test: 40 overreach, 90 contradiction in 4,148). Two additions, **training and validation
only, never test**:

| Source | How | Kept |
|---|---|---|
| `synth` | DeepSeek (`deepseek-v4-pro`, temperature 0.9) rewrites one segment of a clean turn by a named subtype. Overreach: speech, action, decision, feeling, reaction. Contradiction: wrong room, Nora's whereabouts, crate state, who heard what, previous passage, setting. Plus "near misses" (lies, perception, rephrasing, hints) that look suspicious but are allowed. The Claude teacher then labels the rewritten turn; only the teacher's label is used. | 994 generated; teacher confirmed overreach 395/400, contradiction 268/394, flagged 1/200 near misses. 850 in train, 144 in val. |
| `logged` | Spans the game's guard really blocked, re-inserted into their passage at the logged segment index, then labelled by the teacher. | 329 spans, about two thirds confirmed; 166 train, 32 val, 131 `test_logged`. |

Two rewrite subtypes barely took ("previous passage" 1/23, "who heard what" 6/23 confirmed on inspection: the
rewrites did not actually contradict), so the model has almost no examples of them.

## 4. Models

Both use **`microsoft/mdeberta-v3-base`** (multilingual, ~280M parameters), fully fine-tuned, with task heads on top.

### M2: one encoder, many heads

Input: player text `</s>` context (room, present characters, story phase, phone/call state, recent NPC lines). The
context is dropped at random for 30% of training examples, so the model cannot lean on it.

| Head | Reads | Output | Loss |
|---|---|---|---|
| segmentation | every token | channel tag (speech / action / expression …) | cross-entropy |
| act, verb, target | each segment (mean of its tokens) | single label | cross-entropy |
| topics, implausible | each segment | multi-label / binary | BCE |
| addressee, Nora, side | turn: [CLS] ⊕ mean of player tokens | single label | cross-entropy (masked when not applicable) |
| claims | turn | multi-label | BCE |
| suspicion | turn | 0–3 | MSE / 3 |
| **validity** | turn | `ok` + 9 violations | cross-entropy |
| **validity span** | every token | in the violating span | BCE (violations only) |

### M3: perception heads + rules

Input: `[kind:speaker] segment text` `</s>` `player: … || scene: room, who is present, crate, phones, call ||
flags || before: last 700 characters of the previous passage || heard: who heard which fact`. "Heard" goes last
so truncation drops it first. Max 512 tokens, truncating only the context.

| Head | Reads | Output | Loss |
|---|---|---|---|
| facts | [CLS] ⊕ mean of the segment's tokens | 10 secrets, multi-label: *stated* or not | BCE |
| overreach | same | binary | BCE, positive weight (neg/pos)^0.5 ≤ 20 |
| contradiction | same | binary | BCE, positive weight (neg/pos)^0.5 ≤ 20 |
| span | every segment token | in overreach span / in contradiction span | BCE, positives of that head only |

**Composition** (`train/m3_data.py: compose`, mirrors the engine's `Guard.failures`), in order:
1. a stated fact that is not in the allowed set, outside the ending → `premature_leak`;
2. else contradiction → `contradiction`;
3. else overreach → `player_overreach`, except at the opening, and in the ending outside the player's own quoted speech;
4. else `consistent`.

Output per segment: `{index, label, fact, span, confidence}`, the format of the engine's `TrainedGuardPath`.
The engine already turns failures into rewrite hints (`segment 3: premature_leak (leo_dead)`) and, after two failed
rewrites, replaces only the failing segment (`engine/narrator/narrator.py: repair`).

## 5. Training

| Setting | M2 (batch 7) | M3 (batch 9) |
|---|---|---|
| Optimiser | AdamW, encoder lr 2e-5, heads lr 1e-3, weight decay 0.01 | same |
| Schedule | linear, 10% warm-up | same |
| Batch / max length | 16 / 256 | 8 / 512 |
| Dropout | 0.1 (heads) | 0.1 |
| Precision | fp32 weights, bf16 autocast | same |
| Gradient clipping | 1.0 | 1.0 |
| Epochs / early stopping | up to 30, patience 3 | up to 15, patience 4 |
| Model selection (on val) | mean of acts µF1, topics µF1, addressee accuracy, segmentation char-F1, compliance balanced accuracy | mean of facts µF1, overreach AP, contradiction AP, on the **real-source** val only (self-play + logged: 1,169 of 1,313) |
| Decision thresholds | argmax (compliance: `ok` vs the rest) | overreach / contradiction thresholds: best F1 on the same real-source val, grid 0.05–0.95; facts at 0.5 |
| Seeds | 0, 1, 2 | 0, 1, 2; probabilities averaged (`train/m3_ensemble.py`) |
| Epochs run (best) | 13 (10), 21 (18), 24 (21) | 14 (10), 15 (11), 14 (10); self-play only: 8 (4), 11 (7), 11 (7) |
| Time per run | 13–23 min | 70–95 min (~290 s/epoch); self-play only ~45 min |

Hardware: one RTX 4070 Ti (12 GB), PyTorch 2.14.1 + CUDA 12.6, transformers 4.57.6. Peak allocated memory
8.4 GB (M2) and 9.6 GB (M3).

Two things that mattered:
- **fp32 weights.** transformers 5.x loads mDeBERTa in float16 by default; AdamW on float16 weights turns the
  loss into NaN within the first steps. The weights stay float32 and only the forward pass runs in bf16.
- **Select and tune on real data only (M3).** In batch 8, model selection and thresholds used all of val, where
  the 144 easy rewrites dominated the average precision: chosen thresholds ranged from 0.05 to 0.95 across seeds.
  Batch 9 restricts both to real-source val and averages the seeds; the ensemble's thresholds are 0.6 / 0.35.

## 6. Evaluation

**Baselines, same splits, same metrics:** majority class; keyword rules (the engine's own rule paths:
`FACT_PATTERNS` for M3); TF-IDF (word + character n-grams) + logistic regression; for M2 also frozen e5
embeddings + logistic regression; for M3 the DeepSeek guard (`LLMGuardPath`, the production prompt) run on the
test turns.

**M3 metrics.** Per head: facts micro/macro-F1; overreach and contradiction precision, recall, F1, AP (average
precision), AUROC, span character-F1. Game level: verdict macro-F1 over the four labels, leak recall, segment false
alarm, and **passage level** (a passage is sent back if any segment fails): F1 and false reject.

**Allowed facts at test time.** The engine's run-time allowed list (`GuardContext.allowed`) is not logged; we use
the facts revealed by the end of the turn. This is applied identically to every system, including the DeepSeek
guard's verdicts, so comparisons are fair, but absolute leak numbers may be stricter than in the live game.

**M2 metrics.** Compliance as ok-vs-violation: false-reject rate (valid inputs sent back, ranked first by the
design), miss rate, AUROC; 10-class macro-F1; span char-F1. Understanding heads as in `RESULTS.md`.

### Main numbers (test)

M3, 4,148 segments / 530 turns (182 turns the teacher would send back):

| System | Facts µF1 | Overreach F1 | Contra. F1 | Verdict macro-F1 | Leak recall | Passage sent back (clean) | Passage caught (bad) |
|---|---|---|---|---|---|---|---|
| Keyword rules | 0.293 | 0.140 | 0.000 | 0.322 | 19.5% | 1.1% | 15.9% |
| DeepSeek guard | 0.181 | 0.232 | 0.217 | 0.487 | 32.9% | 8.3% | 41.2% |
| TF-IDF + LR | 0.739 | 0.301 | 0.102 | 0.477 | 88.6% | 33.3% | 80.2% |
| Ours, self-play only (ensemble) | 0.778 | 0.400 | 0.138 | 0.497 | 81.9% | 5.5% | 66.5% |
| Ours, + rewrites + logged (ensemble) | 0.760 | 0.405 | 0.117 | **0.535** | 81.2% | 17.0% | 69.2% |
| Second teacher (Opus vs Sonnet, 150 turns) | 0.890 | 0.452 | 0.316 | 0.655 | 97.7% | 6.6% | 74.6% |

M2, 609 turns: compliance false reject 1.4%, miss 18.7%, AUROC 0.95 (rules miss 67.1%, TF-IDF 50.7%); on the
103-turn seed set false reject 6.3%, miss 40.3%, AUROC 0.81 (rules miss 37.5%).

The exact values for every figure are in `figures_data.json`.

## 7. Limitations (put these in the report)

1. **Teacher, not humans.** Every score is agreement with an LLM teacher. The second-teacher check shows that
   overreach (F1 0.45) and especially contradiction (0.32) are not well-defined even between two strong models.
2. **Contradiction is not learned** (AP 0.08–0.12). Few real examples, and the rewrites that would teach the
   hardest subtypes mostly failed verification.
3. **Allowed facts are approximated** by end-of-turn revealed facts (§6). 34% of test turns would be sent back
   under this rule, which likely overstates leaks in the live game.
4. **One test round.** M3 test is 20 sessions from one self-play round with one player model.
5. **M2 compliance does not transfer** to the seed set (different authors, styles and languages): miss 40%, no
   better than keyword rules.
6. **Two operating points, no single winner.** Self-play-only is best on clean narration; with rewrites is best on
   real blocked drafts. Choosing depends on whether a needless rewrite or a missed violation costs more in play.
7. **Leaks are located to the segment, not the words**: the facts head has no span tagger.
8. **Not integrated.** `TrainedEncoderPath` and `TrainedGuardPath` still call the LLM; latency and cost savings are
   not measured in the running game.

## 8. Reproducing

From `backend/`, with the data in `$TASK2_DATA` and runs written to the handoff repo:

```bash
# M3 data
python -m ml.task2.gen.m3_export && python -m ml.task2.gen.m3_relabel --model sonnet   # Claude teacher (CLI)
python -m ml.task2.gen.m3_relabel --model opus --split test --sample 150             # second teacher
python -m ml.task2.gen.m3_synth --n-overreach 400 --n-contradiction 400 --n-near-miss 200
python -m ml.task2.gen.m3_verify --model sonnet && python -m ml.task2.gen.m3_build
# M3 baselines
python -m ml.task2.train.m3_baselines --data $D --out $R
python -m ml.task2.gen.m3_rule_baseline --data $D --out $R
python -m ml.task2.gen.m3_llm_baseline --data $D --out $R
python -m ml.task2.gen.m3_agreement --gold opus --pred sonnet --out $R
# M3 training (GPU), then the ensemble
python -m ml.task2.train.m3_train --data $D --out $R --name m3_r9_s0 --seed 0 --epochs 15 --save-model
python -m ml.task2.train.m3_ensemble --data $D --runs $R --members m3_r9_s0 m3_r9_s1 m3_r9_s2 --name m3_r9_ens
# M2 training (GPU)
python -m ml.task2.train.train --data <examples_v3> --out <runs/v3> --name rung4_full_e30_s0 --seed 0 --epochs 30 --turn-pool both --save-model
# tables and figures
python -m ml.task2.train.m3_summarize --runs $R --split test
python -m ml.task2.final.build_figures --runs <handoff>/runs --data $D
```
