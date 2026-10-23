use crate::model::{PasteMode, StatusHandle};
use anyhow::{Context, Result};
use enigo::{Direction, Enigo, Key, Keyboard, Settings};

pub(super) struct Backend {
    status: StatusHandle,
    clipboard: Option<arboard::Clipboard>,
    keyboard: Option<Enigo>,
    #[cfg(target_os = "macos")]
    watcher: Option<tokio::task::JoinHandle<()>>,
}

impl Backend {
    pub(super) fn new(status: StatusHandle) -> Self {
        Self {
            status,
            clipboard: None,
            keyboard: None,
            #[cfg(target_os = "macos")]
            watcher: None,
        }
    }
    pub(super) async fn authorize(&mut self) -> Result<()> {
        let keyboard = Enigo::new(&Settings::default()).context(permission_help())?;
        let clipboard = arboard::Clipboard::new().context("無法開啟系統剪貼簿")?;
        self.keyboard = Some(keyboard);
        self.clipboard = Some(clipboard);
        super::set_status(&self.status, true, "已授權，可以傳送文字");
        #[cfg(target_os = "macos")]
        {
            let status = self.status.clone();
            self.watcher = Some(tokio::spawn(async move {
                let mut interval = tokio::time::interval(std::time::Duration::from_millis(500));
                loop {
                    interval.tick().await;
                    if !accessibility_allowed() {
                        super::set_status(&status, false, permission_help());
                        break;
                    }
                }
            }));
        }
        Ok(())
    }
    pub(super) async fn paste(&mut self, text: &str, mode: PasteMode) -> Result<()> {
        #[cfg(target_os = "macos")]
        if !accessibility_allowed() {
            anyhow::bail!(permission_help());
        }
        self.clipboard
            .as_mut()
            .context("尚未授權剪貼簿")?
            .set_text(text)
            .context("無法寫入系統剪貼簿")?;
        let keyboard = self.keyboard.as_mut().context("尚未授權鍵盤控制")?;
        #[cfg(target_os = "macos")]
        let keys = {
            let _ = mode;
            // macOS Terminal uses Cmd+V too; Ctrl+Shift+V has different semantics.
            vec![Key::Meta, Key::Unicode('v')]
        };
        #[cfg(target_os = "windows")]
        let keys = match mode {
            PasteMode::Normal => vec![Key::Control, Key::Unicode('v')],
            PasteMode::Terminal => vec![Key::Control, Key::Shift, Key::Unicode('v')],
        };
        let mut pressed = Vec::new();
        let mut failure = None;
        for key in keys {
            // An API error can happen after an event reached the OS.
            pressed.push(key);
            if let Err(error) = keyboard.key(key, Direction::Press) {
                failure = Some(anyhow::Error::new(error));
                break;
            }
        }
        for key in pressed.into_iter().rev() {
            if let Err(error) = keyboard.key(key, Direction::Release) {
                if failure.is_none() {
                    failure = Some(anyhow::Error::new(error));
                }
            }
        }
        if let Some(error) = failure {
            return Err(error.context(permission_help()));
        }
        Ok(())
    }
    pub(super) async fn close(&mut self) {
        #[cfg(target_os = "macos")]
        if let Some(watcher) = self.watcher.take() {
            watcher.abort();
            let _ = watcher.await;
        }
        self.keyboard = None;
        self.clipboard = None;
        super::set_status(&self.status, false, "桌面控制已關閉");
    }
}

fn permission_help() -> &'static str {
    #[cfg(target_os = "macos")]
    {
        "請在「系統設定 → 隱私權與安全性 → 輔助使用」允許本程式，再按重新授權；若已允許，請重啟程式"
    }
    #[cfg(target_os = "windows")]
    {
        "無法傳送鍵盤事件，請確認目標程式與本程式的權限等級相同，再重新授權"
    }
}

#[cfg(target_os = "macos")]
fn accessibility_allowed() -> bool {
    #[link(name = "ApplicationServices", kind = "framework")]
    unsafe extern "C" {
        fn AXIsProcessTrusted() -> bool;
    }
    // Query only; permission prompts are created by Enigo during authorization.
    unsafe { AXIsProcessTrusted() }
}
