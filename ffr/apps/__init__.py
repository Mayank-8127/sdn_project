"""Controller applications, one per recovery strategy."""

from .static import StaticRouting

APPS = {
    "static": StaticRouting,
}


def get(name: str):
    try:
        return APPS[name]
    except KeyError:
        raise KeyError(f"unknown app {name!r}; choose from {sorted(APPS)}") from None
