#!/bin/bash
# Full evaluation: reference run, do-nothing and stop-early baselines, and three agent runs; prints each reward.
# Agent flags are passed to `harbor run`, e.g.
#   ./eval.sh -a opencode -m anthropic/claude-opus-5-5
# Each run draws a random market; BACKHAUL_SEED=1 replays the market behind the README results.
set -euo pipefail
cd "$(dirname "$0")"
[ $# -gt 0 ] || { echo "usage: $0 <harbor agent flags, e.g. -a opencode -m provider/model>" >&2; exit 2; }
run=eval-$(date +%Y%m%d-%H%M%S)
h() { name=$1; shift; harbor run -p task -e docker --yes -o "jobs/$run" --job-name "$name" "$@" >"jobs/$run.$name.log" 2>&1 || true; }
mkdir -p "jobs/$run"
h reference -a oracle &
h do-nothing -a nop &
h stop-early -a oracle --ae REFERENCE_WEEKS=2 &
wait
h agent -k 3 -n 3 "$@"
python3 - "jobs/$run" <<'PY'
import json, pathlib, sys
for job in ("reference", "do-nothing", "stop-early", "agent"):
    for trial in sorted((pathlib.Path(sys.argv[1]) / job).glob("*/verifier/score.json")):
        s = json.loads(trial.read_text())
        print(f"{job:11} reward {s['reward']:.3f}  cash {s['cash']:>10,.0f}  weeks played {s['weeks_played_by_agent']}  {trial.parent.parent.name}")
PY
