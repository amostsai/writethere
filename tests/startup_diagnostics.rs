#![cfg(target_os = "linux")]

use std::process::Command;

#[test]
fn failed_window_startup_leaves_a_readable_error_and_nonzero_exit() {
    let dir = tempfile::tempdir().unwrap();
    // An unavailable display reproduces an actual eframe initialization error.
    let output = Command::new(env!("CARGO_BIN_EXE_writethere"))
        .env("XDG_STATE_HOME", dir.path())
        .env("XDG_DATA_HOME", dir.path().join("data"))
        .env("DISPLAY", ":65530")
        .env("WAYLAND_DISPLAY", "phone-pad-nonexistent-wayland")
        .env("WINIT_UNIX_BACKEND", "x11")
        .output()
        .unwrap();
    assert!(!output.status.success());
    let log = std::fs::read_to_string(dir.path().join("phone-pad/startup.log"))
        .expect("GUI initialization failure must leave a startup log");
    assert!(log.contains("starting version="), "{log}");
    assert!(
        log.contains("startup failed") || log.contains("panic:"),
        "{log}"
    );
}
