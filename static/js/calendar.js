/* calendar.js – FullCalendar init + session modal loader */

document.addEventListener('DOMContentLoaded', function () {
  const calendarEl = document.getElementById('calendar');
  const toggleBtn  = document.getElementById('mySessionsToggle');
  let mySessionsMode = false;

  // ── FullCalendar ──────────────────────────────────────────────────────────
  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'dayGridMonth',
    locale: LANG || 'de',
    firstDay: 1,
    headerToolbar: {
      left:   'prev,next today',
      center: 'title',
      right:  'dayGridMonth,timeGridWeek,timeGridDay,listWeek',
    },
    nowIndicator: true,
    editable: false,
    eventDisplay: 'block',
    dayMaxEvents: 4,
    height: 'auto',

    events: function (fetchInfo, successCallback, failureCallback) {
      const params = new URLSearchParams({
        start:       fetchInfo.startStr.slice(0, 10),
        end:         fetchInfo.endStr.slice(0, 10),
        my_sessions: mySessionsMode ? '1' : '0',
      });
      fetch(`${CALENDAR_EVENTS_URL}?${params}`)
        .then(r => r.json())
        .then(data => successCallback(data))
        .catch(() => failureCallback());
    },

    eventClick: function (info) {
      const props = info.event.extendedProps;
      if (props.type === 'exception') { showExceptionModal(props); return; }
      openSessionModal(props.session_id, props.date, props.instance_id);
    },

    eventDidMount: function (info) {
      const props = info.event.extendedProps;
      const label = props.type === 'exception'
        ? `❌ ${props.reason}`
        : `📍 ${props.location || ''}`;
      info.el.setAttribute('data-bs-toggle', 'tooltip');
      info.el.setAttribute('data-bs-title', label);
      new bootstrap.Tooltip(info.el, { placement: 'top', trigger: 'hover' });
    },
  });

  calendar.render();

  // ── My sessions toggle ────────────────────────────────────────────────────
  if (toggleBtn) {
    toggleBtn.addEventListener('click', () => {
      mySessionsMode = !mySessionsMode;
      toggleBtn.classList.toggle('active', mySessionsMode);
      calendar.refetchEvents();
    });
  }

  // ── Session modal ─────────────────────────────────────────────────────────
  window.openSessionModal = function (sessionId, sessionDate, instanceId) {
    const modal      = new bootstrap.Modal(document.getElementById('sessionModal'));
    const modalBody  = document.getElementById('sessionModalBody');
    const modalTitle = document.getElementById('sessionModalTitle');

    modalBody.innerHTML = `
      <div class="text-center py-5">
        <div class="spinner-border text-primary" role="status"></div>
        <p class="text-muted mt-2 small">Lade…</p>
      </div>`;
    modal.show();

    fetchModalContent(`/training/session/${sessionId}/${sessionDate}/`, 'GET', null,
      (data) => {
        applyModalData(data, modalBody, modalTitle, sessionDate);
      }
    );
  };

  window.createSessionInstance = function (sessionId, sessionDate) {
    const modalBody = document.getElementById('sessionModalBody');
    fetchModalContent(
      `/training/session/${sessionId}/${sessionDate}/`, 'POST', getCookie('csrftoken'),
      (data) => {
        applyModalData(data, modalBody, document.getElementById('sessionModalTitle'), sessionDate);
        calendar.refetchEvents();
      }
    );
  };

  // Shared fetch helper – the view now returns JSON {html, instance_id, is_trainer}
  // so we no longer depend on injected <script> tags (which innerHTML never executes).
  function fetchModalContent(url, method, csrfToken, onSuccess) {
    const headers = { 'X-Requested-With': 'XMLHttpRequest' };
    if (csrfToken) headers['X-CSRFToken'] = csrfToken;

    fetch(url, { method, headers })
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(data => onSuccess(data))
      .catch(err => {
        const modalBody = document.getElementById('sessionModalBody');
        if (modalBody) modalBody.innerHTML =
          `<div class="alert alert-danger m-3">Fehler beim Laden: ${err.message}</div>`;
      });
  }

  function applyModalData(data, modalBody, modalTitle, sessionDate) {
    // Inject translated HTML
    modalBody.innerHTML = data.html;

    // Set title
    if (modalTitle) modalTitle.textContent = 'Training – ' + formatDate(sessionDate);

    // Initialise WebSocket with the metadata returned by the view
    if (data.instance_id && data.is_trainer) {
      initSessionWebSocket(data.instance_id);
    }

    initSortable();
    updateAttendanceCounts();
  }

  // Clean up when modal closes
  document.getElementById('sessionModal').addEventListener('hidden.bs.modal', () => {
    if (window._sessionWS) {
      window._sessionWS.close();
      window._sessionWS = null;
    }
  });

  // ── Helpers ───────────────────────────────────────────────────────────────
  function formatDate(iso) {
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString(LANG || 'de', {
      weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
    });
  }

  function showExceptionModal(props) {
    const modalBody  = document.getElementById('sessionModalBody');
    const modalTitle = document.getElementById('sessionModalTitle');
    const modal      = new bootstrap.Modal(document.getElementById('sessionModal'));
    if (modalTitle) modalTitle.textContent = '❌ Abgesagt';
    modalBody.innerHTML = `
      <div class="text-center py-4">
        <i class="bi bi-calendar-x text-danger mb-3 d-block" style="font-size:3rem"></i>
        <h5 class="fw-bold">Training abgesagt</h5>
        <p class="text-muted">${props.reason}</p>
        <p class="small text-muted"><i class="bi bi-geo-alt me-1"></i>${props.location || ''}</p>
      </div>`;
    modal.show();
  }
});

// ── CSRF helper ───────────────────────────────────────────────────────────────
function getCookie(name) {
  const value = `; ${document.cookie}`;
  const parts = value.split(`; ${name}=`);
  if (parts.length === 2) return parts.pop().split(';').shift();
}