import math

import pytest

from ffr import topology as T
from ffr.risk import RiskModel
from ffr.routing import edge


def model(**kw):
    t = T.ring(4)
    t.link("s1", "s2").fail_prob = 0.1
    t.add_srlg("duct", ("s1", "s2"), ("s3", "s4"))
    return RiskModel(t, **kw)


def test_prior_and_cost():
    m = model()
    e = edge("s1", "s2")
    assert m.p(e, 0) == pytest.approx(0.1)
    assert m.risk_cost(e, 0) == pytest.approx(-math.log(0.9))
    assert m.p(edge("s2", "s3"), 0) == 0.0


def test_failure_penalty_decays_with_half_life():
    m = model(half_life=2.0, flap_penalty=0.4)
    e = edge("s2", "s3")
    m.record_failure(e, now=10.0)
    assert m.p(e, 10.0) == pytest.approx(0.4)
    assert m.p(e, 12.0) == pytest.approx(0.2)
    assert m.p(e, 14.0) == pytest.approx(0.1)
    m.record_failure(e, now=14.0)  # flaps again: penalties accumulate
    assert m.p(e, 14.0) == pytest.approx(0.5)


def test_srlg_correlation():
    m = model(flap_penalty=0.4, correlation=0.5)
    assert m.shared_risk(edge("s1", "s2")) == {edge("s3", "s4")}
    m.record_failure(edge("s1", "s2"), now=0.0)
    assert m.p(edge("s3", "s4"), 0.0) == pytest.approx(0.2)
    assert m.p(edge("s2", "s3"), 0.0) == 0.0


def test_path_survival_and_holddown():
    m = model()
    assert m.path_survival(["s1", "s2", "s3"], 0) == pytest.approx(0.9)
    e = edge("s2", "s3")
    assert m.holddown(e, 0, base=1.0) == 1.0
    m.record_failure(e, 0)
    m.record_failure(e, 0)
    assert m.holddown(e, 0, base=1.0) == pytest.approx(3.0)
