/* calendar.js – FullCalendar init + session modal loader */

document.addEventListener('DOMContentLoaded', function () {
  const calendarEl = document.getElementById('calendar');
  const toggleBtn   = document.getElementById('mySessionsToggle');
  let mySessionsMode = false;

  // ── FullCalendar init ─────────────────────────────────────────────────────
  const calendar = new FullCalendar.Calendar(calendarEl, {
    initialView: 'dayGridMonth',
    locale: 'de',
    firstDay: 1, // Monday
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
        start: fetchInfo.startStr.slice(0, 10),
        end:   fetchInfo.endStr.slice(0, 10),
        my_sessions: mySessionsMode ? '1' : '0',
      });
      fetch(`${CALENDAR_EVENTS_URL}?${params}`)
        .then(r => r.json())
        .then(data => successCallback(data))
        .catch(() => failureCallback());
    },

    eventClick: function (info) {
      const props = info.event.extendedProps;
      if (props.type === 'exception') {
        showExceptionToast(props);
        return;
      }
      openSessionModal(props.session_id, props.date, props.instance_id);
    },

    eventDidMount: function (info) {
      const props = info.event.extendedProps;
      const label = props.type === 'exception'
        ? `❌ Abgesagt: ${props.reason}`
        : `📍 ${props.location || ''}`;

      // Bootstrap tooltip
      const el = info.el;
      el.setAttribute('data-bs-toggle', 'tooltip');
      el.setAttribute('data-bs-title', label);
      new bootstrap.Tooltip(el, { placement: 'top', trigger: 'hover' });
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
    const modal     = new bootstrap.Modal(document.getElementById('sessionModal'));
    const modalBody = document.getElementById('sessionModalBody');
    const modalTitle = document.getElementById('sessionModalTitle');

    // Loading spinner
    modalBody.innerHTML = `
      <div class="text-center py-5">
        <div class="spinner-border text-primary" role="status">
          <span class="visually-hidden">Lade…</span>
        </div>
        <p class="text-muted mt-2 small">Lade Einheit…</p>
      </div>`;
    modal.show();

    const url = `/training/session/${sessionId}/${sessionDate}/`;

    fetch(url, { method: 'GET', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(r => r.text())
      .then(html => {
        modalBody.innerHTML = html;
        modalTitle.textContent = 'Training – ' + formatDate(sessionDate);
        // Init WS if instance exists and user is trainer
        if (window.SESSION_INSTANCE_ID && window.SESSION_IS_TRAINER) {
          initSessionWebSocket(window.SESSION_INSTANCE_ID);
        }
        initSortable();
        updateAttendanceCounts();
      })
      .catch(() => {
        modalBody.innerHTML = `<div class="alert alert-danger">Fehler beim Laden.</div>`;
      });
  };

  window.createSessionInstance = function (sessionId, sessionDate) {
    const modalBody  = document.getElementById('sessionModalBody');
    const csrfToken  = getCookie('csrftoken');

    fetch(`/training/session/${sessionId}/${sessionDate}/`, {
      method: 'POST',
      headers: {
        'X-Requested-With': 'XMLHttpRequest',
        'X-CSRFToken': csrfToken,
      },
    })
      .then(r => r.text())
      .then(html => {
        modalBody.innerHTML = html;
        calendar.refetchEvents();
        if (window.SESSION_INSTANCE_ID && window.SESSION_IS_TRAINER) {
          initSessionWebSocket(window.SESSION_INSTANCE_ID);
        }
        initSortable();
      })
      .catch(() => {
        modalBody.innerHTML = `<div class="alert alert-danger">Fehler beim Erstellen.</div>`;
      });
  };

  // Clean up WS when modal closes
  document.getElementById('sessionModal').addEventListener('hidden.bs.modal', () => {
    if (window._sessionWS) {
      window._sessionWS.close();
      window._sessionWS = null;
    }
    // Reset inline state
    window.SESSION_INSTANCE_ID = null;
    window.SESSION_IS_TRAINER = false;
  });

  // ── Helper ────────────────────────────────────────────────────────────────
  function formatDate(iso) {
    const d = new Date(iso + 'T00:00:00');
    return d.toLocaleDateString('de-DE', { weekday:'short', day:'numeric', month:'short', year:'numeric' });
  }

  function showExceptionToast(props) {
    const container = document.getElementById('sessionModalBody');
    const modalBody = container;
    const modal = new bootstrap.Modal(document.getElementById('sessionModal'));
    document.getElementById('sessionModalTitle').textContent = '❌ Abgesagt';
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
