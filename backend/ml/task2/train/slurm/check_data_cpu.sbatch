#!/bin/bash
#SBATCH --account=yzhao010_1531
#SBATCH --partition=main
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --job-name=t2_check
#SBATCH --output=/project2/yzhao010_1531/%u/logs/t2_check-%j.out
set -euo pipefail
source /project2/yzhao010_1531/$USER/code/task2/train/slurm/common.sh
python -m task2.train.check_data --examples $DATA/train.jsonl
