"""
builder.py — Scene Manifest Generator
Receives a resolved render dict from derg.py, queries asset pools,
generates asset placements, and writes scene_manifest.json to disk.
Returns ("OK", manifest_path) or ("FAIL", None) to derg.py.
"""
import json
import logging
import math
import random
from pathlib import Path
from typing import Any
from Code.derg_assets import ASSETS, LOCATION, SKY, WEATHER, TERRAIN, MATERIALS
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("BUILDER")
GRID_SIZE   = 400
PAD_CENTER  = (200.0, 200.0)
PAD_RADIUS  = 30.0
CHUNK_SIZE  = 50
MAX_ATTEMPTS = 50  # max resampling attempts before giving up on a point
# builder.py owns everything about placement behaviour
CLUSTER_TYPES = ["tree", "rock", "foliage"]   # structures always use zone placement

SPREAD = {
    "tree":    25.0,
    "rock":    15.0,
    "foliage": 20.0,
}

MIN_DIST = {
    "tree":    5.0,
    "rock":    2.0,
    "foliage": 1.5,
}
MIN_DIST_STRUCTURE = 20.0  # structures need more space than other assets

STRUCTURE_ZONES = [
    (300, 380, 300, 380),
    (20,  100, 300, 380),
    (300, 380, 20,  100),
    (20,  100, 20,  100),
    (150, 250, 320, 380),
    (150, 250, 20,  80),
]
#--------------- MATH (EWW) -------------------

def distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two 2D points."""
    return math.sqrt((x1 - x2)**2 + (y1 - y2)**2)
def in_pad_zone(x: float, y: float) -> bool:
    """Returns True if the point falls inside the rocket pad exclusion zone."""
    return distance(x, y, PAD_CENTER[0], PAD_CENTER[1]) < PAD_RADIUS
def in_bounds(x: float, y: float) -> bool:
    """Returns True if the point is within the 400x400 grid."""
    return 0.0 <= x <= GRID_SIZE and 0.0 <= y <= GRID_SIZE
def edge_weight(x: float, y: float) -> float:
    """
    Returns a 0.0-1.0 weight based on distance from pad center.
    0.0 = at the pad, 1.0 = at the grid edge.
    Used for density falloff — assets more likely near edges.
    """
    dist = distance(x, y, PAD_CENTER[0], PAD_CENTER[1])
    return min(dist / (GRID_SIZE / 2), 1.0)
def too_close(x: float, y: float, existing: list, min_dist: float) -> bool:
    """
    Returns True if (x, y) is within min_dist of any existing Pointer.
    Used by Poisson disk sampling to prevent asset overlap.
    """
    return any(distance(x, y, p.x, p.y) < min_dist for p in existing)

def valid_position(x: float, y: float, existing: list, min_dist: float) -> bool:
    """
    Returns True if a position passes all placement checks:
    inside grid bounds, outside pad zone, not too close to existing assets.
    """
    return in_bounds(x, y) and not in_pad_zone(x, y) and not too_close(x, y, existing, min_dist)
#--------------- Query Helpers -------------------

def get_assets_by_type(asset_type: str, location: str) -> list[dict]:
    """
    Returns all assets of the given type valid for the given location.
    Checks asset tags against the location's allowed_tags.
    """
    if asset_type not in ASSETS:
        log.warning("Unknown asset type '%s'", asset_type)
        return []

    allowed     = set(LOCATION[location]["allowed_tags"])
    asset_list  = []

    for asset in ASSETS[asset_type]:
        asset_tags = set(asset["tags"])
        if asset_tags & allowed:
            asset_list.append(asset)

    return asset_list
def pick_asset(asset_type: str, location: str) -> str:
    """Randomly selects one asset name from the valid pool for a type and location."""
    pool = get_assets_by_type(asset_type, location)
    if not pool:
        log.warning("No assets found for type '%s' in location '%s'", asset_type, location)
        return ""
    return random.choice(pool)["name"]
#--------------- Asset Intilization -------------------

def random_scale(base: float = 1.0, variance: float = 0.2) -> float:
    """Returns a randomised scale value centered on base. variance of 0.2 = ±20%."""
    return round(random.uniform(base - variance, base + variance), 3)


def random_rotation() -> float:
    """Returns a random Y-axis rotation in degrees 0-360."""
    return round(random.uniform(0.0, 360.0), 2)
    
class Pointer:
    """
    Base placement unit for a single scene asset.
    asset_name and asset_type are set on creation.
    x, y, z, scale, rotation are all set by the populator.
    Subclass for asset types requiring additional placement data.
    """
    def __init__(self, asset_name: str, asset_type: str):
        self.asset_name = asset_name
        self.asset_type = asset_type
        self.x          = 0.0
        self.y          = 0.0
        self.z          = 0.0
        self.scale      = 1.0
        self.rotation   = 0.0
def calculate_assets(render: dict[str, Any])->dict[str, int]:
    """
    Calculates the amount of assets of each type to be placed into the scene
    """
    rules = LOCATION[render["location"]]["asset_rules"]
    counts = {}
    for asset_type in ["tree", "rock", "structure", "foliage"]:
        counts[asset_type] = random.randint(rules[asset_type]["min"], rules[asset_type]["max"])
    return counts

def pointer_generator(asset_amounts: dict[str, int], location: str) -> dict[str, list[Pointer]]:
    """
    Generates pointers grouped by asset type.
    Each pointer has identity (name, type) but no position yet.
    """
    pointers: dict[str, list[Pointer]] = {}

    for asset_type in ["tree", "rock", "structure", "foliage"]:
        pointers[asset_type] = []
        for _ in range(asset_amounts[asset_type]):
            name = pick_asset(asset_type, location)
            if name:
                pointers[asset_type].append(Pointer(name, asset_type))

    return pointers
def populator(pointers: dict[str, list[Pointer]]) -> dict[str, list[Pointer]]:
    for asset_type in CLUSTER_TYPES:
        pointers[asset_type] = populate_clusters(
            pointers[asset_type],
            SPREAD[asset_type],
            MIN_DIST[asset_type]
        )
    pointers["structure"] = populate_structures(pointers["structure"])
    return pointers

def populate_clusters(pointers: list[Pointer], spread: float, min_dist: float) -> list[Pointer]:
    """
    Uses the cluster algo for positioning
    """
    num_clusters = max(1, len(pointers) // 4)
    cluster_centers = []

    for _ in range(num_clusters):
        for _ in range(MAX_ATTEMPTS):
            cx = random.uniform(0, GRID_SIZE)
            cy = random.uniform(0, GRID_SIZE)
            if not in_pad_zone(cx, cy) and in_bounds(cx, cy):
                cluster_centers.append((cx, cy))
                break
    placed: list[Pointer] = []

    for pointer in pointers:
        cx, cy = random.choice(cluster_centers)
    
        for _ in range(MAX_ATTEMPTS):
            x = random.gauss(cx, spread)
            y = random.gauss(cy, spread)
        
            if valid_position(x, y, placed, min_dist):
                if random.random() < edge_weight(x, y):
                    pointer.x        = round(x, 3)
                    pointer.y        = round(y, 3)
                    pointer.scale    = random_scale()
                    pointer.rotation = random_rotation()
                    placed.append(pointer)
                    break
        else:
            log.warning("Could not place %s after %s attempts — skipping", pointer.asset_name, MAX_ATTEMPTS)

    return placed

def populate_structures(pointers: list[Pointer]) -> list[Pointer]:
    placed: list[Pointer] = []
    available_zones = STRUCTURE_ZONES.copy()
    random.shuffle(available_zones)

    for pointer in pointers:
        if not available_zones:
            log.warning("No available zones left for structure %s — skipping", pointer.asset_name)
            break

        zone = available_zones.pop()  # take one zone off the list
        x_min, x_max, y_min, y_max = zone

        for _ in range(MAX_ATTEMPTS):
            x = random.uniform(x_min, x_max)
            y = random.uniform(y_min, y_max)

            if valid_position(x, y, placed, MIN_DIST_STRUCTURE):
                pointer.x        = round(x, 3)
                pointer.y        = round(y, 3)
                pointer.scale    = random_scale(base=1.0, variance=0.1)  # structures vary less
                pointer.rotation = random_rotation()
                placed.append(pointer)
                break
        else:
            log.warning("Could not place structure %s — skipping", pointer.asset_name)
            available_zones.append(zone)  # return zone to pool if placement failed
    return placed

def write_manifest(render: dict[str, Any], pointers: dict[str, list[Pointer]], output_dir: Path) -> tuple[str, Any]:
    """
    Serialises the fully resolved scene into a JSON manifest.
    This is the final output of builder.py — internal_blender.py reads this file.
    Returns ("OK", manifest_path) on success or ("FAIL", None) on failure.
    """

    # pull the HDRI from the sky pool — one random choice from the available HDRIs for this sky type
    chosen_hdri = random.choice(SKY[render["sky"]]["hdri"])

    # pull terrain mesh name and randomise its scale within the allowed range for this terrain type
    terrain_mesh  = TERRAIN[render["terrain"]]["mesh"]
    terrain_scale = round(random.uniform(*TERRAIN[render["terrain"]]["scale_range"]), 3)

    # pull location-specific settings — ground material, grass particle system
    ground_material = LOCATION[render["location"]]["ground_material"]
    grass_system    = LOCATION[render["location"]]["grass_system"]

    # pull the full weather data block — internal_blender.py reads this directly
    weather_data = WEATHER[render["weather"]]

    # build the top level manifest dict — everything internal_blender.py needs to know
    manifest = {
        "render_id":       render["id"],        # which render job this belongs to
        "sky":             render["sky"],        # sky type string e.g. "clear"
        "weather":         render["weather"],    # weather type string e.g. "snow"
        "terrain":         render["terrain"],    # terrain type string e.g. "mountainous"
        "location":        render["location"],   # location type string e.g. "farmland"
        "hdri":            chosen_hdri,          # exact HDRI filename to load
        "ground_material": ground_material,      # Blender material name for the ground mesh
        "grass_system":    grass_system,         # Blender hair particle system name to enable
        "terrain_mesh":    terrain_mesh,         # Blender object name to duplicate from hidden collection
        "terrain_scale":   terrain_scale,        # randomised scale to apply to terrain mesh
        "weather_data":    weather_data,         # full weather block — fog, wind, wetness, particles
        "assets":          []                    # populated below — one entry per placed asset
    }

    # iterate every asset type and every pointer in that type's list
    for asset_type, pointer_list in pointers.items():
        for p in pointer_list:

            # convert each Pointer object into a plain dict — JSON cannot serialise objects directly
            manifest["assets"].append({
                "asset_name": p.asset_name,   # Blender object name to duplicate
                "asset_type": p.asset_type,   # type label e.g. "tree" — for internal_blender routing
                "x":          p.x,            # world X position in the 400x400 grid
                "y":          p.y,            # world Y position in the 400x400 grid
                "z":          p.z,            # always 0.0 — Blender resolves actual height via shrinkwrap
                "scale":      p.scale,        # uniform scale to apply
                "rotation":   p.rotation,     # Y axis rotation in degrees
            })

    # build the output path — scene_manifest.json sits inside the render's output folder
    manifest_path = output_dir / "scene_manifest.json"

    try:
        # create the output directory if it doesn't exist yet
        output_dir.mkdir(parents=True, exist_ok=True)

        # write the manifest to disk with readable indentation
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        log.info("Manifest written to %s", manifest_path)
        return ("OK", manifest_path)     # signal success + path back to derg.py

    except Exception as e:
        log.error("Failed to write manifest: %s", e)
        return ("FAIL", None)            # signal failure — derg.py will mark render as failed


def build_scene(render: dict[str, Any]) -> tuple[str, Any]:
    output_dir = Path("outputs") / f"render_{render['id']:03d}"
    asset_amounts = calculate_assets(render)
    pointers = pointer_generator(asset_amounts, render["location"])
    pointers = populator(pointers)
    return write_manifest(render, pointers, output_dir)     
