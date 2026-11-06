#!/usr/bin/env sh
# Installer for tmux-menu. Installs to ~/.local/share/tmux-menu and links
# ~/.local/bin/tmux-menu. Re-run to upgrade. Use "--uninstall" to remove.
set -eu

REPO="imwasay/tmux_utility"
BRANCH="main"
DEST="${TMUX_MENU_HOME:-$HOME/.local/share/tmux-menu}"
BIN="${TMUX_MENU_BIN:-$HOME/.local/bin}"

if [ "${1:-}" = "--uninstall" ]; then
    rm -f "$BIN/tmux-menu"
    echo "Removed $BIN/tmux-menu. Your hosts file is kept in $DEST/.env;"
    echo "delete $DEST to remove everything."
    exit 0
fi

for cmd in python3 tmux curl tar; do
    command -v "$cmd" >/dev/null 2>&1 || { echo "error: '$cmd' is required" >&2; exit 1; }
done

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

echo "Downloading tmux-menu..."
curl -fsSL "https://github.com/$REPO/archive/refs/heads/$BRANCH.tar.gz" \
    | tar -xz -C "$tmp" --strip-components=1

mkdir -p "$DEST" "$BIN"
# Copy program files only; never touch an existing .env.
cp "$tmp/tmux-ui.py" "$tmp/tmux-menu" "$tmp/README.md" "$tmp/LICENSE" "$tmp/.env.example" "$DEST/"
chmod +x "$DEST/tmux-ui.py" "$DEST/tmux-menu"
ln -sf "$DEST/tmux-menu" "$BIN/tmux-menu"

echo "Installed: $BIN/tmux-menu"
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) echo "Note: add $BIN to your PATH, e.g. export PATH=\"$BIN:\$PATH\"" ;;
esac
echo "Run: tmux-menu"
