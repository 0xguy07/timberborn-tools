# timberborn-tools

[![CI](https://github.com/0xguy07/timberborn-tools/actions/workflows/ci.yml/badge.svg)](https://github.com/0xguy07/timberborn-tools/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/0xguy07/timberborn-tools)](https://github.com/0xguy07/timberborn-tools/releases/latest)

Tools and notes for [Timberborn](https://mechanistry.com/timberborn), built by reading the game's files and assemblies rather than guides.

- **`maptools/`** writes and validates `.timber` map files from plain Python. Includes a generator for *Practice Valley*, a beginner-friendly 128x128 map, and a validator that catches the silent ways a hand-built map dies on load.
- **`bridge/`** is a read-only [MCP](https://modelcontextprotocol.io) server over your saves. Ask a model about districts, food, water, power and logistics in a running colony. Stdlib Python only.
- **`mods/BeaverBridge/`** is a C# mod that exposes the live game over local HTTP. Builds offline against the installed game.
- **`tools/`** holds an API dump tool for the game's assemblies and a script to sync a local copy of them.
- **`docs/`** holds the reverse-engineered `.timber` format, mechanics measured from a 600-day colony, and the mod's build notes.
- **`maps/`** ships the generated *Practice Valley* map, ready to drop into your `Maps` folder.

Verified against game version 1.1.2.4 (bridge) and 1.0.13.1 (map tools). Nothing here is affiliated with Mechanistry.

Full documentation is on the [wiki](https://github.com/0xguy07/timberborn-tools/wiki): getting started, the map format, design rules, every validator check, the save bridge, mechanics notes, the modding guide, and the roadmap.

## Map tools

```sh
pip install Pillow                      # only for the generator's thumbnail
python3 maptools/practice_valley_generator.py "maps/Practice Valley.timber"
python3 maptools/validate_map.py "maps/Practice Valley.timber"
python3 maptools/measure_arable.py "maps/Practice Valley.timber"
```

`validate_map.py` runs about fifty checks: terrain depth and gaps, water sources sitting in channels, every channel draining to an edge, no closed basins, reservoir volume in drought, arable fraction, a clear level build zone at spawn, caches within capacity and storage type, and a walkability flood-fill from spawn. It prints `PASS`/`FAIL` per check and exits non-zero on any failure.

Two optional inputs make it stricter:

- `--blueprints Blueprints.zip` (or `TIMBERBORN_BLUEPRINTS`) checks terrain height against the game's own `MapSizeSpec`. The Steam install path is tried automatically on macOS, Linux and Windows.
- `--reference some-shipped-map.timber` (or `TIMBERBORN_REFERENCE_MAP`) compares the JSON shape of your map against one the game ships with, such as Plains. Shipped maps are game content, so copy one out of your install; do not commit it.

`measure_arable.py` reports what fraction of land is irrigated and prints a block map of the dry ground. The design rules behind the numbers are in [docs/timber-map-format.md](docs/timber-map-format.md).

## Save bridge (MCP server)

```sh
python3 bridge/timberborn_mcp.py --selftest | less      # works with no client
claude mcp add timberborn -s user -- python3 "$PWD/bridge/timberborn_mcp.py"
```

Saves are read from `~/Documents/Timberborn` or the platform save folder; set `TIMBERBORN_DIR` to override. The bridge never writes to a save. Tool list, and what is exact versus approximated, in [bridge/README.md](bridge/README.md).

## Beaver Bridge mod

`mods/BeaverBridge/` is a C# mod that runs an HTTP API inside the game: read districts, housing, inventories, workplaces and reachability; place and demolish buildings, set priorities and worker counts, migrate beavers, move the camera, save. It builds offline against the installed game's assemblies and installs with one script. Version 0.9.0 is a rebuild of the lost 0.8.0 source, compiled against 1.1.2.7 but not yet run in the game. See [mods/BeaverBridge/README.md](mods/BeaverBridge/README.md).

```sh
mods/BeaverBridge/install.sh
```

## Tools

- **`tools/apidump`** prints the public API of any .NET assembly as greppable text, using only the reflection-metadata library in the runtime. Point it at the game's `Managed` folder and you get 658 files you can grep for a signature, or diff between game versions.

  ```sh
  dotnet run --project tools/apidump -- --out /tmp/api "$HOME/Library/Application Support/Steam/steamapps/common/Timberborn/Timberborn.app/Contents/Resources/Data/Managed"
  grep -A20 "class Timberborn.WorkSystem.Workplace " /tmp/api/Timberborn.WorkSystem.txt
  ```

- **`tools/sync-gamerefs.sh`** refreshes a local copy of the game's assemblies and records the game version, so a mod is never built against a stale copy by accident.

## Docs

| File | What it is |
|---|---|
| [docs/timber-map-format.md](docs/timber-map-format.md) | The `.timber` zip layout, voxel and water array indexing, entity shape, starting-supply caches, and the terrain rules learned by playing generated maps |
| [docs/mechanics-notes.md](docs/mechanics-notes.md) | Building footprints and entrance offsets, stacking rules from the game's enums, districts and labour, wellbeing multipliers |
| [docs/modding-notes.md](docs/modding-notes.md) | How to build a Timberborn mod on macOS without Steam Workshop, read the API by reflection, and keep game access on the main thread |

## Contributing

Issues and pull requests are welcome, especially validator checks for map failures you have hit, and bridge reports for questions the save can answer. Keep game binaries, saves and shipped maps out of the repo; `.gitignore` already refuses the obvious ones.

## Security

Nothing here makes a network request. The save bridge is read-only, the mod listens on loopback only and refuses requests a browser could send, and the repository ships no binaries. What each part can and cannot touch, and how to report a problem privately, is in [SECURITY.md](SECURITY.md).

## License

MIT. See [LICENSE](LICENSE).
