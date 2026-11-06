# Timberborn bridge

An MCP server that reads Timberborn `.timber` saves and reports on districts,
food and water, power and logistics. Stdlib Python 3 only — nothing to install.

Verified against game version `1.1.2.4` (Folktails, 256x256 map).

## Install

```sh
claude mcp add timberborn -s user -- python3 "/path/to/timberborn-tools/bridge/timberborn_mcp.py"
```

For the Claude desktop app, add the same command to its MCP server settings.
Local MCP servers configured there are also reachable from cloud sessions that
are linked to this Mac.

Check it works without any client:

```sh
python3 bridge/timberborn_mcp.py --selftest | less
```

Saves are read from `~/Documents/Timberborn/Saves`. Override with
`TIMBERBORN_DIR`. Nothing is ever written to a save — the bridge is read-only.

## Tools

| tool | what it answers |
|---|---|
| `list_saves` | which saves exist, newest first |
| `overview` | cycle, weather, population, districts, drought record |
| `district_report` | population, housing, open jobs, needs, goods flow per district |
| `food_water_report` | stock, real production/consumption rates, days of buffer, drought exposure |
| `water_report` | stored volume, contamination, sources, floodgates, dams |
| `power_report` | generators, transmission, and which buildings actually ran short |
| `logistics_report` | hauling posts, storage allocation, workplaces far from storage, import/export policy |
| `workplace_report` | every workplace ranked by yesterday's productivity |
| `construction_report` | unfinished builds, materials delivered, builder staffing |
| `find_buildings` | locate anything by template or name |
| `good_history` | day-by-day stock/production/consumption for one good |
| `raw` | walk the save's singleton JSON by dotted path |

Every tool takes an optional `save` (name, partial name, or path) and
`settlement`. With neither, the most recently modified save is used — so after
an autosave, just ask again.

## What is exact and what is not

Exact, read straight from the save:

- population, ages, assigned district, jobs and homes
- desired vs. assigned workers per building
- need satisfaction per beaver
- per-district and settlement-wide production, consumption, stock and capacity
  per good, sampled daily by the game itself
- workplace productivity (work done vs. work possible, hour by hour)
- water depth and contamination per map column, water source strength,
  floodgate heights
- drought and badtide history

Approximate, and labelled as such in the output:

- **District of a building.** The game decides district membership by path
  connectivity, which the save does not store. Buildings with assigned workers
  or dwellers are attributed exactly (citizens carry their district); everything
  else falls back to the nearest district center.
- **Distances.** Manhattan on the grid with height weighted double, not walked
  path length.
- **Power.** The save does not contain the power network or per-building demand,
  so there is no grid-level balance. Generator counts are exact; horsepower
  figures are nominal wiki ratings. The productivity table is the real evidence
  of a starved building.
- **Housing capacity.** Derived from the save (most dwellers ever seen in that
  building type), floored by a small table in `tb_specs.py`.

## Layout

    timberborn_mcp.py   MCP server (stdio JSON-RPC, no dependencies)
    tb_save.py          zip + JSON loading, entity indexing, map decoding
    tb_reports.py       the reports
    tb_specs.py         the handful of constants the save does not contain

Save format notes, confirmed empirically against entity coordinates:

    terrain voxel  index = z*X*Y + y*X + x            value 0/1
    water column   index = level*X*Y + y*X + x        "depth:contamination:?:floorZ:prevDepth"
