//! Interactive verification only: real OS backend, ephemeral localhost listener.
use serde_json::json;
use std::future::IntoFuture;
use tokio::io::AsyncReadExt;
use writethere::{
    model::{self, BackendCommand},
    platform::Platform,
    service::{self, AppState},
};

#[tokio::main(flavor = "current_thread")]
async fn main() -> anyhow::Result<()> {
    let status = model::new_status();
    let (tx, mut rx) = tokio::sync::mpsc::channel(4);
    let state = AppState::new(status.clone(), tx);
    let listener = tokio::net::TcpListener::bind(("127.0.0.1", 0)).await?;
    let port = listener.local_addr()?.port();
    let snapshot = state.snapshot();
    let server = tokio::spawn(axum::serve(listener, service::router(state)).into_future());
    println!(
        "{}",
        json!({"port":port,"token":snapshot.invitation,"code":snapshot.pin})
    );
    let mut platform = Platform::new(status.clone());
    if let Err(error) = platform.authorize().await {
        println!("{}", json!({"ready":false,"error":error.to_string()}));
        platform.close().await;
        server.abort();
        return Ok(());
    }
    println!("{}", json!({"ready":true}));
    let mut stdin = tokio::io::stdin();
    let mut buffer = vec![];
    loop {
        tokio::select! {
            _=stdin.read_to_end(&mut buffer)=>break,
            command=rx.recv()=>match command {
                Some(BackendCommand::Paste{text,mode,reply})=>{let result=platform.paste(&text,mode).await.map_err(|e|e.to_string());let _=reply.send(result);}
                _=>break,
            }
        }
    }
    platform.close().await;
    server.abort();
    Ok(())
}
