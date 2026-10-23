#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
TARGET="${1:-$(rustc -vV | sed -n 's/^host: //p')}"
OUT="${PHONE_PAD_DIST_DIR:-$PWD/dist}"
metadata="$(cargo metadata --locked --no-deps --format-version 1)"
VERSION="$(printf '%s' "$metadata" | python3 -c 'import json,sys; print(next(p["version"] for p in json.load(sys.stdin)["packages"] if p["name"] == "phone-pad"))')"
TARGET_DIR="$(printf '%s' "$metadata" | python3 -c 'import json,sys; print(json.load(sys.stdin)["target_directory"])')"
case "$TARGET" in
  aarch64-apple-darwin) export MACOSX_DEPLOYMENT_TARGET=11.0 ;;
  x86_64-apple-darwin) export MACOSX_DEPLOYMENT_TARGET=10.15 ;;
  x86_64-unknown-linux-gnu) ;;
  *) echo "Unsupported release target: $TARGET" >&2; exit 2 ;;
esac
cargo test --locked --target "$TARGET"
cargo build --locked --release --target "$TARGET" --bin phone-pad
mkdir -p "$OUT"
case "$TARGET" in
  *-apple-darwin)
    scripts/package-macos.sh "$TARGET_DIR/$TARGET/release/phone-pad" "$TARGET" "$VERSION" "$OUT"
    ;;
  x86_64-unknown-linux-gnu)
    name="phone-pad-$VERSION-linux-x64"
    install -m 755 "$TARGET_DIR/$TARGET/release/phone-pad" "$OUT/$name"
    install -m 644 assets/NotoSansCJK-LICENSE.txt "$OUT/NotoSansCJK-LICENSE.txt"
    tar -czf "$OUT/$name.tar.gz" -C "$OUT" "$name" NotoSansCJK-LICENSE.txt
    (cd "$OUT"; sha256sum "$name" "$name.tar.gz" NotoSansCJK-LICENSE.txt > "$name.sha256")
    ;;
esac
