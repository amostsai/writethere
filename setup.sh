#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_DIR"
if ! command -v cargo >/dev/null 2>&1; then
    printf '%s\n' '編譯需要 Rust 1.88 或更新版本；使用預先編譯的執行檔則不需要安裝 Rust。' >&2
    exit 1
fi
cargo build --release --locked --bin phone-pad
BUILD_DIR=${CARGO_TARGET_DIR:-target}
mkdir -p dist
install -m 755 "$BUILD_DIR/release/phone-pad" dist/phone-pad
if [ "$(uname -s)" = Linux ]; then
    ./scripts/install-linux.sh
fi
printf '%s\n' 'Rust 執行檔已建立。執行 ./run.sh，或點選「手機手寫板」圖示。'
