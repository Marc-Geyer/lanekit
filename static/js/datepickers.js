/* European date/time pickers (flatpickr). Fields without JS still work as plain text
   inputs in the same format (dd.mm.yyyy / HH:MM).
   - [data-datepicker]       text field, value dd.mm.yyyy (Django forms)
   - [data-datepicker="iso"] value stays yyyy-mm-dd for the server/JS, but dd.mm.yyyy is shown
   - [data-timepicker]       24 h time picker, value HH:MM                                 */
(function () {
  if (typeof flatpickr === 'undefined') return;
  const l10n = (flatpickr.l10ns && flatpickr.l10ns[typeof LANG !== 'undefined' ? LANG : 'de']) || flatpickr.l10ns.default;
  const locale = Object.assign({}, l10n, { firstDayOfWeek: 1 });

  function init(root) {
    (root || document).querySelectorAll('[data-datepicker]').forEach(el => {
      if (el._flatpickr) return;
      const iso = el.dataset.datepicker === 'iso';
      flatpickr(el, Object.assign({ locale, allowInput: true, disableMobile: true }, iso
        ? { dateFormat: 'Y-m-d', altInput: true, altFormat: 'd.m.Y', altInputClass: el.className }
        : { dateFormat: 'd.m.Y' }));
    });
    (root || document).querySelectorAll('[data-timepicker]').forEach(el => {
      if (el._flatpickr) return;
      flatpickr(el, { locale, enableTime: true, noCalendar: true, time_24hr: true,
                      dateFormat: 'H:i', allowInput: true, disableMobile: true, minuteIncrement: 5 });
    });
  }
  window.initDatepickers = init;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => init());
  else init();
})();
