"""
fix_textures.py — One-shot texture path repair for DergScene.blend
Fixes broken/absolute image paths so the file opens clean on any machine.

Designed for a shared drive used by both macOS and Windows — absolute paths
from one OS (/Volumes/... vs D:/...) always break on the other. Relative
paths (// prefix) are OS-agnostic and survive the file moving folders.

Run once from the project root:
    blender DergScene.blend --python fix_textures.py

What it does, in order:
    1. Enables "Save Relative" on the .blend so every future manual save
       keeps paths relative automatically
    2. Unpacks any images packed into the .blend to their expected disk location
    3. Walks assets/ and hdri/ to build a filename -> path lookup for all PNGs and HDRs
    4. For every image block in the file — broken or not — attempts to locate
       it in the lookup and remap it to a // relative path
    5. Reports anything it could not resolve so you can fix it manually
    6. Saves the .blend

Run it once. After saving, all paths will be relative and persistent across
both macOS and Windows as long as the folder structure stays the same.
"""

import bpy
from pathlib import Path


def log(msg: str) -> None:
    print(f"[FIX_TEXTURES] {msg}", flush=True)


def enable_relative_paths() -> None:
    """
    Turns on 'Save Relative' for the current file so every future save —
    including manual saves on either OS — keeps paths as // relative.
    This is the file-level setting under File > External Data > Make All Paths Relative.
    """
    bpy.context.preferences.filepaths.use_relative_paths = True
    # also run the built-in operator to remap any currently-valid paths right now
    try:
        bpy.ops.file.make_paths_relative()
        log("Save Relative enabled and existing paths remapped.")
    except Exception as e:
        log(f"make_paths_relative operator failed (non-fatal): {e}")


def build_texture_lookup(blend_dir: Path) -> dict[str, Path]:
    """
    Walks assets/ and hdri/ and builds a lowercase filename -> absolute path dict.
    Covers PNGs anywhere under assets/, and HDR/EXR files under hdri/.
    If two files share a filename the first found wins and a warning is logged —
    keep texture filenames unique across the project to avoid this.
    """
    lookup: dict[str, Path] = {}
    search_roots = [
        (blend_dir / "assets", ["*.png", "*.PNG"]),
        (blend_dir / "hdri",   ["*.hdr", "*.HDR", "*.exr", "*.EXR"]),
    ]

    for root, patterns in search_roots:
        if not root.exists():
            log(f"  Folder not found, skipping: {root}")
            continue
        for pattern in patterns:
            for f in root.rglob(pattern):
                key = f.name.lower()
                if key in lookup:
                    log(f"  WARNING duplicate filename: {f.name} — keeping {lookup[key]}")
                else:
                    lookup[key] = f

    log(f"Texture lookup built: {len(lookup)} file(s) found.")
    return lookup


def unpack_images(blend_dir: Path) -> None:
    """
    Unpacks any images that are packed into the .blend file out to disk.
    Uses USE_ORIGINAL so it respects the stored filepath rather than inventing one.
    Falls back to WRITE_LOCAL (next to the .blend) if the original path is missing.
    """
    packed = [img for img in bpy.data.images if img.packed_file]
    if not packed:
        log("No packed images found.")
        return

    log(f"Unpacking {len(packed)} packed image(s)...")
    for img in packed:
        try:
            img.unpack(method='USE_ORIGINAL')
            log(f"  Unpacked (original path): {img.name}")
        except Exception:
            try:
                img.unpack(method='WRITE_LOCAL')
                log(f"  Unpacked (local fallback): {img.name}")
            except Exception as e2:
                log(f"  WARNING: could not unpack {img.name} — {e2}")


def to_relative(path: Path, blend_dir: Path) -> str:
    """
    Converts an absolute path to a Blender-style relative path (// prefix).
    Always uses forward slashes so the path is valid on both macOS and Windows.
    Returns the original path string unchanged if it cannot be made relative.
    """
    try:
        rel = path.relative_to(blend_dir)
        return "//" + str(rel).replace("\\", "/")
    except ValueError:
        return str(path)


def repair_image_paths(lookup: dict[str, Path], blend_dir: Path) -> tuple[int, int, list[str]]:
    """
    Iterates every image datablock and attempts to:
      - Convert already-valid absolute paths to relative
      - Relocate broken/missing paths using the texture lookup by filename
    Cross-platform note: bpy.path.abspath() resolves // paths using the
    current OS, so a path that was absolute on Windows will be broken on Mac
    and fall through to the filename-based lookup — which is exactly what we want.
    Returns (fixed_count, already_ok_count, unresolved_names).
    """
    fixed      = 0
    already_ok = 0
    unresolved = []

    for img in bpy.data.images:
        # skip internal types that have no real file path
        if img.type in ('RENDER_RESULT', 'COMPOSITING'):
            continue

        raw_path = bpy.path.abspath(img.filepath, library=img.library)
        abs_path = Path(raw_path) if raw_path else None

        # ── case 1: path resolves fine on this OS ─────────────────────────
        if abs_path and abs_path.exists():
            new_rel = to_relative(abs_path, blend_dir)
            if img.filepath != new_rel:
                log(f"  Repathed  (found):    {img.name}")
                log(f"                        {img.filepath}")
                log(f"                     -> {new_rel}")
                img.filepath = new_rel
                fixed += 1
            else:
                already_ok += 1
            continue

        # ── case 2: path broken — locate by filename in lookup ─────────────
        # strip any path component, just use the bare filename
        raw_filename = Path(img.filepath).name if img.filepath else ""
        fallback_name = img.name  # Blender uses the filename as the datablock name by default
        key = (raw_filename or fallback_name).lower()

        match = lookup.get(key)

        if match:
            new_rel = to_relative(match, blend_dir)
            log(f"  Relocated (broken):   {img.name}")
            log(f"                        {img.filepath or '(no path)'}")
            log(f"                     -> {new_rel}")
            img.filepath = new_rel
            img.reload()
            fixed += 1
        else:
            log(f"  UNRESOLVED:           {img.name}  ({img.filepath or 'no path stored'})")
            unresolved.append(img.name)

    return fixed, already_ok, unresolved


def main() -> None:
    log("Starting texture path repair...")

    blend_path = bpy.data.filepath
    if not blend_path:
        log("ERROR: .blend file has not been saved to disk yet — save it first, then re-run.")
        return

    blend_dir = Path(blend_path).parent
    log(f".blend location: {blend_dir}")

    # ── step 1: enable relative path saving for all future saves ──────────
    enable_relative_paths()

    # ── step 2: unpack anything embedded in the .blend ────────────────────
    unpack_images(blend_dir)

    # ── step 3: build filename lookup from assets/ and hdri/ ──────────────
    lookup = build_texture_lookup(blend_dir)

    # ── step 4: repair all image paths ────────────────────────────────────
    fixed, already_ok, unresolved = repair_image_paths(lookup, blend_dir)

    # ── step 5: save ──────────────────────────────────────────────────────
    if fixed > 0:
        log(f"Saving {blend_path}...")
        bpy.ops.wm.save_mainfile()
        log("Saved.")
    else:
        log("No paths changed — skipping save.")

    # ── summary ───────────────────────────────────────────────────────────
    log("")
    log("━━  Repair complete  ━━")
    log(f"  Fixed:       {fixed}")
    log(f"  Already OK:  {already_ok}")
    log(f"  Unresolved:  {len(unresolved)}")

    if unresolved:
        log("")
        log("The following images could not be located automatically.")
        log("Use File > External Data > Find Missing Files in Blender to relink them:")
        for name in unresolved:
            log(f"    * {name}")
    else:
        log("")
        log("All textures resolved. The file will now open clean on both macOS and Windows.")


main()
