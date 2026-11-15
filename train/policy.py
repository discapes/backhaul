"""A one-call-per-week policy interface to the Backhaul market, for small models.

Each week the model reads a compact text observation, built from the same `market_brief` and `get_status` data the
MCP tools return, and answers with one JSON action. `play` runs a season against the market simulator the MCP server
wraps and scores it the way the verifier does.
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "task/environment/market"), str(ROOT / "task/solution")]
os.environ.setdefault("SCORE_TOKEN", "unused")

import server  # noqa: E402
import sim  # noqa: E402
from optimum import do_nothing, optimum  # noqa: E402

SYSTEM = """You run the Baltic desk of Tern Forwarding for a 10-week season and want to end it with as much cash as possible.
Each week has one southbound sailing (Kotka to Lübeck) and one northbound sailing (Lübeck to Kotka). Space on each \
sailing is sold in a sealed-bid auction: the carriers fill the sailing from the highest bid down until capacity runs \
out and accept no bid below a confidential reserve. Every winning bid pays its own price, and you pay for space you \
win even if you have no cargo for it. Won space is loaded with your ready cargo, earliest deadline first; customers \
pay the order's revenue per ton when it is loaded, and tons not shipped by the deadline cost the order's penalty per \
ton. Offers can only be accepted in the week they are offered. Other shippers see the same outlook and news and bid \
with them in mind.
Reply with only a JSON object: {"accept": [offer ids], "bids": {"south": [{"price": $/t, "tons": t}], "north": [...]}}"""


def observe(brief: dict, status: dict) -> str:
    """Compact text of everything the agent can see this week."""
    lo_s, hi_s = brief["other_shippers_value_range_per_ton"]["south"]
    lo_n, hi_n = brief["other_shippers_value_range_per_ton"]["north"]
    costs = brief["carriers"]["costs"]
    lines = [f"Week {status['week']} of 10. Cash ${status['cash']:,.0f}.",
             f"Carrier costs: fuel ${costs['fuel_per_sailing']:,} per sailing, port dues ${costs['port_dues_per_call']:,} "
             f"per call, charter ${costs['charter_hire_per_vessel_week']:,} per vessel-week, cargo handling "
             f"${costs['cargo_handling_per_ton']}/t. Vessels sail both legs every week whatever their load.",
             f"Other shippers value space at ${lo_s:g}-{hi_s:g}/t southbound and ${lo_n:g}-{hi_n:g}/t northbound.",
             "Outlook (week: capacity t, other shippers' south t / north t):"]
    lines += [f"  W{o['week']}: {o['capacity_tons_per_sailing']}, {o['other_shippers_tons']['south']} / "
              f"{o['other_shippers_tons']['north']}" for o in brief["outlook"] if o["week"] >= status["week"]]
    lines.append("News: " + " ".join(n["text"] for n in brief["news"]))
    lines.append("Your orders (id leg tons-left ready-deadline revenue/t penalty/t):")
    lines += [f"  {o['id']} {o['leg']} {o['tons'] - o['shipped']} W{o['ready_week']}-W{o['deadline_week']} "
              f"${o['revenue_per_ton']} ${o['penalty_per_ton']}"
              for o in status["orders"] if o["shipped"] < o["tons"] and o["deadline_week"] >= status["week"]]
    lines.append("Open offers: " + ("; ".join(
        f"{o['id']} {o['leg']} {o['tons']} t W{o['ready_week']}-W{o['deadline_week']} ${o['revenue_per_ton']}/t "
        f"penalty ${o['penalty_per_ton']}/t" for o in status["open_offers"]) or "none"))
    past = []
    for wk in status["past_weeks"]:
        parts = []
        for leg in ("south", "north"):
            s = wk["sailings"][leg]
            mine = ", ".join(f"{b['tons_won']}/{b['tons_bid']} t at ${b['price']:g}" for b in s["your_bids"]) or "no bids"
            parts.append(f"{leg[0].upper()} cleared ${s['clearing_price']:g} ({mine})")
        past.append(f"  W{wk['week']}: " + "; ".join(parts))
    if past:
        lines.append("Past auctions (clearing price, your bids won/bid):")
        lines += past
    return "\n".join(lines)


def action_text(accepts: list[str], bids: dict[str, list[dict]]) -> str:
    return json.dumps({"accept": accepts, "bids": {leg: bids.get(leg, []) for leg in ("south", "north")}})


def parse(text: str) -> tuple[list[str], dict[str, list[dict]]]:
    """The first JSON object in a reply; raises ValueError when there is none."""
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("no JSON object")
    a = json.loads(m.group(0))
    return list(a.get("accept", [])), {leg: list(a.get("bids", {}).get(leg, [])) for leg in ("south", "north")}


def apply(m: sim.Market, reply: str) -> int:
    """Apply a reply's moves one by one, as separate MCP tool calls would be; returns how many were refused."""
    try:
        accepts, bids = parse(reply)
    except (ValueError, TypeError, AttributeError):
        return 1
    refused = 0
    for a in accepts:
        try:
            m.accept(a)
        except (ValueError, TypeError):
            refused += 1
    for leg, b in bids.items():
        try:
            m.place_bids(leg, [(x["price"], x["tons"]) for x in b])
        except (ValueError, KeyError, TypeError):
            refused += 1
    return refused


def play(seed: int, policy, sc: sim.Scenario = sim.TASK) -> dict:
    """One season. `policy(observation) -> reply text`; refused moves are skipped, as tool errors would be."""
    m = sim.Market(seed, sc)
    errors = 0
    while not m.over:
        errors += apply(m, policy(observe(server.brief(m), server.status(m))))
        m.advance()
    best, base = optimum(seed, sc), do_nothing(sc)
    return {"seed": seed, "cash": m.cash, "reward": max(0.0, min(1.0, (m.cash - base) / (best - base))), "errors": errors}


def play_batch(seeds: list[int], generate, scenario) -> list[dict]:
    """Seasons played in lockstep: each week `generate(observations) -> replies` answers every season at once."""
    markets = [sim.Market(s, scenario(s)) for s in seeds]
    errors = [0] * len(seeds)
    while not markets[0].over:
        replies = generate([observe(server.brief(m), server.status(m)) for m in markets])
        for i, (m, reply) in enumerate(zip(markets, replies)):
            errors[i] += apply(m, reply)
            m.advance()
    out = []
    for s, m, e in zip(seeds, markets, errors):
        best, base = optimum(s, m.scenario), do_nothing(m.scenario)
        out.append({"seed": s, "cash": m.cash, "reward": max(0.0, min(1.0, (m.cash - base) / (best - base))), "errors": e})
    return out
