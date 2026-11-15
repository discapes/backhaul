"""MCP server for the Backhaul market. One market per container; the verifier reads /score with a token."""
import os
import secrets
import threading

from fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

import sim
from optimum import do_nothing, optimum

# A random seed per container keeps rival bids unknowable even to an agent that has read this source.
SEED = int(os.environ.get("SEED") or secrets.randbits(32))
TOKEN = os.environ["SCORE_TOKEN"]

RULES = """\
You run the Baltic desk of Tern Forwarding. Each week has one southbound sailing (Kotka → Lübeck) and one \
northbound sailing (Lübeck → Kotka). The season lasts 10 weeks. Your result is your cash balance after week 10.

Space auctions
- Space on each sailing is sold in a sealed-bid auction. A bid is a price in $/t and a number of tons; you may \
place several bids per sailing at different prices.
- The carriers fill the sailing from the highest bid down until its capacity runs out, and accept no bid below \
their confidential reserve price. At equal prices, other shippers' bids rank first.
- Every winning bid pays its own price for the tons it wins (pay-as-bid). You pay for space you win even if you \
have no ready cargo to fill it.
- After the auction, each sailing's clearing price (the lowest accepted bid) is published.

Cargo
- Space you win is loaded with your ready cargo on that leg, earliest deadline first.
- An order can ship in any week from its ready week to its deadline, split across weeks if you like. The \
customer pays the order's revenue per ton when it is loaded. Tons not shipped by the deadline cost the order's \
penalty per ton.
- New customer orders are offered during the season. An offer can only be accepted in the week it is offered; \
accepting it makes it a binding order.

Other shippers
- Many other shippers bid for the same space. They see the same outlook and news you do. Each values a ton of \
space on a sailing somewhere in that leg's value range, spread evenly, and bids with that in mind.
"""

CARRIERS = {
    "operators": "Three ro-ro vessels of 2,000 t each run a fixed weekly rotation. Every vessel in service sails "
                 "both legs every week, whatever its load.",
    "costs": {"charter_hire_per_vessel_week": 55_000, "fuel_per_sailing": sim.FUEL_PER_SAILING,
              "port_dues_per_call": 9_000, "cargo_handling_per_ton": sim.HANDLING},
}

market = sim.Market(SEED)
lock = threading.Lock()
mcp = FastMCP("backhaul")


def order_view(o: sim.Order) -> dict:
    return {"id": o.id, "leg": o.leg, "tons": o.tons, "shipped": o.shipped, "ready_week": o.ready,
            "deadline_week": o.deadline, "revenue_per_ton": o.revenue, "penalty_per_ton": o.penalty}


def brief(m: sim.Market) -> dict:
    now, sc = min(m.week, sim.WEEKS), m.scenario
    outlook = []
    for w in range(1, sim.WEEKS + 1):
        ships = sc.published_ships(w, now)
        outlook.append({"week": w, "vessels": ships, "capacity_tons_per_sailing": sim.SHIP_TONS * len(ships),
                        "other_shippers_tons": {leg: sc.rival_tons(leg, w) for leg in sim.LEGS}})
    costs = dict(CARRIERS["costs"])
    if now >= sc.fuel_spike_week:
        costs["fuel_per_sailing"] = sc.fuel_after_spike
    return {"rules": RULES, "carriers": {**CARRIERS, "costs": costs},
            "other_shippers_value_range_per_ton": {leg: list(r) for leg, r in sim.VALUES.items()},
            "outlook": outlook, "news": [{"week": w, "text": t} for w, t in sc.news if w <= now]}


def status(m: sim.Market) -> dict:
    return {"week": None if m.over else m.week, "season_over": m.over, "cash": round(m.cash, 2),
            "freight_paid": round(m.freight_paid, 2), "revenue": round(m.revenue, 2),
            "penalties": round(m.penalties, 2),
            "orders": [order_view(o) for o in m.book()],
            "open_offers": [order_view(o) for o in m.open_offers()],
            "bids_this_week": {leg: [{"price": p, "tons": t} for p, t in b] for leg, b in m.bids.items()},
            "past_weeks": m.history}


@mcp.tool()
def market_brief() -> dict:
    """Market rules, carrier costs, the 10-week outlook of capacity and other shippers' demand, and news to date."""
    with lock:
        return brief(market)


@mcp.tool()
def get_status() -> dict:
    """Current week, cash, your orders, open offers, bids placed this week and every past week's auction results."""
    with lock:
        return status(market)


@mcp.tool()
def accept_offer(order_id: str) -> dict:
    """Accept an open offer, making it a binding order. Offers expire when the week advances."""
    with lock:
        return {"accepted": order_view(market.accept(order_id))}


@mcp.tool()
def place_bids(leg: str, bids: list[dict]) -> dict:
    """Set this week's bids for one sailing, replacing earlier bids on it.

    leg: "south" or "north". bids: list of {"price": $/t, "tons": whole tons}; an empty list withdraws all bids.
    """
    with lock:
        market.place_bids(leg, [(b["price"], b["tons"]) for b in bids])
        return {"week": market.week, "leg": leg, "bids": [{"price": p, "tons": t} for p, t in market.bids[leg]]}


@mcp.tool()
def advance_week() -> dict:
    """Close this week: run both auctions, load cargo, charge penalties for missed deadlines, and start the next week."""
    with lock:
        report = market.advance()
        return {"result": report, "next_week": None if market.over else market.week}


OPTIMUM, DO_NOTHING = optimum(SEED), do_nothing()


@mcp.custom_route("/score", methods=["GET"])
async def score(request: Request) -> JSONResponse:
    if request.headers.get("authorization") != f"Bearer {TOKEN}":
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    with lock:
        weeks_played = len(market.history)
        market.finish()
        reward = (market.cash - DO_NOTHING) / (OPTIMUM - DO_NOTHING)
        return JSONResponse({
            "reward": round(min(1.0, max(0.0, reward)), 4), "cash": round(market.cash, 2),
            "optimum": round(OPTIMUM, 2), "do_nothing": DO_NOTHING, "weeks_played_by_agent": weeks_played,
            "freight_paid": round(market.freight_paid, 2), "revenue": round(market.revenue, 2),
            "penalties": round(market.penalties, 2), "seed": SEED,
            "orders": [order_view(o) for o in market.book()], "weeks": market.history})


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
