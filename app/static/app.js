/* ═══════════════════════════════════════════════════════
   Colab Worker TTS — Dashboard JavaScript
   WebSocket + REST API client
   ═══════════════════════════════════════════════════════ */

(function () {
  "use strict";

  // ── Config ─────────────────────────────────────────
  const API = "";  // Same origin
  let ws = null;
  let reconnectTimer = null;
  let activePlayback = null;
  let refreshTimeout = null;
  let lastCreatedTaskId = null;

  // ── Auth check ─────────────────────────────────────
  (function checkAuth() {
    const token = localStorage.getItem("token");
    const user = (function() { try { return JSON.parse(localStorage.getItem("user")); } catch { return null; } })();
    if (!token || !user || user.role !== "admin") {
      window.location.href = "/login";
      return;
    }
  })();

  // ── DOM refs ───────────────────────────────────────
  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  // ── Tab switching ──────────────────────────────────
  $$(".nav-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      $$(".nav-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      $$(".tab-content").forEach((t) => t.classList.remove("active"));
      const tab = $(`#tab-${btn.dataset.tab}`);
      if (tab) tab.classList.add("active");

      // Refresh data for the tab
      if (btn.dataset.tab === "dashboard") refreshDashboard();
      if (btn.dataset.tab === "accounts") refreshAccounts();
      if (btn.dataset.tab === "voices") refreshVoices();
      if (btn.dataset.tab === "tts") refreshVoices(); // Need voices for dropdown
    });
  });

  // ── WebSocket ──────────────────────────────────────
  function connectWebSocket() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${proto}//${location.host}/ws/dashboard`;
    try {
      ws = new WebSocket(url);
      ws.onopen = () => {
        updateWsStatus(true);
        addLog("info", "WebSocket connected.");
      };
      ws.onclose = () => {
        updateWsStatus(false);
        scheduleReconnect();
      };
      ws.onerror = () => {
        ws.close();
      };
      ws.onmessage = (evt) => {
        try {
          const msg = JSON.parse(evt.data);
          handleWsMessage(msg);
        } catch (_) {}
      };
    } catch (_) {
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      connectWebSocket();
    }, 3000);
  }

  function debounceRefresh() {
    if (refreshTimeout) return;
    refreshTimeout = setTimeout(() => {
      refreshDashboard();
      refreshRecentTasks();
      refreshTimeout = null;
    }, 500);
  }

  function handleWsMessage(msg) {
    const ev = msg.event;
    if (ev === "worker_connected" || ev === "worker_disconnected" || ev === "worker_status") {
      debounceRefresh();
    } else if (ev === "task_created" || ev === "task_completed" || ev === "task_failed") {
      debounceRefresh();

      if (msg.task_id === lastCreatedTaskId) {
        if (ev === "task_completed") {
          addLog("success", `Task hoàn thành: ${msg.task_id.slice(0, 8)}...`);
          $("#ttsResultContent").innerHTML = `
            <div class="task-status-line">
              <span class="status-badge completed">Hoàn thành</span>
            </div>
            <div class="audio-player-container">
              <audio class="audio-player" controls autoplay src="${API}/api/tasks/${msg.task_id}/audio"></audio>
            </div>
          `;
        } else if (ev === "task_failed") {
          addLog("error", `Task thất bại: ${msg.error || "Unknown error"}`);
          $("#ttsResultContent").innerHTML = `
            <div class="task-status-line">
              <span class="status-badge failed">Thất bại</span>
              <span style="color: var(--red); font-size: 0.85rem;">${esc(msg.error || "Unknown error")}</span>
            </div>
          `;
        }
      }
    }
  }

  function updateWsStatus(connected) {
    const el = $("#wsStatus");
    el.innerHTML = connected
      ? '<span class="status-dot connected"></span><span>Connected</span>'
      : '<span class="status-dot disconnected"></span><span>Disconnected</span>';
  }

  // ── API helpers ────────────────────────────────────
  function authHeaders() {
    const token = localStorage.getItem("token");
    return token ? { "Authorization": `Bearer ${token}` } : {};
  }

  async function api(path, opts = {}) {
    const url = API + path;
    try {
      const resp = await fetch(url, {
        headers: { "Content-Type": "application/json", ...authHeaders(), ...opts.headers },
        ...opts,
      });
      if (resp.status === 401) {
        localStorage.clear();
        window.location.href = "/login";
        throw new Error("Session expired");
      }
      if (!resp.ok) {
        const err = await resp.json().catch(() => ({}));
        throw new Error(err.detail || `HTTP ${resp.status}`);
      }
      return resp.json();
    } catch (exc) {
      addLog("error", `API error: ${exc.message}`);
      throw exc;
    }
  }

  // ── Dashboard ──────────────────────────────────────
  
  
  function formatDuration(s) {
    if (s <= 0) return "00:00:00";
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sc = Math.floor(s % 60);
    return [h, m, sc].map(v => v.toString().padStart(2, "0")).join(":");
  }

  let workerTimers = {};
  function startWorkerTick() {
    if (window._workerInterval) clearInterval(window._workerInterval);
    window._workerInterval = setInterval(() => {
      const els = document.querySelectorAll(".remaining-timer");
      els.forEach(el => {
        let s = parseInt(el.dataset.seconds);
        if (s > 0) {
          s--;
          el.dataset.seconds = s;
          el.textContent = formatDuration(s);
          if (s < 600) el.style.color = "#e74c3c"; // Red if < 10min
        }
      });
    }, 1000);
  }

  async function refreshDashboard() {
    try {
      const [hRes, wRes, sRes] = await Promise.all([
        fetch("/api/health/"),
        fetch("/api/health/workers"),
        fetch("/api/health/stats")
      ]);
      const health = await hRes.json();
      const workers = await wRes.json();
      const stats = await sRes.json();

      $("#statActiveWorkers").textContent = workers.length;
      $("#statCompleted").textContent = stats.completed;
      $("#statPending").textContent = stats.pending;
      $("#statFailed").textContent = stats.failed;

      const tbody = $("#workerTableBody");
      if (workers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5" class="empty-row">Chưa có worker nào kết nối</td></tr>';
        return;
      }

      tbody.innerHTML = workers.map(w => {
        const statusClass = w.status.toLowerCase();
        const expiringTag = w.expiring ? '<span class="status-badge expiring">Bàn giao</span>' : '';
        return `
          <tr>
            <td>
              <div class="worker-email">${w.email}</div>
              <div class="worker-subtext">${w.gpu}</div>
            </td>
            <td>
              <span class="status-badge ${statusClass}">${w.status}</span>
              ${expiringTag}
            </td>
            <td>
              <div class="uptime-counter ${w.expiring ? 'expiring' : ''}">
                ${formatDuration(w.uptime_seconds)}
              </div>
            </td>
            <td>
              <div class="remaining-timer" data-seconds="${w.remaining_seconds}">
                ${formatDuration(w.remaining_seconds)}
              </div>
            </td>
            <td>
              <button class="btn-icon" onclick="stopWorker('${w.email}')" title="Stop">🛑</button>
            </td>
          </tr>
        `;
      }).join("");
      startWorkerTick();
    } catch (err) {
      console.error("Dashboard refresh error:", err);
    }
  }


  async function refreshRecentTasks() {
    try {
      const tasks = await api("/api/tasks/?limit=10");
      const el = $("#recentTasks");
      if (tasks.length === 0) {
        el.innerHTML = '<div class="empty-row">Chưa có task nào</div>';
        return;
      }
      el.innerHTML = tasks
        .map(
          (t) => `
        <div class="task-item">
          <span class="status-badge ${t.status.toLowerCase()}">${t.status}</span>
          <span class="task-text">${esc(t.text)}</span>
          <span class="task-time">${t.created_at ? timeAgo(t.created_at) : ""}</span>
          ${
            t.status === "COMPLETED"
              ? `<button class="btn btn-sm btn-ghost" onclick="playAudio('${t.id}')">▶ Nghe</button>`
              : ""
          }
        </div>`
        )
        .join("");
    } catch (_) {}
  }

  // ── Accounts ───────────────────────────────────────
  function cooldownLabel(iso) {
    if (!iso) return "";
    const diff = new Date(iso).getTime() - Date.now();
    if (diff <= 0) return "";
    const h = Math.floor(diff / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    return h > 0 ? `Cooldown còn ${h}h ${m}m` : `Cooldown còn ${m}m`;
  }

  async function refreshAccounts() {
    try {
      const accounts = await api("/api/accounts/");
      const el = $("#accountsList");
      if (accounts.length === 0) {
        el.innerHTML = '<div class="empty-row">Chưa có tài khoản nào</div>';
        return;
      }
      el.innerHTML = accounts
        .map((a) => {
          const cd = cooldownLabel(a.quota_reset_at);
          const inCooldown = !!cd;
          const last = a.last_active ? timeAgo(a.last_active) : "chưa chạy";
          const startBtn = a.status === "OFFLINE" && !inCooldown
            ? `<button class="btn btn-sm btn-primary" onclick="startWorker(${a.id})">Khởi chạy</button>` : "";
          const loginBtn = a.status === "CONNECTING"
            ? `<button class="btn btn-sm btn-primary" onclick="finishLogin(${a.id})">Hoàn tất đăng nhập</button>` : "";
          const stopBtn = (a.status === "ACTIVE" || a.status === "CONNECTING")
            ? `<button class="btn btn-sm btn-ghost" onclick="stopWorker(${a.id})">Dừng</button>` : "";
          return `
        <div class="account-card">
          <div class="account-header">
            <div class="account-avatar">${esc(a.email.charAt(0).toUpperCase())}</div>
            <div class="account-info">
              <div class="account-email">${esc(a.email)}</div>
              <span class="status-badge ${a.status.toLowerCase()}">${esc(a.status)}</span>
            </div>
          </div>
          <div class="account-meta">
            <span>Lần cuối hoạt động: ${last}</span>
            ${inCooldown ? `<span class="cooldown-line">${cd}</span>` : ""}
          </div>
          <div class="account-actions">
            ${startBtn}${loginBtn}${stopBtn}
            <button class="btn btn-sm btn-danger" onclick="deleteAccount(${a.id})">Xóa</button>
          </div>
        </div>`;
        })
        .join("");
    } catch (_) {}
  }

  // Account form
  $("#addAccountForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const email = $("#accountEmail").value.trim();
    if (!email) return;
    try {
      await api("/api/accounts/add", {
        method: "POST",
        body: JSON.stringify({ email }),
      });
      addLog("info", `Đã gửi yêu cầu thêm tài khoản: ${email}`);
      addLog("info", "Cửa sổ Chrome sẽ mở ra. Đăng nhập Google bình thường.");
      addLog("success", "Sau khi đăng nhập xong, server tự đóng Chrome (không cần thao tác tay).");
      $("#accountEmail").value = "";
      refreshAccounts();
    } catch (_) {}
  });

  // ── Voices ─────────────────────────────────────────
  async function refreshVoices() {
    try {
      const voices = await api("/api/voices/");
      const el = $("#voicesList");
      const select = $("#ttsVoice");

      // Update voice dropdown
      const currentVal = select.value;
      select.innerHTML = '<option value="">-- Chọn giọng nói --</option>';
      voices.forEach((v) => {
        const opt = document.createElement("option");
        opt.value = v.id;
        opt.textContent = v.name;
        select.appendChild(opt);
      });
      if (currentVal) select.value = currentVal;

      // Update voice grid
      if (voices.length === 0) {
        el.innerHTML = '<div class="empty-row">Chưa có giọng nói nào</div>';
        return;
      }
      el.innerHTML = voices
        .map(
          (v) => `
        <div class="voice-card">
          <div class="voice-name">${esc(v.name)}</div>
          <div class="voice-transcript">${esc(v.transcript || "")}</div>
          <div class="voice-actions">
            <button class="btn btn-sm btn-ghost" onclick="playVoiceAudio(${v.id})">Nghe mẫu</button>
            <button class="btn btn-sm btn-danger" onclick="deleteVoice(${v.id})">Xóa</button>
          </div>
        </div>`
        )
        .join("");
    } catch (_) {}
  }

  // Voice form
  $("#addVoiceForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const name = $("#voiceName").value.trim();
    const transcript = $("#voiceTranscript").value.trim();
    const file = $("#voiceAudio").files[0];
    if (!name || !file) return;

    const formData = new FormData();
    formData.append("name", name);
    formData.append("transcript", transcript);
    formData.append("audio", file);

    try {
      await fetch(`${API}/api/voices/`, { method: "POST", body: formData });
      addLog("success", `Đã thêm giọng nói: ${name}`);
      $("#voiceName").value = "";
      $("#voiceTranscript").value = "";
      $("#voiceAudio").value = "";
      refreshVoices();
    } catch (exc) {
      addLog("error", `Lỗi thêm giọng nói: ${exc.message}`);
    }
  });

  // ── TTS Form ───────────────────────────────────────
  $("#ttsForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = $("#ttsText").value.trim();
    const voiceId = $("#ttsVoice").value;
    const language = $("#ttsLanguage").value || null;
    if (!text || !voiceId) return;

    try {
      const result = await api("/api/tasks/", {
        method: "POST",
        body: JSON.stringify({ text, voice_id: parseInt(voiceId), language }),
      });
      addLog("info", `Task tạo thành công: ${result.id.slice(0, 8)}...`);

      // Show result area
      const area = $("#ttsResultArea");
      area.style.display = "block";
      $("#ttsResultContent").innerHTML = `
        <div class="task-status-line">
          <span class="status-badge processing">Đang xử lý...</span>
          <span style="color: var(--text-muted); font-size: 0.85rem;">${esc(text.slice(0, 60))}${text.length > 60 ? "..." : ""}</span>
        </div>
      `;

      lastCreatedTaskId = result.id;
    } catch (_) {}
  });

  // ── Global actions ─────────────────────────────────
  window.startWorker = async function (id) {
    try {
      await api(`/api/accounts/${id}/start`, { method: "POST" });
      addLog("info", "Worker đang khởi chạy...");
      refreshAccounts();
      refreshDashboard();
    } catch (_) {}
  };

  window.finishLogin = async function (id) {
    try {
      await api(`/api/accounts/${id}/finish-login`, { method: "POST" });
      addLog("success", "Đã lưu session tài khoản Google thành công.");
      refreshAccounts();
      refreshDashboard();
    } catch (_) {}
  };


  window.stopWorker = async function (id) {
    try {
      await api(`/api/accounts/${id}/stop`, { method: "POST" });
      addLog("info", "Worker đã dừng.");
      refreshAccounts();
      refreshDashboard();
    } catch (_) {}
  };

  window.deleteAccount = async function (id) {
    if (!confirm("Xác nhận xóa tài khoản này?")) return;
    try {
      await api(`/api/accounts/${id}`, { method: "DELETE" });
      addLog("info", "Đã xóa tài khoản.");
      refreshAccounts();
    } catch (_) {}
  };

  window.deleteVoice = async function (id) {
    if (!confirm("Xác nhận xóa giọng nói này?")) return;
    try {
      await api(`/api/voices/${id}`, { method: "DELETE" });
      addLog("info", "Đã xóa giọng nói.");
      refreshVoices();
    } catch (_) {}
  };

  window.playAudio = function (taskId) {
    const url = `${API}/api/tasks/${taskId}/audio`;
    if (activePlayback) {
      activePlayback.pause();
    }
    activePlayback = new Audio(url);
    activePlayback.play().catch((err) => {
      addLog("error", `Không thể phát âm thanh: ${err.message}`);
    });
  };

  window.playVoiceAudio = function (voiceId) {
    const url = `${API}/api/voices/${voiceId}/audio`;
    if (activePlayback) {
      activePlayback.pause();
    }
    activePlayback = new Audio(url);
    activePlayback.play().catch((err) => {
      addLog("error", `Không thể phát âm thanh mẫu: ${err.message}`);
    });
  };

  // ── Log ────────────────────────────────────────────
  function addLog(type, message) {
    const el = $("#ttsLog");
    const empty = el.querySelector(".log-empty");
    if (empty) empty.remove();

    const time = new Date().toLocaleTimeString("vi-VN");
    const div = document.createElement("div");
    div.className = `log-entry ${type}`;
    div.textContent = `[${time}] ${message}`;
    el.prepend(div);

    // Keep max 100 entries
    while (el.children.length > 100) el.lastChild.remove();
  }

  // ── Utils ──────────────────────────────────────────
  function esc(s) {
    const d = document.createElement("div");
    d.textContent = s;
    return d.innerHTML;
  }

  function timeAgo(iso) {
    const diff = Date.now() - new Date(iso).getTime();
    const secs = Math.floor(diff / 1000);
    if (secs < 60) return `${secs}s trước`;
    const mins = Math.floor(secs / 60);
    if (mins < 60) return `${mins}m trước`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs}h trước`;
    return `${Math.floor(hrs / 24)}d trước`;
  }

  // ── Init ───────────────────────────────────────────
  connectWebSocket();
  refreshDashboard();
  setInterval(() => {
    refreshDashboard();
    refreshAccounts();
  }, 15000);

  async function stopWorker(email) {
    if (!confirm("Dừng worker " + email + "?")) return;
    try {
      const accs = await api("/api/accounts/");
      const acc = accs.find(a => a.email === email);
      if (!acc) { alert("Không tìm thấy account"); return; }
      await fetch("/api/accounts/" + acc.id + "/stop", { method: "POST", headers: authHeaders() });
      addLog("info", "Đã dừng worker: " + email);
      refreshDashboard();
      refreshAccounts();
    } catch (e) { alert("Lỗi: " + e.message); }
  }
  window.stopWorker = stopWorker;

  // ── Logout ────────────────────────────────────────
  const logoutBtn = document.getElementById("adminLogout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      localStorage.clear();
      window.location.href = "/";
    });
  }

})();
