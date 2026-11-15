"""Full-information optimum: the best season profit given the realised rival bids, as a mixed-integer program.

Each sailing gets at most one price level (see sim.price_levels); each offer is accepted or not; tons of each
order are shipped across the weeks of its window.
"""
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from sim import LEGS, TASK, WEEKS, Scenario, price_levels, rival_bids


def optimum(seed: int, sc: Scenario = TASK) -> float:
    orders = sc.make_orders()
    rivals = rival_bids(seed, sc)
    cols, cost, upper, integer = [], [], [], []  # cost is minimised, so profit enters negated

    def var(key, c, ub, is_int=0):
        cols.append(key)
        cost.append(c)
        upper.append(ub)
        integer.append(is_int)

    for o in orders:
        for w in range(o.ready, o.deadline + 1):
            var(("ship", o.id, o.leg, w), -(o.revenue + o.penalty), o.tons)
        if not o.accepted:
            var(("accept", o.id), o.tons * o.penalty, 1, 1)
    levels = {(leg, w): price_levels(rivals[leg, w], sc.capacity(w)) for leg in LEGS for w in range(1, WEEKS + 1)}
    for (leg, w), lv in levels.items():
        for k, (price, _) in enumerate(lv):
            var(("buy", leg, w, k), price, sc.capacity(w))
            var(("use", leg, w, k), 0, 1, 1)
    index = {key: i for i, key in enumerate(cols)}

    rows, ub = [], []

    def row(entries, bound):
        r = np.zeros(len(cols))
        for key, coef in entries:
            r[index[key]] += coef
        rows.append(r)
        ub.append(bound)

    for o in orders:  # shipped tons of an order <= its tons if accepted
        ships = [(("ship", o.id, o.leg, w), 1) for w in range(o.ready, o.deadline + 1)]
        if o.accepted:
            row(ships, o.tons)
        else:
            row(ships + [(("accept", o.id), -o.tons)], 0)
    for (leg, w), lv in levels.items():
        ships = [(k, 1) for k in index if k[0] == "ship" and k[2:] == (leg, w)]
        row(ships + [(("buy", leg, w, k), -1) for k in range(len(lv))], 0)  # shipped tons <= space bought
        for k, (_, tons) in enumerate(lv):  # a level's tons are only available if that level is used
            row([(("buy", leg, w, k), 1), (("use", leg, w, k), -tons)], 0)
        row([(("use", leg, w, k), 1) for k in range(len(lv))], 1)  # one price per sailing
    res = milp(cost, constraints=LinearConstraint(np.array(rows), -np.inf, ub), integrality=integer,
               bounds=Bounds(0, upper))
    assert res.status == 0, res.message
    committed_penalties = sum(o.tons * o.penalty for o in orders if o.accepted)
    return -res.fun - committed_penalties


def do_nothing(sc: Scenario = TASK) -> float:
    return -sum(o.tons * o.penalty for o in sc.make_orders() if o.accepted)
