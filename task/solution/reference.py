"""Reference forwarder: plans the season with a market model built only from the public brief and results.

Space on a sailing costs what other shippers bid for it, not what it costs the carriers to sail. Where other
shippers' demand is below capacity, spare space sells at the carriers' reserve, which sits just above their
per-ton handling cost because the vessels sail anyway. Where demand exceeds capacity, other shippers bid up to
the value of the marginal ton they would otherwise lose, and taking space means outbidding them. Each week the
planner solves a mixed-integer program over the remaining weeks for which orders to ship when and which offers to
accept, then bids this week's part of the plan at one price per sailing.
"""
import asyncio
import json
import os
import sys

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

OTHERS = 1500  # tons per sailing other shippers are assumed to leave for forwarders like us; erring high errs towards scarcity
NOISE = 1.08  # other shippers' realised tons vary around the outlook
MARGIN = 3.0  # bid above the expected rival price, covering the spread of their bids


def reserve_estimate(status: dict, handling: float) -> float:
    """Lowest observed clearing price, raised above any of our bids the carriers rejected as below reserve."""
    clearing = [s["clearing_price"] for wk in status["past_weeks"] for s in wk["sailings"].values()]
    rejected = [b["price"] for wk in status["past_weeks"] for s in wk["sailings"].values()
                for b in s["your_bids"] if b["outcome"] == "below carrier reserve"]
    estimate = min(clearing) if clearing else handling + 1.25
    return max([estimate] + [p + 0.1 for p in rejected])


def levels(brief: dict, leg: str, week: dict, reserve: float) -> list[tuple[float, int]]:
    """Expected (bid price, tons it wins) options on one sailing.

    A bid just above the reserve wins the space other shippers leave. Winning more means outbidding them, and
    since the auction fills from the top down, all our tons on that sailing then need the higher price.
    """
    lo, hi = brief["other_shippers_value_range_per_ton"][leg]
    cap, tons = week["capacity_tons_per_sailing"], week["other_shippers_tons"][leg]
    room = cap - OTHERS
    rival = reserve if tons <= room else hi - (hi - lo) * room / tons
    free = max(0, cap - int(tons * NOISE))
    return ([(reserve + 0.05, free)] if free else []) + [(rival + MARGIN, cap)]


def decide(brief: dict, status: dict) -> tuple[list[str], dict[str, list[dict]]]:
    now = status["week"]
    reserve = reserve_estimate(status, brief["carriers"]["costs"]["cargo_handling_per_ton"])
    orders = [o for o in status["orders"] if o["shipped"] < o["tons"] and o["deadline_week"] >= now]
    offers = status["open_offers"]
    options = {(leg, w["week"]): levels(brief, leg, w, reserve)
               for w in brief["outlook"] if w["week"] >= now for leg in ("south", "north")}

    cols, cost, upper, integer = [], [], [], []
    for o in orders + offers:
        for w in range(max(now, o["ready_week"]), o["deadline_week"] + 1):
            cols.append(("ship", o["id"], o["leg"], w))
            cost.append(-(o["revenue_per_ton"] + o["penalty_per_ton"]))
            upper.append(o["tons"] - o["shipped"])
            integer.append(0)
    for o in offers:
        cols.append(("accept", o["id"]))
        cost.append(o["tons"] * o["penalty_per_ton"])
        upper.append(1)
        integer.append(1)
    for (leg, w), opts in options.items():
        for k, (price, tons) in enumerate(opts):
            cols += [("buy", leg, w, k), ("use", leg, w, k)]
            cost += [price, 0]
            upper += [tons, 1]
            integer += [0, 1]
    index = {c: i for i, c in enumerate(cols)}

    rows, ub = [], []

    def row(entries, bound):
        r = np.zeros(len(cols))
        for c, coef in entries:
            r[index[c]] += coef
        rows.append(r)
        ub.append(bound)

    for o in orders + offers:
        ships = [(c, 1) for c in index if c[0] == "ship" and c[1] == o["id"]]
        if o in offers:
            row(ships + [(("accept", o["id"]), -o["tons"])], 0)
        else:
            row(ships, o["tons"] - o["shipped"])
    for (leg, w), opts in options.items():
        ships = [(c, 1) for c in index if c[0] == "ship" and c[2:] == (leg, w)]
        row(ships + [(("buy", leg, w, k), -1) for k in range(len(opts))], 0)
        for k, (_, tons) in enumerate(opts):
            row([(("buy", leg, w, k), 1), (("use", leg, w, k), -tons)], 0)
        row([(("use", leg, w, k), 1) for k in range(len(opts))], 1)
    res = milp(cost, constraints=LinearConstraint(np.array(rows), -np.inf, ub), integrality=integer,
               bounds=Bounds(0, upper))
    x = dict(zip(cols, res.x))

    accepts = [o["id"] for o in offers if x["accept", o["id"]] > 0.5]
    bids = {}
    for leg in ("south", "north"):
        tons = sum(v for c, v in x.items() if c[0] == "ship" and c[2:] == (leg, now))
        price = next((p for k, (p, _) in enumerate(options[leg, now]) if x["use", leg, now, k] > 0.5), None)
        bids[leg] = [{"price": round(price, 2), "tons": int(round(tons / 100) * 100)}] if tons >= 50 else []
    return accepts, bids


async def play(url: str, weeks: int):
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(url) as streams:
        async with ClientSession(streams[0], streams[1]) as session:
            await session.initialize()

            async def call(name, **args):
                result = await session.call_tool(name, args)
                text = result.content[0].text
                if getattr(result, "is_error", None) or getattr(result, "isError", None):
                    raise RuntimeError(f"{name}: {text}")
                return json.loads(text)

            for _ in range(weeks):
                status = await call("get_status")
                if status["season_over"]:
                    break
                brief = await call("market_brief")
                accepts, bids = decide(brief, status)
                for order_id in accepts:
                    await call("accept_offer", order_id=order_id)
                for leg, leg_bids in bids.items():
                    await call("place_bids", leg=leg, bids=leg_bids)
                report = await call("advance_week")
                print(report["result"]["week"], report["result"]["cash"], accepts, bids, flush=True)


if __name__ == "__main__":
    # Optional argument: number of weeks to play before stopping (the stop-early baseline).
    asyncio.run(play(os.environ.get("MARKET_URL", "http://market:8000/mcp"), int(sys.argv[1]) if len(sys.argv) > 1 else 10))
