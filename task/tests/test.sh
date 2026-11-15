#!/bin/bash
# Reads the score from the market sidecar, which first plays out any weeks the agent left unplayed.
# Runs as root: stop everything the agent user left running so nothing can rewrite the reward afterwards, and
# run Python isolated so modules planted in the working directory are not imported.
pkill -9 -u agent || true
# Remove anything the agent wrote into the verifier directory (a pre-written reward.txt or reward.json would
# otherwise stand if scoring failed).
find /logs/verifier -mindepth 1 ! -name 'test-std*' -delete
cd /
/usr/bin/python3 -I - <<'PY'
import json, os, urllib.request
req = urllib.request.Request("http://market:8000/score", headers={"Authorization": f"Bearer {os.environ['SCORE_TOKEN']}"})
score = json.load(urllib.request.urlopen(req, timeout=60))
json.dump(score, open("/logs/verifier/score.json", "w"), indent=1)
open("/logs/verifier/reward.txt", "w").write(f"{score['reward']}\n")
print({k: score[k] for k in ("reward", "cash", "optimum", "do_nothing", "weeks_played_by_agent")})
PY
