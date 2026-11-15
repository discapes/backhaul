#!/bin/bash
# Runs on a GPU machine from the directory holding backhaul/: trains the LoRA on the expert experience, then plays the
# Harbor task's season (seeds 1-30) and 30 unseen generated seasons with the base model and the fine-tuned one.
# Usage: bash backhaul/train/job.sh [expert data file]
set -euo pipefail
MODEL=${MODEL:-Qwen/Qwen3-4B-Instruct-2507}
DATA=${1:-data/expert.jsonl}
cd backhaul/train
nvidia-smi conf-compute -srs 1 2>/dev/null || true  # confidential-computing GPUs refuse CUDA until set ready
if [ ! -x venv/bin/python ]; then
  curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null
  export PATH=$HOME/.local/bin:$PATH
  uv venv -q --python 3.12 venv
  uv pip install -q --python venv/bin/python torch transformers trl peft datasets fastmcp==4.2.0 scipy==1.18.1 numpy
fi
source venv/bin/activate
mkdir -p results

python sft.py "$MODEL" "$DATA" out/lora > logs-train.txt 2>&1
for spec in "base:$MODEL" "tuned:$MODEL+out/lora"; do
  label=${spec%%:*} model=${spec#*:}
  python evaluate.py hf "$model" 1 31 "results/$label-task.json"
  SCENARIOS=generated python evaluate.py hf "$model" 9000 9030 "results/$label-generated.json"
done
touch done
