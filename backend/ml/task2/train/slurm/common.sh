# Sourced by the task 2 job scripts: conda env, caches, and the code/data/run locations on CARC.
module purge
module load conda
source "$(conda info --base)/etc/profile.d/conda.sh"
conda activate torch
export HF_HOME=/scratch1/$USER/.cache/huggingface
export TASK2_ROOT=/project2/yzhao010_1531/$USER
export PYTHONPATH=$TASK2_ROOT/code:$PYTHONPATH
export DATA=$TASK2_ROOT/data/task2/examples
export RUNS=$TASK2_ROOT/runs/task2
cd $TASK2_ROOT/code
