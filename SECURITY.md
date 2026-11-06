# Security Policy

timberborn-tools reads your game files and, with the mod installed, lets software control a running game. This page says exactly what each part touches, what it can never do, and how to report a problem.

## Supported versions

Fixes land on `main` and ship as a new release. Only the latest release is supported.

| Version | Supported |
|---|---|
| Latest release | Yes |
| Older releases | No; please upgrade |

## Reporting a vulnerability

**Please do not open a public issue for a security problem.**

Report it privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability** ([direct link](https://github.com/0xguy07/timberborn-tools/security/advisories/new)).

Please include what you found and why it matters, the commit or release, your OS and game version, steps to reproduce, and a suggested fix if you have one. Do not attach your save files; a description of the save layout is enough.

## What to expect

This is a small project maintained by one person, so these are good-faith targets, not guarantees: acknowledgement within about 7 days, an initial assessment within about 14 days, and a fix or mitigation with coordinated disclosure and credit, if you want it, as soon as is practical.

## What each part can and cannot do

Nothing in this repository makes a network request. There is no telemetry, no update check, and no account.

### Map tools (`maptools/`)

- Read the `.timber` file you name on the command line, and optionally the game's `Blueprints.zip` and a shipped map you point them at.
- The generator writes one `.timber` file to the path you give it. The validator and measurer write nothing.
- The only third-party dependency is Pillow, used by the generator for the map thumbnail. The validator and measurer are standard-library Python.

### Save bridge (`bridge/`)

- **Read-only.** It opens `.timber` saves under one folder, `~/Documents/Timberborn` or `TIMBERBORN_DIR`, and never writes to them. There is no code path that modifies a save.
- Speaks MCP over stdin and stdout only. It opens no sockets and listens on no port.
- Standard-library Python with no dependencies, so there is nothing to install and nothing to update.
- The `raw` tool walks the save's JSON by dotted path. It cannot reach outside the save file.
- Reports contain your settlement name, district names and colony statistics. That is data from your own save, returned to the MCP client you configured. The bridge sends it nowhere else.

### Beaver Bridge mod (`mods/BeaverBridge/`)

This is the only part that can change anything, and only inside a running game.

- **Loopback only.** It listens on `127.0.0.1`, so it is unreachable from other machines on your network, including over Wi-Fi. The port defaults to 7777 and can be changed with `BEAVER_BRIDGE_PORT`.
- **No authentication.** Any program running as your user on the same machine can read and control the game while it is loaded. Treat it like a debugger: install it when you want an agent driving the game, remove it when you do not. The game only loads mods from its `Mods` folder at startup.
- **Browsers are kept out.** Every POST must carry `Content-Type: application/json` and the server sends no CORS headers and answers no preflights. A web page you happen to have open cannot send that request cross-origin without a preflight, so it cannot place, demolish, migrate or save on your behalf. GET requests from a page are refused the response by the browser's same-origin policy.
- **What it can change:** construction sites, demolition, worker counts, priorities, migration, game speed, the camera, and saving under a name you supply. Demolition is instant and has no undo; the mod does not add any destructive capability the in-game UI lacks, but it removes the confirmation dialogs.
- **Save names are validated** against the operating system's invalid filename characters, and the game's own save repository decides the final path. The mod does not build file paths itself.
- **Bounded input.** Request headers are capped at 64 KB and bodies at 1 MB. Malformed HTTP or JSON returns a 400 and touches nothing.
- **Nothing leaves the machine.** The mod makes no outbound connections.
- **Builds offline.** The project has no package references and its `nuget.config` clears all package sources. It references the game's own assemblies in place and never copies or redistributes them. The repository contains no compiled binaries; you build the DLL yourself from the source you can read.

### Tools (`tools/`)

- `apidump` reads assembly metadata from files you name and prints text. It does not load or execute the assemblies.
- `sync-gamerefs.sh` copies DLLs from the game's install folder to a local folder with `rsync`. The destination is yours; the script never touches the game install.

## What is deliberately kept out of the repository

Game assemblies, saves, player data, error reports and the game's shipped maps. They are game content, and saves can carry your settlement names. `.gitignore` refuses `*.dll`, `Saves/`, `PlayerData/` and generated maps. If you contribute, please keep it that way.

## Continuous integration

CI runs on GitHub's hosted runners with no secrets, no deploy keys and no access to anything outside the checkout. It regenerates and validates the sample map, lints the Python, builds `apidump`, and runs the mod's protocol tests. It cannot build the mod itself because that needs the game's assemblies, which are not in the repo.

## In scope

- The save bridge writing to, moving or deleting any file
- The mod accepting a connection from a non-loopback address, or acting on a request a browser could have sent cross-origin
- Any input that lets the mod read or write a path outside the game's own save and mod folders
- Crashes or hangs of the game process triggered through the bridge's HTTP interface
- Unsafe handling of map or save contents in the Python tools, such as paths taken from inside a `.timber` file

## Out of scope

- Vulnerabilities in Timberborn, Unity or the .NET runtime; report those to their vendors
- Anything that requires an attacker to already be running code as your user on your machine, since the mod is explicitly unauthenticated on loopback
- Consequences of commands you send to the mod on purpose
- Findings from automated scanners without a demonstrated impact
