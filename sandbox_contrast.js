/* Sandbox presentation only. No requests, storage, application data or timers. */
(() => {
  'use strict';
  if (document.documentElement.dataset.pqmEnvironment !== 'sandbox') return;
  const mark = 'data-pqm-light-ink';
  const darkMark = 'data-pqm-dark-ink';
  const excluded = new Set(['SCRIPT', 'STYLE', 'LINK', 'META', 'IMG', 'SVG', 'CANVAS', 'VIDEO', 'IFRAME']);
  const pending = new Set();
  let frame = 0;
  function rgba(value) {
    if (value === 'transparent') return [0, 0, 0, 0];
    const match = value.match(/^rgba?\(([^)]+)\)$/);
    if (!match) return null;
    const parts = match[1].split(/[, /]+/).filter(Boolean).map(Number);
    return parts.length === 3 ? [...parts, 1] : parts;
  }
  function background(style, parent) {
    // Images/gradients are not solid UI surfaces: leave their text unchanged.
    if (style.backgroundImage !== 'none') return null;
    const color = rgba(style.backgroundColor);
    if (!color || color.some(v => !Number.isFinite(v))) return null;
    if (color[3] === 1) return color.slice(0, 3);
    if (!parent) return null;
    return color.slice(0, 3).map((v, i) => v * color[3] + parent[i] * (1 - color[3]));
  }
  function light(color) {
    if (!color) return false;
    const rgb = color.map(v => {v /= 255; return v <= .04045 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4;});
    return rgb[0] * .2126 + rgb[1] * .7152 + rgb[2] * .0722 >= .45;
  }
  function scan(root) {
    if (!root.isConnected || root.nodeType !== 1) return;
    let ancestor = root.parentElement, base = [255, 255, 255];
    const ancestors = [];
    while (ancestor) {ancestors.unshift(ancestor); ancestor = ancestor.parentElement;}
    for (const node of ancestors) base = background(getComputedStyle(node), base);
    const changes = [];
    function visit(node, parent) {
      if (node.namespaceURI !== 'http://www.w3.org/1999/xhtml' || excluded.has(node.tagName)) return;
      const style = getComputedStyle(node);
      if (style.display === 'none') return; // Rescan when opened/unhidden.
      const surface = background(style, parent), desired = light(surface);
      const darkBoundary = light(parent) && surface !== null && !desired;
      if (node.hasAttribute(mark) !== desired) changes.push([node, mark, desired]);
      if (node.hasAttribute(darkMark) !== darkBoundary) changes.push([node, darkMark, darkBoundary]);
      for (const child of node.children) visit(child, surface);
    }
    visit(root, base);
    // Finish all style reads before writes; marker changes do not retrigger observer.
    for (const [node, attribute, desired] of changes) node.toggleAttribute(attribute, desired);
  }
  function queue(node) {
    if (!node || node.nodeType !== 1) return;
    pending.add(node);
    if (frame) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      const roots = [...pending]; pending.clear();
      for (const root of roots) if (!roots.some(other => other !== root && other.contains(root))) scan(root);
    });
  }
  function start() {
    queue(document.body);
    new MutationObserver(records => {
      for (const record of records) {
        if (record.type === 'attributes') queue(record.target);
        else for (const node of record.addedNodes) queue(node.nodeType === 1 ? node : node.parentElement);
      }
    }).observe(document.body, {subtree: true, childList: true, attributes: true,
      attributeFilter: ['class', 'style', 'hidden', 'open', 'disabled']});
    for (const event of ['pointerover', 'pointerout', 'focusin', 'focusout']) {
      document.addEventListener(event, e => queue(e.target), {passive: true});
    }
    window.addEventListener('resize', () => queue(document.body), {passive: true});
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start, {once: true});
  else start();
})();
