"""Failure awareness: what the controller knows about how the network fails.

Three kinds of knowledge are combined:

1. **Priors.** Each link starts with a failure probability ``p0(e)`` (from the
   topology: history, fibre length, ...).
2. **Experience.** Every observed failure of a link adds a *penalty* that
   decays exponentially with half-life ``half_life``, the same idea as BGP
   route-flap damping (RFC 2439). A link that failed recently, or flaps, is
   considered risky; one that has been stable for a long time is forgiven.
   Links sharing an SRLG with the failed link get a fraction of the penalty
   (``correlation``), since correlated failures tend to follow.
3. **Shared risk.** SRLG membership tells which links may fail *together*,
   so a backup must not share an SRLG with what it protects.

The probability of link ``e`` failing is ``p(e) = min(p_max, p0(e) + penalty(e))``.

For routing we convert probabilities into additive costs. A path survives if
all its links survive: ``P(survive) = Π (1 - p(e))``. Taking ``-ln`` turns the
product into a sum, so ``risk_cost(e) = -ln(1 - p(e))`` can be added along a
path and minimising it maximises the survival probability. The routing
weight trades latency for reliability with a factor ``lam``::

    w(e) = delay(e) / mean_delay + lam * risk_cost(e)
"""

from __future__ import annotations

import math

from .routing import Edge, edge


class RiskModel:
    def __init__(self, topo, half_life: float = 5.0, flap_penalty: float = 0.3,
                 correlation: float = 0.5, p_max: float = 0.99):
        self.half_life = half_life
        self.flap_penalty = flap_penalty
        self.correlation = correlation
        self.p_max = p_max
        self.prior: dict[Edge, float] = {}
        self.delay: dict[Edge, float] = {}
        self.srlgs: dict[Edge, set[str]] = {}
        self._penalty: dict[Edge, tuple[float, float]] = {}  # e -> (value, time)
        self.failures: dict[Edge, int] = {}
        for l in topo.links:
            e = edge(l.a, l.b)
            self.prior[e] = l.fail_prob
            self.delay[e] = l.delay
            self.srlgs[e] = set(l.srlgs)
        self.mean_delay = (sum(self.delay.values()) / len(self.delay)) if self.delay else 1.0

    # -- penalties -------------------------------------------------------------
    def penalty(self, e: Edge, now: float) -> float:
        value, t = self._penalty.get(e, (0.0, now))
        return value * 0.5 ** ((now - t) / self.half_life)

    def _add_penalty(self, e: Edge, amount: float, now: float) -> None:
        self._penalty[e] = (self.penalty(e, now) + amount, now)

    def record_failure(self, e: Edge, now: float) -> None:
        """A failure of ``e`` was observed at ``now``."""
        self.failures[e] = self.failures.get(e, 0) + 1
        self._add_penalty(e, self.flap_penalty, now)
        for other in self.shared_risk(e):
            self._add_penalty(other, self.flap_penalty * self.correlation, now)

    # -- queries -----------------------------------------------------------------
    def p(self, e: Edge, now: float) -> float:
        return min(self.p_max, self.prior.get(e, 0.0) + self.penalty(e, now))

    def risk_cost(self, e: Edge, now: float) -> float:
        return -math.log(1.0 - self.p(e, now))

    def weight(self, e: Edge, now: float, lam: float) -> float:
        return self.delay[e] / self.mean_delay + lam * self.risk_cost(e, now)

    def shared_risk(self, e: Edge) -> set[Edge]:
        """Other links that share at least one SRLG with ``e``."""
        groups = self.srlgs.get(e, set())
        if not groups:
            return set()
        return {o for o, g in self.srlgs.items() if o != e and g & groups}

    def path_survival(self, path: list[str], now: float) -> float:
        prob = 1.0
        for a, b in zip(path, path[1:]):
            prob *= 1.0 - self.p(edge(a, b), now)
        return prob

    def holddown(self, e: Edge, now: float, base: float) -> float:
        """How long a recovered link must stay up before it is trusted again.

        Grows with the link's recent instability: a link that keeps flapping
        is kept out of service for longer.
        """
        return base * (1.0 + self.penalty(e, now) / self.flap_penalty)
