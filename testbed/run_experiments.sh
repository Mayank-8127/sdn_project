#!/usr/bin/env bash
# Run the Mininet scenarios against the FA-FRR controller and keep every log.
#
#   testbed/run_experiments.sh [PYTHON] [RUNS]
#   PING_MS=2 CTRL_DELAY_MS=5 RESULTS=testbed/results-wan testbed/run_experiments.sh [PYTHON] [RUNS]
#
# PYTHON is an interpreter with os-ken and mininet installed (default: python3),
# RUNS the number of repetitions per scenario (default: 3). Needs sudo for
# Mininet, and Open vSwitch must be running. Environment: PING_MS is the probe
# interval (default 10), CTRL_DELAY_MS a one-way delay on the OpenFlow channel
# (default 0), RESULTS the output folder (default testbed/results). Logs go to
# $RESULTS/<scenario>-<run>.{mn,ctl}.log and a summary table to
# $RESULTS/summary.md (see summarise.py).
set -euo pipefail

PY=${1:-python3}
RUNS=${2:-3}
ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT=$(realpath -m "${RESULTS:-$ROOT/testbed/results}")
PING_MS=${PING_MS:-10}
CTRL_DELAY_MS=${CTRL_DELAY_MS:-0}
TOPO=$(mktemp -u /tmp/ffr_topo.XXXXXX.json)
mkdir -p "$OUT"
if ! "$PY" -c "import mininet, os_ken" 2>/dev/null; then
  echo "error: $PY cannot import mininet and os_ken (see README, section 6.2)" >&2
  exit 1
fi
if ! sudo ovs-vsctl show >/dev/null 2>&1; then
  echo "error: Open vSwitch is not running (start ovsdb-server and ovs-vswitchd)" >&2
  exit 1
fi
echo "probe interval ${PING_MS} ms, OpenFlow channel delay ${CTRL_DELAY_MS} ms, results in $OUT"

declare -A SCENARIOS=(
  [cut]="--fail DEN-KSC"
  [gray-nobfd]="--fail DEN-KSC --silent"
  [gray-bfd]="--fail DEN-KSC --silent --bfd"
  [srlg-unaware]="--fail DEN-KSC,SNV-DEN --pairs 12"
  [srlg-aware]="--fail DEN-KSC,SNV-DEN --pairs 12 --srlg duct:DEN-KSC,SNV-DEN"
)

for name in cut gray-nobfd gray-bfd srlg-unaware srlg-aware; do
  for run in $(seq 1 "$RUNS"); do
    echo "=== $name run $run"
    sudo mn -c >/dev/null 2>&1 || true
    sudo rm -f "$TOPO"
    # shellcheck disable=SC2086
    sudo env PYTHONPATH="$ROOT:$ROOT/testbed" "$PY" "$ROOT/testbed/mininet_ffr.py" \
      --topo abilene --topo-file "$TOPO" --ping-ms "$PING_MS" \
      --ctrl-delay-ms "$CTRL_DELAY_MS" ${SCENARIOS[$name]} \
      > "$OUT/$name-$run.mn.log" 2>&1 &
    mn_pid=$!
    for _ in $(seq 60); do [ -f "$TOPO" ] && break; sleep 1; done
    "$PY" -u "$ROOT/testbed/run_controller.py" --topo "$TOPO" \
      > "$OUT/$name-$run.ctl.log" 2>&1 &
    ctl_pid=$!
    wait "$mn_pid"
    kill "$ctl_pid" 2>/dev/null || true
    wait "$ctl_pid" 2>/dev/null || true
    sudo tc qdisc del dev lo root 2>/dev/null || true
  done
done

"$PY" "$ROOT/testbed/summarise.py" "$OUT" | tee "$OUT/summary.md"
