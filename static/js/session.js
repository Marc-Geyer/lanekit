/* session.js – WebSocket client for live session editing
   Translated strings are injected by base.html into WS_STRINGS and UI_STRINGS. */

/* ── Connection management ────────────────────────────────────────────────
   The WebSocket reliably drops when a phone's screen locks. To keep the
   session usable we:
     1. Auto-reconnect with exponential backoff (a few quick retries).
     2. Fall back to polling /training/session/<id>/state/ every few
        seconds if reconnecting keeps failing.
     3. Reconnect immediately once the page becomes visible again
        (screen unlock / app foregrounded).
     4. Offer a manual "Reconnect" button.
     5. Queue attendance changes in localStorage so they're never lost,
        even if made while fully offline, and replay them on reconnect.
   ─────────────────────────────────────────────────────────────────────── */

const WS_RECONNECT_DELAYS = [1000, 2000, 5000]; // ms – exponential-ish backoff
const WS_POLL_INTERVAL = 5000; // ms

window._wsConn = window._wsConn || {
  instanceId: null,
  ws: null,
  reconnectAttempts: 0,
  reconnectTimer: null,
  pollTimer: null,
};

function initSessionWebSocket(instanceId) {
  window._wsConn.instanceId = instanceId;
  window._wsConn.reconnectAttempts = 0;
  connectSessionWebSocket();
}

function connectSessionWebSocket() {
  const conn = window._wsConn;
  if (!conn.instanceId) return;

  clearTimeout(conn.reconnectTimer);
  stopStatePolling();
  setWsStatus('connecting', WS_STRINGS.connecting);

  const wsProtocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${wsProtocol}://${location.host}/ws/session/${conn.instanceId}/`);
  conn.ws = ws;
  window._sessionWS = ws; // kept for backwards compatibility

  ws.onopen = () => {
    conn.reconnectAttempts = 0;
    setWsStatus('connected', WS_STRINGS.live);
    flushPendingAttendanceQueue();
  };
  ws.onclose = () => {
    conn.ws = null;
    window._sessionWS = null;
    scheduleSessionReconnect();
  };
  ws.onerror = () => setWsStatus('error', WS_STRINGS.error);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case 'init':
        handleInit(msg.data);
        window.SESSION_IS_TRAINER = msg.trainer;
        break;
      case 'attendance_update':    handleAttendanceUpdate(msg.data);  break;
      case 'bulk_attendance_update': handleBulkAttendanceUpdate(msg.data); break;
      case 'plan_add':          handlePlanAdd(msg.data);           break;
      case 'plan_update':       handlePlanUpdate(msg.data);        break;
      case 'plan_delete':       handlePlanDelete(msg.data);        break;
      case 'plan_reorder':      handlePlanReorder(msg.data);       break;
      case 'notes_update':      handleNotesUpdate(msg.data);       break;
      case 'sync_attendance':   handleSyncAttendance(msg.data);   break;
    }
  };
}

function scheduleSessionReconnect() {
  const conn = window._wsConn;
  if (!conn.instanceId) return;
  if (conn.reconnectAttempts < WS_RECONNECT_DELAYS.length) {
    setWsStatus('connecting', WS_STRINGS.connecting);
    const delay = WS_RECONNECT_DELAYS[conn.reconnectAttempts];
    conn.reconnectAttempts++;
    conn.reconnectTimer = setTimeout(connectSessionWebSocket, delay);
  } else {
    setWsStatus('polling', WS_STRINGS.polling);
    startStatePolling();
  }
}

/* Manual "Reconnect" button handler */
window.reconnectSession = function () {
  const conn = window._wsConn;
  if (!conn.instanceId) return;
  conn.reconnectAttempts = 0;
  connectSessionWebSocket();
};

/* Reconnect as soon as the page/tab is foregrounded again (e.g. phone unlocked) */
document.addEventListener('visibilitychange', () => {
  const conn = window._wsConn;
  if (document.visibilityState !== 'visible' || !conn.instanceId) return;
  if (!conn.ws || conn.ws.readyState !== WebSocket.OPEN) {
    conn.reconnectAttempts = 0;
    connectSessionWebSocket();
  }
});

/* Try again whenever the device regains network connectivity */
window.addEventListener('online', () => {
  const conn = window._wsConn;
  if (!conn.instanceId) return;
  if (!conn.ws || conn.ws.readyState !== WebSocket.OPEN) {
    conn.reconnectAttempts = 0;
    connectSessionWebSocket();
  } else {
    flushPendingAttendanceQueue();
  }
});

function closeSessionWebSocket() {
  const conn = window._wsConn;
  clearTimeout(conn.reconnectTimer);
  stopStatePolling();
  if (conn.ws) conn.ws.close();
  conn.ws = null;
  conn.instanceId = null;
  conn.reconnectAttempts = 0;
  window._sessionWS = null;
}
window.closeSessionWebSocket = closeSessionWebSocket;

function setWsStatus(cls, text) {
  const dot    = document.getElementById('wsDot');
  const status = document.getElementById('wsStatus');
  const reconnectBtn = document.getElementById('wsReconnectBtn');
  if (dot)    dot.className = 'ws-dot ' + cls;
  if (status) status.textContent = text;
  if (reconnectBtn) reconnectBtn.style.display = (cls === 'polling' || cls === 'error') ? 'inline-block' : 'none';
}

/* ── Polling fallback ─────────────────────────────────────────────────────── */

function startStatePolling() {
  const conn = window._wsConn;
  if (conn.pollTimer) return;
  pollSessionState(); // fetch immediately, then on an interval
  conn.pollTimer = setInterval(pollSessionState, WS_POLL_INTERVAL);
}

function stopStatePolling() {
  const conn = window._wsConn;
  if (conn.pollTimer) {
    clearInterval(conn.pollTimer);
    conn.pollTimer = null;
  }
}

function pollSessionState() {
  const conn = window._wsConn;
  if (!conn.instanceId) return;
  fetch(`/training/session/${conn.instanceId}/state/`, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
    .then(r => { if (!r.ok) throw new Error('poll failed'); return r.json(); })
    .then(data => {
      applyPolledState(data);
      flushPendingAttendanceQueue();
    })
    .catch(() => { /* offline – keep retrying on the interval */ });
}

function applyPolledState(data) {
  window.SESSION_IS_TRAINER = data.is_trainer;

  window._planCache = window._planCache || {};
  (data.plan_entries || []).forEach(e => { window._planCache[e.id] = e; });
  const planContainer = document.getElementById('planEntriesContainer');
  if (planContainer) {
    if (!(data.plan_entries || []).length) {
      planContainer.innerHTML = `<div id="emptyPlan" class="text-center text-muted py-4 small">
        <i class="bi bi-clipboard d-block mb-2" style="font-size:1.5rem"></i>${UI_STRINGS.noEntries}
      </div>`;
    } else {
      planContainer.innerHTML = data.plan_entries.map(renderPlanEntryHTML).join('');
      initSortable();
    }
  }

  (data.attendances || []).forEach(att => applyAttendanceUpdate(att));
  handleNotesUpdate({ notes: data.trainer_notes });
}

function wsSend(action, data) {
  const conn = window._wsConn;
  if (!conn.ws || conn.ws.readyState !== WebSocket.OPEN) return;
  conn.ws.send(JSON.stringify({ action, data }));
}

/* ── Offline queue for attendance changes ─────────────────────────────────── */

function attendanceQueueKey() {
  return `lanekit_pending_attendance_${window._wsConn.instanceId}`;
}

function readAttendanceQueue() {
  try { return JSON.parse(localStorage.getItem(attendanceQueueKey())) || {}; }
  catch (e) { return {}; }
}

function writeAttendanceQueue(queue) {
  try {
    if (Object.keys(queue).length) localStorage.setItem(attendanceQueueKey(), JSON.stringify(queue));
    else localStorage.removeItem(attendanceQueueKey());
  } catch (e) { /* storage unavailable – nothing more we can do */ }
}

function queueAttendanceChange(swimmerId, status) {
  if (!window._wsConn.instanceId) return;
  const queue = readAttendanceQueue();
  queue[swimmerId] = status;
  writeAttendanceQueue(queue);
}

/* Send a queued/pending attendance change via WS if possible, else REST. */
function sendAttendanceChange(swimmerId, status) {
  const conn = window._wsConn;
  if (conn.ws && conn.ws.readyState === WebSocket.OPEN) {
    wsSend('update_attendance', { swimmer_id: swimmerId, status });
    const queue = readAttendanceQueue();
    delete queue[swimmerId];
    writeAttendanceQueue(queue);
    return;
  }
  if (!conn.instanceId) return;
  fetch(`/training/session/${conn.instanceId}/attendance/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') },
    body: JSON.stringify({ swimmer_id: swimmerId, status }),
  }).then(r => {
    if (!r.ok) throw new Error('attendance sync failed');
    const queue = readAttendanceQueue();
    delete queue[swimmerId];
    writeAttendanceQueue(queue);
  }).catch(() => { /* stays queued, retried on next reconnect/poll */ });
}

function flushPendingAttendanceQueue() {
  const queue = readAttendanceQueue();
  Object.entries(queue).forEach(([swimmerId, status]) => {
    sendAttendanceChange(parseInt(swimmerId, 10), status);
  });
}

/* ── Attendance ───────────────────────────────────────────────────────────── */

window.updateAttendance = function (swimmerId, status) {
  if (!window.SESSION_IS_TRAINER) return;
  applyAttendanceUpdate({ swimmer_id: swimmerId, status }); // optimistic
  queueAttendanceChange(swimmerId, status); // persist locally first, in case we're offline
  sendAttendanceChange(swimmerId, status);
};

function handleAttendanceUpdate(data) { applyAttendanceUpdate(data); }

function handleBulkAttendanceUpdate(data) {
  (data.updated || []).forEach(att => applyAttendanceUpdate(att));
}

window.markUnknownAbsent = function () {
  if (!window.SESSION_IS_TRAINER) return;
  if (!window._wsConn.ws || window._wsConn.ws.readyState !== WebSocket.OPEN) {
    alert(WS_STRINGS.disconnected);
    return;
  }
  if (!confirm(UI_STRINGS.confirmMarkUnknownAbsent)) return;
  wsSend('mark_unknown_absent', {});
};

function applyAttendanceUpdate(data) {
  const row = document.getElementById(`att-row-${data.swimmer_id}`);
  if (!row) return;
  row.querySelectorAll('.status-btn').forEach(btn =>
    btn.classList.toggle('active', btn.dataset.status === data.status)
  );
  updateAttendanceCounts();
}

function updateAttendanceCounts() {
  const counts = { present: 0, absent: 0, excused: 0, unknown: 0 };
  document.querySelectorAll('#attendanceTableBody tr[id^="att-row-"]').forEach(row => {
    const active = row.querySelector('.status-btn.active');
    const s = active ? active.dataset.status : 'unknown';
    counts[s] = (counts[s] || 0) + 1;
  });
  const p = document.getElementById('countPresent');
  const a = document.getElementById('countAbsent');
  const e = document.getElementById('countExcused');
  if (p) p.textContent = counts.present;
  if (a) a.textContent = counts.absent;
  if (e) e.textContent = counts.excused;
}

window.syncAttendance = function () {
  if (!window.SESSION_IS_TRAINER) return;
  if (!confirm(UI_STRINGS.confirmSyncAttendance)) return;
  const btn = document.getElementById('syncAttBtn');
  if (btn) { btn.disabled = true; btn.querySelector('i').className = 'bi bi-hourglass-split'; }
  wsSend('sync_attendance', {});
};

function handleSyncAttendance(data) {
  const btn = document.getElementById('syncAttBtn');
  if (btn) { btn.disabled = false; btn.querySelector('i').className = 'bi bi-arrow-repeat'; }

  const tbody = document.getElementById('attendanceTableBody');
  if (!tbody) return;

  // Remove rows for de-listed swimmers
  (data.removed || []).forEach(sid => {
    const row = document.getElementById(`att-row-${sid}`);
    if (row) row.remove();
  });

  // Add rows for new members
  (data.added || []).forEach(att => {
    if (document.getElementById(`att-row-${att.swimmer_id}`)) return; // already present
    const emptyRow = tbody.querySelector('td[colspan]')?.closest('tr');
    if (emptyRow) emptyRow.remove();
    tbody.insertAdjacentHTML('beforeend', renderAttendanceRowHTML(att));
  });

  updateAttendanceCounts();
}

/* ── Training Plan ────────────────────────────────────────────────────────── */

let _editingEntryId = null;


/* ── Quick-add / edit shorthand parser ────────────────────────────────────────
   One line in, structured fields out:
     "H: 8x100m @GA2 20s Kraul, Fokus Beinschlag"
   WU:/H:/CD:        -> category   (optional; defaults to the previous entry's category)
   NxM(m) / NxNxM(m) -> distance   (e.g. 8x100m, 4x6x100m)
   Nmin / N' / N min -> distance   (time-based sets instead of meters, e.g. 5min, 5')
   @token            -> intensity  (e.g. @GA2, @Sprint)
   Ns / Nsek         -> rest_seconds
   everything left over -> description
   Only the FIRST distance-shaped token in the line is taken; anything later
   that merely looks like a distance (e.g. a stroke breakdown
   "200m: 50m arme, 250m beine, 100m gesamt") stays in the description as-is.
   Plain text with none of these markers is just filed as the description,
   so a free-text note ("Besprechung Wettkampfplan") still works.
   ─────────────────────────────────────────────────────────────────────────── */
const CATEGORY_PREFIXES = { wu: 'warmup', h: 'main', cd: 'cooldown' };
const CATEGORY_SHORT    = { warmup: 'WU', main: 'H', cooldown: 'CD' };

function parsePlanEntryText(raw, fallbackCategory) {
  let text = (raw || '').trim();
  let category = fallbackCategory || 'main';

  const catMatch = text.match(/^(wu|h|cd)\s*:\s*/i);
  if (catMatch) {
    category = CATEGORY_PREFIXES[catMatch[1].toLowerCase()];
    text = text.slice(catMatch[0].length);
  }

  let rest_seconds = null;
  const restMatch = text.match(/\b(\d{1,3})\s?(s|sec|sek)\b\.?/i);
  if (restMatch) {
    rest_seconds = parseInt(restMatch[1], 10);
    text = (text.slice(0, restMatch.index) + text.slice(restMatch.index + restMatch[0].length)).trim();
  }

  // Distance: take whichever of these forms occurs EARLIEST in the (remaining)
  // text — everything after it that merely looks like a distance too (e.g. a
  // stroke breakdown "25m arme, 25m beine, 100m gesamt") is left untouched as
  // description. Covers plain meters, repeat×repeat×...×meters chains
  // (4x100m, 4x6x100m, ...), and time-based sets used instead of a distance
  // (5min, 5 min, 5').
  const distCandidates = [
    { re: /\b(\d+(?:\s*[x×]\s*\d+)+)\s*m?\b/i, fmt: (m) => `${m[1].replace(/\s*[x×]\s*/gi, '×')}m` },
    { re: /\b(\d+)\s*m\b/i,                    fmt: (m) => `${m[1]}m` },
    { re: /\b(\d+)\s*(?:min|minuten)\b/i,      fmt: (m) => `${m[1]}min` },
    { re: /\b(\d+)\s*'/,                       fmt: (m) => `${m[1]}'` },
  ];
  let distance = '';
  let bestDist = null;
  for (const cand of distCandidates) {
    const m = text.match(cand.re);
    if (m && (bestDist === null || m.index < bestDist.match.index)) bestDist = { match: m, fmt: cand.fmt };
  }
  if (bestDist) {
    distance = bestDist.fmt(bestDist.match);
    text = (text.slice(0, bestDist.match.index) + text.slice(bestDist.match.index + bestDist.match[0].length)).trim();
  }

  let intensity = '';
  const intMatch = text.match(/@(\S+)/);
  if (intMatch) {
    intensity = intMatch[1].replace(/[.,;:]+$/, '');
    text = (text.slice(0, intMatch.index) + text.slice(intMatch.index + intMatch[0].length)).trim();
  }

  const description = text.replace(/\s{2,}/g, ' ').replace(/^[,;\s]+|[,;\s]+$/g, '');

  return { category, distance, intensity, rest_seconds, description };
}

/* Rebuild the shorthand from an entry's fields, for the click-to-edit input. */
function composePlanEntryText(entry) {
  const parts = [`${CATEGORY_SHORT[entry.category] || 'H'}:`];
  if (entry.distance) parts.push(entry.distance);
  if (entry.intensity) parts.push(`@${entry.intensity}`);
  if (entry.rest_seconds) parts.push(`${entry.rest_seconds}s`);
  if (entry.description) parts.push(entry.description);
  return parts.join(' ');
}

/* Human-readable single-line label (no shorthand markers) for display. */
function composeInlineLabel(entry) {
  const bits = [];
  if (entry.distance) bits.push(entry.distance);
  if (entry.intensity) bits.push(entry.intensity);
  if (entry.description) bits.push(entry.description);
  if (entry.rest_seconds) bits.push(`⏱${entry.rest_seconds}s`);
  return bits.join(' · ') || '…';
}

function lastPlanCategory() {
  const rows = document.querySelectorAll('#planEntriesContainer .plan-entry-row');
  if (!rows.length) return 'main';
  const lastId = rows[rows.length - 1].dataset.entryId;
  return (window._planCache && window._planCache[lastId] && window._planCache[lastId].category) || 'main';
}

/* Quick-add: called on Enter in the field, or on the "+" button click. */
function submitPlanQuickAdd() {
  const input = document.getElementById('planQuickAdd');
  if (!input) return;
  const text = input.value.trim();
  if (!text) return;
  wsSend('add_plan_entry', parsePlanEntryText(text, lastPlanCategory()));
  input.value = '';
  input.focus();
}

document.addEventListener('keydown', (e) => {
  if (e.target.id === 'planQuickAdd' && e.key === 'Enter') {
    e.preventDefault();
    submitPlanQuickAdd();
  }
});

document.addEventListener('click', (e) => {
  if (e.target.closest('#planQuickAddBtn')) {
    submitPlanQuickAdd();
  }
  if (e.target.closest('#planPhotoQuickAddBtn')) {
    document.getElementById('planPhotoQuickAddInput')?.click();
  }
});

/* Photo-only quick add: for digitizing an existing paper plan poolside —
   snap a photo and it becomes its own entry immediately, no typing needed.
   Goes straight to the DB via a dedicated endpoint (create-with-photo in one
   request), then tells other connected devices via the WebSocket; the
   broadcast comes back to this device too, so rendering happens uniformly
   through handlePlanAdd for everyone, the same as a normal quick-add. */
document.addEventListener('change', (e) => {
  if (e.target.id === 'planPhotoQuickAddInput') {
    const file = e.target.files && e.target.files[0];
    e.target.value = '';
    if (!file) return;
    uploadPhotoOnlyEntry(file);
  }
});

function uploadPhotoOnlyEntry(file) {
  const formData = new FormData();
  formData.append('photo', file);
  formData.append('category', lastPlanCategory());
  fetch(`/training/session/${window._wsConn.instanceId}/plan-entry/photo-create/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCookie('csrftoken') },
    body: formData,
  })
    .then(r => { if (!r.ok) throw new Error('create failed'); return r.json(); })
    .then(entry => {
      wsSend('photo_entry_created', entry);
    })
    .catch(() => alert(UI_STRINGS.photoUploadError));
}


/* Click a row's text to turn it into an editable shorthand input. */
window.startPlanEntryEdit = function (entryId) {
  const row = document.querySelector(`.plan-entry-row[data-entry-id="${entryId}"]`);
  const span = row && row.querySelector('.plan-entry-text');
  if (!span) return;
  const entry = (window._planCache && window._planCache[entryId]) || {};

  const input = document.createElement('input');
  input.type = 'text';
  input.className = 'plan-entry-edit-input form-control form-control-sm bg-transparent border-secondary text-light flex-grow-1';
  input.value = composePlanEntryText(entry);
  span.replaceWith(input);
  input.focus();
  input.select();

  let committed = false;
  const commit = () => {
    if (committed) return;
    committed = true;
    const parsed = parsePlanEntryText(input.value, entry.category);
    parsed.id = entryId;
    wsSend('update_plan_entry', parsed);
    handlePlanUpdate({ ...entry, ...parsed });
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commit(); }
    if (e.key === 'Escape') { e.preventDefault(); committed = true; handlePlanUpdate(entry); }
  });
  input.addEventListener('blur', commit);
};

/* Checkbox toggle – stays in place, never reorders. */
window.togglePlanEntry = function (entryId, checked) {
  const entry = (window._planCache && window._planCache[entryId]) || {};
  wsSend('update_plan_entry', { id: entryId, checked });
  handlePlanUpdate({ ...entry, id: entryId, checked });
};


window.deletePlanEntry = function (entryId) {
  if (!confirm(UI_STRINGS.confirmDeleteEntry)) return;
  wsSend('delete_plan_entry', { id: entryId });
  handlePlanDelete({ id: entryId });
};

window.saveNotes = function () {
  wsSend('update_notes', { notes: document.getElementById('trainerNotes')?.value || '' });
};

document.addEventListener('input', (e) => {
  if (e.target.id === 'trainerNotes') {
    clearTimeout(window._notesSaveTimer);
    window._notesSaveTimer = setTimeout(saveNotes, 1000);
  }
});

function handleInit(data) {
  window._planCache = {};
  (data.plan_entries || []).forEach(e => { window._planCache[e.id] = e; });
  updateAttendanceCounts();
}

function handlePlanAdd(entry) {
  window._planCache = window._planCache || {};
  window._planCache[entry.id] = entry;
  const container = document.getElementById('planEntriesContainer');
  const empty = document.getElementById('emptyPlan');
  if (empty) empty.remove();
  container.insertAdjacentHTML('beforeend', renderPlanEntryHTML(entry));
  initSortable();
}

function handlePlanUpdate(entry) {
  if (window._planCache) window._planCache[entry.id] = { ...(window._planCache[entry.id] || {}), ...entry };
  const row = document.querySelector(`.plan-entry-row[data-entry-id="${entry.id}"]`);
  if (row) row.outerHTML = renderPlanEntryHTML(entry);
}

function handlePlanDelete(data) {
  if (window._planCache) delete window._planCache[data.id];
  const row = document.querySelector(`.plan-entry-row[data-entry-id="${data.id}"]`);
  if (row) row.remove();
  const container = document.getElementById('planEntriesContainer');
  if (container && !container.querySelector('.plan-entry-row')) {
    container.innerHTML = `<div id="emptyPlan" class="text-center text-muted py-4 small">
      <i class="bi bi-clipboard d-block mb-2" style="font-size:1.5rem"></i>${UI_STRINGS.noEntries}
    </div>`;
  }
}

function handlePlanReorder(data) {
  const container = document.getElementById('planEntriesContainer');
  if (!container) return;
  data.order.forEach(item => {
    const row = container.querySelector(`.plan-entry-row[data-entry-id="${item.id}"]`);
    if (row) container.appendChild(row);
  });
}

function handleNotesUpdate(data) {
  const ta = document.getElementById('trainerNotes');
  if (ta && document.activeElement !== ta) ta.value = data.notes || '';
}

/* ── Training plan photo (single OS picker – camera or library) ───────────── */

window.triggerPlanEntryPhotoFor = function (entryId) {
  _editingEntryId = entryId;
  document.getElementById('planPhotoInput')?.click();
};

document.addEventListener('change', (e) => {
  if (e.target.id === 'planPhotoInput') {
    const file = e.target.files && e.target.files[0];
    if (file) uploadPlanEntryPhoto(file);
    e.target.value = ''; // allow picking the same file again later
  }
});

function uploadPlanEntryPhoto(file) {
  if (!_editingEntryId) return;
  const formData = new FormData();
  formData.append('photo', file);
  fetch(`/training/plan-entry/${_editingEntryId}/photo/`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCookie('csrftoken') },
    body: formData,
  })
    .then(r => { if (!r.ok) throw new Error('upload failed'); return r.json(); })
    .then(entry => {
      handlePlanUpdate(entry);
      wsSend('photo_updated', entry); // tell other connected devices
    })
    .catch(() => alert(UI_STRINGS.photoUploadError));
}

window.removePlanEntryPhotoFor = function (entryId, evt) {
  if (evt) evt.stopPropagation();
  if (!confirm(UI_STRINGS.confirmRemovePhoto)) return;
  fetch(`/training/plan-entry/${entryId}/photo/`, {
    method: 'DELETE',
    headers: { 'X-CSRFToken': getCookie('csrftoken') },
  })
    .then(r => { if (!r.ok) throw new Error('delete failed'); return r.json(); })
    .then(entry => {
      handlePlanUpdate(entry);
      wsSend('photo_updated', entry);
    })
    .catch(() => alert(UI_STRINGS.photoUploadError));
};

/* Open a plan entry's photo full-size in a new tab */
window.viewPlanEntryPhoto = function (url) {
  window.open(url, '_blank');
};

function renderPlanEntryHTML(entry) {
  const cat     = entry.category || 'main';
  const trainer = window.SESSION_IS_TRAINER;
  const catLabel = { warmup: UI_STRINGS.catWarmup, main: UI_STRINGS.catMain, cooldown: UI_STRINGS.catCooldown }[cat] || cat;
  return `
  <div class="plan-entry-row d-flex align-items-center gap-2${entry.checked ? ' is-checked' : ''}" data-entry-id="${entry.id}">
    ${trainer ? '<span class="drag-handle"><i class="bi bi-grip-vertical"></i></span>' : ''}
    ${trainer
      ? `<input type="checkbox" class="plan-check" ${entry.checked ? 'checked' : ''} onchange="togglePlanEntry(${entry.id}, this.checked)">`
      : `<i class="bi ${entry.checked ? 'bi-check-circle-fill text-success' : 'bi-circle text-muted'}"></i>`}
    <span class="plan-cat-dot cat-${cat}" title="${catLabel}"></span>
    <span class="plan-entry-text flex-grow-1 text-truncate"${trainer ? ` onclick="startPlanEntryEdit(${entry.id})"` : ''}>
      ${composeInlineLabel(entry)}
    </span>
    ${entry.photo_url ? `
    <span class="plan-entry-photo-wrap">
      <img src="${entry.photo_url}" class="plan-entry-photo-thumb-sm" onclick="viewPlanEntryPhoto('${entry.photo_url}')">
      ${trainer ? `<button class="plan-entry-photo-remove" title="${UI_STRINGS.btnRemovePhoto}" onclick="removePlanEntryPhotoFor(${entry.id}, event)">&times;</button>` : ''}
    </span>` : ''}
    ${trainer ? `
    <button class="btn btn-xs btn-icon-only" title="${UI_STRINGS.btnAddPhoto}" onclick="triggerPlanEntryPhotoFor(${entry.id})"><i class="bi bi-camera" style="font-size:.75rem"></i></button>
    <button class="btn btn-xs btn-icon-only text-danger" onclick="deletePlanEntry(${entry.id})"><i class="bi bi-trash" style="font-size:.75rem"></i></button>` : ''}
  </div>`;
}

/* ── Collapsible sections – remembered per browser ─────────────────────────── */

function initCollapsibleSections() {
  ['plan', 'attendance'].forEach(key => {
    const body = document.getElementById(`${key}Body`);
    if (!body || typeof bootstrap === 'undefined') return;
    const collapsed = localStorage.getItem(`lanekit_${key}Collapsed`) === '1';
    const instance = bootstrap.Collapse.getOrCreateInstance(body, { toggle: false });
    if (collapsed) instance.hide(); else instance.show();
    body.addEventListener('shown.bs.collapse', () => localStorage.setItem(`lanekit_${key}Collapsed`, '0'));
    body.addEventListener('hidden.bs.collapse', () => localStorage.setItem(`lanekit_${key}Collapsed`, '1'));
  });
}
window.initCollapsibleSections = initCollapsibleSections;

function renderAttendanceRowHTML(att) {
  const sid = att.swimmer_id;
  const statuses = ['present', 'absent', 'excused', 'unknown'];
  const icons    = { present: 'check-lg', absent: 'x-lg', excused: 'shield-check', unknown: 'question-lg' };
  const buttons  = statuses.map(s => `
    <button class="status-btn${att.status === s ? ' active' : ''}"
            data-status="${s}"
            onclick="updateAttendance(${sid},'${s}')">
      <i class="bi bi-${icons[s]}"></i>
    </button>`).join('');

  return `
  <tr id="att-row-${sid}">
    <td style="width:36px"><div class="sc-avatar-sm">${att.swimmer_initials}</div></td>
    <td><div class="fw-medium small">${att.swimmer_name}</div></td>
    <td class="text-end">
      <div class="d-flex gap-1 justify-content-end flex-wrap">${buttons}</div>
    </td>
  </tr>`;
}

/* ── Sortable drag-and-drop for plan entries ──────────────────────────────── */

function initSortable() {
  const container = document.getElementById('planEntriesContainer');
  if (!container || !window.SESSION_IS_TRAINER) return;
  if (container._sortable) container._sortable.destroy();
  container._sortable = Sortable.create(container, {
    handle: '.drag-handle',
    animation: 150,
    onEnd: () => {
      const order = [...container.querySelectorAll('.plan-entry-row')]
        .map((r, i) => ({ id: parseInt(r.dataset.entryId), order: i }));
      wsSend('reorder_plan', { order });
    },
  });
}
