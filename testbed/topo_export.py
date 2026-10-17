"""Write the JSON topology description shared by Mininet and the controller.

Kept free of Mininet/OS-Ken imports so it can be used (and tested) anywhere.
"""

from __future__ import annotations

import json


def export(topo, switch_port, host_port, path: str) -> dict:
    """``switch_port(a, b)`` -> port on switch a towards b;
    ``host_port(h)`` -> port on h's switch towards h."""
    names = list(topo.switches)
    spec = {
        "name": topo.name,
        "switches": [{"name": s, "dpid": i + 1} for i, s in enumerate(names)],
        "links": [{"a": l.a, "b": l.b, "a_port": switch_port(l.a, l.b),
                   "b_port": switch_port(l.b, l.a), "delay": l.delay,
                   "fail_prob": l.fail_prob} for l in topo.links],
        "srlgs": {},
        "hosts": [],
    }
    for l in topo.links:
        for g in l.srlgs:
            spec["srlgs"].setdefault(g, []).append([l.a, l.b])
    for i, (h, s) in enumerate(sorted(topo.hosts.items())):
        spec["hosts"].append({"name": h, "switch": s, "port": host_port(h),
                              "ip": f"10.0.0.{i + 1}", "mac": f"00:00:00:00:00:{i + 1:02x}"})
    with open(path, "w") as fh:
        json.dump(spec, fh, indent=1)
    return spec
