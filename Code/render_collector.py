"""
render_collector.py — Render Coordinator
Launches Blender as a non-blocking subprocess, polls for PNG frame output,
then converts each stage's PNG sequence to mp4 via ffmpeg.
Returns ("OK", output_dir) or ("FAIL", None) to derg.py.
"""
import json
import logging
import os
import platform
import subprocess
import time
from pathlib import Path
from typing import Any

# ── Paths ─────────────────────────────────────────────────────────────────────
BLEND_FILE      = Path("DergScene.blend")
INTERNAL_SCRIPT = Path("Code/internal_blender.py")

# ── Render settings ───────────────────────────────────────────────────────────
POLL_INTERVAL   = 60      # seconds between output checks
TIMEOUT_MINUTES = 120     # kill blender after 2 hours
FRAMES_PER_STAGE = 10   # expected frame count per stage

STAGE_NAMES = [
    "stage_1_prelaunch",
    "stage_2_launch",
    "stage_3_ascent",
]

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("COLLECTOR")


# ── OS detection ──────────────────────────────────────────────────────────────

def get_blender_exe() -> str:
    """Returns the default Blender executable path for the current OS."""
    system = platform.system()
    if system == "Darwin":
        return "/Applications/Blender.app/Contents/MacOS/Blender"
    elif system == "Windows":
        return "C:\\Program Files\\Blender Foundation\\Blender 4.0\\blender.exe"
    else:
        return "blender"


def get_ffmpeg_exe() -> str:
    """Returns the ffmpeg executable — assumes it is on PATH."""
    return "ffmpeg"


# ── Preflight ─────────────────────────────────────────────────────────────────

def verify_blend(blend_file: Path) -> bool:
    """Checks that DergScene.blend exists before attempting to launch Blender."""
    if not blend_file.exists():
        log.error("DergScene.blend not found at %s", blend_file)
        return False
    return True


# ── Output verification ───────────────────────────────────────────────────────

def count_stage_frames(output_dir: Path, stage_name: str) -> int:
    """
    Counts how many PNG frames exist in the stage's frames folder.
    Returns 0 if the folder doesn't exist.
    """
    frames_dir = output_dir / stage_name
    if not frames_dir.exists():
        return 0
    return len(list(frames_dir.glob("*.png")))


def verify_render(output_dir: Path) -> bool:
    """
    Checks that all 3 stages have rendered their full PNG sequences
    and that all 3 bbox JSON files exist and are non-empty.
    This is the completion signal — not Blender's exit code.
    """
    for stage_name in STAGE_NAMES:
        # check frame count
        frame_count = count_stage_frames(output_dir, stage_name)
        if frame_count < FRAMES_PER_STAGE:
            return False

        # check bbox JSON exists and is non-empty
        bbox_path = output_dir / f"{stage_name}_bbox.json"
        if not bbox_path.exists() or bbox_path.stat().st_size == 0:
            return False

    return True


def verify_mp4s(output_dir: Path) -> bool:
    """
    Checks that all 3 mp4 files exist and are non-empty after conversion.
    """
    return all(
        (output_dir / f"{name}.mp4").exists() and
        (output_dir / f"{name}.mp4").stat().st_size > 0
        for name in STAGE_NAMES
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
        "--background",
        str(BLEND_FILE),
        "--python", str(INTERNAL_SCRIPT),
    ]

    # pass manifest path via env var — avoids CLI escaping issues
    env = os.environ.copy()
    env["DERG_MANIFEST"] = str(manifest_path)

    log.info("Launching Blender — manifest: %s", manifest_path)
    log.debug("Command: %s", " ".join(cmd))

    return subprocess.Popen(cmd, env=env)


# ── Polling loop ──────────────────────────────────────────────────────────────

def poll_until_complete(process: subprocess.Popen, output_dir: Path) -> str:
    """
    Polls output directory every POLL_INTERVAL seconds.
    Logs frame progress per stage each tick so you can see rendering advancing.
    Returns "OK" when all frames and bbox JSONs are present.
    Returns "FAIL" on timeout or if Blender exits without full output.
    """
    elapsed = 0

    while process.poll() is None:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        # log per-stage progress so the user can see what's happening
        for stage_name in STAGE_NAMES:
            count = count_stage_frames(output_dir, stage_name)
            log.info("%s — %d / %d frames", stage_name, count, FRAMES_PER_STAGE)

        if verify_render(output_dir):
            log.info("All frames verified — terminating Blender")
            process.terminate()
            return "OK"

        if elapsed >= TIMEOUT_MINUTES * 60:
            log.error("Render timed out after %s minutes — terminating", TIMEOUT_MINUTES)
            process.terminate()
            return "FAIL"

    # Blender exited on its own — final check
    log.info("Blender process exited — running final output check")
    if verify_render(output_dir):
        return "OK"

    log.error("Blender exited but output is incomplete")
    return "FAIL"


# ── FFmpeg conversion ─────────────────────────────────────────────────────────

def convert_stage_to_mp4(output_dir: Path, stage_name: str,
                          ffmpeg_exe: str, fps: int = 60) -> bool:
    """
    Converts a PNG frame sequence to mp4 using ffmpeg.
    Input:  output_dir/stage_name/%04d.png
    Output: output_dir/stage_name.mp4

    Returns True on success, False on failure.
    ffmpeg must be installed and on PATH.
    """
    frames_dir = output_dir / stage_name
    output_mp4 = output_dir / f"{stage_name}.mp4"

    # %04d matches Blender's default frame naming: 0001.png, 0002.png etc
    input_pattern = str(frames_dir / "%04d.png")

    cmd = [
        ffmpeg_exe,
        "-y",                          # overwrite output if exists
        "-framerate", str(fps),
        "-i", input_pattern,           # input PNG sequence
        "-c:v", "libx264",             # H.264 codec
        "-pix_fmt", "yuv420p",         # compatible pixel format
        "-crf", "18",                  # quality — lower = better (18 is high quality)
        "-preset", "fast",             # encoding speed vs compression tradeoff
        str(output_mp4),
    ]

    log.info("Converting %s to mp4...", stage_name)
    result = subprocess.run(cmd, check=False, capture_output=True)

    if result.returncode != 0:
        log.error("ffmpeg failed for %s: %s", stage_name,
                  result.stderr.decode("utf-8", errors="replace"))
        return False

    log.info("%s.mp4 written → %s", stage_name, output_mp4)
    return True


def convert_all_stages(output_dir: Path, ffmpeg_exe: str, fps: int = 60) -> bool:
    """
    Converts all 3 stage PNG sequences to mp4.
    Returns True only if all 3 conversions succeed.
    """
    results = []
    for stage_name in STAGE_NAMES:
        success = convert_stage_to_mp4(output_dir, stage_name, ffmpeg_exe, fps)
        results.append(success)

    if not all(results):
        log.error("One or more stage conversions failed")
        return False

    log.info("All stages converted to mp4")
    return True


# ── Main entry point ──────────────────────────────────────────────────────────

def collect_render(manifest_path: Path, blender_exe: str = None) -> tuple[str, Any]:
    """
    Main entry point called by derg.py.
    Reads output_dir from the manifest, launches Blender, polls for
    PNG frame completion, then converts to mp4 via ffmpeg.
    Returns ("OK", output_dir) or ("FAIL", None).
    """
    # resolve executables
    if blender_exe is None:
        blender_exe = get_blender_exe()
    ffmpeg_exe = get_ffmpeg_exe()

    # preflight
    if not verify_blend(BLEND_FILE):
        return ("FAIL", None)

    # read output_dir from manifest
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        render_id  = manifest["render_id"]
        output_dir = Path("outputs") / f"render_{render_id:03d}"
    except (KeyError, FileNotFoundError) as e:
        log.error("Could not read manifest at %s — %s", manifest_path, e)
        return ("FAIL", None)

    # ── launch and poll ───────────────────────────────────────────────────
    process = launch_blender(manifest_path, blender_exe)
    result  = poll_until_complete(process, output_dir)

    if result == "FAIL":
        log.error("Render %s failed during Blender stage", render_id)
        return ("FAIL", None)

    # ── convert PNG sequences to mp4 ─────────────────────────────────────
    log.info("Blender complete — starting ffmpeg conversion")
    converted = convert_all_stages(output_dir, ffmpeg_exe)

    if not converted:
        log.error("Render %s failed during ffmpeg conversion", render_id)
        return ("FAIL", None)

    # ── final mp4 verification ────────────────────────────────────────────
    if not verify_mp4s(output_dir):
        log.error("Render %s — mp4 files missing after conversion", render_id)
        return ("FAIL", None)

    log.info("Render %s complete → %s", render_id, output_dir)
    return ("OK", output_dir)