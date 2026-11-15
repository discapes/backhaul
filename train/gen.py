"""Expert experience: the reference planner plays generated seasons (sim.random_scenario); every week becomes one
chat example (observation -> the planner's action). The Harbor task's own season is never among them.

    python gen.py 1000 1800 data/expert.jsonl
"""
import json
import sys
import multiprocessing

from policy import SYSTEM, action_text, observe, server, sim
from reference import decide


def season(seed: int) -> list[dict]:
    m, rows = sim.Market(seed, sim.random_scenario(seed)), []
    while not m.over:
        brief, status = server.brief(m), server.status(m)
        accepts, bids = decide(brief, status)
        rows.append({"seed": seed, "messages": [{"role": "system", "content": SYSTEM},
                                                 {"role": "user", "content": observe(brief, status)},
                                                 {"role": "assistant", "content": action_text(accepts, bids)}]})
        for a in accepts:
            m.accept(a)
        for leg, b in bids.items():
            m.place_bids(leg, [(x["price"], x["tons"]) for x in b])
        m.advance()
    return rows


if __name__ == "__main__":
    lo, hi, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3]
    # spawn: forked workers inherit the solver's thread state and deadlock
    with multiprocessing.get_context("spawn").Pool() as pool, open(out, "w") as f:
        for rows in pool.imap_unordered(season, range(lo, hi)):
            for r in rows:
                f.write(json.dumps(r) + "\n")
