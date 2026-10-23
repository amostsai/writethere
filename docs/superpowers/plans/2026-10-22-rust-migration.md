# Rust migration implementation plan

Goal: preserve the approved phone-pad behavior in native Rust executables.

1. Implement settings and HTTP/session state in Rust with tests for authentication, exclusive pairing, expiry, rate limiting, duplicate sends, saved ports and listener failures.
2. Implement independent platform backends against model.rs: Linux Portal clipboard + keyboard, Windows/macOS native clipboard + keyboard. Keep desktop authorization and cancellation explicit.
3. Implement eframe UI, embed phone web assets and a CJK font, preserve settings path and port 39945. Avoid focusing the desktop window on received text.
4. Build Linux release, exercise browser/UI/Portal behavior. Configure native OS CI jobs and packaging for Windows x64, macOS ARM64/x64 and Linux x64. Attempt local Windows build only if a valid cross-toolchain can be provisioned within resources.
5. Switch launchers after verification, preserve legacy sources, document actual artifact availability and platform testing limitations.

No remote repository exists yet; hosted build jobs cannot be dispatched until one is provided. Do not publish or upload project sources without user direction.
