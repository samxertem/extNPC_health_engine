"""
Entry point for the extNPC live population dashboard.

    python run_dashboard.py            # -> http://127.0.0.1:8050
    python run_dashboard.py --port 8060

Requires: dash, plotly, networkx (plus the engine's numpy/scipy).
Install:  python -m pip install dash plotly networkx
"""

from __future__ import annotations

import argparse

from dashboard.app import app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    print(f"\n  extNPC Living Population  ->  http://{args.host}:{args.port}\n"
          f"  Press Play, then click any dot to inspect that individual.\n")
    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
