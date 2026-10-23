# Rust 原生版本建置與封裝

本專案的 Cargo package / executable 為 `phone-pad`，目前原始碼版本 `0.2.3`。
`Cargo.lock` 必須納入版本控制；建置與測試均使用 `--locked`。
最低 Rust 版本為 1.88，GitHub Actions 固定使用 **1.93.1**。

## 原生建置

| 系統 | 預設目標 | 產物 |
| --- | --- | --- |
| Windows x64 | `x86_64-pc-windows-msvc` | `.exe`、`.zip`、SHA256 |
| Linux x64 | `x86_64-unknown-linux-gnu` | 可執行檔、`.tar.gz`、SHA256 |
| macOS Apple Silicon | `aarch64-apple-darwin` | `.app.zip`、SHA256 |
| macOS Intel | `x86_64-apple-darwin` | `.app.zip`、SHA256 |

輸出位於 `dist/`。檔名包含版本、作業系統與 CPU，例如
`phone-pad-0.2.0-windows-x64.exe`、`phone-pad-0.2.0-macos-arm64.app.zip`。
產物嵌入手機網頁資源與字型，不需要 Python、Node.js 或外部網頁伺服器。
建置 shell 腳本使用 Python 3 解析 Cargo metadata；發行後執行程式不需要 Python。
所有發行壓縮檔附帶 `NotoSansCJK-LICENSE.txt`（macOS 位於 `.app/Contents/Resources/`）；
獨立執行檔旁也會附帶此 SIL Open Font License，請隨程式一起保留。

### Windows

安裝 Rust 1.93.1 的 MSVC toolchain，以及 Visual Studio Build Tools 的
Desktop development with C++ 與 Windows SDK。在 PowerShell 執行：

```powershell
./scripts/build-release.ps1
# 或指定輸出目錄
./scripts/build-release.ps1 -OutputDirectory C:\phone-pad-dist
```

腳本依序執行目標平台測試、release build、封裝與 SHA256。
MSVC 建置使用 `-C target-feature=+crt-static`，將 C runtime 靜態連結；Windows 系統 DLL 仍由作業系統提供。
Windows 原生版預設使用 MSVC；下方 Linux 交叉編譯的 gnullvm 版本是另一個建置方式。

### Linux

Ubuntu / Debian 建置依賴：

```sh
sudo apt-get install build-essential python3 pkg-config libxkbcommon-dev libwayland-dev libgl1-mesa-dev
./scripts/build-release.sh x86_64-unknown-linux-gnu
```

需要相容的系統動態函式庫與圖形桌面；這不是完全靜態的 musl 執行檔。
CI 使用 Ubuntu 22.04，避免默認採用更新發行版的 glibc。
GNOME Wayland 的鍵盤與剪貼簿操作仍需桌面 Portal 和使用者授權；單元測試通過不代表已完成真實桌面驗證。

### macOS

安裝 Xcode Command Line Tools、Rust 1.93.1 與 Python 3，在對應的 Mac 執行：

```sh
# Apple Silicon Mac
./scripts/build-release.sh aarch64-apple-darwin
# Intel Mac
./scripts/build-release.sh x86_64-apple-darwin
```

腳本設定 Apple Silicon 的 `MACOSX_DEPLOYMENT_TARGET=11.0`、Intel 的
`MACOSX_DEPLOYMENT_TARGET=10.15`，並將相同版本寫入 Info.plist。
這些是建置部署目標，實際最舊系統仍須實機測試。
`.app` 的識別碼是 `tw.local.PhoneHandwritingPad`，執行檔位於
`Contents/MacOS/phone-pad`。它是一般可見應用程式（`LSUIElement=false`）。
Info.plist 包含輔助使用權限用途說明；仍須在系統設定中允許控制鍵盤。

目前沒有開發者簽章或公證憑證，封裝腳本沒有 Developer ID 簽章與 notarization 步驟。
因此 macOS 產物是**未經 Developer ID 簽署、未經 Apple 公證**的版本，系統可能阻擋開啟。
在確認來源後，可透過系統設定的「隱私權與安全性」開啟。
Windows 版本也沒有 Authenticode 簽章，可能顯示未知發行者提示。
SHA256 用於核對檔案完整性，不等同發行者認證。

## GitHub Actions

`.github/workflows/build.yml` 支援手動 `workflow_dispatch` 與推送 `v*` tag。
四個原生 runner 分別執行 `cargo test --locked`、`cargo build --locked --release`、封裝與 SHA256，
最後上傳四組清楚命名的 workflow artifacts，保留 30 天。
下載 workflow artifact 後先解開外層 ZIP，再使用其中的 `.app.zip` 或 `.tar.gz`，以保留可執行權限。
此流程只產生 workflow artifacts，不會自動建立 GitHub Release 或發布檔案。

目前尚未連接遠端儲存庫，也未執行此 workflow。設定檔存在不代表四個平台已成功建置。
原生 OS 整合測試、權限提示、輸入焦點與貼上操作，須在每個作業系統分別驗證。

Runner 架構與標籤參考 [GitHub 官方 runner 文件](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)。
Apple 部署目標設定參考 [Rust 官方 macOS 平台文件](https://doc.rust-lang.org/rustc/platform-support/apple-darwin.html)。

## Linux 上交叉建置 Windows（可選）

這不需要更動系統套件。可將與編譯器版本完全相同的
[官方 Rust Windows gnullvm 標準函式庫](https://static.rust-lang.org/dist/)
與 [llvm-mingw 官方 Linux host release](https://github.com/mstorsjo/llvm-mingw/releases)
解壓縮至暫存目錄。必須先核對下載來源提供的 SHA256。
此處選用與 llvm-mingw 相容的 `x86_64-pc-windows-gnullvm` 與 UCRT，
避免 GNU std 對 GCC runtime 的相依需求；參考 [Rust 官方 gnullvm 文件](https://doc.rust-lang.org/rustc/platform-support/windows-gnullvm.html)。

本次使用 `/tmp/phone-pad-cross`，Rust 1.93.1 Windows gnullvm std、官方 Linux host rustc / std 1.93.1 與 llvm-mingw 20260908 UCRT。
本機 apt 版 rustc 雖然版本號相同，仍會以 E0514 拒絕官方 std；必須使用同一組官方編譯器與標準函式庫。
建立私人 sysroot：`lib/rustlib/x86_64-pc-windows-gnullvm` 指向解壓的 Windows std，
`lib/rustlib/x86_64-unknown-linux-gnu` 指向解壓的官方 Linux std。
設定 linker 與獨立輸出目錄後執行：

```sh
export RUSTC=/tmp/phone-pad-cross/rustc-1.93.1-x86_64-unknown-linux-gnu/rustc/bin/rustc
# 此私人編譯器的 lib/rustlib/x86_64-unknown-linux-gnu/lib 也需連到官方 host std 的 lib，
# 供 build scripts / proc macros 使用。
export CARGO_HOME=/tmp/phone-pad-cargo
export CARGO_TARGET_DIR=/tmp/phone-pad-cross/target
export CARGO_TARGET_X86_64_PC_WINDOWS_GNULLVM_LINKER=/tmp/phone-pad-cross/llvm-mingw-20260908-ucrt-ubuntu-22.04-x86_64/bin/x86_64-w64-mingw32-gcc
export CARGO_TARGET_X86_64_PC_WINDOWS_GNULLVM_RUSTFLAGS='--sysroot /tmp/phone-pad-cross/sysroot -C target-feature=+crt-static'
export PATH="/tmp/phone-pad-cross/llvm-mingw-20260908-ucrt-ubuntu-22.04-x86_64/bin:$PATH"
cargo build --locked --release --target x86_64-pc-windows-gnullvm --bin phone-pad
```

`+crt-static` 也讓 llvm-mingw 的 libunwind 靜態連結，避免發行時需要另外附帶 `libunwind.dll`。
仍應以 `llvm-objdump -p` 核對最終 PE 的 DLL imports。
交叉建置只能驗證編譯與連結，不能取代 Windows 上執行測試。
macOS 在此 Linux 環境沒有 Apple SDK；因此不以非官方 SDK 交叉編譯，改由原生 Mac / CI 產生產物。

## 本機 Windows 建置驗證紀錄（2026-10-22）

此 Linux 主機已使用上述官方 Rust 1.93.1 + UCRT llvm-mingw 工具鏈，
成功執行 `cargo build --locked --release --target x86_64-pc-windows-gnullvm --bin phone-pad`，
並以 `+crt-static` 產生 `dist/phone-pad-0.2.0-windows-x64.exe`、`.zip` 與 `.sha256`。
`file` 確認為 PE32+ x86-64 GUI executable；`llvm-objdump -p` 確認 DLL imports
只含 Windows 與 UCRT 系統 DLL，沒有 libunwind、libgcc、libc++ 或 VC redistributable DLL。
ZIP 內的 exe 與字型授權文字已核對與外部檔案逐位元一致。

此紀錄代表編譯、連結、封裝與靜態 imports 檢查成功，尚未在 Windows 實機執行。
macOS 兩個架構仍需原生 Mac 或實際執行 GitHub Actions 後才能取得產物。

## 0.2.1 Windows 繪圖相容性修正

Windows 目標僅開啟 eframe wgpu 與 wgpu dx12，優先使用 WARP 軟體繪圖，Fxc 使用系統函式庫；Linux／macOS 繼續使用 glow。此修正回應 Win11 虛擬機已確認的 `egui_glow requires opengl 2.0+` 啟動失敗。原始碼以目標平台區分 renderer，避免 Windows 再次依賴 OpenGL。

## 0.2.2 驗證碼字樣

桌面「配對驗證碼：xxxxxx」整行改為 32 點 Noto Sans TC Bold，使用內嵌粗體字型；已在隔離桌面檢查完整顯示。Windows 保留 0.2.1 的 Direct3D 軟體繪圖。

## 0.2.3 介面可讀性

一般文字與按鈕使用 18 點、提示文字 16 點、標題 26 點，驗證碼保留 32 點粗體。預設視窗改為 520×900。移除「停止並關閉」與字型授權入口，使用視窗關閉功能停止服務；字型授權文件保留在發行壓縮檔。隔離桌面已確認新版文字與按鈕完整顯示。
