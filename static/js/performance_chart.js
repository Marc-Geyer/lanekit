/* Per-swimmer performance chart + table (swimmer detail page).
   Data: <script id="perfData"> (list of result dicts), strings: RESULT_STRINGS, library: Chart.js 4. */
(function () {
  const dataEl = document.getElementById('perfData');
  if (!dataEl) return;
  const ALL = JSON.parse(dataEl.textContent);
  const S = RESULT_STRINGS;
  const body = document.getElementById('perfBody');
  const empty = document.getElementById('perfEmpty');
  if (!ALL.length) { empty.style.display = ''; return; }
  if (typeof Chart === 'undefined') { empty.textContent = S.chartUnavailable; empty.style.display = ''; return; }
  body.style.display = '';

  const PALETTE = ['#38bdf8', '#f472b6', '#facc15', '#4ade80', '#a78bfa',
                   '#fb923c', '#2dd4bf', '#f87171', '#60a5fa', '#c084fc'];
  Chart.defaults.color = '#94a3b8';
  Chart.defaults.borderColor = '#334155';

  const pad = n => String(n).padStart(2, '0');
  const fmtDateMs = ms => { const d = new Date(ms); return `${pad(d.getUTCDate())}.${pad(d.getUTCMonth() + 1)}.${d.getUTCFullYear()}`; };
  const fmtDateIso = iso => iso.split('-').reverse().join('.');
  const fmtSeconds = sec => {
    const cs = Math.round(sec * 100), m = Math.floor(cs / 6000), s = Math.floor((cs % 6000) / 100), h = cs % 100;
    return m ? `${m}:${pad(s)},${pad(h)}` : `${s},${pad(h)}`;
  };
  const strokeLabel = k => S.strokes[k] || k;
  const poolKey = p => (p == null ? 'none' : String(p));
  // Lines are split by pool length by default (25 m and 50 m times are not directly
  // comparable); the toggle merges them for those who want one line per discipline.
  const seriesKey = r => `${r.stroke}|${r.distance}` + (state.splitPools ? `|${poolKey(r.pool)}` : '');
  const seriesLabel = r => `${strokeLabel(r.stroke)} ${r.distance} m` + (state.splitPools && r.pool ? ` (${r.pool} m)` : '');

  // Stable colour per series, independent of the active filters.
  let allKeys = [];
  const refreshKeys = () => { allKeys = Array.from(new Set(ALL.map(seriesKey))).sort(); };
  const colorOf = key => PALETTE[allKeys.indexOf(key) % PALETTE.length];

  const uniq = (arr, sortFn) => Array.from(new Set(arr)).sort(sortFn);
  const strokeOrder = ['free', 'back', 'breast', 'fly', 'medley'];
  const state = {
    strokes:   new Set(ALL.map(r => r.stroke)),
    distances: new Set(ALL.map(r => String(r.distance))),
    pools:     new Set(ALL.map(r => poolKey(r.pool))),
    official: true, unofficial: true, from: '', to: '', mode: 'time', splitPools: true,
  };
  refreshKeys();
  const hiddenSeries = new Set();   // series switched off via the legend

  function chips(containerId, values, labelFn, set) {
    const box = document.getElementById(containerId);
    box.innerHTML = '';
    values.forEach((v, i) => {
      const id = `${containerId}-${i}`;
      const input = Object.assign(document.createElement('input'),
        { type: 'checkbox', className: 'btn-check', id, checked: set.has(String(v)) });
      input.autocomplete = 'off';
      const label = Object.assign(document.createElement('label'),
        { className: 'btn btn-outline-primary btn-sm rounded-pill py-0 px-2', htmlFor: id, textContent: labelFn(v) });
      input.addEventListener('change', () => {
        if (input.checked) set.add(String(v)); else set.delete(String(v));
        render();
      });
      box.append(input, label);
    });
  }

  chips('perfStrokes', uniq(ALL.map(r => r.stroke), (a, b) => strokeOrder.indexOf(a) - strokeOrder.indexOf(b)), strokeLabel, state.strokes);
  chips('perfDistances', uniq(ALL.map(r => r.distance), (a, b) => a - b), v => `${v} m`, state.distances);
  const poolValues = uniq(ALL.map(r => poolKey(r.pool)), (a, b) => (a === 'none') - (b === 'none') || a - b);
  chips('perfPools', poolValues, v => (v === 'none' ? '–' : `${v} m`), state.pools);
  document.getElementById('perfPoolsWrap').style.display = poolValues.length > 1 ? '' : 'none';

  const bind = (id, key, isCheckbox) => document.getElementById(id).addEventListener('change', e => {
    state[key] = isCheckbox ? e.target.checked : e.target.value; render();
  });
  document.getElementById('perfSplitPools').addEventListener('change', e => {
    state.splitPools = e.target.checked;
    hiddenSeries.clear();                       // series keys change meaning
    refreshKeys();
    document.getElementById('perfMergeHint').style.display = state.splitPools ? 'none' : '';
    render();
  });
  bind('perfOfficial', 'official', true);
  bind('perfUnofficial', 'unofficial', true);
  bind('perfFrom', 'from'); bind('perfTo', 'to'); bind('perfMode', 'mode');

  function filtered() {
    return ALL.filter(r =>
      state.strokes.has(r.stroke) && state.distances.has(String(r.distance)) && state.pools.has(poolKey(r.pool)) &&
      (r.official ? state.official : state.unofficial) &&
      (!state.from || r.date >= state.from) && (!state.to || r.date <= state.to));
  }

  const value = r => (state.mode === 'pace' ? (r.time_cs / 100) / r.distance * 100 : r.time_cs / 100);

  let chart = null;
  function buildDatasets(rows) {
    const bySeries = new Map();
    rows.forEach(r => { const k = seriesKey(r); if (!bySeries.has(k)) bySeries.set(k, []); bySeries.get(k).push(r); });
    return Array.from(bySeries.entries()).sort(([a], [b]) => a.localeCompare(b)).map(([key, list]) => {
      list.sort((a, b) => a.date.localeCompare(b.date) || a.id - b.id);
      return {
        key, label: seriesLabel(list[0]), borderColor: colorOf(key), backgroundColor: colorOf(key),
        borderWidth: 2, tension: 0, spanGaps: true, hidden: hiddenSeries.has(key),
        pointRadius: 4, pointHoverRadius: 6,
        pointStyle: list.map(r => (r.official ? 'triangle' : 'circle')),
        data: list.map(r => ({ x: Date.parse(r.date), y: value(r), r })),
      };
    });
  }

  function renderChart(rows) {
    const datasets = buildDatasets(rows);
    if (chart) chart.destroy();
    chart = new Chart(document.getElementById('perfChart'), {
      type: 'line',
      data: { datasets },
      options: {
        responsive: true, maintainAspectRatio: false, parsing: false,
        interaction: { mode: 'nearest', intersect: true },
        scales: {
          x: { type: 'linear', grace: '2%', ticks: { maxTicksLimit: 7, callback: v => fmtDateMs(v) } },
          y: { grace: '8%', title: { display: true, text: state.mode === 'pace' ? S.yPace : S.yTime },
               ticks: { callback: v => fmtSeconds(v) } },
        },
        plugins: {
          legend: {
            onClick(e, item, legend) {        // default toggle + remember the choice across re-renders
              Chart.defaults.plugins.legend.onClick.call(this, e, item, legend);
              const ds = legend.chart.data.datasets[item.datasetIndex];
              if (legend.chart.isDatasetVisible(item.datasetIndex)) hiddenSeries.delete(ds.key);
              else hiddenSeries.add(ds.key);
            },
          },
          tooltip: {
            callbacks: {
              title: items => fmtDateMs(items[0].parsed.x),
              label: ctx => {
                const r = ctx.raw.r;
                const lines = [`${ctx.dataset.label}: ${r.time}`];
                if (state.mode === 'pace') lines.push(`${S.yPace}: ${fmtSeconds(ctx.parsed.y)}`);
                if (r.location) lines.push(r.location);
                lines.push(r.official ? S.official : S.unofficial);
                return lines;
              },
            },
          },
        },
      },
    });
  }

  function renderTable(rows) {
    const best = new Map();
    rows.forEach(r => { const k = seriesKey(r); if (!best.has(k) || r.time_cs < best.get(k)) best.set(k, r.time_cs); });
    const sorted = rows.slice().sort((a, b) => b.date.localeCompare(a.date) || b.id - a.id);
    const tbody = document.getElementById('perfTableBody');
    tbody.innerHTML = sorted.map(r => `
      <tr>
        <td class="text-nowrap">${fmtDateIso(r.date)}</td>
        <td>${escapeHtml(seriesLabel(r))}</td>
        <td class="text-nowrap fw-semibold">${escapeHtml(r.time)}${r.time_cs === best.get(seriesKey(r)) ? ` <i class="bi bi-trophy-fill text-warning" title="${escapeHtml(S.best)}"></i>` : ''}</td>
        <td class="text-muted small">${escapeHtml(r.location)}</td>
        <td>${r.official ? '' : `<span class="badge bg-secondary">${escapeHtml(S.unofficial)}</span>`}</td>
      </tr>`).join('');
  }

  function render() {
    const rows = filtered();
    document.getElementById('perfNoMatch').style.display = rows.length ? 'none' : '';
    document.getElementById('perfChartWrap').style.display = rows.length ? '' : 'none';
    document.getElementById('perfTableWrap').style.display = rows.length ? '' : 'none';
    if (!rows.length) { if (chart) { chart.destroy(); chart = null; } return; }
    renderChart(rows);
    renderTable(rows);
  }

  function escapeHtml(str) {
    return String(str ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  render();
})();
