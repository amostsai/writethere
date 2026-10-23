# Rust 版驗證紀錄（2026-10-22）

## 已驗證

- Linux：`cargo test --locked --all-targets`，19 項測試全部通過，包含驗證碼冷卻、單一配對、過期與撤銷、請求去重、原文與模式、設定持久化、鍵盤釋放與剪貼簿傳輸。
- `tests/rust_browser_smoke.py`：以 Rust HTTP fixture 和兩個獨立 Chrome browser contexts，確認配對與排他連線、中文與 emoji、多行文字、IME 組字、兩種模式、重載、授權撤銷、離線不自動重送、中斷後換機。
- Rust 桌面程式在隔離 X11 顯示環境啟動，預設 39945 可取得內嵌手機頁面；中文字型、QR code、驗證碼、設定欄與狀態顯示正常。截圖位於 `artifacts/rust-desktop.png`。
- Linux release 編譯與 Windows x64 交叉編譯、發行封裝；Windows PE 系統 DLL imports 已檢查。

## 尚未驗證

- 真實 GNOME Wayland 自動貼上：已嘗試執行 `tests/rust_live_desktop_check.py`，但系統授權未於 120 秒內完成，因此不算通過。需使用者在系統對話框允許後，驗證瀏覽器、文字編輯器與終端機的目標焦點與貼上內容。
- Windows 實機執行、權限與貼上流程。
- macOS 編譯、執行、輔助使用授權與貼上流程。本機無 Apple SDK，也尚未連接 GitHub 遠端；已備妥 Apple Silicon 與 Intel 的原生 CI 建置流程，尚無 macOS 執行檔。

Linux 本機產物在目前 Ubuntu 環境編譯，仍依賴相容的 glibc／圖形系統函式庫；較舊 Linux 的發行檔請透過 Ubuntu 22.04 CI 重新建置。
