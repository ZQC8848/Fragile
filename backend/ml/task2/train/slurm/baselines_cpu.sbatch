#!/bin/bash
#SBATCH --account=yzhao010_1531
#SBATCH --partition=main
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=t2_rung01
#SBATCH --output=/project2/yzhao010_1531/%u/logs/t2_rung01-%j.out
# Rung 0 (rules, majority) and rung 1 (TF-IDF + logistic regression) on CPU.
set -euo pipefail
source /project2/yzhao010_1531/$USER/code/task2/train/slurm/common.sh
python -m task2.train.baselines.rule_teacher --data $DATA --out $RUNS
python -m task2.train.baselines.tfidf --data $DATA --out $RUNS
python -m task2.train.summarize --runs $RUNS --split test --by-lang
