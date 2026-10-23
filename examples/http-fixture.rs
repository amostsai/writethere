//! Test-only HTTP fixture. Never linked into the distributed desktop binary.
use serde_json::{json, Value};
use tokio::io::{AsyncBufReadExt, BufReader};
use writethere::{
    model::{self, BackendCommand},
    service::{self, AppState},
};

fn announce(state: &AppState, port: u16) {
    println!(
        "{}",
        json!({"port":port,"token":state.invitation(),"code":state.pairing_code()})
    );
}
#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    let status = model::new_status();
    {
        let mut status = status.lock().unwrap();
        status.ready = true;
        status.message = "已授權，可以傳送文字".into();
    }
    let (tx, mut rx) = tokio::sync::mpsc::channel(4);
    let state = AppState::new(status.clone(), tx);
    tokio::spawn(async move {
        while let Some(command) = rx.recv().await {
            if let BackendCommand::Paste { reply, .. } = command {
                tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                let _ = reply.send(Ok(()));
            }
        }
    });
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0)).await?;
    let port = listener.local_addr()?.port();
    let server = tokio::spawn(axum::serve(listener, service::router(state.clone())).into_future());
    announce(&state, port);
    let mut lines = BufReader::new(tokio::io::stdin()).lines();
    while let Some(line) = lines.next_line().await? {
        let command: Value = serde_json::from_str(&line)?;
        match command["action"].as_str().unwrap_or("") {
            "disconnect" => state.disconnect().await,
            "status" => {
                let mut status = status.lock().unwrap();
                status.ready = command["ready"].as_bool().unwrap();
                status.message = command["message"].as_str().unwrap().into();
            }
            _ => break,
        }
        announce(&state, port);
    }
    server.abort();
    Ok(())
}
use std::future::IntoFuture;
