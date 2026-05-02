import { state } from './state.js';
import { icon, toast, escapeHTML, svgBars, svgActivityBars } from './utils.js';
import {
  loadJobs, loadDashboard, loadIdeas, loadOutputs, loadMusic,
  loadSettings, runSystemCheck
} from './api.js';

export function showPage(id) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + id).classList.add('active');
  document.querySelector(`[data-page="${id}"]`).classList.add('active');

  if (id === 'jobs')      loadJobs();
  if (id === 'dashboard') loadDashboard();
  if (id === 'ideas')   loadIdeas();
  if (id === 'outputs') loadOutputs();
  if (id === 'music')   loadMusic();
  if (id === 'settings') loadSettings();
  if (id === 'setup')   runSystemCheck();
}

export function updateWordCount() {
  const script = document.getElementById('vid-script').value;
  const words  = script.trim() ? script.trim().split(/\s+/).length : 0;
  const secs   = Math.round(words / 2.4);
  const m = Math.floor(secs / 60), s = secs % 60;

  document.getElementById('wc-display').textContent = `${words.toLocaleString()} words`;
  document.getElementById('dur-display').textContent = `~${m}m ${s}s`;

  const status = document.getElementById('dur-status');
  if (words >= 720 && words <= 2200) {
    status.innerHTML = icon('check') + ' Good length';
    status.className = 'ok';
  } else if (words < 720) {
    status.textContent = `Need ${720 - words} more words`;
    status.className = 'warn';
  } else {
    status.textContent = 'Over 15 min target';
    status.className = 'warn';
  }
}

export function showResult(res) {
  const card = document.getElementById('result-card');
  card.classList.add('show');

  const thumb = document.getElementById('result-thumb');
  if (res.thumbnail) {
    thumb.src = `/api/outputs/thumbnail/${res.thumbnail}`;
    thumb.style.display = 'block';
  } else {
    thumb.style.display = 'none';
  }

  document.getElementById('result-meta').innerHTML = `
    <div class="result-meta-item">Duration: <strong>${res.duration}</strong></div>
    <div class="result-meta-item">Size: <strong>${res.size_mb} MB</strong></div>
    <div class="result-meta-item">Format: <strong>1080p MP4</strong></div>
  `;

  document.getElementById('result-actions').innerHTML = `
    <a href="/api/outputs/download/${res.video}" class="btn btn-primary" download>
      <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:15px;height:15px"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"/></svg>
      Download Video
    </a>
    <a href="/api/outputs/thumbnail/${res.thumbnail}" class="btn btn-gold" download>
      <svg fill="none" stroke="currentColor" viewBox="0 0 24 24" style="width:15px;height:15px"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>
      Download Thumbnail
    </a>
  `;

  document.getElementById('result-desc').textContent = res.description || '';
  card.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

export function copyDesc() {
  const desc = document.getElementById('result-desc').textContent;
  navigator.clipboard.writeText(desc).then(() => toast('Description copied!', 'ok'));
}

export function setProgress(pct, stage) {
  document.getElementById('progress-fill').style.width = pct + '%';
  document.getElementById('progress-pct').textContent  = pct + '%';
  document.getElementById('stage-text').textContent    = stage || 'Processing...';
}

export function appendLog(line) {
  const box = document.getElementById('log-box');
  const div = document.createElement('div');
  let cls = '';
  if (line.includes('✅')) cls = 'log-ok';
  else if (line.includes('⚠️') || line.includes('ℹ️')) cls = 'log-warn';
  else if (line.includes('❌')) cls = 'log-error';
  else if (line.includes('%')) cls = 'log-info';
  div.className = cls;
  div.textContent = line;
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

export function clearLog() {
  document.getElementById('log-box').innerHTML = '';
  state.lastLogLength = 0;
}

export function animatePulse(on) {
  const pulse = document.getElementById('stage-pulse');
  if (on) {
    pulse.style.background = 'var(--red)';
    pulse.style.animation  = 'pulse 1.2s ease infinite';
  } else {
    pulse.style.background = 'var(--green-b)';
    pulse.style.animation  = 'none';
  }
}

export function resetGenBtn() {
  document.getElementById('gen-btn').disabled = false;
}

const VOICE_OPTIONS = [
  ['en-US-GuyNeural',     '[US] Guy (deep, authoritative)'],
  ['en-US-EricNeural',    '[US] Eric (warm, measured)'],
  ['en-US-DavisNeural',   '[US] Davis (gravelly, dramatic)'],
  ['en-GB-RyanNeural',    '[UK] Ryan (British, formal)'],
  ['en-GB-ThomasNeural',  '[UK] Thomas (British, historical)'],
  ['en-AU-WilliamNeural', '[AU] William (calm authority)'],
  ['en-US-AndrewNeural',  '[US] Andrew (clear, crisp)'],
];

export function renderVoicePool(selected) {
  const grid = document.getElementById('voice-pool');
  if (!grid) return;
  const sel = new Set(selected || []);
  grid.innerHTML = VOICE_OPTIONS.map(([id, label]) => `
    <label style="display:flex;align-items:center;gap:8px;font-size:12px;cursor:pointer;padding:5px 7px;border-radius:4px;background:#0d0d0d;border:1px solid #1a1a1a">
      <input type="checkbox" data-voice="${id}" ${sel.has(id) ? 'checked' : ''}
             style="width:16px;height:16px;accent-color:var(--gold)">
      <span>${label}</span>
    </label>
  `).join('');
}

export function collectVoicePool() {
  return Array.from(document.querySelectorAll('#voice-pool input[type="checkbox"]'))
    .filter(b => b.checked).map(b => b.dataset.voice);
}

export function renderReview(box, r) {
  const overall = r.overall || {};
  const scores  = r.scores  || {};
  const ovColor = overall.score >= 7 ? 'var(--gold)'
                : overall.score >= 5 ? 'var(--text)' : '#e6a23a';

  const dimRow = (label, key) => {
    const s = scores[key] || {};
    const sc = s.score || 0;
    const pct = (sc / 10) * 100;
    const color = sc >= 7 ? 'var(--gold)' : sc >= 5 ? '#9aa' : '#e6a23a';
    return `
      <div style="padding:8px 0;border-bottom:1px solid #1a1a1a">
        <div style="display:flex;justify-content:space-between;font-size:13px">
          <span style="font-weight:600">${label}</span>
          <span style="color:${color}">${sc}/10</span>
        </div>
        <div style="height:5px;background:#1a1a1a;border-radius:3px;margin-top:4px;overflow:hidden">
          <div style="height:100%;width:${pct}%;background:${color}"></div>
        </div>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">${escapeHTML(s.reason || '')}</div>
      </div>`;
  };

  const improvements = (r.actionable_improvements || []).map(s =>
    `<li style="margin-bottom:6px">${escapeHTML(s)}</li>`
  ).join('');

  box.innerHTML = `
    <div style="display:flex;align-items:baseline;gap:14px;margin-bottom:8px">
      <div style="font-size:38px;font-weight:700;color:${ovColor}">${overall.score || 0}<span style="font-size:18px;color:var(--text-dim)">/10</span></div>
      <div style="font-size:13px;color:var(--text)">${escapeHTML(overall.verdict || '')}</div>
    </div>
    ${!r.metrics_present ? `<div style="font-size:11px;color:var(--text-dim);margin-bottom:8px;display:flex;align-items:center;gap:6px">${icon('warning')} No YouTube metrics yet — review is from artifacts only.</div>` : ''}

    ${dimRow('Title',       'title')}
    ${dimRow('Thumbnail',   'thumbnail')}
    ${dimRow('Hook',        'hook')}
    ${dimRow('Structure',   'structure')}
    ${dimRow('Description', 'description')}
    ${dimRow('Tags',        'tags')}

    <div style="margin-top:14px">
      <div style="font-size:13px;font-weight:600;margin-bottom:6px">Actionable improvements</div>
      <ul style="font-size:12px;color:var(--text);padding-left:20px;line-height:1.5">${improvements || '<li style="color:var(--text-dim)">no suggestions</li>'}</ul>
    </div>

    <div style="font-size:10px;color:var(--text-dim);margin-top:14px">model: ${escapeHTML(r.model || '?')}</div>
  `;
}

export function stat(label, value) {
  return `
    <div class="card" style="padding:14px 16px;margin:0">
      <div style="font-size:11px;color:var(--text-dim);text-transform:uppercase;letter-spacing:0.04em">${label}</div>
      <div style="font-size:22px;color:var(--text);margin-top:4px;font-weight:600">${value}</div>
    </div>`;
}

export function toggleSchedLog() {
  const log = document.getElementById('sched-log');
  if (log.style.display === 'none' || !log.style.display) {
    log.style.display = 'block';
    log.textContent = (state._schedState?.log || []).join('\\n');
    log.scrollTop = log.scrollHeight;
  } else {
    log.style.display = 'none';
  }
}
