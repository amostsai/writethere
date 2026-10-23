#![cfg(target_os = "linux")]

use std::{fs, process::Command};

#[test]
fn duplicate_exits_before_gui_and_preserves_first_instances_log() {
    let dir = tempfile::tempdir().unwrap();
    let data = dir.path().join("data/phone-pad");
    let state = dir.path().join("state/phone-pad");
    fs::create_dir_all(&data).unwrap();
    fs::create_dir_all(&state).unwrap();
    let lock = fs::OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(data.join("writethere.lock"))
        .unwrap();
    lock.try_lock().unwrap();
    fs::write(state.join("startup.log"), "first process diagnostics").unwrap();
    let binary = env!("CARGO_BIN_EXE_writethere");
    let copied = dir.path().join("copied-writethere");
    fs::copy(binary, &copied).unwrap();
    for executable in [std::path::Path::new(binary), copied.as_path()] {
        let output = Command::new(executable)
            .env("XDG_DATA_HOME", dir.path().join("data"))
            .env("XDG_STATE_HOME", dir.path().join("state"))
            .env("XDG_CONFIG_HOME", dir.path().join("config"))
            .env("DISPLAY", ":65530")
            .env("WAYLAND_DISPLAY", "writethere-nonexistent-wayland")
            .env("WINIT_UNIX_BACKEND", "x11")
            .output()
            .unwrap();
        assert!(
            output.status.success(),
            "duplicate should exit before GUI: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        assert_eq!(
            fs::read_to_string(state.join("startup.log")).unwrap(),
            "first process diagnostics"
        );
    }
}
