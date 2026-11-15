"""Baltic short-sea freight market: weekly pay-as-bid space auctions on a fixed Kotka–Lübeck rotation.

The agent is a forwarder holding cargo orders in both directions. A scenario fixes the season (vessels, demand,
news, orders); rival shippers' bids come from the seed and the scenario, independently of the agent, so the
full-information optimum (optimum.py) is exact for the realised market.
"""
import random
from dataclasses import dataclass, field

WEEKS = 10
LEGS = ("south", "north")
HANDLING = 4.0  # carriers' cost per ton loaded: stevedoring, lashing, cargo dues
RESERVE = 5.0  # carriers' confidential floor: handling plus a small margin, since sailings run regardless of load
SHIP_TONS = 2000
FUEL_PER_SAILING = 38_000
OTHER_DEMAND = 1200  # tons per sailing rival shippers expect other forwarders (the agent) to take
VALUES = {"south": (30.0, 70.0), "north": (6.0, 28.0)}  # range of rival shippers' value of a ton of space ($/t)
FLEET = ("Aurora", "Baltic Star", "Kestrel")


@dataclass
class Order:
    id: str
    leg: str
    tons: int
    ready: int
    deadline: int
    revenue: float  # $/t paid by the customer on delivery
    penalty: float  # $/t owed for tons not shipped by the deadline
    offered: int = 0  # week the offer is open; 0 for orders already in the book at the start
    accepted: bool = False
    shipped: int = 0


@dataclass(frozen=True)
class Scenario:
    """Everything about a season except the rival bids: vessels, demand, news, fuel price and the agent's orders."""
    ships: dict  # week -> vessels in service
    late_ship: str | None  # a vessel chartered in late, left out of the outlook until it is announced
    late_ship_announced: int
    south_tons: dict  # week -> rival shippers' tons offered
    north_tons: dict
    fuel_spike_week: int
    fuel_after_spike: int
    orders: tuple  # (id, leg, tons, ready, deadline, revenue, penalty, offered week; 0 = already in the book)
    news: tuple  # (week published, text)

    def capacity(self, week: int) -> int:
        return SHIP_TONS * len(self.ships[week])

    def rival_tons(self, leg: str, week: int) -> int:
        return (self.south_tons if leg == "south" else self.north_tons)[week]

    def published_ships(self, week: int, now: int) -> list[str]:
        return [s for s in self.ships[week] if s != self.late_ship or now >= self.late_ship_announced]

    def make_orders(self) -> list[Order]:
        return [Order(i, leg, tons, ready, deadline, rev, pen, offered, accepted=not offered)
                for i, leg, tons, ready, deadline, rev, pen, offered in self.orders]


def _ships(drydock: tuple[str, int, int] | None, late: tuple[str, int, int] | None) -> dict:
    ships = {}
    for w in range(1, WEEKS + 1):
        ships[w] = [s for s in FLEET if not (drydock and drydock[0] == s and drydock[1] <= w <= drydock[2])]
        if late and late[1] <= w <= late[2]:
            ships[w].append(late[0])
    return ships


# The season every Harbor run plays: the scenario behind all reported results.
TASK = Scenario(
    ships=_ships(("Baltic Star", 6, 7), ("Nordic Swan", 9, 10)),
    late_ship="Nordic Swan", late_ship_announced=6,
    south_tons={1: 7000, 2: 7000, 3: 4500, 4: 4500, 5: 7000, 6: 7000, 7: 7000, 8: 8500, 9: 8500, 10: 7000},
    north_tons={w: 2200 for w in range(1, WEEKS + 1)},
    fuel_spike_week=5, fuel_after_spike=61_000,
    orders=(
        ("S1", "south", 1500, 1, 2, 62, 30, 0), ("S2", "south", 2000, 1, 5, 55, 30, 0),
        ("S3", "south", 1500, 5, 7, 70, 40, 0), ("S4", "south", 2000, 6, 10, 58, 30, 0),
        ("N1", "north", 1200, 1, 3, 20, 15, 0), ("N2", "north", 1500, 4, 8, 18, 15, 0),
        ("N3", "north", 1000, 7, 10, 22, 15, 0),
        ("O1", "north", 1500, 2, 6, 11, 15, 1), ("O2", "south", 1500, 3, 4, 34, 30, 2),
        ("O3", "south", 1000, 6, 7, 42, 30, 4), ("O4", "north", 2000, 6, 9, 13, 15, 5),
        ("O5", "south", 1500, 8, 10, 49, 30, 6), ("O6", "north", 1000, 8, 10, 9, 15, 7),
        ("O7", "south", 800, 9, 10, 60, 30, 8),
    ),
    news=(
        (1, "Metsälä pulp mill near Kotka shuts for maintenance in weeks 3–4. Southbound shipper demand in those "
            "weeks falls to about 4,500 t per sailing (included in the outlook)."),
        (1, "Baltic Star goes to drydock for its class survey in weeks 6–7; two vessels run those weeks "
            "(included in the outlook)."),
        (1, "Pre-holiday paper and retail restocking lifts southbound shipper demand to about 8,500 t per sailing "
            "in weeks 8–9 (included in the outlook)."),
        (5, "Bunker fuel prices rose 60% this week. Fuel now costs the carriers about $61,000 per sailing "
            "(was $38,000)."),
        (6, "The carriers have chartered Nordic Swan (2,000 t) for weeks 9–10 to meet the holiday peak "
            "(included in the outlook)."),
    ),
)


def random_scenario(seed: int) -> Scenario:
    """A different season from the same generator: event timing and size, the fleet, the fuel shock and every order
    vary. Used to produce training experience that never includes the Harbor task's own season."""
    rng = random.Random(f"scenario-{seed}")
    hundreds = lambda lo, hi: rng.randint(lo // 100, hi // 100) * 100  # noqa: E731
    base_s, base_n = hundreds(6500, 7500), hundreds(1800, 2800)
    south = {w: base_s for w in range(1, WEEKS + 1)}
    north = {w: base_n for w in range(1, WEEKS + 1)}
    news = []

    mill = rng.choice(["Metsälä pulp mill", "Kymi paper mill", "Sunila pulp mill", "Hamina board mill"])
    a = rng.randint(2, 4)
    low = hundreds(3800, 5000)
    for w in (a, a + 1):
        south[w] = low
    news.append((1, f"{mill} near Kotka shuts for maintenance in weeks {a}–{a + 1}. Southbound shipper demand in "
                    f"those weeks falls to about {low:,} t per sailing (included in the outlook)."))

    dock = rng.choice(FLEET)
    d = rng.randint(5, 7)
    news.append((1, f"{dock} goes to drydock for its class survey in weeks {d}–{d + 1}; two vessels run those weeks "
                    f"(included in the outlook)."))

    u = rng.randint(7, 9)
    peak = hundreds(8000, 9200)
    for w in (u, u + 1):
        if w <= WEEKS:
            south[w] = max(south[w], peak)
    news.append((1, f"Pre-holiday paper and retail restocking lifts southbound shipper demand to about {peak:,} t per "
                    f"sailing in weeks {u}–{min(u + 1, WEEKS)} (included in the outlook)."))

    if rng.random() < 0.4:  # some seasons have a northbound rush, so the trip home is not always cheap
        n = rng.randint(2, 8)
        rush = hundreds(6500, 7800)
        for w in (n, n + 1):
            north[w] = rush
        news.append((1, f"Wind-turbine components bound for Finland lift northbound shipper demand to about "
                        f"{rush:,} t per sailing in weeks {n}–{n + 1} (included in the outlook)."))

    late = None
    if rng.random() < 0.7:
        name = rng.choice(["Nordic Swan", "Gulf Tern", "Saimaa Star"])
        start = rng.randint(8, 9)
        announced = rng.randint(4, start - 1)
        late = (name, start, WEEKS)
        news.append((announced, f"The carriers have chartered {name} (2,000 t) for weeks {start}–{WEEKS} to meet the "
                                f"holiday peak (included in the outlook)."))

    f = rng.randint(3, 8)
    rise = rng.choice([30, 45, 60, 80])
    after = round(FUEL_PER_SAILING * (1 + rise / 100), -3)
    news.append((f, f"Bunker fuel prices rose {rise}% this week. Fuel now costs the carriers about ${after:,.0f} per "
                    f"sailing (was ${FUEL_PER_SAILING:,})."))

    orders = []
    for k in range(rng.randint(3, 5)):
        r = rng.randint(1, 7)
        orders.append((f"S{k + 1}", "south", hundreds(800, 2200), r, min(WEEKS, r + rng.randint(1, 4)),
                       rng.randint(50, 72), rng.choice([25, 30, 40]), 0))
    for k in range(rng.randint(2, 4)):
        r = rng.randint(1, 7)
        orders.append((f"N{k + 1}", "north", hundreds(800, 1800), r, min(WEEKS, r + rng.randint(2, 4)),
                       rng.randint(15, 24), rng.choice([12, 15, 18]), 0))
    for k in range(rng.randint(5, 8)):
        week = rng.randint(1, 8)
        leg = rng.choice(LEGS)
        r = rng.randint(week, min(WEEKS, week + 2))
        rev = rng.randint(30, 66) if leg == "south" else rng.randint(7, 16)
        orders.append((f"O{k + 1}", leg, hundreds(600, 2000), r, min(WEEKS, r + rng.randint(1, 3)), rev,
                       30 if leg == "south" else 15, week))
    orders.sort(key=lambda o: (o[7] or 0, o[0]))

    return Scenario(ships=_ships((dock, d, d + 1), late), late_ship=late and late[0],
                    late_ship_announced=announced if late else 0,
                    south_tons=south, north_tons=north, fuel_spike_week=f, fuel_after_spike=int(after),
                    orders=tuple(orders), news=tuple(sorted(news, key=lambda n: n[0])))


def rival_bids(seed: int, sc: Scenario = TASK) -> dict[tuple[str, int], list[tuple[float, int]]]:
    """Rival shippers' sealed bids per sailing as (price, tons) lots.

    Each rival knows the outlook and bids the lower of its value and the price it expects to clear the
    sailing, assuming other forwarders take OTHER_DEMAND tons. Where space is plentiful that price is the
    carriers' floor, so rivals bid just above it.
    """
    rng = random.Random(seed)
    bids = {}
    for week in range(1, WEEKS + 1):
        for leg in LEGS:
            lo, hi = VALUES[leg]
            target = sc.rival_tons(leg, week) * rng.uniform(0.95, 1.05)
            lots = []
            while sum(t for _, t in lots) < target:
                lots.append((rng.uniform(lo, hi), rng.choice((100, 200, 300, 400, 500))))
            # Rivals plan against the published outlook, not the realised lots.
            room = sc.capacity(week) - OTHER_DEMAND
            outlook = sc.rival_tons(leg, week)
            expected = RESERVE if outlook <= room else hi - (hi - lo) * room / outlook
            bids[leg, week] = [
                (round(max(RESERVE + rng.uniform(0.05, 0.6), min(v, expected + rng.gauss(0, 1.5))), 2), t)
                for v, t in lots
            ]
    return bids


def price_levels(leg_bids: list[tuple[float, int]], cap: int) -> list[tuple[float, int]]:
    """(bid price, most tons it wins) for an extra bidder on one sailing, cheapest first.

    The carriers fill from the highest bid down, so a bidder's own higher bids take space ahead of its lower
    ones: every ton it wins effectively costs the price needed for its last ton. A bid at the reserve wins the
    space rivals leave; a bid one cent above a rival lot also wins that lot's space and everything below it.
    """
    levels = [(RESERVE, max(0, cap - sum(t for _, t in leg_bids)))]
    for price in sorted({p for p, _ in leg_bids}):
        bid = round(price + 0.01, 2)
        levels.append((bid, min(cap, cap - sum(t for p, t in leg_bids if p >= bid))))
    best = []  # drop levels that win no more space than a cheaper one
    for price, tons in levels:
        if tons > 0 and (not best or tons > best[-1][1]):
            best.append((price, tons))
    return best


@dataclass
class Market:
    seed: int
    scenario: Scenario = TASK
    week: int = 1
    orders: dict[str, Order] = field(default_factory=dict)
    bids: dict[str, list[tuple[float, int]]] = field(default_factory=lambda: {leg: [] for leg in LEGS})
    cash: float = 0.0
    freight_paid: float = 0.0
    revenue: float = 0.0
    penalties: float = 0.0
    history: list[dict] = field(default_factory=list)

    def __post_init__(self):
        self.rivals = rival_bids(self.seed, self.scenario)
        self.orders = {o.id: o for o in self.scenario.make_orders()}

    @property
    def over(self) -> bool:
        return self.week > WEEKS

    def open_offers(self) -> list[Order]:
        return [o for o in self.orders.values() if o.offered == self.week and not o.accepted]

    def book(self) -> list[Order]:
        return [o for o in self.orders.values() if o.accepted]

    def accept(self, order_id: str) -> Order:
        o = self.orders.get(order_id)
        if self.over or o is None or o.offered != self.week:
            raise ValueError(f"{order_id} is not an open offer this week")
        o.accepted = True
        return o

    def place_bids(self, leg: str, bids: list[tuple[float, int]]):
        if self.over:
            raise ValueError("the season is over")
        if leg not in LEGS:
            raise ValueError(f"leg must be one of {LEGS}")
        clean = []
        for price, tons in bids:
            if not (0 < price <= 500) or not (0 < tons <= 20_000) or int(tons) != tons:
                raise ValueError("each bid needs 0 < price <= 500 $/t and a whole number of tons in 1..20000")
            clean.append((round(float(price), 2), int(tons)))
        if sum(t for _, t in clean) > 20_000:
            raise ValueError("at most 20000 t of bids per sailing")
        self.bids[leg] = clean

    def advance(self) -> dict:
        """Run both auctions for the current week, load cargo, settle deadlines and move to the next week."""
        if self.over:
            raise ValueError("the season is over")
        week, report = self.week, {"week": self.week, "sailings": {}}
        for leg in LEGS:
            report["sailings"][leg] = self._auction(leg, week)
        for o in self.book():
            if o.deadline == week and o.shipped < o.tons:
                due = (o.tons - o.shipped) * o.penalty
                self.penalties += due
                self.cash -= due
                report.setdefault("missed_deadlines", []).append(
                    {"order": o.id, "tons_unshipped": o.tons - o.shipped, "penalty": due})
        report["cash"] = round(self.cash, 2)
        self.history.append(report)
        self.bids = {leg: [] for leg in LEGS}
        self.week += 1
        return report

    def _auction(self, leg: str, week: int) -> dict:
        ours = [(p, t, i) for i, (p, t) in enumerate(self.bids[leg])]
        # Rivals rank ahead of the agent at equal prices.
        entries = [(p, 1, t, None) for p, t in self.rivals[leg, week]] + [(p, 0, t, i) for p, t, i in ours]
        entries.sort(key=lambda e: (e[0], e[1]), reverse=True)
        left, won, accepted_prices = self.scenario.capacity(week), {}, []
        for price, _, tons, idx in entries:
            if price < RESERVE or left == 0:
                continue
            take = min(tons, left)
            left -= take
            accepted_prices.append(price)
            if idx is not None:
                won[idx] = take
        results = []
        for p, t, i in ours:
            w = won.get(i, 0)
            results.append({"price": p, "tons_bid": t, "tons_won": w,
                            "outcome": "won" if w == t else "partly won" if w else
                            "below carrier reserve" if p < RESERVE else "outbid"})
        bought = sum(won.values())
        cost = sum(p * won.get(i, 0) for p, _, i in ours)
        self.freight_paid += cost
        self.cash -= cost
        loaded = self._load(leg, week, bought)
        return {"ships": self.scenario.ships[week], "capacity_tons": self.scenario.capacity(week), "clearing_price": min(accepted_prices),
                "your_bids": results, "space_bought_tons": bought, "freight_paid": round(cost, 2),
                "loaded": loaded, "unused_space_tons": bought - sum(loaded.values())}

    def _load(self, leg: str, week: int, space: int) -> dict[str, int]:
        """Fill bought space with ready cargo, earliest deadline first, then the most valuable."""
        loaded = {}
        due = sorted((o for o in self.book() if o.leg == leg and o.ready <= week <= o.deadline and o.shipped < o.tons),
                     key=lambda o: (o.deadline, -(o.revenue + o.penalty)))
        for o in due:
            take = min(space, o.tons - o.shipped)
            if take:
                o.shipped += take
                space -= take
                loaded[o.id] = take
                self.revenue += take * o.revenue
                self.cash += take * o.revenue
        return loaded

    def finish(self):
        """Play out any remaining weeks with no bids, as when the agent stops early."""
        while not self.over:
            self.advance()
