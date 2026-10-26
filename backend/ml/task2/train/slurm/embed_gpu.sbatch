#!/bin/bash
#SBATCH --account=yzhao010_1531
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=01:00:00
#SBATCH --job-name=t2_rung2
#SBATCH --output=/project2/yzhao010_1531/%u/logs/t2_rung2-%j.out
# Rung 2: frozen multilingual sentence embeddings + logistic regression. MODEL can be overridden with --export.
# Inference only (no training), so any GPU will do; the torch env runs on P100/V100 as well (CUDA 12.6 build).
set -euo pipefail
source /project2/yzhao010_1531/$USER/code/task2/train/slurm/common.sh
MODEL=${MODEL:-intfloat/multilingual-e5-base}
python -m task2.train.baselines.embed --data $DATA --out $RUNS --model $MODEL
python -m task2.train.summarize --runs $RUNS --split test --by-lang
