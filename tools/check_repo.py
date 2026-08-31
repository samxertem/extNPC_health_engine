"""Repository hygiene, as a gate rather than as a habit.

Every rule here was checked by hand at least once and then forgotten about
until it broke. A rule enforced by memory is enforced until the day it is not,
so each one is a check that can fail, and each names what to do about it.

Usage:  python tools/check_repo.py
Exit code is 1 if any rule is broken.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import List

ROOT = Path(__file__).resolve().parents[1]

fails: List[str] = []


def gate(label: str, ok: bool, detail: str = "") -> None:
    print(("  PASS  " if ok else "  FAIL  ") + label
          + (("   " + detail) if detail else ""))
    if not ok:
        fails.append(label)


def tracked() -> List[str]:
    out = subprocess.run(["git", "ls-files"], cwd=str(ROOT),
                         capture_output=True, text=True)
    return [ln for ln in out.stdout.splitlines() if ln]


def read(rel: str) -> str:
    try:
        return (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


print("PROSE STYLE")
# Standing preference: rewrite, do not substitute a hyphen.
prose_files = ["README.md", "unity/com.samal.extnpc/README.md"]
dashes = {f: read(f).count("—") + read(f).count("–")
          for f in prose_files if (ROOT / f).exists()}
bad = {f: n for f, n in dashes.items() if n}
gate("no em or en dashes in prose", not bad, str(bad) if bad else "")

# The public name is SAMARA. extNPC survives only as identifiers: an
# environment variable, a UPM package path and a C# class.
readme = read("README.md")
ident = ("EXTNPC_CATALOGUE", "com.samal.extnpc", "ExtNpcWorldLoader")
stray = [ln for ln in readme.splitlines()
         if "extnpc" in ln.lower() and not any(i in ln for i in ident)]
gate("README says SAMARA, not extNPC", not stray,
     (stray[0][:60] if stray else ""))


print("\nLINKS")
missing = []
for m in re.finditer(r'src="([^"]+)"', readme):
    href = m.group(1)
    if href.startswith("http"):
        continue
    if not (ROOT / href).exists():
        missing.append(href)
gate("every README image resolves", not missing, ", ".join(missing[:3]))


print("\nDEAD POINTERS")
# reads/ holds private notes and is not tracked, so a path into it is a dead
# reference the moment somebody clones the repository.
offenders = []
for rel in tracked():
    if rel == ".gitignore" or rel.startswith("tools/"):
        continue
    if not rel.endswith((".py", ".cs", ".md", ".txt", ".json")):
        continue
    if "reads/" in read(rel):
        offenders.append(rel)
gate("no reads/ paths in tracked source", not offenders,
     ", ".join(offenders[:3]))


print("\nGENERATED ARTEFACTS")
# The diagrams claim to be reproducible. Rebuild them and find out.
before = {p.name: p.read_bytes() for p in (ROOT / "docs" / "brand").glob("*.svg")}
if before:
    subprocess.run([sys.executable, "docs/make_diagrams.py"], cwd=str(ROOT),
                   capture_output=True, text=True)
    after = {p.name: p.read_bytes()
             for p in (ROOT / "docs" / "brand").glob("*.svg")}
    moved = [k for k in before if before[k] != after.get(k)]
    gate("diagrams regenerate byte-identically", not moved, ", ".join(moved))
else:
    gate("diagrams present", False, "docs/brand is empty")

shots = list((ROOT / "docs" / "showcase").glob("*.png"))
gate("showcase images present", len(shots) >= 12, "%d files" % len(shots))


print("\nPACKAGING")
gate("a licence exists", (ROOT / "LICENSE").exists(),
     "" if (ROOT / "LICENSE").exists() else "blocks any public release")
pkg = read("unity/com.samal.extnpc/package.json")
gate("the Unity package declares its licence", '"license"' in pkg,
     "" if '"license"' in pkg else "package.json has no license field")

print("\n" + "=" * 58)
print("REPOSITORY CLEAN" if not fails else "BROKEN: " + "; ".join(fails))
sys.exit(1 if fails else 0)
