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
