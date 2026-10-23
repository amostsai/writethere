//! Desktop integration lives exclusively on the dedicated backend runtime.
use crate::model::{PasteMode, StatusHandle};
use anyhow::{bail, Result};

#[cfg(target_os = "linux")]
#[path = "platform/linux.rs"]
mod linux;
#[cfg(target_os = "linux")]
use linux::Backend;
#[cfg(any(target_os = "windows", target_os = "macos"))]
#[path = "platform/native.rs"]
mod native;
#[cfg(any(target_os = "windows", target_os = "macos"))]
use native::Backend;
#[cfg(not(any(target_os = "linux", target_os = "windows", target_os = "macos")))]
compile_error!("WriteThere supports Linux, Windows and macOS");

pub struct Platform {
    status: StatusHandle,
    backend: Backend,
}
impl Platform {
    pub fn new(status: StatusHandle) -> Self {
        set_status(&status, false, "尚未取得桌面控制授權");
        Self {
            backend: Backend::new(status.clone()),
            status,
        }
    }
    pub async fn authorize(&mut self) -> Result<()> {
        set_status(&self.status, false, "等待桌面授權，請在電腦確認系統對話框");
        self.backend.close().await;
        set_status(&self.status, false, "等待桌面授權，請在電腦確認系統對話框");
        if let Err(error) = self.backend.authorize().await {
            self.backend.close().await;
            set_status(&self.status, false, &format!("桌面授權失敗：{error:#}"));
            return Err(error);
        }
        Ok(())
    }
    pub async fn paste(&mut self, text: &str, mode: PasteMode) -> Result<()> {
        if !self.status.lock().unwrap_or_else(|e| e.into_inner()).ready {
            bail!("尚未取得桌面控制授權，請在電腦重新授權");
        }
        if let Err(error) = self.backend.paste(text, mode).await {
            set_status(
                &self.status,
                false,
                "貼上失敗，請重新授權；先查看電腦的貼上結果",
            );
            self.backend.close().await;
            set_status(
                &self.status,
                false,
                "貼上失敗，請重新授權；先查看電腦的貼上結果",
            );
            return Err(error);
        }
        // Keep the serial command queue occupied until the focused application
        // has had a chance to request the current clipboard selection.
        tokio::time::sleep(std::time::Duration::from_millis(250)).await;
        if !self.status.lock().unwrap_or_else(|e| e.into_inner()).ready {
            self.backend.close().await;
            bail!("桌面控制或剪貼簿傳輸失敗，請重新授權；先查看電腦的貼上結果");
        }
        Ok(())
    }
    pub async fn close(&mut self) {
        set_status(&self.status, false, "服務已停止");
        self.backend.close().await;
        set_status(&self.status, false, "服務已停止");
    }
}
fn set_status(status: &StatusHandle, ready: bool, message: &str) {
    let mut status = status.lock().unwrap_or_else(|e| e.into_inner());
    status.ready = ready;
    status.message = message.into();
}

// Every attempted press is balanced even if its reply or a later release fails.
#[cfg(any(target_os = "linux", test))]
async fn balanced_keys<F, Fut>(keys: &[i32], mut send: F) -> Result<()>
where
    F: FnMut(i32, bool) -> Fut,
    Fut: std::future::Future<Output = Result<()>>,
{
    let mut count = 0;
    let mut failure = None;
    for &key in keys {
        count += 1;
        if let Err(error) = send(key, true).await {
            failure = Some(error);
            break;
        }
    }
    for &key in keys[..count].iter().rev() {
        if let Err(error) = send(key, false).await {
            if failure.is_none() {
                failure = Some(error);
            }
        }
    }
    match failure {
        Some(error) => Err(error),
        None => Ok(()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn failed_press_still_releases_every_possibly_pressed_key() {
        let mut events = Vec::new();
        let result = balanced_keys(&[0xffe3, 0xffe1, 0x76], |key, down| {
            events.push((key, down));
            std::future::ready(if key == 0xffe1 && down {
                Err(anyhow::anyhow!("lost reply"))
            } else {
                Ok(())
            })
        })
        .await;
        assert!(result.is_err());
        assert_eq!(
            events,
            [
                (0xffe3, true),
                (0xffe1, true),
                (0xffe1, false),
                (0xffe3, false)
            ]
        );
    }
    #[tokio::test]
    async fn failed_release_does_not_skip_other_releases() {
        let mut events = Vec::new();
        let result = balanced_keys(&[0xffe3, 0x76], |key, down| {
            events.push((key, down));
            std::future::ready(if key == 0x76 && !down {
                Err(anyhow::anyhow!("release failed"))
            } else {
                Ok(())
            })
        })
        .await;
        assert!(result.is_err());
        assert_eq!(
            events,
            [(0xffe3, true), (0x76, true), (0x76, false), (0xffe3, false)]
        );
    }
    #[tokio::test]
    async fn rejects_paste_without_authorization() {
        let status = crate::model::new_status();
        let mut platform = Platform::new(status.clone());
        assert!(platform.paste("秘密文字", PasteMode::Normal).await.is_err());
        assert!(!status.lock().unwrap().ready);
    }
}
