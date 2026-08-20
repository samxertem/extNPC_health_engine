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

    python run_mpfb_probe.py --export-bodies              # bake the two bodies
    python run_mpfb_probe.py --install-bodies <project>   # verify, then install
    python run_mpfb_probe.py --check-portrait             # render the face
    python run_mpfb_probe.py --shoot-village <bundle>     # the A/B pictures
    python run_mpfb_probe.py --perf                       # the 600-at-60 budget

The last three need a graphics device and so run WITHOUT `-nographics`,
unlike everything else here.

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
import shutil
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
# the inspector's portrait
# ---------------------------------------------------------------------

def portrait(args) -> int:
    """Render the inspector's moving head and check what came out.

    WHY THIS IS NOT AN EditMode TEST. `run_unity_tests.py` runs the editor
    under `-nographics`, which has no device and cannot render to a texture.
    PortraitPoseTests pins all the arithmetic, but arithmetic cannot tell you
    that the camera is aimed at a head rather than at a shoulder or at nothing.
    This renders four pictures and asserts on their pixels.

    Four questions, one picture each:
      * is there a face at all, or is the frame empty backdrop,
      * does it MOVE between two times,
      * do two villagers move DIFFERENTLY at the same time,
      * is the backdrop the lineage colour it was given.
    """
    import run_unity_tests as rut
    from mpfb import unity_measure

    manifest = json.loads((rut.PACKAGE / "package.json").read_text(encoding="utf-8"))
    editor = rut.find_editor(manifest.get("unity", "6000.0"))
    project = rut.DEFAULT_PROJECT
    log_dir = project.parent / (project.name + "-logs")
    png_dir = (args.out / "portraits").resolve()

    shots = unity_measure.check_portrait(project, log_dir, editor, png_dir)
    unity_measure.write_json(shots, args.out / "unity_portrait.json")

    device = shots.pop("device", {})
    print(f"\n  device {device.get('graphicsDeviceType')}, "
          f"body installed {device.get('bodyInstalled')}")
    if str(device.get("bodyInstalled", "")).lower() != "true":
        print("  no body pack installed; the portrait cannot draw a face. "
              "Run --export-bodies first.")
        return 1

    failed = 0
    for tag, shot in sorted(shots.items()):
        fraction = shot.get("subject_fraction", 0.0)
        # A head and shoulders at this framing covers roughly a third of the
        # frame. Far below means the camera is looking past the body; far above
        # means it is inside it.
        ok = 0.15 <= fraction <= 0.72
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {tag}: subject fills "
              f"{fraction:.1%} of frame, backdrop rgb "
              f"{shot.get('backdrop_rgb')}, mean luma {shot.get('mean_luma')}")

    def box(tag):
        return shots.get(tag, {}).get("subject_box")

    moved = box("Selin-24_t0.0") != box("Selin-24_t3.7")
    print(f"  [{'PASS' if moved else 'FAIL'}] the head moves between t=0.0 and "
          f"t=3.7 ({box('Selin-24_t0.0')} -> {box('Selin-24_t3.7')})")
    failed += not moved

    apart = box("Selin-24_t3.7") != box("Tomas-28_t3.7")
    print(f"  [{'PASS' if apart else 'FAIL'}] two villagers are at different "
          f"points in the sway at the same instant")
    failed += not apart

    warm = shots.get("Selin-24_t0.0", {}).get("backdrop_rgb") or [0, 0, 0]
    cool = shots.get("Tomas-28_t0.0", {}).get("backdrop_rgb") or [0, 0, 0]
    tinted = warm[0] > warm[2] and cool[2] > cool[0]
    print(f"  [{'PASS' if tinted else 'FAIL'}] the backdrop carries the lineage "
          f"colour (warm {warm} vs cool {cool})")
    failed += not tinted

    print(f"\n  pictures in {png_dir}")
    return 1 if failed else 0


def _editor_and_project():
    """The throwaway consuming project and an editor that matches the package."""
    import run_unity_tests as rut

    manifest = json.loads((rut.PACKAGE / "package.json").read_text(encoding="utf-8"))
    editor = rut.find_editor(manifest.get("unity", "6000.0"))
    project = rut.DEFAULT_PROJECT
    return editor, project, project.parent / (project.name + "-logs")


def install_assets(exe: Path, args) -> int:
    """Item A2. Download the CC0 pack, unpack it where MPFB looks, catalogue it.

    The catalogue at the end is not a flourish. `.mhm` bodypart lines carry a
    name AND a uuid, and MPFB's fallback when it cannot match both fits some
    other asset instead of failing, so nothing in this project may hardcode an
    asset name. The catalogue is what the writer is allowed to choose from.
    """
    from mpfb import asset_pack

    cache = (args.out / "assetpack").resolve()
    print(f"  cache {cache}")
    zip_path = asset_pack.download(cache)

    data_dir = _mpfb_data_dir(exe)
    if data_dir is None:
        print("  could not ask Blender where MPFB keeps its data.")
        return 1
    print(f"  unpacking into {data_dir}")
    families = asset_pack.extract(zip_path, Path(data_dir))
    if not families:
        print("  nothing was unpacked; the archive layout may have changed.")
        return 1
    for name, count in sorted(families.items()):
        print(f"    {name:14s} {count:5d} files")

    return list_assets(exe, args)


def _mpfb_data_dir(exe: Path):
    """Ask the installed Blender where MPFB's data directory is.

    Asked rather than constructed: it depends on the Blender version, on the
    extension id, and on an MPFB preference that can override it, so a path
    built here would be right on this machine and wrong on the next one.
    """
    expr = (
        "import bpy,sys\n"
        "try: bpy.ops.preferences.addon_enable(module='bl_ext.user_default.mpfb')\n"
        "except Exception: pass\n"
        "for n in list(sys.modules):\n"
        "    if n.endswith('mpfb.services.locationservice'):\n"
        "        print('[DATA]', sys.modules[n].LocationService.get_user_data())\n"
        "        break\n")
    code, output = _run_blender(exe, ["--python-expr", expr])
    for line in output.splitlines():
        if line.startswith("[DATA] "):
            return line[len("[DATA] "):].strip()
    return None


def list_assets(exe: Path, args) -> int:
    """Write the installed-asset catalogue, uuids included."""
    out = Path("health_engine") / "data" / "mpfb_assets.json"
    script = Path(__file__).parent / "mpfb" / "list_assets.py"
    code, output = _run_blender(exe, ["-P", str(script), "--", "--out", str(out)])
    for line in output.splitlines():
        if line.startswith("[ASSETS]"):
            print("  " + line)
    return code


def lineup(args) -> int:
    """Photograph the per-villager bodies side by side, front on.

    Separate from `village` because it answers a different question. The
    village camera shows that the world is populated; this one shows whether
    the people in it differ from each other, which is the whole of Stage 8.
    """
    from mpfb import unity_lineup

    bundle = args.shoot_lineup.resolve()
    if not (bundle / "bodies" / "bodies.json").exists():
        print(f"  {bundle} has no bodies/bodies.json. Make one with:\n"
              f"    python export_bodies.py --years 110 --bundle {bundle}\n"
              f"    blender -b -P mpfb/bake_bodies.py -- --bodies {bundle}/bodies")
        return 1

    editor, project, log_dir = _editor_and_project()
    png_dir = (args.out / "lineup").resolve()
    result = unity_lineup.shoot(project, log_dir, editor, bundle, png_dir)
    code = unity_lineup.report(result)
    print(f"\n  picture in {png_dir}")
    return code


def village(args) -> int:
    """Photograph a bundle with the bodies and without them.

    The A/B is the point. Two pictures of the same year from the same camera,
    differing only in whether a body asset existed, is what makes "villagers
    are people now" falsifiable rather than decorative.
    """
    from mpfb import unity_village

    bundle = args.shoot_village.resolve()
    if not (bundle / "manifest.json").exists():
        print(f"  {bundle} does not look like a bundle (no manifest.json). "
              f"Make one with: python export_for_unity.py")
        return 1

    editor, project, log_dir = _editor_and_project()
    png_dir = (args.out / "village").resolve()
    result = unity_village.both(project, log_dir, editor, bundle, png_dir)
    unity_village.write_json(result, args.out / "unity_village.json")

    failed = 0
    for arm in ("capsules", "bodies"):
        scene = result.get(arm, {}).get("scene", {})
        load = result.get(arm, {}).get("load", {})
        drawn = scene.get("bodies_in_scene", 0)
        ok = drawn > 0 and str(scene.get("headcount_ok", "")).lower() == "true"
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {arm}: {drawn:.0f} villagers, "
              f"headcount {scene.get('headcount_ok')}, tallest localScale.y "
              f"{scene.get('tallest_local_scale_y')}, body installed "
              f"{load.get('body_installed')}")

    cap = result.get("capsules", {}).get("scene", {}).get("tallest_local_scale_y")
    bod = result.get("bodies", {}).get("scene", {}).get("tallest_local_scale_y")
    # The A/B in one number. A primitive's origin is its centre so it scales by
    # half the stature; a baked body's origin is its soles so it scales by the
    # whole of it. Equal values mean the mesh never reached VillagerView.
    differ = cap is not None and bod is not None and abs(bod - 2 * cap) < 1e-3
    print(f"  [{'PASS' if differ else 'FAIL'}] the two arms differ as they "
          f"should: {cap} against {bod}, the same person under two "
          f"scaling conventions")
    failed += not differ

    print(f"\n  pictures in {png_dir}")
    return 1 if failed else 0


def perf(args) -> int:
    """Time capsules against bodies, against §4.3's 600-at-60 budget."""
    from mpfb import unity_perf

    editor, project, log_dir = _editor_and_project()
    result = unity_perf.both(project, log_dir, editor)
    unity_perf.write_json(result, args.out / "unity_perf.json")

    print(f"\n{'N':>6} {'capsule ms':>11} {'body ms':>9} {'ratio':>7} "
          f"{'body fps':>9}")
    budget_ok = None
    for count in (28, 100, 300, 600, 1000):
        cap = result.get("capsules", {}).get(f"n{count}", {}).get("ms_min")
        bod = result.get("bodies", {}).get(f"n{count}", {}).get("ms_min")
        if not cap or not bod:
            continue
        print(f"{count:>6} {cap:>11.3f} {bod:>9.3f} {bod / cap:>7.2f} "
              f"{1000 / bod:>9.1f}")
        if count == 600:
            budget_ok = (1000 / bod) >= 60.0

    if budget_ok is None:
        print("\n  no 600-villager sample; cannot judge the budget")
        return 1
    print(f"\n  [{'PASS' if budget_ok else 'FAIL'}] UNITY_PLAN.md section 4.3: "
          f"600 villagers at 60 fps")
    print("  Offscreen editor rendering, not a frame rate and not a build. "
          "About 1.2 ms of readback sits inside every number.")
    return 0 if budget_ok else 1


# ---------------------------------------------------------------------
# the two viewer bodies
# ---------------------------------------------------------------------

def bodies(exe: Path, args) -> int:
    """Export `human_female.fbx` / `human_male.fbx`, optionally installing them.

    These are what turns UNITY_PLAN.md Stage 6's last line, "replace capsules
    with one shared human mesh", from a plan into a village of people, and what
    gives the inspector a face to animate.

    NOT TRACKED, and that is the whole shape of the design. MPFB's code is
    GPLv3 and its output is CC0, so the FBX may ship anywhere but the generator
    may never live inside the Unity package. `HumanMesh` therefore treats their
    absence as a supported state: with no body installed every villager stays a
    capsule and the inspector says why.
    """
    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    wanted = [out / "human_female.fbx", out / "human_male.fbx"]

    if args.export_bodies or not all(p.exists() for p in wanted):
        code, output = _run_blender(exe, ["-P", str(PROBE), "--",
                                          "--out", str(out),
                                          "--mode", "bodies",
                                          "--ethnicity", args.ethnicity])
        if code != 0:
            print(output[-6000:])
            return 1
        for line in output.splitlines():
            if line.startswith("[BODY]"):
                print("  " + line)

    missing = [p for p in wanted if not p.exists()]
    if missing:
        print(f"  MISSING after export: {[p.name for p in missing]}")
        return 1

    # Verify in the throwaway project BEFORE touching anyone's real one.
    # HumanMesh.Bake has one job, folding the FBX's centimetre Z-up transform
    # into the vertices, and the EditMode suite can only test that job on
    # synthetic boxes. This is the only place it meets a real MPFB export.
    import run_unity_tests as rut
    from mpfb import unity_measure

    manifest = json.loads((rut.PACKAGE / "package.json").read_text(encoding="utf-8"))
    editor = rut.find_editor(manifest.get("unity", "6000.0"))
    project = rut.DEFAULT_PROJECT
    log_dir = project.parent / (project.name + "-logs")
    print(f"\n  verifying in {project.name}")
    checked = unity_measure.check_bodies(out, project, log_dir, editor)
    unity_measure.write_json(checked, out / "unity_bodies.json")

    failed = 0
    for label, got in sorted(checked.items()):
        # C# writes a lowercase bool literal; comparing against Python's "True"
        # made a working pipeline report FAIL twice before this was noticed.
        if str(got.get("installed", "")).lower() != "true":
            print(f"  [FAIL] {label}: not installed")
            failed += 1
            continue
        height = got.get("unit_height", 0.0)
        floor = got.get("unit_min_y", 1.0)
        rendered = got.get("rendered_at_1p754592", 0.0)
        ok = (abs(height - 1.0) < 1e-4 and abs(floor) < 1e-4
              and abs(rendered - 1.754592) < 1e-4)
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}: authored "
              f"{got.get('authored_stature_m'):.6f} m, normalised to "
              f"{height:.6f} tall standing on {floor:+.6f}, "
              f"renders {rendered:.6f} m when scaled to 1.754592")
    if failed:
        print("\n  the body pipeline is broken; not installing anywhere else.")
        return 1

    if args.install_bodies is None:
        print(f"\n  bodies are in {out}. Re-run with "
              f"--install-bodies <projectPath> to put them in a Unity project.")
        return 0

    project = args.install_bodies.resolve()
    if not (project / "Assets").is_dir():
        print(f"  {project} does not look like a Unity project (no Assets/).")
        return 1
    target = project / "Assets" / "Resources" / "extnpc"
    target.mkdir(parents=True, exist_ok=True)
    for path in wanted:
        shutil.copy2(path, target / path.name)
        print(f"  installed {path.name} -> {target / path.name}")
    print("\n  Unity will import them on next focus. VillagerView picks them "
          "up automatically; no scene change is needed.")
    return 0


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
    parser.add_argument("--export-bodies", action="store_true",
                        help="export the two viewer bodies (human_female.fbx, "
                             "human_male.fbx) instead of running the probe")
    parser.add_argument("--ethnicity", default="even_thirds",
                        help="the fixed ethnicity macro for --export-bodies")
    parser.add_argument("--install-bodies", type=Path, default=None,
                        help="a Unity project to copy the bodies into, at "
                             "Assets/Resources/extnpc/. Implies --export-bodies "
                             "if the files are not already there.")
    parser.add_argument("--shoot-village", type=Path, default=None,
                        metavar="BUNDLE",
                        help="photograph a world bundle twice, with the body "
                             "pack installed and with it moved aside. Needs a "
                             "graphics device.")
    parser.add_argument("--install-assets", action="store_true",
                        help="download and install the CC0 "
                             "makehuman_system_assets pack (item A2): eyes, "
                             "eyebrows, eyelashes, teeth, hair, clothes. "
                             "267 MB, resumable, segmented because the origin "
                             "throttles one connection to 32 KB/s.")
    parser.add_argument("--list-assets", action="store_true",
                        help="catalogue the MPFB assets installed here, with "
                             "their uuids, to health_engine/data/mpfb_assets.json")
    parser.add_argument("--shoot-lineup", type=Path, default=None,
                        metavar="BUNDLE",
                        help="photograph the bundle's per-villager bodies "
                             "standing in a row, front on. The village camera "
                             "cannot answer Stage 8's question because twenty "
                             "humans at 34 m are twenty dots. Needs a graphics "
                             "device.")
    parser.add_argument("--perf", action="store_true",
                        help="time 28 to 1000 villagers, capsules against "
                             "bodies, against the plan's 600-at-60 budget. "
                             "Needs a graphics device.")
    parser.add_argument("--check-portrait", action="store_true",
                        help="render the inspector's portrait head to PNG and "
                             "report on it. Needs a graphics device.")
    args = parser.parse_args()

    exe = args.blender or find_blender()
    print(f"  blender  {exe}")
    if args.install_mpfb:
        install_mpfb(exe, args.out / "_install")

    if args.check_portrait:
        return portrait(args)

    if args.install_assets:
        return install_assets(exe, args)

    if args.list_assets:
        return list_assets(exe, args)

    if args.shoot_village is not None:
        return village(args)

    if args.shoot_lineup is not None:
        return lineup(args)

    if args.perf:
        return perf(args)

    if args.export_bodies or args.install_bodies:
        return bodies(exe, args)

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
