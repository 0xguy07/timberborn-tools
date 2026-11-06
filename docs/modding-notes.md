# Beaver Bridge — build notes

A Timberborn mod that exposes the running game over local HTTP so an external
agent can read and control a colony. Written against game version **1.1.2.4**
(Unity 6000.5.5f1, Mono, macOS Steam build).

---

## Why it exists

The purpose-built mod for this (Timberbot API) is broken on 1.1.x: its HTTP
listener answers `/ping` but every endpoint touching the simulation times out.
That failure signature — listener alive, game data dead — is what a mod looks
like when its game-side bindings never attach after a version bump.

Building our own turned out to be a smaller job than patching it.

---

## Architecture

The single non-obvious constraint: **game state may only be touched on Unity's
main thread.** A socket listener runs on a background thread, so it cannot read
the simulation directly.

```
TcpListener (background thread)
      │  enqueue Job + ManualResetEventSlim
      ▼
ConcurrentQueue<Job>
      ▼
IUpdatableSingleton.UpdateSingleton()   ← main thread, once per FRAME
      │  execute, fill Job.Result, signal
      ▼
socket thread wakes, writes HTTP response
```

**Use `IUpdatableSingleton`, not a tick hook.** `UpdateSingleton` fires every
rendered frame, so the bridge answers even while the game is paused. A
simulation-tick hook would starve whenever the player pauses — a plausible
explanation for Timberbot's permanent 2-second timeouts.

`/ping` is answered directly from the socket thread and reports `pumpRunning`,
a flag the main-thread pump sets. That single boolean distinguishes "mod not
loaded" from "mod loaded but not bound" without guessing from timeouts.

### Registration

```csharp
[Context("Game")]                       // "MainMenu" | "Game" | "MapEditor" | "Bootstrapper"
public class BridgeConfigurator : Configurator {
  protected override void Configure() {
    Bind<BridgeServer>().AsSingleton();
  }
}
```

Lifecycle interfaces the container honours: `ILoadableSingleton.Load()`,
`IUpdatableSingleton.UpdateSingleton()`, `ILateUpdatableSingleton`,
`IPostLoadableSingleton`, `IUnloadableSingleton`.

### Why TcpListener and not HttpListener

`System.Net.HttpListener` is not in `netstandard2.1`. Rather than fight BCL
profiles (and with NuGet unavailable), the bridge speaks minimal HTTP/1.1 over
a raw `TcpListener` in about 60 lines. It also hand-rolls JSON read and write,
avoiding a dependency on the game's bundled Newtonsoft.

---

## Toolchain

```
Mod layout:  ~/Documents/Timberborn/Mods/<Name>/
                 manifest.json   { Name, Version, Id, MinimumGameVersion }
                 Code.dll
```

- Target `netstandard2.1`, assembly name **`Code`**
- Reference the game's own DLLs from
  `…/Timberborn.app/Contents/Resources/Data/Managed` with `<Private>false</Private>`
- Build offline: a `nuget.config` with `<packageSources><clear /></packageSources>`
  lets `dotnet build` restore with no network
- No Steam, no Workshop. Dropping the folder in `Mods/` is the whole install.

### Reading the API without documentation

The wiki is thin. The assemblies are not. A ~120-line `System.Reflection.Metadata`
dumper (no NuGet needed — it ships in the .NET runtime) lists every public type,
base type, interface and member signature in any assembly. Set it to include
protected members to find things like `Configurator.Configure()`.

This is the single highest-leverage tool in the project: it turns "what does the
API look like in 1.1.2.4" from guesswork into a grep.

---

## Hard-won gotchas

**`GetComponent<T>()` throws on multiples.** District centers carry several
`IPrioritizable` components. Use a helper that calls `GetComponentsAllocating<T>()`
and returns the first match, everywhere, or you will hit
`InvalidOperationException` at runtime on entities you never anticipated.

**A registry you create at `Load()` is empty forever.** `EntityComponentRegistry`
is populated by registration events, so one created after the save has loaded
never sees the existing entities. Enumerate through
`DistrictCenter.DistrictBuildingRegistry.GetEnabledBuildings<T>()` instead — which
has the bonus of tagging every building with its district. Note `T` must be
`IRegisteredComponent`: `Building` and `Dwelling` and `Workplace` qualify,
`Inventory` and `BlockObject` do not (reach those off a `Building`).

**`Workplace.DesiredWorkers` has no setter.** Use `IncreaseDesiredWorkers()` /
`DecreaseDesiredWorkers()` in a guarded loop.

**`SpeedManager.CurrentSpeed` reads stale in the same frame** — it applies on
LateUpdate. Echo the requested value, not a read-back.

**Compiling proves signatures, not correctness.** Every one of the above compiled
clean and failed at runtime. Budget for iteration.

**Mods bind at process start.** No hot reload: every code change costs a full
quit and relaunch. Batch fixes aggressively.

**Verify deployments by checksum, not by the copy tool's success response.** A
file transfer reported success twice while silently leaving the old DLL in place,
costing a wasted restart. Read the file back and compare hashes.

**The game only persists on save.** Everything the bridge does lives in memory.
Quitting without saving discards all of it — we lost a fully-staffed district
this way. `/save` calls `GameSaver.QueueSaveSkippingNameValidation` with a
`SaveReference(name, SettlementReferenceService.SettlementReference)`.

---

## Endpoints

| GET | returns |
|---|---|
| `/ping` | version, `pumpRunning` — liveness without touching game state |
| `/state` | cycle, day, weather, speed, districts with population |
| `/districts` | district list with population |
| `/housing` | homes, beds, adult/child slots, occupancy, free beds per district |
| `/buildings?filter=` | inventories with template, district, coords, stock, reachability |
| `/workplaces` | desired vs assigned workers, priority, district, understaffed flag |
| `/prefabs` | every template with real footprint `Size`, entrance offset, flippable |
| `/unreachable` | finished buildings the game reports as having no valid access |

| POST | body |
|---|---|
| `/speed` | `{speed}` — 0 pauses; 3 is the UI max but higher values work |
| `/place` | `{prefab,x,y,z,orientation}` — creates a construction site |
| `/demolish` | `{x,y,z}` — instant delete, no refund, no undo |
| `/priority` | `{x,y,z,priority}` — VeryLow…VeryHigh |
| `/workers` | `{x,y,z,desired}` |
| `/migrate` | `{from,to,adults,children,bots}` — by district name |
| `/camera` | `{x,y,z,zoom}` — moves the player's view |
| `/save` | `{name}` |

### Placement chain

```
name → TemplateCollectionService.AllTemplates
     → Blueprint carrying a TemplateSpec whose IsNamed(name) matches
     → new EntitySetup.Builder(blueprint)
     → ConstructionFactory.CreateAsUnfinished(builder, new Placement(coord, orientation, FlipMode.Unflipped))
```

This produces a real construction site that beavers build with real materials —
not a spawned freebie. Invalid placements throw cleanly and create nothing, so
brute-forcing candidate tiles is safe and costs nothing. The game is a reliable
placement oracle; trust it over your own occupancy model.

### Known-wrong, still to fix

- **Auto-orientation is broken.** It keeps the first attempt as a fallback, which
  occupies the tile, so rotations 90/180/270 fail with `InvalidOperationException`.
  It must delete each attempt before trying the next.
- **`Accessible.ValidAccessible` appears to be false on unfinished buildings**,
  making the placement-time reachability check a false negative. Verify against
  `/unreachable` after construction finishes instead.

---

## API check against 1.1.2.7 (2026-11-05)

Static inspection of the installed game's managed assemblies with REA
(`inspect_managed_artifact` / `inspect_managed_members`, no code executed).
The notes above were written against 1.1.2.4; the installed build is now
1.1.2.7, and **628 of 658 assemblies changed between the two**, including every
one the bridge touches. `Bindito.Core` is among the 30 that did not change.
Rebuild against the current `Managed` folder, not a stale copy.

### Everything the bridge relied on still exists under the same name

| Type | Confirmed members (1.1.2.7) |
|---|---|
| `Bindito.Core.Configurator`, `ContextAttribute`, `IConfigurator`, `IContainer` | present; `[Context("Game")]` registration model unchanged |
| `Timberborn.SingletonSystem` | `ILoadableSingleton.Load`, `IUpdatableSingleton.UpdateSingleton`, `ILateUpdatableSingleton.LateUpdateSingleton`, `IPostLoadableSingleton.PostLoad`, `IUnloadableSingleton.Unload`, plus `INonSingletonLoader` / `INonSingletonPostLoader` |
| `Timberborn.SingletonSystem.EventBus` | `Register(object)`, `Unregister(object)`, `Post(object)`, `PostNow(object)`; handlers marked with `[OnEvent]`. Not used by the bridge yet; it is the clean way to react to game events instead of polling |
| `Timberborn.GameDistricts.DistrictCenter` | properties `District`, `DistrictPopulation`, `DistrictBuildingRegistry`, `DistrictName`, `CenterCoordinates`; methods `DistanceToCitizen`, `IsGloballyReachableFromCitizen`, `AccessibleIsOnDistrictRoad` |
| `Timberborn.GameDistricts.DistrictBuildingRegistry` | `GetEnabledBuildings<T>()` as before, plus new `GetEnabledBuildingsInstant<T>()` |
| `Timberborn.GameDistricts.Citizen` | `AssignedDistrict`, `HasAssignedDistrict`, `AssignDistrict(DistrictCenter)` |
| `Timberborn.WorkSystem.Workplace` | `DesiredWorkers` getter public, **setter private**; `IncreaseDesiredWorkers()` / `DecreaseDesiredWorkers()` public; `SetDesiredWorkers(int)` exists but is private. The guarded-loop advice stands |
| `Timberborn.TimeSystem.SpeedManager` | `CurrentSpeed` getter public, setter private; public `ChangeSpeed(float)`, `ChangeAndLockSpeed(float)`, `UnlockSpeed()`, `ChangeSpeedScale(float)`. `ChangeSpeed` stores a pending value that `LateUpdateSingleton` applies, which is exactly why a same-frame read-back is stale |
| `Timberborn.TemplateCollectionSystem.TemplateCollectionService` | `AllTemplates` public getter |
| `Timberborn.ConstructionSites.ConstructionFactory` | `CreateAsUnfinished(builder, Placement)` and `CreateAsFinished(builder, Placement)` |
| `Timberborn.EntitySystem.EntityComponentRegistry` | `GetAll<T>()`, `GetEnabled<T>()`, `Register`, `Unregister` |
| `Timberborn.GameSaveRuntimeSystem.GameSaver` | `QueueSave`, `QueueSaveSkippingNameValidation`, `SaveInstantlySkippingNameValidation`, `SaveWithoutFinishingTick` |

### Drift to handle in the rebuild

- **`GameSaver.QueueSaveSkippingNameValidation` now takes two parameters**, a
  `SaveReference` and a second reference-type argument that static metadata
  does not name. The old one-argument call will not compile. Resolve the second
  type from the assembly (likely a completion callback) before wiring `/save`.
- `EntitySetup`'s constructor is private; the public nested builder type is
  present but its nested name did not match `EntitySetup/Builder` in the
  inspector. Confirm the exact nested-type name when compiling.
- `Timberborn.Modding` exposes `ModManifest`, `ModLoader`, `ModRepository`,
  `ModSorter` (dependency ordering) and `UserFolderModsProvider`. Manifest
  fields are read by `ManifestLoader`; the five keys in `manifest.json` are the
  ones it needs.

### Save-format keys confirmed from string literals

`Timberborn.WaterSystem` loads these keys: `WaterMapNew`, `Levels`,
`WaterColumns`, `ColumnOutflows` (current), and the legacy `WaterMap`,
`WaterDepths`, `Outflows`, `ContaminationMap`, `Contaminations`,
`PollutionMap`, `Pollutions`, with `WaterSimulationMigrator` / `IsMigrated`
guarding the upgrade. `Timberborn.TerrainSystem` loads `TerrainMap` /
`Voxels` and the legacy `Heights`.

The terrain loader now carries the strings *"Loaded map has heights exceeding
map size"* and *"Terrain data height exceeds map size, truncating to fit."*
plus a `LoadingIssue.TerrainCutOffIssue`. That is an inference, not an
observation: a wrong column depth that crashed 1.0.13.1 may now be truncated
with a loading issue instead. Verify by loading a deliberately wrong map
before relying on it.

### How this was done

REA's managed inspection reads PE/CLI metadata, member signatures, IL
anchors, and `ldstr` literals without loading the assembly. It replaces the
hand-written `System.Reflection.Metadata` dumper described above, and it works
on any version of the game without a build step. Evidence IDs for every table
above are in the session ledger; the artifact digests are the installed
1.1.2.7 files.

---

## Rebuild (0.9.0, 2026-11-05)

The source now lives in `mods/BeaverBridge/src/`, rebuilt from these notes and
the 1.1.2.7 API check above. It compiles with zero warnings against the
installed game and its JSON and HTTP layers pass a unit test harness. It has
not yet been loaded in the game.

Resolved during the rebuild:

- `GameSaver.QueueSaveSkippingNameValidation(SaveReference, Action onSaveCompleted)`:
  the second argument is a completion callback.
- The builder is `Timberborn.EntitySystem.EntitySetup.Builder`, constructed
  from a `Blueprint`; `EntitySetup`'s own constructor is private.
- `Placement` lives in `Timberborn.Coordinates`, as do `Orientation` and
  `FlipMode` (a struct with `Unflipped` / `Flipped`), not in `BlockSystem`.
- Grid to world for the camera is `CoordinateSystem.GridToWorldCentered`.
- An entity's template name is its GameObject `Name` minus `(Clone)`.
- District membership of a building comes from each
  `DistrictCenter.DistrictBuildingRegistry.GetEnabledBuildings<Building>()`.
- Auto-orientation: try each `Orientation` with a fresh builder and placement;
  a failed attempt throws and creates nothing, so nothing is kept.
- Reference only `Timberborn.*.dll`, `Bindito.Core.dll`,
  `UnityEngine.CoreModule.dll` and `System.Collections.Immutable.dll` from the
  game. Referencing the game's `mscorlib`/`netstandard` copies alongside the
  SDK's reference pack produces duplicate-type errors.

`tools/apidump` replaces the hand-written reflection dumper. The whole
`Managed` folder dumps in under a second.
