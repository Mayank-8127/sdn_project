import pytest

from ffr import topology as T
from ffr.controller import Controller
from ffr.network import Network


def test_loss_of_signal_reports_both_ends_to_controller():
    net = Network(T.ring(3), los_delay=0.002)
    ctrl = Controller(net, ctrl_delay=0.005)
    net.schedule_link_failure(0.1, "s1", "s2", restore_at=0.2)
    seen = []
    ctrl.on_port_status = lambda msg, changed: seen.append((round(net.sim.now, 6), msg.switch, msg.live, changed))
    net.sim.run()
    port = net.switches["s1"].ports[net.switches["s1"].port_to("s2")]
    assert port.live
    assert seen == [
        (0.107, "s1", False, True),   # 0.1 failure + 2 ms LOS + 5 ms channel
        (0.107, "s2", False, False),  # duplicate report from the other end
        (0.207, "s1", True, True),
        (0.207, "s2", True, False),
    ]
    assert ctrl.down_links == set()


def test_port_goes_non_live_after_detection_delay():
    net = Network(T.linear(2), los_delay=0.01)
    net.schedule_link_failure(0.1, "s1", "s2")
    p = net.switches["s1"].ports[1]
    net.sim.run(until=0.105)
    assert not net.link("s1", "s2").up and p.live  # cut, not yet noticed
    net.sim.run(until=0.111)
    assert not p.live
