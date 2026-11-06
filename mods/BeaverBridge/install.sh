#!/usr/bin/env sh
# Build Beaver Bridge and install it into the game's Mods folder.
#
#   mods/BeaverBridge/install.sh [MODS_DIR]     default: ~/Documents/Timberborn/Mods
#
# The previous Code.dll is kept as Code.dll.previous. The copy is verified by
# checksum because a copy tool once reported success while leaving the old
# DLL in place. Quit the game before installing: mods bind at process start.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
mods="${1:-$HOME/Documents/Timberborn/Mods}"
dest="$mods/BeaverBridge"

export PATH="$HOME/.dotnet:$PATH"
( cd "$here/src" && dotnet build -c Release -nologo -v q )
built="$here/src/bin/Release/netstandard2.1/Code.dll"
[ -f "$built" ] || { echo "install: build produced no Code.dll" >&2; exit 1; }

mkdir -p "$dest"
[ -f "$dest/Code.dll" ] && cp "$dest/Code.dll" "$dest/Code.dll.previous"
cp "$built" "$dest/Code.dll"
cp "$here/manifest.json" "$dest/manifest.json"

want=$(shasum -a 256 "$built" | cut -d' ' -f1)
have=$(shasum -a 256 "$dest/Code.dll" | cut -d' ' -f1)
[ "$want" = "$have" ] || { echo "install: checksum mismatch after copy" >&2; exit 1; }
echo "install: Beaver Bridge $(grep '"Version"' "$here/manifest.json" | sed 's/[^0-9.]//g') installed to $dest (sha256 ${have%${have#????????}})"
