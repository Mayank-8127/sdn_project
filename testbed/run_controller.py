#!/usr/bin/env python3
"""Start the FA-FRR controller with OS-Ken (no osken-manager binary needed).

Recent OS-Ken releases (4.x) are a library without the old ``osken-manager``
command, so this tiny launcher loads the OpenFlow handler plus our app::

    FFR_TOPO=/tmp/ffr_topo.json python3 testbed/run_controller.py [--port 6653]

With classic Ryu you can instead run ``ryu-manager testbed/ffr_osken_app.py``.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=6653)
    ap.add_argument("--topo", default=os.environ.get("FFR_TOPO", "/tmp/ffr_topo.json"))
    args = ap.parse_args()
    os.environ["FFR_TOPO"] = args.topo

    from os_ken import cfg
    from os_ken.base import app_manager

    cfg.CONF(args=[], project="os_ken")
    cfg.CONF.set_override("ofp_tcp_listen_port", args.port)
    print(f"FA-FRR controller listening on tcp/{args.port}, topology {args.topo}")
    app_manager.AppManager.run_apps(["os_ken.controller.ofp_handler",
                                     os.path.join(HERE, "ffr_osken_app.py")])


if __name__ == "__main__":
    main()
