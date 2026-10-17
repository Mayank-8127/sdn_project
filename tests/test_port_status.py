import pytest

from ffr import topology as T
from ffr.controller import Controller
from ffr.network import Network


def test_loss_of_signal_reports_both_ends_to_controller():
    net = Network(T.ring(3), los_delay=0.002)
    ctrl = Controller(net, ctrl_delay=0.005)
    net.schedule_link_failure(0.1, "s1", "s2", restore_at=0.2)
    seen = []
    ctrl.note = lambda text: seen.append((round(net.sim.now, 6), text))
    net.sim.run()
    port = net.switches["s1"].ports[net.switches["s1"].port_to("s2")]
    assert port.live
    assert seen == [  # 0.1 failure + 2 ms LOS + 5 ms channel
        (0.107, "port_status s1:1->s2 DOWN"),
        (0.107, "port_status s2:1->s1 DOWN (dup)"),  # the other end reports too
        (0.207, "port_status s1:1->s2 UP"),
        (0.207, "port_status s2:1->s1 UP (dup)"),
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


def test_barrier_fires_after_all_rules_are_installed():
    from ffr.openflow import Match, Output
    net = Network(T.ring(3), rule_install_time=0.002)
    ctrl = Controller(net, ctrl_delay=0.005)
    done = []
    for i in range(3):
        ctrl.install("s1", Match(dst=f"h{i}"), [Output(1)])
    ctrl.install("s2", Match(dst="x"), [Output(1)])
    ctrl.barrier(["s1", "s2"], lambda: done.append((round(net.sim.now, 6), len(net.switches["s1"].table))))
    net.sim.run()
    # s1: arrives 5 ms, 3 rules x 2 ms -> 11 ms, reply +5 ms = 16 ms
    assert done == [(0.016, 3)]
