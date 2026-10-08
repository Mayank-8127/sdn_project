import pytest

from ffr import topology as T
from ffr.network import Network


def detect_time(detection, silent=False, **kw):
    """Time from failure until s1 marks its port towards s2 dead."""
    net = Network(T.ring(3), detection=detection, **kw)
    port = net.switches["s1"].ports[net.switches["s1"].port_to("s2")]
    t_fail = 0.1
    net.schedule_link_failure(t_fail, "s1", "s2", silent=silent)
    seen = []

    def watch():
        if not port.live and not seen:
            seen.append(net.sim.now)
        if net.sim.now < 0.3:
            net.sim.schedule(0.0001, watch)

    net.sim.at(t_fail, watch)
    net.sim.run(0.3)
    return (seen[0] - t_fail) if seen else None, net


def test_los_detects_cuts_quickly_but_not_gray_failures():
    t, _ = detect_time("los", los_delay=0.002)
    assert t == pytest.approx(0.002, abs=2e-4)
    t, _ = detect_time("los", silent=True)
    assert t is None


@pytest.mark.parametrize("interval,mult", [(0.0033, 3), (0.01, 3), (0.001, 5)])
def test_bfd_detection_time_is_about_mult_intervals(interval, mult):
    t, net = detect_time("bfd", silent=True, bfd_interval=interval, bfd_mult=mult)
    assert t is not None
    # between (mult-1) and mult intervals after the last hello made it through
    assert (mult - 1) * interval - 1e-3 <= t <= mult * interval + 2e-4


def test_bfd_overhead_and_no_false_positives_on_long_links():
    # Abilene has 11 ms links, longer than 3 x 3.3 ms: must not cause false alarms.
    net = Network(T.abilene(), detection="bfd")
    net.sim.run(0.5)
    bfd = net.detector("bfd")
    assert bfd.detections == 0
    assert all(p.live for s in net.switches.values() for p in s.ports.values())
    # 2 ends x 14 links x (0.5 s / 3.3 ms)
    assert bfd.sent == pytest.approx(28 * 0.5 / 0.0033, rel=0.02)
    assert net.probe_packets == bfd.sent


def test_bfd_brings_port_back_up_after_repair():
    net = Network(T.ring(3), detection="bfd")
    net.schedule_link_failure(0.1, "s1", "s2", restore_at=0.2, silent=True)
    port = net.switches["s1"].ports[net.switches["s1"].port_to("s2")]
    net.sim.run(0.15)
    assert not port.live
    net.sim.run(0.25)
    assert port.live


def test_no_detection():
    t, _ = detect_time("none")
    assert t is None


def test_unknown_detection():
    with pytest.raises(ValueError):
        Network(T.ring(3), detection="magic")
