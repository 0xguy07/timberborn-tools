#!/usr/bin/env sh
# Refresh a local copy of Timberborn's managed assemblies from the installed game.
#
#   tools/sync-gamerefs.sh [DEST]      default DEST: ~/Documents/Timberborn/GameRefs
#
# Set TIMBERBORN_MANAGED to the game's Managed folder if it is not in the Steam
# default location. The copy is for building mods against; it is game content
# and must never be committed.
set -eu

dest="${1:-$HOME/Documents/Timberborn/GameRefs}"
if [ -n "${TIMBERBORN_MANAGED:-}" ]; then
  src="$TIMBERBORN_MANAGED"
else
  for c in \
    "$HOME/Library/Application Support/Steam/steamapps/common/Timberborn/Timberborn.app/Contents/Resources/Data/Managed" \
    "$HOME/.steam/steam/steamapps/common/Timberborn/Timberborn_Data/Managed" \
    "$HOME/.local/share/Steam/steamapps/common/Timberborn/Timberborn_Data/Managed" \
    "/c/Program Files (x86)/Steam/steamapps/common/Timberborn/Timberborn_Data/Managed"; do
    if [ -d "$c" ]; then src="$c"; break; fi
  done
fi
if [ -z "${src:-}" ] || [ ! -d "$src" ]; then
  echo "sync-gamerefs: game Managed folder not found; set TIMBERBORN_MANAGED" >&2
  exit 1
fi

app="${src%/Contents/Resources/Data/Managed}"
version=""
if [ -f "$app/Contents/Info.plist" ] && command -v defaults >/dev/null 2>&1; then
  version=$(defaults read "$app/Contents/Info.plist" CFBundleShortVersionString 2>/dev/null || true)
fi

mkdir -p "$dest"
changed=$(rsync -a --delete --itemize-changes --include='*.dll' --exclude='*' "$src/" "$dest/" | grep -c '^>f' || true)
total=$(ls "$dest"/*.dll 2>/dev/null | wc -l | tr -d ' ')
printf '%s\n' "${version:-unknown}" > "$dest/GAME_VERSION"
echo "sync-gamerefs: $total assemblies in $dest ($changed updated), game version ${version:-unknown}"
