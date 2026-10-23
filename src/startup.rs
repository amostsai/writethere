//! Startup failures must be visible even in Windows GUI-subsystem builds.
use std::{fs, io::Write, path::PathBuf};

#[derive(Clone)]
pub struct Diagnostics {
    path: Option<PathBuf>,
}
impl Diagnostics {
    pub fn initialize() -> Self {
        let preferred = directories::BaseDirs::new().map(|dirs| {
            #[cfg(target_os = "linux")]
            let base = dirs.state_dir().unwrap_or_else(|| dirs.data_local_dir());
            #[cfg(not(target_os = "linux"))]
            let base = dirs.data_local_dir();
            base.join("phone-pad/startup.log")
        });
        let path = preferred
            .into_iter()
            .chain(std::iter::once(
                std::env::temp_dir().join("phone-pad/startup.log"),
            ))
            .find(|path| {
                path.parent()
                    .is_some_and(|parent| fs::create_dir_all(parent).is_ok())
                    && fs::write(path, b"").is_ok()
            });
        let diagnostics = Self { path };
        diagnostics.record(&format!(
            "starting version={} os={} arch={} renderer={}",
            env!("CARGO_PKG_VERSION"),
            std::env::consts::OS,
            std::env::consts::ARCH,
            crate::renderer::name()
        ));
        let panic_diagnostics = diagnostics.clone();
        let previous = std::panic::take_hook();
        std::panic::set_hook(Box::new(move |info| {
            panic_diagnostics.failure(&format!("panic: {info}"));
            previous(info);
        }));
        diagnostics
    }
    pub fn record(&self, message: &str) {
        if let Some(path) = &self.path {
            if let Ok(mut file) = fs::OpenOptions::new().append(true).open(path) {
                let seconds = std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .as_secs();
                let _ = writeln!(file, "[{seconds}] {message}");
                let _ = file.flush();
            }
        }
    }
    pub fn failure(&self, error: &str) {
        self.record(&format!("startup failed: {error}"));
        let location = self
            .path
            .as_ref()
            .map(|path| path.display().to_string())
            .unwrap_or_else(|| "無法寫入診斷檔".into());
        let message = format!("WriteThere 無法正常啟動。\n\n{error}\n\n診斷檔：{location}\n\n請提供此訊息或執行診斷包中的 diagnose-windows.cmd。");
        report_early_failure(&message);
    }
}

pub fn report_early_failure(message: &str) {
    eprintln!("{message}");
    #[cfg(target_os = "windows")]
    show_error(message);
}

#[cfg(target_os = "windows")]
fn show_error(message: &str) {
    #[link(name = "user32")]
    unsafe extern "system" {
        fn MessageBoxW(
            window: *mut std::ffi::c_void,
            text: *const u16,
            caption: *const u16,
            flags: u32,
        ) -> i32;
    }
    let wide = |text: &str| {
        text.encode_utf16()
            .map(|c| if c == 0 { 0xfffd } else { c })
            .chain(Some(0))
            .collect::<Vec<_>>()
    };
    let text = wide(message);
    let caption = wide("WriteThere：啟動失敗");
    // This native dialog does not depend on the graphics context that failed.
    unsafe {
        MessageBoxW(std::ptr::null_mut(), text.as_ptr(), caption.as_ptr(), 0x10);
    }
}
