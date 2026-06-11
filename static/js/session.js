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

window.addPlanEntry = function () {
  _editingEntryId = null;
  clearEditor();
  updatePhotoEditorUI(null);
  document.getElementById('planEntryEditor').style.display = 'block';
  document.getElementById('editorDescription').focus();
};

window.editPlanEntry = function (entryId) {
  _editingEntryId = entryId;
  const cached = window._planCache && window._planCache[entryId];
  if (cached) {
    document.getElementById('editorCategory').value    = cached.category    || 'main';
    document.getElementById('editorDescription').value = cached.description || '';
    document.getElementById('editorDistance').value    = cached.distance    || '';
    document.getElementById('editorIntensity').value   = cached.intensity   || '';
    document.getElementById('editorRest').value        = cached.rest_seconds || '';
  }
  updatePhotoEditorUI(cached);
  document.getElementById('planEntryEditor').style.display = 'block';
};

window.cancelPlanEdit = function () {
  document.getElementById('planEntryEditor').style.display = 'none';
  _editingEntryId = null;
};

window.savePlanEntry = function () {
  const data = {
    category:     document.getElementById('editorCategory').value,
    description:  document.getElementById('editorDescription').value,
    distance:     document.getElementById('editorDistance').value,
    intensity:    document.getElementById('editorIntensity').value,
    rest_seconds: parseInt(document.getElementById('editorRest').value) || null,
  };
  if (_editingEntryId) {
    data.id = _editingEntryId;
    wsSend('update_plan_entry', data);
    handlePlanUpdate({ ...data, id: _editingEntryId });
  } else {
    wsSend('add_plan_entry', data);
  }
  cancelPlanEdit();
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

function clearEditor() {
  ['editorCategory', 'editorDescription', 'editorDistance', 'editorIntensity', 'editorRest']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = id === 'editorCategory' ? 'main' : ''; });
}

/* ── Training plan photo (upload from camera or gallery) ──────────────────── */

function updatePhotoEditorUI(entry) {
  const section  = document.getElementById('editorPhotoSection');
  const hint     = document.getElementById('editorPhotoNewHint');
  const preview  = document.getElementById('editorPhotoPreview');
  const removeBtn = document.getElementById('editorPhotoRemoveBtn');
  if (!section) return;

  // A brand-new, unsaved entry has no id yet, so there's nothing to attach
  // a photo to until it's saved once.
  if (!entry || !entry.id) {
    section.style.display = 'none';
    if (hint) hint.style.display = 'block';
    return;
  }

  section.style.display = 'block';
  if (hint) hint.style.display = 'none';

  if (entry.photo_url) {
    if (preview) { preview.src = entry.photo_url; preview.style.display = 'block'; }
    if (removeBtn) removeBtn.style.display = 'inline-block';
  } else {
    if (preview) { preview.style.display = 'none'; preview.removeAttribute('src'); }
    if (removeBtn) removeBtn.style.display = 'none';
  }
}

window.triggerPlanEntryPhotoCamera = function () {
  document.getElementById('editorPhotoCameraInput')?.click();
};

window.triggerPlanEntryPhotoGallery = function () {
  document.getElementById('editorPhotoGalleryInput')?.click();
};

document.addEventListener('change', (e) => {
  if (e.target.id === 'editorPhotoCameraInput' || e.target.id === 'editorPhotoGalleryInput') {
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
      updatePhotoEditorUI(entry);
      wsSend('photo_updated', entry); // tell other connected devices
    })
    .catch(() => alert(UI_STRINGS.photoUploadError));
}

window.removePlanEntryPhoto = function () {
  if (!_editingEntryId) return;
  if (!confirm(UI_STRINGS.confirmRemovePhoto)) return;
  fetch(`/training/plan-entry/${_editingEntryId}/photo/`, {
    method: 'DELETE',
    headers: { 'X-CSRFToken': getCookie('csrftoken') },
  })
    .then(r => { if (!r.ok) throw new Error('delete failed'); return r.json(); })
    .then(entry => {
      handlePlanUpdate(entry);
      updatePhotoEditorUI(entry);
      wsSend('photo_updated', entry);
    })
    .catch(() => alert(UI_STRINGS.photoUploadError));
};

/* Open a plan entry's photo full-size in a new tab */
window.viewPlanEntryPhoto = function (url) {
  window.open(url, '_blank');
};

/* Use translated category labels from UI_STRINGS (injected by base.html) */
const CAT_LABELS = () => ({
  warmup:   UI_STRINGS.catWarmup,
  main:     UI_STRINGS.catMain,
  cooldown: UI_STRINGS.catCooldown,
});

function renderPlanEntryHTML(entry) {
  const cat      = entry.category || 'main';
  const catLabel = CAT_LABELS()[cat] || cat;
  const trainer  = window.SESSION_IS_TRAINER;
  return `
  <div class="plan-entry-row d-flex align-items-start gap-2" data-entry-id="${entry.id}">
    ${trainer ? '<span class="drag-handle mt-1"><i class="bi bi-grip-vertical"></i></span>' : ''}
    ${entry.photo_url ? `<img src="${entry.photo_url}" class="plan-entry-photo-thumb" alt="" onclick="viewPlanEntryPhoto('${entry.photo_url}')">` : ''}
    <div class="flex-grow-1">
      <div class="d-flex align-items-center gap-2 mb-1 flex-wrap">
        <span class="badge category-badge-${cat} rounded-pill px-2 py-1" style="font-size:.72rem">${catLabel}</span>
        ${entry.distance  ? `<span class="badge bg-secondary rounded-pill" style="font-size:.72rem">${entry.distance}</span>` : ''}
        ${entry.intensity ? `<span class="text-muted" style="font-size:.75rem"><i class="bi bi-lightning"></i> ${entry.intensity}</span>` : ''}
      </div>
      <p class="mb-0 small" style="line-height:1.4">${entry.description || ''}</p>
      ${entry.rest_seconds ? `<small class="text-muted"><i class="bi bi-hourglass me-1"></i>${entry.rest_seconds}s</small>` : ''}
    </div>
    ${trainer ? `
    <div class="d-flex flex-column gap-1">
      <button class="btn btn-xs btn-outline-secondary p-1" style="line-height:1" onclick="editPlanEntry(${entry.id})">
        <i class="bi bi-pencil" style="font-size:.7rem"></i>
      </button>
      <button class="btn btn-xs btn-outline-danger p-1" style="line-height:1" onclick="deletePlanEntry(${entry.id})">
        <i class="bi bi-trash" style="font-size:.7rem"></i>
      </button>
    </div>` : ''}
  </div>`;
}

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
