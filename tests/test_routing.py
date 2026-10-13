import pytest

from ffr import topology as T
from ffr.routing import Graph, edge, next_hops_to, path_cost, shortest_path


def square():
    #  a --1-- b
    #  |       |
    #  4       1
    #  |       |
    #  d --1-- c
    g = Graph()
    g.add_edge("a", "b", 1)
    g.add_edge("b", "c", 1)
    g.add_edge("c", "d", 1)
    g.add_edge("a", "d", 4)
    return g


def test_shortest_path_and_exclusions():
    g = square()
    assert shortest_path(g, "a", "d") == ["a", "b", "c", "d"]
    assert path_cost(g, ["a", "b", "c", "d"]) == 3
    assert shortest_path(g, "a", "d", excluded_edges=[edge("b", "c")]) == ["a", "d"]
    assert shortest_path(g, "a", "c", excluded_nodes=["b"]) == ["a", "d", "c"]
    assert shortest_path(g, "a", "c", excluded_nodes=["b", "d"]) is None


def test_next_hops_tree():
    g = square()
    nh = next_hops_to(g, "d")
    assert nh == {"c": "d", "b": "c", "a": "b"}


def test_deterministic_ties():
    g = Graph.from_topology(T.ring(4), weight="hops")
    # s1 -> s3 has two equal paths (via s2 or s4); tie broken by name.
    assert shortest_path(g, "s1", "s3") == ["s1", "s2", "s3"]
    assert shortest_path(g, "s3", "s1") == shortest_path(g, "s3", "s1")


def test_from_topology_weights():
    g = Graph.from_topology(T.abilene())
    assert shortest_path(g, "SEA", "NYC")[0] == "SEA"
    gh = Graph.from_topology(T.abilene(), weight="hops")
    assert all(w == 1.0 for nb in gh.adj.values() for w in nb.values())


def trap():
    """The classic 'trap' topology where greedy disjoint routing fails.

        a - b - c - z   (cheap middle path a-b-c-z)
        a - x - c       and  b - y - z
    The shortest path a-b-c-z blocks both alternatives; the optimal
    disjoint pair is a-b-y-z + a-x-c-z.
    """
    g = Graph()
    for u, v, w in [("a", "b", 1), ("b", "c", 1), ("c", "z", 1),
                    ("a", "x", 2), ("x", "c", 2), ("b", "y", 2), ("y", "z", 2)]:
        g.add_edge(u, v, w)
    return g


def test_bhandari_solves_trap_topology():
    from ffr.routing import disjoint_paths, path_edges
    g = trap()
    p1, p2 = disjoint_paths(g, "a", "z")
    assert {tuple(p1), tuple(p2)} == {("a", "b", "y", "z"), ("a", "x", "c", "z")}
    assert not set(path_edges(p1)) & set(path_edges(p2))
    # greedy would fail: removing the shortest path's edges disconnects a from z
    sp = shortest_path(g, "a", "z")
    assert shortest_path(g, "a", "z", excluded_edges=path_edges(sp)) is None


def test_disjoint_on_ring_and_line():
    from ffr.routing import disjoint_paths
    g = Graph.from_topology(T.ring(6), weight="hops")
    p1, p2 = disjoint_paths(g, "s1", "s3")
    assert p1 == ["s1", "s2", "s3"] and p2 == ["s1", "s6", "s5", "s4", "s3"]
    g = Graph.from_topology(T.linear(3))
    assert disjoint_paths(g, "s1", "s3") == (["s1", "s2", "s3"], None)


def test_node_disjoint_differs_from_link_disjoint():
    from ffr.routing import disjoint_paths
    # bow-tie: two triangles sharing node m. Link-disjoint pairs exist,
    # node-disjoint ones do not.
    g = Graph()
    for u, v in [("a", "b"), ("a", "m"), ("b", "m"), ("m", "c"), ("m", "d"), ("c", "d")]:
        g.add_edge(u, v, 1)
    p1, p2 = disjoint_paths(g, "a", "d")
    assert p2 is not None
    assert disjoint_paths(g, "a", "d", node_disjoint=True)[1] is None


@pytest.mark.parametrize("name", ["abilene", "nsfnet", "grid3x3"])
def test_disjoint_pairs_exist_everywhere_on_2_connected(name):
    from ffr.routing import disjoint_paths, path_edges
    g = Graph.from_topology(T.get(name))
    for s in g.nodes:
        for t in g.nodes:
            if s < t:
                for nd in (False, True):
                    p1, p2 = disjoint_paths(g, s, t, node_disjoint=nd)
                    assert p1[0] == p2[0] == s and p1[-1] == p2[-1] == t
                    assert not set(path_edges(p1)) & set(path_edges(p2))
                    if nd:
                        assert not set(p1[1:-1]) & set(p2[1:-1])
