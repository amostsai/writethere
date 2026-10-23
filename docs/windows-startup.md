# Windows 雙擊後沒有視窗

使用者提供的 Win11 虛擬機錯誤視窗已確認：`egui_glow requires opengl 2.0+`。舊版以 OpenGL 建立介面，而虛擬機提供的版本不足，造成初始化失敗。原版 Windows GUI subsystem 又使 stderr 不可見，因此最初表現為程序出現一下就消失。

新版在進入 Rust 主程式時建立診斷檔，記錄啟動階段；視窗初始化錯誤與 Rust panic 會以原生 Windows 錯誤視窗顯示。這個視窗不需要 OpenGL。

1. 將新的 Windows 診斷 ZIP 完整解壓縮到資料夾。
2. 雙擊 `diagnose-windows.cmd`，不需系統管理員權限。
3. 若出現錯誤視窗，保留其訊息；腳本約十秒後寫出 `%LOCALAPPDATA%\phone-pad\windows-diagnostic.txt`。
4. 提供此檔案內容以判定原因。`startup.log` 同樣位於該資料夾；若該處不可寫，程式改用 `%TEMP%\phone-pad\startup.log`。

診斷包會記錄退出碼、執行檔 SHA256、Windows／CPU 架構、遠端工作階段、顯示卡與驅動，以及此次啟動的日誌。若 Windows 在進入 Rust 前即無法載入執行檔，程式內的錯誤視窗無法顯示，此時靠外部腳本的退出碼區分。

0.2.1 Windows 版改為 wgpu Direct3D 12，僅編入 DX12 backend，優先選擇可呈現視窗的 WARP 軟體繪圖裝置；未提供相容軟體裝置時才選硬體裝置。使用 Windows 系統提供的 Fxc 編譯器，不需要附加 dxcompiler.dll，也不需要 OpenGL。啟動日誌會記錄候選與選用的繪圖裝置。使用者已確認 0.2.1 在該 Win11 虛擬機成功啟動；實際貼上流程仍需另外驗證。

## 本次驗證

- `cargo test --locked --all-targets`：19 項原有測試與 1 項啟動失敗回歸測試通過。回歸測試先在舊版確認因缺少日誌失敗，再於修正後通過。
- 隔離 X11 正常啟動：視窗、39945 HTTP 服務與三個啟動階段紀錄均正常。
- Windows x64 gnullvm release 交叉編譯成功；確認 PE x64 GUI、原生 `MessageBoxW` import、無外加編譯器 runtime DLL，ZIP 內容及 SHA256 通過核對。
- Win11 虛擬機與 Windows PowerShell 診斷腳本仍需目標電腦執行，尚未收到該主機的啟動紀錄。

## 0.2.1 產物核對

`phone-pad-0.2.1-windows-x64.exe` 已成功交叉編譯與封裝。舊版 PE 的 `opengl32.dll` import 檢查先確認失敗；新版確認不再匯入 OpenGL，包含 DX12、系統 Fxc 與軟體優先選擇的實作。ZIP 逐檔與 SHA256 檢查通過。Linux 完整 20 項測試通過；這些檢查不等同已在使用者的 Win11 虛擬機完成實測。

## 使用者確認與 0.2.2

使用者已回報 Direct3D 版能成功啟動。0.2.2 保留此繪圖方式，將整行配對驗證碼改為 32 點內嵌 Noto Sans TC Bold；隔離桌面已確認顯示完整且字重正確。
