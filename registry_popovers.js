(() => {
  const selector = '.multi-filter,.advanced-filters,.toolbar-settings';
  const panelSelector = ':scope > .multi-panel,:scope > .advanced-filter-panel,:scope > .edr-monitoring-filter-grid';

  function panelFor(details) {
    if (details.matches('.toolbar-settings')) return details.querySelector(':scope > .toolbar-settings-panel');
    return details.querySelector(panelSelector);
  }

  function showInTopLayer(panel, bringToFront = false) {
    if (typeof panel.showPopover !== 'function') return false;
    panel.setAttribute('popover', 'manual');
    try {
      if (bringToFront && panel.matches(':popover-open')) panel.hidePopover();
      if (!panel.matches(':popover-open')) panel.showPopover();
      return panel.matches(':popover-open');
    } catch {
      panel.removeAttribute('popover');
      return false;
    }
  }

  function positionPanel(details, bringToFront = false) {
    const panel = panelFor(details);
    const summary = details.querySelector(':scope > summary');
    if (!panel || !summary) return;

    const anchor = summary.getBoundingClientRect();
    showInTopLayer(panel, bringToFront);
    details.classList.add('popover-fixed');
    if (panel.classList.contains('multi-panel')) panel.style.setProperty('--registry-popover-min-width', `${anchor.width}px`);
    panel.style.setProperty('--registry-popover-top', '0px');
    panel.style.setProperty('--registry-popover-left', '0px');

    const size = panel.getBoundingClientRect();
    const margin = 8;
    const viewportWidth = document.documentElement.clientWidth || innerWidth;
    const viewportHeight = document.documentElement.clientHeight || innerHeight;
    let preferredLeft = details.matches('.toolbar-settings') ? anchor.right - size.width : anchor.left;
    if (details.matches('.toolbar-settings') && preferredLeft < margin) preferredLeft = anchor.left;
    const left = Math.max(margin, Math.min(preferredLeft, viewportWidth - size.width - margin));
    const below = viewportHeight - anchor.bottom - margin - 4;
    const above = anchor.top - margin - 4;
    const top = size.height <= below || below >= above
      ? Math.min(anchor.bottom + 4, viewportHeight - size.height - margin)
      : Math.max(margin, Math.min(anchor.top - size.height - 4, viewportHeight - size.height - margin));
    const layoutZoom = Number.parseFloat(getComputedStyle(document.documentElement).zoom) || 1;

    panel.style.setProperty('--registry-popover-top', `${top / layoutZoom}px`);
    panel.style.setProperty('--registry-popover-left', `${left / layoutZoom}px`);
  }

  function resetPanel(details) {
    const panel = panelFor(details);
    const restoreFocus = Boolean(panel?.contains(document.activeElement));
    if (panel?.matches(':popover-open')) panel.hidePopover();
    details.classList.remove('popover-fixed');
    panel?.style.removeProperty('--registry-popover-top');
    panel?.style.removeProperty('--registry-popover-left');
    panel?.style.removeProperty('--registry-popover-min-width');
    if (restoreFocus) requestAnimationFrame(() => details.querySelector(':scope > summary')?.focus());
  }

  function syncOpenPanels() {
    document.querySelectorAll(`${selector}[open]`).forEach(positionPanel);
  }

  document.addEventListener('toggle', event => {
    const details = event.target;
    if (!(details instanceof HTMLDetailsElement) || !details.matches(selector)) {
      const panel = event.target;
      const owner = panel instanceof HTMLElement && panel.matches('.multi-panel,.advanced-filter-panel,.edr-monitoring-filter-grid,.toolbar-settings-panel')
        ? panel.parentElement?.closest(selector) : null;
      if (owner?.open && !panel.matches(':popover-open')) {
        owner.open = false;
        requestAnimationFrame(() => owner.querySelector(':scope > summary')?.focus());
      }
      return;
    }
    if (details.open) positionPanel(details, true);
    else resetPanel(details);
  }, true);

  document.addEventListener('scroll', syncOpenPanels, true);
  window.addEventListener('resize', syncOpenPanels);
  window.visualViewport?.addEventListener('resize', syncOpenPanels);
  window.visualViewport?.addEventListener('scroll', syncOpenPanels);
  // The application already owns pointerdown dismissal. Handle keyboard and
  // programmatic clicks here so navigation cannot leave a hidden panel open.
  document.addEventListener('click', event => {
    const settingsAction = event.target instanceof Element ? event.target.closest('.toolbar-settings-panel button') : null;
    if (settingsAction) {
      const owner = settingsAction.closest('.toolbar-settings[open]');
      if (owner) owner.open = false;
    }
    if (event.detail !== 0) return;
    document.querySelectorAll(`${selector}[open]`).forEach(details => {
      if (!details.contains(event.target)) details.open = false;
    });
  });
  document.addEventListener('change', event => {
    const details = event.target.closest('.multi-filter.popover-fixed[open]');
    if (details && event.target.matches('input[type="checkbox"],input[type="radio"]')) details.open = false;
  }, true);
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    const details = [...document.querySelectorAll(`${selector}[open]`)].find(item => panelFor(item)?.contains(document.activeElement));
    if (!details) return;
    event.preventDefault();
    details.open = false;
    requestAnimationFrame(() => details.querySelector(':scope > summary')?.focus());
  }, true);
})();
