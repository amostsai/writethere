use anyhow::{bail, Context, Result};
use serde::{Deserialize, Serialize};
use std::{
    fs,
    io::Write,
    path::{Path, PathBuf},
};

pub const DEFAULT_PORT: u16 = 39945;
#[derive(Serialize, Deserialize)]
struct Config {
    port: u16,
}

pub fn path() -> Result<PathBuf> {
    #[cfg(target_os = "linux")]
    if let Some(home) = std::env::var_os("XDG_CONFIG_HOME").filter(|v| !v.is_empty()) {
        return Ok(PathBuf::from(home).join("phone-pad/settings.json"));
    }
    let dirs = directories::BaseDirs::new().context("無法找到使用者設定目錄")?;
    Ok(dirs.config_dir().join("phone-pad/settings.json"))
}

pub fn parse_port(input: &str) -> Result<u16> {
    let text = input.trim();
    if text.is_empty() || text.len() > 5 || !text.bytes().all(|c| c.is_ascii_digit()) {
        bail!("連接埠須為 1–65535 的整數");
    }
    let port = text.parse::<u16>().context("連接埠須為 1–65535 的整數")?;
    if port == 0 {
        bail!("連接埠須為 1–65535 的整數");
    }
    Ok(port)
}

pub fn load(path: &Path) -> (u16, Option<String>) {
    match fs::read(path) {
        Ok(data) => match serde_json::from_slice::<Config>(&data) {
            Ok(config) if config.port > 0 => (config.port, None),
            _ => (
                DEFAULT_PORT,
                Some("設定無效，暫用 39945；可修改並儲存".into()),
            ),
        },
        Err(err) if err.kind() == std::io::ErrorKind::NotFound => (DEFAULT_PORT, None),
        Err(_) => (
            DEFAULT_PORT,
            Some("無法讀取設定，暫用 39945；可修改並儲存".into()),
        ),
    }
}

pub fn save(path: &Path, port: u16) -> Result<()> {
    if port == 0 {
        bail!("連接埠不可為 0");
    }
    let parent = path.parent().context("設定檔路徑無效")?;
    fs::create_dir_all(parent).context("無法建立設定資料夾")?;
    let mut temporary = tempfile::NamedTempFile::new_in(parent)?;
    serde_json::to_writer(&mut temporary, &Config { port })?;
    temporary.write_all(b"\n")?;
    temporary.as_file().sync_all()?;
    temporary
        .persist(path)
        .map_err(|error| anyhow::anyhow!("無法儲存設定：{}", error.error))?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn fresh_default_and_saved_port_survive_a_new_instance() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("settings.json");
        assert_eq!(load(&path).0, 39945);
        save(&path, 45678).unwrap();
        assert_eq!(load(&path).0, 45678);
    }
    #[test]
    fn validates_ports_and_preserves_bad_file() {
        for value in ["", "0", "65536", "-1", "abc", "３９９４５"] {
            assert!(parse_port(value).is_err(), "{value}");
        }
        assert_eq!(parse_port(" 39945 ").unwrap(), 39945);
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("settings.json");
        std::fs::write(&path, "broken").unwrap();
        let (port, warning) = load(&path);
        assert_eq!(port, 39945);
        assert!(warning.is_some());
        assert_eq!(std::fs::read_to_string(path).unwrap(), "broken");
    }
}
