#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$PROJECT_DIR"
if [ -x "$PROJECT_DIR/dist/phone-pad" ]; then
    exec "$PROJECT_DIR/dist/phone-pad" "$@"
fi
if [ -x "$PROJECT_DIR/target/release/phone-pad" ]; then
    exec "$PROJECT_DIR/target/release/phone-pad" "$@"
fi
printf '%s\n' '找不到 Rust 執行檔。請先執行 ./setup.sh，或下載對應平台的執行檔。' >&2
exit 1
