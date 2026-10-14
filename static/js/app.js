/**
 * Transcriptor Pro - Client-side Application Logic
 */

let state = {
  currentUser: null,
  token: localStorage.getItem("transcriptor_token") || "",
  activeTab: "new",
  transcriptions: [],
  currentTranscript: null,
  pollTimer: null,
  selectedFile: null
};

// ==========================================================
// Utility & Toast Notifications
// ==========================================================
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  const bgColors = {
    info: "bg-slate-900 text-white border-slate-700",
    success: "bg-emerald-600 text-white border-emerald-500",
    error: "bg-rose-600 text-white border-rose-500",
    warning: "bg-amber-600 text-white border-amber-500"
  };

  toast.className = `p-4 rounded-xl shadow-xl border text-xs font-semibold flex items-center gap-2 transform transition-all duration-300 translate-y-2 opacity-0 pointer-events-auto ${bgColors[type] || bgColors.info}`;
  toast.innerHTML = `<span>${message}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.remove("translate-y-2", "opacity-0");
  }, 10);

  setTimeout(() => {
    toast.classList.add("opacity-0", "translate-y-2");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function formatSeconds(seconds) {
  if (!seconds || isNaN(seconds)) return "00:00";
  const s = Math.floor(seconds);
  const hrs = Math.floor(s / 3600);
  const mins = Math.floor((s % 3600) / 60);
  const secs = s % 60;
  if (hrs > 0) {
    return `${hrs.toString().padStart(2, "0")}:${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
  }
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
}

// ==========================================================
// API Client Fetch Wrapper
// ==========================================================
async function apiFetch(endpoint, options = {}) {
  const headers = options.headers || {};
  if (state.token) {
    headers["Authorization"] = `Bearer ${state.token}`;
  }
  options.headers = headers;

  const res = await fetch(endpoint, options);
  if (res.status === 401) {
    // Unauthorized -> Log out
    state.currentUser = null;
    state.token = "";
    localStorage.removeItem("transcriptor_token");
    renderAuthState();
    throw new Error("เซสชันหมดอายุ กรุณาเข้าสู่ระบบใหม่");
  }

  const contentType = res.headers.get("content-type") || "";
  if (!res.ok) {
    let errMessage = `Error ${res.status}`;
    if (contentType.includes("application/json")) {
      const errData = await res.json();
      errMessage = errData.detail || JSON.stringify(errData);
    } else {
      errMessage = await res.text();
    }
    throw new Error(errMessage);
  }

  if (contentType.includes("application/json")) {
    return await res.json();
  }
  return res;
}

// ==========================================================
// Authentication Lifecycle
// ==========================================================
async function checkAuth() {
  if (!state.token) {
    renderAuthState();
    return;
  }
  try {
    const data = await apiFetch("/api/auth/me");
    state.currentUser = data.user;
    renderAuthState();
    navigateTab("new");
    checkSettingsKeyWarning();
  } catch (e) {
    state.currentUser = null;
    state.token = "";
    localStorage.removeItem("transcriptor_token");
    renderAuthState();
  }
}

function renderAuthState() {
  const loginView = document.getElementById("view-login");
  const appView = document.getElementById("view-app");

  if (!state.currentUser) {
    loginView.classList.remove("hidden");
    appView.classList.add("hidden");
  } else {
    loginView.classList.add("hidden");
    appView.classList.remove("hidden");

    // Update user info in sidebar
    document.getElementById("user-display-name").textContent = state.currentUser.full_name || state.currentUser.username;
    document.getElementById("user-avatar").textContent = (state.currentUser.username || "U")[0].toUpperCase();
    
    const roleBadge = document.getElementById("user-role-badge");
    if (state.currentUser.role === "admin") {
      roleBadge.textContent = "Admin";
      roleBadge.className = "text-[10px] px-1.5 py-0.5 rounded font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30";
      // Show admin menus
      document.querySelectorAll(".admin-only").forEach(el => el.classList.remove("hidden"));
    } else {
      roleBadge.textContent = "User";
      roleBadge.className = "text-[10px] px-1.5 py-0.5 rounded font-medium bg-slate-800 text-slate-300";
      // Hide admin menus
      document.querySelectorAll(".admin-only").forEach(el => el.classList.add("hidden"));
    }

    lucide.createIcons();
  }
}

async function login(username, password) {
  const errDiv = document.getElementById("login-error");
  errDiv.classList.add("hidden");

  try {
    const data = await apiFetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password })
    });

    state.token = data.token;
    state.currentUser = data.user;
    localStorage.setItem("transcriptor_token", data.token);

    showToast(`ยินดีต้อนรับคุณ ${state.currentUser.full_name}`, "success");
    renderAuthState();
    navigateTab("new");
    checkSettingsKeyWarning();
  } catch (err) {
    errDiv.textContent = err.message;
    errDiv.classList.remove("hidden");
  }
}

async function logout() {
  try {
    await apiFetch("/api/auth/logout", { method: "POST" });
  } catch (e) {}
  state.currentUser = null;
  state.token = "";
  localStorage.removeItem("transcriptor_token");
  if (state.pollTimer) clearInterval(state.pollTimer);
  renderAuthState();
  showToast("ออกจากระบบแล้ว", "info");
}

async function checkSettingsKeyWarning() {
  if (state.currentUser && state.currentUser.role === "admin") {
    try {
      const data = await apiFetch("/api/settings");
      const warningBanner = document.getElementById("banner-api-key-warning");
      if (!data.settings.has_api_key) {
        warningBanner.classList.remove("hidden");
      } else {
        warningBanner.classList.add("hidden");
      }
    } catch (e) {}
  }
}

// ==========================================================
// Navigation & Tabs
// ==========================================================
function navigateTab(tabName) {
  state.activeTab = tabName;

  // Hide all tabs
  document.querySelectorAll(".tab-pane").forEach(el => el.classList.add("hidden"));

  // Reset nav items styling
  document.querySelectorAll(".nav-item").forEach(btn => {
    btn.className = "nav-item w-full flex items-center gap-3 px-3.5 py-2.5 text-sm font-medium rounded-xl text-slate-400 hover:text-white hover:bg-slate-800/80 transition";
  });

  const activeBtn = document.getElementById(`nav-btn-${tabName}`);
  if (activeBtn) {
    activeBtn.className = "nav-item w-full flex items-center gap-3 px-3.5 py-2.5 text-sm font-medium rounded-xl text-white bg-brand-600 transition shadow-sm";
  }

  const targetTab = document.getElementById(`tab-${tabName}`);
  if (targetTab) {
    targetTab.classList.remove("hidden");
  }

  // Load content according to active tab
  if (tabName === "library") {
    loadTranscriptions();
  } else if (tabName === "logs") {
    loadLogs();
  } else if (tabName === "users") {
    loadUsers();
  } else if (tabName === "settings") {
    loadSettings();
  }

  lucide.createIcons();
}

// ==========================================================
// File Upload & New Transcription Tab
// ==========================================================
function initDropzone() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("file-input");

  dropzone.addEventListener("click", () => fileInput.click());

  dropzone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-active");
  });

  dropzone.addEventListener("dragleave", () => {
    dropzone.classList.remove("drag-active");
  });

  dropzone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-active");
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFileSelected(e.dataTransfer.files[0]);
    }
  });

  fileInput.addEventListener("change", (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFileSelected(e.target.files[0]);
    }
  });
}

function handleFileSelected(file) {
  state.selectedFile = file;
  document.getElementById("dropzone-empty").classList.add("hidden");
  const infoEl = document.getElementById("dropzone-file-info");
  infoEl.classList.remove("hidden");

  document.getElementById("selected-file-name").textContent = file.name;
  document.getElementById("selected-file-size").textContent = formatBytes(file.size);

  // Auto fill title if empty
  const titleInput = document.getElementById("task-title");
  if (!titleInput.value) {
    const baseName = file.name.substring(0, file.name.lastIndexOf('.')) || file.name;
    titleInput.value = baseName;
  }
}

function clearSelectedFile(e) {
  if (e) e.stopPropagation();
  state.selectedFile = null;
  document.getElementById("file-input").value = "";
  document.getElementById("dropzone-empty").classList.remove("hidden");
  document.getElementById("dropzone-file-info").classList.add("hidden");
}

async function handleTranscribeSubmit(e) {
  e.preventDefault();
  if (!state.selectedFile) {
    showToast("กรุณาเลือกไฟล์เสียงหรือวิดีโอก่อนกดเริ่มถอดเสียง", "warning");
    return;
  }

  const btn = document.getElementById("btn-submit-transcribe");
  btn.disabled = true;
  btn.innerHTML = `<i data-lucide="loader-2" class="w-5 h-5 animate-spin"></i><span>กำลังอัปโหลดและส่งเข้าคิว...</span>`;
  lucide.createIcons();

  const formData = new FormData();
  formData.append("file", state.selectedFile);
  formData.append("title", document.getElementById("task-title").value);
  formData.append("model_id", document.getElementById("task-model").value);
  formData.append("language_code", document.getElementById("task-language").value);
  formData.append("diarize", document.getElementById("task-diarize").checked ? "true" : "false");

  const numSpeakers = document.getElementById("task-num-speakers").value;
  if (numSpeakers) {
    formData.append("num_speakers", numSpeakers);
  }

  try {
    const res = await apiFetch("/api/transcriptions/upload", {
      method: "POST",
      body: formData
    });

    showToast("อัปโหลดสำเร็จ! ระบบกำลังเริ่มถอดเสียง", "success");
    clearSelectedFile();
    document.getElementById("task-title").value = "";
    document.getElementById("task-num-speakers").value = "";

    // Switch to library view to watch progress
    navigateTab("library");
  } catch (err) {
    showToast(`เกิดข้อผิดพลาด: ${err.message}`, "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i data-lucide="sparkles" class="w-5 h-5"></i><span>เริ่มถอดเสียงด้วย ElevenLabs AI</span>`;
    lucide.createIcons();
  }
}

// ==========================================================
// Library / Transcriptions List
// ==========================================================
async function loadTranscriptions() {
  try {
    const data = await apiFetch("/api/transcriptions");
    state.transcriptions = data.transcriptions || [];
    renderTranscriptions();
    checkPollingNeeds();
  } catch (err) {
    showToast(`โหลดรายการไม่สำเร็จ: ${err.message}`, "error");
  }
}

function checkPollingNeeds() {
  // If any task is queued or processing, poll every 3 seconds
  const hasActiveTasks = state.transcriptions.some(t => t.status === "queued" || t.status === "processing");
  if (hasActiveTasks) {
    if (!state.pollTimer) {
      state.pollTimer = setInterval(loadTranscriptions, 3500);
    }
  } else {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }
}

function filterTranscriptions() {
  renderTranscriptions();
}

function renderTranscriptions() {
  const container = document.getElementById("transcriptions-container");
  const search = (document.getElementById("lib-search").value || "").toLowerCase().trim();
  const statusFilter = document.getElementById("lib-status-filter").value;

  const filtered = state.transcriptions.filter(item => {
    const matchSearch = !search || 
      (item.title && item.title.toLowerCase().includes(search)) ||
      (item.filename && item.filename.toLowerCase().includes(search));
    const matchStatus = !statusFilter || item.status === statusFilter;
    return matchSearch && matchStatus;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div class="bg-white rounded-2xl p-12 text-center border border-slate-200/80 shadow-sm space-y-3">
        <div class="w-12 h-12 rounded-2xl bg-slate-100 text-slate-400 mx-auto flex items-center justify-center">
          <i data-lucide="inbox" class="w-6 h-6"></i>
        </div>
        <p class="text-sm font-semibold text-slate-700">ไม่พบบทถอดเสียง</p>
        <p class="text-xs text-slate-400">ยังไม่มีรายการที่ตรงกับเงื่อนไข หรือคุณยังไม่ได้อัปโหลดไฟล์</p>
      </div>
    `;
    lucide.createIcons();
    return;
  }

  container.innerHTML = filtered.map(item => {
    let statusBadge = "";
    if (item.status === "completed") {
      statusBadge = `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
        <i data-lucide="check-circle" class="w-3.5 h-3.5"></i> สำเร็จ
      </span>`;
    } else if (item.status === "processing") {
      statusBadge = `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200 animate-pulse">
        <i data-lucide="loader" class="w-3.5 h-3.5 animate-spin"></i> กำลังถอดเสียง...
      </span>`;
    } else if (item.status === "queued") {
      statusBadge = `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
        <i data-lucide="clock" class="w-3.5 h-3.5"></i> รอดำเนินการ
      </span>`;
    } else {
      statusBadge = `<span class="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200" title="${item.error_message || ''}">
        <i data-lucide="alert-circle" class="w-3.5 h-3.5"></i> ข้อผิดพลาด
      </span>`;
    }

    return `
      <div class="bg-white rounded-2xl p-5 border border-slate-200/80 shadow-sm hover:shadow-md transition flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div class="min-w-0 space-y-1.5">
          <div class="flex items-center gap-2.5 flex-wrap">
            <h3 class="text-base font-bold text-slate-900 truncate hover:text-brand-600 cursor-pointer" onclick="openDetail('${item.id}')">
              ${escapeHtml(item.title)}
            </h3>
            ${statusBadge}
          </div>
          <div class="flex items-center gap-3 text-xs text-slate-500 flex-wrap">
            <span class="flex items-center gap-1"><i data-lucide="file" class="w-3.5 h-3.5"></i> ${escapeHtml(item.filename)}</span>
            <span>•</span>
            <span class="flex items-center gap-1"><i data-lucide="hard-drive" class="w-3.5 h-3.5"></i> ${formatBytes(item.file_size)}</span>
            <span>•</span>
            <span class="flex items-center gap-1"><i data-lucide="clock" class="w-3.5 h-3.5"></i> ${formatSeconds(item.duration)}</span>
            <span>•</span>
            <span>${item.created_at ? item.created_at.substring(0, 10) : ''}</span>
          </div>
        </div>

        <div class="flex items-center gap-2 self-end md:self-auto flex-shrink-0">
          ${item.status === 'completed' ? `
            <button onclick="openDetail('${item.id}')"
              class="flex items-center gap-1.5 px-3 py-1.5 bg-brand-50 hover:bg-brand-100 text-brand-700 rounded-xl text-xs font-bold transition">
              <i data-lucide="eye" class="w-4 h-4"></i>
              <span>ดูบทถอด</span>
            </button>
            <div class="relative inline-block text-left">
              <button onclick="triggerDirectDownload('${item.id}', 'docx')" title="ดาวน์โหลด Word (.docx)"
                class="p-2 bg-blue-50 hover:bg-blue-100 text-blue-700 rounded-xl transition">
                <i data-lucide="file-text" class="w-4 h-4"></i>
              </button>
              <button onclick="triggerDirectDownload('${item.id}', 'pdf')" title="ดาวน์โหลด PDF (.pdf)"
                class="p-2 bg-rose-50 hover:bg-rose-100 text-rose-700 rounded-xl transition">
                <i data-lucide="file-check-2" class="w-4 h-4"></i>
              </button>
            </div>
          ` : ''}

          <button onclick="deleteTranscription('${item.id}', '${escapeHtml(item.title)}')"
            title="ลบรายการ"
            class="p-2 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-xl transition">
            <i data-lucide="trash-2" class="w-4 h-4"></i>
          </button>
        </div>
      </div>
    `;
  }).join("");

  lucide.createIcons();
}

function escapeHtml(text) {
  if (!text) return "";
  return text.replace(/[&<>"']/g, function(m) {
    return {
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#039;'
    }[m];
  });
}

async function deleteTranscription(id, title) {
  if (!confirm(`คุณต้องการลบรายการถอดเสียง "${title}" ใช่หรือไม่?`)) return;
  try {
    await apiFetch(`/api/transcriptions/${id}`, { method: "DELETE" });
    showToast("ลบรายการถอดเสียงเรียบร้อยแล้ว", "success");
    loadTranscriptions();
  } catch (err) {
    showToast(`ลบไม่สำเร็จ: ${err.message}`, "error");
  }
}

// ==========================================================
// Detail & Interactive Audio Sync Viewer
// ==========================================================
async function openDetail(id) {
  try {
    const data = await apiFetch(`/api/transcriptions/${id}`);
    state.currentTranscript = data;
    renderDetailView(data);
    navigateTab("detail");
  } catch (err) {
    showToast(`ไม่สามารถเปิดข้อมูลได้: ${err.message}`, "error");
  }
}

function renderDetailView(data) {
  document.getElementById("detail-title").textContent = data.title;
  document.getElementById("detail-filename").textContent = data.filename;
  document.getElementById("detail-duration").textContent = formatSeconds(data.duration);
  document.getElementById("detail-language").textContent = (data.language_code || "TH").toUpperCase();
  document.getElementById("detail-model").textContent = data.model_id;

  const audioWarning = document.getElementById("audio-purged-warning");
  const playerContainer = document.getElementById("audio-player-container");
  const audioEl = document.getElementById("html5-audio");

  if (data.has_audio) {
    audioWarning.classList.add("hidden");
    playerContainer.classList.remove("hidden");
    // Set audio source with auth query param or cookie
    audioEl.src = `/api/transcriptions/${data.id}/audio?token=${state.token}`;
    audioEl.load();
    initAudioPlayerControls();
  } else {
    audioWarning.classList.remove("hidden");
    playerContainer.classList.add("hidden");
  }

  // Populate Speaker Rename inputs
  const spkContainer = document.getElementById("speaker-inputs-container");
  const speakerMap = data.speaker_map || {};
  const speakerKeys = Object.keys(speakerMap);

  if (speakerKeys.length > 0) {
    spkContainer.innerHTML = speakerKeys.map(k => `
      <div>
        <label class="block text-[11px] font-semibold text-slate-500 uppercase mb-1">${k}</label>
        <input type="text" data-speaker-key="${k}" value="${escapeHtml(speakerMap[k])}"
          class="speaker-rename-input w-full px-3 py-1.5 border border-slate-300 rounded-lg text-xs font-semibold focus:ring-2 focus:ring-brand-500">
      </div>
    `).join("");
  } else {
    spkContainer.innerHTML = `<p class="text-xs text-slate-400">ไม่มีข้อมูลการแยกผู้พูดในไฟล์นี้</p>`;
  }

  // Render Dialogue Segments
  const dialogueContainer = document.getElementById("dialogue-container");
  const segments = data.segments || [];

  if (segments.length === 0) {
    dialogueContainer.innerHTML = `
      <div class="bg-white p-6 rounded-2xl border border-slate-200 text-slate-700 whitespace-pre-wrap leading-relaxed font-reading text-base">
        ${escapeHtml(data.formatted_text || "ไม่มีข้อความ")}
      </div>
    `;
    return;
  }

  const speakerColors = [
    { text: "text-blue-700", bg: "bg-blue-50", border: "border-blue-200" },
    { text: "text-teal-700", bg: "bg-teal-50", border: "border-teal-200" },
    { text: "text-amber-700", bg: "bg-amber-50", border: "border-amber-200" },
    { text: "text-purple-700", bg: "bg-purple-50", border: "border-purple-200" },
    { text: "text-rose-700", bg: "bg-rose-50", border: "border-rose-200" },
    { text: "text-indigo-700", bg: "bg-indigo-50", border: "border-indigo-200" }
  ];

  const colorMap = {};
  let cIdx = 0;

  dialogueContainer.innerHTML = segments.map((seg, idx) => {
    const spkId = seg.speaker_id || "speaker_0";
    if (!colorMap[spkId]) {
      colorMap[spkId] = speakerColors[cIdx % speakerColors.length];
      cIdx++;
    }
    const theme = colorMap[spkId];
    const spkName = speakerMap[spkId] || spkId;
    const startStr = formatSeconds(seg.start);
    const endStr = formatSeconds(seg.end);

    return `
      <div class="dialogue-card bg-white rounded-2xl p-5 border-l-4 border-transparent hover:border-slate-300 border-r border-t border-b border-slate-200/80 shadow-sm transition space-y-2 cursor-pointer"
           id="seg-${idx}"
           data-start="${seg.start}"
           data-end="${seg.end}"
           onclick="seekToTime(${seg.start})">
        <div class="flex items-center justify-between flex-wrap gap-2">
          <div class="flex items-center gap-2">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold ${theme.bg} ${theme.text} border ${theme.border}">
              <i data-lucide="user" class="w-3.5 h-3.5"></i>
              <span class="spk-display-${spkId}">${escapeHtml(spkName)}</span>
            </span>
          </div>
          <button type="button" class="text-xs font-mono font-semibold text-slate-400 hover:text-brand-600 flex items-center gap-1 bg-slate-50 hover:bg-brand-50 px-2 py-1 rounded-lg transition" title="คลิกเพื่อฟังเสียงช่วงนี้">
            <i data-lucide="play-circle" class="w-3.5 h-3.5"></i>
            <span>${startStr} - ${endStr}</span>
          </button>
        </div>
        <p class="text-slate-800 leading-relaxed font-reading text-base pt-1 pl-1">
          ${escapeHtml(seg.text)}
        </p>
      </div>
    `;
  }).join("");

  lucide.createIcons();
}

function toggleSpeakerPanel() {
  const body = document.getElementById("speaker-panel-body");
  const icon = document.getElementById("speaker-panel-icon");
  if (body.classList.contains("hidden")) {
    body.classList.remove("hidden");
    icon.style.transform = "rotate(180deg)";
  } else {
    body.classList.add("hidden");
    icon.style.transform = "rotate(0deg)";
  }
}

async function saveSpeakerNames() {
  if (!state.currentTranscript) return;
  const inputs = document.querySelectorAll(".speaker-rename-input");
  const newMap = {};
  inputs.forEach(inp => {
    const k = inp.getAttribute("data-speaker-key");
    newMap[k] = inp.value.trim() || k;
  });

  try {
    await apiFetch(`/api/transcriptions/${state.currentTranscript.id}/speakers`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ speaker_map: newMap })
    });

    state.currentTranscript.speaker_map = newMap;
    // Update live text labels in dialogue view
    Object.keys(newMap).forEach(k => {
      document.querySelectorAll(`.spk-display-${k}`).forEach(el => {
        el.textContent = newMap[k];
      });
    });

    showToast("บันทึกชื่อผู้พูดสำเร็จ และอัปเดตไฟล์ดาวน์โหลดแล้ว", "success");
  } catch (err) {
    showToast(`เกิดข้อผิดพลาด: ${err.message}`, "error");
  }
}

// ==========================================================
// Audio Player Controls & Auto Highlight
// ==========================================================
function initAudioPlayerControls() {
  const audio = document.getElementById("html5-audio");
  const playBtn = document.getElementById("player-play-btn");
  const curTimeEl = document.getElementById("player-cur-time");
  const totalTimeEl = document.getElementById("player-total-time");
  const seekSlider = document.getElementById("player-seek");

  audio.onloadedmetadata = () => {
    totalTimeEl.textContent = formatSeconds(audio.duration);
    seekSlider.max = audio.duration;
  };

  audio.ontimeupdate = () => {
    curTimeEl.textContent = formatSeconds(audio.currentTime);
    seekSlider.value = audio.currentTime;
    highlightActiveSegment(audio.currentTime);
  };

  audio.onplay = () => {
    playBtn.innerHTML = `<i data-lucide="pause" class="w-5 h-5"></i>`;
    lucide.createIcons();
  };

  audio.onpause = () => {
    playBtn.innerHTML = `<i data-lucide="play" class="w-5 h-5 ml-0.5"></i>`;
    lucide.createIcons();
  };

  seekSlider.oninput = () => {
    audio.currentTime = seekSlider.value;
  };
}

function toggleAudioPlay() {
  const audio = document.getElementById("html5-audio");
  if (!audio) return;
  if (audio.paused) {
    audio.play();
  } else {
    audio.pause();
  }
}

function changeAudioSpeed(speed) {
  const audio = document.getElementById("html5-audio");
  if (audio) {
    audio.playbackRate = parseFloat(speed);
  }
}

function seekToTime(seconds) {
  const audio = document.getElementById("html5-audio");
  if (audio && !isNaN(seconds)) {
    audio.currentTime = seconds;
    audio.play();
  }
}

function highlightActiveSegment(currentTime) {
  const cards = document.querySelectorAll(".dialogue-card");
  cards.forEach(card => {
    const start = parseFloat(card.getAttribute("data-start"));
    const end = parseFloat(card.getAttribute("data-end"));
    if (currentTime >= start && currentTime <= end) {
      if (!card.classList.contains("segment-playing")) {
        cards.forEach(c => c.classList.remove("segment-playing"));
        card.classList.add("segment-playing");
      }
    }
  });
}

// ==========================================================
// Exports: Word, PDF, Text, Copy
// ==========================================================
function triggerDirectDownload(transcriptionId, format) {
  const url = `/api/transcriptions/${transcriptionId}/export/${format}?token=${state.token}`;
  window.open(url, "_blank");
}

function downloadCurrent(format) {
  if (!state.currentTranscript) return;
  triggerDirectDownload(state.currentTranscript.id, format);
}

function copyCurrentTranscript() {
  if (!state.currentTranscript) return;
  const text = state.currentTranscript.formatted_text || state.currentTranscript.full_text || "";
  navigator.clipboard.writeText(text).then(() => {
    showToast("คัดลอกบทถอดเสียงลงคลิปบอร์ดแล้ว", "success");
  }).catch(() => {
    showToast("ไม่สามารถคัดลอกข้อความได้", "error");
  });
}

// ==========================================================
// Activity Logs Tab (Admin Only)
// ==========================================================
async function loadLogs() {
  const userFilter = document.getElementById("log-search-user").value.trim();
  const actionFilter = document.getElementById("log-filter-action").value;

  const params = new URLSearchParams();
  if (userFilter) params.append("username", userFilter);
  if (actionFilter) params.append("action", actionFilter);
  params.append("limit", "100");

  try {
    const data = await apiFetch(`/api/logs?${params.toString()}`);
    renderLogs(data.logs || []);
  } catch (err) {
    showToast(`โหลดบันทึกกิจกรรมไม่สำเร็จ: ${err.message}`, "error");
  }
}

function renderLogs(logs) {
  const tbody = document.getElementById("logs-tbody");
  const emptyDiv = document.getElementById("logs-empty");

  if (logs.length === 0) {
    tbody.innerHTML = "";
    emptyDiv.classList.remove("hidden");
    return;
  }
  emptyDiv.classList.add("hidden");

  tbody.innerHTML = logs.map(l => {
    let actionColor = "bg-slate-100 text-slate-700";
    if (l.action.includes("LOGIN")) actionColor = "bg-emerald-50 text-emerald-700 border border-emerald-200";
    if (l.action.includes("UPLOAD")) actionColor = "bg-blue-50 text-blue-700 border border-blue-200";
    if (l.action.includes("TRANSCRIBE")) actionColor = "bg-purple-50 text-purple-700 border border-purple-200";
    if (l.action.includes("DOWNLOAD")) actionColor = "bg-teal-50 text-teal-700 border border-teal-200";
    if (l.action.includes("DELETE") || l.action.includes("FAIL")) actionColor = "bg-rose-50 text-rose-700 border border-rose-200";
    if (l.action.includes("SETTINGS")) actionColor = "bg-amber-50 text-amber-700 border border-amber-200";

    const dt = l.timestamp ? l.timestamp.replace("T", " ").substring(0, 19) : "-";

    return `
      <tr class="hover:bg-slate-50 transition">
        <td class="py-3 px-4 text-slate-500 whitespace-nowrap">${dt}</td>
        <td class="py-3 px-4 font-semibold text-slate-900">${escapeHtml(l.username)}</td>
        <td class="py-3 px-4 text-slate-400 font-mono text-[11px]">${escapeHtml(l.ip_address)}</td>
        <td class="py-3 px-4">
          <span class="inline-block px-2 py-0.5 rounded text-[11px] font-bold ${actionColor}">
            ${escapeHtml(l.action)}
          </span>
        </td>
        <td class="py-3 px-4 text-slate-600 max-w-md truncate" title="${escapeHtml(l.details)}">
          ${escapeHtml(l.details)}
        </td>
      </tr>
    `;
  }).join("");
}

function exportLogsCsv() {
  window.open(`/api/logs/export?token=${state.token}`, "_blank");
}

// ==========================================================
// User Management Tab (Admin Only)
// ==========================================================
async function loadUsers() {
  try {
    const data = await apiFetch("/api/users");
    renderUsers(data.users || []);
  } catch (err) {
    showToast(`โหลดรายชื่อผู้ใช้ไม่สำเร็จ: ${err.message}`, "error");
  }
}

function renderUsers(users) {
  const tbody = document.getElementById("users-tbody");
  tbody.innerHTML = users.map(u => {
    const isSelf = state.currentUser && state.currentUser.id === u.id;
    const roleBadge = u.role === "admin" 
      ? `<span class="px-2 py-0.5 rounded-full text-[11px] font-bold bg-purple-50 text-purple-700 border border-purple-200">Admin</span>`
      : `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-slate-100 text-slate-600">User</span>`;

    const statusBadge = u.is_active
      ? `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700">เปิดใช้งาน</span>`
      : `<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700">ปิดใช้งาน</span>`;

    const lastLogin = u.last_login_at ? u.last_login_at.replace("T", " ").substring(0, 16) : "ยังไม่เคยเข้าสู่ระบบ";

    return `
      <tr class="hover:bg-slate-50 transition">
        <td class="py-3.5 px-4 font-mono text-slate-400">#${u.id}</td>
        <td class="py-3.5 px-4 font-bold text-slate-900">${escapeHtml(u.username)}</td>
        <td class="py-3.5 px-4 text-slate-700">${escapeHtml(u.full_name)}</td>
        <td class="py-3.5 px-4">${roleBadge}</td>
        <td class="py-3.5 px-4">${statusBadge}</td>
        <td class="py-3.5 px-4 text-slate-400 text-[11px]">${lastLogin}</td>
        <td class="py-3.5 px-4 text-right space-x-1">
          <button onclick="openEditUserModal(${JSON.stringify(u).replace(/"/g, '&quot;')})"
            class="p-1.5 text-slate-400 hover:text-brand-600 hover:bg-brand-50 rounded-lg transition" title="แก้ไข">
            <i data-lucide="edit-3" class="w-4 h-4"></i>
          </button>
          ${!isSelf ? `
            <button onclick="deleteUser(${u.id}, '${escapeHtml(u.username)}')"
              class="p-1.5 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded-lg transition" title="ลบผู้ใช้">
              <i data-lucide="trash-2" class="w-4 h-4"></i>
            </button>
          ` : ''}
        </td>
      </tr>
    `;
  }).join("");

  lucide.createIcons();
}

function openCreateUserModal() {
  document.getElementById("modal-user-title").textContent = "สร้างผู้ใช้งานใหม่";
  document.getElementById("modal-user-id").value = "";
  document.getElementById("modal-user-username").value = "";
  document.getElementById("modal-user-username").disabled = false;
  document.getElementById("modal-user-fullname").value = "";
  document.getElementById("modal-user-password").value = "";
  document.getElementById("modal-user-password").required = true;
  document.getElementById("modal-user-role").value = "user";
  document.getElementById("modal-user-active-group").classList.add("hidden");
  document.getElementById("modal-pwd-hint").classList.add("hidden");

  document.getElementById("modal-user").classList.remove("hidden");
}

function openEditUserModal(user) {
  document.getElementById("modal-user-title").textContent = `แก้ไขผู้ใช้ (${user.username})`;
  document.getElementById("modal-user-id").value = user.id;
  document.getElementById("modal-user-username").value = user.username;
  document.getElementById("modal-user-username").disabled = true;
  document.getElementById("modal-user-fullname").value = user.full_name;
  document.getElementById("modal-user-password").value = "";
  document.getElementById("modal-user-password").required = false;
  document.getElementById("modal-user-role").value = user.role;
  
  const activeCheckbox = document.getElementById("modal-user-active");
  activeCheckbox.checked = !!user.is_active;
  document.getElementById("modal-user-active-group").classList.remove("hidden");
  document.getElementById("modal-pwd-hint").classList.remove("hidden");

  document.getElementById("modal-user").classList.remove("hidden");
}

function closeUserModal() {
  document.getElementById("modal-user").classList.add("hidden");
}

async function submitUserForm(e) {
  e.preventDefault();
  const userId = document.getElementById("modal-user-id").value;
  const username = document.getElementById("modal-user-username").value.trim();
  const fullName = document.getElementById("modal-user-fullname").value.trim();
  const password = document.getElementById("modal-user-password").value;
  const role = document.getElementById("modal-user-role").value;
  const isActive = document.getElementById("modal-user-active").checked;

  try {
    if (!userId) {
      // Create
      await apiFetch("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username,
          full_name: fullName,
          password,
          role
        })
      });
      showToast(`สร้างผู้ใช้งาน "${username}" สำเร็จ`, "success");
    } else {
      // Update
      const body = {
        full_name: fullName,
        role: role,
        is_active: isActive
      };
      if (password) body.password = password;

      await apiFetch(`/api/users/${userId}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      showToast(`อัปเดตข้อมูลผู้ใช้งานเรียบร้อยแล้ว`, "success");
    }

    closeUserModal();
    loadUsers();
  } catch (err) {
    showToast(`เกิดข้อผิดพลาด: ${err.message}`, "error");
  }
}

async function deleteUser(id, username) {
  if (!confirm(`คุณแน่ใจหรือไม่ว่าต้องการลบบัญชีผู้ใช้ "${username}" ?`)) return;
  try {
    await apiFetch(`/api/users/${id}`, { method: "DELETE" });
    showToast(`ลบผู้ใช้ "${username}" สำเร็จ`, "success");
    loadUsers();
  } catch (err) {
    showToast(`ลบไม่สำเร็จ: ${err.message}`, "error");
  }
}

// ==========================================================
// Settings & Storage Tab (Admin Only)
// ==========================================================
async function loadSettings() {
  try {
    const data = await apiFetch("/api/settings");
    const s = data.settings;
    const st = data.storage;

    document.getElementById("setting-masked-key").textContent = s.masked_api_key || "(ยังไม่ได้ตั้งค่า)";
    document.getElementById("setting-retention-policy").value = s.retention_policy || "7_days";

    // Storage stats
    document.getElementById("stat-audio-count").textContent = `${st.upload_files_count} ไฟล์`;
    document.getElementById("stat-audio-size").textContent = formatBytes(st.upload_bytes);
    document.getElementById("stat-db-size").textContent = formatBytes(st.db_bytes);
    document.getElementById("stat-disk-free").textContent = formatBytes(st.disk_free_bytes);

    document.getElementById("test-key-result").classList.add("hidden");
  } catch (err) {
    showToast(`โหลดการตั้งค่าไม่สำเร็จ: ${err.message}`, "error");
  }
}

async function testApiKey() {
  const keyInput = document.getElementById("setting-api-key").value.trim();
  const resDiv = document.getElementById("test-key-result");
  const btn = document.getElementById("btn-test-key");

  btn.disabled = true;
  btn.textContent = "กำลังตรวจสอบ...";
  resDiv.classList.add("hidden");

  try {
    const res = await apiFetch("/api/settings/test-elevenlabs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: keyInput || undefined })
    });

    resDiv.classList.remove("hidden");
    if (res.valid) {
      resDiv.className = "p-3 rounded-xl text-xs bg-emerald-50 text-emerald-800 border border-emerald-200";
      let detailText = "";
      if (res.character_limit > 0) {
        detailText = `<br/>แพ็กเกจ (Tier): <b>${res.tier}</b> | โควต้าอักขระ: ${res.character_count.toLocaleString()} / ${res.character_limit.toLocaleString()}`;
      } else if (res.note) {
        detailText = `<br/><span class="text-emerald-700">${res.note}</span>`;
      }
      resDiv.innerHTML = `✅ เชื่อมต่อ ElevenLabs สำเร็จ!${detailText}`;
      showToast("ElevenLabs API Key ใช้งานได้ถูกต้อง", "success");
    } else {
      resDiv.className = "p-3 rounded-xl text-xs bg-rose-50 text-rose-800 border border-rose-200";
      resDiv.innerHTML = `❌ ไม่สามารถเชื่อมต่อได้: ${res.error}`;
      showToast("API Key ไม่ถูกต้อง", "error");
    }
  } catch (err) {
    resDiv.className = "p-3 rounded-xl text-xs bg-rose-50 text-rose-800 border border-rose-200";
    resDiv.innerHTML = `❌ เกิดข้อผิดพลาด: ${err.message}`;
    resDiv.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = "ทดสอบการเชื่อมต่อ";
  }
}

async function saveAllSettings() {
  const apiKey = document.getElementById("setting-api-key").value.trim();
  const retentionPolicy = document.getElementById("setting-retention-policy").value;

  const payload = {
    retention_policy: retentionPolicy
  };
  if (apiKey) {
    payload.elevenlabs_api_key = apiKey;
  }

  try {
    await apiFetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    showToast("บันทึกการตั้งค่าระบบเรียบร้อยแล้ว", "success");
    document.getElementById("setting-api-key").value = "";
    loadSettings();
    checkSettingsKeyWarning();
  } catch (err) {
    showToast(`บันทึกไม่สำเร็จ: ${err.message}`, "error");
  }
}

async function triggerCleanupNow() {
  if (!confirm("คุณต้องการสั่งล้างไฟล์เสียงเก่าออกจากดิสก์ทันทีตามนโยบายจัดเก็บใช่หรือไม่? (บทถอดความจะยังอยู่ครบ)")) return;
  try {
    const res = await apiFetch("/api/settings/cleanup-storage", { method: "POST" });
    showToast(res.message, "success");
    loadSettings();
  } catch (err) {
    showToast(`เกิดข้อผิดพลาดในการล้างไฟล์: ${err.message}`, "error");
  }
}

// ==========================================================
// Initialization on DOM Ready
// ==========================================================
document.addEventListener("DOMContentLoaded", () => {
  // Bind Login Form
  const loginForm = document.getElementById("form-login");
  if (loginForm) {
    loginForm.addEventListener("submit", (e) => {
      e.preventDefault();
      const u = document.getElementById("login-username").value;
      const p = document.getElementById("login-password").value;
      login(u, p);
    });
  }

  // Bind Upload Form & Dropzone
  const uploadForm = document.getElementById("form-upload");
  if (uploadForm) {
    uploadForm.addEventListener("submit", handleTranscribeSubmit);
  }
  initDropzone();

  // Run Auth Check
  checkAuth();
  lucide.createIcons();
});
