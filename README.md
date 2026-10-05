# Failure-Aware Fast Rerouting in SDN

An implementation and study of **fast failure recovery
in Software-Defined Networks (SDN)**: a deterministic OpenFlow
emulator in pure Python, and controller apps implementing increasingly
advanced recovery strategies.

## Quick start

```bash
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest
.venv/bin/python -m ffr run --topo abilene --app static --fail DEN-KSC@0.3 -v
```

## Versions

| Tag | Adds |
|-----|------|
| v0.1 | emulator + static shortest-path controller (no recovery) |
| v0.2 | PORT_STATUS + reactive restoration by the controller |
| v0.3 | fast-failover groups + tagged detours (frr-link, frr-node) |
