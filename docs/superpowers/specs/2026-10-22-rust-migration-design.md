# Rust 跨平台遷移

保留手機網頁、6 位數配對碼、單手機／30 秒租約、錯誤驗證限流、請求去重、原文與換行、桌面 QR code、網卡選擇及可保存的連接埠（預設 39945，下次啟動生效）。

以 eframe 桌面介面、Tokio／Axum HTTP 服務、嵌入式網頁與字型取代 Python 執行環境。後端在獨立執行緒處理授權與序列化貼上，UI 與狀態端點保持回應。

Linux 目標為目前 GNOME Wayland，以 RemoteDesktop 與 Clipboard Portal 避免取得焦點。Windows 使用原生剪貼簿與 Ctrl+V／Ctrl+Shift+V。macOS 使用原生剪貼簿與 Cmd+V，需輔助使用權限；終端機不額外按 Enter。

建置目標預設 Windows x64、Linux x64、macOS ARM64 與 x64。本機可產生的二進位檔與僅有建置流程的目標分開記錄；不得宣稱未執行的編譯成功。macOS 建置需要 Apple SDK／macOS runner，目前環境沒有 Git 遠端。

設定沿用 Linux ~/.config/phone-pad/settings.json；Windows 使用使用者設定目錄，macOS 使用 Application Support。不得存入配對密碼、手機憑證或輸入文字。

驗證包含 Rust 邏輯測試、原有瀏覽器配對情境、桌面畫面、真實 Linux Portal，以及平台建置。保留舊 Python 原始碼作為遷移參照，但正式入口改為 Rust。
