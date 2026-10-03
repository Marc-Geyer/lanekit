// Light input masks for European date/time text inputs (data-eu-input).
// Digits typed are auto-separated: 31122026 -> 31.12.2026, 1830 -> 18:30.
(function () {
  function mask(kind, raw) {
    const d = raw.replace(/\D/g, '');
    const date = d.slice(0, 8).replace(/^(\d{2})(\d)/, '$1.$2').replace(/^(\d{2}\.\d{2})(\d)/, '$1.$2');
    const time = d.slice(0, 4).replace(/^(\d{2})(\d)/, '$1:$2');
    if (kind === 'date') return date;
    if (kind === 'time') return time;
    const dd = d.slice(0, 12);
    const dpart = dd.slice(0, 8).replace(/^(\d{2})(\d)/, '$1.$2').replace(/^(\d{2}\.\d{2})(\d)/, '$1.$2');
    const tpart = dd.slice(8).replace(/^(\d{2})(\d)/, '$1:$2');
    return tpart ? dpart + ' ' + tpart : dpart;
  }
  document.addEventListener('input', function (e) {
    const el = e.target;
    const kind = el.dataset && el.dataset.euInput;
    if (!kind || (e.inputType && e.inputType.startsWith('delete'))) return;
    // Only mask pure-digit typing; leave already formatted / pasted text alone.
    if (/[^\d.: ]/.test(el.value)) return;
    el.value = mask(kind, el.value);
  });
})();
