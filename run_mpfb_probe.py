#!/usr/bin/env python3
"""Measure MPFB2 end to end, Blender to Unity, without opening either GUI.

WHY THIS EXISTS. Phase B (`reads/UNITY_PLAN.md` Stage 6) needs the engine's
`height_cm` to become a real stature on a real mesh in Unity, and its
acceptance criterion is "a 1.75 m character measures 1.75 m in Unity". Every
number that criterion depends on belongs to a third-party Blender add-on, so
none of them can be read off documentation; they have to be measured, and
re-measured when MPFB is upgraded. Session 22 measured them interactively over
an MCP connection to a running Blender, which answered the questions but left
nothing anyone could re-run. This script is the re-runnable version.

    python run_mpfb_probe.py                 # Blender half, then Unity half
    python run_mpfb_probe.py --install-mpfb  # download and install MPFB first
    python run_mpfb_probe.py --skip-unity    # calibration only
    python run_mpfb_probe.py --blender "C:/.../blender.exe"

It runs `mpfb/blender_probe.py` inside Blender, then imports the FBX files
that produced into the throwaway Unity project `run_unity_tests.py` already
knows how to generate, and compares the two sides.

Exit code is 0 only if all three pipeline rules still hold:

  1. the baked FBX measures in Unity what it measured in Blender,
  2. the un-baked one does NOT (Unity zeroes blendshape weights, so the
     character arrives as the neutral base mesh, a plausible 1.67 m human),
  3. the un-rigged one does NOT (it loses the unit round-trip and the
     Z-up -> Y-up conversion, arriving 100x small and lying down).

Rules 2 and 3 are asserted as FAILURES ON PURPOSE. If MPFB or Blender ever
starts handling either case correctly, this script should say so loudly rather
than keep warning about a trap that no longer exists.

WHAT THIS DOES NOT CHECK. Nothing here opens a window. Whether the character
looks like a person, whether the skin material survived, and whether a family
of them looks like a family are still human questions; the last of those
is Stage 2's deliverable in `reads/MPFB_UNITY_INVESTIGATION.md`, deliberately
gated behind this one.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO))

PROBE = REPO / "mpfb" / "blender_probe.py"
OUT_DIR = REPO / "outputs" / "mpfb"

# MPFB's minimum is Blender 4.2 (blender_manifest.toml). Below that the
# extension will not even install, so there is no point searching for one.
MIN_BLENDER = (4, 2)
MPFB_TAG = "v2.0.17"
MPFB_SOURCE = f"https://codeload.github.com/makehumancommunity/mpfb2/zip/refs/tags/{MPFB_TAG}"


# ---------------------------------------------------------------------
# finding Blender
# ---------------------------------------------------------------------

def _blender_roots() -> list[Path]:
    if platform.system() == "Windows":
        return [Path(r"C:\Program Files\Blender Foundation"),
                Path(os.environ.get("PROGRAMFILES", "")) / "Blender Foundation"]
    if platform.system() == "Darwin":
        return [Path("/Applications")]
    return [Path("/usr/share"), Path("/opt"), Path.home() / ".local" / "share"]


def _blender_exe(directory: Path) -> Path | None:
    for rel in ("blender.exe", "Blender.app/Contents/MacOS/Blender", "blender"):
        candidate = directory / rel
        if candidate.is_file():
            return candidate
    return None


def find_blender() -> Path:
    """The newest installed Blender at or above MPFB's 4.2 floor."""
    if os.environ.get("BLENDER"):
        return Path(os.environ["BLENDER"])
    found: list[tuple[tuple[int, ...], Path]] = []
    for root in _blender_roots():
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            exe = _blender_exe(child)
            if exe is None:
                continue
            match = re.search(r"(\d+)\.(\d+)", child.name)
            version = tuple(int(g) for g in match.groups()) if match else (0, 0)
            found.append((version, exe))
    usable = [(v, p) for v, p in found if v >= MIN_BLENDER]
    if not usable:
        installed = ", ".join(p.parent.name for _, p in found) or "none"
        raise SystemExit(
            f"no installed Blender at or above {MIN_BLENDER[0]}.{MIN_BLENDER[1]} "
            f"(MPFB's floor).\n  installed: {installed}\n"
            f"  install one, set $BLENDER, or pass --blender.")
    return max(usable)[1]


def _run_blender(exe: Path, args: list[str], timeout: int = 1800) -> tuple[int, str]:
    # `--factory-startup` is deliberately NOT passed: it would skip the user
    # preferences, and with them the enabled MPFB extension that is the whole
    # subject of the measurement.
    cmd = [str(exe), "-b", *args]
    print("  $ " + " ".join(cmd))
    start = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout)
    print(f"  blender exited {proc.returncode} in {time.perf_counter() - start:.0f}s")
    return proc.returncode, proc.stdout + proc.stderr


# ---------------------------------------------------------------------
# installing MPFB
# ---------------------------------------------------------------------

def install_mpfb(exe: Path, work: Path) -> None:
    """Repack MPFB's source tree as an extension zip and install it.

    The GitHub source archive is NOT installable as-is. MPFB 2.0.17 ships a
    `blender_manifest.toml`, which makes it a Blender 4.2+ *extension*, and an
    extension zip must carry that manifest at its ROOT. In the source archive
    it sits four levels down at `mpfb2-<tag>/src/mpfb/`, and the release page
    attaches no built asset, so the zip has to be constructed here.
    """
    work.mkdir(parents=True, exist_ok=True)
    source_zip = work / f"mpfb2-{MPFB_TAG}-src.zip"
    if not source_zip.exists():
        print(f"  downloading {MPFB_SOURCE}")
        urllib.request.urlretrieve(MPFB_SOURCE, source_zip)  # noqa: S310
    print(f"  source archive {source_zip.stat().st_size / 1e6:.0f} MB")

    extension_zip = work / f"mpfb-{MPFB_TAG}-extension.zip"
    with zipfile.ZipFile(source_zip) as src:
        prefix = next(n for n in src.namelist() if n.endswith("/src/mpfb/blender_manifest.toml"))
        prefix = prefix[: -len("blender_manifest.toml")]
        with zipfile.ZipFile(extension_zip, "w", zipfile.ZIP_DEFLATED) as out:
            written = 0
            for info in src.infolist():
                if info.is_dir() or not info.filename.startswith(prefix):
                    continue
                out.writestr(info.filename[len(prefix):], src.read(info))
                written += 1
    print(f"  repacked {written} files -> {extension_zip.name}")

    expr = (
        "import bpy;"
        f"bpy.ops.extensions.package_install_files(filepath=r'{extension_zip}',"
        "repo='user_default', enable_on_install=True)"
    )
    code, output = _run_blender(exe, ["--python-expr", expr])
    if code != 0:
        print(output[-4000:])
        raise SystemExit("MPFB install failed")
    print("  MPFB installed and enabled")


# ---------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------

def _height(entry: dict) -> float | None:
    span = entry.get("vertex_span")
    return span[1] if span else None


def verdicts(probe: dict, unity: dict) -> list[tuple[bool, str]]:
    """The three pipeline rules, each phrased so it can fail."""
    authored = probe["export_stature_m"]
    out: list[tuple[bool, str]] = []

    baked = _height(unity.get("mpfb_baked.fbx", {}))
    if baked is None:
        out.append((False, "baked FBX: Unity reported no vertices"))
    else:
        error_mm = abs(baked - authored) * 1000
        out.append((error_mm < 0.01,
                    f"baked FBX measures {baked:.6f} m in Unity against "
                    f"{authored:.6f} m authored in Blender "
                    f"({error_mm:.4f} mm error, tolerance 0.01 mm)"))

    rigged = _height(unity.get("mpfb_gamerig.fbx", {}))
    if rigged is None:
        out.append((False, "un-baked FBX: Unity reported no vertices"))
    else:
        differs = abs(rigged - authored) * 1000 > 1.0
        out.append((differs,
                    f"un-baked FBX measures {rigged:.6f} m, the neutral base "
                    f"mesh, because Unity imports blendshape weights at zero. "
                    f"{'Still true' if differs else 'NO LONGER TRUE: MPFB or Unity changed, update the docs'}"))

    norig = _height(unity.get("mpfb_norig.fbx", {}))
    if norig is None:
        out.append((False, "un-rigged FBX: Unity reported no vertices"))
    else:
        shrunk = norig < authored / 10
        out.append((shrunk,
                    f"un-rigged FBX measures {norig:.6f} m, 100x small and "
                    f"Z-up preserved, so the armature is what carries the unit "
                    f"and axis conversion. "
                    f"{'Still true' if shrunk else 'NO LONGER TRUE: update the docs'}"))
    return out


# ---------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--blender", type=Path, default=None)
    parser.add_argument("--install-mpfb", action="store_true",
                        help="download MPFB, repack it as an extension, install it")
    parser.add_argument("--skip-unity", action="store_true",
                        help="Blender half only")
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--export-macro", type=float, default=0.5151)
    args = parser.parse_args()

    exe = args.blender or find_blender()
    print(f"  blender  {exe}")
    if args.install_mpfb:
        install_mpfb(exe, args.out / "_install")

    args.out.mkdir(parents=True, exist_ok=True)
    code, output = _run_blender(exe, ["-P", str(PROBE), "--",
                                      "--out", str(args.out),
                                      "--export-macro", str(args.export_macro)])
    probe_json = args.out / "mpfb_probe.json"
    if code != 0 or not probe_json.exists():
        print(output[-6000:])
        return 1
    probe = json.loads(probe_json.read_text(encoding="utf-8"))

    print(f"\n  MPFB {probe['mpfb']} on Blender {probe['blender']}, "
          f"{probe['unit_system']} at scale_length={probe['scale_length']}")
    path_ind = probe["path_independence"]
    print(f"  same macro vector, {len(path_ind['histories'])} different histories: "
          f"{path_ind['distinct_statures']} distinct statures over "
          f"{path_ind['distinct_key_orders']} distinct key-block orders, "
          f"spread {path_ind['spread_mm'] * 1000:.4f} um "
          f"({'bit-identical' if path_ind['bit_identical'] else 'NOT bit-identical'})")
    for label, band in probe["dead_band"].items():
        print(f"  dead band {label:14} [{band['low']:.3f}, {band['high']:.3f}] "
              f"width {band['width']:.4f}, unreachable step {band['step_mm']:.2f} mm")
    print(f"  authored stature {probe['export_stature_m']:.6f} m "
          f"at height macro {probe['export_macro']}")

    if args.skip_unity:
        print("\n  --skip-unity, stopping before the Unity half")
        return 0

    import run_unity_tests as rut
    from mpfb import unity_measure

    manifest = json.loads((rut.PACKAGE / "package.json").read_text(encoding="utf-8"))
    editor = rut.find_editor(manifest.get("unity", "6000.0"))
    print(f"\n  editor   {editor}")
    project = rut.DEFAULT_PROJECT
    log_dir = project.parent / (project.name + "-logs")
    unity = unity_measure.measure(args.out, project, log_dir, editor)
    unity_measure.write_json(unity, args.out / "unity_measure.json")

    print("\n=== the three pipeline rules ===")
    failed = 0
    for ok, message in verdicts(probe, unity):
        print(f"  [{'PASS' if ok else 'FAIL'}] {message}")
        failed += not ok
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
