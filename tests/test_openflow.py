from ffr.openflow import ANY, FlowEntry, FlowTable, Match, Output
from ffr.packet import Packet


def pkt(src="a", dst="b", tag=None):
    return Packet(src, dst, tag=tag)


def test_match_wildcards_and_tag_semantics():
    assert Match().matches(pkt(), 1)
    assert Match(dst="b").matches(pkt(), 1)
    assert not Match(dst="c").matches(pkt(), 1)
    assert Match(in_port=1).matches(pkt(), 1)
    assert not Match(in_port=2).matches(pkt(), 1)
    # tag=None means "untagged only"; ANY means any tag.
    assert Match(tag=None).matches(pkt(), 1)
    assert not Match(tag=None).matches(pkt(tag=7), 1)
    assert Match(tag=7).matches(pkt(tag=7), 1)
    assert Match(tag=ANY).matches(pkt(tag=7), 1)


def test_priority_wins_regardless_of_index_bucket():
    t = FlowTable()
    t.add(FlowEntry(Match(), (Output(9),), priority=0))
    t.add(FlowEntry(Match(dst="b"), (Output(1),), priority=10))
    t.add(FlowEntry(Match(dst="b", tag=5), (Output(2),), priority=20))
    assert t.lookup(pkt(), 1).actions == (Output(1),)
    assert t.lookup(pkt(tag=5), 1).actions == (Output(2),)
    assert t.lookup(pkt(dst="zzz"), 1).actions == (Output(9),)
    # wildcard-dst rule with higher priority beats a dst rule
    t.add(FlowEntry(Match(src="a"), (Output(3),), priority=50))
    assert t.lookup(pkt(), 1).actions == (Output(3),)


def test_add_replaces_identical_and_delete():
    t = FlowTable()
    t.add(FlowEntry(Match(dst="b"), (Output(1),), cookie=1))
    t.add(FlowEntry(Match(dst="b"), (Output(2),), cookie=1))
    assert len(t) == 1
    assert t.lookup(pkt(), None).actions == (Output(2),)
    t.add(FlowEntry(Match(dst="c"), (Output(3),), cookie=2))
    assert t.delete(cookie=1) == 1
    assert len(t) == 1
    assert t.lookup(pkt(), None) is None
    assert t.misses == 1
