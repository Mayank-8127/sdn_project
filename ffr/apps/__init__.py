"""Controller applications, one per recovery strategy."""

from .e2e import PathProtection
from .fa_frr import FailureAwareFRR
from .frr import LocalFRR, NodeFRR
from .reactive import ReactiveRouting
from .static import StaticRouting

APPS = {
    "static": StaticRouting,
    "reactive": ReactiveRouting,
    "frr-link": LocalFRR,
    "frr-node": NodeFRR,
    "e2e": PathProtection,
    "fa-frr": FailureAwareFRR,
}


def get(name: str):
    try:
        return APPS[name]
    except KeyError:
        raise KeyError(f"unknown app {name!r}; choose from {sorted(APPS)}") from None
