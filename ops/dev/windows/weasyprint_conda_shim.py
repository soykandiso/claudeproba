"""Let WeasyPrint find conda-forge's GTK on a Windows dev host. Not used anywhere else.

Production and the Codespace are Linux, where WeasyPrint finds Pango by its usual
names. On the user's Windows machine (docs/handoff.md §5) Pango comes from
conda-forge, whose DLLs are named `gobject-2.0-0.dll`, not MSYS2's
`libgobject-2.0-0.dll`. WeasyPrint asks for the MSYS2 names, and the conda name it
also tries (`gobject-2.0-0`, no `.dll`) fails because Windows reads `.0-0` as an
extension and never appends `.dll`.

Copying the DLLs under MSYS2 names does not work: Windows then loads two copies of
GObject and Pango, the font map is made in one and used from the other, and Pango
reports `context->font_map != NULL`. So this maps each name WeasyPrint asks for to the
conda file's *full path*, the same module everything else in that folder imports.

Install (once per venv; `uv sync` leaves it alone):

    copy ops\\dev\\windows\\weasyprint_conda_shim.py .venv\\Lib\\site-packages\\
    echo import weasyprint_conda_shim> .venv\\Lib\\site-packages\\weasyprint_conda_shim.pth

It does nothing unless WEASYPRINT_DLL_DIRECTORIES names a folder holding
`gobject-2.0-0.dll`, so it is inert on any machine without conda's GTK.
"""

import os

_NAMES = {
    "libgobject-2.0-0": "gobject-2.0-0.dll",
    "libpango-1.0-0": "pango-1.0-0.dll",
    "libharfbuzz-0": "harfbuzz.dll",
    "libharfbuzz-subset-0": "harfbuzz-subset.dll",
    "libharfbuzz-vector-0": "harfbuzz-vector.dll",
    "libfontconfig-1": "fontconfig-1.dll",
    "libpangoft2-1.0-0": "pangoft2-1.0-0.dll",
}


def _install() -> None:
    if os.name != "nt":
        return
    folders = [d for d in os.environ.get("WEASYPRINT_DLL_DIRECTORIES", "").split(";") if d]
    has_gtk = [d for d in folders if os.path.isfile(os.path.join(d, "gobject-2.0-0.dll"))]
    folder = has_gtk[0] if has_gtk else None
    if folder is None:
        return
    import cffi.api

    original = cffi.api.FFI.dlopen

    def dlopen(self, name, flags=0):
        mapped = _NAMES.get(name)
        if mapped and os.path.isfile(os.path.join(folder, mapped)):
            name = os.path.join(folder, mapped)
        return original(self, name, flags)

    cffi.api.FFI.dlopen = dlopen


_install()
