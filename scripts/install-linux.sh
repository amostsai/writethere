#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
# Generate Exec quoting without invoking Python. Percent is a Desktop Entry
# field-code prefix; it must be doubled even inside quoted arguments.
exec_path=$(printf '%s' "$PROJECT_DIR/run.sh" | sed 's/\\/\\\\/g; s/"/\\"/g; s/`/\\`/g; s/\$/\\$/g; s/%/%%/g')
launcher="$PROJECT_DIR/手機手寫板.desktop"
cat > "$launcher" <<EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=WriteThere
Comment=手機掃碼輸入文字，自動貼到電腦
Exec="$exec_path"
Icon=$PROJECT_DIR/phone_pad/assets/icon.svg
Terminal=false
Categories=Utility;Accessibility;
StartupNotify=true
StartupWMClass=tw.local.PhoneHandwritingPad
EOF
chmod 755 "$launcher"
app_dir="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$app_dir"
cp "$launcher" "$app_dir/tw.local.PhoneHandwritingPad.desktop"
if command -v xdg-user-dir >/dev/null 2>&1; then
    desktop_dir=$(xdg-user-dir DESKTOP)
    if [ -d "$desktop_dir" ] && [ "$desktop_dir" != "$HOME" ]; then
        cp "$launcher" "$desktop_dir/手機手寫板.desktop"
        gio set "$desktop_dir/手機手寫板.desktop" metadata::trusted true 2>/dev/null || true
    fi
fi
if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$app_dir" || true
fi
