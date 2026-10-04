"""Controller applications, one per recovery strategy."""

from .frr import LocalFRR, NodeFRR
from .reactive import ReactiveRouting
from .static import StaticRouting

APPS = {
    "static": StaticRouting,
    "reactive": ReactiveRouting,
    "frr-link": LocalFRR,
    "frr-node": NodeFRR,
}


def get(name: str):
    try:
        return APPS[name]
    except KeyError:
        raise KeyError(f"unknown app {name!r}; choose from {sorted(APPS)}") from None
