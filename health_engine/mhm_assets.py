"""
The MPFB asset catalogue: what is actually installed, read from a probe.

WHY THIS FILE EXISTS AT ALL, and it is the nastiest trap in the body pipeline.
A `.mhm` names a bodypart by NAME and UUID on one line. MPFB's
`HumanService._check_parse_mhm_bodypart_line` first looks for an asset whose
key contains the requested name AND whose `.mhclo` carries the requested uuid.
When that fails and deep search is on, its last resort is this, quoted from
`humanservice.py`:

    given_name = str(asset_name).lower()
    mhclo_name = str(mhclo.name).lower()
    label = asset["label"].lower()
    if given_name == mhclo_name or given_name == label:
        human_info[bodypart] = asset["fragment"]

The requested name is not in that condition. It compares each candidate
against ITSELF, so the first self-consistent asset in the family wins whatever
was asked for. A typo, a renamed asset or a pack that was never installed
therefore does not raise: it silently fits some other asset and renders
happily. Nothing in this project may hardcode an asset name, and this module
is the reason it does not have to.

WHAT IS AND IS NOT TRUSTED HERE. `mpfb/list_assets.py` runs inside Blender,
asks the installed MPFB what it holds, and reads each uuid out of the `.mhclo`
itself. This module only reads that JSON. It refuses any asset with no uuid,
because a uuid-less asset can only ever be matched by the broken path above --
that is not a hypothetical: `proxymeshes` and `skins` report zero uuids in the
shipped CC0 pack, which is exactly why neither is offered here.

WHICH STRING GOES ON THE LINE. The catalogue's `key`, not its `name_in_file`.
The first matcher tests `requested.lower() in key.lower()`, so a key always
matches itself, while `name_in_file` does not always match its key: the eyes
family has key `High-poly` against name_in_file `HighPolyEyes`, and
`"highpolyeyes" in "high-poly"` is False. Emitting `name_in_file` would drop
that line into the deep search every time, which is the road to the fallback
above.
"""

from __future__ import annotations

import json
import os
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

__all__ = [
    "CATALOGUE_PATH",
    "AssetCatalogue",
    "load_catalogue",
    "MissingAssetPack",
]

CATALOGUE_PATH = os.path.join(os.path.dirname(__file__), "data",
                              "mpfb_assets.json")


class MissingAssetPack(RuntimeError):
    """The catalogue is absent, empty, or missing a family that was asked for.

    Raised rather than warned. A missing pack that degrades to "no bodyparts"
    is survivable; a missing pack that degrades to "some other asset" is the
    trap in the module docstring, and the difference between the two is one
    `except` away, so this is loud on purpose.
    """


class AssetCatalogue:
    """The installed assets, as name/uuid pairs per family.

    Immutable by convention and cheap to copy. Holds no Blender handle and no
    file handle: once constructed it is plain data, so the code that chooses
    assets stays a pure function of (villager, catalogue).
    """

    #: Families this project will emit. `proxymeshes` and `skins` are absent
    #: deliberately -- neither carries a uuid, see the module docstring -- and
    #: `skins` is additionally pigmentation, which never enters a `.mhm`.
    EMITTABLE = ("eyes", "eyebrows", "eyelashes", "hair", "teeth", "tongue",
                 "clothes")

    def __init__(self, families: Mapping[str, Sequence[Mapping[str, object]]],
                 source: str = "") -> None:
        self.source = source
        self._families: Dict[str, Tuple[Tuple[str, str], ...]] = {}
        for family, assets in families.items():
            pairs = []
            for asset in assets:
                key = asset.get("key")
                uuid = asset.get("uuid")
                if not key or not uuid:
                    # Dropped, not defaulted. An asset with no uuid can only be
                    # matched by the self-comparing fallback, so offering it
                    # would mean offering "some asset, we will find out which".
                    continue
                pairs.append((str(key), str(uuid)))
            self._families[family] = tuple(sorted(pairs))

    # ------------------------------------------------------------------
    # reading
    # ------------------------------------------------------------------

    def families(self) -> List[str]:
        """Family names that have at least one usable asset, sorted."""
        return sorted(f for f, a in self._families.items() if a)

    def options(self, family: str) -> Tuple[Tuple[str, str], ...]:
        """`(key, uuid)` pairs for `family`, sorted by key.

        Sorted rather than left in the probe's order because the order decides
        which asset a cosmetic index lands on, and a body that changes its
        haircut when MPFB reorders its listing is not reproducible.
        """
        assets = self._families.get(family, ())
        if not assets:
            raise MissingAssetPack(
                f"no usable {family!r} assets in {self.source or 'the catalogue'}. "
                f"Run `python run_mpfb_probe.py --install-assets` to install the "
                f"CC0 pack, then `--list-assets` to re-probe. Families present: "
                f"{', '.join(self.families()) or 'none'}.")
        return assets

    def uuid(self, family: str, key: str) -> str:
        """The uuid for one asset, or raise.

        Raising on an unknown key is the whole point: this is the check that
        turns a typo into an error instead of into someone else's hairstyle.
        """
        for candidate, uuid in self.options(family):
            if candidate == key:
                return uuid
        raise MissingAssetPack(
            f"{family}/{key!r} is not installed. Choosing it anyway would let "
            f"MPFB's deep search substitute a different asset silently. "
            f"Available: {', '.join(k for k, _ in self.options(family))}.")

    @staticmethod
    def token(key: str) -> str:
        """The name to WRITE on a `.mhm` line for an asset whose key is `key`.

        A KEY WITH A SPACE IN IT CANNOT BE WRITTEN DOWN, which is not obvious
        and cost a whole bake to find. MPFB reads a bodypart line with
        `line.split(" ", 2)`, so `clothes Male casualsuit02 <uuid>` parses as
        name=`Male` and uuid=`casualsuit02 <uuid>`. The uuid then matches
        nothing, and because deep search is off the part simply never loads.
        In the first dressed bake every space-free asset bound -- `Ponytail01`,
        `Shoes06`, `Eyebrow005` -- and every spaced one vanished: no suit on
        anybody, and no teeth, with an empty log.

        WHY A SUBSTRING IS SAFE HERE, given that the whole module exists to
        stop loose matching. The matcher's first pass requires BOTH
        `requested.lower() in key.lower()` AND an exact uuid match. Uuids are
        unique, so at most one asset can satisfy the second condition, and the
        substring only has to be specific enough to be a substring of the right
        key. The dangerous loop is the last-resort one, which we never reach:
        it is unreachable with deep search off, and unnecessary with a uuid.

        The LONGEST token is chosen rather than the first because it is the
        informative half -- `casualsuit02` rather than `Male`, `shape02` rather
        than `Teeth` -- so a human reading the `.mhm` can still tell what the
        villager is wearing.
        """
        parts = [p for p in str(key).split(" ") if p]
        if len(parts) <= 1:
            return str(key)
        return max(parts, key=len)

    def line(self, family: str, key: str) -> str:
        """One `.mhm` bodypart line, `<family> <name> <uuid>`.

        `name` is `token(key)`, never the raw key: see `token` for the parsing
        limit that makes the difference.
        """
        return f"{family} {self.token(key)} {self.uuid(family, key)}"

    def key_for_uuid(self, family: str, uuid: str) -> str:
        """The asset whose uuid this is. The inverse of `uuid()`.

        Exists for verification rather than for emission. Once `line()` writes
        a space-free TOKEN rather than the key, the key is no longer readable
        off the line, and a check that wants to ask "is this villager actually
        wearing a male suit" has to go through the uuid, which is the field
        that identifies the asset anyway.
        """
        for candidate, candidate_uuid in self.options(family):
            if candidate_uuid == uuid:
                return candidate
        raise MissingAssetPack(
            f"no {family} asset has uuid {uuid!r} in {self.source}")

    def keys(self, family: str) -> Tuple[str, ...]:
        """Just the keys for `family`, sorted."""
        return tuple(k for k, _ in self.options(family))


def load_catalogue(path: Optional[str] = None) -> AssetCatalogue:
    """Read the probe's JSON. Raises `MissingAssetPack` when it is not there.

    The absent case is an error rather than an empty catalogue because the
    caller's next move would otherwise be to carry on and bake eyeless
    mannequins, which is precisely what the pack was installed to stop.
    """
    target = path or CATALOGUE_PATH
    if not os.path.isfile(target):
        raise MissingAssetPack(
            f"no asset catalogue at {target}. Run "
            f"`python run_mpfb_probe.py --install-assets`, which installs the "
            f"CC0 pack and writes it.")
    with open(target, encoding="utf-8") as fh:
        data = json.load(fh)

    families = data.get("families") or {}
    return AssetCatalogue(
        {name: (info or {}).get("assets", ()) for name, info in families.items()},
        source=target)
