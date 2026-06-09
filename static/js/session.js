/* session.js – WebSocket client for live session editing
   Translated strings are injected by base.html into WS_STRINGS and UI_STRINGS. */

/* ── WebSocket ────────────────────────────────────────────────────────────── */

function initSessionWebSocket(instanceId) {
  const wsProtocol = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${wsProtocol}://${location.host}/ws/session/${instanceId}/`);
  window._sessionWS = ws;

  const dot    = document.getElementById('wsDot');
  const status = document.getElementById('wsStatus');

  function setStatus(cls, text) {
    if (dot)    dot.className = 'ws-dot ' + cls;
    if (status) status.textContent = text;
  }

  setStatus('connecting', WS_STRINGS.connecting);
  ws.onopen  = () => setStatus('connected', WS_STRINGS.live);
  ws.onclose = () => { setStatus('error', WS_STRINGS.disconnected); window._sessionWS = null; };
  ws.onerror = () => setStatus('error', WS_STRINGS.error);

  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    switch (msg.type) {
      case 'init':
        handleInit(msg.data);
        window.SESSION_IS_TRAINER = msg.trainer;
        break;
      case 'attendance_update': handleAttendanceUpdate(msg.data);  break;
      case 'plan_add':          handlePlanAdd(msg.data);           break;
      case 'plan_update':       handlePlanUpdate(msg.data);        break;
      case 'plan_delete':       handlePlanDelete(msg.data);        break;
      case 'plan_reorder':      handlePlanReorder(msg.data);       break;
      case 'notes_update':      handleNotesUpdate(msg.data);       break;
    }
  };
}

function wsSend(action, data) {
  if (!window._sessionWS || window._sessionWS.readyState !== WebSocket.OPEN) return;
  window._sessionWS.send(JSON.stringify({ action, data }));
}

/* ── Attendance ───────────────────────────────────────────────────────────── */

window.updateAttendance = function (swimmerId, status) {
  console.log(swimmerId, status);
  console.log(window.SESSION_IS_TRAINER)
  if (!window.SESSION_IS_TRAINER) return;
  console.log(swimmerId, status);
  wsSend('update_attendance', { swimmer_id: swimmerId, status });
  applyAttendanceUpdate({ swimmer_id: swimmerId, status }); // optimistic
};

function handleAttendanceUpdate(data) { applyAttendanceUpdate(data); }

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

/* ── Training Plan ────────────────────────────────────────────────────────── */

let _editingEntryId = null;

window.addPlanEntry = function () {
  _editingEntryId = null;
  clearEditor();
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
