# ── Axis Pools ────────────────────────────────────────────────────────────────
# Used by derg.py to resolve null fields in the session JSON

SKY_POOL      = ["clear", "overcast", "stormy", "dawn", "dusk", "night"] # Changes the HDRI and lighting used
WEATHER_POOL  = ["dry", "rain", "snow", "fog"]                            # Changes the material presentation and VFX
TERRAIN_POOL  = ["flat", "hilly", "mountainous", "valley"]                # Changes the background environment
LOCATION_POOL = ["farmland", "grassland", "desert", "arctic", "gravel", "dirt"] # Changes the nearby terrain presentation


# ── Sky ───────────────────────────────────────────────────────────────────────
# Controls lighting, HDRI, sun angle, ambient color temperature
# sun_intensity: strength of the sun lamp in Blender
# ambient_temp: color temperature in Kelvin

SKY = {
    "clear":    { "hdri": ["clear_01.hdr",    "clear_02.hdr",    "clear_03.hdr",    "clear_04.hdr",    "clear_05.hdr"],    "sun_intensity": 5.0, "ambient_temp": 6500 },
    "overcast": { "hdri": ["overcast_01.hdr", "overcast_02.hdr", "overcast_03.hdr", "overcast_04.hdr", "overcast_05.hdr"], "sun_intensity": 1.5, "ambient_temp": 5500 },
    "stormy":   { "hdri": ["stormy_01.hdr",   "stormy_02.hdr",   "stormy_03.hdr",   "stormy_04.hdr",   "stormy_05.hdr"],   "sun_intensity": 0.5, "ambient_temp": 4500 },
    "dawn":     { "hdri": ["dawn_01.hdr",     "dawn_02.hdr",     "dawn_03.hdr",     "dawn_04.hdr",     "dawn_05.hdr"],     "sun_intensity": 1.0, "ambient_temp": 3200 },
    "dusk":     { "hdri": ["dusk_01.hdr",     "dusk_02.hdr",     "dusk_03.hdr",     "dusk_04.hdr",     "dusk_05.hdr"],     "sun_intensity": 0.8, "ambient_temp": 3000 },
    "night":    { "hdri": ["night_01.hdr",    "night_02.hdr",    "night_03.hdr",    "night_04.hdr",    "night_05.hdr"],    "sun_intensity": 0.0, "ambient_temp": 2800 },
}


# ── Weather ───────────────────────────────────────────────────────────────────
# Controls precipitation, particles, surface wetness, wind
# Independent of sky — any weather can pair with any sky
#
# fog is split into two independent types:
#   ground_fog  — low lying volume at base of scene, handled as a volume object in Blender
#   atmospheric — distant depth haze affecting backdrop visibility, handled via world shader
#
# precipitation:   whether a particle system is active
# wetness:         float 0.0-1.0, drives surface wetness shader parameter
# wind:            float 0.0-1.0, drives wind strength for foliage and particles
# particle_system: name of particle system object in DergScene.blend, None if unused

WEATHER = {
    "dry": {
        "precipitation":   False,
        "particle_system": None,
        "wind":            0.2,
        "wetness":         0.0,
        "ground_fog":      { "enabled": False, "density": 0.0,  "height":   0.0  },
        "atmospheric":     { "enabled": False, "density": 0.0,  "distance": 0.0  },
    },
    "rain": {
        "precipitation":   True,
        "particle_system": "PS_Rain",
        "wind":            0.6,
        "wetness":         1.0,
        "ground_fog":      { "enabled": False, "density": 0.0,  "height":   0.0  },
        "atmospheric":     { "enabled": True,  "density": 0.05, "distance": 60.0 },
    },
    "snow": {
        "precipitation":   True,
        "particle_system": "PS_Snow",
        "wind":            0.3,
        "wetness":         0.0,
        "ground_fog":      { "enabled": False, "density": 0.0,  "height":   0.0  },
        "atmospheric":     { "enabled": True,  "density": 0.08, "distance": 50.0 },
    },
    "fog": {
        "precipitation":   False,
        "particle_system": "PS_Fog",
        "wind":            0.1,
        "wetness":         0.4,
        "ground_fog":      { "enabled": True,  "density": 0.3,  "height":   2.0  },
        "atmospheric":     { "enabled": True,  "density": 0.2,  "distance": 40.0 },
    },
}


# ── Terrain ───────────────────────────────────────────────────────────────────
# Controls the backdrop expanse — what you see in the distance
# Mesh names must match hidden collection objects in DergScene.blend
# scale_range: (min, max) applied randomly per render for subtle variation

TERRAIN = {
    "flat":        { "mesh": "TERRAIN_Flat_01",        "scale_range": (0.9, 1.1) },
    "hilly":       { "mesh": "TERRAIN_Hilly_01",       "scale_range": (0.9, 1.1) },
    "mountainous": { "mesh": "TERRAIN_Mountainous_01", "scale_range": (0.8, 1.2) },
    "valley":      { "mesh": "TERRAIN_Valley_01",      "scale_range": (0.9, 1.1) },
}


# ── Location ──────────────────────────────────────────────────────────────────
# Controls the immediate launch site feel
# ground_material: applied to launch site ground mesh, must match a key in MATERIALS
# allowed_tags:    asset tags builder.py may query from ASSETS for this location
# grass_system:    name of the hair particle system in DergScene.blend for ground cover
# asset_rules:     min/max count per asset type — clustering behaviour lives in builder.py

LOCATION = {
    "farmland": {
        "ground_material": "MAT_Dirt_01",
        "allowed_tags":    ["farmland", "universal"],
        "grass_system":    "GS_Dirt_Sparse",
        "asset_rules": {
            "structure": { "min": 1,  "max": 4  },
            "tree":      { "min": 2,  "max": 8  },
            "rock":      { "min": 0,  "max": 6  },
            "foliage":   { "min": 5,  "max": 15 },
        }
    },
    "grassland": {
        "ground_material": "MAT_Grass_01",
        "allowed_tags":    ["grassland", "universal"],
        "grass_system":    "GS_Grass_Dense",
        "asset_rules": {
            "structure": { "min": 1,  "max": 3  },
            "tree":      { "min": 5,  "max": 20 },
            "rock":      { "min": 2,  "max": 10 },
            "foliage":   { "min": 10, "max": 30 },
        }
    },
    "desert": {
        "ground_material": "MAT_Sand_01",
        "allowed_tags":    ["desert", "universal"],
        "grass_system":    "GS_Sand_Sparse",
        "asset_rules": {
            "structure": { "min": 0,  "max": 1  },
            "tree":      { "min": 0,  "max": 3  },
            "rock":      { "min": 10, "max": 30 },
            "foliage":   { "min": 2,  "max": 10 },
        }
    },
    "arctic": {
        "ground_material": "MAT_Snow_01",
        "allowed_tags":    ["arctic", "universal"],
        "grass_system":    "GS_Snow_Bare",
        "asset_rules": {
            "structure": { "min": 0,  "max": 2  },
            "tree":      { "min": 0,  "max": 6  },
            "rock":      { "min": 5,  "max": 20 },
            "foliage":   { "min": 0,  "max": 4  },
        }
    },
    "gravel": {
        "ground_material": "MAT_Gravel_01",
        "allowed_tags":    ["gravel", "universal"],
        "grass_system":    "GS_Gravel_Bare",
        "asset_rules": {
            "structure": { "min": 0,  "max": 2  },
            "tree":      { "min": 0,  "max": 4  },
            "rock":      { "min": 8,  "max": 25 },
            "foliage":   { "min": 2,  "max": 8  },
        }
    },
    "dirt": {
        "ground_material": "MAT_Dirt_02",
        "allowed_tags":    ["dirt", "universal"],
        "grass_system":    "GS_Dirt_Sparse",
        "asset_rules": {
            "structure": { "min": 0,  "max": 3  },
            "tree":      { "min": 3,  "max": 15 },
            "rock":      { "min": 3,  "max": 12 },
            "foliage":   { "min": 5,  "max": 20 },
        }
    },
}


# ── Materials ─────────────────────────────────────────────────────────────────
# Blender material data-block names as they exist in DergScene.blend

MATERIALS = {
    "dirt":   "MAT_Dirt_01",
    "dirt_2": "MAT_Dirt_02",
    "grass":  "MAT_Grass_01",
    "snow":   "MAT_Snow_01",
    "rock":   "MAT_Rock_01",
    "sand":   "MAT_Sand_01",
    "gravel": "MAT_Gravel_01",
}


# ── Asset Registry ────────────────────────────────────────────────────────────
# Dict of lists of dicts — type is the top level key, no type tag needed
# Each asset carries: name (must match object in DergScene.blend) and location tags
# builder.py queries by type first, then filters by location allowed_tags
# update_assets.py syncs names automatically from DergScene.blend
# NOTE: names below are dummies for testing — replace with real Blender object names

ASSETS: dict[str, list[dict]] = {

    "tree": [
        { "name": "TREE_Oak_01",   "tags": ["grassland", "farmland", "universal"] },
        { "name": "TREE_Oak_02",   "tags": ["grassland", "farmland", "universal"] },
        { "name": "TREE_Pine_01",  "tags": ["arctic",    "universal"] },
        { "name": "TREE_Pine_02",  "tags": ["arctic",    "universal"] },
        { "name": "TREE_Dead_01",  "tags": ["desert",    "universal"] },
    ],

    "rock": [
        { "name": "ROCK_Small_01", "tags": ["universal"] },
        { "name": "ROCK_Small_02", "tags": ["universal"] },
        { "name": "ROCK_Large_01", "tags": ["universal"] },
        { "name": "ROCK_Large_02", "tags": ["universal"] },
        { "name": "ROCK_Flat_01",  "tags": ["universal"] },
    ],

    "structure": [
        { "name": "STRUCT_Shed_01",   "tags": ["farmland"] },
        { "name": "STRUCT_Shed_02",   "tags": ["farmland"] },
        { "name": "STRUCT_Barn_01",   "tags": ["farmland"] },
        { "name": "STRUCT_House_01",  "tags": ["grassland"] },
        { "name": "STRUCT_House_02",  "tags": ["grassland"] },
    ],

    "foliage": [
        { "name": "FOLIAGE_Bush_01",   "tags": ["grassland", "universal"] },
        { "name": "FOLIAGE_Bush_02",   "tags": ["grassland", "universal"] },
        { "name": "FOLIAGE_Weed_01",   "tags": ["farmland",  "universal"] },
        { "name": "FOLIAGE_Weed_02",   "tags": ["farmland",  "universal"] },
        { "name": "FOLIAGE_Cactus_01", "tags": ["desert"] },
    ],

    "vfx": [
        { "name": "VFX_Dust_01",  "tags": ["desert",    "universal"] },
        { "name": "VFX_Spark_01", "tags": ["universal"] },
    ],

}


# ── Cameras ───────────────────────────────────────────────────────────────────
# TODO: add camera presets once real camera specs are confirmed
# Each preset must match actual hardware focal length and sensor size
# builder.py selects one per render, internal_blender.py applies it

CAMERAS = {

}