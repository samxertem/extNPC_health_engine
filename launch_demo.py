#!/usr/bin/env python3
"""
One command for the demo: the dashboard and Unity, started together.

    python launch_demo.py                 # dashboard + browser + Unity
    python launch_demo.py --no-unity      # dashboard only
    python launch_demo.py --no-dashboard  # Unity only
    python launch_demo.py --port 8060

WHY PYTHON AND NOT THE .ps1 THIS REPLACES. Every other entry point here is
`python <something>.py` -- run_dashboard, export_for_unity, install_to_unity,
run_unity_tests -- so a PowerShell script in that set is a trap rather than a
convenience: the habitual `python launch_demo.ps1` gets a SyntaxError on the
comment block, which is exactly what happened the first time it was used.

WHAT THIS DELIBERATELY DOES NOT DO. It does not export a world, bake bodies,
install a bundle, or set the scene's worldName. Those stay separate, explicit
steps (the dashboard's Controls tab -> Export for Unity, then
Tools > extNPC > Install Latest Export inside Unity). Folding them in would
mean starting the demo silently installs and plays whatever the last export
happened to be, which is the wrong default for a working session.
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

REPO = Path(__file__).resolve().parent

# The project the owner actually opens, overridable so this does not assume
# one machine's layout. Same variable install_to_unity.py reads.
DEFAULT_UNITY_PROJECT = Path(
    os.environ.get("EXTNPC_UNITY_PROJECT",
                   str(Path.home() / "extNPC_healthEngine")))

HUB_EDITORS = Path(r"C:\Program Files\Unity\Hub\Editor")


def find_unity() -> Path | None:
    """The 6000.x editor this package targets, or None.

    `package.json`'s `unity` floor is the two-component "6000.0", so any
    6000.x will open the project; the newest installed one is preferred
    rather than a version pinned here, which would go stale on the next Hub
    update and report "Unity not found" on a machine that has it.
    """
    override = os.environ.get("EXTNPC_UNITY_EXE")
    if override:
        exe = Path(override)
        return exe if exe.is_file() else None

    if not HUB_EDITORS.is_dir():
        return None
    candidates = sorted(
        (d for d in HUB_EDITORS.iterdir() if d.name.startswith("6000.")),
        key=lambda d: d.name, reverse=True)
    for directory in candidates:
        exe = directory / "Editor" / "Unity.exe"
        if exe.is_file():
            return exe
    return None


def port_is_open(host: str, port: int, timeout: float = 0.5) -> bool:
    with socket.socket() as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except OSError:
            return False


def wait_for_port(host: str, port: int, deadline_s: float = 30.0) -> bool:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if port_is_open(host, port):
            return True
        time.sleep(0.4)
    return False


def unity_already_open(project: Path) -> bool:
    """Unity writes this while a project is open and removes it on exit.

    A second editor on the same project is refused by Unity itself, but it
    is refused with a modal dialog, which in the middle of a demo is worse
    than not launching one.
    """
    return (project / "Temp" / "UnityLockfile").is_file()


def start_dashboard(host: str, port: int) -> subprocess.Popen | None:
    # ITS OWN WINDOW, on purpose: the dashboard logs every callback, and
    # interleaving that with this script's output makes both unreadable.
    # A separate console also means closing the demo is closing a window.
    kwargs = {}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_CONSOLE
    return subprocess.Popen(
        [sys.executable, "run_dashboard.py", "--host", host, "--port", str(port)],
        cwd=str(REPO), **kwargs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8050)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--no-dashboard", action="store_true",
                    help="start Unity only")
    ap.add_argument("--no-unity", action="store_true",
                    help="start the dashboard only")
    ap.add_argument("--project", type=Path, default=DEFAULT_UNITY_PROJECT,
                    help="the Unity project to open")
    args = ap.parse_args()

    url = f"http://{args.host}:{args.port}"

    # ---- the dashboard -------------------------------------------------
    if not args.no_dashboard:
        if port_is_open(args.host, args.port):
            # A STALE SERVER IS THE KNOWN TRAP ON THIS MACHINE, not a
            # hypothetical: a dashboard left running from an earlier session
            # keeps serving the OLD code, so edits appear not to apply.
            # Starting a second one on a taken port would fail anyway; say
            # which situation this is instead.
            print(f"  something is ALREADY serving {url}.")
            print( "  If that is an old dashboard, it is serving old code. Kill it with:")
            print( "    Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" |")
            print( "      Where-Object { $_.CommandLine -like '*run_dashboard*' } |")
            print( "      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
            print( "  Not starting another one.")
        else:
            print(f"  starting the dashboard in its own window -> {url}")
            start_dashboard(args.host, args.port)
            if wait_for_port(args.host, args.port):
                webbrowser.open(url)
            else:
                print("  the dashboard did not come up within 30 s; check its window.")

    # ---- Unity ---------------------------------------------------------
    if not args.no_unity:
        project = args.project
        if not (project / "Assets").is_dir():
            print(f"  no Unity project at {project}")
            print( "  set EXTNPC_UNITY_PROJECT, pass --project, or use --no-unity.")
        elif unity_already_open(project):
            print(f"  Unity already has {project.name} open; leaving it alone.")
        else:
            exe = find_unity()
            if exe is None:
                print("  no Unity 6000.x found under the Hub's editor folder.")
                print("  open the project by hand, or set EXTNPC_UNITY_EXE.")
            else:
                print(f"  opening Unity ({exe.parent.parent.name}) on {project} ...")
                subprocess.Popen([str(exe), "-projectPath", str(project)])

    print()
    print("  " + "-" * 62)
    print(f"  Dashboard : {url}")
    print( "  Unity     : Tools > extNPC > Install Latest Export, then press Play.")
    print( "              (No export yet? Dashboard Controls tab -> Export for Unity.)")
    print("  " + "-" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
