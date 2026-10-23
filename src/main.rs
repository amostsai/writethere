#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod renderer;
mod startup;

use eframe::egui;
use std::{
    path::PathBuf,
    sync::{Arc, Mutex},
    time::Duration,
};
use tokio::sync::{mpsc, oneshot, watch};
use writethere::{
    model::{self, BackendCommand, StatusHandle},
    platform::Platform,
    service::{self, AppState},
    settings,
};

#[derive(Default)]
struct View {
    port: Option<u16>,
    error: String,
    authorizing: bool,
}
struct Bridge {
    app: AppState,
    view: Arc<Mutex<View>>,
    shutdown: watch::Sender<bool>,
    thread: Option<std::thread::JoinHandle<()>>,
}
impl Bridge {
    fn start(port: u16) -> Self {
        let status = model::new_status();
        let (commands, mut receiver) = mpsc::channel::<BackendCommand>(4);
        let app = AppState::new(status.clone(), commands);
        let view = Arc::new(Mutex::new(View::default()));
        let (shutdown, mut stop) = watch::channel(false);
        let state = app.clone();
        let display = view.clone();
        let thread = std::thread::spawn(move || {
            let rt = tokio::runtime::Builder::new_current_thread()
                .enable_all()
                .build()
                .expect("Tokio runtime");
            rt.block_on(async move {
                let listener = match tokio::net::TcpListener::bind(("0.0.0.0", port)).await {
                    Ok(listener) => listener,
                    Err(error) => {
                        display.lock().unwrap().error =
                            if error.kind() == std::io::ErrorKind::AddrInUse {
                                format!("連接埠 {port} 已被占用。請修改、儲存並重新啟動。")
                            } else {
                                format!("無法啟動連接埠 {port}：{error}")
                            };
                        return;
                    }
                };
                display.lock().unwrap().port = Some(port);
                let (web_stop, web_done) = oneshot::channel::<()>();
                let mut http_stop = stop.clone();
                let server = tokio::spawn(async move {
                    axum::serve(listener, service::router(state))
                        .with_graceful_shutdown(async move {
                            tokio::select! {_=web_done=>(),_=http_stop.changed()=>()}
                        })
                        .await
                });
                let mut platform = Platform::new(status.clone());
                let mut pending = Some(BackendCommand::Authorize);
                loop {
                    if *stop.borrow() {
                        break;
                    }
                    let command = if let Some(command) = pending.take() {
                        Some(command)
                    } else {
                        tokio::select! {
                            _=stop.changed()=>break,
                            command=receiver.recv()=>command,
                        }
                    };
                    let Some(command) = command else { break };
                    match command {
                        BackendCommand::Authorize => {
                            display.lock().unwrap().authorizing = true;
                            let result = tokio::select! {
                                _=stop.changed()=>None,
                                result=platform.authorize()=>Some(result),
                            };
                            display.lock().unwrap().authorizing = false;
                            match result {
                                None => break,
                                Some(Err(error)) => set_error(&status, error.to_string()),
                                _ => (),
                            }
                        }
                        BackendCommand::Paste { text, mode, reply } => {
                            // Do not cancel a chord between key-down and key-up.
                            // Platform bounds OS calls and balances every release.
                            let result = platform
                                .paste(&text, mode)
                                .await
                                .map_err(|error| error.to_string());
                            let _ = reply.send(result);
                        }
                    }
                }
                drop(receiver);
                platform.close().await;
                let _ = web_stop.send(());
                let mut server = server;
                if tokio::time::timeout(Duration::from_secs(5), &mut server)
                    .await
                    .is_err()
                {
                    server.abort();
                }
                display.lock().unwrap().port = None;
            });
        });
        Self {
            app,
            view,
            shutdown,
            thread: Some(thread),
        }
    }
}
impl Drop for Bridge {
    fn drop(&mut self) {
        set_error(&self.app.backend, "服務正在停止".into());
        let _ = self.shutdown.send(true);
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}
fn set_error(status: &StatusHandle, message: String) {
    let mut state = status.lock().unwrap();
    state.ready = false;
    state.message = message;
}

fn addresses() -> Vec<(String, String)> {
    let mut result = vec![];
    if let Ok(interfaces) = if_addrs::get_if_addrs() {
        for interface in interfaces {
            if interface.is_loopback()
                || [
                    "docker",
                    "veth",
                    "br-",
                    "virbr",
                    "tun",
                    "tap",
                    "tailscale",
                    "wg",
                ]
                .iter()
                .any(|prefix| interface.name.starts_with(prefix))
            {
                continue;
            }
            if let std::net::IpAddr::V4(ip) = interface.ip() {
                if ip.is_private() || ip.is_link_local() {
                    let ip = ip.to_string();
                    if !result.iter().any(|(_, value)| value == &ip) {
                        result.push((format!("{} · {}", interface.name, ip), ip));
                    }
                }
            }
        }
    }
    result.sort();
    result
}

struct PhonePad {
    bridge: Bridge,
    addresses: Vec<(String, String)>,
    selected: usize,
    port_text: String,
    settings_path: Option<PathBuf>,
    settings_message: String,
    qr_url: String,
    qr: Option<egui::TextureHandle>,
}
impl PhonePad {
    fn new(cc: &eframe::CreationContext<'_>) -> Self {
        let mut fonts = egui::FontDefinitions::default();
        let mut cjk =
            egui::FontData::from_static(include_bytes!("../assets/NotoSansCJK-Regular.ttc"));
        cjk.index = 3; // Traditional Chinese face in the Noto CJK collection.
        fonts.font_data.insert("noto-tc".into(), Arc::new(cjk));
        fonts
            .families
            .entry(egui::FontFamily::Proportional)
            .or_default()
            .push("noto-tc".into());
        fonts
            .families
            .entry(egui::FontFamily::Monospace)
            .or_default()
            .push("noto-tc".into());
        fonts.font_data.insert(
            "code-bold".into(),
            Arc::new(egui::FontData::from_static(include_bytes!(
                "../assets/NotoSansTC-Bold.ttf"
            ))),
        );
        fonts.families.insert(
            egui::FontFamily::Name("code-bold".into()),
            vec!["code-bold".into()],
        );
        cc.egui_ctx.set_fonts(fonts);
        cc.egui_ctx.set_visuals(egui::Visuals::light());
        cc.egui_ctx.style_mut(|style| {
            for (kind, size) in [
                (egui::TextStyle::Body, 18.),
                (egui::TextStyle::Button, 18.),
                (egui::TextStyle::Small, 16.),
                (egui::TextStyle::Heading, 26.),
                (egui::TextStyle::Monospace, 18.),
            ] {
                style.text_styles.insert(
                    kind,
                    egui::FontId::new(size, egui::FontFamily::Proportional),
                );
            }
            style.spacing.interact_size.y = 32.;
            style.spacing.button_padding = egui::vec2(10., 6.);
        });
        let path = settings::path();
        let (port, warning) = path.as_ref().map(|path| settings::load(path)).unwrap_or((
            settings::DEFAULT_PORT,
            Some("無法找到設定目錄，使用預設 39945".into()),
        ));
        Self {
            bridge: Bridge::start(port),
            addresses: addresses(),
            selected: 0,
            port_text: port.to_string(),
            settings_path: path.ok(),
            settings_message: warning.unwrap_or_default(),
            qr_url: String::new(),
            qr: None,
        }
    }
    fn update_qr(&mut self, ctx: &egui::Context, url: String) {
        if self.qr_url == url {
            return;
        }
        self.qr_url = url;
        self.qr = None;
        if self.qr_url.is_empty() {
            return;
        }
        if let Ok(code) = qrcode::QrCode::new(self.qr_url.as_bytes()) {
            let width = code.width();
            let full = width + 8;
            let mut pixels = vec![egui::Color32::WHITE; full * full];
            for y in 0..width {
                for x in 0..width {
                    if code[(x, y)] == qrcode::Color::Dark {
                        pixels[(y + 4) * full + x + 4] = egui::Color32::BLACK;
                    }
                }
            }
            self.qr = Some(ctx.load_texture(
                "pair-qr",
                egui::ColorImage::new([full, full], pixels),
                egui::TextureOptions::NEAREST,
            ));
        }
    }
}
impl eframe::App for PhonePad {
    fn update(&mut self, ctx: &egui::Context, _: &mut eframe::Frame) {
        ctx.request_repaint_after(Duration::from_millis(300));
        let (port, error, authorizing) = {
            let view = self.bridge.view.lock().unwrap();
            (view.port, view.error.clone(), view.authorizing)
        };
        let snapshot = self.bridge.app.snapshot();
        let backend = self.bridge.app.backend.lock().unwrap().clone();
        let url = port
            .and_then(|port| {
                self.addresses
                    .get(self.selected)
                    .map(|(_, ip)| format!("http://{ip}:{port}/#token={}", snapshot.invitation))
            })
            .unwrap_or_default();
        self.update_qr(ctx, url);
        egui::CentralPanel::default().show(ctx,|ui| {egui::ScrollArea::vertical().show(ui,|ui| {
            ui.add_space(8.);ui.heading("WriteThere");ui.label("手機掃碼，寫好後傳到電腦游標所在的位置。");ui.add_space(12.);
            if !error.is_empty(){ui.colored_label(egui::Color32::DARK_RED,&error);}else{ui.label(if port.is_some(){"區網服務已啟動"}else{"正在啟動區網服務…"});}
            ui.horizontal(|ui| {
                ui.label("連接埠");ui.add(egui::TextEdit::singleline(&mut self.port_text).desired_width(100.));
                if ui.button("儲存").clicked(){
                    self.settings_message=match settings::parse_port(&self.port_text).and_then(|port| {
                        let path=self.settings_path.as_ref().ok_or_else(||anyhow::anyhow!("無法找到設定目錄"))?;
                        settings::save(path,port)?;self.port_text=port.to_string();Ok(port)
                    }) {Ok(port)=>format!("已儲存 {port}，下次啟動套用"),Err(error)=>format!("儲存失敗：{error}")};
                }
            });
            ui.small(if self.settings_message.is_empty(){"儲存後於下次啟動套用"}else{&self.settings_message});
            ui.add_space(8.);
            ui.horizontal(|ui| {
                egui::ComboBox::from_id_salt("interface").selected_text(self.addresses.get(self.selected).map(|(label,_)|label.as_str()).unwrap_or("尚未找到區網 IPv4 位址"))
                    .show_ui(ui,|ui|{for (index,(name,_)) in self.addresses.iter().enumerate(){ui.selectable_value(&mut self.selected,index,name);}});
                if ui.button("重新偵測").clicked(){self.addresses=addresses();self.selected=0;}
            });
            ui.vertical_centered(|ui| {
                if let Some(texture)=&self.qr {ui.add(egui::Image::new(texture).fit_to_exact_size(egui::vec2(232.,232.)));}
                ui.add(egui::Label::new(&self.qr_url).wrap().selectable(true));
                ui.add_space(8.);
                ui.label(egui::RichText::new(format!("配對驗證碼：{}",snapshot.pin))
                    .font(egui::FontId::new(32.,egui::FontFamily::Name("code-bold".into())))
                    .strong());
            });
            ui.add_space(8.);ui.label(&backend.message);
            ui.label(if snapshot.paired{"手機已連線（限一支）"}else{"等待手機輸入驗證碼配對"});
            if ui.add_enabled(snapshot.paired,egui::Button::new("中斷手機連線／更新驗證碼")).clicked(){
                let state=self.bridge.app.clone();std::thread::spawn(move||{let rt=tokio::runtime::Builder::new_current_thread().enable_all().build().unwrap();rt.block_on(state.disconnect());});
            }
            ui.add_space(10.);ui.small("手機與電腦須在同一區網。傳送會取代剪貼簿內容。\n保持此視窗開啟；接收文字時不會搶走焦點。");
            ui.add_space(8.);
            ui.horizontal(|ui| {
                if ui.add_enabled(port.is_some()&&!authorizing,egui::Button::new("重新授權")).clicked(){self.bridge.app.authorize();}
            });
            ui.add_space(12.);ui.separator();
            ui.small(concat!("v",env!("CARGO_PKG_VERSION")));
        });});
    }
}
fn main() -> std::process::ExitCode {
    let _instance = match writethere::instance::InstanceGuard::acquire() {
        Ok(Some(guard)) => guard,
        Ok(None) => return std::process::ExitCode::SUCCESS,
        Err(error) => {
            startup::report_early_failure(&format!("WriteThere 無法檢查執行狀態：{error}"));
            return std::process::ExitCode::FAILURE;
        }
    };
    let diagnostics = startup::Diagnostics::initialize();
    match run(&diagnostics) {
        Ok(()) => {
            diagnostics.record("application exited normally");
            std::process::ExitCode::SUCCESS
        }
        Err(error) => {
            diagnostics.failure(&format!("{error:#?}"));
            std::process::ExitCode::FAILURE
        }
    }
}

fn run(diagnostics: &startup::Diagnostics) -> eframe::Result {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title("WriteThere")
            .with_app_id("tw.local.PhoneHandwritingPad")
            .with_inner_size([520., 900.])
            .with_min_inner_size([440., 640.]),
        ..renderer::options(diagnostics)
    };
    eframe::run_native(
        "tw.local.PhoneHandwritingPad",
        options,
        Box::new(|cc| {
            diagnostics.record("graphics context created; initializing application");
            let app = PhonePad::new(cc);
            diagnostics.record("application initialized; entering event loop");
            Ok(Box::new(app))
        }),
    )
}
