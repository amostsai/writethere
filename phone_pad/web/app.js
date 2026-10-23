"use strict";
const text = document.querySelector("#text");
const mode = document.querySelector("#mode");
const send = document.querySelector("#send");
const clear = document.querySelector("#clear");
const count = document.querySelector("#count");
const connection = document.querySelector("#connection");
const result = document.querySelector("#result");
const code = document.querySelector("#code");
const pairButton = document.querySelector("#pair");
const pairResult = document.querySelector("#pair-result");
const disconnect = document.querySelector("#disconnect");
function stored(key) { try { return sessionStorage.getItem(key) || ""; } catch (_) { return ""; } }
function store(key, value) { try { sessionStorage.setItem(key, value); } catch (_) {} }
let invitation = new URLSearchParams(location.hash.slice(1)).get("token") || "";
if (invitation && invitation !== stored("phone-pad-token")) store("phone-pad-session", "");
invitation = invitation || stored("phone-pad-token");
store("phone-pad-token", invitation);
let sessionToken = stored("phone-pad-session");
history.replaceState(null, "", location.pathname);
let ready = false;
let busy = false;
let pairBusy = false;
let composing = false;
connection.textContent = invitation ? "請輸入電腦顯示的驗證碼配對" : "請掃描電腦上的 QR code 開啟此頁面";

function update() {
  document.querySelector("#pair-panel").hidden = !!sessionToken;
  document.querySelector("#pad-panel").hidden = !sessionToken;
  count.textContent = `${Array.from(text.value).length.toLocaleString()} / 20,000`;
  send.disabled = !sessionToken || !ready || busy || composing || text.value.length === 0;
  clear.disabled = busy;
  mode.disabled = busy;
  disconnect.disabled = busy;
  pairButton.disabled = pairBusy || !invitation;
  code.disabled = pairBusy || !invitation;
  send.textContent = busy ? "傳送中…" : "傳送到電腦";
  pairButton.textContent = pairBusy ? "正在驗證…" : "驗證並連線";
  connection.classList.toggle("offline", !ready);
}

function loseSession(message) {
  sessionToken = "";
  store("phone-pad-session", "");
  ready = false;
  code.value = "";
  connection.textContent = message;
  update();
}

async function api(path, options = {}, credential = sessionToken) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 10000);
  try {
    return await fetch(path, {...options, signal: controller.signal,
      headers: {"Authorization": `Bearer ${credential}`, ...options.headers}, cache: "no-store"});
  } finally { clearTimeout(timer); }
}

async function checkStatus() {
  if (!sessionToken) return;
  const checkedToken = sessionToken;
  try {
    const response = await api("/api/status");
    if (checkedToken !== sessionToken) return;
    if (response.status === 401) {
      loseSession("連線已釋放，請輸入電腦目前的驗證碼重新配對");
      return;
    }
    if (!response.ok) throw new Error("電腦服務暫時無法使用");
    const status = await response.json();
    if (checkedToken !== sessionToken) return;
    if (status.platform === "macos") {
      mode.options[0].textContent = "一般輸入框（⌘V）";
      mode.options[1].textContent = "終端機（⌘V）";
    }
    ready = status.ready;
    connection.textContent = status.message;
  } catch (error) {
    if (checkedToken !== sessionToken) return;
    ready = false;
    connection.textContent = error.name === "TypeError" || error.name === "AbortError"
      ? "連線中斷，請確認手機與電腦在同一區網，且電腦工具仍開啟" : error.message;
  }
  update();
}
async function poll() { await checkStatus(); setTimeout(poll, 2000); }

document.querySelector("#pair-form").addEventListener("submit", async event => {
  event.preventDefault();
  if (pairBusy || !invitation || !/^[0-9]{6}$/.test(code.value)) return;
  pairBusy = true;
  pairResult.textContent = "";
  update();
  try {
    const response = await api("/api/pair", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: code.value})}, invitation);
    if (response.status === 401 && !response.headers.get("Content-Type")?.includes("application/json")) {
      throw new Error("連線網址已失效，請重新掃描電腦上的 QR code");
    }
    const data = await response.json();
    if (!response.ok) { pairResult.textContent = data.message; return; }
    sessionToken = data.session_token;
    store("phone-pad-session", sessionToken);
    code.value = "";
    await checkStatus();
  } catch (error) {
    pairResult.textContent = error.name === "Error" ? error.message
      : "連線失敗；若名額已被占用，請在電腦中斷手機連線後重試";
  } finally { pairBusy = false; update(); }
});

disconnect.addEventListener("click", async () => {
  if (busy) return;
  const initiatingSession = sessionToken;
  busy = true;
  update();
  try {
    const response = await api("/api/disconnect", {method: "POST"});
    if (sessionToken !== initiatingSession) return;
    if (!response.ok && response.status !== 401) throw new Error();
    loseSession("已中斷連線，請查看電腦更新後的驗證碼");
  } catch (_) {
    if (sessionToken === initiatingSession) result.textContent = "無法確認是否已中斷；也可在電腦按「中斷手機連線」";
  }
  finally { busy = false; update(); }
});

text.addEventListener("input", update);
text.addEventListener("compositionstart", () => { composing = true; update(); });
text.addEventListener("compositionend", () => { composing = false; update(); });
clear.addEventListener("click", () => { text.value = ""; result.textContent = ""; update(); text.focus(); });
send.addEventListener("click", async () => {
  if (!ready || busy || composing || !text.value || !sessionToken) return;
  const initiatingSession = sessionToken;
  const requestId = Array.from(crypto.getRandomValues(new Uint8Array(16)),
    value => value.toString(16).padStart(2, "0")).join("");
  const payload = {request_id: requestId, text: text.value, mode: mode.value};
  busy = true;
  update();
  result.textContent = "";
  try {
    const response = await api("/api/send", {method: "POST",
      headers: {"Content-Type": "application/json"}, body: JSON.stringify(payload)});
    const data = await response.json();
    if (sessionToken !== initiatingSession) return;
    result.textContent = data.message || "傳送失敗，請先查看電腦";
    if (response.status === 401) loseSession(data.message);
    if (!response.ok) ready = false;
  } catch (_) {
    if (sessionToken === initiatingSession) {
      ready = false;
      result.textContent = "連線中斷，無法確認貼上結果。請先查看電腦；系統不會自動重送。";
    }
  } finally { busy = false; update(); }
});
update();
poll();
