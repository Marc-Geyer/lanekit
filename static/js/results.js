/* Swim-time entry inside the session modal (trainer only).
   Relies on globals: RESULT_STRINGS (base.html), getCookie (calendar.js), escapeHtml (session.js). */

function _resInstanceId() {
  const el = document.getElementById('resultsBody');
  return el ? el.dataset.instance : null;
}

function _resHeaders() {
  return { 'Content-Type': 'application/json', 'X-CSRFToken': getCookie('csrftoken') };
}

function showResMsg(text, cls) {
  const el = document.getElementById('resMsg');
  if (!el) return;
  el.className = cls || 'text-muted';
  el.textContent = text || '';
}

/* Swimmers currently marked "present" in the attendance table (live DOM, so
   WebSocket updates are respected). */
function presentSwimmersFromDom() {
  const people = [];
  document.querySelectorAll('#attendanceTableBody tr[id^="att-row-"]').forEach(tr => {
    const active = tr.querySelector('.status-btn.active');
    if (!active || active.dataset.status !== 'present') return;
    const nameEl = tr.querySelector('.fw-medium');
    people.push({ id: tr.id.replace('att-row-', ''), name: nameEl ? nameEl.textContent.trim() : '' });
  });
  return people;
}

/* Start order is by performance, not by name list: rows can be dragged by their
   handle. The order is remembered per device and session (each trainer may time
   a different heat). */
function _resOrderKey() { return `lanekit_resOrder_${_resInstanceId()}`; }

function _loadResOrder() {
  try { return JSON.parse(localStorage.getItem(_resOrderKey())) || []; } catch (e) { return []; }
}

function _saveResOrder() {
  const ids = Array.from(document.querySelectorAll('#resEntryBody input[data-swimmer]')).map(i => i.dataset.swimmer);
  try { localStorage.setItem(_resOrderKey(), JSON.stringify(ids)); } catch (e) { /* storage full / private mode */ }
}

function buildResultEntryTable() {
  const body = document.getElementById('resEntryBody');
  if (!body) return;
  const keep = {};   // keep what was already typed when the table is rebuilt
  body.querySelectorAll('input[data-swimmer]').forEach(i => { if (i.value.trim()) keep[i.dataset.swimmer] = i.value; });
  const domOrder = Array.from(body.querySelectorAll('input[data-swimmer]')).map(i => i.dataset.swimmer);
  const order = domOrder.length ? domOrder : _loadResOrder();
  // Known swimmers keep their position, newcomers go to the end.
  const people = presentSwimmersFromDom().sort((a, b) => {
    const ia = order.indexOf(a.id), ib = order.indexOf(b.id);
    if (ia < 0 && ib < 0) return 0;
    if (ia < 0) return 1;
    if (ib < 0) return -1;
    return ia - ib;
  });
  if (!people.length) {
    body.innerHTML = `<tr><td class="text-muted small text-center py-2">${escapeHtml(RESULT_STRINGS.noPresent)}</td></tr>`;
    return;
  }
  body.innerHTML = people.map(p => `
    <tr>
      <td class="res-handle text-muted" style="width:24px;cursor:grab;touch-action:none"><i class="bi bi-grip-vertical"></i></td>
      <td class="small">${escapeHtml(p.name)} <span class="res-recorded small text-success text-nowrap"></span></td>
      <td style="width:8.5rem">
        <input type="text" inputmode="decimal" autocomplete="off" data-swimmer="${p.id}"
               placeholder="m:ss,hh" value="${escapeHtml(keep[p.id] || '')}"
               class="form-control form-control-sm bg-transparent border-secondary text-light"
               onkeydown="resEntryKey(event)">
      </td>
    </tr>`).join('');
  _saveResOrder();
  markRecordedInEntryTable();
}

function sortResultEntryByName() {
  const body = document.getElementById('resEntryBody');
  if (!body) return;
  Array.from(body.querySelectorAll('tr')).filter(tr => tr.querySelector('input[data-swimmer]'))
    .sort((a, b) => a.children[1].textContent.trim().localeCompare(b.children[1].textContent.trim(), LANG))
    .forEach(tr => body.appendChild(tr));
  _saveResOrder();
}

/* Show next to each swimmer whether a time for the selected stroke/distance already
   exists in the session – e.g. entered by another trainer – so nobody enters it twice. */
function markRecordedInEntryTable() {
  const strokeEl = document.getElementById('resStroke'), distEl = document.getElementById('resDistance');
  if (!strokeEl || !distEl) return;
  const stroke = strokeEl.value, dist = String(parseInt(distEl.value, 10));
  document.querySelectorAll('#resEntryBody tr').forEach(tr => {
    const input = tr.querySelector('input[data-swimmer]');
    const tag = tr.querySelector('.res-recorded');
    if (!input || !tag) return;
    const times = Array.from(document.querySelectorAll(
      `#resultsList tr[data-swimmer-id="${input.dataset.swimmer}"][data-stroke="${stroke}"][data-distance="${dist}"] .res-time`
    )).map(el => el.textContent.trim());
    tag.textContent = '';
    if (times.length) {
      const icon = document.createElement('i');
      icon.className = 'bi bi-check-circle-fill me-1';
      icon.title = RESULT_STRINGS.alreadyRecorded;
      tag.append(icon, times.join(' · '));
    }
  });
}

/* Enter jumps to the next swimmer's field – quick entry poolside. */
function resEntryKey(e) {
  if (e.key !== 'Enter') return;
  e.preventDefault();
  const inputs = Array.from(document.querySelectorAll('#resEntryBody input[data-swimmer]'));
  const next = inputs[inputs.indexOf(e.target) + 1];
  if (next) next.focus(); else e.target.blur();
}

function _renderResultsList(html) {
  const el = document.getElementById('resultsList');
  if (el && typeof html === 'string') el.innerHTML = html;
  markRecordedInEntryTable();
}

function saveResults() {
  const id = _resInstanceId();
  if (!id) return;
  const inputs = Array.from(document.querySelectorAll('#resEntryBody input[data-swimmer]'));
  inputs.forEach(i => i.classList.remove('is-invalid'));
  const entries = inputs.filter(i => i.value.trim())
    .map(i => ({ swimmer_id: parseInt(i.dataset.swimmer, 10), time: i.value.trim() }));
  if (!entries.length) { showResMsg(RESULT_STRINGS.needTime, 'text-warning'); return; }
  const distance = parseInt(document.getElementById('resDistance').value, 10);
  const stroke = document.getElementById('resStroke').value;
  const btn = document.getElementById('resSaveBtn');
  if (btn) btn.disabled = true;

  fetch(`/training/session/${id}/results/`, {
    method: 'POST', headers: _resHeaders(),
    body: JSON.stringify({ stroke, distance: Number.isNaN(distance) ? null : distance, entries }),
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      if (!ok) {
        Object.keys(d.errors || {}).forEach(sid => {
          const inp = document.querySelector(`#resEntryBody input[data-swimmer="${sid}"]`);
          if (inp) inp.classList.add('is-invalid');
        });
        showResMsg(d.error || RESULT_STRINGS.error, 'text-danger');
        return;
      }
      inputs.forEach(i => { i.value = ''; });
      _renderResultsList(d.html);
      showResMsg(RESULT_STRINGS.saved.replace('{n}', d.saved), 'text-success');
    })
    .catch(() => showResMsg(RESULT_STRINGS.error, 'text-danger'))
    .finally(() => { if (btn) btn.disabled = false; });
}

function _reloadResultsList() {
  const id = _resInstanceId();
  if (!id) return;
  if (document.querySelector('#resultsList input')) return;   // a time is being edited – don't wipe it
  fetch(`/training/session/${id}/results/`, { headers: { 'Accept': 'application/json' } })
    .then(r => r.json()).then(d => _renderResultsList(d.html)).catch(() => {});
}

function editResultTime(resultId) {
  const row = document.querySelector(`#resultsList tr[data-result-id="${resultId}"]`);
  if (!row) return;
  const span = row.querySelector('.res-time');
  const old = span.textContent.trim();
  const input = document.createElement('input');
  input.type = 'text'; input.value = old; input.inputMode = 'decimal';
  input.className = 'form-control form-control-sm d-inline-block bg-transparent border-secondary text-light';
  input.style.width = '6.5rem';
  span.replaceWith(input);
  input.focus(); input.select();
  let done = false;
  const finish = commit => {
    if (done) return;
    done = true;
    const value = input.value.trim();
    if (!commit || !value || value === old) { input.replaceWith(span); return; }
    fetch(`/training/result/${resultId}/update/`, {
      method: 'POST', headers: _resHeaders(), body: JSON.stringify({ time: value }),
    })
      .then(r => r.json().then(d => ({ ok: r.ok, d })))
      .then(({ ok, d }) => {
        if (ok) { span.textContent = d.time; showResMsg('', 'text-muted'); }
        else showResMsg(d.error || RESULT_STRINGS.error, 'text-danger');
        input.replaceWith(span);
      })
      .catch(() => { showResMsg(RESULT_STRINGS.error, 'text-danger'); input.replaceWith(span); });
  };
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter') finish(true); else if (e.key === 'Escape') finish(false);
  });
  input.addEventListener('blur', () => finish(true));
}

function deleteResult(resultId) {
  if (!confirm(RESULT_STRINGS.confirmDelete)) return;
  fetch(`/training/result/${resultId}/delete/`, { method: 'POST', headers: _resHeaders(), body: '{}' })
    .then(r => { if (r.ok) _reloadResultsList(); else showResMsg(RESULT_STRINGS.error, 'text-danger'); })
    .catch(() => showResMsg(RESULT_STRINGS.error, 'text-danger'));
}

/* Called by calendar.js after the modal HTML has been injected. */
function initResultsPanel() {
  const body = document.getElementById('resultsBody');
  if (!body) return;
  body.addEventListener('shown.bs.collapse', buildResultEntryTable);
  ['resStroke', 'resDistance'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.addEventListener('change', markRecordedInEntryTable); el.addEventListener('input', markRecordedInEntryTable); }
  });
  const tbody = document.getElementById('resEntryBody');
  if (tbody && typeof Sortable !== 'undefined') {
    tbody.dataset.sortableReady = '1';
    Sortable.create(tbody, { handle: '.res-handle', animation: 150, onEnd: _saveResOrder });
  }
}
window.initResultsPanel = initResultsPanel;
