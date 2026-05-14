"""
internal_blender.py — Blender Executor
Runs inside Blender as an injected script via --python flag.
Reads scene_manifest.json, builds the scene, renders 3 stages,
writes bbox JSON per stage. Makes no decisions — executes only.

Communication back to derg.py is via Blender's existing log system.
Errors are logged via print() which Blender captures in its stdout.

Run via render_collector.py — never directly.
"""
import bpy
import bpy_extras.object_utils
import json
import os
import sys
import math
from pathlib import Path
from mathutils import Vector


# ── Stage definitions ─────────────────────────────────────────────────────────
# One continuous 12,000 frame animation split into 3 output files

STAGES = [
    { "name": "stage_1_prelaunch", "start": 1,  "end": 10 },
    { "name": "stage_2_launch",    "start": 11, "end": 20 },
    { "name": "stage_3_ascent",    "start": 21, "end": 30 },
]

ROCKET_OBJECT_NAME = "Rocket_Mesh"
ASSETS_COLLECTION  = "ASSETS_HIDDEN"
RENDER_COLLECTION  = "Collection"       # active scene collection assets get linked into


# ── Logging ───────────────────────────────────────────────────────────────────
# print() is used instead of logging — Blender captures stdout in its log system
# derg.py reads the blender log after subprocess exits

def log(level: str, msg: str) -> None:
    """Prints a formatted log line that Blender captures in its stdout."""
    print(f"[DERG:{level}] {msg}", flush=True)


# ── Manifest loading ──────────────────────────────────────────────────────────

def load_manifest() -> dict:
    """
    Reads the manifest path from the DERG_MANIFEST environment variable.
    This is how derg.py communicates the manifest path into Blender.
    """
    manifest_path = os.environ.get("DERG_MANIFEST")

    if not manifest_path:
        log("ERROR", "DERG_MANIFEST environment variable not set — aborting")
        sys.exit(1)

    path = Path(manifest_path)
    if not path.exists():
        log("ERROR", f"Manifest not found at {manifest_path} — aborting")
        sys.exit(1)

    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    log("INFO", f"Manifest loaded from {manifest_path}")
    return manifest


# ── Asset validation ──────────────────────────────────────────────────────────

def validate_assets(manifest: dict) -> bool:
    """
    Checks that every asset name in the manifest exists in ASSETS_HIDDEN.
    Logs warnings for missing assets but does not abort — missing assets
    are skipped during placement rather than crashing the whole render.
    Returns False if the hidden collection itself is missing.
    """
    if ASSETS_COLLECTION not in bpy.data.collections:
        log("ERROR", f"Hidden collection '{ASSETS_COLLECTION}' not found in DergScene.blend")
        return False

    hidden_names = {obj.name for obj in bpy.data.collections[ASSETS_COLLECTION].objects}

    for asset in manifest.get("assets", []):
        name = asset["asset_name"]
        if name not in hidden_names:
            log("WARN", f"Asset '{name}' not found in {ASSETS_COLLECTION} — will be skipped")

    log("INFO", "Asset validation complete")
    return True


# ── Scene clearing ────────────────────────────────────────────────────────────

def clear_placed_assets() -> None:
    """
    Removes all previously placed asset objects from the scene.
    Identifies placed objects by the custom property 'derg_placed' = True.
    Terrain mesh is also removed so it can be replaced fresh each run.
    Does not touch the rocket, cameras, or lights.
    """
    to_remove = [
        obj for obj in bpy.data.objects
        if obj.get("derg_placed") is True
    ]

    for obj in to_remove:
        bpy.data.objects.remove(obj, do_unlink=True)

    log("INFO", f"Cleared {len(to_remove)} previously placed objects")


# ── Asset duplication ─────────────────────────────────────────────────────────

def duplicate_asset(source_name: str, x: float, y: float, z: float,
                    scale: float, rotation: float) -> bpy.types.Object | None:
    """
    Duplicates a named object from ASSETS_HIDDEN into the active scene.
    Sets position, uniform scale, and Y-axis rotation.
    Tags the new object with derg_placed = True for cleanup on next run.
    Returns the new object, or None if the source wasn't found.
    """
    hidden = bpy.data.collections.get(ASSETS_COLLECTION)
    if not hidden:
        return None

    source = hidden.objects.get(source_name)
    if not source:
        log("WARN", f"Skipping '{source_name}' — not found in {ASSETS_COLLECTION}")
        return None

    # duplicate object and its mesh data
    new_obj      = source.copy()
    new_obj.data = source.data.copy()

    # tag so clear_placed_assets() can find and remove it next run
    new_obj["derg_placed"] = True

    # link into active scene collection
    bpy.data.collections[RENDER_COLLECTION].objects.link(new_obj)

    # set placement — z is always 0.0, shrinkwrap handles height
    new_obj.location = (x, y, z)
    new_obj.scale    = (scale, scale, scale)

    # rotation is Y-axis only (vertical axis in Blender Z-up)
    new_obj.rotation_euler = (0.0, 0.0, math.radians(rotation))

    # make visible for rendering
    new_obj.hide_render   = False
    new_obj.hide_viewport = False

    return new_obj


# ── Shrinkwrap ────────────────────────────────────────────────────────────────

def apply_shrinkwrap(obj: bpy.types.Object, terrain_obj: bpy.types.Object) -> None:
    """
    Adds a Shrinkwrap constraint to snap the object's Z position
    to the terrain surface. This replaces manual height lookup.
    Blender resolves the actual Z at render time.
    """
    constraint           = obj.constraints.new(type='SHRINKWRAP')
    constraint.target    = terrain_obj
    constraint.shrinkwrap_type = 'PROJECT'
    constraint.project_axis    = 'NEG_Z'    # project downward
    constraint.use_project_opposite = True  # also project upward if needed


# ── Scene setup functions ─────────────────────────────────────────────────────

def set_hdri(hdri_name: str) -> None:
    """
    Sets the world HDRI by loading the named file from the project's
    hdri/ folder and assigning it to the world shader node.
    """
    world = bpy.context.scene.world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links

    # find or create environment texture node
    env_node = nodes.get("Environment Texture")
    if not env_node:
        env_node      = nodes.new(type='ShaderNodeTexEnvironment')
        env_node.name = "Environment Texture"

    hdri_path = Path("hdri") / hdri_name

    if not hdri_path.exists():
        log("WARN", f"HDRI file not found: {hdri_path} — sky will be default")
        return

    env_node.image = bpy.data.images.load(str(hdri_path), check_existing=True)

    # ensure it's connected to the background node
    bg_node = nodes.get("Background")
    if bg_node and not env_node.outputs[0].links:
        links.new(env_node.outputs[0], bg_node.inputs[0])

    log("INFO", f"HDRI set to {hdri_name}")


def set_ground_material(material_name: str) -> None:
    """
    Applies the named material to the object called 'Ground_Mesh'.
    Material must already exist in DergScene.blend.
    """
    ground = bpy.data.objects.get("Ground_Mesh")
    if not ground:
        log("WARN", "Ground_Mesh not found — ground material not applied")
        return

    mat = bpy.data.materials.get(material_name)
    if not mat:
        log("WARN", f"Material '{material_name}' not found — ground material not applied")
        return

    if ground.data.materials:
        ground.data.materials[0] = mat
    else:
        ground.data.materials.append(mat)

    log("INFO", f"Ground material set to {material_name}")


def set_grass_system(system_name: str) -> None:
    """
    Enables the named hair particle system on Ground_Mesh.
    All other particle systems on Ground_Mesh are disabled.
    """
    ground = bpy.data.objects.get("Ground_Mesh")
    if not ground:
        log("WARN", "Ground_Mesh not found — grass system not applied")
        return

    found = False
    for mod in ground.modifiers:
        if mod.type == 'PARTICLE_SYSTEM':
            mod.show_render = (mod.particle_system.name == system_name)
            if mod.particle_system.name == system_name:
                found = True

    if not found:
        log("WARN", f"Grass system '{system_name}' not found on Ground_Mesh")
    else:
        log("INFO", f"Grass system set to {system_name}")


def place_terrain(terrain_mesh_name: str, terrain_scale: float) -> bpy.types.Object | None:
    """
    Duplicates the named terrain mesh from ASSETS_HIDDEN,
    places it at the origin, and applies the given scale.
    Returns the terrain object for use as shrinkwrap target.
    """
    terrain_obj = duplicate_asset(terrain_mesh_name, 0.0, 0.0, 0.0, terrain_scale, 0.0)
    if not terrain_obj:
        log("ERROR", f"Terrain mesh '{terrain_mesh_name}' could not be placed")
        return None

    log("INFO", f"Terrain placed: {terrain_mesh_name} at scale {terrain_scale}")
    return terrain_obj


def configure_weather(weather_data: dict) -> None:
    """
    Applies weather settings from the manifest weather_data block.
    Sets wind strength, wetness parameter, particle visibility,
    ground fog volume density, and atmospheric world shader haze.
    """
    wind    = weather_data.get("wind", 0.0)
    wetness = weather_data.get("wetness", 0.0)

    # ── wind ──────────────────────────────────────────────────────────────
    # drive wind via a Force Field object named 'Wind_Force' if it exists
    wind_obj = bpy.data.objects.get("Wind_Force")
    if wind_obj and wind_obj.field:
        wind_obj.field.strength = wind * 10.0   # scale 0-1 to Blender units

    # ── wetness ───────────────────────────────────────────────────────────
    # drive wetness via a custom property on Ground_Mesh read by its shader
    ground = bpy.data.objects.get("Ground_Mesh")
    if ground:
        ground["wetness"] = wetness

    # ── precipitation particle system ─────────────────────────────────────
    ps_name = weather_data.get("particle_system")
    if ps_name:
        ps_obj = bpy.data.objects.get(ps_name)
        if ps_obj:
            ps_obj.hide_render   = False
            ps_obj.hide_viewport = False
            log("INFO", f"Particle system enabled: {ps_name}")
        else:
            log("WARN", f"Particle system object '{ps_name}' not found in scene")

    # ── ground fog ────────────────────────────────────────────────────────
    fog_data = weather_data.get("ground_fog", {})
    fog_obj  = bpy.data.objects.get("Ground_Fog_Volume")
    if fog_obj:
        fog_obj.hide_render = not fog_data.get("enabled", False)
        mat = fog_obj.active_material
        if mat and mat.use_nodes:
            density_node = mat.node_tree.nodes.get("Principled Volume")
            if density_node:
                density_node.inputs["Density"].default_value = fog_data.get("density", 0.0)

    # ── atmospheric haze ──────────────────────────────────────────────────
    atm_data = weather_data.get("atmospheric", {})
    world    = bpy.context.scene.world
    if world and world.use_nodes and atm_data.get("enabled", False):
        atm_node = world.node_tree.nodes.get("Atmospheric_Haze")
        if atm_node:
            atm_node.inputs["Density"].default_value   = atm_data.get("density", 0.0)
            atm_node.inputs["Distance"].default_value  = atm_data.get("distance", 0.0)

    log("INFO", "Weather configured")


# ── Bounding box computation ──────────────────────────────────────────────────

def get_rocket_bbox_2d(scene: bpy.types.Scene, camera: bpy.types.Object,
                       frame: int) -> dict:
    """
    Projects the rocket's 3D world-space bounding box corners into
    2D normalised screen coordinates (0.0-1.0) for the given frame.

    Returns a dict with in_frame, x_min, y_min, x_max, y_max.
    Coordinates are normalised — (0,0) is bottom-left, (1,1) is top-right.
    If the rocket is not in frame, in_frame is False and coords are null.
    """
    rocket = bpy.data.objects.get(ROCKET_OBJECT_NAME)

    if not rocket:
        return { "frame": frame, "in_frame": False,
                 "x_min": None, "y_min": None,
                 "x_max": None, "y_max": None }

    # set scene to this frame so the rocket is at the right position
    scene.frame_set(frame)

    # get the 8 corners of the rocket's world-space bounding box
    bbox_corners = [rocket.matrix_world @ Vector(corner)
                    for corner in rocket.bound_box]

    # project each 3D corner into 2D normalised screen space
    render     = scene.render
    res_x      = render.resolution_x
    res_y      = render.resolution_y

    coords_2d = []
    for corner in bbox_corners:
        co = bpy_extras.object_utils.world_to_camera_view(scene, camera, corner)
        # co.x and co.y are normalised, co.z is depth (positive = in front of camera)
        if co.z > 0:                          # only include corners in front of camera
            coords_2d.append((co.x, co.y))

    if not coords_2d:
        return { "frame": frame, "in_frame": False,
                 "x_min": None, "y_min": None,
                 "x_max": None, "y_max": None }

    xs = [c[0] for c in coords_2d]
    ys = [c[1] for c in coords_2d]

    x_min = round(min(xs), 4)
    x_max = round(max(xs), 4)
    y_min = round(min(ys), 4)
    y_max = round(max(ys), 4)

    # check if the box is at least partially within the frame (0-1 range)
    in_frame = x_max > 0 and x_min < 1 and y_max > 0 and y_min < 1

    return {
        "frame":    frame,
        "in_frame": in_frame,
        "x_min":    max(0.0, x_min) if in_frame else None,
        "y_min":    max(0.0, y_min) if in_frame else None,
        "x_max":    min(1.0, x_max) if in_frame else None,
        "y_max":    min(1.0, y_max) if in_frame else None,
    }


# ── Rendering ─────────────────────────────────────────────────────────────────

def render_stage(stage: dict, output_dir: Path,
                 scene: bpy.types.Scene,
                 camera: bpy.types.Object) -> None:
    """
    Renders one stage as a PNG frame sequence and writes the bbox JSON.
    Frames land in output_dir/stage_name/####.png
    render_collector.py handles converting the sequence to mp4 via ffmpeg
    after Blender exits — this keeps Blender 5.0 compatible.
    """
    stage_name  = stage["name"]
    frame_start = stage["start"]
    frame_end   = stage["end"]

    log("INFO", f"Rendering {stage_name} (frames {frame_start}–{frame_end})")

    # ── create stage subfolder for PNG frames ─────────────────────────────
    # frames land at: outputs/render_001/stage_1_prelaunch/0001.png
    frames_dir = output_dir / stage_name
    frames_dir.mkdir(parents=True, exist_ok=True)

    # ── configure PNG output ──────────────────────────────────────────────
    scene.render.filepath = str(frames_dir) + "/"
    scene.render.image_settings.file_format      = 'PNG'
    scene.render.image_settings.color_mode       = 'RGB'
    scene.render.image_settings.compression      = 15    # 0-100, lower = faster write

    # ── set frame range ───────────────────────────────────────────────────
    scene.frame_start = frame_start
    scene.frame_end   = frame_end

    # ── compute bbox for every frame before rendering ─────────────────────
    log("INFO", f"Computing bbox for {stage_name}...")
    bbox_data = []
    for frame in range(frame_start, frame_end + 1):
        bbox_data.append(get_rocket_bbox_2d(scene, camera, frame))

    # write bbox JSON alongside the frames folder
    bbox_path = output_dir / f"{stage_name}_bbox.json"
    with open(bbox_path, "w", encoding="utf-8") as f:
        json.dump(bbox_data, f, indent=2)
    log("INFO", f"Bbox JSON written to {bbox_path}")

    # ── render PNG sequence ───────────────────────────────────────────────
    bpy.ops.render.render(animation=True)
    log("INFO", f"{stage_name} frames complete → {frames_dir}")


# ── Main execution ────────────────────────────────────────────────────────────

def main() -> None:
    """
    Full execution sequence — called once when Blender runs this script.
    Order matches the steps defined in the architecture documentation.
    """
    log("INFO", "internal_blender.py starting")

    # ── 1. load manifest ──────────────────────────────────────────────────
    manifest   = load_manifest()
    render_id  = manifest["render_id"]
    output_dir = Path("outputs") / f"render_{render_id:03d}"
    output_dir.mkdir(parents=True, exist_ok=True)

    scene  = bpy.context.scene
    camera = scene.camera

    if not camera:
        log("ERROR", "No active camera in DergScene.blend — aborting")
        sys.exit(1)

    # ── 2. validate assets ────────────────────────────────────────────────
    if not validate_assets(manifest):
        log("ERROR", "Asset validation failed — aborting")
        sys.exit(1)

    # ── 3. clear previous run's objects ───────────────────────────────────
    clear_placed_assets()

    # ── 4. place terrain ──────────────────────────────────────────────────
    terrain_obj = place_terrain(
        manifest["terrain_mesh"],
        manifest["terrain_scale"]
    )

    # ── 5. apply ground material ──────────────────────────────────────────
    set_ground_material(manifest["ground_material"])

    # ── 6. enable grass particle system ───────────────────────────────────
    set_grass_system(manifest["grass_system"])

    # ── 7. set HDRI ───────────────────────────────────────────────────────
    set_hdri(manifest["hdri"])

    # ── 8. configure weather ──────────────────────────────────────────────
    configure_weather(manifest["weather_data"])

    # ── 9. place all assets ───────────────────────────────────────────────
    placed_objects = []
    for asset in manifest.get("assets", []):
        obj = duplicate_asset(
            asset["asset_name"],
            asset["x"],
            asset["y"],
            asset["z"],
            asset["scale"],
            asset["rotation"],
        )
        if obj:
            # apply shrinkwrap if terrain was placed successfully
            if terrain_obj:
                apply_shrinkwrap(obj, terrain_obj)
            placed_objects.append(obj)

    log("INFO", f"Placed {len(placed_objects)} assets")

    # ── 10. render all 3 stages ───────────────────────────────────────────
    for stage in STAGES:
        render_stage(stage, output_dir, scene, camera)

    log("INFO", "All stages complete — exiting without saving")

    # exit without saving DergScene.blend
    bpy.ops.wm.quit_blender()


main()