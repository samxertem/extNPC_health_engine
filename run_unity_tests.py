#!/usr/bin/env python3
"""
Compile and test the Unity package WITHOUT opening the Unity editor.
=====================================================================

WHY THIS EXISTS. Every C# file in `unity/com.samal.extnpc` was written, tested
against pytest source rules, and shipped *without ever going through a
compiler*. Sessions 18 and 19 both ended with the same line in the report --
"NOT VERIFIED IN-EDITOR" -- because verifying it meant a human opening Unity,
clicking through the Test Runner and reading a bar. Session 18's four
in-editor defects were all invisible to the pytest suite, which is exactly the
gap a source-level rule cannot close: pytest can prove that a file *says*
`CsvParse.Double`, never that the assembly *builds*.

Unity can do both from the command line. This script:

  1. finds an installed editor matching the package's `unity` field,
  2. generates a throwaway project that CONSUMES the package (the repo has
     always declined to track one -- see .gitignore -- so it is regenerable
     output, and this script is the thing that regenerates it),
  3. runs the EditMode tests in batch mode,
  4. and reports the two failure modes separately, because they mean
     different things: a COMPILE error means the package does not build at
     all, while a TEST failure means it builds and disagrees with the
     dashboard.

    python run_unity_tests.py              # generate if needed, then run
    python run_unity_tests.py --clean      # discard the project first
    python run_unity_tests.py --editor "C:/.../Unity.exe"

Exit code is 0 only if the assemblies compiled AND every test passed AND at
least one test actually ran. That last clause is not paranoia. A Unity package
whose tests are not listed in the consuming project's `testables` reports

    <test-run testcasecount="0" ... result="Passed">

-- zero tests, green, and indistinguishable at a glance from a suite that ran.
This script refuses to call that a pass.

WHAT THIS DOES NOT CHECK. Nothing here opens a window. Frame rate, glyph
rendering (does `●` tofu in the built-in font?), and whether the scene looks
right remain human questions. It answers "does it build and do the formatters
still agree with Python", which is the part a machine can own.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET  # noqa: S314 -- see below
from pathlib import Path

# On xml.etree: the only document this script parses is the results file the
# local Unity editor just wrote, seconds earlier, into a path this script
# chose. It is not attacker-reachable, so `defusedxml` would add a pinned
# dependency to requirements.txt for no threat. If this ever parses a bundle
# or anything off the network, that changes.

REPO = Path(__file__).resolve().parent
PACKAGE = REPO / "unity" / "com.samal.extnpc"
# NOT a dotted name. Unity refuses to create a project whose folder begins
# with "." -- "`.test-project` is not a valid directory name" -- so the
# gitignore does the hiding instead.
DEFAULT_PROJECT = REPO / "unity" / "test-project"
PACKAGE_NAME = "com.samal.extnpc"


# ---------------------------------------------------------------------
# finding an editor
# ---------------------------------------------------------------------

def _hub_roots() -> list[Path]:
    """Where Unity Hub keeps editors, per platform."""
    system = platform.system()
    if system == "Windows":
        return [Path(r"C:\Program Files\Unity\Hub\Editor"),
                Path(os.environ.get("LOCALAPPDATA", "")) / "Unity" / "Hub" / "Editor"]
    if system == "Darwin":
        return [Path("/Applications/Unity/Hub/Editor")]
    return [Path.home() / "Unity" / "Hub" / "Editor"]


def _executable(editor_dir: Path) -> Path | None:
    for rel in ("Editor/Unity.exe", "Unity.app/Contents/MacOS/Unity", "Editor/Unity"):
        candidate = editor_dir / rel
        if candidate.exists():
            return candidate
    return None


def _version_tuple(name: str) -> tuple[int, int, int]:
    """`6000.1.6f1` -> (6000, 1, 6), and `6000.0` -> (6000, 0, 0).

    Both shapes have to work, and they come from different places: an install
    directory is a full version, while package.json's `unity` field is a
    two-component MINIMUM ("6000.0"). Requiring three components here parsed
    that floor as (0,) and reported "no editor matches major 0" while listing
    the matching editor on the next line.
    """
    m = re.match(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?", name.strip())
    if not m:
        return (0, 0, 0)
    return tuple(int(g) if g else 0 for g in m.groups())  # type: ignore[return-value]


def find_editor(required: str) -> Path:
    """The newest installed editor whose MAJOR matches package.json's `unity`.

    Major only. `unity: "6000.0"` is a floor, not a pin -- Unity's own
    compatibility rule -- so 6000.1.6f1 satisfies it while 2022.3.62f2 does
    not, and silently testing on the 2022 editor would prove something about a
    runtime the package does not claim to support.
    """
    want_major = _version_tuple(required)[0]
    found: list[tuple[tuple[int, ...], Path]] = []
    for root in _hub_roots():
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            exe = _executable(child) if child.is_dir() else None
            if exe is not None:
                found.append((_version_tuple(child.name), exe))

    matching = [(v, p) for v, p in found if v[0] == want_major]
    if not matching:
        installed = ", ".join(p.parent.parent.name for _, p in found) or "none"
        raise SystemExit(
            f"no installed Unity editor matches package.json's unity "
            f"\"{required}\" (major {want_major}).\n"
            f"  installed: {installed}\n"
            f"  install one via Unity Hub, or pass --editor explicitly.")
    return max(matching)[1]


# ---------------------------------------------------------------------
# the throwaway consuming project
# ---------------------------------------------------------------------

def _run_editor(exe: Path, args: list[str], log: Path, timeout: int) -> int:
    log.parent.mkdir(parents=True, exist_ok=True)
    if log.exists():
        log.unlink()
    cmd = [str(exe), "-batchmode", "-nographics", "-accept-apiupdate",
           "-logFile", str(log), *args]
    print("  $ " + " ".join(cmd))
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(cmd, timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"  editor timed out after {timeout}s -- see {log}")
        return 124
    print(f"  editor exited {proc.returncode} in {time.perf_counter() - t0:.0f}s")
    return proc.returncode


def ensure_project(exe: Path, project: Path, log_dir: Path) -> None:
    """A default project made BY this editor, then patched to consume us.

    The manifest is not written from scratch on purpose. Pinning
    com.unity.test-framework to a version string guessed here would fail
    resolution on any editor shipping a different one, and the failure would
    look like a package problem rather than a script problem. Letting the
    editor generate its own default manifest means every version in it is one
    that editor actually has.
    """
    if not (project / "ProjectSettings" / "ProjectVersion.txt").exists():
        print(f"  creating a consuming project at {project}")
        project.parent.mkdir(parents=True, exist_ok=True)
        code = _run_editor(exe, ["-quit", "-createProject", str(project)],
                           log_dir / "create.log", timeout=1800)
        if code != 0 or not (project / "Packages" / "manifest.json").exists():
            _print_log_errors(log_dir / "create.log")
            raise SystemExit(f"could not create a Unity project (exit {code})")
    else:
        print(f"  reusing the project at {project}")

    manifest_path = project / "Packages" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    deps = manifest.setdefault("dependencies", {})

    # `file:` paths in a manifest are relative to the Packages folder, and
    # must use forward slashes on every platform.
    rel = os.path.relpath(PACKAGE, manifest_path.parent).replace("\\", "/")
    deps[PACKAGE_NAME] = f"file:{rel}"

    if not any(k.startswith("com.unity.test-framework") for k in deps):
        # Only if the editor's own default project somehow lacks it.
        deps["com.unity.test-framework"] = "1.4.5"

    # THE LINE THE README WARNS ABOUT. Tests inside a package are invisible to
    # the Test Runner unless the consuming project names the package here, and
    # the symptom is a green bar over zero tests.
    testables = manifest.setdefault("testables", [])
    if PACKAGE_NAME not in testables:
        testables.append(PACKAGE_NAME)

    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8")
    print(f"  manifest patched: {PACKAGE_NAME} -> file:{rel}, testables OK")


# ---------------------------------------------------------------------
# reading what came back
# ---------------------------------------------------------------------

_CS_ERROR = re.compile(r"^.*?\berror CS\d+\b.*$", re.M)
_LICENSE_TROUBLE = re.compile(
    r"(No valid Unity Editor license|License is not (?:active|valid)|"
    r"Failed to (?:activate|resolve) license|LICENSE SYSTEM \[.*?\] Error)", re.I)


def _print_log_errors(log: Path, limit: int = 40) -> bool:
    """Compile errors out of the editor log. True if any were printed."""
    if not log.exists():
        print(f"  (no log at {log})")
        return False
    text = log.read_text(encoding="utf-8", errors="replace")

    if _LICENSE_TROUBLE.search(text):
        print("\n  LICENSE: this editor could not acquire a licence in batch "
              "mode.\n  Open Unity Hub once and sign in, then re-run. The "
              "matching log lines:")
        for line in text.splitlines():
            if _LICENSE_TROUBLE.search(line):
                print(f"    {line.strip()}")

    seen: list[str] = []
    for match in _CS_ERROR.findall(text):
        line = match.strip()
        if line not in seen:
            seen.append(line)
    if seen:
        print(f"\n  COMPILE ERRORS ({len(seen)} distinct):")
        for line in seen[:limit]:
            print(f"    {line}")
        if len(seen) > limit:
            print(f"    ... and {len(seen) - limit} more, see {log}")
    return bool(seen)


def report(results: Path, log: Path) -> int:
    """NUnit3 XML -> a summary a human can act on. Returns an exit code."""
    if not results.exists():
        print("\n  NO RESULTS FILE. The tests did not run; the assemblies "
              "almost certainly did not compile.")
        _print_log_errors(log)
        return 1

    root = ET.parse(results).getroot()
    total = int(root.get("testcasecount", 0))
    passed = int(root.get("passed", 0))
    failed = int(root.get("failed", 0))
    skipped = int(root.get("skipped", 0))
    inconclusive = int(root.get("inconclusive", 0))
    duration = root.get("duration", "?")

    print(f"\n  {total} tests | {passed} passed | {failed} failed | "
          f"{skipped} skipped | {inconclusive} inconclusive | {duration}s")

    if failed:
        print("\n  FAILURES:")
        for case in root.iter("test-case"):
            if case.get("result") != "Failed":
                continue
            print(f"\n    {case.get('fullname')}")
            message = case.findtext("failure/message") or ""
            for line in message.strip().splitlines():
                print(f"      {line}")
            stack = (case.findtext("failure/stack-trace") or "").strip()
            if stack:
                print(f"      at {stack.splitlines()[0].strip()}")

    if total == 0:
        print("\n  ZERO TESTS RAN, which this script treats as a FAILURE.\n"
              "  A package's tests are invisible to the Test Runner unless the\n"
              "  consuming project lists it in `testables` -- and the symptom is\n"
              "  a green bar over an empty suite. Check that the assemblies\n"
              "  compiled at all:")
        _print_log_errors(log)
        return 1

    return 1 if failed else 0


# ---------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--editor", type=Path, default=None,
                    help="path to Unity.exe; default = newest matching install")
    ap.add_argument("--project", type=Path, default=DEFAULT_PROJECT,
                    help=f"throwaway consuming project (default {DEFAULT_PROJECT})")
    ap.add_argument("--platform", default="EditMode",
                    choices=["EditMode", "PlayMode"],
                    help="test platform (default EditMode)")
    ap.add_argument("--filter", default=None,
                    help="NUnit test filter, e.g. ExtNPC.Tests.WorldClockTests")
    ap.add_argument("--clean", action="store_true",
                    help="delete the generated project first (forces a "
                         "full reimport; the honest way to reproduce a "
                         "from-nothing result)")
    ap.add_argument("--timeout", type=int, default=3600,
                    help="seconds to allow the editor (default 3600)")
    args = ap.parse_args()

    manifest = json.loads((PACKAGE / "package.json").read_text(encoding="utf-8"))
    required = manifest.get("unity", "6000.0")

    exe = args.editor or find_editor(required)
    print(f"  package  {PACKAGE.name} {manifest.get('version')} "
          f"(needs Unity {required})")
    print(f"  editor   {exe}")

    project = args.project.resolve()
    if args.clean and project.exists():
        print(f"  removing {project}")
        shutil.rmtree(project)

    log_dir = project.parent / (project.name + "-logs")
    ensure_project(exe, project, log_dir)

    results = log_dir / "results.xml"
    if results.exists():
        results.unlink()
    run_log = log_dir / "tests.log"

    test_args = ["-runTests", "-projectPath", str(project),
                 "-testPlatform", args.platform,
                 "-testResults", str(results)]
    if args.filter:
        test_args += ["-testFilter", args.filter]

    # -runTests quits by itself; passing -quit as well truncates the run.
    _run_editor(exe, test_args, run_log, timeout=args.timeout)

    code = report(results, run_log)
    print(f"\n  logs: {run_log}\n  xml:  {results}")
    return code


if __name__ == "__main__":
    sys.exit(main())
