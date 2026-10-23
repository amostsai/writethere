use serde::{Deserialize, Serialize};
use std::sync::{Arc, Mutex};
use tokio::sync::oneshot;

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum PasteMode {
    Normal,
    Terminal,
}

#[derive(Clone, Debug)]
pub struct BackendStatus {
    pub ready: bool,
    pub message: String,
}
pub type StatusHandle = Arc<Mutex<BackendStatus>>;

pub enum BackendCommand {
    Authorize,
    Paste {
        text: String,
        mode: PasteMode,
        reply: oneshot::Sender<Result<(), String>>,
    },
}

pub fn new_status() -> StatusHandle {
    Arc::new(Mutex::new(BackendStatus {
        ready: false,
        message: "尚未取得桌面控制授權".into(),
    }))
}
