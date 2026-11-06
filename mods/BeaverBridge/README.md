# Beaver Bridge

A Timberborn mod that exposes the running game over local HTTP, so an external agent can read and control a colony. Version 0.9.0 is a from-scratch rebuild of the 0.8.0 mod whose source was lost; it compiles against game 1.1.2.7 and **has not yet been run in the game**. See [Status](#status).

## Build and install

Requires the .NET SDK (10.x used here; 8+ should work) and an installed copy of Timberborn. Nothing is downloaded: the project has no package references and references the game's own assemblies in place.

```sh
mods/BeaverBridge/install.sh            # build, back up the old DLL, copy, verify by checksum
```

Or by hand:

```sh
cd mods/BeaverBridge/src
dotnet build -c Release                  # -p:TimberbornManaged=/path/to/Managed if not the Steam default
cp bin/Release/netstandard2.1/Code.dll ../manifest.json "$HOME/Documents/Timberborn/Mods/BeaverBridge/"
```

Quit the game before installing. Mods bind at process start and there is no hot reload. The game logs `[BeaverBridge] v0.9.0 listening on http://127.0.0.1:7777/` in `Player.log` when the mod loads into a game context. Set `BEAVER_BRIDGE_PORT` to change the port.

## Use

```sh
curl -s localhost:7777/ping                      # {"version":"0.9.0","pumpRunning":true}
curl -s localhost:7777/state
curl -s 'localhost:7777/buildings?filter=Warehouse'
curl -s localhost:7777/workplaces
curl -s -d '{"speed":3}' localhost:7777/speed
curl -s -d '{"prefab":"Lodge","x":40,"y":52,"z":11,"orientation":"auto"}' localhost:7777/place
curl -s -d '{"x":40,"y":52,"z":11,"priority":"High"}' localhost:7777/priority
curl -s -d '{"from":"North","to":"South","adults":5}' localhost:7777/migrate
curl -s -d '{"name":"bridge-checkpoint"}' localhost:7777/save
```

`GET /` lists every endpoint. The full endpoint table, with request bodies, is in [docs/modding-notes.md](../../docs/modding-notes.md).

`pumpRunning` from `/ping` is answered on the socket thread and only says whether the main-thread pump has run at least once. If it is `false`, the mod loaded but no game is bound, which is what a stale build against a newer game looks like. Every other request waits up to five seconds for the main thread and returns 504 if nothing answers.

## How it works

Game state may only be touched on Unity's main thread. A `TcpListener` on a background thread parses each request, queues a job, and blocks on it. `BridgeServer.UpdateSingleton` runs once per rendered frame, including while paused, drains the queue, and signals each job. `GameApi` holds the endpoints and is injected with the game's own services through Bindito, the game's DI container, from a `[Context("Game")]` configurator.

Writes go through the same services the UI uses: `ConstructionFactory` for placing, `EntityService` for deleting, `WorkplacePriority` and `BuilderPrioritizable` for priority, `MigrationService` for moving beavers, `GameSaver` for saving. Invalid placements throw inside the game and create nothing, so `/place` with `"orientation":"auto"` tries each rotation in turn and keeps nothing from a failed attempt. That is the fix for the 0.8.0 auto-orientation bug.

JSON and HTTP are hand-rolled in `Json.cs` and `Http.cs` to avoid depending on the game's bundled Newtonsoft or on BCL types missing from `netstandard2.1`. Both files have no game dependencies and are covered by a small test harness described in the repo's CI notes.

## Layout

```
manifest.json          mod manifest the game reads
install.sh             build + checksum-verified install
src/BeaverBridge.csproj
src/BridgeConfigurator.cs   DI registration
src/BridgeServer.cs         listener thread + main-thread job pump
src/GameApi.cs              every endpoint
src/Http.cs                 request parser, response writer
src/Json.cs                 writer and parser
```

## Status

| | |
|---|---|
| Compiles against 1.1.2.7 | yes, zero warnings |
| JSON and HTTP layers unit-tested | yes |
| Loaded in the game | **not yet** |
| Endpoints exercised in the game | **not yet** |

Expect runtime iteration: in the 0.8.0 build every API misuse compiled clean and failed at runtime. Things to verify first when the game is available, in order: the mod loads and logs its port; `/ping` reports `pumpRunning: true` after a game loads; `/state` returns; `/place` on a known-good tile; `/save` writes a file. The two 0.8.0 caveats to re-check are that `Accessible.ValidAccessible` may be false on unfinished buildings, so `/buildings` marks fresh construction sites unreachable, and that `/unreachable` is the reliable check after construction finishes.
