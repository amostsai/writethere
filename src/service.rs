use crate::model::{BackendCommand, PasteMode, StatusHandle};
use axum::{
    body::Body,
    extract::{DefaultBodyLimit, State},
    http::{header, Request, StatusCode},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
    Json, Router,
};
use rand::{rngs::OsRng, Rng, RngCore};
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
    time::{Duration, Instant},
};
use subtle::ConstantTimeEq;
use tokio::sync::{mpsc, oneshot};

const LEASE: Duration = Duration::from_secs(30);
const MAX_REQUESTS: usize = 10_000;
fn secret() -> String {
    let mut bytes = [0u8; 32];
    OsRng.fill_bytes(&mut bytes);
    bytes.iter().map(|b| format!("{b:02x}")).collect()
}
fn pin() -> String {
    format!("{:06}", OsRng.gen_range(0..1_000_000))
}
fn equal(a: &str, b: &str) -> bool {
    a.as_bytes().ct_eq(b.as_bytes()).into()
}

struct Owner {
    token: String,
    seen: Instant,
}
#[derive(Clone)]
struct Record {
    digest: Vec<u8>,
    code: StatusCode,
    message: &'static str,
}
struct Sessions {
    invitation: String,
    pin: String,
    owner: Option<Owner>,
    failures: Vec<Instant>,
    blocked_until: Option<Instant>,
    records: HashMap<String, Record>,
    sending: bool,
}
impl Sessions {
    fn release(&mut self) {
        self.owner = None;
        self.failures.clear();
        self.blocked_until = None;
        let old = self.pin.clone();
        while self.pin == old {
            self.pin = pin();
        }
    }
    fn expire(&mut self) {
        if !self.sending
            && self
                .owner
                .as_ref()
                .is_some_and(|o| o.seen.elapsed() >= LEASE)
        {
            self.release();
        }
    }
    fn owns(&mut self, bearer: &str) -> bool {
        self.expire();
        self.owner.as_ref().is_some_and(|o| equal(&o.token, bearer))
    }
}

#[derive(Clone)]
pub struct AppState {
    inner: Arc<Mutex<Sessions>>,
    pub backend: StatusHandle,
    commands: mpsc::Sender<BackendCommand>,
    send_lock: Arc<tokio::sync::Mutex<()>>,
}
#[derive(Clone)]
pub struct Snapshot {
    pub invitation: String,
    pub pin: String,
    pub paired: bool,
}
impl AppState {
    pub fn new(backend: StatusHandle, commands: mpsc::Sender<BackendCommand>) -> Self {
        Self {
            inner: Arc::new(Mutex::new(Sessions {
                invitation: secret(),
                pin: pin(),
                owner: None,
                failures: vec![],
                blocked_until: None,
                records: HashMap::new(),
                sending: false,
            })),
            backend,
            commands,
            send_lock: Arc::new(tokio::sync::Mutex::new(())),
        }
    }
    pub fn snapshot(&self) -> Snapshot {
        let mut inner = self.inner.lock().unwrap();
        inner.expire();
        Snapshot {
            invitation: inner.invitation.clone(),
            pin: inner.pin.clone(),
            paired: inner.owner.is_some(),
        }
    }
    pub fn invitation(&self) -> String {
        self.snapshot().invitation
    }
    pub fn pairing_code(&self) -> String {
        self.snapshot().pin
    }
    pub async fn disconnect(&self) {
        let _guard = self.send_lock.lock().await;
        self.inner.lock().unwrap().release();
    }
    pub fn authorize(&self) -> bool {
        self.commands.try_send(BackendCommand::Authorize).is_ok()
    }
}

fn message(code: StatusCode, text: impl Into<String>) -> Response {
    (code, Json(json!({"message":text.into()}))).into_response()
}
fn bearer(req: &Request<Body>) -> &str {
    req.headers()
        .get(header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "))
        .unwrap_or("")
}

async fn security(State(app): State<AppState>, req: Request<Body>, next: Next) -> Response {
    let rejection = {
        let origin = req
            .headers()
            .get(header::ORIGIN)
            .and_then(|v| v.to_str().ok());
        let expected = format!(
            "http://{}",
            req.headers()
                .get(header::HOST)
                .and_then(|v| v.to_str().ok())
                .unwrap_or("")
        );
        if origin.is_some_and(|origin| origin != expected) {
            Some(message(StatusCode::FORBIDDEN, "不允許跨網站請求"))
        } else if req.uri().path().starts_with("/api/") {
            let token = bearer(&req);
            let mut inner = app.inner.lock().unwrap();
            if req.uri().path() == "/api/pair" {
                if !equal(token, &inner.invitation) {
                    Some(message(
                        StatusCode::UNAUTHORIZED,
                        "連線網址已失效，請重新掃描 QR code",
                    ))
                } else {
                    None
                }
            } else if !inner.owns(token) {
                Some(message(
                    StatusCode::UNAUTHORIZED,
                    "連線已釋放，請輸入電腦目前的驗證碼重新配對",
                ))
            } else {
                inner.owner.as_mut().unwrap().seen = Instant::now();
                None
            }
        } else {
            None
        }
    };
    let mut response = if let Some(response) = rejection {
        response
    } else {
        next.run(req).await
    };
    for (key,value) in [
        ("cache-control","no-store"), ("referrer-policy","no-referrer"), ("x-content-type-options","nosniff"),
        ("content-security-policy","default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
    ] { response.headers_mut().insert(key, value.parse().unwrap()); }
    response
}

pub fn router(app: AppState) -> Router {
    Router::new()
        .route(
            "/",
            get(|| async { axum::response::Html(include_str!("../phone_pad/web/index.html")) }),
        )
        .route(
            "/app.js",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/javascript; charset=utf-8")],
                    include_str!("../phone_pad/web/app.js"),
                )
            }),
        )
        .route(
            "/style.css",
            get(|| async {
                (
                    [(header::CONTENT_TYPE, "text/css; charset=utf-8")],
                    include_str!("../phone_pad/web/style.css"),
                )
            }),
        )
        .route("/api/pair", post(pair_phone))
        .route("/api/disconnect", post(disconnect_phone))
        .route("/api/status", get(status))
        .route("/api/send", post(send))
        .layer(DefaultBodyLimit::max(128 * 1024))
        .layer(middleware::from_fn_with_state(app.clone(), security))
        .with_state(app)
}

#[derive(Deserialize)]
struct Pair {
    code: String,
}
async fn pair_phone(
    State(app): State<AppState>,
    body: Result<Json<Pair>, axum::extract::rejection::JsonRejection>,
) -> Response {
    let Ok(Json(data)) = body else {
        return message(StatusCode::BAD_REQUEST, "請輸入 6 位數驗證碼");
    };
    if data.code.len() != 6 || !data.code.bytes().all(|c| c.is_ascii_digit()) {
        return message(StatusCode::BAD_REQUEST, "請輸入 6 位數驗證碼");
    }
    let mut inner = app.inner.lock().unwrap();
    inner.expire();
    if inner.owner.is_some() {
        return message(
            StatusCode::CONFLICT,
            "已有手機連線，請先在電腦中斷連線或等待其斷線 30 秒",
        );
    }
    inner.failures.retain(|stamp| stamp.elapsed() < LEASE);
    if inner
        .blocked_until
        .is_some_and(|until| until > Instant::now())
    {
        let mut response = message(
            StatusCode::TOO_MANY_REQUESTS,
            "驗證嘗試過多，請於 30 秒後重試",
        );
        response
            .headers_mut()
            .insert("retry-after", "30".parse().unwrap());
        return response;
    }
    if !equal(&data.code, &inner.pin) {
        inner.failures.push(Instant::now());
        if inner.failures.len() >= 5 {
            inner.blocked_until = Some(Instant::now() + LEASE);
        }
        return message(
            StatusCode::UNAUTHORIZED,
            "驗證碼錯誤，請查看電腦目前顯示的 6 位數字",
        );
    }
    let token = secret();
    inner.owner = Some(Owner {
        token: token.clone(),
        seen: Instant::now(),
    });
    inner.failures.clear();
    inner.blocked_until = None;
    Json(json!({"session_token":token,"message":"配對成功"})).into_response()
}

async fn status(State(app): State<AppState>) -> Response {
    let status = app.backend.lock().unwrap().clone();
    Json(json!({"ready":status.ready,"message":status.message,"platform":std::env::consts::OS}))
        .into_response()
}
async fn disconnect_phone(State(app): State<AppState>, req: Request<Body>) -> Response {
    let token = bearer(&req).to_owned();
    let _guard = app.send_lock.lock().await;
    let mut inner = app.inner.lock().unwrap();
    if !inner.owns(&token) {
        return message(StatusCode::UNAUTHORIZED, "連線已釋放");
    }
    inner.release();
    message(StatusCode::OK, "已中斷連線；請查看電腦更新後的驗證碼")
}

#[derive(Deserialize)]
struct SendText {
    request_id: String,
    text: String,
    mode: PasteMode,
}
async fn send(
    State(app): State<AppState>,
    headers: axum::http::HeaderMap,
    body: Result<Json<SendText>, axum::extract::rejection::JsonRejection>,
) -> Response {
    let Ok(Json(data)) = body else {
        return message(StatusCode::BAD_REQUEST, "文字或傳送格式不正確");
    };
    if data.text.is_empty()
        || data.text.chars().count() > 20000
        || data.text.contains('\0')
        || data.request_id.is_empty()
        || data.request_id.len() > 80
        || !data
            .request_id
            .bytes()
            .all(|c| c.is_ascii_alphanumeric() || c == b'_' || c == b'-')
    {
        return message(
            StatusCode::BAD_REQUEST,
            "文字需為 1–20,000 字，且傳送格式必須正確",
        );
    }
    let token = headers
        .get(header::AUTHORIZATION)
        .and_then(|h| h.to_str().ok())
        .and_then(|h| h.strip_prefix("Bearer "))
        .unwrap_or("")
        .to_owned();
    // Hyper may cancel a response future after a client disconnects. An owned
    // delivery task must finish accounting for the desktop side effect anyway.
    tokio::spawn(deliver(app, token, data))
        .await
        .unwrap_or_else(|_| message(StatusCode::BAD_GATEWAY, "無法確認貼上結果，請先查看電腦"))
}
async fn deliver(app: AppState, token: String, data: SendText) -> Response {
    let _guard = app.send_lock.lock().await;
    let mut hash = Sha256::new();
    hash.update(if data.mode == PasteMode::Normal {
        b"normal\0".as_slice()
    } else {
        b"terminal\0".as_slice()
    });
    hash.update(data.text.as_bytes());
    let digest = hash.finalize().to_vec();
    {
        let mut inner = app.inner.lock().unwrap();
        if !inner.owns(&token) {
            return message(StatusCode::UNAUTHORIZED, "連線已釋放，請重新配對");
        }
        if let Some(record) = inner.records.get(&data.request_id) {
            return if record.digest != digest {
                message(StatusCode::CONFLICT, "請求識別碼已使用")
            } else {
                message(record.code, record.message)
            };
        }
        let status = app.backend.lock().unwrap().clone();
        if !status.ready {
            return message(StatusCode::SERVICE_UNAVAILABLE, status.message);
        }
        if inner.records.len() >= MAX_REQUESTS {
            return message(
                StatusCode::SERVICE_UNAVAILABLE,
                "本次工作階段已達上限，請重新啟動並掃碼",
            );
        }
        inner.records.insert(
            data.request_id.clone(),
            Record {
                digest: digest.clone(),
                code: StatusCode::BAD_GATEWAY,
                message: "無法確認貼上結果；請先查看電腦，避免重複傳送",
            },
        );
        inner.sending = true;
    }
    let (reply, receiver) = oneshot::channel();
    let queued = app
        .commands
        .send(BackendCommand::Paste {
            text: data.text,
            mode: data.mode,
            reply,
        })
        .await
        .is_ok();
    let success = queued && matches!(receiver.await, Ok(Ok(())));
    let mut inner = app.inner.lock().unwrap();
    inner.sending = false;
    if let Some(owner) = &mut inner.owner {
        owner.seen = Instant::now()
    }
    let record = inner.records.get_mut(&data.request_id).unwrap();
    if success {
        record.code = StatusCode::OK;
        record.message = "已送出貼上指令";
    }
    message(record.code, record.message)
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::{body::Body, http::Request};
    use http_body_util::BodyExt;
    use serde_json::Value;
    use std::sync::atomic::{AtomicUsize, Ordering};
    use tower::ServiceExt;

    fn fixture() -> (AppState, Arc<AtomicUsize>) {
        let status = crate::model::new_status();
        status.lock().unwrap().ready = true;
        let (tx, mut rx) = tokio::sync::mpsc::channel(4);
        let calls = Arc::new(AtomicUsize::new(0));
        let count = calls.clone();
        tokio::spawn(async move {
            while let Some(command) = rx.recv().await {
                if let BackendCommand::Paste { reply, .. } = command {
                    count.fetch_add(1, Ordering::SeqCst);
                    let _ = reply.send(Ok(()));
                }
            }
        });
        (AppState::new(status, tx), calls)
    }

    async fn request(
        app: &AppState,
        path: &str,
        token: &str,
        body: Option<Value>,
    ) -> (StatusCode, Value) {
        let req = Request::builder()
            .uri(path)
            .method(if body.is_some() { "POST" } else { "GET" })
            .header("Authorization", format!("Bearer {token}"))
            .header("Content-Type", "application/json")
            .body(Body::from(body.map(|b| b.to_string()).unwrap_or_default()))
            .unwrap();
        let response = router(app.clone()).oneshot(req).await.unwrap();
        let status = response.status();
        let bytes = response.into_body().collect().await.unwrap().to_bytes();
        (
            status,
            serde_json::from_slice(&bytes).unwrap_or(Value::Null),
        )
    }
    async fn pair(app: &AppState) -> String {
        let (status, value) = request(
            app,
            "/api/pair",
            &app.invitation(),
            Some(json!({"code":app.pairing_code()})),
        )
        .await;
        assert_eq!(status, StatusCode::OK);
        value["session_token"].as_str().unwrap().to_owned()
    }
    fn payload() -> Value {
        json!({"text":"  繁體😊\nEnglish\n", "mode":"normal", "request_id":"first"})
    }

    #[tokio::test]
    async fn qr_is_not_a_send_credential_and_only_one_phone_pairs() {
        let (app, _) = fixture();
        assert_eq!(
            request(&app, "/api/send", &app.invitation(), Some(payload()))
                .await
                .0,
            StatusCode::UNAUTHORIZED
        );
        let owner = pair(&app).await;
        assert_ne!(owner, app.invitation());
        assert_eq!(
            request(
                &app,
                "/api/pair",
                &app.invitation(),
                Some(json!({"code":app.pairing_code()}))
            )
            .await
            .0,
            StatusCode::CONFLICT
        );
    }
    #[tokio::test]
    async fn duplicate_is_attempted_once_and_conflicting_id_rejected() {
        let (app, calls) = fixture();
        let owner = pair(&app).await;
        let (a, b) = tokio::join!(
            request(&app, "/api/send", &owner, Some(payload())),
            request(&app, "/api/send", &owner, Some(payload()))
        );
        assert_eq!(a.0, StatusCode::OK);
        assert_eq!(b.0, StatusCode::OK);
        assert_eq!(calls.load(Ordering::SeqCst), 1);
        let mut other = payload();
        other["text"] = json!("different");
        assert_eq!(
            request(&app, "/api/send", &owner, Some(other)).await.0,
            StatusCode::CONFLICT
        );
    }
    #[tokio::test]
    async fn revoke_rejects_old_phone_and_rotates_pin() {
        let (app, _) = fixture();
        let pin = app.pairing_code();
        let owner = pair(&app).await;
        app.disconnect().await;
        assert_ne!(app.pairing_code(), pin);
        assert_eq!(
            request(&app, "/api/status", &owner, None).await.0,
            StatusCode::UNAUTHORIZED
        );
        let _ = pair(&app).await;
    }
    #[tokio::test]
    async fn wrong_pin_rate_limit_and_expired_slot() {
        let (app, _) = fixture();
        let wrong = if app.pairing_code() == "000000" {
            "111111"
        } else {
            "000000"
        };
        for _ in 0..5 {
            assert_eq!(
                request(
                    &app,
                    "/api/pair",
                    &app.invitation(),
                    Some(json!({"code":wrong}))
                )
                .await
                .0,
                StatusCode::UNAUTHORIZED
            );
        }
        assert_eq!(
            request(
                &app,
                "/api/pair",
                &app.invitation(),
                Some(json!({"code":app.pairing_code()}))
            )
            .await
            .0,
            StatusCode::TOO_MANY_REQUESTS
        );
        app.inner.lock().unwrap().blocked_until = Some(Instant::now() - Duration::from_secs(1));
        let old = pair(&app).await;
        app.inner.lock().unwrap().owner.as_mut().unwrap().seen -= Duration::from_secs(31);
        assert_eq!(
            request(&app, "/api/status", &old, None).await.0,
            StatusCode::UNAUTHORIZED
        );
        let _ = pair(&app).await;
    }
    #[tokio::test]
    async fn preserves_actual_utf8_text_and_terminal_mode() {
        let status = crate::model::new_status();
        status.lock().unwrap().ready = true;
        let (tx, mut rx) = mpsc::channel(2);
        let app = AppState::new(status, tx);
        let owner = pair(&app).await;
        let task = tokio::spawn(async move {
            let BackendCommand::Paste { text, mode, reply } = rx.recv().await.unwrap() else {
                panic!("wrong command")
            };
            assert_eq!(text, "  繁體😊\nEnglish\n");
            assert_eq!(mode, PasteMode::Terminal);
            reply.send(Ok(())).unwrap();
        });
        let mut data = payload();
        data["mode"] = json!("terminal");
        assert_eq!(
            request(&app, "/api/send", &owner, Some(data)).await.0,
            StatusCode::OK
        );
        task.await.unwrap();
    }
    #[tokio::test]
    async fn invalid_text_mode_and_request_id_never_reach_backend() {
        let (app, calls) = fixture();
        let owner = pair(&app).await;
        for (field, value) in [
            ("text", json!("")),
            ("text", json!("a\u{0}b")),
            ("text", json!("a".repeat(20001))),
            ("mode", json!("bad")),
            ("request_id", json!("")),
            ("request_id", json!("中文")),
        ] {
            let mut data = payload();
            data[field] = value;
            assert_eq!(
                request(&app, "/api/send", &owner, Some(data)).await.0,
                StatusCode::BAD_REQUEST
            );
        }
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
    #[tokio::test]
    async fn permission_revocation_blocks_send() {
        let (app, calls) = fixture();
        let owner = pair(&app).await;
        app.backend.lock().unwrap().ready = false;
        assert_eq!(
            request(&app, "/api/send", &owner, Some(payload())).await.0,
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(calls.load(Ordering::SeqCst), 0);
    }
    #[tokio::test]
    async fn cross_origin_is_rejected_and_assets_never_reveal_secrets() {
        let (app, _) = fixture();
        let owner = pair(&app).await;
        let req = Request::builder()
            .uri("/api/status")
            .header("Host", "localhost:39945")
            .header("Origin", "http://untrusted.example")
            .header("Authorization", format!("Bearer {owner}"))
            .body(Body::empty())
            .unwrap();
        assert_eq!(
            router(app.clone()).oneshot(req).await.unwrap().status(),
            StatusCode::FORBIDDEN
        );
        let response = router(app.clone())
            .oneshot(Request::builder().uri("/").body(Body::empty()).unwrap())
            .await
            .unwrap();
        assert_eq!(response.headers()["cache-control"], "no-store");
        let text = String::from_utf8(
            response
                .into_body()
                .collect()
                .await
                .unwrap()
                .to_bytes()
                .to_vec(),
        )
        .unwrap();
        assert!(!text.contains(&app.invitation()));
        assert!(!text.contains(&owner));
    }
    #[tokio::test]
    async fn failed_paste_is_not_retried_with_the_same_identifier() {
        let status = crate::model::new_status();
        status.lock().unwrap().ready = true;
        let (tx, mut rx) = mpsc::channel(2);
        let app = AppState::new(status, tx);
        let owner = pair(&app).await;
        let task = tokio::spawn(async move {
            let BackendCommand::Paste { reply, .. } = rx.recv().await.unwrap() else {
                panic!("wrong command")
            };
            reply.send(Err("desktop failed".into())).unwrap();
            // If a duplicate gets requeued, the test cannot complete normally.
            assert!(tokio::time::timeout(Duration::from_millis(30), rx.recv())
                .await
                .is_err());
        });
        for _ in 0..2 {
            assert_eq!(
                request(&app, "/api/send", &owner, Some(payload())).await.0,
                StatusCode::BAD_GATEWAY
            );
        }
        task.await.unwrap();
    }
    #[tokio::test]
    async fn leading_zero_pin_and_phone_disconnect() {
        let (app, _) = fixture();
        app.inner.lock().unwrap().pin = "012345".into();
        let owner = pair(&app).await;
        assert_eq!(
            request(&app, "/api/disconnect", &owner, Some(json!({})))
                .await
                .0,
            StatusCode::OK
        );
        assert_eq!(
            request(&app, "/api/status", &owner, None).await.0,
            StatusCode::UNAUTHORIZED
        );
        assert_ne!(app.pairing_code(), "012345");
    }

    #[tokio::test]
    async fn cooldown_lasts_thirty_seconds_after_the_fifth_failure() {
        let (app, _) = fixture();
        {
            let mut inner = app.inner.lock().unwrap();
            inner.failures = [29, 20, 10, 5]
                .map(|seconds| Instant::now() - Duration::from_secs(seconds))
                .to_vec();
        }
        let wrong = if app.pairing_code() == "000000" {
            "111111"
        } else {
            "000000"
        };
        assert_eq!(
            request(
                &app,
                "/api/pair",
                &app.invitation(),
                Some(json!({"code":wrong}))
            )
            .await
            .0,
            StatusCode::UNAUTHORIZED
        );
        app.inner.lock().unwrap().failures[0] = Instant::now() - Duration::from_secs(31);
        assert_eq!(
            request(
                &app,
                "/api/pair",
                &app.invitation(),
                Some(json!({"code":app.pairing_code()}))
            )
            .await
            .0,
            StatusCode::TOO_MANY_REQUESTS
        );
    }
}
