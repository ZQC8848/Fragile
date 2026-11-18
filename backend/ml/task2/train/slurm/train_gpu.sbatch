#!/bin/bash
#SBATCH --account=yzhao010_1531
#SBATCH --partition=gpu
#SBATCH --gres=gpu:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --time=02:00:00
#SBATCH --job-name=t2_rung4
#SBATCH --array=0-2
#SBATCH --output=/project2/yzhao010_1531/%u/logs/t2_rung4-%A_%a.out
# Rung 4: multi-head mDeBERTa, one seed per array task. Extra flags for ablations go in ARGS and NAME, e.g.
#   sbatch --export=ALL,NAME=rung4_unc,ARGS="--uncertainty" train_gpu.sbatch
# Any GPU works (the env runs on P100/V100 too); bf16 is used only where supported.
set -euo pipefail
source /project2/yzhao010_1531/$USER/code/task2/train/slurm/common.sh
NAME=${NAME:-rung4_mdeberta}
ARGS=${ARGS:-}
SEED=${SLURM_ARRAY_TASK_ID:-0}
python -m task2.train.train --data $DATA --out $RUNS --name ${NAME}_s${SEED} --seed $SEED $ARGS
