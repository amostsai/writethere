#!/usr/bin/env bash
set -euo pipefail
if [[ $# -ne 4 ]]; then
  echo "Usage: $0 BINARY TARGET VERSION OUTPUT_DIRECTORY" >&2
  exit 2
fi
BINARY="$1"
TARGET="$2"
VERSION="$3"
OUT="$4"
case "$TARGET" in
  aarch64-apple-darwin) ARCH=arm64; MIN_OS=11.0 ;;
  x86_64-apple-darwin) ARCH=x64; MIN_OS=10.15 ;;
  *) echo "Unsupported macOS target: $TARGET" >&2; exit 2 ;;
esac
[[ "$(uname -s)" == Darwin ]] || { echo "macOS packaging requires a macOS host (ditto and plutil)." >&2; exit 2; }
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
APP="$stage/WriteThere.app"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
install -m 755 "$BINARY" "$APP/Contents/MacOS/writethere"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
install -m 644 "$SCRIPT_DIR/../assets/NotoSansCJK-LICENSE.txt" "$APP/Contents/Resources/NotoSansCJK-LICENSE.txt"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleIdentifier</key><string>tw.local.PhoneHandwritingPad</string>
  <key>CFBundleName</key><string>WriteThere</string>
  <key>CFBundleDisplayName</key><string>WriteThere</string>
  <key>CFBundleExecutable</key><string>writethere</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>LSMinimumSystemVersion</key><string>$MIN_OS</string>
  <key>LSUIElement</key><false/>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAccessibilityUsageDescription</key><string>手機手寫板需要輔助使用權限，才能將手機傳來的文字貼入目前使用的應用程式。</string>
</dict></plist>
PLIST
plutil -lint "$APP/Contents/Info.plist"
name="writethere-$VERSION-macos-$ARCH"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$OUT/$name.app.zip"
(cd "$OUT"; shasum -a 256 "$name.app.zip" > "$name.sha256")
