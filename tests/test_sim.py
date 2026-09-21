import pytest

from ffr.sim import Simulator


def test_events_run_in_time_order():
    sim = Simulator()
    log = []
    sim.schedule(0.3, log.append, "c")
    sim.schedule(0.1, log.append, "a")
    sim.schedule(0.2, log.append, "b")
    sim.run()
    assert log == ["a", "b", "c"]
    assert sim.now == pytest.approx(0.3)


def test_same_time_is_fifo():
    sim = Simulator()
    log = []
    for i in range(5):
        sim.schedule(1.0, log.append, i)
    sim.run()
    assert log == [0, 1, 2, 3, 4]


def test_run_until_stops_and_advances_clock():
    sim = Simulator()
    log = []
    sim.schedule(1.0, log.append, 1)
    sim.schedule(3.0, log.append, 3)
    sim.run(until=2.0)
    assert log == [1]
    assert sim.now == 2.0
    sim.run()
    assert log == [1, 3]


def test_cancel():
    sim = Simulator()
    log = []
    ev = sim.schedule(1.0, log.append, "x")
    ev.cancel()
    sim.run()
    assert log == []


def test_events_can_schedule_events():
    sim = Simulator()
    log = []

    def tick(n):
        log.append((round(sim.now, 6), n))
        if n < 3:
            sim.schedule(0.5, tick, n + 1)

    sim.schedule(0, tick, 0)
    sim.run()
    assert log == [(0.0, 0), (0.5, 1), (1.0, 2), (1.5, 3)]


def test_no_past_scheduling():
    sim = Simulator()
    with pytest.raises(ValueError):
        sim.schedule(-1, print)
