/* ════════════════════════════════════════════════════════
   ICON HELPERS (replaces emojis with inline SVG)
════════════════════════════════════════════════════════ */
export const ICON_PATHS = {
  check:    '<path d="M5 13l4 4L19 7"/>',
  x:        '<path d="M6 18L18 6M6 6l12 12"/>',
  'check-circle': '<path d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"/>',
  'x-circle':     '<path d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z"/>',
  warning:  '<path d="M12 9v2m0 4h.01M5.07 19h13.86c1.54 0 2.5-1.67 1.73-3L13.73 4c-.77-1.33-2.69-1.33-3.46 0L3.34 16c-.77 1.33.19 3 1.73 3z"/>',
  film:     '<path d="M7 4v16M17 4v16M3 8h4m10 0h4M3 12h18M3 16h4m10 0h4M4 4h16a1 1 0 011 1v14a1 1 0 01-1 1H4a1 1 0 01-1-1V5a1 1 0 011-1z"/>',
  trash:    '<path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>',
  music:    '<path d="M9 19V6l12-3v13M9 19c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zm12-3c0 1.105-1.343 2-3 2s-3-.895-3-2 1.343-2 3-2 3 .895 3 2zM9 10l12-3"/>',
  palette:  '<path d="M7 21a4 4 0 01-4-4V5a2 2 0 012-2h4a2 2 0 012 2v12a4 4 0 01-4 4zm0 0h12a2 2 0 002-2v-4a2 2 0 00-2-2h-2.343M11 7.343l1.657-1.657a2 2 0 012.828 0l2.829 2.829a2 2 0 010 2.828l-8.486 8.485M7 17h.01"/>',
  image:    '<path d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/>',
  chart:    '<path d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z"/>',
  search:   '<circle cx="11" cy="11" r="7"/><path d="M21 21l-4.35-4.35"/>',
  broom:    '<path d="M9.31 4.69l9.99 9.99M9.5 4.5l-3 3 9 9 3-3-9-9zM5.5 11.5l-2 2 5 5 2-2M3 21h7"/>',
  bolt:     '<path d="M13 10V3L4 14h7v7l9-11h-7z"/>',
  phone:    '<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M11 18h2"/>',
  mic:      '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M19 11a7 7 0 11-14 0M12 18v3M8 21h8"/>',
  cog:      '<path d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><circle cx="12" cy="12" r="3"/>',
  doc:      '<path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>',
  folder:   '<path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>',
  disk:     '<path d="M8 7H5a2 2 0 00-2 2v9a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-3m-1 4l-3 3m0 0l-3-3m3 3V4"/>',
  wheat:    '<path d="M12 22V8M12 8c0-3 2-5 4-5M12 8c0-3-2-5-4-5M12 14c0-2 2-4 4-4M12 14c0-2-2-4-4-4M12 19c0-2 2-3 4-3M12 19c0-2-2-3-4-3"/>',
  sparkle:  '<path d="M12 2v4M2 12h4M22 12h-4M12 22v-4M5.6 5.6l2.8 2.8M18.4 5.6l-2.8 2.8M5.6 18.4l2.8-2.8M18.4 18.4l-2.8-2.8"/>',
  download: '<path d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M7 10l5 5 5-5M12 15V3"/>',
  upload:   '<path d="M7 16a4 4 0 01-.88-7.903A5 5 0 0115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>',
  refresh:  '<path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/>',
  globe:    '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 010 18M12 3a14 14 0 000 18"/>',
};

export function icon(name, size) {
  const path = ICON_PATHS[name];
  if (!path) return '';
  const s = size ? `style="width:${size}px;height:${size}px"` : '';
  return `<svg class="icon icon-sm" ${s} viewBox="0 0 24 24" aria-hidden="true">${path}</svg>`;
}

/* ════════════════════════════════════════════════════════
   TOAST
════════════════════════════════════════════════════════ */
export function toast(msg, type = 'info', duration = 3500) {
  const c = document.getElementById('toast-container');
  if (!c) return;
  const t = document.createElement('div');
  t.className = `toast ${type}`;
  t.textContent = msg;
  c.appendChild(t);
  setTimeout(() => t.remove(), duration);
}

export function escapeHTML(s) {
  return String(s).replace(/[&<>"']/g, c => (
    {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
  ));
}

export function svgBars(items, opts = {}) {
  if (!items.length) return '<div style="color:var(--text-dim);font-size:12px">no data</div>';
  const max = Math.max(1, ...items.map(i => +i.value || 0));
  const fmt = opts.fmt || (n => n.toLocaleString());
  return items.map(i => {
    const pct = ((+i.value || 0) / max) * 100;
    const c   = i.color || 'var(--gold)';
    return `
      <div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:11px">
        <div style="flex:0 0 38%;color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${escapeHTML(i.label)}</div>
        <div style="flex:1;height:14px;background:#1a1a1a;border-radius:3px;position:relative;overflow:hidden">
          <div style="position:absolute;top:0;left:0;height:100%;width:${pct}%;background:${c}"></div>
        </div>
        <div style="flex:0 0 80px;text-align:right;color:var(--text-dim)">${fmt(+i.value || 0)}</div>
      </div>`;
  }).join('');
}

export function svgActivityBars(daily) {
  if (!daily || !daily.length) return '<div style="color:var(--text-dim);font-size:12px">no jobs in window</div>';
  const max = Math.max(1, ...daily.map(d => (d.done || 0) + (d.error || 0)));
  const W = 300, H = 70, n = daily.length;
  const colW = (W - 4) / n - 2;
  let bars = '';
  daily.forEach((d, i) => {
    const total  = (d.done || 0) + (d.error || 0);
    const x      = 2 + i * (colW + 2);
    const h      = (total / max) * (H - 12);
    const doneH  = ((d.done || 0) / max) * (H - 12);
    const errorH = h - doneH;
    bars += `<rect x="${x}" y="${H - h}" width="${colW}" height="${doneH}" fill="rgba(206,170,98,0.85)"/>`;
    if (errorH > 0)
      bars += `<rect x="${x}" y="${H - h + doneH}" width="${colW}" height="${errorH}" fill="#e6a23a"/>`;
    bars += `<title>${d.date}: ${d.done || 0} done, ${d.error || 0} errors</title>`;
  });
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:70px;display:block">${bars}</svg>
    <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text-dim);margin-top:2px">
      <span>${daily[0].date}</span><span>${daily[daily.length-1].date}</span>
    </div>`;
}

export function copyCode(btn) {
  const block = btn.parentElement;
  const text  = block.innerText.replace('Copy\n', '').trim();
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy', 1800);
  });
}

export function closeModal(id) {
  document.getElementById(id).classList.remove('open');
}

export function copyModalDesc() {
  const text = document.getElementById('modal-desc').value;
  navigator.clipboard.writeText(text).then(() => toast('Copied!', 'ok'));
}
