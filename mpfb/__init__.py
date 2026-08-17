"""Build-time bridge to MPFB2 (MakeHuman Plugin For Blender).

NOT part of the shipped Unity package, and never will be. MPFB's code is
GPLv3 while its assets are CC0, so the baked FBX/glTF output can ship
anywhere but the generator cannot be vendored into `com.samal.extnpc`. This
package only ever *drives* an MPFB installed on the developer's machine; it
contains none of MPFB's code. See `reads/MPFB_UNITY_INVESTIGATION.md` §2.

`blender_probe.py` runs inside Blender and is not importable outside it. It
imports `bpy` at module scope on purpose, so importing it from pytest fails
loudly rather than silently measuring nothing.
"""
