import logging
import subprocess
import time
from pathlib import Path
from typing import Any
import platform
import os
import json

# ── Paths ─────────────────────────────────────────────────────────────────────
BLEND_FILE      = Path("DergScene.blend")
INTERNAL_SCRIPT = Path("Code/internal_blender.py")

# ── Render settings ───────────────────────────────────────────────────────────
POLL_INTERVAL   = 60     # seconds between output checks
TIMEOUT_MINUTES = 120    # kill blender after 2 hours

EXPECTED_FILES = [
    "stage_1_prelaunch.mp4",
    "stage_1_prelaunch_bbox.json",
    "stage_2_launch.mp4",
    "stage_2_launch_bbox.json",
    "stage_3_ascent.mp4",
    "stage_3_ascent_bbox.json",
]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("COLLECTOR")


# ── Preflight ─────────────────────────────────────────────────────────────────

def verify_blend(blend_file: Path) -> bool:
    """Checks that DergScene.blend exists before attempting to launch Blender."""
    if not blend_file.exists():
        log.error("DergScene.blend not found at %s", blend_file)
        return False
    return True


def get_blender_exe() -> str:
    """Returns the default Blender executable path for the current OS."""
    system = platform.system()
    if system == "Darwin":
        return "/Applications/Blender.app/Contents/MacOS/Blender"
    elif system == "Windows":
        return "C:\\Program Files\\Blender Foundation\\Blender 4.0\\blender.exe"
    else:
        return "blender"


# ── Output verification ───────────────────────────────────────────────────────

def verify_render(output_dir: Path) -> bool:
    """
    Checks all 6 expected output files exist and are non-zero in size.
    This is the only reliable completion signal — not Blender's exit code.
    """
    return all(
        (output_dir / f).exists() and (output_dir / f).stat().st_size > 0
        for f in EXPECTED_FILES
    )


# ── Blender launcher ──────────────────────────────────────────────────────────

def launch_blender(manifest_path: Path, blender_exe: str) -> subprocess.Popen:
    """
    Launches Blender headlessly as a non-blocking subprocess.
    Passes the manifest path to internal_blender.py via environment variable.
    Returns the process handle for polling.
    """
    cmd = [
        blender_exe,
        "--background",                    # no UI, headless
        str(BLEND_FILE),                   # open DergScene.blend
        "--python", str(INTERNAL_SCRIPT),  # inject internal_blender.py
    ]

    # pass manifest path via environment — cleanest way to communicate
    # into Blender without CLI argument escaping issues
    env = os.environ.copy()
    env["DERG_MANIFEST"] = str(manifest_path)

    log.info("Launching Blender — manifest: %s", manifest_path)
    log.debug("Command: %s", " ".join(cmd))

    return subprocess.Popen(cmd, env=env)


# ── Polling loop ──────────────────────────────────────────────────────────────

def poll_until_complete(process: subprocess.Popen, output_dir: Path) -> str:
    """
    Polls the output directory every POLL_INTERVAL seconds.
    Returns "OK" when all expected files appear on disk.
    Returns "FAIL" on timeout or if Blender exits without producing output.

    Uses file verification rather than exit codes — Blender can exit non-zero
    after a successful render, and can exit zero after a failed one.
    """
    elapsed = 0

    while process.poll() is None:           # None = Blender still running
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        log.info("Polling output — %s minutes elapsed", elapsed // 60)

        if verify_render(output_dir):
            log.info("Output verified — all files present")
            process.terminate()             # cleanly stop Blender
            return "OK"

        if elapsed >= TIMEOUT_MINUTES * 60:
            log.error("Render timed out after %s minutes — terminating", TIMEOUT_MINUTES)
            process.terminate()
            return "FAIL"

    # Blender exited on its own — do one final check before declaring failure
    log.info("Blender process exited — running final output check")
    if verify_render(output_dir):
        return "OK"

    log.error("Blender exited but output files are missing or empty")
    return "FAIL"


# ── Main entry point ──────────────────────────────────────────────────────────

def collect_render(manifest_path: Path, blender_exe: str = None) -> tuple[str, Any]:
    """
    Main entry point called by derg.py.
    Reads output_dir from the manifest, launches Blender, polls for completion.
    Returns ("OK", output_dir) or ("FAIL", None).
    """
    # resolve blender executable
    if blender_exe is None:
        blender_exe = get_blender_exe()

    # preflight — check blend file exists before doing anything
    if not verify_blend(BLEND_FILE):
        return ("FAIL", None)

    # read output_dir from manifest — avoids passing it as a parameter
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        render_id  = manifest["render_id"]
        output_dir = Path("outputs") / f"render_{render_id:03d}"
    except (KeyError, FileNotFoundError) as e:
        log.error("Could not read manifest at %s — %s", manifest_path, e)
        return ("FAIL", None)

    # launch and poll
    process = launch_blender(manifest_path, blender_exe)
    result  = poll_until_complete(process, output_dir)

    if result == "OK":
        log.info("Render %s complete — output at %s", render_id, output_dir)
        return ("OK", output_dir)

    log.error("Render %s failed", render_id)
    return ("FAIL", None)