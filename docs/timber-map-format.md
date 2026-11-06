# The .timber map format, and how Practice Valley is built

`maptools/practice_valley_generator.py` builds `maps/Practice Valley.timber` from scratch.
`maptools/validate_map.py` re-checks a map for cliffs, ungrounded objects, broken water
flow, and blocked spawn tiles.

    python3 maptools/practice_valley_generator.py "maps/Practice Valley.timber" && python3 maptools/validate_map.py "maps/Practice Valley.timber"

## .timber file format (game version 1.0.13.1)

A `.timber` is a plain zip holding four members:

    map_metadata.json   {"Width","Height","MapNameLocKey","MapDescription",...}
                        Leave the loc keys empty on a user map -- the map list
                        falls back to the file name.
    map_thumbnail.jpg   preview shown in the map picker
    version.txt         must match world.json's GameVersion
    world.json          {"GameVersion","Timestamp","Singletons","Entities"}

### Terrain

`Singletons.TerrainMap.Voxels.Array` is a space-separated string of `0`/`1`,
indexed **`z * Width * Height + y * Width + x`**. A column must be solid from
z=0 upward with no gaps.

**The vertical size is global, not per-map, and is NOT inferred from the array
length.** It comes from `Blueprints.zip`
`Configurations/MapSize.blueprint.json` -> `MapSizeSpec.MaxGameTerrainHeight`
(22), plus one: **23 slots per column for every map, whatever its width and
height**. `map_metadata.json` carries only `Width` and `Height`; there is no
depth field anywhere.

Getting this wrong is a silent killer. The game reads the metadata, starts the
new game, then throws `IndexOutOfRangeException` in
`MapIndexService.Unpack3D` from `TerrainMap.Load()` and dies with no in-game
error message -- the trace only appears in
`~/Library/Logs/Mechanistry/Timberborn/Player.log`. Terrain itself should stay
at or below `MaxMapEditorTerrainHeight` (16).

`Timestamp` is `"%Y-%m-%d %H:%M:%S"` with no trailing `Z`.

### Water and soil

`WaterMapNew`, `WaterEvaporationMap`, `SoilMoistureSimulator` and
`SoilContaminationSimulator` all use arrays of `Width * Height * 2`
(two stacked water levels), indexed `level * Width * Height + y * Width + x`.
Simulation state may be left at defaults (`0`, or `1` for evaporation
modifiers) -- the game fills the river in from the water sources on load.

### Entities

    {"Id": <uuid4>, "Template": <name>, "Components": {...}}

`BlockObject.Coordinates.Z` is the **first air voxel**, i.e. it equals the
column's solid height. Optional `BlockObject.Orientation` is
`Cw90`/`Cw180`/`Cw270` (omit for 0). Omitted components fall back to the
template's defaults, so entities can be written minimally.

Valid template names live in the game install under
`Timberborn.app/Contents/Resources/Data/StreamingAssets/Modding/Blueprints.zip`
(`NaturalResources/`, `MapEditor/`). Note the folder name is not always the
template name -- e.g. `Bushes/Blueberry` -> `BlueberryBush`.

Cut yields are fixed per species: Birch 1 log, Pine 2, Oak 8.
`RuinColumnH<N>` yields `N * 15` ScrapMetal.

### Design notes for this map

Plain datum 6, river bed 4, bank terrace 5, reservoir floor 1. Terraces keep
every bank a single step so beavers reach water without construction. The
reservoir floor sits 3 below the inlet sill, so ~650 blocks of water stay
trapped when the sources shut off during a drought.

## Starting supplies

Maps cannot change the faction's starting goods. The only map-level lever is the
`Reserve*` caches, and their blueprints have `PlaceFinished: true` with the
`BuildingCost` (10 ScrapMetal) already sitting in the serialized
`Inventory:ConstructionSite` — so they cost the player nothing.

Capacity is hard-capped per building by `StockpileSpec.MaxCapacity`, so more
goods means more buildings, not bigger numbers:

    ReserveWarehouse  2x2  cap 200  Box goods       (Berries, Gear, Bread, ...)
    ReserveTank       2x2  cap 300  Liquid goods    (Water, Badwater, ...)
    ReservePile       2x2  cap 160  Pileable goods  (Log, Plank, Dirt, ScrapMetal, ...)

Exceeding the cap or putting a good in the wrong storage type is invalid.
`validate_map.py` checks both.

Edit the `RESERVES` table in the generator to change the starting stock. The
depot pads are claimed before trees and ruins are scattered, so raising the
counts just consumes more pads from the same grid west of spawn; the script
asserts if it runs out.

## Two design rules learned the hard way (both from actually playing the map)

**1. A flat riverbed does not flow.** Water needs a downhill gradient or it just
puddles near the sources. The valley datum now slopes from 12 in the north to 6
in the south, putting the riverbed at 10 at the sources and 4 at the outlet --
about one step every 21 tiles. `validate_map.py` asserts the centreline bed
never rises going downstream and drops at least 5 overall.

**2. Nothing may stand in a building's access tiles.** All three `Reserve*`
buildings declare `BlockObjectSpec.Entrance` at local `(1, -1)`, i.e. a tile
*outside* the 2x2 footprint. Trees and bushes packed into the 1-tile lanes of
the old depot grid were rejected on load with

    Can't validate loaded BlockObject Birch(Clone) at (x, y, z).
    It's not backward compatible. Deleting it.

Non-overlapping footprints are not sufficient. The depot now uses a 5-tile grid
pitch (2x2 building + 3 clear tiles) on a levelled yard with the whole rectangle
kept free of vegetation, which also makes it far easier to run paths through.
`validate_map.py` asserts no vegetation touches a cache and that every cache has
a fully clear perimeter.

### Bank generation

Bank heights are not a fixed terrace constant. They come from a cone that rises
one level per tile away from every channel tile; final height is the minimum of
that cone and the open-land field. Both fields are 1-Lipschitz, so their minimum
is too -- which is what guarantees no 2-block cliffs anywhere, including where
the valley gradient steps down. Use `math.floor(v + 0.5)`, not `round()`, which
banks to even and can open a 2-block step.

## Arable land is set by water spread, not by flat ground

Measured from the shipped Plains map's own serialised `MoistureLevels` against
its terrain and water depth — the fraction of land tiles that are moist, by
height above the waterline and distance to water:

    rise  d1    d2    d4    d6    d8    d10
      0   100%  100%  100%  100%  100%  100%
      1   100%  100%  100%  100%  100%  100%
      2   100%  100%  100%  100%   97%   83%
      3   100%  100%  100%   14%    8%    8%
      4     0%    0%    0%    0%    0%    0%

So land 0–2 levels above the waterline is irrigated out to 10+ tiles, 3 levels
only within about 4, and **4+ levels above the waterline is permanently dry**.
This matches `SoilMoistureSimulatorSpec.VerticalSpreadCostMultiplier: 6` against
`MaxClusterSaturation: 8` — one level of rise costs six tiles of range.

The practical consequence: a single straight river irrigates a band roughly 20
tiles wide and nothing else. Version 2 of this map was 25% arable. Spreading the
same water as a braided network of tributaries took it to 67% without adding
flat ground. `measure_arable.py` reports the figure and a block map of where the
dry ground still is.

Narrow channels are better than wide ones: irrigation reach is measured in
distance from water, so slimming the network costs almost no arable land, frees
up buildable ground, and leaves spans narrow enough to dam cheaply.

## Two traps in the terrain generator

**Reserve the settlement footprint BEFORE carving.** Carving a dense network
first and hunting for a clear square afterwards fails outright — at 5,700 water
tiles there was no clear 24x24 anywhere on the map. Tributaries that would cross
a reserved zone are rerouted (control point and junction row both move), not
dropped; dropping one costs a whole corner its irrigation.

**Never hard-stamp a level plateau.** Its rim becomes a 2-block cliff. Clamp the
terrain between `LEVEL - d` and `LEVEL + d`, where `d` is distance to the zone.
Both bounds are 1-Lipschitz, as is the water cone, so the result is too. An
iterative raise/lower "feather" pass does NOT work — the two rules fight and it
oscillates instead of converging.

**A basin with a water source and no outlet fills forever.** The second
reservoir is centred on an already-carved tributary rather than in open ground.
`validate_map.py` asserts every channel tile can reach a map edge.

Do not assert a strictly monotonic riverbed either: pools and reservoirs dip
below the trend on purpose. Assert instead that a through-channel exists at the
designed bed in every row, and that the designed bed descends.
