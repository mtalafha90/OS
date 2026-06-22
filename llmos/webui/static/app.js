/* LLM-OS Web UI — Desktop application logic */
"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let ws = null;
let wsReady = false;
let pendingThinkingEl = null;

const CHART_WINDOW = 60;
let _charts = {};
const _chartData = { cpu: [], ram: [], disk: [], gpu: [] };

let _mediaRecorder = null;
let _audioChunks = [];
let _isRecording = false;

// ── Lock Screen ───────────────────────────────────────────────────────────────
const LOCK_PASSWORD = "llmos";
let _locked = true;

function tryUnlock() {
  const pw = document.getElementById("lock-pw").value;
  if (!pw || pw === LOCK_PASSWORD) {
    document.getElementById("lockscreen").classList.add("hidden");
    _locked = false;
    connectWS();
    pollGPU();
    setInterval(pollGPU, 5000);
  } else {
    const errEl = document.getElementById("lock-error");
    errEl.textContent = "Wrong password — try 'llmos'";
    const input = document.getElementById("lock-pw");
    input.value = "";
    input.classList.remove("shake");
    void input.offsetWidth; // reflow to re-trigger animation
    input.classList.add("shake");
    setTimeout(() => input.classList.remove("shake"), 400);
  }
}

function lockScreen() {
  document.getElementById("lockscreen").classList.remove("hidden");
  _locked = true;
  document.getElementById("lock-pw").value = "";
  document.getElementById("lock-error").textContent = "";
  if (ws) { try { ws.close(); } catch (_) {} ws = null; wsReady = false; }
  setTimeout(() => document.getElementById("lock-pw").focus(), 80);
}

function _updateLockClock() {
  const now = new Date();
  const t = document.getElementById("lock-time");
  const d = document.getElementById("lock-date");
  if (t) t.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  if (d) d.textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
}

// ── Markdown renderer (minimal) ───────────────────────────────────────────────
function renderMarkdown(text) {
  if (!text) return "";
  let h = text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_, __, code) => `<pre><code>${code.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(/^### (.+)$/gm, "<h3>$1</h3>")
    .replace(/^## (.+)$/gm, "<h2>$1</h2>")
    .replace(/^# (.+)$/gm, "<h1>$1</h1>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>\n?)+/g, "<ul>$&</ul>")
    .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
    .replace(/^---$/gm, "<hr/>")
    .replace(/\n\n/g, "</p><p>")
    .replace(/\n/g, "<br/>");
  return `<p>${h}</p>`;
}

// ── WebSocket ─────────────────────────────────────────────────────────────────
function connectWS() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/chat`);
  ws.onopen = () => { wsReady = true; };
  ws.onclose = () => {
    wsReady = false;
    if (!_locked) setTimeout(connectWS, 2000);
  };
  ws.onerror = (e) => console.error("[llmos] WS error", e);
  ws.onmessage = (e) => handleServerMessage(JSON.parse(e.data));
}

function handleServerMessage(data) {
  removePendingThinking();
  switch (data.type) {
    case "thinking":
      pendingThinkingEl = addMsg("Thinking…", "thinking-msg");
      break;
    case "tool_call": {
      const args = Object.entries(data.args || {}).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ");
      addMsg(`↳ ${data.name}(${args})`, "tool-call-msg");
      break;
    }
    case "tool_result":
      if (data.result) addMsg(data.result, "tool-msg");
      break;
    case "response":
      addMsg(data.content, "ai-msg", true);
      setInputEnabled(true);
      break;
    case "cleared":
      document.getElementById("chat-messages").innerHTML =
        `<div class="msg system-msg"><strong>LLM-OS</strong> — History cleared.</div>`;
      break;
    case "model_switched":
      document.getElementById("model-badge").textContent = data.model;
      addMsg(`Switched to model: ${data.model}`, "system-msg");
      break;
    case "error":
      addMsg(`Error: ${data.message}`, "system-msg");
      setInputEnabled(true);
      break;
  }
  scrollToBottom();
}

// ── Message rendering ─────────────────────────────────────────────────────────
function addMsg(content, cssClass, isHtml = false) {
  const container = document.getElementById("chat-messages");
  const el = document.createElement("div");
  el.className = `msg ${cssClass}`;
  if (isHtml) {
    el.innerHTML = renderMarkdown(content);
  } else {
    el.textContent = content;
  }
  container.appendChild(el);
  scrollToBottom();
  return el;
}

function removePendingThinking() {
  if (pendingThinkingEl) { pendingThinkingEl.remove(); pendingThinkingEl = null; }
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
  addMsg(text, "user-msg");
  input.value = "";
  setInputEnabled(false);
  ws.send(JSON.stringify({ action: "chat", message: text }));
}

function quickSend(text) {
  document.getElementById("chat-input").value = text;
  sendMessage();
}

function clearHistory() {
  if (ws && wsReady) ws.send(JSON.stringify({ action: "clear" }));
}

function setInputEnabled(enabled) {
  document.getElementById("chat-input").disabled = !enabled;
  document.getElementById("send-btn").disabled = !enabled;
}

// ── Keyboard shortcuts ────────────────────────────────────────────────────────
document.addEventListener("keydown", (e) => {
  if (_locked) return;
  if (e.key === "Enter" && document.activeElement.id === "chat-input") { sendMessage(); return; }
  if ((e.ctrlKey || e.metaKey) && e.key === "l") { e.preventDefault(); lockScreen(); return; }
  if (e.key === "Escape") {
    const grid = document.getElementById("app-grid");
    if (!grid.classList.contains("hidden")) { grid.classList.add("hidden"); return; }
    closeLightbox();
    closeJobDialog();
  }
});

// ── Window management ─────────────────────────────────────────────────────────
let dragState = null;

function startDrag(e, winId) {
  if (e.target.classList.contains("wbtn")) return;
  const win = document.getElementById(winId);
  const rect = win.getBoundingClientRect();
  dragState = { winId, startX: e.clientX, startY: e.clientY, origLeft: rect.left, origTop: rect.top - 34 };
  document.addEventListener("mousemove", onDragMove);
  document.addEventListener("mouseup", onDragEnd, { once: true });
}

function onDragMove(e) {
  if (!dragState) return;
  const win = document.getElementById(dragState.winId);
  win.style.left = `${Math.max(0, dragState.origLeft + e.clientX - dragState.startX)}px`;
  win.style.top  = `${Math.max(0, dragState.origTop  + e.clientY - dragState.startY)}px`;
}

function onDragEnd() { dragState = null; document.removeEventListener("mousemove", onDragMove); }

function closeWindow(winId) { document.getElementById(winId).classList.add("hidden"); updateDockState(); }
function minimizeWindow(winId) { closeWindow(winId); }

function maximizeWindow(winId) {
  const win = document.getElementById(winId);
  if (win.style.width === "100%") {
    win.style.width = win.style.height = win.style.left = win.style.top = "";
    win.style.borderRadius = "";
  } else {
    win.style.width = "100%"; win.style.height = "100%";
    win.style.left = "0"; win.style.top = "0";
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
  const open = !document.getElementById("win-assistant").classList.contains("hidden");
  document.querySelector(".dock-item.active")?.classList.remove("active");
  if (open) document.querySelector(".dock-item[title='AI Assistant']")?.classList.add("active");
}

function openApp(name) {
  document.getElementById("app-grid").classList.add("hidden");
  const winMap = { assistant: "win-assistant", settings: "win-settings", dashboard: "win-dashboard" };
  const winId = winMap[name];
  if (winId) {
    showWindow(winId);
    if (name === "dashboard") initDashboard();
  } else {
    const prompts = {
      files: "list files in the home directory",
      terminal: "show me a terminal overview: current directory, user, uptime",
      system: "show full system information",
      network: "show network interfaces and connectivity status",
      packages: "list recently installed packages and check for updates",
    };
    if (prompts[name]) { showWindow("win-assistant"); quickSend(prompts[name]); }
  }
}

function openDashboard() { showWindow("win-dashboard"); initDashboard(); }
function toggleAppGrid() { document.getElementById("app-grid").classList.toggle("hidden"); }

function toggleSettings() {
  const win = document.getElementById("win-settings");
  if (win.classList.contains("hidden")) { loadSettingsPanel(); showWindow("win-settings"); }
  else closeWindow("win-settings");
}

// ── Tab Switching ─────────────────────────────────────────────────────────────
function switchTab(windowId, tabName) {
  const win = document.getElementById(`win-${windowId}`);
  if (!win) return;
  win.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  win.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));
  win.querySelectorAll(".tab").forEach(t => {
    if (t.getAttribute("onclick") === `switchTab('${windowId}', '${tabName}')`)
      t.classList.add("active");
  });
  const content = document.getElementById(`tab-${windowId}-${tabName}`);
  if (content) content.classList.add("active");
  if (tabName === "jobs")    pollJobs();
  if (tabName === "history") pollHistory();
  if (tabName === "plots")   pollPlots();
}

// ── Settings ──────────────────────────────────────────────────────────────────
async function loadSettingsPanel() {
  try {
    const data = await fetch("/api/status").then(r => r.json());
    const sel = document.getElementById("model-select");
    sel.innerHTML = "";
    (data.models || []).forEach(m => {
      const opt = document.createElement("option");
      opt.value = m; opt.textContent = m;
      if (m === data.model || m.startsWith(data.model.split(":")[0])) opt.selected = true;
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
  document.getElementById("settings-status").textContent = "URL change requires server restart.";
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
      const pct = data.gpus[0].util_pct;
      bar.style.width = `${pct}%`;
      label.textContent = `${pct}%`;
      const g = data.gpus[0];
      widget.title = `${g.name} | ${pct}% util | ${g.mem_used}/${g.mem_total}MB | ${g.temp}°C`;
    } else {
      widget.classList.add("hidden");
    }
  } catch (_) {}
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
let _dashboardInitialized = false;

function initDashboard() {
  if (_dashboardInitialized) return;
  _dashboardInitialized = true;

  const baseOpts = {
    responsive: true, maintainAspectRatio: false,
    animation: { duration: 300 },
    plugins: { legend: { display: false } },
    scales: {
      x: { display: false },
      y: { min: 0, max: 100, ticks: { color: "#666", font: { size: 10 }, maxTicksLimit: 5, callback: v => v + "%" }, grid: { color: "rgba(255,255,255,0.05)" } },
    },
  };

  function makeChart(id, color) {
    const ctx = document.getElementById(id);
    if (!ctx) return null;
    const empties = Array(CHART_WINDOW).fill(null);
    return new Chart(ctx, {
      type: "line",
      data: {
        labels: Array(CHART_WINDOW).fill(""),
        datasets: [{
          data: [...empties], borderColor: color,
          backgroundColor: color.replace(")", ", 0.1)").replace("rgb", "rgba"),
          borderWidth: 1.5, pointRadius: 0, fill: true, tension: 0.3,
        }],
      },
      options: baseOpts,
    });
  }

  _charts.cpu  = makeChart("chart-cpu",  "rgb(233,84,32)");
  _charts.ram  = makeChart("chart-ram",  "rgb(90,160,255)");
  _charts.disk = makeChart("chart-disk", "rgb(200,200,60)");
  _charts.gpu  = makeChart("chart-gpu",  "rgb(40,200,64)");

  pollMetrics();
  setInterval(pollMetrics, 2000);
  pollJobs();
  setInterval(pollJobs, 5000);
  pollHistory();
  setInterval(pollHistory, 30000);
  pollPlots();
  setInterval(pollPlots, 10000);
}

function _pushChart(key, value) {
  const chart = _charts[key];
  if (!chart) return;
  const ds = chart.data.datasets[0];
  ds.data.push(value);
  chart.data.labels.push("");
  if (ds.data.length > CHART_WINDOW) { ds.data.shift(); chart.data.labels.shift(); }
  chart.update("none");
}

async function pollMetrics() {
  try {
    const d = await fetch("/api/metrics").then(r => r.json());
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    set("mv-cpu",  `${d.cpu_pct  ?? "--"}%`);
    set("mv-ram",  `${d.ram_pct  ?? "--"}%`);
    set("mv-disk", `${d.disk_pct ?? "--"}%`);
    const gpu = d.gpu && d.gpu.length > 0 ? d.gpu[0].util : null;
    set("mv-gpu", gpu !== null ? `${gpu}%` : "N/A");
    _pushChart("cpu",  d.cpu_pct  ?? 0);
    _pushChart("ram",  d.ram_pct  ?? 0);
    _pushChart("disk", d.disk_pct ?? 0);
    _pushChart("gpu",  gpu        ?? 0);
  } catch (_) {}
}

async function pollJobs() {
  try {
    const jobs = await fetch("/api/jobs").then(r => r.json());
    const tbody = document.getElementById("jobs-tbody");
    if (!tbody) return;
    if (!jobs || jobs.length === 0) {
      tbody.innerHTML = `<tr><td colspan="8" class="table-empty">No jobs in queue</td></tr>`;
      return;
    }
    tbody.innerHTML = jobs.map(job => {
      const s = (job.status || "pending").toLowerCase();
      const canCancel = s === "pending" || s === "running";
      return `<tr>
        <td style="color:var(--text-dim);font-size:11px">${job.id ?? ""}</td>
        <td>${escHtml(job.name ?? "")}</td>
        <td><span class="status-badge ${s}">${s}</span></td>
        <td style="font-family:monospace;font-size:11px">${escHtml(job.command ?? "")}</td>
        <td>${escHtml(String(job.gpu_ids ?? ""))}</td>
        <td>${job.mpi_ranks ?? 1}</td>
        <td>${job.priority ?? 5}</td>
        <td>${canCancel ? `<button class="cancel-btn" onclick="cancelJob('${job.id}')">Cancel</button>` : ""}</td>
      </tr>`;
    }).join("");
  } catch (_) {}
}

async function pollHistory() {
  try {
    const sims = await fetch("/api/simulations").then(r => r.json());
    const tbody = document.getElementById("history-tbody");
    if (!tbody) return;
    if (!sims || sims.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="table-empty">No simulation history</td></tr>`;
      return;
    }
    tbody.innerHTML = sims.map((sim, i) => {
      const s = (sim.status || "done").toLowerCase();
      const detailId = `hist-detail-${i}`;
      return `<tr onclick="toggleHistoryRow('${detailId}', this)">
        <td><button class="expand-btn" id="expand-${detailId}">&#x25B6;</button></td>
        <td>${escHtml(sim.name ?? "")}</td>
        <td><span class="status-badge ${s}">${s}</span></td>
        <td style="font-size:11px;color:var(--text-dim)">${escHtml(sim.started ?? "")}</td>
        <td style="font-size:11px">${escHtml(sim.duration ?? "")}</td>
        <td style="font-size:11px">${sim.exit_code ?? ""}</td>
      </tr>
      <tr id="${detailId}" class="history-detail-row" style="display:none">
        <td colspan="6">${escHtml(JSON.stringify(sim, null, 2))}</td>
      </tr>`;
    }).join("");
  } catch (_) {}
}

function toggleHistoryRow(detailId, _rowEl) {
  const detail = document.getElementById(detailId);
  const btn = document.getElementById(`expand-${detailId}`);
  if (!detail) return;
  const hidden = detail.style.display === "none";
  detail.style.display = hidden ? "table-row" : "none";
  if (btn) btn.textContent = hidden ? "▼" : "▶";
}

async function pollPlots() {
  try {
    const plots = await fetch("/api/plots").then(r => r.json());
    const gallery = document.getElementById("plot-gallery");
    if (!gallery) return;
    if (!plots || plots.length === 0) {
      gallery.innerHTML = `<div class="plot-empty">No plots found in ~/plots/</div>`;
      return;
    }
    gallery.innerHTML = plots.map(p =>
      `<div class="plot-thumb" onclick="showPlot('${escHtml(p.url)}','${escHtml(p.name)}')">
        <img src="${escHtml(p.url)}" alt="${escHtml(p.name)}" loading="lazy" onerror="this.style.display='none'"/>
        <div class="plot-thumb-label">${escHtml(p.name)}</div>
      </div>`
    ).join("");
  } catch (_) {}
}

// ── Job Dialog ────────────────────────────────────────────────────────────────
function openJobDialog()  { document.getElementById("job-dialog").classList.remove("hidden"); }
function closeJobDialog() { document.getElementById("job-dialog")?.classList.add("hidden"); }

function submitJobFromDialog() {
  const g = id => document.getElementById(id);
  const form = {
    name:      g("jd-name").value.trim(),
    command:   g("jd-command").value.trim(),
    workdir:   g("jd-workdir").value.trim(),
    gpu_ids:   g("jd-gpus").value.trim(),
    mpi_ranks: parseInt(g("jd-mpi").value.trim() || "1", 10),
    priority:  parseInt(g("jd-priority").value.trim() || "5", 10),
  };
  if (!form.name || !form.command) { alert("Job name and command are required."); return; }
  fetch("/api/jobs/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(form),
  }).then(r => r.json()).then(result => {
    if (result && !result.error) {
      closeJobDialog(); pollJobs();
      addMsg(`Job "${form.name}" submitted.`, "system-msg");
    } else {
      alert("Error: " + (result.error || "unknown"));
    }
  }).catch(e => alert("Network error: " + e.message));
}

async function cancelJob(jobId) {
  try {
    await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    pollJobs();
  } catch (_) {}
}

// ── Voice ─────────────────────────────────────────────────────────────────────
async function toggleVoice() {
  const btn = document.getElementById("voice-btn");
  if (_isRecording) {
    if (_mediaRecorder && _mediaRecorder.state !== "inactive") _mediaRecorder.stop();
    _isRecording = false;
    btn.classList.remove("recording");
    btn.title = "Voice input";
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream);
    _mediaRecorder.ondataavailable = e => { if (e.data.size > 0) _audioChunks.push(e.data); };
    _mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_audioChunks, { type: "audio/webm" });
      _audioChunks = [];
      try {
        const fd = new FormData();
        fd.append("file", blob, "recording.webm");
        const res = await fetch("/api/voice/transcribe", { method: "POST", body: fd }).then(r => r.json());
        if (res.text) { document.getElementById("chat-input").value = res.text; document.getElementById("chat-input").focus(); }
      } catch (e) { addMsg("Voice transcription failed: " + e.message, "system-msg"); }
    };
    _mediaRecorder.start();
    _isRecording = true;
    btn.classList.add("recording");
    btn.title = "Click to stop recording";
  } catch (e) { alert("Could not access microphone: " + e.message); }
}

// ── Lightbox ──────────────────────────────────────────────────────────────────
function showPlot(url, name) {
  document.getElementById("lightbox-img").src = url;
  const cap = document.getElementById("lightbox-caption");
  if (cap) cap.textContent = name || "";
  document.getElementById("plot-lightbox").classList.remove("hidden");
}
function closeLightbox() { document.getElementById("plot-lightbox")?.classList.add("hidden"); }

// ── Utility ───────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ── Startup ───────────────────────────────────────────────────────────────────
window.addEventListener("DOMContentLoaded", () => {
  // Lock screen clock (always runs, even when locked)
  _updateLockClock();
  setInterval(_updateLockClock, 10000);

  // Desktop clock
  updateClock();
  setInterval(updateClock, 10000);

  // Set username from OS
  fetch("/api/status").then(r => r.json()).then(data => {
    document.getElementById("model-badge").textContent = data.model;
    const userEl = document.getElementById("lock-user");
    if (userEl && data.user) userEl.textContent = data.user;
  }).catch(() => {});

  // Focus password input
  setTimeout(() => document.getElementById("lock-pw")?.focus(), 100);
});
