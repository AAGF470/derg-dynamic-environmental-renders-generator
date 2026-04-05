import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any
import random
from Code.derg_assets import SKY_POOL, WEATHER_POOL, TERRAIN_POOL, LOCATION_POOL
from Code.builder import build_scene

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("DERG")

# Local pool map — used by context() to resolve null fields
POOL_MAP = {
    "sky":      SKY_POOL,
    "weather":  WEATHER_POOL,
    "terrain":  TERRAIN_POOL,
    "location": LOCATION_POOL,
}


def read_job(name_of_job: str) -> Any:
    """Grabs the JSON file for the blender session."""
    with open(name_of_job, "r", encoding="utf-8") as raw_job:
        return json.load(raw_job)


def save_session(session: dict[str, Any], path: str) -> None:
    """Writes the current session state back to disk."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session, f, indent=2)


def validate_job(session: dict[str, Any]) -> bool:
    """
    Checks if the blender job is in the proper format for rendering.

    Args:
        session: the loaded session dictionary to validate.
    Returns:
        bool: False if the format is not sufficient.
    Raises:
        KeyError: if any required key is missing.
    """
    try:
        if not isinstance(session["engine"], str):
            log.error("'engine' must be a string")
            return False

        if not isinstance(session["renders"], list):
            log.error("'renders' must be a list")
            return False

        for render in session["renders"]:
            render_id = render["id"]

            for field in ["sky", "weather", "terrain", "location"]:
                value = render[field]
                if value is not None and not isinstance(value, (str, list)):
                    log.error("Render %s field '%s' must be null, a string, or a list", render_id, field)
                    return False

            if render["status"] not in ("pending", "done", "failed"):
                log.error("Render %s has invalid status '%s'", render_id, render["status"])
                return False

    except KeyError as e:
        log.error("Session file is missing required key %s", e)
        return False

    return True


def context(session: dict[str, Any], path: str) -> None:
    """
    Standardizes the session JSON — resolves null and list fields
    into single concrete string values via random selection.

    Does not edit done or failed renders.
    Writes the resolved session back to disk immediately.
    """
    for each_render in session["renders"]:
        if each_render["status"] == "pending":
            for field in ["sky", "weather", "terrain", "location"]:
                value = each_render[field]
                if isinstance(value, list):
                    each_render[field] = random.choice(value)
                elif value is None:
                    each_render[field] = random.choice(POOL_MAP[field])

    save_session(session, path)
    log.info("Session context resolved and written to %s", path)


def main() -> None:
    """
    Main entry point.
    Validates and resolves the session JSON, then iterates
    pending renders — calling builder and render_collector in sequence.
    Writes render status back to disk after every render attempt.
    """
    if len(sys.argv) < 2:
        print("Usage: python derg.py session.json")
        sys.exit(1)

    session_path = sys.argv[1]
    session      = read_job(session_path)

    if not validate_job(session):
        log.error("Session file is invalid — exiting.")
        sys.exit(1)

    context(session, session_path)

    for each_render in session["renders"]:
        if each_render["status"] in ("done", "failed"):
            log.info("Render %s skipped — %s", each_render["id"], each_render["status"])
            continue

        log.info("━━  Render %s  ━━", each_render["id"])

        # ── Stage 1: build scene manifest ─────────────────────────────────
        status, manifest_path = build_scene(each_render)

        if status == "FAIL":
            log.error("Render %s failed at build stage — skipping.", each_render["id"])
            each_render["status"] = "failed"
            save_session(session, session_path)
            continue

        # ── Stage 2: render (render_collector — not yet wired) ────────────
        # TODO: status, output_dir = collect_render(manifest_path)
        # TODO: verify output files on disk
        # TODO: each_render["status"] = "done" or "failed"
        # TODO: save_session(session, session_path)

    log.info("━━  Session complete  ━━")


if __name__ == "__main__":
    main()