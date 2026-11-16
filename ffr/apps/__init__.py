"""Controller applications, one per recovery strategy."""

from .e2e import PathProtection, SrlgPathProtection
from .fa_frr import FailureAwareFRR
from .frr import LocalFRR, NodeFRR, SrlgNodeFRR
from .reactive import ReactiveRouting
from .static import StaticRouting

APPS = {
    "static": StaticRouting,
    "reactive": ReactiveRouting,
    "frr-link": LocalFRR,
    "frr-node": NodeFRR,
    "frr-srlg": SrlgNodeFRR,
    "e2e": PathProtection,
    "e2e-srlg": SrlgPathProtection,
    "fa-frr": FailureAwareFRR,
}


def get(name: str):
    try:
        return APPS[name]
    except KeyError:
        raise KeyError(f"unknown app {name!r}; choose from {sorted(APPS)}") from None
