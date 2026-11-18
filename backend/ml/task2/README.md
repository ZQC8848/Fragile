# Task 2: player input understanding

Trains a local model to take over the *understanding* half of the review step (`TrainedEncoderPath` in
`engine/models/encoder.py`): channel segmentation, dialogue act, addressee, topics, action, suspicion, claims,
`nora_answer`, `side_answer`. Validity belongs to task 3; translation and rewrites stay with the API.

## Layout

| Directory | Runs where | Imports the engine? |
|---|---|---|
| `common/` labels, normalisation, tag alignment, split | both | no (standard library only) |
| `gen/` data generation and relabelling | locally, `uv run` in `backend/` | yes |
| `train/` metrics, baselines, later the model | CARC, conda env `torch` | no |
| `tests/` | locally | no |

Data never goes into the repo: it lives in `$TASK2_DATA` (default `~/fragile_task2_data/`):
`raw/<run>/{turns,sessions}.jsonl`, `relabel/<run>.jsonl`, `examples/*.jsonl`.

## 1. Generate data (locally, needs `backend/.env`)

Only the self-play player (Kimi, falling back to DeepSeek when Kimi times out) and the review teacher (DeepSeek)
are live; narrator, guard, scorer, tension and options run on their offline mocks.

```bash
cd backend
uv run python -m ml.task2.gen.export_meta                         # labels.json, action_table.json from the engine
uv run python -m ml.task2.gen.run_selfplay --run smoke --games 2 --max-turns 5 --mock-player   # no API calls
uv run python -m ml.task2.gen.run_selfplay --run b1 --games 50 --concurrency 8
uv run python -m ml.task2.gen.inspect_run --run b1
uv run python -m ml.task2.gen.import_seeds                        # Sonnet EN/ZH + review evals, teacher-labelled
uv run python -m ml.task2.gen.relabel_tagged --run b1             # segmentation on the original text
uv run python -m ml.task2.gen.relabel_tagged --run seeds
uv run python -m ml.task2.gen.relabel_tagged --run b1 --report
uv run python -m ml.task2.gen.consistency --run b1 --n 300        # teacher self-agreement (ceiling)
uv run python -m ml.task2.gen.build_examples --runs b1 --out all.jsonl
uv run python -m ml.task2.gen.build_examples --runs seeds --out seeds.jsonl
uv run python -m ml.task2.common.split --examples ~/fragile_task2_data/examples/all.jsonl --out ~/fragile_task2_data/examples
uv run pytest ml/task2/tests
```

## 2. Baselines on CARC

```bash
# from backend/ on the laptop, with the shared SSH connection open (see project/carc-access.md)
rsync -a --exclude __pycache__ ml/task2/ haosenca@discovery.usc.edu:/project2/yzhao010_1531/haosenca/code/task2/
rsync -a ~/fragile_task2_data/examples/ haosenca@discovery.usc.edu:/project2/yzhao010_1531/haosenca/data/task2/examples/
# on CARC
sbatch /project2/yzhao010_1531/haosenca/code/task2/train/slurm/check_data_cpu.sbatch
sbatch /project2/yzhao010_1531/haosenca/code/task2/train/slurm/baselines_cpu.sbatch   # rung 0 + rung 1
sbatch /project2/yzhao010_1531/haosenca/code/task2/train/slurm/embed_gpu.sbatch       # rung 2
python -m task2.train.summarize --runs /project2/yzhao010_1531/haosenca/runs/task2 --split test --by-lang
```

All systems are scored on the same turn-level heads (`train/data.py`): act set, topics, claims (multi-label F1),
addressee, action, Nora answer, side answer (accuracy and macro-F1), suspicion (MAE, quadratic-weighted kappa),
and segmentation (per-character F1, whitespace skipped). Labels are the teacher's unless a split says otherwise.
