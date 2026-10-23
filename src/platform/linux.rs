//! Keyboard-only GNOME RemoteDesktop + Clipboard portal.
use super::balanced_keys;
use crate::model::{PasteMode, StatusHandle};
use anyhow::{bail, Context, Result};
use ashpd::desktop::{
    clipboard::{Clipboard, RequestClipboardOptions, SetSelectionOptions},
    remote_desktop::{
        DeviceType, KeyState, NotifyKeyboardKeysymOptions, RemoteDesktop, SelectDevicesOptions,
        StartOptions,
    },
    CreateSessionOptions, Session,
};
use futures_util::{pin_mut, StreamExt};
use std::{
    io::{self, Write},
    os::fd::{AsRawFd, OwnedFd},
    sync::{
        atomic::{AtomicBool, Ordering},
        Arc, Mutex,
    },
    time::Duration,
};
use tokio::{
    io::unix::AsyncFd,
    sync::oneshot,
    task::{JoinHandle, JoinSet},
};

const MIME_TYPES: &[&str] = &["text/plain;charset=utf-8", "text/plain", "UTF8_STRING"];
type Selection = Arc<Mutex<Option<Arc<[u8]>>>>;

pub(super) struct Backend {
    status: StatusHandle,
    state: Option<State>,
}
struct State {
    remote: Arc<RemoteDesktop>,
    clipboard: Arc<Clipboard>,
    session: Arc<Session<RemoteDesktop>>,
    data: Selection,
    live: Arc<AtomicBool>,
    monitor: JoinHandle<()>,
}

impl Backend {
    pub(super) fn new(status: StatusHandle) -> Self {
        Self {
            status,
            state: None,
        }
    }
    pub(super) async fn authorize(&mut self) -> Result<()> {
        let remote = Arc::new(
            RemoteDesktop::new()
                .await
                .context("無法連接 GNOME 桌面 Portal")?,
        );
        let clipboard = Arc::new(
            Clipboard::with_connection(remote.connection().clone())
                .await
                .context("GNOME 桌面缺少 Clipboard Portal，請更新桌面服務")?,
        );
        let session = Arc::new(
            remote
                .create_session(CreateSessionOptions::default())
                .await?,
        );
        let data = Arc::new(Mutex::new(None));
        let live = Arc::new(AtomicBool::new(true));
        let (ready_tx, ready_rx) = oneshot::channel();
        let monitor = tokio::spawn(monitor(
            remote.clone(),
            clipboard.clone(),
            session.clone(),
            data.clone(),
            live.clone(),
            self.status.clone(),
            ready_tx,
        ));
        self.state = Some(State {
            remote,
            clipboard,
            session,
            data,
            live,
            monitor,
        });
        let result =
            match tokio::time::timeout(Duration::from_secs(120), self.start(ready_rx)).await {
                Ok(result) => result,
                Err(_) => Err(anyhow::anyhow!("桌面授權逾時，請重新授權")),
            };
        if result.is_err() {
            self.close().await;
        }
        result
    }
    async fn start(&self, ready: oneshot::Receiver<Result<()>>) -> Result<()> {
        ready.await.context("無法監聽桌面控制狀態")??;
        let state = self.state.as_ref().unwrap();
        state
            .remote
            .select_devices(
                &state.session,
                SelectDevicesOptions::default()
                    .set_devices(ashpd::enumflags2::BitFlags::from(DeviceType::Keyboard)),
            )
            .await?
            .response()?;
        // Clipboard access must be requested BEFORE Start.
        state
            .clipboard
            .request(&state.session, RequestClipboardOptions::default())
            .await?;
        let request = state
            .remote
            .start(&state.session, None, StartOptions::default())
            .await?;
        let granted = request.response()?;
        if !granted.devices().contains(DeviceType::Keyboard) {
            bail!("系統未授予鍵盤控制權限，請重新授權");
        }
        if !granted.is_clipboard_enabled() {
            bail!("系統未授予剪貼簿權限，請重新授權");
        }
        let mut status = self.status.lock().unwrap_or_else(|e| e.into_inner());
        if !state.live.load(Ordering::SeqCst) {
            bail!("桌面控制授權已撤銷，請重新授權");
        }
        status.ready = true;
        status.message = "已授權，可以傳送文字".into();
        Ok(())
    }
    pub(super) async fn paste(&mut self, text: &str, mode: PasteMode) -> Result<()> {
        let state = self.state.as_ref().context("尚未取得桌面授權")?;
        if !state.live.load(Ordering::SeqCst) {
            bail!("桌面控制已中斷，請重新授權");
        }
        *state.data.lock().unwrap_or_else(|e| e.into_inner()) = Some(Arc::from(text.as_bytes()));
        tokio::time::timeout(
            Duration::from_secs(5),
            state.clipboard.set_selection(
                &state.session,
                SetSelectionOptions::default().set_mime_types(MIME_TYPES),
            ),
        )
        .await
        .context("寫入剪貼簿逾時")??;
        let keys: &[i32] = match mode {
            PasteMode::Normal => &[0xffe3, 0x76],
            PasteMode::Terminal => &[0xffe3, 0xffe1, 0x76],
        };
        balanced_keys(keys, |key, down| async move {
            tokio::time::timeout(
                Duration::from_secs(3),
                state.remote.notify_keyboard_keysym(
                    &state.session,
                    key,
                    if down {
                        KeyState::Pressed
                    } else {
                        KeyState::Released
                    },
                    NotifyKeyboardKeysymOptions::default(),
                ),
            )
            .await
            .context("鍵盤控制逾時")?
            .map_err(Into::into)
        })
        .await
    }
    pub(super) async fn close(&mut self) {
        if let Some(state) = self.state.take() {
            invalidate(&self.status, &state.live, &state.data, "桌面控制已關閉");
            state.monitor.abort();
            let _ = state.monitor.await;
            let _ = tokio::time::timeout(Duration::from_secs(3), state.session.close()).await;
        }
    }
}

fn invalidate(status: &StatusHandle, live: &AtomicBool, data: &Selection, message: &str) {
    // Take the same status lock used when granting authorization to avoid a stale
    // successful Start racing with a Closed or owner-change notification.
    let mut status = status.lock().unwrap_or_else(|e| e.into_inner());
    live.store(false, Ordering::SeqCst);
    *data.lock().unwrap_or_else(|e| e.into_inner()) = None;
    status.ready = false;
    status.message = message.into();
}

async fn monitor(
    remote: Arc<RemoteDesktop>,
    clipboard: Arc<Clipboard>,
    session: Arc<Session<RemoteDesktop>>,
    data: Selection,
    live: Arc<AtomicBool>,
    status: StatusHandle,
    ready: oneshot::Sender<Result<()>>,
) {
    let streams = async {
        Ok::<_, anyhow::Error>((
            session.receive_closed().await?,
            remote.receive_owner_changed().await?,
            clipboard
                .receive_selection_owner_changed::<RemoteDesktop>()
                .await?,
            clipboard
                .receive_selection_transfer::<RemoteDesktop>()
                .await?,
        ))
    }
    .await;
    let (closed, owner, selection, transfer) = match streams {
        Ok(streams) => streams,
        Err(error) => {
            let _ = ready.send(Err(error));
            invalidate(&status, &live, &data, "無法監聽桌面授權狀態");
            return;
        }
    };
    pin_mut!(closed, owner, selection, transfer);
    let session_id = serde_json::to_string(session.as_ref()).unwrap();
    let mut transfers = JoinSet::new();
    let _ = ready.send(Ok(()));
    loop {
        tokio::select! {
            _ = closed.next() => break,
            _ = owner.next() => break,
            event = selection.next() => match event {
                Some((event_session, details)) => {
                    if serde_json::to_string(&event_session).ok().as_deref() == Some(&session_id) && details.session_is_owner() == Some(false) {
                        *data.lock().unwrap_or_else(|e| e.into_inner()) = None;
                    }
                }
                None => break,
            },
            event = transfer.next() => match event {
                Some((event_session, mime, serial)) => {
                    if serde_json::to_string(&event_session).ok().as_deref() != Some(&session_id) { continue; }
                    let bytes = data.lock().unwrap_or_else(|e| e.into_inner()).clone();
                    let clipboard = clipboard.clone();
                    let session = session.clone();
                    transfers.spawn(async move {
                        let result = async {
                            let bytes = bytes.context("剪貼簿已變更")?;
                            if !MIME_TYPES.contains(&mime.as_str()) { bail!("不支援的剪貼簿格式"); }
                            let fd: OwnedFd = clipboard.selection_write(&session, serial).await?.into();
                            write_fd(fd, &bytes).await?;
                            Ok::<_, anyhow::Error>(())
                        };
                        let result = match tokio::time::timeout(Duration::from_secs(5), result).await {
                            Ok(result) => result,
                            Err(error) => Err(error.into()),
                        };
                        let done = tokio::time::timeout(
                            Duration::from_secs(3),
                            clipboard.selection_write_done(&session, serial, result.is_ok()),
                        ).await;
                        result.and(match done {
                            Ok(done) => done.map_err(Into::into),
                            Err(error) => Err(error.into()),
                        })
                    });
                }
                None => break,
            },
            result = transfers.join_next(), if !transfers.is_empty() => {
                if !matches!(result, Some(Ok(Ok(())))) { break; }
            },
        }
    }
    invalidate(
        &status,
        &live,
        &data,
        "桌面控制或剪貼簿已中斷，請重新授權；先查看電腦的貼上結果",
    );
    transfers.abort_all();
    while transfers.join_next().await.is_some() {}
}

/// Write a portal-owned pipe without ever blocking the input runtime thread.
async fn write_fd(fd: OwnedFd, mut bytes: &[u8]) -> io::Result<()> {
    unsafe extern "C" {
        fn fcntl(fd: i32, cmd: i32, ...) -> i32;
    }
    // Linux F_GETFL/F_SETFL/O_NONBLOCK. The FD stays owned throughout the calls.
    let flags = unsafe { fcntl(fd.as_raw_fd(), 3) };
    if flags == -1 || unsafe { fcntl(fd.as_raw_fd(), 4, flags | 0o4000) } == -1 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: File owns this stable descriptor until AsyncFd is dropped.
    let file = unsafe { AsyncFd::register(std::fs::File::from(fd)) }.map_err(io::Error::from)?;
    while !bytes.is_empty() {
        let mut writable = file.writable().await?;
        match writable.try_io(|fd| (&*fd.get_ref()).write(bytes)) {
            Ok(Ok(0)) => return Err(io::ErrorKind::WriteZero.into()),
            Ok(Ok(count)) => bytes = &bytes[count..],
            Ok(Err(error)) if error.kind() == io::ErrorKind::Interrupted => {}
            Ok(Err(error)) => return Err(error),
            Err(_) => {}
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use tokio::io::AsyncReadExt;

    #[tokio::test]
    async fn large_transfer_yields_instead_of_blocking_backend_runtime() {
        let (writer, reader) = std::os::unix::net::UnixStream::pair().unwrap();
        reader.set_nonblocking(true).unwrap();
        let mut reader = tokio::net::UnixStream::from_std(reader).unwrap();
        let bytes = "手機手寫輸入\n".repeat(100_000).into_bytes();
        let received = tokio::time::timeout(Duration::from_secs(3), async {
            let write = write_fd(writer.into(), &bytes);
            let read = async {
                // A synchronous writer deadlocks the single-thread runtime here.
                tokio::time::sleep(Duration::from_millis(10)).await;
                let mut output = Vec::new();
                reader.read_to_end(&mut output).await.unwrap();
                output
            };
            let (result, received) = tokio::join!(write, read);
            result.unwrap();
            received
        })
        .await
        .unwrap();
        assert_eq!(received, bytes);
    }

    #[tokio::test]
    async fn closed_receiver_reports_transfer_failure() {
        let (writer, reader) = std::os::unix::net::UnixStream::pair().unwrap();
        drop(reader);
        assert!(write_fd(writer.into(), b"payload").await.is_err());
    }

    #[test]
    fn invalidation_clears_sensitive_selection_and_authorization() {
        let status = crate::model::new_status();
        status.lock().unwrap().ready = true;
        let live = AtomicBool::new(true);
        let data: Selection = Arc::new(Mutex::new(Some(Arc::from(&b"private text"[..]))));
        invalidate(&status, &live, &data, "revoked");
        assert!(!status.lock().unwrap().ready);
        assert!(!live.load(Ordering::SeqCst));
        assert!(data.lock().unwrap().is_none());
    }
}
