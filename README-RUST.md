# WriteThere — 手機手寫板（Rust）

手機免安裝 App，掃描電腦視窗的 QR code，輸入電腦上的 6 位數驗證碼，在手機網頁寫好文字後傳送到電腦目前的輸入框。每次只允許一個配對工作階段；斷線 30 秒或手動中斷後更新驗證碼。

## 目前產物

`dist/` 已提供 Linux x64 0.2.6 與 Windows x64 0.2.6 執行檔及壓縮包。macOS Apple Silicon／Intel 尚待原生 Mac 或 GitHub Actions 實際建置。Linux 版在目前 Ubuntu 26.04 編譯；Windows 0.2.1 已由使用者確認能在 Win11 虛擬機啟動。測試範圍與限制見 [驗證紀錄](docs/rust-verification.md)。

## 執行

- Windows：雙擊對應的 `.exe`。0.2.1 改用 Direct3D 12 並優先使用系統軟體繪圖，不再要求虛擬機提供 OpenGL 2.0。一般模式 Ctrl＋V；終端機模式 Ctrl＋Shift＋V。目標程式與本程式的權限等級須相同。
- macOS：解壓縮 `.app.zip` 後開啟 `.app`，在「隱私權與安全性 → 輔助使用」允許，再按重新授權。一般與終端機模式均使用 ⌘V。無簽章／公證版本可能受到 Gatekeeper 提示，請先確認下載來源。
- Linux：執行 `./writethere`，在 GNOME 桌面對話框授予鍵盤與剪貼簿控制；目前以 GNOME Wayland 為驗證環境。需系統的 OpenGL／EGL、XKB 與桌面 Portal，無需 Python 或 GTK。

執行檔內含手機頁面、QR code 產生器與 Noto CJK 字型，不需在啟動時下載素材。Noto 字型的開源授權文字隨發行壓縮檔附帶；使用者不需要額外授權。

預設連接埠 **39945**。在視窗修改並儲存後，下次啟動沿用新值；目前連線不會被中斷。埠被占用時顯示錯誤，不改用隨機埠。

設定檔：Linux 沿用 `$XDG_CONFIG_HOME/phone-pad/settings.json`（預設 `~/.config/phone-pad/settings.json`）；Windows 為 `%APPDATA%\phone-pad\settings.json`；macOS 為 `~/Library/Application Support/phone-pad/settings.json`。只保存連接埠，不保存驗證碼、工作階段憑證或輸入歷史。

手機與電腦須在可互通的區網。QR code 只帶邀請憑證，配對還需電腦顯示的驗證碼。失敗或逾時不會自動重送。傳送會取代剪貼簿內容；保持目標輸入框取得焦點。工具不額外按 Enter，但文字本身的換行在終端機可能執行指令。

Windows 雙擊後沒有視窗時，請使用發行包中的 `diagnose-windows.cmd` 蒐集啟動錯誤，操作說明見 [Windows 啟動診斷](docs/windows-startup.md)。

同一使用者一次只能執行一個 WriteThere。重複啟動會在建立視窗與服務前直接結束；從其他資料夾複製執行檔或修改連接埠也不會繞過限制。關閉或異常退出後可正常再次啟動。

## 開發與建置

Rust 1.89+，鎖定依賴使用 `Cargo.lock`。在 Linux 開發可先安裝 `pkg-config libxkbcommon-dev libwayland-dev libgl1-mesa-dev`。

```sh
cargo test --locked --all-targets
cargo build --locked --release --bin writethere
./target/release/writethere
```

`./setup.sh` 會編譯 Rust 程式，並在 Linux 建立桌面圖示；`./run.sh` 優先執行 `dist/writethere`，其次 `target/release/writethere`。預先編譯的發行檔無需安裝 Rust。

四種原生建置與打包流程位於 `.github/workflows/build.yml`，可手動執行或以 `v*` 標籤觸發；詳細步驟見 `docs/rust-build.md`。執行工作流程需要先將專案放進你指定的 GitHub 儲存庫；本機尚無 Git 遠端，不會自動上傳原始碼。

測試用範例不會編入正式桌面程式：

```sh
cargo build --locked --examples --features test-fixture
RUST_FIXTURE_BIN=target/debug/examples/http-fixture PYTHONPATH=. .venv/bin/python tests/rust_browser_smoke.py
RUST_LIVE_BIN=target/debug/examples/live-backend PYTHONPATH=. .venv/bin/python tests/rust_live_desktop_check.py
```

Python 僅用於可選的瀏覽器／桌面驗證工具；`phone_pad/`、`pyproject.toml` 與舊測試保留為遷移參照，正式入口不再使用 Python。
