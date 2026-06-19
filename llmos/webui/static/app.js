/* LLM-OS Web UI — Desktop application logic */

"use strict";

// ── State ─────────────────────────────────────────────────────────────────────
let ws = null;
let wsReady = false;
let pendingThinkingEl = null;

// Dashboard charts
let _charts = {};
const CHART_WINDOW = 60; // rolling data points
const _chartData = {
  cpu:  { labels: [], values: [] },
  ram:  { labels: [], values: [] },
  disk: { labels: [], values: [] },
  gpu:  { labels: [], values: [] },
};

// Voice recording state
let _mediaRecorder = null;
let _audioChunks = [];
let _isRecording = false;

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
    settings:  "win-settings",
    dashboard: "win-dashboard",
  };
  const winId = winMap[name];
  if (winId) {
    showWindow(winId);
    if (name === "dashboard") {
      initDashboard();
    }
  } else {
    // For other "apps", just send a contextual prompt
    const prompts = {
      files:    "list files in the home directory",
      terminal: "show me a terminal overview: current directory, user, uptime",
      system:   "show full system information",
      network:  "show network interfaces and connectivity status",
      packages: "list recently installed packages and check for updates",
    };
    if (prompts[name]) {
      showWindow("win-assistant");
      quickSend(prompts[name]);
    }
  }
}

function openDashboard() {
  showWindow("win-dashboard");
  initDashboard();
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

// ── Tab Switching ─────────────────────────────────────────────────────────────
function switchTab(windowId, tabName) {
  const win = document.getElementById(`win-${windowId}`);
  if (!win) return;

  // Deactivate all tabs and tab-contents in this window
  win.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  win.querySelectorAll(".tab-content").forEach(tc => tc.classList.remove("active"));

  // Activate the selected tab button (match by onclick text)
  win.querySelectorAll(".tab").forEach(t => {
    if (t.getAttribute("onclick") === `switchTab('${windowId}', '${tabName}')`) {
      t.classList.add("active");
    }
  });

  // Activate the corresponding tab-content
  const content = document.getElementById(`tab-${windowId}-${tabName}`);
  if (content) content.classList.add("active");

  // Trigger data load on tab switch
  if (tabName === "jobs")    pollJobs();
  if (tabName === "history") pollHistory();
  if (tabName === "plots")   pollPlots();
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

// ── Dashboard: Chart.js Init ──────────────────────────────────────────────────
let _dashboardInitialized = false;

function initDashboard() {
  if (_dashboardInitialized) return;
  _dashboardInitialized = true;

  const chartDefaults = {
    type: "line",
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: { legend: { display: false } },
      scales: {
        x: {
          display: false,
        },
        y: {
          min: 0,
          max: 100,
          ticks: {
            color: "#666",
            font: { size: 10 },
            maxTicksLimit: 5,
            callback: v => v + "%",
          },
          grid: { color: "rgba(255,255,255,0.05)" },
        },
      },
    },
  };

  function makeChart(canvasId, color) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return null;
    const emptyLabels = Array(CHART_WINDOW).fill("");
    const emptyData   = Array(CHART_WINDOW).fill(null);
    return new Chart(ctx, {
      ...chartDefaults,
      data: {
        labels: [...emptyLabels],
        datasets: [{
          data: [...emptyData],
          borderColor: color,
          backgroundColor: color.replace(")", ", 0.1)").replace("rgb", "rgba"),
          borderWidth: 1.5,
          pointRadius: 0,
          fill: true,
          tension: 0.3,
        }],
      },
      options: { ...chartDefaults.options },
    });
  }

  _charts.cpu  = makeChart("chart-cpu",  "rgb(233,84,32)");
  _charts.ram  = makeChart("chart-ram",  "rgb(90,160,255)");
  _charts.disk = makeChart("chart-disk", "rgb(200,200,60)");
  _charts.gpu  = makeChart("chart-gpu",  "rgb(40,200,64)");

  // Start polling
  pollMetrics();
  setInterval(pollMetrics, 2000);
  pollJobs();
  setInterval(pollJobs, 5000);
  pollHistory();
  setInterval(pollHistory, 30000);
  pollPlots();
  setInterval(pollPlots, 10000);
}

function _pushChartPoint(key, value) {
  const chart = _charts[key];
  if (!chart) return;
  const ds = chart.data.datasets[0];
  const labels = chart.data.labels;

  ds.data.push(value);
  labels.push("");
  if (ds.data.length > CHART_WINDOW) {
    ds.data.shift();
    labels.shift();
  }
  chart.update("none");
}

// ── pollMetrics ───────────────────────────────────────────────────────────────
async function pollMetrics() {
  try {
    const data = await fetch("/api/metrics").then(r => r.json());

    // Update metric cards
    const setText = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val;
    };

    setText("mv-cpu",  `${data.cpu_pct ?? "--"}%`);
    setText("mv-ram",  `${data.ram_pct ?? "--"}%`);
    setText("mv-disk", `${data.disk_pct ?? "--"}%`);

    const gpuUtil = data.gpu && data.gpu.length > 0 ? data.gpu[0].util : null;
    setText("mv-gpu", gpuUtil !== null ? `${gpuUtil}%` : "N/A");

    // Push chart points
    _pushChartPoint("cpu",  data.cpu_pct  ?? 0);
    _pushChartPoint("ram",  data.ram_pct  ?? 0);
    _pushChartPoint("disk", data.disk_pct ?? 0);
    _pushChartPoint("gpu",  gpuUtil       ?? 0);

  } catch (e) {
    // silently ignore if not available
  }
}

// ── pollJobs ──────────────────────────────────────────────────────────────────
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
      const statusClass = (job.status || "pending").toLowerCase();
      const canCancel = statusClass === "pending" || statusClass === "running";
      return `<tr>
        <td style="color:var(--text-dim);font-size:11px">${job.id ?? ""}</td>
        <td>${escHtml(job.name ?? "")}</td>
        <td><span class="status-badge ${statusClass}">${statusClass}</span></td>
        <td style="font-family:monospace;font-size:11px">${escHtml(job.command ?? "")}</td>
        <td>${escHtml(String(job.gpu_ids ?? ""))}</td>
        <td>${job.mpi_ranks ?? 1}</td>
        <td>${job.priority ?? 5}</td>
        <td>${canCancel ? `<button class="cancel-btn" onclick="cancelJob('${job.id}')">Cancel</button>` : ""}</td>
      </tr>`;
    }).join("");
  } catch (e) {
    // silently ignore
  }
}

// ── pollHistory ───────────────────────────────────────────────────────────────
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
      const statusClass = (sim.status || "done").toLowerCase();
      const detailId = `hist-detail-${i}`;
      return `<tr onclick="toggleHistoryRow('${detailId}', this)">
        <td><button class="expand-btn" id="expand-${detailId}">&#x25B6;</button></td>
        <td>${escHtml(sim.name ?? "")}</td>
        <td><span class="status-badge ${statusClass}">${statusClass}</span></td>
        <td style="font-size:11px;color:var(--text-dim)">${escHtml(sim.started ?? "")}</td>
        <td style="font-size:11px">${escHtml(sim.duration ?? "")}</td>
        <td style="font-size:11px">${sim.exit_code ?? ""}</td>
      </tr>
      <tr id="${detailId}" class="history-detail-row" style="display:none">
        <td colspan="6">${escHtml(JSON.stringify(sim, null, 2))}</td>
      </tr>`;
    }).join("");
  } catch (e) {
    // silently ignore
  }
}

function toggleHistoryRow(detailId, rowEl) {
  const detail = document.getElementById(detailId);
  const btn = document.getElementById(`expand-${detailId}`);
  if (!detail) return;
  const hidden = detail.style.display === "none";
  detail.style.display = hidden ? "table-row" : "none";
  if (btn) btn.textContent = hidden ? "▼" : "▶";
}

// ── pollPlots ─────────────────────────────────────────────────────────────────
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
      `<div class="plot-thumb" onclick="showPlot('${escHtml(p.url)}', '${escHtml(p.name)}')">
        <img src="${escHtml(p.url)}" alt="${escHtml(p.name)}" loading="lazy"
             onerror="this.style.display='none'" />
        <div class="plot-thumb-label">${escHtml(p.name)}</div>
      </div>`
    ).join("");
  } catch (e) {
    // silently ignore
  }
}

// ── submitJob ─────────────────────────────────────────────────────────────────
async function submitJob(form) {
  try {
    const resp = await fetch("/api/jobs/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(form),
    });
    const result = await resp.json();
    return result;
  } catch (e) {
    console.error("[llmos] submitJob error:", e);
    return { error: e.message };
  }
}

function submitJobFromDialog() {
  const form = {
    name:      document.getElementById("jd-name").value.trim(),
    command:   document.getElementById("jd-command").value.trim(),
    workdir:   document.getElementById("jd-workdir").value.trim(),
    gpu_ids:   document.getElementById("jd-gpus").value.trim(),
    mpi_ranks: parseInt(document.getElementById("jd-mpi").value.trim() || "1", 10),
    priority:  parseInt(document.getElementById("jd-priority").value.trim() || "5", 10),
  };

  if (!form.name || !form.command) {
    alert("Job name and command are required.");
    return;
  }

  submitJob(form).then(result => {
    if (result && !result.error) {
      closeJobDialog();
      pollJobs();
      appendMessage(`Job "${form.name}" submitted.`, "system-msg");
      scrollToBottom();
    } else {
      alert("Error submitting job: " + (result.error || "unknown error"));
    }
  });
}

// ── cancelJob ─────────────────────────────────────────────────────────────────
async function cancelJob(jobId) {
  try {
    await fetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: "DELETE" });
    pollJobs();
  } catch (e) {
    console.error("[llmos] cancelJob error:", e);
  }
}

// ── toggleVoice ───────────────────────────────────────────────────────────────
async function toggleVoice() {
  const btn = document.getElementById("voice-btn");

  if (_isRecording) {
    // Stop recording
    if (_mediaRecorder && _mediaRecorder.state !== "inactive") {
      _mediaRecorder.stop();
    }
    _isRecording = false;
    btn.classList.remove("recording");
    btn.title = "Voice input";
    return;
  }

  // Start recording
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    _audioChunks = [];
    _mediaRecorder = new MediaRecorder(stream);

    _mediaRecorder.ondataavailable = e => {
      if (e.data.size > 0) _audioChunks.push(e.data);
    };

    _mediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      const blob = new Blob(_audioChunks, { type: "audio/webm" });
      _audioChunks = [];
      await transcribeAudio(blob);
    };

    _mediaRecorder.start();
    _isRecording = true;
    btn.classList.add("recording");
    btn.title = "Click to stop recording";
  } catch (e) {
    console.error("[llmos] Voice input error:", e);
    alert("Could not access microphone: " + e.message);
  }
}

async function transcribeAudio(blob) {
  try {
    const formData = new FormData();
    formData.append("file", blob, "recording.webm");
    const resp = await fetch("/api/voice/transcribe", {
      method: "POST",
      body: formData,
    });
    const result = await resp.json();
    if (result.text) {
      const input = document.getElementById("chat-input");
      input.value = result.text;
      input.focus();
    }
  } catch (e) {
    console.error("[llmos] Transcription error:", e);
    appendMessage("Voice transcription failed: " + e.message, "system-msg");
  }
}

// ── showPlot / lightbox ───────────────────────────────────────────────────────
function showPlot(url, name) {
  const lb = document.getElementById("plot-lightbox");
  const img = document.getElementById("lightbox-img");
  const cap = document.getElementById("lightbox-caption");
  img.src = url;
  if (cap) cap.textContent = name || "";
  lb.classList.remove("hidden");
}

function closeLightbox() {
  const lb = document.getElementById("plot-lightbox");
  if (lb) lb.classList.add("hidden");
}

// ── Job Dialog ────────────────────────────────────────────────────────────────
function openJobDialog() {
  document.getElementById("job-dialog").classList.remove("hidden");
}

function closeJobDialog() {
  const d = document.getElementById("job-dialog");
  if (d) d.classList.add("hidden");
}

// ── Utility: escape HTML ──────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
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
