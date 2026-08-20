"""
Install the MakeHuman CC0 system assets pack (item A2). Runs OUTSIDE Blender.

    python run_mpfb_probe.py --install-assets

WHY THIS IS A SCRIPT AND NOT A README LINE. The pack is 267 MB and the origin
throttles a single connection to about **32 KB/s**, measured, which puts it two
and a half hours away. It does honour Range requests, so this pulls N segments
concurrently and gets the same bytes in a fraction of the time. A README line
saying "download the pack" hands the next person a two-hour wait and no clue
that it is avoidable.

RESUMABLE ON PURPOSE. Segments are cached individually and a complete one is
never re-fetched, so an interrupted run costs only the segments that were in
flight. The cache lives beside the repo rather than in a temp directory for
exactly that reason: a session-scoped temp directory throws away the download
when the session ends, which is how this ended up being started twice.

WHAT IT DOES NOT DO. It does not verify a checksum, because upstream publishes
none. It verifies the assembled size against the Content-Length the server
reported and it verifies the zip's own central directory by opening it, which
together catch truncation and corruption but would not catch a substituted
file. Said plainly rather than implied, because "verified" should mean
something specific.

LICENCE. The pack is CC0, which is what makes it shippable in the same
sentence as this project's licence story: GPLv3 tooling, CC0 output, a
permissive package. MPFB's own code stays GPLv3 and is never vendored; this
downloads ASSETS, which is a different thing with a different licence.
Source: http://static.makehumancommunity.org/assets/assetpacks.html
"""

from __future__ import annotations

import concurrent.futures as cf
import os
import shutil
import sys
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import List, Tuple

PACK_URL = ("https://files2.makehumancommunity.org/asset_packs/"
            "makehuman_system_assets/makehuman_system_assets_cc0.zip")

# Segment count. Sixteen was measured to give roughly eight times the
# single-connection rate; the origin appears to throttle per connection rather
# than per client, but more segments stop helping and start looking abusive.
SEGMENTS = 16

DEFAULT_CACHE = Path("outputs") / "mpfb" / "assetpack"


def plan_segments(total: int, n: int) -> List[Tuple[int, int, int]]:
    """Split `total` bytes into at most `n` (index, start, end) inclusive spans.

    Pure arithmetic so it can be tested without a network. The off-by-one that
    matters is the last span's end, which must be `total - 1` and not `total`:
    an HTTP Range whose end is past the resource is not an error, it is
    silently clamped, so a wrong end here produces a file that is the right
    size and has a duplicated tail.
    """
    if total <= 0:
        raise ValueError(f"total must be positive, got {total}")
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")

    chunk = (total + n - 1) // n
    spans = []
    for i in range(n):
        start = i * chunk
        if start >= total:
            break
        spans.append((i, start, min(start + chunk - 1, total - 1)))
    return spans


def remote_size(url: str = PACK_URL, timeout: int = 60) -> int:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.headers["Content-Length"])


def resume_offset(have: int, start: int, end: int) -> int:
    """Where to restart a partially fetched segment, as an absolute byte offset.

    Returns `end + 1` when the segment is already complete, which the caller
    reads as "nothing to do".

    This is a function rather than three lines inline because resuming WITHIN a
    segment is the difference between a cache that helps and one that does
    not. Interrupt a 16-way download and the overwhelmingly likely state is
    sixteen PARTIAL segments and zero complete ones, so a resume that only
    skips exact-size parts throws away everything it just spent an hour
    fetching. That is exactly what happened on 2026-08-20: 178 MB cached,
    0 of 16 segments complete.

    A `have` larger than the segment means the file on disk is not what this
    plan expects, so it is discarded rather than appended to; trusting it would
    splice foreign bytes into the middle of the archive.
    """
    if have < 0:
        raise ValueError(f"have must not be negative, got {have}")
    size = end - start + 1
    if have >= size:
        return end + 1 if have == size else start
    return start + have


def _fetch_segment(url: str, cache: Path, index: int, start: int, end: int,
                   attempts: int = 5) -> int:
    path = cache / f"p{index:02d}"
    expected = end - start + 1

    for attempt in range(attempts):
        have = path.stat().st_size if path.exists() else 0
        offset = resume_offset(have, start, end)
        if offset > end:
            return expected                  # complete; do not refetch

        # A short partial is appended to; anything else starts clean.
        mode = "ab" if offset > start else "wb"
        request = urllib.request.Request(
            url, headers={"Range": f"bytes={offset}-{end}"})
        try:
            with urllib.request.urlopen(request, timeout=300) as response, \
                    open(path, mode) as handle:
                shutil.copyfileobj(response, handle, 65536)
            if path.stat().st_size == expected:
                return expected
            raise IOError(f"segment {index} is {path.stat().st_size}, "
                          f"expected {expected}")
        except Exception:                                        # noqa: BLE001
            if attempt == attempts - 1:
                raise
            time.sleep(2 * (attempt + 1))
    return 0


def download(cache: Path, url: str = PACK_URL,
             segments: int = SEGMENTS) -> Path:
    """Fetch the pack into `cache`, resuming, and return the assembled zip."""
    cache.mkdir(parents=True, exist_ok=True)
    zip_path = cache / "makehuman_system_assets_cc0.zip"

    total = remote_size(url)
    if zip_path.exists() and zip_path.stat().st_size == total:
        print(f"  already downloaded: {zip_path} ({total:,} bytes)")
        return zip_path

    spans = plan_segments(total, segments)
    have = sum((cache / f"p{i:02d}").stat().st_size
               for i, _, _ in spans if (cache / f"p{i:02d}").exists())
    print(f"  {total:,} bytes in {len(spans)} segments"
          + (f", {have:,} already cached" if have else ""))

    start_time = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=len(spans)) as pool:
        futures = [pool.submit(_fetch_segment, url, cache, i, s, e)
                   for i, s, e in spans]
        done = 0
        for future in cf.as_completed(futures):
            future.result()
            done += 1
            print(f"    segment {done}/{len(spans)} "
                  f"({time.perf_counter() - start_time:.0f}s)", flush=True)

    with open(zip_path, "wb") as out:
        for i, _, _ in spans:
            with open(cache / f"p{i:02d}", "rb") as part:
                shutil.copyfileobj(part, out, 1 << 20)

    size = zip_path.stat().st_size
    elapsed = time.perf_counter() - start_time
    print(f"  wrote {size:,} bytes in {elapsed:.0f}s "
          f"({size / max(elapsed, 1) / 1024:.0f} KB/s)")
    if size != total:
        raise SystemExit(f"size mismatch: got {size:,}, expected {total:,}")
    return zip_path


def extract(zip_path: Path, data_dir: Path) -> dict:
    """Unpack into MPFB's data directory. Returns a per-family file count.

    The zip's own layout decides where things land; MPFB expects
    `<data>/eyes/...`, `<data>/hair/...` and so on. If upstream ever changes
    the layout this reports zero for every family rather than appearing to
    succeed, which is what the caller checks.
    """
    data_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            raise SystemExit(f"corrupt entry in the archive: {bad}")
        archive.extractall(data_dir)

    families = {}
    for child in sorted(data_dir.iterdir()):
        if child.is_dir():
            families[child.name] = sum(1 for _ in child.rglob("*") if _.is_file())
    return families
