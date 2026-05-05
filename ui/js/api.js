import { state } from './state.js';
import { icon, toast, escapeHTML, svgBars, svgActivityBars } from './utils.js';
import {
  showPage, updateWordCount, showResult, copyDesc, setProgress, appendLog, clearLog,
  animatePulse, resetGenBtn, renderVoicePool, collectVoicePool, renderReview,
  stat
} from './ui.js';

export async function runSystemCheck() {
  const grid = document.getElementById('sys-check-grid');
  grid.innerHTML = '<div style="color:var(--text-dim);font-size:13px">Checking...</div>';
  try {
    const r   = await fetch('/api/system-check');
    const d   = await r.json();
    const pkg = d.packages;

    const items = [
      { label: 'Python',       sub: d.python.version || '—',   ok: d.python.ok },
      { label: 'FFmpeg',       sub: d.ffmpeg.version || 'Not found', ok: d.ffmpeg.ok },
      { label: 'edge-tts',     sub: 'Python package',           ok: pkg.edge_tts },
      { label: 'moviepy',      sub: 'Python package',           ok: pkg.moviepy },
      { label: 'Pillow',       sub: 'Python package',           ok: pkg.PIL },
      { label: 'requests',     sub: 'Python package',           ok: pkg.requests },
      { label: 'Pexels API',   sub: d.pexels_key_set ? 'Key saved' : 'Key not set',
        ok: d.pexels_key_set },
      { label: 'Music Files',  sub: `${d.music_count} track(s)`, ok: d.music_count > 0 },
    ];

    grid.innerHTML = items.map(i => `
      <div class="check-item">
        <div>
          <div class="check-item-label">${i.label}</div>
          <div class="check-item-sub">${i.sub}</div>
        </div>
        <div class="badge ${i.ok ? 'badge-ok' : 'badge-error'}">
          ${i.ok ? icon('check') + ' OK' : icon('x') + ' Missing'}
        </div>
      </div>
    `).join('');
  } catch(e) {
    grid.innerHTML = '<div class="badge badge-error">Cannot connect to server</div>';
  }
}

export async function installPackages() {
  toast('Installing packages... this may take a minute.', 'info', 8000);
  const r = await fetch('/api/install', { method: 'POST' });
  const d = await r.json();
  if (d.ok) {
    toast('Packages installed successfully!', 'ok');
    runSystemCheck();
  } else {
    toast('Install failed — check terminal output.', 'error', 5000);
  }
}

// ── SSE / polling monitor ────────────────────────────────

function _stopJobMonitor() {
  if (state.eventSource) {
    state.eventSource.close();
    state.eventSource = null;
  }
  if (state.pollInterval) {
    clearInterval(state.pollInterval);
    state.pollInterval = null;
  }
}

function _onJobDone(result) {
  _stopJobMonitor();
  animatePulse(false);
  resetGenBtn();
  state.currentResult = result;
  showResult(result);
  toast('Video generated successfully.', 'ok', 5000);
}

function _onJobError(errorMsg) {
  _stopJobMonitor();
  animatePulse(false);
  resetGenBtn();
  toast('Pipeline error: ' + (errorMsg || 'Unknown error'), 'error', 8000);
  appendLog('[ERR] ' + (errorMsg || 'Unknown error'));
}

function _connectSSE(jobId) {
  if (!window.EventSource) {
    // Browser doesn't support SSE — fall back to polling
    state.pollInterval = setInterval(pollStatus, 2000);
    return;
  }
  const es = new EventSource(`/api/events/${jobId}`);
  state.eventSource = es;

  es.onmessage = e => {
    try {
      const msg = JSON.parse(e.data);
      if (msg.type === 'progress') {
        setProgress(msg.pct, msg.stage);
      } else if (msg.type === 'log') {
        appendLog(msg.line);
      } else if (msg.type === 'done') {
        _onJobDone(msg.result);
      } else if (msg.type === 'error') {
        _onJobError(msg.error);
      }
      // 'ping' intentionally ignored
    } catch (err) {
      console.error('[SSE parse]', err);
    }
  };

  es.onerror = () => {
    // SSE failed — close and fall back to polling if job isn't done yet
    es.close();
    state.eventSource = null;
    if (state.currentJobId && !state.pollInterval) {
      state.pollInterval = setInterval(pollStatus, 2000);
    }
  };
}

export async function startGeneration() {
  const title  = document.getElementById('vid-title').value.trim();
  const script = document.getElementById('vid-script').value.trim();

  if (!title) { toast('Please enter a video title.', 'error'); return; }
  if (script.length < 100) { toast('Script is too short (minimum 100 characters).', 'error'); return; }

  document.getElementById('gen-btn').disabled = true;
  document.getElementById('result-card').classList.remove('show');
  setProgress(0, 'Queuing job...');
  clearLog();
  animatePulse(true);

  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ title, script })
    });
    const d = await r.json();
    if (!r.ok) {
      toast(d.error || 'Failed to start pipeline.', 'error');
      resetGenBtn();
      return;
    }
    state.currentJobId = d.job_id;
    state.lastLogLength = 0;
    if (d.queue_pos > 0) {
      toast(`Queued at position ${d.queue_pos + 1} — will start when current job finishes.`, 'info', 5000);
      setProgress(0, `Queued (position ${d.queue_pos + 1})`);
    }
    _stopJobMonitor();
    _connectSSE(d.job_id);
  } catch(e) {
    toast('Cannot reach server. Is server.py running?', 'error');
    resetGenBtn();
  }
}

export async function generateShort() {
  const idea = document.getElementById('short-idea').value.trim();
  const words = parseInt(document.getElementById('short-words').value || '110');
  if (idea.length < 8) { toast('Enter a topic first.', 'error'); return; }

  const btn = document.getElementById('short-gen-btn');
  const stat = document.getElementById('short-status');
  btn.disabled = true; btn.textContent = 'Working...';
  stat.textContent = 'Starting Shorts pipeline...';

  let r, d;
  try {
    r = await fetch('/api/run-short', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ idea, target_words: words }),
    });
    d = await r.json();
  } catch (e) {
    toast('Network error.', 'error');
    btn.disabled = false; btn.textContent = 'Generate Short'; return;
  }
  if (!r.ok) {
    toast(d.error || 'Failed.', 'error');
    btn.disabled = false; btn.textContent = 'Generate Short'; return;
  }

  state.currentJobId = d.job_id;
  state.lastLogLength = 0;
  document.getElementById('result-card').classList.remove('open');
  document.getElementById('progress-card').classList.add('active');
  if (d.queue_pos > 0) {
    stat.textContent = `Queued at position ${d.queue_pos + 1}`;
  } else {
    stat.textContent = '';
  }
  btn.disabled = false; btn.textContent = 'Generate Short';
  _stopJobMonitor();
  _connectSSE(d.job_id);
}

export async function pollStatus() {
  // Fallback for browsers without EventSource support
  if (!state.currentJobId) return;
  try {
    const r = await fetch(`/api/status/${state.currentJobId}`);
    const d = await r.json();

    setProgress(d.progress, d.stage);

    if (d.log && d.log.length > state.lastLogLength) {
      const newLines = d.log.slice(state.lastLogLength);
      newLines.forEach(line => appendLog(line));
      state.lastLogLength = d.log.length;
    }

    if (d.status === 'done') {
      _onJobDone(d.result);
    } else if (d.status === 'error') {
      _onJobError(d.error);
    }
  } catch(e) {
    console.error('[pollStatus]', e);
  }
}

export async function loadOutputs() {
  const grid = document.getElementById('output-grid');
  grid.innerHTML = '<div style="color:var(--text-dim);font-size:13px;padding:20px">Loading...</div>';

  const [vidsRes, anRes] = await Promise.all([
    fetch('/api/outputs'),
    fetch('/api/analytics/list'),
  ]);
  const d  = await vidsRes.json();
  const an = await anRes.json();
  const metricsByVid = (an?.metrics?.by_video) || {};
  const uploads = an?.uploads || [];
  const titleToVid = {};
  for (const u of uploads) {
    titleToVid[(u.title || '').toLowerCase()] = u.video_id;
  }

  const summary = document.getElementById('analytics-summary');
  if (an?.metrics?.refreshed_at && Object.keys(metricsByVid).length) {
    const totViews = Object.values(metricsByVid).reduce((s, m) => s + (m.views || 0), 0);
    const ctrs    = Object.values(metricsByVid).map(m => m.ctr || 0).filter(x => x > 0);
    const avgCTR  = ctrs.length ? (ctrs.reduce((a,b) => a+b, 0) / ctrs.length).toFixed(1) : '—';
    summary.textContent = `${Object.keys(metricsByVid).length} tracked videos · ${totViews.toLocaleString()} total views · avg CTR ${avgCTR}% · refreshed ${an.metrics.refreshed_at.slice(0,16)}`;
  } else {
    summary.textContent = '';
  }

  if (!d.length) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column:1/-1">
        <svg fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"/></svg>
        <p>No videos yet. Generate your first one!</p>
      </div>`;
    return;
  }

  grid.innerHTML = d.map(v => {
    const vidName = v.name.replace('.mp4','').slice(16);
    const vid     = titleToVid[vidName.toLowerCase()];
    const m       = vid ? metricsByVid[vid] : null;
    let perf = '';
    if (m) {
      const ctr = (m.ctr || 0).toFixed(1);
      const avp = (m.avg_view_percent || 0).toFixed(0);
      perf = `<div class="output-meta" style="color:var(--gold);margin-top:4px">
        ${(m.views||0).toLocaleString()} views · CTR ${ctr}% · AVD ${avp}%
      </div>`;
    }
    const safeName  = escapeHTML(v.name);
    const safeThumb = v.thumbnail ? escapeHTML(v.thumbnail) : '';
    return `
    <div class="output-card">
      ${v.thumbnail
        ? `<img class="output-thumb" src="/api/outputs/thumbnail/${safeThumb}" alt="thumbnail" loading="lazy">`
        : `<div class="output-thumb-placeholder">${icon('film', 32)}</div>`}
      <div class="output-info">
        <div class="output-name">${escapeHTML(vidName)}</div>
        <div class="output-meta">${escapeHTML(String(v.size_mb))} MB &nbsp;·&nbsp; ${escapeHTML(v.created)}</div>
        ${perf}
        <div class="output-actions">
          <a href="/api/outputs/download/${safeName}" class="btn btn-primary btn-sm" download>
            ↓ Download
          </a>
          ${v.thumbnail ? `<a href="/api/outputs/thumbnail/${safeThumb}" class="btn btn-ghost btn-sm" title="Download thumbnail" download>${icon('image')}</a>` : ''}
          <button class="btn btn-gold btn-sm" data-action="yt-upload" data-video="${safeName}" title="Upload to YouTube">${icon('upload')} YT</button>
          <button class="btn btn-ghost btn-sm" data-action="review-video" data-video="${safeName}" title="LLM performance review">${icon('search')}</button>
          <button class="btn btn-danger btn-sm" data-action="delete-output" data-video="${safeName}" title="Delete">${icon('trash')}</button>
        </div>
      </div>
    </div>
  `;
  }).join('');

  // Event delegation — attach once; no inline onclick with dynamic data
  if (!grid.dataset.delegated) {
    grid.dataset.delegated = '1';
    grid.addEventListener('click', e => {
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      const video  = btn.dataset.video;
      if (action === 'yt-upload')      ytUploadVideo(video);
      else if (action === 'review-video')  reviewVideo(video);
      else if (action === 'delete-output') deleteOutput(video);
    });
  }
}

export async function refreshAnalytics() {
  toast('Pulling YouTube analytics...', 'info');
  const r = await fetch('/api/analytics/refresh', { method: 'POST' });
  const d = await r.json();
  if (!r.ok) { toast(d.error || 'Failed.', 'error'); return; }

  const poll = setInterval(async () => {
    const sr = await fetch('/api/analytics/refresh-status/' + d.job_id);
    const sd = await sr.json();
    if (sd.status === 'done') {
      clearInterval(poll);
      const r2 = sd.result || {};
      toast(`Analytics refreshed: ${r2.refreshed||0}/${r2.total||0}`, 'ok');
      loadOutputs();
    } else if (sd.status === 'error') {
      clearInterval(poll);
      toast('Analytics failed: ' + (sd.error || ''), 'error');
    }
  }, 2000);
}

export async function deleteOutput(name) {
  if (!confirm(`Delete ${name}?`)) return;
  await fetch('/api/outputs/delete', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name })
  });
  toast('Deleted.', 'info');
  loadOutputs();
}

export async function loadMusic() {
  const list = document.getElementById('music-list');
  const r    = await fetch('/api/music');
  const d    = await r.json();
  document.getElementById('music-count').textContent = d.length;

  if (!d.length) {
    list.innerHTML = '<div style="color:var(--text-dim);font-size:13px;text-align:center;padding:20px">No music uploaded yet.</div>';
    return;
  }

  list.innerHTML = d.map(t => `
    <div class="music-item">
      <div class="music-item-info">
        <div class="music-icon">${icon('music', 22)}</div>
        <div>
          <div class="music-name">${t.name}</div>
          <div class="music-size">${t.size_kb} KB</div>
        </div>
      </div>
      <button class="btn btn-danger btn-sm" onclick="deleteMusic('${t.name}')">Remove</button>
    </div>
  `).join('');
}

export async function uploadMusic(files) {
  for (const file of files) {
    const fd = new FormData();
    fd.append('file', file);
    const r = await fetch('/api/music/upload', { method: 'POST', body: fd });
    const d = await r.json();
    if (d.ok) toast(`Uploaded: ${file.name}`, 'ok');
    else toast(d.error || 'Upload failed', 'error');
  }
  loadMusic();
}

export async function deleteMusic(name) {
  await fetch('/api/music/delete', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ name })
  });
  toast('Removed.', 'info');
  loadMusic();
}

export async function generateScriptWithAI() {
  const idea     = document.getElementById('ai-idea').value.trim();
  const minutes  = parseFloat(document.getElementById('ai-minutes').value || '10');
  const research = document.getElementById('ai-research').checked;
  if (idea.length < 8) { toast('Enter a topic first.', 'error'); return; }

  const btn   = document.getElementById('ai-gen-btn');
  const stat  = document.getElementById('ai-status');
  const logEl = document.getElementById('ai-log');
  btn.disabled    = true;
  btn.textContent = 'Working...';
  stat.textContent = 'Sending to OpenRouter...';
  logEl.style.display = 'block';
  logEl.textContent   = '';

  let r, d;
  try {
    r = await fetch('/api/generate-script', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ idea, minutes, research }),
    });
    d = await r.json();
  } catch (e) {
    stat.textContent = ''; toast('Network error.', 'error');
    btn.disabled = false; btn.textContent = 'Generate Title + Script + SEO';
    return;
  }
  if (!r.ok) {
    stat.textContent = '';
    toast(d.error || 'Failed.', 'error');
    btn.disabled = false; btn.textContent = 'Generate Title + Script + SEO';
    return;
  }

  const jobId = d.job_id;
  if (state.aiScriptPoll) clearInterval(state.aiScriptPoll);
  state.aiScriptPoll = setInterval(async () => {
    const sr = await fetch('/api/script-status/' + jobId);
    const sd = await sr.json();
    logEl.textContent = (sd.log || []).join('\n');
    logEl.scrollTop   = logEl.scrollHeight;

    if (sd.status === 'done') {
      clearInterval(state.aiScriptPoll); state.aiScriptPoll = null;
      const res = sd.result;
      document.getElementById('vid-title').value  = res.title || '';
      document.getElementById('vid-script').value = res.script || '';
      window.aiResult = res;   // hold for description copy
      updateWordCount();
      stat.innerHTML  = `<span class="badge badge-ok">${icon('check')} Generated — review, then click Generate Video below.</span>`
                      + '<div style="margin-top:8px;color:var(--text-dim)">Model: ' + (res.model||'?')
                      + ' · Words: ' + (res.word_count||0)
                      + (res.warning ? ` · <span style="color:#e6a23a">${icon('warning')} ` + res.warning + '</span>' : '')
                      + '</div>';
      btn.disabled = false; btn.textContent = 'Generate Title + Script + SEO';
      toast('Script ready.', 'ok');
    } else if (sd.status === 'error') {
      clearInterval(state.aiScriptPoll); state.aiScriptPoll = null;
      stat.innerHTML = `<span class="badge badge-error">${icon('x')} ` + (sd.error || 'Failed') + '</span>';
      btn.disabled = false; btn.textContent = 'Generate Title + Script + SEO';
      toast('Generation failed.', 'error');
    } else {
      stat.textContent = 'Working... (' + ((sd.log || []).slice(-1)[0] || '') + ')';
    }
  }, 1500);
}

export async function loadJobs() {
  const list = document.getElementById('jobs-list');
  if (!list) return;
  const status = document.getElementById('jobs-filter-status').value;
  const kind   = document.getElementById('jobs-filter-kind').value;
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (kind)   params.set('kind',   kind);
  params.set('limit', '100');
  list.innerHTML = '<div style="color:var(--text-dim);font-size:13px">Loading...</div>';

  let items = [];
  try {
    const r = await fetch('/api/jobs/list?' + params.toString());
    items = await r.json();
  } catch (e) {
    list.innerHTML = '<div style="color:var(--text-dim)">Failed to load.</div>';
    return;
  }

  if (!items.length) {
    list.innerHTML = '<div class="empty-state"><p>No jobs in this filter yet.</p></div>';
    return;
  }

  list.innerHTML = items.map(j => {
    const when = (j.started_at || '').replace('T', ' ').slice(0, 16);
    const ttl  = (j.title || '').replace(/[<>]/g, '');
    const dur  = j.duration_s ? ` · ${j.duration_s}s` : '';
    const sb   = j.status === 'done'    ? `<span class="badge badge-ok">done</span>`
              : j.status === 'error'   ? `<span class="badge badge-error">error</span>`
              : j.status === 'running' ? `<span class="badge" style="background:#3a3a00;color:#e6a23a">running ${j.progress||0}%</span>`
              : `<span class="badge" style="background:#222;color:var(--text-dim)">${j.status||'?'}</span>`;
    return `
      <div class="card" style="margin-bottom:8px;cursor:pointer" onclick="toggleJobDetail('${j.id}')">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:12px">
          <div style="flex:1;min-width:0">
            <div style="font-size:13px;font-weight:600">${escapeHTML(ttl)}</div>
            <div style="font-size:11px;color:var(--text-dim);margin-top:4px">
              ${j.kind || '?'} · ${when}${dur} · id: ${j.id}
              ${j.error ? ` · <span style="color:#e6a23a">${escapeHTML(j.error.slice(0, 90))}</span>` : ''}
              ${j.stage && j.status === 'running' ? ` · ${escapeHTML(j.stage)}` : ''}
            </div>
          </div>
          ${sb}
        </div>
        <div id="jdetail-${j.id}" style="display:none;margin-top:10px;padding-top:10px;border-top:1px solid #222"></div>
      </div>`;
  }).join('');
}

export async function toggleJobDetail(id) {
  const el = document.getElementById('jdetail-' + id);
  if (!el) return;
  if (el.style.display === 'block') { el.style.display = 'none'; return; }
  el.style.display = 'block';
  el.innerHTML = '<div style="color:var(--text-dim);font-size:12px">Loading...</div>';

  let j = {};
  try {
    const r = await fetch('/api/jobs/' + id);
    j = await r.json();
  } catch (e) {
    el.innerHTML = '<div style="color:var(--text-dim)">Failed to load detail.</div>';
    return;
  }

  const log = j.log || '';
  const result = j.result ? `<pre style="background:#0a0a0a;border:1px solid #222;border-radius:6px;padding:8px;font-size:11px;color:var(--text);overflow-x:auto;white-space:pre-wrap">${escapeHTML(JSON.stringify(j.result, null, 2))}</pre>` : '';
  el.innerHTML = `
    ${result}
    <details ${log ? 'open' : ''} style="margin-top:8px">
      <summary style="cursor:pointer;font-size:12px;color:var(--text-dim)">Log (${log.split('\\n').length} lines)</summary>
      <pre style="max-height:300px;overflow:auto;background:#0a0a0a;border:1px solid #222;border-radius:6px;padding:8px;font-size:11px;color:var(--text-dim);margin-top:6px;white-space:pre-wrap">${escapeHTML(log)}</pre>
    </details>`;
}

export async function cleanupJobs() {
  if (!confirm('Trim job history to the most recent 200 entries?')) return;
  const r = await fetch('/api/jobs/cleanup', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ keep_recent: 200 }),
  });
  const d = await r.json();
  toast(`Removed ${d.deleted || 0} old job records.`, 'ok');
  loadJobs();
}

export async function runStorageCleanup() {
  if (!confirm('Clean intermediate workspaces older than 7 days and enforce the output cap?')) return;
  const r = await fetch('/api/storage/cleanup', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ older_than_days: 7, output_cap_gb: 30 }),
  });
  const d = await r.json();
  toast(`Freed ${(d.workspaces?.freed_mb || 0)} MB · ${(d.workspaces?.workspaces_cleaned || 0)} workspaces · ${(d.output?.deleted || 0)} old MP4s`, 'ok');
  loadDashboard();
}

const BRANDING_LABELS = {
  long_intro:  "Long-form intro (1920×1080)",
  long_outro:  "Long-form outro (1920×1080)",
  short_intro: "Short intro (1080×1920)",
  short_outro: "Short outro (1080×1920)",
};

export async function loadBrandingSlots() {
  const box = document.getElementById('branding-slots');
  if (!box) return;
  let d = {};
  try {
    const r = await fetch('/api/branding/list');
    d = await r.json();
  } catch (e) { return; }

  box.innerHTML = Object.keys(BRANDING_LABELS).map(slot => {
    const v = d[slot];
    const exists = !!v;
    const dur = exists && v.duration ? v.duration.toFixed(1) + 's' : '';
    return `
      <div style="border:1px solid #222;border-radius:6px;padding:10px;background:#0d0d0d">
        <div style="font-size:12px;color:var(--text);margin-bottom:6px">${BRANDING_LABELS[slot]}</div>
        ${exists ? `
          <video src="/api/branding/preview/${slot}?t=${Date.now()}" controls muted
                 style="width:100%;border-radius:4px;background:#000;display:block;max-height:140px;margin-bottom:6px"></video>
          <div style="font-size:11px;color:var(--text-dim);display:flex;justify-content:space-between">
            <span>${dur} · ${(v.size_kb).toLocaleString()} KB</span>
            <button class="btn btn-danger btn-sm" onclick="deleteBranding('${slot}')">Remove</button>
          </div>
        ` : `
          <input type="file" accept="video/mp4,video/quicktime,video/x-matroska,video/webm"
                 id="brand-${slot}-file" style="display:none"
                 onchange="uploadBranding('${slot}', this.files[0])">
          <button class="btn btn-ghost btn-sm" style="width:100%"
                  onclick="document.getElementById('brand-${slot}-file').click()">
            Upload MP4
          </button>
          <div style="font-size:11px;color:var(--text-dim);margin-top:6px">No file yet.</div>
        `}
      </div>`;
  }).join('');
}

export async function uploadBranding(slot, file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('slot', slot);
  fd.append('file', file);
  toast('Uploading + normalising...', 'info');
  const r = await fetch('/api/branding/upload', { method: 'POST', body: fd });
  const d = await r.json();
  if (!r.ok) { toast(d.error || 'failed', 'error'); return; }

  const poll = setInterval(async () => {
    const sr = await fetch('/api/branding/upload-status/' + d.job_id);
    const sd = await sr.json();
    if (sd.status === 'done') {
      clearInterval(poll);
      toast('Branding clip ready.', 'ok');
      loadBrandingSlots();
    } else if (sd.status === 'error') {
      clearInterval(poll);
      toast('Normalize failed: ' + (sd.error || ''), 'error');
    }
  }, 1500);
}

export async function deleteBranding(slot) {
  if (!confirm('Remove this branding clip?')) return;
  await fetch('/api/branding/' + slot, { method: 'DELETE' });
  toast('Removed.', 'info');
  loadBrandingSlots();
}

export async function loadDashboard() {
  const body = document.getElementById('dash-body');
  if (!body) return;
  body.innerHTML = '<div style="color:var(--text-dim)">Loading...</div>';

  let d = {};
  try {
    const r = await fetch('/api/dashboard');
    d = await r.json();
  } catch (e) {
    body.innerHTML = '<div style="color:var(--text-dim)">Could not load dashboard.</div>';
    return;
  }

  const ch = d.channel || {};
  const refreshed = ch.metrics_refreshed_at
    ? ch.metrics_refreshed_at.replace('T', ' ').slice(0, 16)
    : '<span style="color:var(--text-dim)">never — click Refresh Analytics on the Library tab</span>';

  const pip = d.today_pipeline || {};
  const pool = d.idea_pool || {};

  const recentRows = (d.recent_uploads || []).map(u => {
    const m   = u.metrics || {};
    const ts  = (u.uploaded_at || '').replace('T', ' ').slice(0, 16);
    const url = `https://youtu.be/${u.video_id}`;
    return `<tr>
      <td style="padding:6px 10px;color:var(--text-dim);font-size:11px">${ts}</td>
      <td style="padding:6px 10px"><a href="${url}" target="_blank" style="color:var(--gold)">${escapeHTML((u.title || '').slice(0, 70))}</a></td>
      <td style="padding:6px 10px;text-align:right;color:var(--text)">${(m.views||0).toLocaleString()}</td>
      <td style="padding:6px 10px;text-align:right;color:var(--text)">${(m.ctr||0).toFixed(1)}%</td>
      <td style="padding:6px 10px;text-align:right;color:var(--text)">${(m.avg_view_percent||0).toFixed(0)}%</td>
    </tr>`;
  }).join('');

  const schedRows = Object.entries(d.scheduler || {}).map(([name, t]) => `
    <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid #1a1a1a;font-size:12px">
      <span>${name}</span>
      <span style="color:${t.enabled ? 'var(--gold)' : 'var(--text-dim)'}">
        ${t.enabled
          ? 'every ' + t.interval_hours + 'h · next ' + (t.next_run ? t.next_run.slice(11, 16) : '—')
          : 'disabled'}
      </span>
    </div>`).join('');

  const topBarItems = (d.top_tokens || []).map(t => ({
    label: `${t.token} · ${t.samples}n`, value: Math.round((t.multiplier - 1) * 100),
    color: 'var(--gold)',
  }));
  const botBarItems = (d.bottom_tokens || []).map(t => ({
    label: `${t.token} · ${t.samples}n`, value: Math.round((1 - t.multiplier) * 100),
    color: '#e6a23a',
  }));

  const uploadsBarItems = (d.recent_uploads || []).map(u => ({
    label: (u.title || '').slice(0, 50),
    value: u.metrics?.views || 0,
    color: 'rgba(206,170,98,0.85)',
  }));

  const st = d.storage || {};
  const totalDisk = st.disk_total_mb || 1;
  const usedDisk  = (st.disk_total_mb || 0) - (st.disk_free_mb || 0);
  const appPct    = ((st.app_total_mb || 0) / totalDisk) * 100;
  const usedPct   = (usedDisk / totalDisk) * 100;

  body.innerHTML = `
    <!-- Top row -->
    <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:18px">
      ${stat('Tracked videos', ch.uploads_tracked || 0)}
      ${stat('Total views',    (ch.total_views || 0).toLocaleString())}
      ${stat('Avg CTR',        (ch.avg_ctr || 0).toFixed(2) + '%')}
      ${stat('Avg AVD',        (ch.avg_view_percent || 0).toFixed(0) + '%')}
      ${stat('Subs gained',    (ch.subs_gained || 0).toLocaleString())}
      ${stat('Today: done / err / queued', (pip.done||0) + ' / ' + (pip.errors||0) + ' / ' + (pip.running||0))}
    </div>
    <div style="font-size:11px;color:var(--text-dim);margin-bottom:18px">Last analytics refresh: ${refreshed}</div>

    <!-- Activity chart + Storage panel side-by-side -->
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px">
      <div class="card">
        <div class="card-title">Pipeline activity (last 14 days)</div>
        ${svgActivityBars(d.daily_activity || [])}
        <div style="font-size:10px;color:var(--text-dim);margin-top:6px">
          <span style="display:inline-block;width:9px;height:9px;background:rgba(206,170,98,0.85);margin-right:4px"></span>done
          <span style="display:inline-block;width:9px;height:9px;background:#e6a23a;margin:0 4px 0 14px"></span>error
        </div>
      </div>
      <div class="card">
        <div class="card-title">Storage</div>
        <div style="font-size:12px;color:var(--text-dim);margin-bottom:6px">
          Disk: ${(usedDisk/1024).toFixed(1)} GB used · ${(st.disk_free_mb/1024 || 0).toFixed(1)} GB free of ${(totalDisk/1024).toFixed(0)} GB
        </div>
        <div style="height:14px;background:#1a1a1a;border-radius:3px;overflow:hidden;position:relative">
          <div style="height:100%;width:${appPct.toFixed(1)}%;background:var(--gold);position:absolute;left:0"></div>
          <div style="height:100%;width:${(usedPct - appPct).toFixed(1)}%;background:#444;position:absolute;left:${appPct.toFixed(1)}%"></div>
        </div>
        <div style="font-size:11px;color:var(--text);margin-top:10px;line-height:1.7">
          <div style="display:flex;align-items:center;gap:6px">${icon('folder')} workspace: <strong>${(st.workspace_mb||0).toLocaleString()} MB</strong></div>
          <div style="display:flex;align-items:center;gap:6px">${icon('film')} output: <strong>${(st.output_mb||0).toLocaleString()} MB</strong></div>
          <div style="display:flex;align-items:center;gap:6px">${icon('disk')} cache: <strong>${(st.cache_mb||0).toLocaleString()} MB</strong></div>
          <div style="display:flex;align-items:center;gap:6px">${icon('palette')} branding: <strong>${(st.branding_mb||0).toLocaleString()} MB</strong></div>
        </div>
        ${(st.freeable?.freeable_mb > 0)
          ? `<div style="font-size:11px;color:var(--gold);margin-top:8px">${st.freeable.freeable_mb} MB freeable in ${st.freeable.candidate_workspaces} workspace(s).</div>`
          : ''}
        <button class="btn btn-ghost btn-sm" style="margin-top:10px;display:inline-flex;align-items:center;gap:6px" onclick="runStorageCleanup()">${icon('broom')} Run cleanup now</button>
      </div>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;margin-bottom:18px">
      <div class="card">
        <div class="card-title">Idea pool</div>
        <div style="font-size:13px;line-height:1.8">
          <div>Pending review: <strong>${pool.pending || 0}</strong></div>
          <div>Approved: <strong>${pool.approved || 0}</strong></div>
          <div>Produced: <strong>${pool.produced || 0}</strong></div>
          <div>Rejected: <strong>${pool.rejected || 0}</strong></div>
        </div>
      </div>
      <div class="card">
        <div class="card-title">Scheduler</div>
        ${schedRows || '<div style="color:var(--text-dim);font-size:12px">No schedules configured.</div>'}
      </div>
    </div>

    ${uploadsBarItems.length ? `
    <div class="card" style="margin-bottom:18px">
      <div class="card-title">Recent uploads — view counts</div>
      ${svgBars(uploadsBarItems)}
    </div>` : ''}

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px">
      <div class="card">
        <div class="card-title">Top-performing tokens</div>
        ${topBarItems.length
          ? svgBars(topBarItems, { fmt: n => `+${n}%` })
          : '<div style="color:var(--text-dim);font-size:12px">No data yet — upload + refresh analytics.</div>'}
      </div>
      <div class="card">
        <div class="card-title">Underperforming tokens</div>
        ${botBarItems.length
          ? svgBars(botBarItems, { fmt: n => `−${n}%` })
          : '<div style="color:var(--text-dim);font-size:12px">None yet — every signal stays at 1.0× until it deviates.</div>'}
      </div>
    </div>
  `;
}

const SCHED_TASK_LABELS = {
  harvest_ideas:     `${icon('wheat')} Harvest ideas`,
  produce_top_idea:  `${icon('film')} Produce top idea`,
  refresh_analytics: `${icon('chart')} Refresh analytics`,
  storage_cleanup:   `${icon('broom')} Storage cleanup`,
};

export async function loadScheduler() {
  const r = await fetch('/api/scheduler/state');
  const d = await r.json();
  state._schedState = d;
  const rows = document.getElementById('sched-rows');
  if (!rows) return;
  rows.innerHTML = Object.keys(SCHED_TASK_LABELS).map(name => {
    const t = (d.tasks || {})[name] || {};
    const label = SCHED_TASK_LABELS[name];
    const lastRun = t.last_run ? t.last_run.replace('T', ' ').slice(0, 16) : '—';
    const nextRun = t.next_run ? t.next_run.replace('T', ' ').slice(0, 16) : '—';
    const lastStatus = t.last_status || '';
    const statusBadge = !lastStatus
      ? ''
      : (lastStatus.startsWith('ok') || lastStatus.startsWith('skip'))
        ? `<span style="color:var(--gold);font-size:11px">${escapeHTML(lastStatus)}</span>`
        : `<span style="color:#e6a23a;font-size:11px">${escapeHTML(lastStatus)}</span>`;
    return `
      <div style="display:flex;gap:10px;align-items:center;padding:10px 0;border-top:1px solid #222">
        <div style="flex:0 0 200px">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="sched-${name}-enabled"
                   ${t.enabled ? 'checked' : ''}
                   onchange="saveSchedulerInline()"
                   style="width:18px;height:18px;accent-color:var(--gold)">
            <span>${label}</span>
          </label>
        </div>
        <div style="flex:0 0 130px;font-size:12px;color:var(--text-dim)">
          every
          <input type="number" id="sched-${name}-hours"
                 min="1" max="168" step="1" value="${t.interval_hours}"
                 onchange="saveSchedulerInline()"
                 style="width:54px;background:#1a1a1a;color:var(--text);border:1px solid #333;border-radius:4px;padding:2px 6px;margin:0 4px">
          h
        </div>
        <div style="flex:1;font-size:11px;color:var(--text-dim);line-height:1.5;min-width:0">
          last: ${lastRun}<br>
          next: ${nextRun}<br>
          ${statusBadge}
        </div>
        <button class="btn btn-ghost btn-sm" onclick="triggerScheduler('${name}')" title="Run this task now">Run now</button>
      </div>`;
  }).join('');
}

export async function saveSchedulerInline() {
  const cfg = (await (await fetch('/api/config')).json()) || {};
  cfg.scheduler = cfg.scheduler || {};
  for (const name of Object.keys(SCHED_TASK_LABELS)) {
    const enabled = document.getElementById('sched-' + name + '-enabled')?.checked;
    const hours   = parseFloat(document.getElementById('sched-' + name + '-hours')?.value || '6');
    cfg.scheduler[name] = { enabled: !!enabled, interval_hours: hours };
  }
  await fetch('/api/config', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(cfg),
  });
  loadScheduler();
}

export async function triggerScheduler(name) {
  const r = await fetch('/api/scheduler/trigger/' + name, { method: 'POST' });
  const d = await r.json();
  if (!r.ok) { toast(d.error || 'failed', 'error'); return; }
  toast('Triggered: ' + name, 'info');
  setTimeout(loadScheduler, 1500);
}

export async function harvestIdeas() {
  const btn = document.getElementById('harv-btn');
  const stat = document.getElementById('harv-status');
  const log  = document.getElementById('harv-log');
  btn.disabled = true; btn.textContent = 'Harvesting...';
  log.style.display = 'block'; log.textContent = '';
  stat.textContent = 'starting...';

  const ytSeeds = (document.getElementById('harv-yt').value || '')
    .split(',').map(s => s.trim()).filter(Boolean);
  const subs    = (document.getElementById('harv-subs').value || '')
    .split(',').map(s => s.trim()).filter(Boolean);
  const niche   = (document.getElementById('harv-niche').value || '').trim();

  const r = await fetch('/api/ideas/harvest', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({
      yt_seeds: ytSeeds, subreddits: subs, niche,
      include_wikipedia: true,
    }),
  });
  const d = await r.json();

  if (state.harvestPoll) clearInterval(state.harvestPoll);
  state.harvestPoll = setInterval(async () => {
    const sr = await fetch('/api/ideas/harvest-status/' + d.job_id);
    const sd = await sr.json();
    log.textContent = (sd.log || []).join('\n');
    log.scrollTop = log.scrollHeight;
    if (sd.status === 'done') {
      clearInterval(state.harvestPoll); state.harvestPoll = null;
      btn.disabled = false; btn.textContent = 'Harvest Now';
      stat.innerHTML = `<span class="badge badge-ok">${icon('check')} +${sd.result?.added||0} new ideas</span>`;
      toast(`Added ${sd.result?.added||0} ideas.`, 'ok');
      loadIdeas();
    } else if (sd.status === 'error') {
      clearInterval(state.harvestPoll); state.harvestPoll = null;
      btn.disabled = false; btn.textContent = 'Harvest Now';
      stat.innerHTML = `<span class="badge badge-error">${icon('x')} ` + (sd.error || 'failed') + `</span>`;
    } else {
      stat.textContent = 'working... ' + ((sd.log || []).slice(-1)[0] || '');
    }
  }, 1500);
}

export async function loadIdeas() {
  const status = document.getElementById('ideas-filter').value;
  const r = await fetch('/api/ideas/list' + (status ? '?status=' + status : ''));
  const items = await r.json();
  const box = document.getElementById('ideas-list');
  document.getElementById('ideas-count').textContent = items.length + ' shown';

  if (!items.length) {
    box.innerHTML = `<div class="empty-state"><p>No ideas in this bucket. Try harvesting.</p></div>`;
    return;
  }

  box.innerHTML = items.map(it => {
    const fit = (it.niche_fit !== null && it.niche_fit !== undefined)
      ? Math.round(it.niche_fit * 100) + '%' : '—';
    const fitColor = (it.niche_fit !== null && it.niche_fit !== undefined)
      ? (it.niche_fit >= 0.7 ? 'var(--gold)' : (it.niche_fit >= 0.5 ? 'var(--text)' : 'var(--text-dim)'))
      : 'var(--text-dim)';
    const sourceTag = it.source.replace('_', ' ');
    let perfBadge = '';
    if (it.perf_multiplier && Math.abs(it.perf_multiplier - 1.0) > 0.05) {
      const pct = Math.round((it.perf_multiplier - 1.0) * 100);
      const color = pct > 0 ? 'var(--gold)' : '#888';
      const sign  = pct > 0 ? '+' : '';
      perfBadge = `<span style="margin-left:10px;color:${color}" title="Predicted multiplier vs channel average, from past video performance">perf signal: ${sign}${pct}%</span>`;
    }
    const isPending = it.status === 'pending';
    return `
      <div class="card" style="margin-bottom:10px">
        <div style="display:flex;justify-content:space-between;gap:14px;align-items:flex-start">
          <div style="flex:1;min-width:0">
            <div style="font-weight:600;line-height:1.4">${escapeHTML(it.title)}</div>
            <div style="font-size:11px;color:var(--text-dim);margin-top:6px">
              <span class="badge" style="background:#222;color:var(--text-dim)">${sourceTag}</span>
              <span style="margin-left:10px">niche fit: <strong style="color:${fitColor}">${fit}</strong></span>
              ${perfBadge}
              ${it.rationale ? `<span style="margin-left:10px;color:var(--text-muted)">${escapeHTML(it.rationale)}</span>` : ''}
              ${it.source_url ? `<a href="${it.source_url}" target="_blank" style="margin-left:10px;color:var(--gold)">source ↗</a>` : ''}
            </div>
            ${it.scripted_title ? `<div style="font-size:11px;color:var(--text-muted);margin-top:4px">→ scripted as: ${escapeHTML(it.scripted_title)}</div>` : ''}
            <div style="font-size:10px;color:var(--text-dim);margin-top:4px">status: ${it.status}${it.pipeline_job ? ' (pipeline ' + it.pipeline_job + ')' : ''}</div>
          </div>
          <div style="display:flex;gap:6px;flex-shrink:0;flex-wrap:wrap;justify-content:flex-end">
            ${isPending ? `<button class="btn btn-gold btn-sm" onclick="produceIdea('${it.id}')">▶ Generate</button>` : ''}
            ${isPending ? `<button class="btn btn-ghost btn-sm" onclick="setIdeaStatus('${it.id}','rejected')">Reject</button>` : ''}
            ${it.status === 'rejected' || it.status === 'produced'
              ? `<button class="btn btn-ghost btn-sm" onclick="setIdeaStatus('${it.id}','pending')">Restore</button>` : ''}
            <button class="btn btn-danger btn-sm" onclick="deleteIdea('${it.id}')" title="Delete">${icon('trash')}</button>
          </div>
        </div>
      </div>`;
  }).join('');
}

export async function setIdeaStatus(id, status) {
  await fetch('/api/ideas/' + id + '/status', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ status }),
  });
  loadIdeas();
}

export async function deleteIdea(id) {
  if (!confirm('Delete this idea?')) return;
  await fetch('/api/ideas/' + id, { method: 'DELETE' });
  loadIdeas();
}

export async function produceIdea(id) {
  const minutes = parseFloat(prompt('Target video length (minutes)?', '10') || '10');
  if (!minutes || minutes < 3) return;
  const r = await fetch('/api/ideas/' + id + '/produce', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ minutes }),
  });
  const d = await r.json();
  if (!r.ok) { toast(d.error || 'Failed.', 'error'); return; }
  toast('Scripting + rendering started — check the Generate page progress panel.', 'ok');
  showPage('generate');
  loadIdeas();
}

export async function reviewVideo(filename) {
  const body = document.getElementById('review-body');
  document.getElementById('review-modal').classList.add('open');
  body.innerHTML = `<div style="font-size:13px;color:var(--text-dim);padding:30px;text-align:center">
    Analysing <strong style="color:var(--text)">${escapeHTML(filename)}</strong>...<br>
    <span style="font-size:11px">Pulls script + outline + tags + metrics, asks an LLM for a scorecard. Takes ~10–20s.</span>
  </div>`;

  let r, d;
  try {
    r = await fetch('/api/review-video', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ video: filename }),
    });
    d = await r.json();
  } catch (e) {
    body.innerHTML = '<div style="color:#e67">Network error.</div>'; return;
  }
  if (!r.ok) {
    body.innerHTML = `<div style="color:#e67">${escapeHTML(d.error || 'failed')}</div>`;
    return;
  }

  if (state.reviewPoll) clearInterval(state.reviewPoll);
  state.reviewPoll = setInterval(async () => {
    const sr = await fetch('/api/review-status/' + d.job_id);
    const sd = await sr.json();
    if (sd.status === 'done') {
      clearInterval(state.reviewPoll); state.reviewPoll = null;
      renderReview(body, sd.result);
    } else if (sd.status === 'error') {
      clearInterval(state.reviewPoll); state.reviewPoll = null;
      body.innerHTML = `<div style="color:#e67">${escapeHTML(sd.error || 'failed')}</div>`;
    }
  }, 1500);
}

export async function refreshYTStatus() {
  const box = document.getElementById('yt-status-box');
  if (!box) return;
  let d = {};
  try {
    const r = await fetch('/api/youtube/status');
    d = await r.json();
  } catch (e) { box.innerHTML = '<span style="color:var(--text-dim)">Status unavailable.</span>'; return; }

  const row = (label, ok) =>
    `<div>${ok ? `<span class="badge badge-ok">${icon('check')}</span>` : `<span class="badge badge-error">${icon('x')}</span>`} ${label}</div>`;
  let html = '';
  html += row('YouTube libs installed', d.installed);
  html += row('client_secrets.json uploaded', d.has_secrets);
  html += row('Authorized', d.has_token);
  if (d.channel) {
    html += `<div style="margin-top:6px;color:var(--gold)">Channel: <strong>${d.channel.title}</strong> · ${d.channel.subscribers.toLocaleString()} subs</div>`;
  }
  box.innerHTML = html;
  document.getElementById('yt-revoke-btn').style.display = d.has_token ? 'inline-flex' : 'none';
}

export async function ytInstall() {
  const btn = document.getElementById('yt-install-btn');
  const log = document.getElementById('yt-log');
  btn.disabled = true; btn.textContent = 'Installing...';
  log.style.display = 'block'; log.textContent = '';
  const r = await fetch('/api/youtube/install', { method: 'POST' });
  const d = await r.json();
  const poll = setInterval(async () => {
    const sr = await fetch('/api/youtube/install-status/' + d.job_id);
    const sd = await sr.json();
    log.textContent = (sd.log || []).join('\n');
    log.scrollTop = log.scrollHeight;
    if (sd.status === 'done') {
      clearInterval(poll);
      btn.disabled = false; btn.textContent = '1. Install libs';
      toast('YouTube libs installed.', 'ok');
      refreshYTStatus();
    } else if (sd.status === 'error') {
      clearInterval(poll);
      btn.disabled = false; btn.textContent = '1. Install libs';
      toast('Install failed.', 'error');
    }
  }, 1200);
}

export async function ytUploadSecrets(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append('file', file);
  const r = await fetch('/api/youtube/upload-secrets', { method: 'POST', body: fd });
  const d = await r.json();
  if (r.ok) {
    toast('client_secrets.json saved. Now click Authorize.', 'ok');
    refreshYTStatus();
  } else {
    toast(d.error || 'Upload failed.', 'error');
  }
}

export async function ytAuthorize() {
  const btn = document.getElementById('yt-auth-btn');
  const log = document.getElementById('yt-log');
  btn.disabled = true; btn.textContent = 'Waiting for browser...';
  log.style.display = 'block';
  log.textContent = 'A browser tab is opening. Approve access there.\n';

  const r = await fetch('/api/youtube/authorize', { method: 'POST' });
  const d = await r.json();
  if (!r.ok) {
    btn.disabled = false; btn.textContent = '3. Authorize';
    toast(d.error || 'Authorize failed.', 'error'); return;
  }
  const poll = setInterval(async () => {
    const sr = await fetch('/api/youtube/auth-status/' + d.job_id);
    const sd = await sr.json();
    if (sd.log && sd.log.length) {
      log.textContent = sd.log.join('\n'); log.scrollTop = log.scrollHeight;
    }
    if (sd.status === 'done') {
      clearInterval(poll);
      btn.disabled = false; btn.textContent = '3. Authorize';
      toast('Authorized.', 'ok');
      refreshYTStatus();
    } else if (sd.status === 'error') {
      clearInterval(poll);
      btn.disabled = false; btn.textContent = '3. Authorize';
      toast('Auth failed: ' + (sd.error || ''), 'error');
    }
  }, 1500);
}

export async function ytRevoke() {
  if (!confirm('Revoke the saved YouTube token? You will need to re-authorize.')) return;
  await fetch('/api/youtube/revoke', { method: 'POST' });
  toast('Token revoked.', 'info');
  refreshYTStatus();
}

export async function ytUploadVideo(filename) {
  if (!confirm('Upload "' + filename + '" to YouTube as ' +
               (document.getElementById('default-privacy')?.value || 'private') + '?')) return;
  const opts = {
    video: filename,
    privacy_status: document.getElementById('default-privacy')?.value || 'private',
    contains_synthetic_media: (document.getElementById('contains-synth')?.value || 'true') === 'true',
  };
  const r = await fetch('/api/youtube/upload-video', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(opts),
  });
  const d = await r.json();
  if (!r.ok) { toast(d.error || 'Failed to start.', 'error'); return; }

  toast('Uploading to YouTube...', 'info');
  const poll = setInterval(async () => {
    const sr = await fetch('/api/youtube/upload-status/' + d.job_id);
    const sd = await sr.json();
    if (sd.status === 'done') {
      clearInterval(poll);
      toast('Uploaded! ' + sd.result.url, 'ok');
      window.open(sd.result.studio, '_blank');
    } else if (sd.status === 'error') {
      clearInterval(poll);
      toast('Upload failed: ' + (sd.error || ''), 'error');
    }
  }, 2000);
}

export async function testThumbnail() {
  const title = document.getElementById('vid-title').value.trim();
  if (title.length < 4) { toast('Enter a video title first.', 'error'); return; }

  const btn    = document.getElementById('thumb-test-btn');
  const resBox = document.getElementById('thumb-test-result');
  const logEl  = document.getElementById('thumb-test-log');

  btn.disabled    = true;
  btn.textContent = 'Working...';
  resBox.style.display = 'none';
  logEl.style.display  = 'block';
  logEl.textContent    = '';

  let r, d;
  try {
    r = await fetch('/api/test-thumbnail', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ title, variants: 1 })
    });
    d = await r.json();
  } catch (e) {
    toast('Network error.', 'error');
    btn.disabled = false; btn.textContent = 'Test Thumbnail';
    return;
  }
  if (!r.ok) {
    toast(d.error || 'Failed.', 'error');
    btn.disabled = false; btn.textContent = 'Test Thumbnail';
    return;
  }

  const jobId = d.job_id;
  if (state.thumbPoll) clearInterval(state.thumbPoll);
  state.thumbPoll = setInterval(async () => {
    const sr = await fetch('/api/thumb-status/' + jobId);
    const sd = await sr.json();
    logEl.textContent = (sd.log || []).join('\n');
    logEl.scrollTop   = logEl.scrollHeight;

    if (sd.status === 'done') {
      clearInterval(state.thumbPoll); state.thumbPoll = null;
      const res  = sd.result;
      const img  = document.getElementById('thumb-test-img');
      const meta = document.getElementById('thumb-test-meta');
      img.src = '/api/outputs/thumbnail/' + encodeURIComponent(res.primary) + '?t=' + Date.now();
      meta.textContent = 'Punchline: "' + (res.punchline||'') + '" · saved as ' + res.primary;
      resBox.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Test Thumbnail';
      toast('Thumbnail preview ready.', 'ok');
    } else if (sd.status === 'error') {
      clearInterval(state.thumbPoll); state.thumbPoll = null;
      toast('Thumbnail failed: ' + (sd.error || 'unknown'), 'error');
      btn.disabled = false; btn.textContent = 'Test Thumbnail';
    }
  }, 1500);
}

export async function loadSettings() {
  const r = await fetch('/api/config');
  const d = await r.json();

  const key = d.pexels_api_key || '';
  document.getElementById('pexels-key').value   = key;
  document.getElementById('openrouter-key').value = d.openrouter_api_key || '';
  document.getElementById('tts-voice').value    = d.tts_voice || 'en-US-GuyNeural';
  renderVoicePool(d.tts_voices || []);
  document.getElementById('music-vol').value    = d.music_volume || 0.12;
  document.getElementById('vol-val').textContent= Math.round((d.music_volume||0.12)*100)+'%';
  document.getElementById('max-clips').value    = d.max_clips || 25;

  const res = d.video_resolution || [1920,1080];
  document.getElementById('vid-res').value = `${res[0]}x${res[1]}`;

  if (key) {
    document.getElementById('pexels-status').innerHTML =
      `<span class="badge badge-ok">${icon('check')} Key saved</span>`;
  }
  if (d.openrouter_api_key) {
    document.getElementById('openrouter-status').innerHTML =
      `<span class="badge badge-ok">${icon('check')} Key saved</span>`;
  }
  document.getElementById('use-ai-thumb').checked = d.use_ai_thumbnail !== false;
  document.getElementById('thumb-variants').value = d.thumbnail_variants || 1;
  document.getElementById('burn-captions').checked = !!d.burn_captions;
  document.getElementById('caption-model').value   = d.caption_model || 'base.en';
  document.getElementById('smart-broll').checked   = d.smart_broll !== false;
  document.getElementById('chunk-seconds').value   = d.chunk_seconds || 10;
  document.getElementById('pixabay-key').value     = d.pixabay_api_key || '';
  document.getElementById('auto-upload').checked   = !!d.auto_upload;
  document.getElementById('default-privacy').value = d.default_privacy || 'private';
  document.getElementById('contains-synth').value  = (d.contains_synthetic_media === false) ? 'false' : 'true';
  document.getElementById('use-research').checked  = !!d.use_research;
  document.getElementById('motion-effect').value   = d.motion_effect || 'pan';
  document.getElementById('audio-polish').checked  = d.audio_polish !== false;
  document.getElementById('ducking-db').value      = d.ducking_db ?? 8;
  document.getElementById('duck-val').textContent  = (d.ducking_db ?? 8) + ' dB';
  document.getElementById('apply-branding').checked = d.apply_branding !== false;

  if (d.daily_limit_long !== undefined) document.getElementById('limit-long').value = d.daily_limit_long;
  if (d.daily_limit_short !== undefined) document.getElementById('limit-short').value = d.daily_limit_short;

  loadBrandingSlots();
  refreshYTStatus();
  refreshCaptionInstallStatus();
  loadScheduler();
}

export async function refreshCaptionInstallStatus() {
  const el = document.getElementById('cap-install-status');
  if (!el) return;
  try {
    const r = await fetch('/api/captions/status');
    const d = await r.json();
    if (d.available) {
      el.innerHTML = `<span class="badge badge-ok">${icon('check')} Installed</span>`;
      document.getElementById('cap-install-btn').textContent = 'Reinstall';
    } else {
      el.innerHTML = '<span class="badge badge-error">Not installed</span>';
    }
  } catch (e) {
    el.textContent = '';
  }
}

export async function installCaptions() {
  const btn  = document.getElementById('cap-install-btn');
  const stat = document.getElementById('cap-install-status');
  const log  = document.getElementById('cap-install-log');
  btn.disabled = true; btn.textContent = 'Installing...';
  stat.textContent = 'pip install faster-whisper running...';
  log.style.display = 'block';
  log.textContent = '';

  const r = await fetch('/api/captions/install', { method: 'POST' });
  const d = await r.json();
  const jobId = d.job_id;

  const poll = setInterval(async () => {
    const sr = await fetch('/api/captions/install-status/' + jobId);
    const sd = await sr.json();
    log.textContent = (sd.log || []).join('\n');
    log.scrollTop   = log.scrollHeight;
    if (sd.status === 'done') {
      clearInterval(poll);
      btn.disabled = false; btn.textContent = 'Reinstall';
      stat.innerHTML = `<span class="badge badge-ok">${icon('check')} Installed</span>`;
      toast('faster-whisper installed.', 'ok');
      refreshCaptionInstallStatus();
    } else if (sd.status === 'error') {
      clearInterval(poll);
      btn.disabled = false; btn.textContent = 'Install caption deps';
      stat.innerHTML = `<span class="badge badge-error">${icon('x')} ` + (sd.error || 'failed') + `</span>`;
      toast('Install failed — see log.', 'error');
    }
  }, 1200);
}

export async function validateAndSaveOpenrouter() {
  const key = document.getElementById('openrouter-key').value.trim();
  if (!key) { toast('Enter a key first.', 'error'); return; }

  const status = document.getElementById('openrouter-status');
  status.innerHTML = '<span style="color:var(--text-dim);font-size:12px">Validating against free model...</span>';
  const r = await fetch('/api/openrouter/validate', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ key })
  });
  const d = await r.json();
  if (d.valid) {
    status.innerHTML = `<span class="badge badge-ok">${icon('check')} Valid key — saved!</span>`;
    await saveSettings();
    toast('OpenRouter key validated and saved!', 'ok');
  } else {
    status.innerHTML = `<span class="badge badge-error">${icon('x')} Invalid key or no free models available</span>`;
    toast('OpenRouter validation failed.', 'error');
  }
}

export async function validateAndSavePexels() {
  const key = document.getElementById('pexels-key').value.trim();
  if (!key) { toast('Enter a key first.', 'error'); return; }

  document.getElementById('pexels-status').innerHTML = '<span style="color:var(--text-dim);font-size:12px">Validating...</span>';
  const r = await fetch('/api/validate-pexels', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({ key })
  });
  const d = await r.json();
  if (d.valid) {
    document.getElementById('pexels-status').innerHTML = `<span class="badge badge-ok">${icon('check')} Valid key — saved!</span>`;
    await saveSettings();
    toast('Pexels key validated and saved!', 'ok');
  } else {
    document.getElementById('pexels-status').innerHTML = `<span class="badge badge-error">${icon('x')} Invalid key — check and retry</span>`;
    toast('Invalid Pexels API key.', 'error');
  }
}

export async function saveSettings() {
  const res   = document.getElementById('vid-res').value.split('x').map(Number);
  const cfg = {
    pexels_api_key:     document.getElementById('pexels-key').value.trim(),
    openrouter_api_key: document.getElementById('openrouter-key').value.trim(),
    tts_voice:          document.getElementById('tts-voice').value,
    tts_voices:         collectVoicePool(),
    music_volume:       parseFloat(document.getElementById('music-vol').value),
    video_resolution:   res,
    max_clips:          parseInt(document.getElementById('max-clips').value),
    use_ai_thumbnail:   document.getElementById('use-ai-thumb').checked,
    thumbnail_variants: parseInt(document.getElementById('thumb-variants').value) || 1,
    burn_captions:      document.getElementById('burn-captions').checked,
    caption_model:      document.getElementById('caption-model').value,
    smart_broll:        document.getElementById('smart-broll').checked,
    chunk_seconds:      parseInt(document.getElementById('chunk-seconds').value) || 10,
    pixabay_api_key:    document.getElementById('pixabay-key').value.trim(),
    auto_upload:        document.getElementById('auto-upload').checked,
    default_privacy:    document.getElementById('default-privacy').value,
    contains_synthetic_media: document.getElementById('contains-synth').value === 'true',
    use_research:       document.getElementById('use-research').checked,
    motion_effect:      document.getElementById('motion-effect').value,
    audio_polish:       document.getElementById('audio-polish').checked,
    ducking_db:         parseFloat(document.getElementById('ducking-db').value) || 8,
    apply_branding:     document.getElementById('apply-branding').checked,
    daily_limit_long:   parseInt(document.getElementById('limit-long').value) || 0,
    daily_limit_short:  parseInt(document.getElementById('limit-short').value) || 0,
  };
  await fetch('/api/config', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify(cfg)
  });
  toast('Settings saved!', 'ok');
}
