(() => {
  const selector = '.multi-filter,.advanced-filters';

  function positionPanel(details) {
    const panel = details.querySelector(':scope > .multi-panel,:scope > .advanced-filter-panel,:scope > .edr-monitoring-filter-grid');
    const summary = details.querySelector(':scope > summary');
    if (!panel || !summary) return;

    const anchor = summary.getBoundingClientRect();
    details.classList.add('popover-fixed');
    if (panel.classList.contains('multi-panel')) panel.style.setProperty('--registry-popover-min-width', `${anchor.width}px`);
    panel.style.setProperty('--registry-popover-top', '0px');
    panel.style.setProperty('--registry-popover-left', '0px');

    const size = panel.getBoundingClientRect();
    const margin = 8;
    const left = Math.max(margin, Math.min(anchor.left, innerWidth - size.width - margin));
    const below = innerHeight - anchor.bottom - margin - 4;
    const above = anchor.top - margin - 4;
    const top = size.height <= below || below >= above
      ? Math.min(anchor.bottom + 4, innerHeight - size.height - margin)
      : Math.max(margin, anchor.top - size.height - 4);

    panel.style.setProperty('--registry-popover-top', `${top}px`);
    panel.style.setProperty('--registry-popover-left', `${left}px`);
  }

  function syncOpenPanels() {
    document.querySelectorAll(`${selector}[open]`).forEach(positionPanel);
  }

  document.addEventListener('toggle', event => {
    const details = event.target;
    if (!(details instanceof HTMLDetailsElement) || !details.matches(selector)) return;
    if (details.open) positionPanel(details);
    else {
      details.classList.remove('popover-fixed');
      const panel = details.querySelector(':scope > .multi-panel,:scope > .advanced-filter-panel,:scope > .edr-monitoring-filter-grid');
      panel?.style.removeProperty('--registry-popover-top');
      panel?.style.removeProperty('--registry-popover-left');
      panel?.style.removeProperty('--registry-popover-min-width');
    }
  }, true);

  document.addEventListener('scroll', syncOpenPanels, true);
  window.addEventListener('resize', syncOpenPanels);
  // The application already owns pointerdown dismissal. Handle keyboard and
  // programmatic clicks here so navigation cannot leave a hidden panel open.
  document.addEventListener('click', event => {
    if (event.detail !== 0) return;
    document.querySelectorAll(`${selector}[open]`).forEach(details => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
  document.addEventListener('change', event => {
    const details = event.target.closest('.multi-filter.popover-fixed[open]');
    if (details && event.target.matches('input[type="checkbox"],input[type="radio"]')) details.open = false;
  }, true);
})();
