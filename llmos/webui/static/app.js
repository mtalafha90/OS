/* LLM-OS Web UI — Desktop application logic */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let ws = null;
let wsReady = false;
let pendingThinkingEl = null;

// ── Markdown renderer (minimal, no deps) ─────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return "";
  let html = text
    // Escape HTML
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    // Code blocks
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code>${code.trim()}</code></pre>`)
    // Inline code
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    // Bold
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    // Italic
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    // Headers
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    // Unordered lists
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>")
    // Ordered lists
    .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
    // Horizontal rule
    .replace(/^---$/gm, "<hr/>")
    // Line breaks (preserve blank lines as paragraph breaks)
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br/>");

  return `<p>${html}</p>`;
}

// ── WebSocket connection ──────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/chat`);

  ws.onopen = () => {
    wsReady = true;
    console.log("[llmos] WebSocket connected");
  };

  ws.onclose = () => {
    wsReady = false;
    setTimeout(connectWS, 2000);
  };

  ws.onerror = (e) => {
    console.error("[llmos] WebSocket error", e);
  };

  ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    handleServerMessage(data);
  };
}

function handleServerMessage(data) {
  removePendingThinking();

  switch (data.type) {
    case "thinking":
      pendingThinkingEl = appendMessage("Thinking…", "thinking-msg");
      break;

    case "tool_call": {
      const argStr = Object.entries(data.args || {})
        .map(([k, v]) => `${k}=${JSON.stringify(v)}`)
        .join(", ");
      appendMessage(`↳ ${data.name}(${argStr})`, "tool-call-msg");
      break;
    }

    case "tool_result":
      if (data.result) {
        appendMessage(data.result, "tool-msg");
      }
      break;

    case "response":
      appendAIMessage(data.content);
      setInputEnabled(true);
      break;

    case "cleared":
      document.getElementById("chat-messages").innerHTML =
        `<div class="msg system-msg"><strong>LLM-OS</strong> — History cleared.</div>`;
      break;

    case "model_switched":
      document.getElementById("model-badge").textContent = data.model;
      appendMessage(`Switched to model: ${data.model}`, "system-msg");
      break;

    case "error":
      appendMessage(`Error: ${data.message}`, "system-msg");
      setInputEnabled(true);
      break;
  }

  scrollToBottom();
}

// ── Message rendering ─────────────────────────────────────────────────────────
function appendMessage(content, cssClass) {
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = `msg ${cssClass}`;
  el.textContent = content;
  container.appendChild(el);
  scrollToBottom();
  return el;
}

function appendAIMessage(content) {
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = "msg ai-msg";
  el.innerHTML = renderMarkdown(content);
  container.appendChild(el);
  scrollToBottom();
}

function appendUserMessage(content) {
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = "msg user-msg";
  el.textContent = content;
  container.appendChild(el);
  scrollToBottom();
}

function removePendingThinking() {
  if (pendingThinkingEl) {
    pendingThinkingEl.remove();
    pendingThinkingEl = null;
  }
}

function scrollToBottom() {
  const c = document.getElementById("chat-messages");
  c.scrollTop = c.scrollHeight;
}

// ── Send message ──────────────────────────────────────────────────────────────
function sendMessage() {
  const input = document.getElementById("chat-input");
  const text = input.value.trim();
  if (!text || !wsReady) return;

  appendUserMessage(text);
  input.value = "";
  setInputEnabled(false);

  ws.send(JSON.stringify({ action: "chat", message: text }));
}

function quickSend(text) {
  const input = document.getElementById("chat-input");
  input.value = text;
  sendMessage();
}

function clearHistory() {
  if (ws && wsReady) {
    ws.send(JSON.stringify({ action: "clear" }));
  }
}

function setInputEnabled(enabled) {
  document.getElementById("chat-input").disabled = !enabled;
  document.getElementById("send-btn").disabled = !enabled;
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && document.activeElement.id === "chat-input") {
    sendMessage();
  }
  if (e.key === "Escape") {
    const grid = document.getElementById("app-grid");
    if (!grid.classList.contains("hidden")) {
      grid.classList.add("hidden");
    }
  }
});

// ── Window management ─────────────────────────────────────────────────────────
let dragState = null;

function startDrag(e, winId) {
  if (e.target.classList.contains("wbtn")) return;
  const win = document.getElementById(winId);
  const rect = win.getBoundingClientRect();
  dragState = {
    winId,
    startX: e.clientX,
    startY: e.clientY,
    origLeft: rect.left,
    origTop: rect.top - 34, // adjust for topbar
  };
  document.addEventListener("mousemove", onDragMove);
  document.addEventListener("mouseup", onDragEnd, { once: true });
}

function onDragMove(e) {
  if (!dragState) return;
  const win = document.getElementById(dragState.winId);
  const dx = e.clientX - dragState.startX;
  const dy = e.clientY - dragState.startY;
  win.style.left = `${Math.max(0, dragState.origLeft + dx)}px`;
  win.style.top  = `${Math.max(0, dragState.origTop  + dy)}px`;
}

function onDragEnd() {
  dragState = null;
  document.removeEventListener("mousemove", onDragMove);
}

function closeWindow(winId) {
  document.getElementById(winId).classList.add("hidden");
  updateDockState();
}

function minimizeWindow(winId) {
  document.getElementById(winId).classList.add("hidden");
  updateDockState();
}

function maximizeWindow(winId) {
  const win = document.getElementById(winId);
  if (win.style.width === "100%") {
    win.style.width = "";
    win.style.height = "";
    win.style.left = "";
    win.style.top = "";
  } else {
    win.style.width = "100%";
    win.style.height = "100%";
    win.style.left = "0";
    win.style.top = "0";
    win.style.borderRadius = "0";
  }
}

function showWindow(winId) {
  const win = document.getElementById(winId);
  win.classList.remove("hidden");
  win.style.zIndex = Date.now();
  updateDockState();
}

function updateDockState() {
  const assistantOpen = !document.getElementById("win-assistant").classList.contains("hidden");
  document.querySelector(".dock-item.active")?.classList.remove("active");
  if (assistantOpen) {
    document.querySelector(".dock-item[title='AI Assistant']")?.classList.add("active");
  }
}

function openApp(name) {
  document.getElementById("app-grid").classList.add("hidden");
  const winMap = {
    assistant: "win-assistant",
    settings: "win-settings",
  };
  const winId = winMap[name];
  if (winId) {
    showWindow(winId);
  } else {
    // For other "apps", just send a contextual prompt
    const prompts = {
      files: "list files in the home directory",
      terminal: "show me a terminal overview: current directory, user, uptime",
      system: "show full system information",
      network: "show network interfaces and connectivity status",
      packages: "list recently installed packages and check for updates",
    };
    if (prompts[name]) {
      showWindow("win-assistant");
      quickSend(prompts[name]);
    }
  }
}

function toggleAppGrid() {
  document.getElementById("app-grid").classList.toggle("hidden");
}

function toggleSettings() {
  const win = document.getElementById("win-settings");
  if (win.classList.contains("hidden")) {
    loadSettingsPanel();
    showWindow("win-settings");
  } else {
    closeWindow("win-settings");
  }
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function loadSettingsPanel() {
  try {
    const resp = await fetch("/api/status");
    const data = await resp.json();
    const sel = document.getElementById("model-select");
    sel.innerHTML = "";
    data.models.forEach(m => {
      const opt = document.createElement("option");
      opt.value = m;
      opt.textContent = m;
      if (m === data.model || m.startsWith(data.model.split(":")[0])) {
        opt.selected = true;
      }
      sel.appendChild(opt);
    });
    document.getElementById("ollama-url-input").value = data.ollama_url;
    document.getElementById("model-badge").textContent = data.model;
  } catch (e) {
    document.getElementById("settings-status").textContent = "Could not load settings: " + e.message;
  }
}

function switchModel() {
  const model = document.getElementById("model-select").value;
  if (ws && wsReady) {
    ws.send(JSON.stringify({ action: "switch_model", model }));
    document.getElementById("model-badge").textContent = model;
    document.getElementById("settings-status").textContent = `Switched to ${model}`;
  }
}

function applyOllamaUrl() {
  document.getElementById("settings-status").textContent =
    "URL change requires server restart.";
}

// ── Clock ─────────────────────────────────────────────────────────────────────
function updateClock() {
  const now = new Date();
  const day = now.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
  const time = now.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  document.getElementById("clock").textContent = `${day}  ${time}`;
}

// ── GPU Widget ────────────────────────────────────────────────────────────────
async function pollGPU() {
  try {
    const data = await fetch("/api/gpu").then(r => r.json());
    const widget = document.getElementById("gpu-widget");
    const bar    = document.getElementById("gpu-bar");
    const label  = document.getElementById("gpu-label");

    if (data.available && data.gpus.length > 0) {
      widget.classList.remove("hidden");
      const gpu = data.gpus[0];
      const pct = gpu.util_pct;
      bar.style.width = `${pct}%`;
      label.textContent = `${pct}%`;
      widget.title = `${gpu.name} | ${pct}% util | ${gpu.mem_used}/${gpu.mem_total}MB | ${gpu.temp}°C`;
    } else {
      widget.classList.add("hidden");
    }
  } catch (e) {
    // silently skip if endpoint unreachable
  }
}

// ── Startup ───────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  connectWS();
  updateClock();
  setInterval(updateClock, 10000);

  // Load status for model badge
  fetch("/api/status")
    .then(r => r.json())
    .then(data => {
      document.getElementById("model-badge").textContent = data.model;
    })
    .catch(() => {});

  // GPU widget polling
  pollGPU();
  setInterval(pollGPU, 5000);
});
