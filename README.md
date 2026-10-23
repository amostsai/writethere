# WriteThere（手機手寫板）（Rust）

手機掃描電腦的 QR code，輸入 6 位數驗證碼，寫好文字後傳送到電腦目前的輸入框。支援單手機配對、逾時釋放與可保存的連接埠（預設 39945）。

正式程式已改為 Rust，執行不需要 Python。使用方式、平台權限與開發命令請看 [Rust 使用說明](README-RUST.md)。

- `src/`：Rust 桌面介面、HTTP 服務、設定與平台輸入後端。
- `dist/`：本次實際編譯的執行檔、壓縮檔與 SHA256；未編譯成功的平台不會放入假產物。
- `.github/workflows/build.yml`：Windows x64、Linux x64、macOS ARM64／Intel 原生建置。
- [跨平台建置紀錄](docs/rust-build.md)：各目標的實際產出與驗證限制。

本機使用 `./run.sh` 啟動 Rust 執行檔。原始 Python 版本與測試保留為遷移參照，舊版說明位於 [Python 參照文件](docs/python-legacy.md)。
