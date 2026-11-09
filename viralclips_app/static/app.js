/* ==========================================================================
   VIRALCLIPS AI — frontend
   Every view reads from the backend. There are no hardcoded metrics and no
   simulated values: an empty database renders zeros, not samples.
   ========================================================================== */

'use strict';

const State = {
  token: '',
  route: 'overview',
  config: {},
  settings: {},
  ai: null,
  overview: null,
  clips: [],
  tasks: [],
  channels: [],
  videos: [],
  jobs: [],
  accounts: {},
  analytics: null,
  episodes: [],
  search: '',
  selectedClip: null,
  theme: localStorage.getItem('vc-theme') || 'dark',
};

/* ── dom helpers ─────────────────────────────────────────────────────── */

const $  = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (key === 'class') node.className = value;
    // There is deliberately no 'html' attribute: content is set with
    // textContent so that a title or transcript can never be injected
    // as markup.
    else if (key === 'text') node.textContent = value;
    else if (key.startsWith('on') && typeof value === 'function') {
      node.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === 'dataset') {
      Object.assign(node.dataset, value);
    } else node.setAttribute(key, value === true ? '' : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return node;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/* ── icons ────────────────────────────────────────────────────────────── */

const ICONS = {
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M18 6L6 18M6 6l12 12"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><path d="M7 10l5 5 5-5M12 15V3"/></svg>',
  play: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="6 3 20 12 6 21 6 3"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 11-3-6.7L21 8"/><path d="M21 3v5h-5"/></svg>',
  pause: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></svg>',
  film: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><path d="M2 9h20M7 4v5"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/></svg>',
  info: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/></svg>',
  link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 007.5.5l3-3a5 5 0 00-7-7l-1.5 1.5"/><path d="M14 11a5 5 0 00-7.5-.5l-3 3a5 5 0 007 7L12 19"/></svg>',
  send: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 2L11 13M22 2l-7 20-4-9-9-4z"/></svg>',
  video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 10l4.55-2.28A1 1 0 0121 8.62v6.76a1 1 0 01-1.45.9L15 14"/><rect x="3" y="6" width="12" height="12" rx="2"/></svg>',
  expand: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M8 3H5a2 2 0 00-2 2v3M16 3h3a2 2 0 012 2v3M8 21H5a2 2 0 01-2-2v-3M16 21h3a2 2 0 002-2v-3"/></svg>',
  volume: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M19.07 4.93a10 10 0 010 14.14M15.54 8.46a5 5 0 010 7.07"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l1.9 5.6L19.5 9l-5.6 1.9L12 16.5l-1.9-5.6L4.5 9l5.6-1.4z"/></svg>',
};

function icon(name, cls = '') {
  const span = document.createElement('span');
  span.style.display = 'inline-flex';
  span.innerHTML = ICONS[name] || '';
  if (cls) span.setAttribute('class', cls);
  const svg = span.firstElementChild;
  return svg || document.createTextNode('');
}

/* ── api ──────────────────────────────────────────────────────────────── */

async function api(path, options = {}) {
  const opts = { ...options };
  opts.headers = { ...(options.headers || {}) };
  if (State.token) opts.headers['X-ViralClips-Token'] = State.token;
  // Keep the untouched body so a retry after a stale-token rejection
  // does not encode an already-encoded JSON payload a second time.
  const rawBody = opts.body;
  const isJson = rawBody && !(rawBody instanceof FormData);
  if (isJson) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(rawBody);
  }
  const response = await fetch(path, opts);
  const text = await response.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!response.ok) {
    // The API mints a fresh token when it restarts, so a tab that was
    // left open across a restart holds a stale one. Refresh it once and
    // replay the request instead of making the user reload the page.
    if (response.status === 403 && !options.__retried
        && !path.startsWith('/api/bootstrap')) {
      try {
        const fresh = await fetch('/api/bootstrap');
        if (fresh.ok) {
          const body = await fresh.json();
          State.token = body.token;
          const retry = { ...options, __retried: true };
          retry.headers = { ...(options.headers || {}) };
          return await api(path, retry);
        }
      } catch { /* fall through to the original error */ }
    }
    const detail = (data && (data.detail || data.message)) || `Request failed (${response.status})`;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}

/* ── toasts ───────────────────────────────────────────────────────────── */

function toast(message, kind = 'info', timeout = 4600) {
  const host = $('#toasts');
  const node = el('div', { class: `toast ${kind}` },
    icon(kind === 'ok' ? 'check' : kind === 'err' ? 'alert' : 'info'),
    el('div', { text: message }));
  host.append(node);
  setTimeout(() => {
    node.style.transition = 'opacity .25s, transform .25s';
    node.style.opacity = '0';
    node.style.transform = 'translateX(20px)';
    setTimeout(() => node.remove(), 260);
  }, timeout);
}

/* ── modal ────────────────────────────────────────────────────────────── */

function modal({ title, body, actions = [], wide = false }) {
  const host = $('#modal-host');
  const backdrop = el('div', { class: 'modal-backdrop' });
  const box = el('div', { class: 'modal' });
  if (wide) box.style.maxWidth = '860px';

  box.append(el('div', { class: 'modal-head' },
    el('h3', { text: title }),
    el('div', { style: 'margin-left:auto' }),
    el('button', { class: 'icon-btn', onclick: close, 'aria-label': 'Close' }, icon('x'))));

  const bodyNode = el('div', { class: 'modal-body' });
  // A string body is escaped, never injected as markup, so a clip title
  // or error message cannot become script.
  if (typeof body === 'string') bodyNode.textContent = body;
  else bodyNode.append(body);
  box.append(bodyNode);

  if (actions.length) {
    const foot = el('div', { class: 'modal-foot' });
    for (const action of actions) {
      foot.append(el('button', {
        class: `btn ${action.class || ''}`,
        onclick: async (event) => {
          const button = event.currentTarget;
          button.disabled = true;
          try {
            const result = await action.onClick?.();
            if (result !== false) close();
          } catch (error) {
            toast(error.message, 'err');
          } finally {
            button.disabled = false;
          }
        },
      }, action.label));
    }
    box.append(foot);
  }

  backdrop.append(box);
  host.append(backdrop);

  function close() {
    backdrop.remove();
    document.removeEventListener('keydown', onKey);
  }
  function onKey(event) { if (event.key === 'Escape') close(); }
  document.addEventListener('keydown', onKey);
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) close(); });

  return { close, body: bodyNode };
}

function confirmDialog(title, message, confirmLabel = 'Confirm') {
  return new Promise((resolve) => {
    modal({
      title,
      body: el('p', { text: message, style: 'color:var(--fg-muted);margin:0' }),
      actions: [
        { label: 'Cancel', onClick: () => { resolve(false); } },
        { label: confirmLabel, class: 'primary', onClick: () => { resolve(true); } },
      ],
    });
  });
}

/* ── formatting ───────────────────────────────────────────────────────── */

function fmt(n) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString();
}

function fmtDuration(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const total = Math.round(Number(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return `${m}m ${s}s`;
  return `${s}s`;
}

function fmtWhen(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  const diff = (Date.now() - date.getTime()) / 1000;
  if (diff < 60) return 'just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function fmtDateTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

function fmtBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let value = Number(bytes);
  let index = 0;
  while (value >= 1024 && index < units.length - 1) { value /= 1024; index += 1; }
  return `${value.toFixed(value < 10 && index > 0 ? 1 : 0)} ${units[index]}`;
}

function scoreColor(score) {
  if (score >= 7) return 'var(--green)';
  if (score >= 4) return 'var(--amber)';
  return 'var(--red)';
}

function emptyState(title, subtitle, iconName = 'film') {
  return el('div', { class: 'empty' },
    icon(iconName),
    el('div', { class: 't', text: title }),
    el('div', { class: 's', text: subtitle }));
}

function statusBadge(status) {
  const map = {
    completed: 'ok', published: 'ok', approved: 'ok', connected: 'ok',
    running: 'cyan', busy: 'cyan', queued: 'info', pending: 'warn',
    awaiting_credentials: 'warn', awaiting_authorization: 'warn',
    failed: 'err', rejected: 'err', error: 'err', not_published: '',
    cancelled: '', stopped: '', idle: '',
  };
  const label = String(status || '').replace(/_/g, ' ');
  return el('span', { class: `badge ${map[status] ?? ''}` },
    el('span', { class: 'dot' }), label);
}

/* ── chart helpers ────────────────────────────────────────────────────── */

function barChart(entries, { color = 'var(--grad-accent)', max = null } = {}) {
  const wrap = el('div', { class: 'chart' });
  const values = entries.map((e) => e.value);
  const top = max ?? Math.max(1, ...values);
  for (const entry of entries) {
    const pct = Math.max(2, (entry.value / top) * 100);
    const fill = el('div', { class: 'bar-fill' });
    fill.style.width = `${pct}%`;
    fill.style.background = entry.color || color;
    wrap.append(el('div', { class: 'bar-row' },
      el('div', { class: 'lbl', text: entry.label, title: entry.label }),
      el('div', { class: 'bar-track' }, fill),
      el('div', { class: 'val', text: fmt(entry.value) })));
  }
  return wrap;
}

function donutChart(entries) {
  const palette = ['#2f6bff', '#22d3ee', '#8b5cf6', '#34d399', '#fbbf24',
                   '#ec4899', '#f87171', '#64748b'];
  const total = entries.reduce((sum, e) => sum + e.value, 0);
  const size = 132;
  const radius = 52;
  const circumference = 2 * Math.PI * radius;

  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('class', 'donut');
  svg.setAttribute('viewBox', '0 0 132 132');

  const bg = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  bg.setAttribute('cx', '66'); bg.setAttribute('cy', '66');
  bg.setAttribute('r', String(radius));
  bg.setAttribute('fill', 'none');
  bg.setAttribute('stroke', 'var(--bg-inset)');
  bg.setAttribute('stroke-width', '16');
  svg.append(bg);

  let offset = 0;
  entries.forEach((entry, index) => {
    if (!total) return;
    const portion = entry.value / total;
    const arc = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    arc.setAttribute('cx', '66'); arc.setAttribute('cy', '66');
    arc.setAttribute('r', String(radius));
    arc.setAttribute('fill', 'none');
    arc.setAttribute('stroke', entry.color || palette[index % palette.length]);
    arc.setAttribute('stroke-width', '16');
    arc.setAttribute('stroke-dasharray',
      `${portion * circumference} ${circumference}`);
    arc.setAttribute('stroke-dashoffset', String(-offset * circumference));
    arc.setAttribute('transform', 'rotate(-90 66 66)');
    arc.append(el('title', { text: `${entry.label}: ${entry.value}` }));
    svg.append(arc);
    offset += portion;
  });

  const label = document.createElementNS('http://www.w3.org/2000/svg', 'text');
  label.setAttribute('x', '66'); label.setAttribute('y', '62');
  label.setAttribute('text-anchor', 'middle');
  label.setAttribute('fill', 'var(--fg-strong)');
  label.setAttribute('font-size', '22');
  label.setAttribute('font-weight', '700');
  label.textContent = String(total);
  svg.append(label);

  const legend = el('div', { class: 'legend' });
  entries.forEach((entry, index) => {
    legend.append(el('div', { class: 'legend-item' },
      el('span', { class: 'legend-swatch',
        style: `background:${entry.color || palette[index % palette.length]}` }),
      el('span', { text: entry.label }),
      el('span', { class: 'n', text: fmt(entry.value) })));
  });

  return el('div', { class: 'donut-wrap' }, svg, legend);
}

/* ── routes ───────────────────────────────────────────────────────────── */

const ROUTES = {};

function registerRoute(name, loader, renderer) {
  ROUTES[name] = { loader, renderer };
}

function navigate(route) {
  State.route = route;
  $$('.nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.route === route);
  });
  location.hash = `#/${route}`;
  render();
}

//: Incremented on every render. A render whose token is no longer the
//: current one has been superseded and must not touch the view. Without
//: this, two overlapping renders (a hash change while a previous load is
//: still in flight, for example) can write to the view out of order and
//: leave the wrong screen on screen.
let renderToken = 0;

async function render() {
  const token = ++renderToken;
  const route = State.route;
  const entry = ROUTES[route] || ROUTES.overview;
  const view = $('#view');
  view.innerHTML = '';
  try {
    const data = await entry.loader();
    if (token !== renderToken) return;   // a newer render won
    view.innerHTML = '';
    view.append(entry.renderer(data));
  } catch (error) {
    if (token !== renderToken) return;
    view.innerHTML = '';
    view.append(el('div', { class: 'card' },
      el('div', { class: 'card-body' },
        el('div', { class: 'note err' },
          el('strong', { text: 'Could not load this view. ' }),
          el('span', { text: error.message }))))); 
  }
}

/* ══ OVERVIEW ═══════════════════════════════════════════════════════════ */

registerRoute('overview',
  async () => {
    const [overview, jobs] = await Promise.all([
      api('/api/overview'),
      api('/api/jobs?limit=12'),
    ]);
    return { overview, jobs };
  },
  ({ overview, jobs }) => {
    const t = overview.totals;
    const frag = document.createDocumentFragment();

    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Overview' }),
        el('div', { class: 'sub', text: 'Live state of your clipping pipeline.' })),
      el('div', { class: 'actions' },
        el('button', {
          class: 'btn primary',
          onclick: () => navigate('new-task'),
        }, icon('upload'), 'New Task'))));

    // stat row
    const stats = el('div', { class: 'grid c4' });
    const tiles = [
      { label: 'Channels monitored', value: fmt(t.channels),
        foot: `${fmt(t.active_channels)} active`, cls: '' },
      { label: 'Episodes monitored', value: fmt(t.episodes_monitored),
        foot: `${fmt(t.episodes_processed)} processed`, cls: 'cyan' },
      { label: 'Videos processed', value: fmt(t.videos_processed),
        foot: `${fmt(t.jobs_completed)} jobs completed`, cls: 'violet' },
      { label: 'Clips generated', value: fmt(t.clips_generated),
        foot: `${fmt(t.ai_scored_clips)} AI scored`, cls: 'green' },
      { label: 'Awaiting approval', value: fmt(t.clips_awaiting_approval),
        foot: `${fmt(t.clips_approved)} approved`, cls: 'amber' },
      { label: 'Clips published', value: fmt(t.clips_published),
        foot: `${fmt(t.publish_failures)} failures`, cls: 'pink' },
      { label: 'Average AI score',
        value: t.average_ai_score === null ? '—' : t.average_ai_score.toFixed(2),
        foot: 'across all generated clips', cls: '' },
      { label: 'Avg processing time',
        value: t.average_processing_seconds === null
          ? '—' : fmtDuration(t.average_processing_seconds),
        foot: `${fmt(t.jobs_failed)} failed jobs`, cls: 'red' },
    ];
    for (const tile of tiles) {
      stats.append(el('div', { class: `stat ${tile.cls}` },
        el('div', { class: 'stat-label', text: tile.label }),
        el('div', { class: 'stat-value', text: tile.value }),
        el('div', { class: 'stat-foot', text: tile.foot })));
    }
    frag.append(stats);

    // health + accounts
    const health = overview.ai_health || {};
    const worker = overview.worker;
    const workerAlive = worker && worker.state &&
      (worker.state === 'idle' || worker.state === 'busy');

    const healthCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'AI provider health' }),
        el('div', { class: 'spacer' }),
        el('button', { class: 'btn sm ghost', onclick: () => navigate('ai') },
          'Configure')),
      el('div', { class: 'card-body' },
        el('div', { class: 'kv' },
          el('dt', { text: 'Provider' }),
          el('dd', {}, health.provider
            ? el('span', { class: 'badge info' }, health.provider)
            : el('span', { class: 'badge warn', text: 'not configured' })),
          el('dt', { text: 'Model' }),
          el('dd', { class: 'mono', text: health.model || '—' }),
          el('dt', { text: 'Chat status' }),
          el('dd', {}, health.chat_ok
            ? el('span', { class: 'badge ok' }, 'reachable')
            : el('span', { class: 'badge err', text: 'unreachable' })),
          el('dt', { text: 'Background worker' }),
          el('dd', {}, workerAlive
            ? el('span', { class: 'badge ok' }, 'running')
            : el('span', { class: 'badge warn', text: 'not running' })),
          el('dt', { text: 'Embeddings' }),
          el('dd', { class: 'mono',
            text: health.embeddings_supported ? 'supported' : 'not available' })),
        health.error
          ? el('div', { class: 'note warn', style: 'margin-top:12px' },
              el('span', { text: health.error }))
          : null,
        el('div', { class: 'note', style: 'margin-top:12px' },
          el('span', { text: health.embedding_note || '' }))));

    const accounts = overview.accounts || {};
    const accountCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Social connections' }),
        el('div', { class: 'spacer' }),
        el('button', { class: 'btn sm ghost', onclick: () => navigate('accounts') },
          'Manage')),
      el('div', { class: 'card-body list' },
        ...['youtube', 'instagram'].map((platform) => {
          const info = accounts[platform] || {};
          return el('div', { class: 'list-item' },
            el('div', { class: 'grow' },
              el('div', { class: 't', text: platform === 'youtube'
                ? 'YouTube Shorts' : 'Instagram Reels' }),
              el('div', { class: 's', text: info.connected
                ? (info.channel_title || info.display_name || 'Connected')
                : (info.message || 'Not connected') })),
            statusBadge(info.status || 'disconnected'));
        })));

    frag.append(el('div', {
      class: 'grid main-side', style: 'margin-top:16px' },
      el('div', { class: 'grid', style: 'gap:16px' },
        recentJobsCard(jobs.jobs || []),
        recentClipsCard(overview.recent_clips || [])),
      el('div', { class: 'grid', style: 'gap:16px' },
        healthCard, accountCard,
        upcomingCard(overview.upcoming_episodes || []))));

    return frag;
  });

function recentJobsCard(jobList) {
  const body = el('div', { class: 'card-body tight' });
  if (!jobList.length) {
    body.append(emptyState('No jobs yet', 'Create a task or upload a video to start processing.', 'play'));
  } else {
    const table = el('table');
    table.append(el('thead', {}, el('tr', {},
      el('th', { text: 'Job' }), el('th', { text: 'Status' }),
      el('th', { text: 'Stage' }), el('th', { class: 'num', text: 'When' }))));
    const tbody = el('tbody');
    for (const job of jobList) {
      tbody.append(el('tr', {},
        el('td', {}, el('div', { class: 'mono', style: 'font-size:12px',
          text: `#${job.id} ${job.kind}` }),
          el('div', { class: 's', style: 'font-size:11px;color:var(--fg-dim)',
            text: (job.source || '').split(/[\\/]/).pop().slice(0, 52) })),
        el('td', {}, statusBadge(job.status)),
        el('td', { style: 'font-size:12px;color:var(--fg-muted)',
          text: job.progress_stage || '—' }),
        el('td', { class: 'num', style: 'font-size:12px;color:var(--fg-muted)',
          text: fmtWhen(job.created_at) })));
    }
    table.append(tbody);
    body.append(el('div', { class: 'table-wrap' }, table));
  }
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h3', { text: 'Recent processing jobs' }),
      el('div', { class: 'spacer' }),
      el('button', { class: 'btn sm ghost', onclick: () => navigate('queue') },
        'View queue')),
    body);
}

function recentClipsCard(clips) {
  const body = el('div', { class: 'card-body tight' });
  if (!clips.length) {
    body.append(emptyState('No clips generated yet',
      'Approved and scored clips will appear here.', 'video'));
  } else {
    const table = el('table');
    table.append(el('thead', {}, el('tr', {},
      el('th', { text: 'Clip' }), el('th', { text: 'Score' }),
      el('th', { text: 'Approval' }), el('th', { text: 'Published' }),
      el('th', { class: 'num', text: '' }))));
    const tbody = el('tbody');
    for (const clip of clips) {
      tbody.append(el('tr', {
        style: 'cursor:pointer',
        onclick: () => { State.selectedClip = clip.id; navigate('editor'); },
      },
        el('td', {}, el('div', { style: 'max-width:320px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
          text: clip.title || `Clip ${clip.index + 1}` })),
        el('td', { class: 'num', style: `font-weight:650;color:${scoreColor(clip.score)}`,
          text: clip.score.toFixed(2) }),
        el('td', {}, statusBadge(clip.approval_status)),
        el('td', {}, statusBadge(clip.publish_status)),
        el('td', { class: 'num' }, el('button', {
          class: 'btn sm',
          onclick: (event) => {
            event.stopPropagation();
            openClipPreview(clip, { onChange: () => render() });
          },
        }, icon('play'), 'Preview'))));
    }
    table.append(tbody);
    body.append(el('div', { class: 'table-wrap' }, table));
  }
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h3', { text: 'Recently generated clips' }),
      el('div', { class: 'spacer' }),
      el('button', { class: 'btn sm ghost', onclick: () => navigate('clips') },
        'All clips')),
    body);
}

function upcomingCard(episodes) {
  const body = el('div', { class: 'card-body tight' });
  if (!episodes.length) {
    body.append(emptyState('No episodes detected',
      'Add a channel to start monitoring for new episodes.', 'link'));
  } else {
    const list = el('div', { class: 'list' });
    for (const episode of episodes) {
      list.append(el('div', { class: 'list-item' },
        el('div', { class: 'grow' },
          el('div', { class: 't', text: episode.title || episode.video_id }),
          el('div', { class: 's', text: `Detected ${fmtWhen(episode.detected_at)}` })),
        statusBadge(episode.processed ? 'completed' : 'pending')));
    }
    body.append(list);
  }
  return el('div', { class: 'card' },
    el('div', { class: 'card-head' }, el('h3', { text: 'Upcoming monitored episodes' })),
    body);
}

/* ══ NEW TASK ════════════════════════════════════════════════════════════ */

const CAPTION_STYLES = [
  ['default', 'Default'], ['clean', 'Clean / Minimal'], ['bold', 'Bold'],
  ['neon', 'Neon'], ['comic', 'Comedy'], ['podcast', 'Podcast'],
  ['cinematic', 'Cinematic'], ['subtle', 'Subtle'],
];

registerRoute('new-task',
  async () => {
    const [tasks, channels] = await Promise.all([
      api('/api/tasks'), api('/api/channels'),
    ]);
    return { tasks: tasks.tasks || [], channels: channels.channels || [] };
  },
  ({ tasks, channels }) => {
    const frag = document.createDocumentFragment();
    const state = {
      source_type: 'upload',
      source_url: '',
      file: null,
      rights_confirmed: false,
    };

    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'New Task' }),
        el('div', { class: 'sub', text: 'Configure a processing task. Saved tasks can be reused.' }))));

    const form = el('div', { class: 'grid main-side' });

    // ── left: settings
    const left = el('div', { class: 'grid', style: 'gap:16px' });

    // ── source card ───────────────────────────────────────────────────
    // The elements are created first so the toggles below can reference
    // them without a temporal-dead-zone error.
    const fileInput = el('input', {
      type: 'file', accept: 'video/*', style: 'display:none',
      onchange: (event) => {
        const file = event.target.files[0];
        if (!file) return;
        state.file = file;
        dropZone.innerHTML = '';
        dropZone.append(icon('check'),
          el('div', { class: 't', text: file.name }),
          el('div', { class: 's', text: fmtBytes(file.size) }));
        dropZone.classList.add('over');
      },
    });

    const dropZone = el('div', { class: 'drop', onclick: () => fileInput.click() },
      icon('upload'),
      el('div', { class: 't', text: 'Choose a video file' }),
      el('div', { class: 's', text: 'MP4, MKV, WebM, MOV, M4V or AVI' }));
    dropZone.append(fileInput);

    const urlInput = el('input', {
      type: 'url', id: 'task-source-url',
      placeholder: 'https://www.youtube.com/watch?v=…',
      oninput: (event) => { state.source_url = event.target.value; },
    });
    const urlField = el('div', { class: 'field', style: 'margin-top:14px;display:none' },
      el('label', { text: 'Source URL' }),
      urlInput,
      el('div', { class: 'hint',
        text: 'Only use videos you have the rights to download and republish.' }));

    const rightsCheckbox = el('input', {
      type: 'checkbox',
      onchange: (event) => { state.rights_confirmed = event.target.checked; },
    });
    const rightsBox = el('div', { class: 'field', style: 'margin-top:14px;display:none' },
      el('label', { class: 'check' },
        rightsCheckbox,
        el('div', {},
          el('div', { class: 'ct', text: 'I hold the rights to this content' }),
          el('div', { class: 'cs',
            text: 'Required before automatic ingestion of a remote channel. A public channel URL is not permission to download and republish.' }))));

    const sourceButtons = el('div', { class: 'grid c2', style: 'gap:9px' });
    const sourceTypes = [
      ['upload', 'Local upload'],
      ['youtube_video', 'YouTube video URL'],
      ['youtube_channel', 'YouTube channel'],
      ['youtube_playlist', 'YouTube playlist'],
    ];

    const sourceCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' },
        el('h3', { text: 'Video source' }),
        el('div', { class: 'spacer' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'fieldset-title', text: 'Source type' }),
        sourceButtons,
        urlField,
        el('div', { class: 'field', style: 'margin-top:14px' },
          el('label', { text: 'Local video file' }),
          dropZone),
        rightsBox));

    // Wire the source-type buttons after every element exists.
    for (const [value, label] of sourceTypes) {
      const button = el('button', {
        class: `btn ${state.source_type === value ? 'primary' : ''}`,
        style: 'justify-content:flex-start',
        dataset: { value },
        onclick: () => {
          state.source_type = value;
          sourceButtons.querySelectorAll('button').forEach((b) => {
            b.classList.toggle('primary', b.dataset.value === value);
          });
          urlField.style.display = value === 'upload' ? 'none' : '';
          dropZone.parentElement.style.display = value === 'upload' ? '' : 'none';
          rightsBox.style.display =
            ['youtube_channel', 'youtube_playlist'].includes(value) ? '' : 'none';
        },
      }, label);
      sourceButtons.append(button);
    }

    // processing settings
    const settingsCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Processing settings' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'form-grid' },
          field('Task name', el('input', { type: 'text', id: 'task-name',
            placeholder: 'Weekly podcast clips' })),
          field('Category', el('select', { id: 'task-category' },
            ...['general', 'podcast', 'comedy', 'tutorial', 'gaming', 'news', 'vlog']
              .map((c) => el('option', { value: c, text: c })))),
          field('Desired clips', el('input', { type: 'number', id: 'task-clips',
            value: '3', min: '1', max: '50' })),
          field('Minimum AI score', el('input', { type: 'number', id: 'task-score',
            value: '0', min: '0', max: '10', step: '0.5' })),
          field('Minimum duration (s)', el('input', { type: 'number', id: 'task-min',
            value: '15', min: '5', max: '600' })),
          field('Maximum duration (s)', el('input', { type: 'number', id: 'task-max',
            value: '90', min: '10', max: '1800' })),
          field('Aspect ratio', el('select', { id: 'task-aspect' },
            ...['9:16', '16:9', '1:1'].map((v) => el('option', { value: v, text: v })))),
          field('Output resolution', el('select', { id: 'task-res' },
            el('option', { value: '1080x1920', text: '1080 x 1920 (vertical)' }),
            el('option', { value: '1080x1080', text: '1080 x 1080 (square)' }),
            el('option', { value: '1920x1080', text: '1920 x 1080 (landscape)' }))),
          field('Caption style', el('select', { id: 'task-caption' },
            ...CAPTION_STYLES.map(([v, l]) => el('option', { value: v, text: l })))),
          field('Language', el('select', { id: 'task-lang' },
            ...['en', 'es', 'fr', 'de', 'hi', 'pt', 'ar', 'ja']
              .map((v) => el('option', { value: v, text: v })))),
          field('Transcription model', el('select', { id: 'task-whisper' },
            ...['tiny', 'base', 'small', 'medium', 'large-v3']
              .map((v) => el('option', { value: v, text: v })))))));

    // automation
    const automationCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Automation' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'grid', style: 'gap:9px' },
          checkRow('task-monitor', 'Monitor channel automatically',
            'Check the source channel for new episodes on a schedule.'),
          checkRow('task-autoproc', 'Automatically process new episodes',
            'Queue each detected episode for processing without manual action.'),
          checkRow('task-approval', 'Require approval before publishing',
            'Keep clips in the review queue until you approve them. Recommended.', true),
          checkRow('task-autopub', 'Automatically publish approved clips',
            'Publish to connected accounts as soon as a clip is approved.')),
        el('div', { class: 'field', style: 'margin-top:14px' },
          el('label', { text: 'Check interval (minutes)' }),
          el('input', { type: 'number', id: 'task-interval', value: '60',
            min: '1', max: '1440' }))));

    left.append(sourceCard, settingsCard, automationCard);

    // ── right: saved tasks + submit
    const right = el('div', { class: 'grid', style: 'gap:16px' });

    const submitCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Submit' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'note',
          text: 'The task is queued and processed by the background worker. You can close the browser; processing continues.' }),
        el('div', { style: 'display:flex;gap:9px;margin-top:14px' },
          el('button', { class: 'btn primary block', onclick: () => submitTask(state, false) },
            icon('play'), 'Save & run'),
          el('button', { class: 'btn', onclick: () => submitTask(state, true) },
            'Save only')),
        el('div', { id: 'task-error', style: 'margin-top:10px' })));

    const savedCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Saved tasks' }),
        el('div', { class: 'spacer' }),
        el('span', { class: 'badge quiet', text: String(tasks.length) })),
      el('div', { class: 'card-body tight' }));
    const savedBody = savedCard.querySelector('.card-body');
    if (!tasks.length) {
      savedBody.append(emptyState('No saved tasks',
        'Tasks you save will be listed here for reuse.', 'film'));
    } else {
      const list = el('div', { class: 'list' });
      for (const task of tasks) {
        list.append(el('div', { class: 'list-item' },
          el('div', { class: 'grow' },
            el('div', { class: 't', text: task.name }),
            el('div', { class: 's',
              text: `${task.source_type} · ${task.num_clips} clips · ${task.aspect_ratio}` })),
          el('button', {
            class: 'btn sm',
            onclick: async () => {
              try {
                await api(`/api/tasks/${task.id}/run`, { method: 'POST' });
                toast('Task queued for processing.', 'ok');
                navigate('queue');
              } catch (error) { toast(error.message, 'err'); }
            },
          }, icon('play'), 'Run'),
          el('button', {
            class: 'icon-btn',
            title: 'Delete task',
            onclick: async () => {
              if (!await confirmDialog('Delete task',
                `Delete "${task.name}"? This cannot be undone.`, 'Delete')) return;
              try {
                await api(`/api/tasks/${task.id}`, { method: 'DELETE' });
                toast('Task deleted.', 'ok');
                render();
              } catch (error) { toast(error.message, 'err'); }
            },
          }, icon('trash'))));
      }
      savedBody.append(list);
    }

    right.append(submitCard, savedCard);

    form.append(left, right);
    frag.append(form);
    return frag;
  });

function field(label, control) {
  return el('div', { class: 'field' }, el('label', { text: label }), control);
}

function checkRow(id, title, subtitle, checked = false) {
  return el('label', { class: 'check' },
    el('input', { type: 'checkbox', id, ...(checked ? { checked: true } : {}) }),
    el('div', {},
      el('div', { class: 'ct', text: title }),
      el('div', { class: 'cs', text: subtitle })));
}

async function submitTask(state, saveOnly) {
  const errorBox = $('#task-error');
  errorBox.innerHTML = '';
  const name = $('#task-name').value.trim();
  if (!name) {
    errorBox.append(el('div', { class: 'note err', text: 'A task name is required.' }));
    return;
  }
  if (state.source_type === 'upload' && !state.file) {
    errorBox.append(el('div', { class: 'note err',
      text: 'Choose a video file, or switch the source type to a URL.' }));
    return;
  }
  if (state.source_type !== 'upload' && !state.source_url.trim()) {
    errorBox.append(el('div', { class: 'note err', text: 'Enter a source URL.' }));
    return;
  }
  const needsRights = ['youtube_channel', 'youtube_playlist'].includes(state.source_type);
  if (needsRights && !state.rights_confirmed) {
    errorBox.append(el('div', { class: 'note err',
      text: 'Confirm you hold the rights to this content before monitoring a remote channel.' }));
    return;
  }

  const payload = {
    name,
    description: '',
    category: $('#task-category').value,
    source_type: state.source_type,
    source_url: state.source_type === 'upload' ? null : state.source_url.trim(),
    channel_id: null,
    num_clips: Number($('#task-clips').value) || 3,
    min_clip_seconds: Number($('#task-min').value) || 15,
    max_clip_seconds: Number($('#task-max').value) || 90,
    aspect_ratio: $('#task-aspect').value,
    resolution: $('#task-res').value,
    caption_style: $('#task-caption').value,
    language: $('#task-lang').value,
    min_score: Number($('#task-score').value) || 0,
    whisper_model: $('#task-whisper').value,
    ai_model: null,
    monitor_enabled: $('#task-monitor').checked,
    monitor_interval_minutes: Number($('#task-interval').value) || 60,
    auto_process_new_episodes: $('#task-autoproc').checked,
    require_approval: $('#task-approval').checked,
    auto_publish: $('#task-autopub').checked,
    rights_confirmed: state.rights_confirmed,
    rights_note: '',
    enabled: true,
  };

  try {
    const result = await api('/api/tasks', { method: 'POST', body: payload });
    const taskId = result.task.id;

    if (state.source_type === 'upload' && state.file) {
      const form = new FormData();
      form.append('file', state.file);
      form.append('task_id', String(taskId));
      await api('/api/videos/upload', { method: 'POST', body: form });
    } else if (!saveOnly) {
      await api(`/api/tasks/${taskId}/run`, { method: 'POST' });
    }

    toast(saveOnly ? 'Task saved.' : 'Task created and queued.', 'ok');
    navigate(saveOnly ? 'new-task' : 'queue');
  } catch (error) {
    errorBox.append(el('div', { class: 'note err', text: error.message }));
  }
}

/* ══ CHANNEL MONITOR ═════════════════════════════════════════════════════ */

registerRoute('channels',
  async () => {
    const [channels, episodes] = await Promise.all([
      api('/api/channels'), api('/api/episodes?limit=60'),
    ]);
    return { channels: channels.channels || [], episodes: episodes.episodes || [] };
  },
  ({ channels, episodes }) => {
    const frag = document.createDocumentFragment();
    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Channel Monitor' }),
        el('div', { class: 'sub',
          text: 'Persistent monitoring for new episodes on your YouTube channels.' })),
      el('div', { class: 'actions' },
        el('button', { class: 'btn primary', onclick: addChannel },
          icon('link'), 'Add channel'))));

    if (!channels.length) {
      frag.append(el('div', { class: 'card' },
        el('div', { class: 'card-body' },
          emptyState('No channels monitored',
            'Add a YouTube channel URL to detect new episodes automatically. The background worker checks each channel on its own schedule, even when the browser is closed.', 'link'))));
    } else {
      const grid = el('div', { class: 'grid c2' });
      for (const channel of channels) {
        const card = el('div', { class: 'card' },
          el('div', { class: 'card-head' },
            el('div', { style: 'min-width:0' },
              el('h3', { text: channel.name, style: 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis' }),
              el('div', { class: 'card-sub mono', text: channel.channel_id })),
            el('div', { class: 'spacer' }),
            statusBadge(channel.paused ? 'paused' : channel.monitoring ? 'connected' : 'not_published')),
          el('div', { class: 'card-body' },
            el('div', { class: 'kv' },
              el('dt', { text: 'Handle' }), el('dd', { text: channel.handle || '—' }),
              el('dt', { text: 'Channel URL' }),
              el('dd', {}, el('a', {
                href: channel.channel_url, target: '_blank', rel: 'noopener',
                style: 'font-size:12px', text: channel.channel_url || '—',
              })),
              el('dt', { text: 'Episodes found' }), el('dd', { text: fmt(channel.episodes) }),
              el('dt', { text: 'Processed' }), el('dd', { text: fmt(channel.processed) }),
              el('dt', { text: 'Last checked' }), el('dd', { text: fmtWhen(channel.last_checked_at) }),
              el('dt', { text: 'Next check' }), el('dd', { text: channel.next_check_at ? fmtDateTime(channel.next_check_at) : 'paused' }),
              el('dt', { text: 'Interval' }), el('dd', { text: `${channel.check_interval_minutes} min` })),
            channel.last_error
              ? el('div', { class: 'note err', style: 'margin-top:12px' },
                  el('strong', { text: 'Last error: ' }),
                  el('span', { text: channel.last_error }))
              : null,
            el('div', { style: 'display:flex;gap:8px;margin-top:14px;flex-wrap:wrap' },
              el('button', { class: 'btn sm', onclick: () => checkChannel(channel.id) },
                icon('refresh'), 'Check now'),
              el('button', {
                class: 'btn sm',
                onclick: async () => {
                  try {
                    await api(`/api/channels/${channel.id}`, {
                      method: 'PATCH',
                      body: { paused: !channel.paused },
                    });
                    toast(channel.paused ? 'Monitoring resumed.' : 'Monitoring paused.', 'ok');
                    render();
                  } catch (error) { toast(error.message, 'err'); }
                },
              }, icon('pause'), channel.paused ? 'Resume' : 'Pause'),
              el('button', {
                class: 'btn sm',
                onclick: async () => {
                  const value = prompt('Check interval in minutes', String(channel.check_interval_minutes));
                  if (!value) return;
                  try {
                    await api(`/api/channels/${channel.id}`, {
                      method: 'PATCH',
                      body: { check_interval_minutes: Number(value) },
                    });
                    toast('Interval updated.', 'ok');
                    render();
                  } catch (error) { toast(error.message, 'err'); }
                },
              }, 'Interval'),
              el('button', {
                class: 'btn sm danger',
                onclick: async () => {
                  if (!await confirmDialog('Remove channel',
                    `Stop monitoring "${channel.name}"?`, 'Remove')) return;
                  try {
                    await api(`/api/channels/${channel.id}`, { method: 'DELETE' });
                    toast('Channel removed.', 'ok');
                    render();
                  } catch (error) { toast(error.message, 'err'); }
                },
              }, icon('trash'), 'Remove'))));
        grid.append(card);
      }
      frag.append(grid);
    }

    // episodes table
    const body = el('div', { class: 'card-body tight' });
    if (!episodes.length) {
      body.append(emptyState('No episodes detected yet',
        'Detected episodes appear here with their processing state.', 'film'));
    } else {
      const table = el('table');
      table.append(el('thead', {}, el('tr', {},
        el('th', { text: 'Episode' }), el('th', { text: 'Video ID' }),
        el('th', { text: 'Published' }), el('th', { text: 'Detected' }),
        el('th', { text: 'Processing rights' }), el('th', { text: 'Status' }),
        el('th', { class: 'num', text: '' }))));
      const tbody = el('tbody');
      for (const episode of episodes) {
        const state = episode.authorization_state || 'awaiting_authorization';
        const titleCell = el('td', {},
          el('div', { style: 'display:flex;align-items:center;gap:9px' },
            episode.thumbnail_url
              ? el('img', {
                  src: episode.thumbnail_url,
                  alt: '',
                  loading: 'lazy',
                  style: 'width:44px;height:26px;object-fit:cover;border-radius:4px;flex:none',
                  onerror: (event) => { event.target.remove(); },
                })
              : null,
            el('div', { style: 'max-width:300px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
              text: episode.title || 'Untitled episode' })));
        tbody.append(el('tr', {},
          titleCell,
          el('td', { class: 'mono', style: 'font-size:12px;color:var(--fg-muted)',
            text: episode.video_id }),
          el('td', { style: 'font-size:12px;color:var(--fg-muted)',
            text: fmtWhen(episode.published_at) }),
          el('td', { style: 'font-size:12px;color:var(--fg-muted)',
            text: fmtWhen(episode.detected_at) }),
          el('td', {}, authorizationBadge(state)),
          el('td', {}, statusBadge(episode.processed_at ? 'completed' : 'pending')),
          el('td', { class: 'num' },
            el('div', { style: 'display:flex;gap:6px;justify-content:flex-end' },
              el('button', {
                class: 'btn sm',
                onclick: async () => {
                  const note = prompt(
                    'Why are you authorised to process this video?\n' +
                    '(You own it, you licensed it, or you have permission.)',
                    episode.authorization_note || '');
                  if (note === null) return;
                  await setEpisodeAuthorization(episode.id, 'authorized', note);
                },
              }, icon('check'), 'Authorise'),
              el('button', {
                class: 'btn sm ghost',
                onclick: async () => {
                  await setEpisodeAuthorization(episode.id, 'not_authorized',
                    episode.authorization_note || '');
                },
              }, 'Not authorised'),
              el('a', {
                class: 'btn sm ghost',
                href: episode.url, target: '_blank', rel: 'noopener',
              }, 'Open')))));
      }
      table.append(tbody);
      body.append(el('div', { class: 'table-wrap' }, table));
    }
    frag.append(el('div', { class: 'card', style: 'margin-top:16px' },
      el('div', { class: 'card-head' },
        el('h3', { text: 'Detected episodes' }),
        el('div', { class: 'spacer' }),
        el('span', { class: 'badge warn',
          text: 'Detected ≠ authorised to publish' })),
      body));

    return frag;
  });

/**
 * The badge for an episode's processing-rights state.
 *
 * "Awaiting an authorised source" is the honest state for a video that
 * was detected on a public channel but that the user has not confirmed
 * they may process. It is deliberately not shown as an error.
 */
function authorizationBadge(state) {
  if (state === 'authorized') {
    return el('span', { class: 'badge ok', text: 'Authorised source' });
  }
  if (state === 'not_authorized') {
    return el('span', { class: 'badge err', text: 'Not authorised' });
  }
  return el('span', { class: 'badge warn',
    text: 'Awaiting an authorised source' });
}

async function setEpisodeAuthorization(episodeId, state, note) {
  try {
    await api(`/api/episodes/${episodeId}`, {
      method: 'PATCH',
      body: { authorization_state: state, note: note || '' },
    });
    toast(state === 'authorized'
      ? 'Episode marked as authorised.'
      : 'Episode marked as not authorised.', 'ok');
    render();
  } catch (error) { toast(error.message, 'err'); }
}

function addChannel() {
  const input = el('input', { type: 'url', placeholder: 'https://www.youtube.com/@channel' });
  const errorBox = el('div', { style: 'margin-top:10px' });
  const dialog = modal({
    title: 'Add channel to monitor',
    body: el('div', {},
      el('div', { class: 'field' },
        el('label', { text: 'YouTube channel URL or channel id' }), input,
        el('div', { class: 'hint',
          text: 'Detection uses the official YouTube feed and Data API, not page scraping. Downloading and republishing a channel’s videos still requires that you hold the rights.' })),
      errorBox),
    actions: [
      { label: 'Cancel' },
      { label: 'Add channel', class: 'primary', onClick: async () => {
        const url = input.value.trim();
        if (!url) { errorBox.append(el('div', { class: 'note err', text: 'Enter a channel URL.' })); return false; }
        try {
          await api('/api/channels', { method: 'POST', body: { url, check_interval_minutes: 60 } });
          toast('Channel added and monitoring started.', 'ok');
          render();
        } catch (error) {
          errorBox.append(el('div', { class: 'note err', text: error.message }));
          return false;
        }
      }},
    ],
  });
  input.focus();
}

async function checkChannel(channelId) {
  try {
    const result = await api(`/api/channels/${channelId}/check`, { method: 'POST' });
    toast(`Checked: ${result.new_episodes} new episode(s).`, 'ok');
    render();
  } catch (error) {
    toast(error.message, 'err');
    render();
  }
}

/* ══ VIDEO LIBRARY ═══════════════════════════════════════════════════════ */

registerRoute('library',
  async () => {
    const [videos, tasks] = await Promise.all([
      api('/api/videos'), api('/api/tasks'),
    ]);
    return { videos: videos.videos || [], tasks: tasks.tasks || [] };
  },
  ({ videos, tasks }) => {
    const frag = document.createDocumentFragment();
    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Video Library' }),
        el('div', { class: 'sub', text: 'Every source video the platform has ingested.' })),
      el('div', { class: 'actions' },
        el('button', { class: 'btn primary', onclick: uploadVideo }, icon('upload'), 'Upload video'))));

    const body = el('div', { class: 'card-body tight' });
    if (!videos.length) {
      body.append(emptyState('No videos yet',
        'Upload a local video or run a task to populate the library.', 'film'));
    } else {
      const table = el('table');
      table.append(el('thead', {}, el('tr', {},
        el('th', { text: 'Title' }), el('th', { text: 'Source' }),
        el('th', { class: 'num', text: 'Size' }),
        el('th', { class: 'num', text: 'Duration' }),
        el('th', { text: 'Added' }))));
      const tbody = el('tbody');
      for (const video of videos) {
        tbody.append(el('tr', {},
          el('td', {}, el('div', { style: 'max-width:380px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
            text: video.title || 'Untitled' }),
            el('div', { class: 'mono', style: 'font-size:11px;color:var(--fg-dim)',
              text: video.project_id ? `project ${video.project_id}` : '' })),
          el('td', {}, el('span', { class: 'badge', text: video.source_type })),
          el('td', { class: 'num', style: 'font-size:12px', text: fmtBytes(video.size_bytes) }),
          el('td', { class: 'num', style: 'font-size:12px', text: fmtDuration(video.duration_seconds) }),
          el('td', { style: 'font-size:12px;color:var(--fg-muted)', text: fmtWhen(video.created_at) })));
      }
      table.append(tbody);
      body.append(el('div', { class: 'table-wrap' }, table));
    }
    frag.append(el('div', { class: 'card' }, body));

    // tasks
    const taskBody = el('div', { class: 'card-body tight' });
    if (!tasks.length) {
      taskBody.append(emptyState('No saved tasks', 'Create a task from the New Task page.', 'film'));
    } else {
      const table = el('table');
      table.append(el('thead', {}, el('tr', {},
        el('th', { text: 'Task' }), el('th', { text: 'Source' }),
        el('th', { text: 'Automation' }), el('th', { text: 'Rights' }),
        el('th', { class: 'num', text: '' }))));
      const tbody = el('tbody');
      for (const task of tasks) {
        tbody.append(el('tr', {},
          el('td', {}, el('div', { text: task.name }),
            el('div', { class: 's', style: 'font-size:11px;color:var(--fg-dim)',
              text: task.description || task.category })),
          el('td', {}, el('span', { class: 'badge', text: task.source_type })),
          el('td', { style: 'font-size:12px;color:var(--fg-muted)',
            text: `${task.monitor_enabled ? 'Monitoring' : 'Manual'}${task.auto_process_new_episodes ? ' · auto-process' : ''}` }),
          el('td', {}, statusBadge(task.rights_confirmed ? 'approved' : 'pending')),
          el('td', { class: 'num' }, el('button', {
            class: 'btn sm',
            onclick: async () => {
              try {
                await api(`/api/tasks/${task.id}/run`, { method: 'POST' });
                toast('Task queued.', 'ok');
                navigate('queue');
              } catch (error) { toast(error.message, 'err'); }
            },
          }, icon('play'), 'Run'))));
      }
      table.append(tbody);
      taskBody.append(el('div', { class: 'table-wrap' }, table));
    }
    frag.append(el('div', { class: 'card', style: 'margin-top:16px' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Saved task configurations' })),
      taskBody));

    return frag;
  });

function uploadVideo() {
  const fileInput = el('input', { type: 'file', accept: 'video/*' });
  const name = el('div', { style: 'font-weight:600' });
  const detail = el('div', { style: 'font-size:12px;color:var(--fg-dim)' });
  fileInput.addEventListener('change', () => {
    const file = fileInput.files[0];
    if (!file) return;
    name.textContent = file.name;
    detail.textContent = fmtBytes(file.size);
  });
  modal({
    title: 'Upload a video',
    body: el('div', {},
      el('div', { class: 'field' },
        el('label', { text: 'Video file' }),
        el('div', { class: 'drop', onclick: () => fileInput.click() },
          icon('upload'),
          el('div', { class: 't', text: 'Choose a file' }),
          el('div', { class: 's', text: 'MP4, MKV, WebM, MOV, M4V or AVI' })),
        fileInput),
      el('div', { style: 'margin-top:12px' }, name, detail)),
    actions: [
      { label: 'Cancel' },
      { label: 'Upload & process', class: 'primary', onClick: async () => {
        const file = fileInput.files[0];
        if (!file) { toast('Choose a file first.', 'err'); return false; }
        const form = new FormData();
        form.append('file', file);
        try {
          const result = await api('/api/videos/upload', { method: 'POST', body: form });
          toast('Upload received. Processing has started.', 'ok');
          navigate('queue');
        } catch (error) {
          toast(error.message, 'err');
          return false;
        }
      }},
    ],
  });
}

/* ══ PROCESSING QUEUE ════════════════════════════════════════════════════ */

registerRoute('queue',
  async () => api('/api/jobs?limit=100'),
  (data) => {
    const frag = document.createDocumentFragment();
    const counts = data.counts || {};
    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Processing Queue' }),
        el('div', { class: 'sub',
          text: 'Jobs run in a separate worker process and persist across restarts.' })),
      el('div', { class: 'actions' },
        el('button', { class: 'btn', onclick: () => render() }, icon('refresh'), 'Refresh'))));

    const tiles = el('div', { class: 'grid c5' });
    const order = [['queued', 'Queued', ''], ['running', 'Running', 'cyan'],
                   ['completed', 'Completed', 'green'], ['failed', 'Failed', 'red'],
                   ['cancelled', 'Cancelled', '']];
    for (const [key, label, cls] of order) {
      tiles.append(el('div', { class: `stat ${cls}` },
        el('div', { class: 'stat-label', text: label }),
        el('div', { class: 'stat-value', text: fmt(counts[key] || 0) })));
    }
    frag.append(tiles);

    const jobs = data.jobs || [];
    const body = el('div', { class: 'card-body tight' });
    if (!jobs.length) {
      body.append(emptyState('The queue is empty',
        'Upload a video or run a task to enqueue processing work.', 'play'));
    } else {
      const table = el('table');
      table.append(el('thead', {}, el('tr', {},
        el('th', { text: 'Job' }), el('th', { text: 'Status' }),
        el('th', { text: 'Progress' }), el('th', { class: 'num', text: 'Attempts' }),
        el('th', { class: 'num', text: 'Duration' }), el('th', { class: 'num', text: '' }))));
      const tbody = el('tbody');
      for (const job of jobs) {
        const progressBar = el('div', { class: 'progress', style: 'min-width:120px' });
        const total = job.progress_total || 0;
        const pct = total ? Math.round((job.progress_done / total) * 100) : 0;
        const fill = el('div');
        fill.style.width = job.status === 'completed' ? '100%' : `${pct}%`;
        progressBar.append(fill);

        tbody.append(el('tr', {},
          el('td', {}, el('div', { style: 'font-weight:600',
            text: `#${job.id} ${job.kind}` }),
            el('div', { class: 'mono', style: 'font-size:11px;color:var(--fg-dim)',
              text: (job.source || '').split(/[\\/]/).pop().slice(0, 60) }),
            job.error
              ? el('div', { style: 'font-size:11px;color:var(--red);margin-top:3px',
                  text: job.error.slice(0, 120) })
              : null),
          el('td', {}, statusBadge(job.status)),
          el('td', {}, progressBar,
            el('div', { style: 'font-size:11px;color:var(--fg-dim);margin-top:4px',
              text: job.progress_stage || '—' })),
          el('td', { class: 'num', style: 'font-size:12px',
            text: `${job.attempts}/${job.max_attempts}` }),
          el('td', { class: 'num', style: 'font-size:12px;color:var(--fg-muted)',
            text: job.duration_seconds ? fmtDuration(job.duration_seconds) : '—' }),
          el('td', { class: 'num' }, el('div', { class: 'row-actions' },
            job.status === 'running'
              ? el('button', {
                  class: 'btn sm danger',
                  onclick: async () => {
                    try {
                      await api(`/api/jobs/${job.id}/cancel`, { method: 'POST' });
                      toast('Cancellation requested.', 'ok');
                      render();
                    } catch (error) { toast(error.message, 'err'); }
                  },
                }, 'Cancel')
              : el('button', {
                  class: 'btn sm',
                  onclick: async () => {
                    try {
                      await api(`/api/jobs/${job.id}/retry`, { method: 'POST' });
                      toast('Job requeued.', 'ok');
                      render();
                    } catch (error) { toast(error.message, 'err'); }
                  },
                }, icon('refresh'), 'Retry')))));
      }
      table.append(tbody);
      body.append(el('div', { class: 'table-wrap' }, table));
    }
    frag.append(el('div', { class: 'card', style: 'margin-top:16px' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Job history' })),
      body));
    return frag;
  });

/* ══ GENERATED CLIPS ═════════════════════════════════════════════════════ */

// The Clip Library route itself is defined further down, next to the
// player it uses. This helper renders the compact poster card that the
// overview and the queue screens share.

function clipCard(clip) {
  const thumb = el('div', { class: 'clip-thumb' });
  if (clip.poster_path) {
    thumb.append(el('img', {
      src: `/media/clip/${clip.id}/poster`,
      alt: clip.title || 'Clip poster',
      loading: 'lazy',
      onerror: (event) => { event.target.style.display = 'none'; },
    }));
  } else {
    thumb.append(el('div', { class: 'empty', text: 'No poster' }));
  }
  thumb.append(el('div', { class: 'clip-score',
    style: `color:${scoreColor(clip.score)}`, text: clip.score.toFixed(1) }));
  thumb.append(el('div', { class: 'clip-dur', text: fmtDuration(clip.duration_seconds) }));

  const card = el('div', { class: 'clip-card', onclick: () => {
    State.selectedClip = clip.id;
    navigate('editor');
  }},
    thumb,
    el('div', { class: 'clip-body' },
      el('div', { class: 't', text: clip.title || `Clip ${clip.index + 1}` }),
      el('div', { class: 'clip-meta' },
        statusBadge(clip.approval_status),
        clip.ai_adjustment !== null && clip.ai_adjustment !== undefined
          ? el('span', { class: 'badge violet',
              text: `AI ${clip.ai_adjustment >= 0 ? '+' : ''}${Number(clip.ai_adjustment).toFixed(2)}` })
          : null,
        clip.publish_status === 'published'
          ? el('span', { class: 'badge ok', text: clip.published_platform || 'published' })
          : null)));

  return card;
}

async function batchApprove(clipIds, action) {
  if (!clipIds.length) return;
  try {
    const result = await api('/api/clips/batch', {
      method: 'POST',
      body: { clip_ids: clipIds, action },
    });
    toast(`${result.count} clip(s) ${action === 'approve' ? 'approved' : 'rejected'}.`, 'ok');
    render();
  } catch (error) { toast(error.message, 'err'); }
}

/* ══ CLIP PLAYER ═════════════════════════════════════════════════════════ */

/** Format a number of seconds as a clock value, e.g. 83 -> "1:23". */
function fmtClock(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
  const total = Math.floor(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/**
 * A clip player with full transport controls.
 *
 * The video is served by the application's own media route, which
 * implements HTTP byte ranges, so seeking inside the clip works rather
 * than requiring the whole file to download first.
 */
function clipPlayer(clip) {
  const wrap = el('div', { class: 'player' });
  const stage = el('div', { class: 'player-stage' });
  const video = el('video', {
    src: `/media/clip/${clip.id}`,
    poster: `/media/clip/${clip.id}/poster`,
    preload: 'metadata',
    playsinline: 'playsinline',
  });
  const spinner = el('div', { class: 'player-overlay' },
    el('div', { class: 'spinner' }));
  const errorBox = el('div', { class: 'player-overlay player-error' },
    el('div', { class: 'player-error-body' },
      icon('alert'),
      el('div', { class: 't', text: 'This clip could not be loaded' }),
      el('div', { class: 's', text: 'The rendered file may be missing from disk.' })));
  errorBox.style.display = 'none';
  stage.append(video, spinner, errorBox);

  const playBtn = el('button', { class: 'player-btn', type: 'button',
    'aria-label': 'Play' }, icon('play'));
  const timeline = el('input', { type: 'range', class: 'player-timeline',
    min: '0', max: '1000', step: '1', value: '0', 'aria-label': 'Timeline' });
  const currentLabel = el('span', { class: 'player-time', text: '0:00' });
  const totalLabel = el('span', { class: 'player-time dim', text: '0:00' });
  const volume = el('input', { type: 'range', class: 'player-volume',
    min: '0', max: '1', step: '0.05', value: '1', 'aria-label': 'Volume' });
  const speed = el('select', { class: 'player-speed', 'aria-label': 'Playback speed' },
    ...[0.5, 0.75, 1, 1.25, 1.5, 2].map((rate) => el('option', {
      value: String(rate), text: `${rate}×`,
      ...(rate === 1 ? { selected: true } : {}),
    })));
  const fullBtn = el('button', { class: 'player-btn', type: 'button',
    'aria-label': 'Fullscreen' }, icon('expand'));

  const controls = el('div', { class: 'player-controls' },
    el('div', { class: 'player-row' },
      playBtn,
      el('span', { class: 'player-time-group' }, currentLabel,
        el('span', { class: 'dim', text: ' / ' }), totalLabel)),
    timeline,
    el('div', { class: 'player-row' },
      el('span', { class: 'player-volume-wrap' }, icon('volume'), volume),
      el('span', { class: 'spacer' }),
      speed,
      fullBtn));

  wrap.append(stage, controls);

  let scrubbing = false;

  const setPlayIcon = (playing) => {
    playBtn.innerHTML = '';
    playBtn.append(icon(playing ? 'pause' : 'play'));
    playBtn.setAttribute('aria-label', playing ? 'Pause' : 'Play');
  };

  const showError = (message) => {
    errorBox.style.display = 'flex';
    const body = errorBox.querySelector('.player-error-body');
    if (body && message) {
      const sub = body.querySelector('.s');
      if (sub) sub.textContent = message;
    }
    spinner.style.display = 'none';
  };

  video.addEventListener('loadedmetadata', () => {
    totalLabel.textContent = fmtClock(video.duration);
    timeline.max = String(Math.max(1, Math.round(video.duration * 100)));
    spinner.style.display = 'none';
  });
  video.addEventListener('durationchange', () => {
    if (Number.isFinite(video.duration)) {
      totalLabel.textContent = fmtClock(video.duration);
      timeline.max = String(Math.max(1, Math.round(video.duration * 100)));
    }
  });
  video.addEventListener('waiting', () => { spinner.style.display = 'flex'; });
  video.addEventListener('playing', () => {
    spinner.style.display = 'none';
    setPlayIcon(true);
  });
  video.addEventListener('pause', () => setPlayIcon(false));
  video.addEventListener('ended', () => setPlayIcon(false));
  video.addEventListener('error', () => {
    showError('The rendered file may be missing from disk.');
  });
  video.addEventListener('timeupdate', () => {
    if (scrubbing) return;
    currentLabel.textContent = fmtClock(video.currentTime);
    const duration = Number.isFinite(video.duration) && video.duration > 0
      ? video.duration : 0;
    timeline.value = String(Math.round(video.currentTime * 100));
    const percent = duration ? (video.currentTime / duration) * 100 : 0;
    timeline.style.setProperty('--played', `${percent}%`);
  });

  playBtn.addEventListener('click', () => {
    if (video.paused) video.play().catch(() => showError('Playback was blocked by the browser.'));
    else video.pause();
  });
  video.addEventListener('click', () => {
    if (video.paused) video.play().catch(() => {});
    else video.pause();
  });
  timeline.addEventListener('pointerdown', () => { scrubbing = true; });
  timeline.addEventListener('pointerup', () => { scrubbing = false; });
  timeline.addEventListener('input', () => {
    const duration = Number.isFinite(video.duration) ? video.duration : 0;
    if (!duration) return;
    const seconds = (Number(timeline.value) / 100);
    video.currentTime = seconds;
    currentLabel.textContent = fmtClock(seconds);
    timeline.style.setProperty('--played',
      `${(seconds / duration) * 100}%`);
  });
  volume.addEventListener('input', () => {
    video.volume = Number(volume.value);
    video.muted = video.volume === 0;
  });
  speed.addEventListener('change', () => {
    video.playbackRate = Number(speed.value);
  });
  fullBtn.addEventListener('click', () => {
    const target = document.fullscreenElement ? document : stage;
    if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
    else if (target.requestFullscreen) target.requestFullscreen().catch(() => {});
  });

  return wrap;
}

/* ══ CLIP LIBRARY ═══════════════════════════════════════════════════════ */

const CLIP_FILTERS = [
  { key: 'all', label: 'All Clips' },
  { key: 'pending', label: 'Pending Review' },
  { key: 'approved', label: 'Approved' },
  { key: 'rejected', label: 'Rejected' },
  { key: 'published', label: 'Published' },
];

const CLIP_SORTS = [
  { key: 'score', label: 'Highest Score' },
  { key: 'newest', label: 'Newest' },
  { key: 'oldest', label: 'Oldest' },
  { key: 'longest', label: 'Longest' },
  { key: 'shortest', label: 'Shortest' },
];

State.clipFilter = State.clipFilter || 'all';
State.clipSort = State.clipSort || 'score';
State.clipSearch = State.clipSearch || '';

/**
 * Render the named signals as a compact breakdown.
 *
 * Only signals that were actually measured for this clip are shown. The
 * weight registry lists every signal the system knows about, so using it
 * as the row list would draw eight empty bars for a clip that has no
 * signal data at all -- for example a clip rendered before the V2
 * intelligence layer existed.
 */
function signalBreakdown(clip) {
  const signals = clip.signals || {};
  const labels = clip.signal_labels || {};
  const names = Object.keys(signals);
  if (!names.length) return null;

  const rows = el('div', { class: 'signal-list' });
  for (const name of names) {
    const value = Number(signals[name]);
    const pct = Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0;
    const fill = el('div', { class: 'signal-fill' });
    fill.style.width = `${pct}%`;
    rows.append(el('div', { class: 'signal-row' },
      el('span', { class: 'signal-name', text: labels[name] || name }),
      el('span', { class: 'signal-track' }, fill),
      el('span', { class: 'signal-value', text: Number.isFinite(value)
        ? value.toFixed(0) : '—' })));
  }
  return rows;
}

/** The poster image, with a designed fallback when there is none. */
function clipPoster(clip, { className = '' } = {}) {
  const frame = el('div', { class: `clip-poster ${className}`.trim() });
  if (clip.file_path) {
    const img = el('img', {
      src: `/media/clip/${clip.id}/poster`,
      alt: clip.title || 'Clip poster',
      loading: 'lazy',
    });
    img.addEventListener('error', () => {
      img.remove();
      frame.append(el('div', { class: 'clip-poster-fallback' },
        icon('video'),
        el('span', { text: 'No poster' })));
    });
    frame.append(img);
  } else {
    frame.append(el('div', { class: 'clip-poster-fallback' },
      icon('video'), el('span', { text: 'Not rendered' })));
  }
  return frame;
}

/** Open the full clip preview: player on the left, detail on the right. */
async function openClipPreview(clip, { onChange } = {}) {
  let detail;
  try {
    detail = await api(`/api/clips/${clip.id}`);
  } catch (error) {
    toast(error.message, 'err');
    return;
  }
  const full = detail.clip;

  const scoreLabel = el('div', { class: 'preview-score' },
    el('span', { class: 'preview-score-value',
      style: `color:${scoreColor(full.score)}`,
      text: Number(full.score ?? 0).toFixed(1) }),
    el('span', { class: 'preview-score-caption' },
      el('strong', { text: 'Estimated engagement' }),
      el('span', { text: ` · ${full.score_kind || 'estimated'}` })));

  const signals = signalBreakdown(full);

  const explanation = full.explanation || full.reason || '';

  const right = el('div', { class: 'preview-right' },
    el('h3', { class: 'preview-title', text: full.title || `Clip ${full.index + 1}` }),
    el('div', { class: 'preview-sub', text: full.source_video_title
      || `Source video #${full.video_id ?? '—'}` }),
    scoreLabel,
    signals ? el('div', { class: 'preview-block' },
      el('div', { class: 'fieldset-title', text: 'Why this moment was selected' }),
      signals) : null,
    explanation ? el('div', { class: 'preview-block' },
      el('div', { class: 'fieldset-title', text: 'Explanation' }),
      el('div', { class: 'note', text: explanation })) : null,
    full.transcript ? el('div', { class: 'preview-block' },
      el('div', { class: 'fieldset-title', text: 'Transcript excerpt' }),
      el('div', { class: 'note mono transcript', text: full.transcript })) : null,
    el('div', { class: 'preview-block' },
      el('div', { class: 'fieldset-title', text: 'Moment' }),
      el('div', { class: 'kv' },
        el('dt', { text: 'Start' }),
        el('dd', { class: 'mono', text: `${Number(full.start_seconds ?? 0).toFixed(2)}s` }),
        el('dt', { text: 'End' }),
        el('dd', { class: 'mono', text: `${Number(full.end_seconds ?? 0).toFixed(2)}s` }),
        el('dt', { text: 'Duration' }),
        el('dd', { text: fmtDuration(full.duration_seconds) }),
        el('dt', { text: 'Resolution' }),
        el('dd', { text: full.resolution || '—' }),
        el('dt', { text: 'Aspect ratio' }),
        el('dd', { text: full.aspect_ratio || '—' }),
        el('dt', { text: 'Created' }),
        el('dd', { text: fmtDateTime(full.created_at) }))),
    full.description ? el('div', { class: 'preview-block' },
      el('div', { class: 'fieldset-title', text: 'Description' }),
      el('div', { class: 'note', text: full.description })) : null,
    full.hashtags ? el('div', { class: 'preview-block' },
      el('div', { class: 'fieldset-title', text: 'Hashtags' }),
      el('div', { class: 'tag-row' },
        ...String(full.hashtags).split(/\s+/).filter(Boolean)
          .map((tag) => el('span', { class: 'tag', text: tag })))) : null,
    full.suggested_hashtags && !full.hashtags
      ? el('div', { class: 'preview-block' },
          el('div', { class: 'fieldset-title', text: 'Suggested hashtags' }),
          el('div', { class: 'tag-row' },
            ...String(full.suggested_hashtags).split(/\s+/).filter(Boolean)
              .map((tag) => el('span', { class: 'tag', text: tag })))) : null);

  const statusSlot = el('div', { class: 'preview-status' });
  const refreshStatus = (status) => {
    statusSlot.innerHTML = '';
    statusSlot.append(statusBadge(status));
  };
  refreshStatus(full.approval_status);

  const setApproval = async (status) => {
    try {
      await api(`/api/clips/${full.id}`, {
        method: 'PATCH', body: { approval_status: status },
      });
      full.approval_status = status;
      refreshStatus(status);
      toast(`Clip ${status}.`, 'ok');
      if (onChange) onChange(full);
    } catch (error) { toast(error.message, 'err'); }
  };

  const actions = el('div', { class: 'preview-actions' },
    el('button', { class: 'btn success', onclick: () => setApproval('approved') },
      icon('check'), 'Approve'),
    el('button', { class: 'btn danger', onclick: () => setApproval('rejected') },
      icon('x'), 'Reject'),
    el('button', { class: 'btn', onclick: async () => {
      if (!await confirmDialog('Regenerate clip',
        'Render this clip again with the current caption style?', 'Regenerate')) return;
      toast('Regenerating…', 'info');
      try {
        await api(`/api/clips/${full.id}`, { method: 'PATCH', body: { rerender: true } });
        toast('Clip regenerated.', 'ok');
        if (onChange) onChange(full);
      } catch (error) { toast(error.message, 'err'); }
    } }, icon('refresh'), 'Regenerate'),
    el('a', { class: 'btn', href: `/api/clips/${full.id}/download` },
      icon('download'), 'Download'),
    statusSlot);

  const body = el('div', { class: 'preview-grid' },
    el('div', { class: 'preview-left' }, clipPlayer(full)),
    right);

  body.append(actions);
  modal({ title: full.title || 'Clip preview', body, wide: true });
}

/** A single card in the clip library. */
function libraryCard(clip) {
  const score = Number(clip.score ?? 0);
  const card = el('div', { class: 'lib-card' },
    clipPoster(clip, { className: 'lib-poster' }),
    el('div', { class: 'lib-body' },
      el('div', { class: 'lib-title', text: clip.title || `Clip ${clip.index + 1}` }),
      el('div', { class: 'lib-source', text: clip.source_video_title
        || (clip.video_id ? `Source video #${clip.video_id}` : 'Unknown source') }),
      el('div', { class: 'lib-meta' },
        el('span', { class: 'lib-score',
          style: `color:${scoreColor(score)}`,
          text: score.toFixed(1) }),
        el('span', { class: 'lib-dot', text: '·' }),
        el('span', { text: fmtDuration(clip.duration_seconds) }),
        clip.resolution ? el('span', { class: 'lib-dot', text: '·' }) : null,
        clip.resolution ? el('span', { text: clip.resolution }) : null,
        clip.aspect_ratio ? el('span', { class: 'lib-dot', text: '·' }) : null,
        clip.aspect_ratio ? el('span', { text: clip.aspect_ratio }) : null),
      el('div', { class: 'lib-badges' },
        statusBadge(clip.approval_status),
        clip.publish_status === 'published'
          ? el('span', { class: 'badge ok',
              text: clip.published_platform || 'published' }) : null,
        el('span', { class: 'badge quiet',
          text: fmtWhen(clip.created_at) }))));

  const previewBtn = el('button', { class: 'btn primary sm lib-preview',
    onclick: (event) => {
      event.stopPropagation();
      openClipPreview(clip, { onChange: () => render() });
    } }, icon('play'), 'Preview');
  card.querySelector('.lib-body').append(el('div', { class: 'lib-actions' },
    previewBtn,
    el('button', { class: 'btn sm', onclick: (event) => {
      event.stopPropagation();
      State.selectedClip = clip.id;
      navigate('editor');
    } }, 'Open in editor')));

  card.addEventListener('click', () => openClipPreview(clip, { onChange: () => render() }));
  return card;
}

registerRoute('clips',
  async () => {
    const params = new URLSearchParams();
    if (State.clipFilter === 'pending') params.set('approval', 'pending');
    else if (State.clipFilter === 'approved') params.set('approval', 'approved');
    else if (State.clipFilter === 'rejected') params.set('approval', 'rejected');
    else if (State.clipFilter === 'published') params.set('publish_status', 'published');
    if (State.clipSort) params.set('sort', State.clipSort);
    if (State.clipSearch) params.set('search', State.clipSearch);
    params.set('limit', '300');
    const data = await api(`/api/clips?${params.toString()}`);
    return { clips: data.clips || [] };
  },
  ({ clips }) => {
    const frag = document.createDocumentFragment();
    const pending = clips.filter((c) => c.approval_status === 'pending');

    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Clip Library' }),
        el('div', { class: 'sub',
          text: `${fmt(clips.length)} clip(s) · ${fmt(pending.length)} awaiting approval.` })),
      el('div', { class: 'actions' },
        pending.length
          ? el('button', { class: 'btn success',
              onclick: () => batchApprove(pending.map((c) => c.id), 'approve') },
              icon('check'), `Approve all ${pending.length}`)
          : null,
        el('button', { class: 'btn', onclick: () => render() },
          icon('refresh'), 'Refresh'))));

    // filter tabs
    const tabs = el('div', { class: 'filter-tabs' });
    for (const filter of CLIP_FILTERS) {
      tabs.append(el('button', {
        class: `filter-tab ${State.clipFilter === filter.key ? 'active' : ''}`.trim(),
        onclick: () => {
          State.clipFilter = filter.key;
          render();
        },
      }, filter.label));
    }

    // sort + search
    const sortSelect = el('select', { class: 'sort-select',
      'aria-label': 'Sort clips' },
      ...CLIP_SORTS.map((option) => el('option', {
        value: option.key, text: option.label,
        ...(State.clipSort === option.key ? { selected: true } : {}),
      })));
    sortSelect.addEventListener('change', () => {
      State.clipSort = sortSelect.value;
      render();
    });

    const searchInput = el('input', { type: 'search', class: 'search-input',
      placeholder: 'Search titles and transcripts…', value: State.clipSearch });
    searchInput.addEventListener('change', () => {
      State.clipSearch = searchInput.value.trim();
      render();
    });

    frag.append(el('div', { class: 'library-toolbar' }, tabs,
      el('div', { class: 'spacer' }),
      el('div', { class: 'library-tools' }, searchInput, sortSelect)));

    if (!clips.length) {
      frag.append(el('div', { class: 'card' },
        el('div', { class: 'card-body' },
          emptyState('No clips match this view',
            'Run a task or upload a video. Generated vertical clips will appear here for review.',
            'video'))));
      return frag;
    }

    const grid = el('div', { class: 'lib-grid' });
    for (const clip of clips) grid.append(libraryCard(clip));
    frag.append(grid);
    return frag;
  });

/* ══ CLIP EDITOR ═════════════════════════════════════════════════════════ */

registerRoute('editor',
  async () => {
    const list = await api('/api/clips?limit=300');
    const clips = list.clips || [];
    if (!State.selectedClip && clips.length) State.selectedClip = clips[0].id;
    const clip = clips.find((c) => c.id === State.selectedClip) || clips[0] || null;
    const detail = clip ? await api(`/api/clips/${clip.id}`) : null;
    return { clips, clip, detail };
  },
  ({ clips, clip, detail }) => {
    const frag = document.createDocumentFragment();
    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Clip Editor' }),
        el('div', { class: 'sub',
          text: clip ? 'Review, edit, approve, and publish an individual clip.'
                     : 'No clips available to edit yet.' }))));

    if (!clip) {
      frag.append(el('div', { class: 'card' },
        el('div', { class: 'card-body' },
          emptyState('Nothing to edit',
            'Generate a clip first, then return here to review and approve it.', 'video'))));
      return frag;
    }

    const full = detail.clip;
    const grid = el('div', { class: 'editor-grid' });

    // ── left: clip list
    const listCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' },
        el('h3', { text: 'All clips' }),
        el('div', { class: 'spacer' }),
        el('span', { class: 'badge quiet', text: String(clips.length) })),
      el('div', { class: 'card-body tight', style: 'max-height:70vh;overflow-y:auto' }));
    const listBody = listCard.querySelector('.card-body');
    const listNode = el('div', { class: 'list' });
    for (const item of clips) {
      listNode.append(el('div', {
        class: 'list-item',
        style: item.id === clip.id
          ? 'background:var(--accent-glow);border-left:2px solid var(--accent)'
          : 'cursor:pointer',
        onclick: (event) => {
          if (event.target.closest('button')) return;
          State.selectedClip = item.id;
          render();
        },
      },
        el('div', { class: 'grow' },
          el('div', { class: 't', text: item.title || `Clip ${item.index + 1}` }),
          el('div', { class: 's', text: `${item.score.toFixed(2)} · ${fmtDuration(item.duration_seconds)}` })),
        statusBadge(item.approval_status)));
    }
    listBody.append(listNode);
    grid.append(listCard);

    // ── right: player + details
    const right = el('div', { class: 'grid', style: 'gap:16px' });

    const player = el('div', { class: 'player-shell' });
    if (full.file_path) {
      player.append(clipPlayer(full));
    } else {
      player.append(el('div', { class: 'empty', text: 'No rendered video for this clip.' }));
    }

    // The signal breakdown explains why this moment was selected.
    const editorSignals = signalBreakdown(full);
    if (editorSignals) {
      right.append(el('div', { class: 'card' },
        el('div', { class: 'card-head' },
          el('h3', { text: 'Why this moment was selected' })),
        el('div', { class: 'card-body' },
          editorSignals,
          full.explanation
            ? el('div', { class: 'note', style: 'margin-top:12px',
                text: full.explanation })
            : null)));
    }

    // The player goes above the metadata so the clip is the first thing
    // the reviewer sees.
    right.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' },
        el('h3', { text: 'Playback' }),
        el('div', { class: 'spacer' }),
        el('button', {
          class: 'btn sm',
          onclick: () => openClipPreview(full, { onChange: () => render() }),
        }, icon('play'), 'Full preview')),
      el('div', { class: 'card-body' }, player)));

    // metadata editor
    const titleInput = el('input', { type: 'text', value: full.title || '' });
    const descInput = el('textarea', { value: full.description || '' });
    const tagsInput = el('input', { type: 'text', value: full.hashtags || '',
      placeholder: '#shorts #fyp' });
    const captionSelect = el('select', {},
      ...CAPTION_STYLES.map(([v, l]) => el('option', {
        value: v, text: l, ...(v === full.caption_style ? { selected: true } : {}),
      })));

    const saveBtn = el('button', { class: 'btn primary', onclick: async () => {
      try {
        await api(`/api/clips/${full.id}`, {
          method: 'PATCH',
          body: {
            title: titleInput.value,
            description: descInput.value,
            hashtags: tagsInput.value,
            caption_style: captionSelect.value,
          },
        });
        toast('Clip updated.', 'ok');
        render();
      } catch (error) { toast(error.message, 'err'); }
    } }, icon('check'), 'Save changes');

    const metaCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Clip details' }),
        el('div', { class: 'spacer' }), saveBtn),
      el('div', { class: 'card-body' },
        el('div', { class: 'form-grid' },
          el('div', { class: 'field full' },
            el('label', { text: 'Title' }), titleInput),
          el('div', { class: 'field full' },
            el('label', { text: 'Description' }), descInput),
          el('div', { class: 'field' },
            el('label', { text: 'Hashtags' }), tagsInput),
          el('div', { class: 'field' },
            el('label', { text: 'Caption style' }), captionSelect)),
        el('div', { style: 'display:flex;gap:8px;margin-top:14px;flex-wrap:wrap' },
          el('button', {
            class: `btn ${full.approval_status === 'approved' ? 'danger' : 'success'}`,
            onclick: async () => {
              const next = full.approval_status === 'approved' ? 'rejected' : 'approved';
              try {
                await api(`/api/clips/${full.id}`, {
                  method: 'PATCH', body: { approval_status: next },
                });
                toast(`Clip ${next}.`, 'ok');
                render();
              } catch (error) { toast(error.message, 'err'); }
            },
          }, icon(full.approval_status === 'approved' ? 'x' : 'check'),
            full.approval_status === 'approved' ? 'Reject clip' : 'Approve clip'),
          el('button', {
            class: 'btn',
            onclick: async () => {
              if (!await confirmDialog('Re-render clip',
                'Render this clip again with the current caption style?', 'Re-render')) return;
              toast('Re-rendering…', 'info');
              try {
                await api(`/api/clips/${full.id}`, {
                  method: 'PATCH', body: { rerender: true },
                });
                toast('Clip re-rendered.', 'ok');
                render();
              } catch (error) { toast(error.message, 'err'); }
            },
          }, icon('refresh'), 'Re-render'),
          el('a', { class: 'btn', href: `/api/clips/${full.id}/download` }, icon('download'), 'Download'),
          full.srt_path
            ? el('a', { class: 'btn', href: `/api/clips/${full.id}/srt`, target: '_blank' },
                'SRT')
            : null,
          el('button', {
            class: 'btn primary',
            onclick: () => publishDialog(full),
          }, icon('send'), 'Publish'))));

    // analysis card
    const analysisBody = el('div', { class: 'card-body' });
    analysisBody.append(el('div', { class: 'kv', style: 'margin-bottom:14px' },
      el('dt', { text: 'AI score' }),
      el('dd', { style: `font-weight:700;color:${scoreColor(full.score)}`,
        text: full.score.toFixed(2) }),
      el('dt', { text: 'Heuristic score' }),
      el('dd', { text: full.heuristic_score !== null && full.heuristic_score !== undefined
        ? full.heuristic_score.toFixed(2) : '—' }),
      el('dt', { text: 'AI adjustment' }),
      el('dd', { text: full.ai_adjustment !== null && full.ai_adjustment !== undefined
        ? `${full.ai_adjustment >= 0 ? '+' : ''}${full.ai_adjustment.toFixed(2)}` : '—' }),
      el('dt', { text: 'Scoring provider' }),
      el('dd', { class: 'mono', text: full.ai_provider
        || (full.ai_scored ? 'not recorded' : 'none (heuristic only)') }),
      el('dt', { text: 'Scoring model' }),
      el('dd', { class: 'mono', text: full.ai_model
        || (full.ai_scored ? 'not recorded' : 'none (heuristic only)') }),
      el('dt', { text: 'Timestamps' }),
      el('dd', { class: 'mono',
        text: `${full.start_seconds.toFixed(2)}s → ${full.end_seconds.toFixed(2)}s` }),
      el('dt', { text: 'Duration' }),
      el('dd', { text: fmtDuration(full.duration_seconds) }),
      el('dt', { text: 'Category' }),
      el('dd', { text: full.category || 'general' })));

    if (full.reason) {
      analysisBody.append(el('div', { class: 'fieldset-title',
        style: 'margin-top:4px', text: 'Why this clip was selected' }));
      analysisBody.append(el('div', { class: 'note', text: full.reason }));
    }
    if (full.transcript) {
      analysisBody.append(el('div', { class: 'fieldset-title',
        style: 'margin-top:16px', text: 'Transcript' }));
      analysisBody.append(el('div', { class: 'transcript-box', text: full.transcript }));
    }
    if (detail.approval_history?.length) {
      analysisBody.append(el('div', { class: 'fieldset-title',
        style: 'margin-top:16px', text: 'Approval history' }));
      const list = el('div', { class: 'list' });
      for (const event of detail.approval_history) {
        list.append(el('div', { class: 'list-item' },
          el('div', { class: 'grow' },
            el('div', { class: 't', text: event.action }),
            el('div', { class: 's', text: `${event.actor} · ${fmtDateTime(event.created_at)}` }))));
      }
      analysisBody.append(list);
    }

    const analysisCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'AI analysis' })),
      analysisBody);

    right.append(metaCard, analysisCard);
    grid.append(right);
    frag.append(grid);
    return frag;
  });

function publishDialog(clip) {
  const platform = el('select', {},
    el('option', { value: 'youtube', text: 'YouTube Shorts' }),
    el('option', { value: 'instagram', text: 'Instagram Reels' }));
  const title = el('input', { type: 'text', value: clip.title || '' });
  const description = el('textarea', { value: clip.description || '' });
  const privacy = el('select', {},
    el('option', { value: 'public', text: 'Public' }),
    el('option', { value: 'unlisted', text: 'Unlisted' }),
    el('option', { value: 'private', text: 'Private' }));
  const errorBox = el('div', { style: 'margin-top:10px' });

  modal({
    title: 'Publish clip',
    body: el('div', {},
      el('div', { class: 'form-grid' },
        el('div', { class: 'field full' }, el('label', { text: 'Platform' }), platform),
        el('div', { class: 'field full' }, el('label', { text: 'Title' }), title),
        el('div', { class: 'field full' }, el('label', { text: 'Description / caption' }), description),
        el('div', { class: 'field full' }, el('label', { text: 'Privacy' }), privacy)),
      errorBox),
    actions: [
      { label: 'Cancel' },
      { label: 'Publish', class: 'primary', onClick: async () => {
        try {
          const result = await api('/api/publish', {
            method: 'POST',
            body: {
              platform: platform.value,
              clip_ids: [clip.id],
              title: title.value,
              description: description.value,
              privacy_status: privacy.value,
            },
          });
          const outcome = result.results[0];
          if (outcome.status === 'published') {
            toast(`Published to ${platform.value}.`, 'ok');
            render();
          } else {
            errorBox.append(el('div', { class: 'note err',
              text: outcome.error || outcome.detail || 'Publishing did not complete.' }));
            return false;
          }
        } catch (error) {
          errorBox.append(el('div', { class: 'note err', text: error.message }));
          return false;
        }
      }},
    ],
  });
}

/* ══ EDITING STUDIO ═══════════════════════════════════════════════════════ */

registerRoute('studio',
  async () => {
    const list = await api('/api/clips?limit=300');
    const clips = list.clips || [];
    return { clips };
  },
  ({ clips }) => {
    const frag = document.createDocumentFragment();
    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Editing Studio' }),
        el('div', { class: 'sub', text: 'Full video editing workspace with timeline, preview, and export.' }))));

    // Studio layout
    const studio = el('div', { class: 'studio-layout' });

    // Media panel (left)
    const mediaPanel = el('div', { class: 'studio-panel studio-media' },
      el('div', { class: 'panel-head', text: 'Media Library' }),
      el('div', { class: 'panel-body', id: 'studio-media-list' }));
    const mediaList = mediaPanel.querySelector('#studio-media-list');
    for (const c of clips.slice(0, 20)) {
      const item = el('div', { class: 'studio-media-item', 'data-clip-id': c.id },
        el('div', { class: 't', text: c.title || `Clip ${c.index + 1}` }),
        el('div', { class: 's', text: fmtDuration(c.duration_seconds) }));
      item.addEventListener('dblclick', () => addToTimeline(c));
      mediaList.append(item);
    }

    // Preview (center)
    const previewPanel = el('div', { class: 'studio-panel studio-preview' },
      el('div', { class: 'player-shell', id: 'studio-player' },
        el('video', { id: 'studio-video', style: 'width:100%;max-height:360px;background:#000;border-radius:6px' })),
      el('div', { class: 'studio-controls' },
        el('button', { class: 'btn sm', id: 'studio-play-btn', onclick: () => {
          const v = document.getElementById('studio-video');
          if (v) { v.paused ? v.play() : v.pause(); }
        }}, 'Play'),
        el('button', { class: 'btn sm ghost', onclick: () => {
          const v = document.getElementById('studio-video');
          if (v) v.currentTime = Math.max(0, v.currentTime - 1/30);
        }}, '◀ Frame'),
        el('button', { class: 'btn sm ghost', onclick: () => {
          const v = document.getElementById('studio-video');
          if (v) v.currentTime = Math.min(v.duration || 0, v.currentTime + 1/30);
        }}, 'Frame ▶'),
        el('select', { id: 'studio-speed', style: 'margin-left:8px', onchange: (e) => {
          const v = document.getElementById('studio-video');
          if (v) v.playbackRate = parseFloat(e.target.value);
        }},
          el('option', { value: '0.25', text: '0.25x' }),
          el('option', { value: '0.5', text: '0.5x' }),
          el('option', { value: '1', text: '1x', selected: true }),
          el('option', { value: '1.5', text: '1.5x' }),
          el('option', { value: '2', text: '2x' })),
        el('input', { type: 'range', min: '0', max: '1', step: '0.05', value: '1', id: 'studio-vol',
          style: 'margin-left:8px;width:80px',
          oninput: (e) => {
            const v = document.getElementById('studio-video');
            if (v) v.volume = parseFloat(e.target.value);
          }}),
        el('button', { class: 'btn sm ghost', onclick: () => {
          const v = document.getElementById('studio-video');
          if (v) v.requestFullscreen && v.requestFullscreen();
        }}, 'Fullscreen'),
        el('span', { id: 'studio-time', text: '0:00 / 0:00', style: 'margin-left:auto;font-family:monospace;font-size:12px' })));

    // Timeline (bottom)
    const timelinePanel = el('div', { class: 'studio-panel studio-timeline' },
      el('div', { class: 'panel-head', style: 'display:flex;align-items:center;gap:8px' },
        el('span', { text: 'Timeline' }),
        el('div', { class: 'spacer' }),
        el('button', { class: 'btn sm ghost', onclick: () => splitAtPlayhead() }, 'Split'),
        el('button', { class: 'btn sm ghost', onclick: () => deleteSelected() }, 'Delete'),
        el('button', { class: 'btn sm ghost', onclick: () => duplicateSelected() }, 'Duplicate'),
        el('button', { class: 'btn sm ghost', onclick: () => addToAudioTimeline() }, 'Add Audio'),
        el('button', { class: 'btn sm', onclick: () => saveProject() }, 'Save'),
        el('button', { class: 'btn sm primary', onclick: () => exportProject() }, 'Export')),
      el('div', { class: 'timeline-track', id: 'studio-timeline' },
        el('div', { class: 'timeline-ruler', id: 'studio-ruler' }),
        el('div', { class: 'timeline-clips', id: 'studio-clips' })));

    // Properties panel (right)
    const propsPanel = el('div', { class: 'studio-panel studio-props' },
      el('div', { class: 'panel-head', text: 'Properties' }),
      el('div', { class: 'panel-body', id: 'studio-props' },
        el('div', { class: 'prop-row' }, el('label', { text: 'Clip' }), el('span', { id: 'prop-clip-name', text: 'None selected' })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Start' }), el('span', { id: 'prop-start', text: '0.00s' })),
        el('div', { class: 'prop-row' }, el('label', { text: 'End' }), el('span', { id: 'prop-end', text: '0.00s' })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Duration' }), el('span', { id: 'prop-dur', text: '0.00s' })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Speed' }), el('input', { type: 'range', min: '0.25', max: '2', step: '0.25', value: '1', id: 'prop-speed',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.speed = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Volume' }), el('input', { type: 'range', min: '0', max: '1', step: '0.1', value: '1', id: 'prop-volume',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.volume = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Opacity' }), el('input', { type: 'range', min: '0', max: '1', step: '0.1', value: '1', id: 'prop-opacity',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.opacity = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Position X' }), el('input', { type: 'number', value: '0', id: 'prop-posx',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.posX = parseFloat(e.target.value) || 0; } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Position Y' }), el('input', { type: 'number', value: '0', id: 'prop-posy',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.posY = parseFloat(e.target.value) || 0; } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Scale' }), el('input', { type: 'range', min: '0.1', max: '3', step: '0.1', value: '1', id: 'prop-scale',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.scale = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Rotation' }), el('input', { type: 'range', min: '-180', max: '180', step: '1', value: '0', id: 'prop-rotation',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.rotation = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Crop Top' }), el('input', { type: 'range', min: '0', max: '50', step: '1', value: '0', id: 'prop-cropt',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.cropTop = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Crop Bottom' }), el('input', { type: 'range', min: '0', max: '50', step: '1', value: '0', id: 'prop-cropb',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.cropBottom = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Crop Left' }), el('input', { type: 'range', min: '0', max: '50', step: '1', value: '0', id: 'prop-cropl',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.cropLeft = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Crop Right' }), el('input', { type: 'range', min: '0', max: '50', step: '1', value: '0', id: 'prop-cropr',
          oninput: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.cropRight = parseFloat(e.target.value); } })),
        el('div', { class: 'prop-row' }, el('label', { text: 'Aspect Ratio' }), el('select', { id: 'prop-aspect',
          onchange: (e) => { if (State.studioSelectedClip) State.studioSelectedClip.aspectRatio = e.target.value; } },
          el('option', { value: '16:9', text: '16:9' }),
          el('option', { value: '9:16', text: '9:16' }),
          el('option', { value: '1:1', text: '1:1' }),
          el('option', { value: '4:5', text: '4:5' })))
      )
    );

    studio.append(mediaPanel, previewPanel, propsPanel, timelinePanel);
    frag.append(studio);

    // Initialize studio state
    if (!State.studioTimeline) State.studioTimeline = [];
    if (!State.studioSelectedClip) State.studioSelectedClip = null;
    // Load saved project
    try {
      const saved = localStorage.getItem('studio_project');
      if (saved) {
        const proj = JSON.parse(saved);
        if (proj.timeline && Array.isArray(proj.timeline)) {
          State.studioTimeline = proj.timeline.map(c => ({
            ...c,
            speed: c.speed || 1,
            volume: c.volume || 1,
            opacity: c.opacity || 1,
            posX: c.posX || 0,
            posY: c.posY || 0,
            scale: c.scale || 1,
            rotation: c.rotation || 0,
            cropTop: c.cropTop || 0,
            cropBottom: c.cropBottom || 0,
            cropLeft: c.cropLeft || 0,
            cropRight: c.cropRight || 0,
            aspectRatio: c.aspectRatio || '16:9',
          }));
        }
      }
    } catch (e) { /* ignore */ }
    // Render timeline
    renderStudioTimeline();

    // Time update + playhead sync
    setTimeout(() => {
      const v = document.getElementById('studio-video');
      const t = document.getElementById('studio-time');
      if (v && t) {
        v.addEventListener('timeupdate', () => {
          t.textContent = `${fmtDuration(v.currentTime)} / ${fmtDuration(v.duration || 0)}`;
          updatePlayhead(v.currentTime);
        });
        v.addEventListener('play', () => {
          const btn = document.getElementById('studio-play-btn');
          if (btn) btn.textContent = 'Pause';
        });
        v.addEventListener('pause', () => {
          const btn = document.getElementById('studio-play-btn');
          if (btn) btn.textContent = 'Play';
        });
      }
    }, 100);

    // Keyboard shortcuts
    document.addEventListener('keydown', studioKeyHandler);

    return frag;
  });

/* Studio helper functions */
function addToAudioTimeline() {
  if (!State.studioTimeline) State.studioTimeline = [];
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = 'audio/*,video/*';
  input.onchange = async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const url = URL.createObjectURL(file);
    // Generate waveform
    const waveform = await generateWaveform(url);
    const lastEnd = State.studioTimeline.reduce((max, c) => Math.max(max, c.end), 0);
    State.studioTimeline.push({
      id: 'audio_' + Date.now(),
      type: 'audio',
      src: url,
      title: file.name,
      start: lastEnd,
      end: lastEnd + 10,
      trimStart: 0,
      trimEnd: 10,
      volume: 1,
      muted: false,
      fadeIn: 0,
      fadeOut: 0,
      waveform: waveform,
      speed: 1,
      opacity: 1,
      posX: 0, posY: 0, scale: 1, rotation: 0,
      cropTop: 0, cropBottom: 0, cropLeft: 0, cropRight: 0,
      aspectRatio: '16:9',
    });
    renderStudioTimeline();
  };
  input.click();
}

async function generateWaveform(url) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const response = await fetch(url);
    const arrayBuffer = await response.arrayBuffer();
    const audioBuffer = await ctx.decodeAudioData(arrayBuffer);
    const channelData = audioBuffer.getChannelData(0);
    const samples = 200;
    const blockSize = Math.floor(channelData.length / samples);
    const waveform = [];
    for (let i = 0; i < samples; i++) {
      let sum = 0;
      for (let j = 0; j < blockSize; j++) {
        sum += Math.abs(channelData[i * blockSize + j] || 0);
      }
      waveform.push(sum / blockSize);
    }
    ctx.close();
    return waveform;
  } catch (e) {
    console.warn('Waveform generation failed:', e);
    return null;
  }
}
function addToTimeline(clip) {
  if (!State.studioTimeline) State.studioTimeline = [];
  const lastEnd = State.studioTimeline.reduce((max, c) => Math.max(max, c.end), 0);
  State.studioTimeline.push({
    id: 'clip_' + Date.now(),
    sourceClipId: clip.id,
    src: clip.file_path ? `/media/clip/${clip.id}` : null,
    title: clip.title || `Clip ${clip.index + 1}`,
    start: lastEnd,
    end: lastEnd + (clip.duration_seconds || 10),
    trimStart: 0,
    trimEnd: clip.duration_seconds || 10,
    speed: 1,
    volume: 1,
    opacity: 1,
    posX: 0,
    posY: 0,
    scale: 1,
    rotation: 0,
    cropTop: 0,
    cropBottom: 0,
    cropLeft: 0,
    cropRight: 0,
    aspectRatio: '16:9',
  });
  renderStudioTimeline();
}

function renderStudioTimeline() {
  const container = document.getElementById('studio-clips');
  if (!container) return;
  container.innerHTML = '';
  const totalDur = State.studioTimeline.reduce((max, c) => Math.max(max, c.end), 10);
  const pxPerSec = Math.max(10, 600 / totalDur);
  for (const clip of State.studioTimeline) {
    const el2 = document.createElement('div');
    el2.className = 'timeline-clip' + (State.studioSelectedClip && State.studioSelectedClip.id === clip.id ? ' selected' : '');
    el2.style.left = (clip.start * pxPerSec) + 'px';
    el2.style.width = ((clip.end - clip.start) * pxPerSec) + 'px';
    el2.textContent = clip.title;
    el2.addEventListener('click', () => {
      State.studioSelectedClip = clip;
      renderStudioTimeline();
      updatePropsPanel(clip);
      // Load into preview
      const v = document.getElementById('studio-video');
      if (v && clip.src) { v.src = clip.src; v.currentTime = 0; }
    });
    // Trim handles
    const leftHandle = document.createElement('div');
    leftHandle.className = 'trim-handle left';
    leftHandle.addEventListener('mousedown', (e) => startTrim(e, clip, 'left'));
    el2.append(leftHandle);
    const rightHandle = document.createElement('div');
    rightHandle.className = 'trim-handle right';
    rightHandle.addEventListener('mousedown', (e) => startTrim(e, clip, 'right'));
    el2.append(rightHandle);
    container.append(el2);
  }
  // Ruler
  const ruler = document.getElementById('studio-ruler');
  if (ruler) {
    ruler.innerHTML = '';
    for (let s = 0; s <= totalDur; s += 5) {
      const mark = document.createElement('span');
      mark.style.position = 'absolute';
      mark.style.left = (s * pxPerSec) + 'px';
      mark.textContent = fmtDuration(s);
      ruler.append(mark);
    }
  }
}

function updatePlayhead(time) {
  let playhead = document.getElementById('studio-playhead');
  if (!playhead) {
    const timeline = document.getElementById('studio-timeline');
    if (timeline) {
      playhead = document.createElement('div');
      playhead.id = 'studio-playhead';
      playhead.className = 'playhead';
      timeline.append(playhead);
    }
  }
  if (playhead) {
    const totalDur = State.studioTimeline.reduce((max, c) => Math.max(max, c.end), 10);
    const pxPerSec = Math.max(10, 600 / totalDur);
    playhead.style.left = (time * pxPerSec + 8) + 'px';
  }
}

function updatePropsPanel(clip) {
  const name = document.getElementById('prop-clip-name');
  const start = document.getElementById('prop-start');
  const end = document.getElementById('prop-end');
  const dur = document.getElementById('prop-dur');
  if (name) name.textContent = clip.title;
  if (start) start.textContent = clip.start.toFixed(2) + 's';
  if (end) end.textContent = clip.end.toFixed(2) + 's';
  if (dur) dur.textContent = (clip.end - clip.start).toFixed(2) + 's';
  // Load transform values into inputs
  const speed = document.getElementById('prop-speed');
  const volume = document.getElementById('prop-volume');
  const opacity = document.getElementById('prop-opacity');
  const posX = document.getElementById('prop-posx');
  const posY = document.getElementById('prop-posy');
  const scale = document.getElementById('prop-scale');
  const rotation = document.getElementById('prop-rotation');
  const cropT = document.getElementById('prop-cropt');
  const cropB = document.getElementById('prop-cropb');
  const cropL = document.getElementById('prop-cropl');
  const cropR = document.getElementById('prop-cropr');
  const aspect = document.getElementById('prop-aspect');
  if (speed) speed.value = clip.speed || 1;
  if (volume) volume.value = clip.volume || 1;
  if (opacity) opacity.value = clip.opacity || 1;
  if (posX) posX.value = clip.posX || 0;
  if (posY) posY.value = clip.posY || 0;
  if (scale) scale.value = clip.scale || 1;
  if (rotation) rotation.value = clip.rotation || 0;
  if (cropT) cropT.value = clip.cropTop || 0;
  if (cropB) cropB.value = clip.cropBottom || 0;
  if (cropL) cropL.value = clip.cropLeft || 0;
  if (cropR) cropR.value = clip.cropRight || 0;
  if (aspect) aspect.value = clip.aspectRatio || '16:9';
}

function splitAtPlayhead() {
  const v = document.getElementById('studio-video');
  if (!v || !State.studioSelectedClip) return;
  const clip = State.studioSelectedClip;
  const splitTime = v.currentTime;
  if (splitTime <= clip.start || splitTime >= clip.end) return;
  const newClip = {
    id: 'clip_' + Date.now(),
    sourceClipId: clip.sourceClipId,
    src: clip.src,
    title: clip.title + ' (2)',
    start: splitTime,
    end: clip.end,
    trimStart: clip.trimStart + (splitTime - clip.start),
    trimEnd: clip.trimEnd,
    speed: clip.speed,
    volume: clip.volume,
    opacity: clip.opacity,
    posX: clip.posX,
    posY: clip.posY,
    scale: clip.scale,
    rotation: clip.rotation,
    cropTop: clip.cropTop,
    cropBottom: clip.cropBottom,
    cropLeft: clip.cropLeft,
    cropRight: clip.cropRight,
    aspectRatio: clip.aspectRatio,
  };
  clip.end = splitTime;
  clip.trimEnd = clip.trimStart + (splitTime - clip.start);
  const idx = State.studioTimeline.indexOf(clip);
  State.studioTimeline.splice(idx + 1, 0, newClip);
  State.studioSelectedClip = newClip;
  renderStudioTimeline();
  updatePropsPanel(newClip);
}

function deleteSelected() {
  if (!State.studioSelectedClip) return;
  const idx = State.studioTimeline.indexOf(State.studioSelectedClip);
  if (idx >= 0) State.studioTimeline.splice(idx, 1);
  State.studioSelectedClip = State.studioTimeline[0] || null;
  renderStudioTimeline();
  if (State.studioSelectedClip) updatePropsPanel(State.studioSelectedClip);
}

function duplicateSelected() {
  if (!State.studioSelectedClip) return;
  const clip = State.studioSelectedClip;
  const newClip = { ...clip, id: 'clip_' + Date.now(), title: clip.title + ' (copy)', start: clip.end, end: clip.end + (clip.end - clip.start) };
  State.studioTimeline.push(newClip);
  State.studioSelectedClip = newClip;
  renderStudioTimeline();
  updatePropsPanel(newClip);
}

function startTrim(e, clip, side) {
  e.preventDefault();
  const startX = e.clientX;
  const origStart = clip.start;
  const origEnd = clip.end;
  const onMove = (ev) => {
    const dx = ev.clientX - startX;
    const totalDur = State.studioTimeline.reduce((max, c) => Math.max(max, c.end), 10);
    const pxPerSec = Math.max(10, 600 / totalDur);
    const dt = dx / pxPerSec;
    if (side === 'left') {
      clip.start = Math.max(0, Math.min(clip.end - 0.5, origStart + dt));
    } else {
      clip.end = Math.max(clip.start + 0.5, origEnd + dt);
    }
    renderStudioTimeline();
    if (State.studioSelectedClip && State.studioSelectedClip.id === clip.id) updatePropsPanel(clip);
  };
  const onUp = () => {
    document.removeEventListener('mousemove', onMove);
    document.removeEventListener('mouseup', onUp);
  };
  document.addEventListener('mousemove', onMove);
  document.addEventListener('mouseup', onUp);
}

function saveProject() {
  const project = {
    id: 'proj_' + Date.now(),
    timeline: State.studioTimeline,
    savedAt: new Date().toISOString(),
  };
  localStorage.setItem('studio_project', JSON.stringify(project));
  alert('Project saved locally.');
}

function exportProject() {
  alert('Export: Use the existing clip export from the Clip Editor. Full timeline export coming in Milestone 6.');
}

function studioKeyHandler(e) {
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT') return;
  const v = document.getElementById('studio-video');
  if (e.code === 'Space') { e.preventDefault(); if (v) v.paused ? v.play() : v.pause(); }
  if (e.code === 'ArrowLeft') { e.preventDefault(); if (v) v.currentTime = Math.max(0, v.currentTime - 1/30); }
  if (e.code === 'ArrowRight') { e.preventDefault(); if (v) v.currentTime = Math.min(v.duration || 0, v.currentTime + 1/30); }
  if (e.key === 's' || e.key === 'S') { e.preventDefault(); splitAtPlayhead(); }
  if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); deleteSelected(); }
}

/* ══ PUBLISHING CALENDAR ═════════════════════════════════════════════════ */

/* ══ PUBLISHING CALENDAR ═════════════════════════════════════════════════ */

registerRoute('calendar',
  async () => api('/api/publishing/calendar'),
  (data) => {
    const frag = document.createDocumentFragment();
    const calendar = data.calendar || {};
    const days = Object.keys(calendar).sort().reverse();

    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Publishing Calendar' }),
        el('div', { class: 'sub',
          text: `${fmt(data.total)} published clip(s), grouped by publication date.` }))));

    if (!days.length) {
      frag.append(el('div', { class: 'card' },
        el('div', { class: 'card-body' },
          emptyState('Nothing published yet',
            'Approve a clip and publish it to see it on the calendar.', 'send'))));
      return frag;
    }

    for (const day of days) {
      const items = calendar[day];
      const body = el('div', { class: 'card-body tight' });
      const list = el('div', { class: 'list' });
      for (const item of items) {
        list.append(el('div', { class: 'list-item' },
          el('div', { class: 'grow' },
            el('div', { class: 't', text: item.title || `Clip ${item.clip_id}` }),
            el('div', { class: 's',
              text: `${item.platform || 'unknown'} · ${fmtDateTime(item.published_at)}` })),
          item.external_id
            ? el('a', { class: 'btn sm ghost',
                href: `https://www.youtube.com/watch?v=${item.external_id}`,
                target: '_blank', rel: 'noopener' }, 'Open')
            : null));
      }
      body.append(list);
      frag.append(el('div', { class: 'card', style: 'margin-bottom:16px' },
        el('div', { class: 'card-head' },
          el('h3', { text: new Date(day + 'T00:00:00').toLocaleDateString(undefined,
            { weekday: 'long', month: 'long', day: 'numeric' }) }),
          el('div', { class: 'spacer' }),
          el('span', { class: 'badge quiet', text: String(items.length) })),
        body));
    }
    return frag;
  });

/* ══ ANALYTICS ═══════════════════════════════════════════════════════════ */

registerRoute('analytics',
  async () => api('/api/analytics'),
  (data) => {
    const frag = document.createDocumentFragment();
    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Analytics' }),
        el('div', { class: 'sub',
          text: 'Real metrics computed from the processing and publishing history.' }))));

    const tiles = el('div', { class: 'grid c4' });
    const tileData = [
      ['Clips generated', fmt(data.clips_generated), '', 'total clips produced'],
      ['Clips published', fmt(data.clips_published), 'green', 'successfully uploaded'],
      ['Failed uploads', fmt(data.failed_uploads), data.failed_uploads ? 'red' : '',
        'publish attempts that failed'],
      ['Average AI score', data.average_ai_score === null ? '—'
        : data.average_ai_score.toFixed(2), 'cyan', 'across all generated clips'],
    ];
    for (const [label, value, cls, foot] of tileData) {
      tiles.append(el('div', { class: `stat ${cls}` },
        el('div', { class: 'stat-label', text: label }),
        el('div', { class: 'stat-value', text: value }),
        el('div', { class: 'stat-foot', text: foot })));
    }
    frag.append(tiles);

    const timing = data.processing_time || {};
    const platformEntries = Object.entries(data.published_by_platform || {})
      .map(([label, value]) => ({ label, value }));
    const categoryEntries = Object.entries(data.clips_by_category || {})
      .map(([label, value]) => ({ label, value }))
      .sort((a, b) => b.value - a.value);

    const charts = el('div', { class: 'grid c3', style: 'margin-top:16px' });

    charts.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Clips by category' })),
      el('div', { class: 'card-body' },
        categoryEntries.length
          ? barChart(categoryEntries)
          : emptyState('No categories yet', 'Generate clips to populate this chart.', 'video'))));

    charts.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Published by platform' })),
      el('div', { class: 'card-body' },
        platformEntries.length
          ? donutChart(platformEntries)
          : emptyState('Nothing published', 'Published clips will be grouped by platform.', 'send'))));

    charts.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Processing time' })),
      el('div', { class: 'card-body' },
        timing.count
          ? el('div', { class: 'kv' },
              el('dt', { text: 'Jobs measured' }), el('dd', { text: fmt(timing.count) }),
              el('dt', { text: 'Average' }),
              el('dd', { text: fmtDuration(timing.average_seconds) }),
              el('dt', { text: 'Total' }),
              el('dd', { text: fmtDuration(timing.total_seconds) }),
              el('dt', { text: 'Fastest' }),
              el('dd', { text: fmtDuration(timing.min_seconds) }),
              el('dt', { text: 'Slowest' }),
              el('dd', { text: fmtDuration(timing.max_seconds) }))
          : emptyState('No completed jobs', 'Processing durations appear once jobs finish.', 'play'))));

    frag.append(charts);

    const availability = data.metrics_available || {};
    frag.append(el('div', { class: 'card', style: 'margin-top:16px' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Metric availability' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'note warn' },
          el('strong', { text: 'Views and engagement are not reported. ' }),
          el('span', { text: availability.note || '' })))));

    return frag;
  });

/* ══ AI CONFIGURATION ════════════════════════════════════════════════════ */

registerRoute('ai',
  async () => api('/api/ai/status'),
  (status) => {
    const frag = document.createDocumentFragment();
    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'AI Configuration' }),
        el('div', { class: 'sub',
          text: 'Groq powers clip scoring. The API key lives in your local credential file and is never exposed here.' }))));

    const statusCard = el('div', { class: 'card' },
      el('div', { class: 'card-head' },
        el('h3', { text: 'Provider status' }),
        el('div', { class: 'spacer' }),
        el('button', {
          class: 'btn sm',
          onclick: async (event) => {
            const button = event.currentTarget;
            button.disabled = true;
            button.textContent = 'Testing…';
            try {
              const result = await api('/api/ai/test', { method: 'POST' });
              toast(result.chat_ok
                ? 'Provider responded successfully.'
                : `Provider check failed: ${result.error}`, result.chat_ok ? 'ok' : 'err');
              render();
            } catch (error) { toast(error.message, 'err'); }
            finally { button.disabled = false; }
          },
        }, icon('refresh'), 'Test connection')),
      el('div', { class: 'card-body' },
        el('div', { class: 'kv' },
          el('dt', { text: 'Provider' }),
          el('dd', {}, status.provider
            ? el('span', { class: 'badge info' }, status.provider)
            : el('span', { class: 'badge warn', text: 'not configured' })),
          el('dt', { text: 'Model' }),
          el('dd', { class: 'mono', text: status.model || '—' }),
          el('dt', { text: 'Fallback provider' }),
          el('dd', { class: 'mono', text: status.fallback || 'none' }),
          el('dt', { text: 'API key present' }),
          el('dd', {}, status.key_present
            ? el('span', { class: 'badge ok' }, 'yes')
            : el('span', { class: 'badge err', text: 'no' })),
          el('dt', { text: 'Chat endpoint' }),
          el('dd', {}, status.chat_ok
            ? el('span', { class: 'badge ok' }, 'reachable')
            : el('span', { class: 'badge err', text: 'unreachable' })),
          el('dt', { text: 'Embeddings' }),
          el('dd', {}, status.embeddings_supported
            ? el('span', { class: 'badge ok' }, 'supported')
            : el('span', { class: 'badge warn', text: 'not available' }))),
        status.error
          ? el('div', { class: 'note err', style: 'margin-top:14px' },
              el('strong', { text: 'Error: ' }),
              el('span', { text: status.error }))
          : null,
        el('div', { class: 'note', style: 'margin-top:14px' },
          el('span', { text: status.embedding_note || '' }))));

    const modelInput = el('input', { type: 'text', value: status.default_model || '' });
    const providerSelect = el('select', {},
      el('option', { value: 'groq', text: 'Groq (primary)' }),
      el('option', { value: 'openrouter', text: 'OpenRouter (fallback)' }),
      el('option', { value: 'none', text: 'Disabled (heuristic only)' }));
    if (status.default_provider) providerSelect.value = status.default_provider;
    const fallbackSelect = el('select', {},
      el('option', { value: '', text: 'None' }),
      el('option', { value: 'openrouter', text: 'OpenRouter' }),
      el('option', { value: 'groq', text: 'Groq' }));
    if (status.default_fallback) fallbackSelect.value = status.default_fallback;

    const configCard = el('div', { class: 'card', style: 'margin-top:16px' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Scoring configuration' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'form-grid' },
          el('div', { class: 'field' },
            el('label', { text: 'Primary provider' }), providerSelect),
          el('div', { class: 'field' },
            el('label', { text: 'Fallback provider' }), fallbackSelect),
          el('div', { class: 'field full' },
            el('label', { text: 'Model id' }), modelInput,
            el('div', { class: 'hint',
              text: 'Used explicitly when reranking. Groq currently serves openai/gpt-oss-120b.' }))),
        el('div', { style: 'margin-top:14px' },
          el('button', {
            class: 'btn primary',
            onclick: async () => {
              try {
                await api('/api/ai/config', {
                  method: 'POST',
                  body: {
                    provider: providerSelect.value,
                    model: modelInput.value.trim(),
                    fallback_provider: fallbackSelect.value || null,
                  },
                });
                toast('AI configuration saved.', 'ok');
                render();
              } catch (error) { toast(error.message, 'err'); }
            },
          }, icon('check'), 'Save configuration')),
        el('div', { class: 'note', style: 'margin-top:14px' },
          el('span', { text: 'The API key is read from the local credential file at call time. It is never stored in the database, returned by the API, or written to the frontend.' }))));

    frag.append(statusCard, configCard);
    return frag;
  });

/* ══ CONNECTED ACCOUNTS ══════════════════════════════════════════════════ */

registerRoute('accounts',
  async () => api('/api/accounts'),
  (data) => {
    const frag = document.createDocumentFragment();
    const accounts = data.accounts || {};

    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Connected Accounts' }),
        el('div', { class: 'sub',
          text: 'Official OAuth connections for YouTube Shorts and Instagram Reels.' })),
      el('div', { class: 'actions' },
        el('span', { class: 'badge quiet',
          text: `${Object.values(accounts).filter((a) => a.connected).length} connected` }))));

    const grid = el('div', { class: 'grid c2' });
    for (const [platform, info] of Object.entries(accounts)) {
      const label = platform === 'youtube' ? 'YouTube Shorts' : 'Instagram Reels';
      const card = el('div', { class: 'card' },
        el('div', { class: 'card-head' },
          el('h3', { text: label }),
          el('div', { class: 'spacer' }),
          statusBadge(info.status || 'disconnected')),
        el('div', { class: 'card-body' },
          el('div', { class: 'kv' },
            el('dt', { text: 'Status' }),
            el('dd', {}, info.connected
              ? el('span', { class: 'badge ok' }, 'connected')
              : el('span', { class: 'badge warn', text: 'not connected' })),
            el('dt', { text: 'Account' }),
            el('dd', { text: info.channel_title || info.display_name || '—' }),
            el('dt', { text: 'Client id configured' }),
            el('dd', {}, info.client_id_present
              ? el('span', { class: 'badge ok' }, 'yes')
              : el('span', { class: 'badge warn', text: 'no' })),
            el('dt', { text: 'Client secret configured' }),
            el('dd', {}, info.client_secret_present
              ? el('span', { class: 'badge ok' }, 'yes')
              : el('span', { class: 'badge warn', text: 'no' })),
            el('dt', { text: 'Redirect URI' }),
            el('dd', { class: 'mono', style: 'font-size:11px', text: info.redirect_uri || '—' }),
            el('dt', { text: 'Last verified' }),
            el('dd', { text: info.last_verified_at ? fmtDateTime(info.last_verified_at) : '—' })),
          info.message
            ? el('div', { class: 'note', style: 'margin-top:12px' },
                el('span', { text: info.message }))
            : null,
          info.last_error
            ? el('div', { class: 'note err', style: 'margin-top:12px' },
                el('span', { text: info.last_error }))
            : null,
          el('div', { style: 'display:flex;gap:8px;margin-top:14px;flex-wrap:wrap' },
            info.connected
              ? el('button', {
                  class: 'btn danger',
                  onclick: async () => {
                    if (!await confirmDialog('Disconnect account',
                      `Disconnect ${label}? Publishing will stop until you reconnect.`, 'Disconnect')) return;
                    try {
                      await api(`/api/accounts/${platform}/disconnect`, { method: 'POST' });
                      toast('Account disconnected.', 'ok');
                      render();
                    } catch (error) { toast(error.message, 'err'); }
                  },
                }, 'Disconnect')
              : el('button', {
                  class: 'btn primary',
                  onclick: async () => {
                    try {
                      const result = await api(`/api/accounts/${platform}/connect`);
                      window.location.href = result.url;
                    } catch (error) { toast(error.message, 'err'); }
                  },
                }, icon('link'), 'Connect account'))));
      grid.append(card);
    }
    frag.append(grid);

    frag.append(el('div', { class: 'card', style: 'margin-top:16px' },
      el('div', { class: 'card-head' }, el('h3', { text: 'How connections work' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'note' },
          el('span', { text: 'Connections use official OAuth only. This application never asks for your account password and never automates a browser login. Until a client id and secret are added to your local credential file and you complete the consent screen, each integration reports its true state above.' })),
        el('div', { class: 'note warn', style: 'margin-top:10px' },
          el('span', { text: 'Instagram Reels publishing additionally requires a publicly reachable HTTPS URL for the video file, and a Facebook Page linked to a professional (Business or Creator) Instagram account.' })),
        el('div', { class: 'note', style: 'margin-top:10px' },
          el('span', { text: 'Publishing is only ever performed for clips you have explicitly approved. Unapproved clips are reported as skipped rather than silently published.' })))));

    return frag;
  });

/* ══ SETTINGS ════════════════════════════════════════════════════════════ */

registerRoute('settings',
  async () => {
    const [settings, storage] = await Promise.all([
      api('/api/settings'),
      api('/api/storage').catch(() => null),
    ]);
    return { ...settings, storage };
  },
  (data) => {
    const frag = document.createDocumentFragment();
    const settings = data.settings || {};

    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Settings' }),
        el('div', { class: 'sub', text: 'Application, storage, and automation configuration.' }))));

    const grid = el('div', { class: 'grid main-side' });
    const left = el('div', { class: 'grid', style: 'gap:16px' });

    // video settings
    const clipDuration = el('input', { type: 'number',
      value: String(settings.default_clip_duration ?? 45), min: '5', max: '600' });
    const resolution = el('select', {},
      ...['1080x1920', '1080x1080', '1920x1080'].map((v) => el('option', {
        value: v, text: v, ...(v === settings.resolution ? { selected: true } : {}) })));
    const captionStyle = el('select', {},
      ...CAPTION_STYLES.map(([v, l]) => el('option', {
        value: v, text: l, ...(v === settings.caption_style ? { selected: true } : {}) })));
    const outputDir = el('input', { type: 'text',
      value: settings.output_directory || '' });

    left.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Video' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'form-grid' },
          el('div', { class: 'field' }, el('label', { text: 'Default clip duration (s)' }), clipDuration),
          el('div', { class: 'field' }, el('label', { text: 'Output resolution' }), resolution),
          el('div', { class: 'field' }, el('label', { text: 'Default caption style' }), captionStyle),
          el('div', { class: 'field' }, el('label', { text: 'Output directory' }), outputDir,
            el('div', { class: 'hint', text: 'Clips are written here.' }))))));

    // automation settings
    const interval = el('input', { type: 'number',
      value: String(settings.monitor_interval_minutes ?? 60), min: '1', max: '1440' });
    const concurrency = el('input', { type: 'number',
      value: String(settings.processing_concurrency ?? 1), min: '1', max: '4' });
    const maxAttempts = el('input', { type: 'number',
      value: String(settings.retry_policy?.max_attempts ?? 2), min: '1', max: '5' });
    const keepDays = el('input', { type: 'number',
      value: String(settings.cleanup_policy?.keep_days ?? 30), min: '1', max: '3650' });

    left.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Automation' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'form-grid' },
          el('div', { class: 'field' }, el('label', { text: 'Monitoring interval (min)' }), interval),
          el('div', { class: 'field' }, el('label', { text: 'Processing concurrency' }), concurrency,
            el('div', { class: 'hint', text: 'Transcription is CPU bound. One job at a time is fastest.' })),
          el('div', { class: 'field' }, el('label', { text: 'Max retry attempts' }), maxAttempts),
          el('div', { class: 'field' }, el('label', { text: 'Keep artifacts (days)' }), keepDays)))));

    // storage
    const disk = data.disk || {};
    const storage = data.storage || null;
    left.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Storage' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'kv' },
          el('dt', { text: 'Total' }), el('dd', { text: fmtBytes(disk.total) }),
          el('dt', { text: 'Used' }), el('dd', { text: fmtBytes(disk.used) }),
          el('dt', { text: 'Free' }), el('dd', { text: fmtBytes(disk.free) }),
          ...(storage ? [
            el('dt', { text: 'Used by VIRALCLIPS' }),
            el('dd', { text: fmtBytes(storage.application_bytes) }),
            el('dt', { text: 'Backups' }),
            el('dd', { text: String(storage.backup_count ?? 0) }),
          ] : [])),
        el('div', { style: 'margin-top:12px' },
          el('div', { class: 'fieldset-title', text: 'Directories' }),
          el('div', { class: 'kv' },
            ...Object.entries(data.directories || {}).flatMap(([key, value]) => [
              el('dt', { text: key }),
              el('dd', { class: 'mono', style: 'font-size:11px', text: value }),
            ]))),
        ...(storage ? [
          el('div', { style: 'margin-top:12px' },
            el('div', { class: 'fieldset-title', text: 'Directory sizes' }),
            el('div', { class: 'kv' },
              ...storage.directories.flatMap((row) => [
                el('dt', { text: row.name }),
                el('dd', { text: `${fmtBytes(row.size_bytes)} (${row.file_count} files)` }),
              ]))),
        ] : []))));

    // right: save
    const right = el('div', { class: 'grid', style: 'gap:16px' });
    right.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Apply' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'note',
          text: 'These values are stored locally and applied to newly created tasks and to the worker on its next restart.' }),
        el('button', {
          class: 'btn primary block', style: 'margin-top:14px',
          onclick: async () => {
            try {
              await api('/api/settings', {
                method: 'PATCH',
                body: {
                  settings: {
                    default_clip_duration: Number(clipDuration.value) || 45,
                    resolution: resolution.value,
                    caption_style: captionStyle.value,
                    output_directory: outputDir.value,
                    monitor_interval_minutes: Number(interval.value) || 60,
                    processing_concurrency: Number(concurrency.value) || 1,
                    retry_policy: { max_attempts: Number(maxAttempts.value) || 2 },
                    cleanup_policy: { keep_days: Number(keepDays.value) || 30 },
                  },
                },
              });
              toast('Settings saved.', 'ok');
            } catch (error) { toast(error.message, 'err'); }
          },
        }, icon('check'), 'Save settings'))));

    right.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Maintenance' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'note',
          text: 'A backup is a consistent snapshot of the queue, clips, and settings. Cleanup removes old unpublished media only; approved clips are never touched.' }),
        el('button', {
          class: 'btn block', style: 'margin-top:14px',
          onclick: async () => {
            try {
              const result = await api('/api/storage/backup', {
                method: 'POST', body: { label: 'manual' },
              });
              toast(`Backup created: ${result.name}`, 'ok');
            } catch (error) { toast(error.message, 'err'); }
          },
        }, icon('check'), 'Back up the database'),
        el('button', {
          class: 'btn block', style: 'margin-top:8px',
          onclick: async () => {
            try {
              const preview = await api('/api/storage/cleanup', {
                method: 'POST',
                body: { keep_days: Number(keepDays.value) || 30, dry_run: true },
              });
              if (!preview.removed_clips && !preview.removed_videos) {
                toast('Nothing to clean up.', 'ok');
                return;
              }
              const confirmed = window.confirm(
                `This will delete ${preview.removed_clips} clip(s) and `
                + `${preview.removed_videos} video(s) older than `
                + `${preview.keep_days} days, freeing about `
                + `${preview.freed_mb} MB.\n\nApproved and published clips are kept.\n\nContinue?`);
              if (!confirmed) return;
              const done = await api('/api/storage/cleanup', {
                method: 'POST',
                body: { keep_days: Number(keepDays.value) || 30, dry_run: false },
              });
              toast(`Cleanup freed ${done.freed_mb} MB.`, 'ok');
            } catch (error) { toast(error.message, 'err'); }
          },
        }, icon('check'), 'Clean up old media'))));

    right.append(el('div', { class: 'card' },
      el('div', { class: 'card-head' }, el('h3', { text: 'About' })),
      el('div', { class: 'card-body' },
        el('div', { class: 'kv' },
          el('dt', { text: 'Application' }), el('dd', { text: 'VIRALCLIPS AI 1.0.0' }),
          el('dt', { text: 'Engine' }), el('dd', { text: 'Chopify 1.4.0' }),
          el('dt', { text: 'Runtime' }), el('dd', { text: 'Python 3.11, local only' }),
          el('dt', { text: 'Data directory' }), el('dd', { class: 'mono', style: 'font-size:11px',
            text: (data.directories || {}).data || '—' })),
        el('div', { class: 'note', style: 'margin-top:14px',
          text: 'Everything runs on this machine. No cloud hosting, no external video-processing API.' }))));

    grid.append(left, right);
    frag.append(grid);
    return frag;
  });

/* ══ LIVE STATUS ═════════════════════════════════════════════════════════ */

async function refreshStatus() {
  try {
    const health = await api('/api/health');
    const pill = $('#status-pill');
    const text = $('#status-text');
    const chip = $('#worker-chip');
    const chipText = $('#worker-chip-text');

    const counts = health.worker;
    if (counts.state === 'busy') {
      pill.className = 'status-pill busy';
      text.textContent = `Processing job #${counts.current_job ?? ''}`;
    } else if (counts.alive) {
      pill.className = 'status-pill';
      text.textContent = 'Worker ready';
    } else {
      pill.className = 'status-pill idle';
      text.textContent = 'Worker offline';
    }

    chip.className = `worker-chip ${counts.state === 'busy' ? 'busy' : counts.alive ? 'on' : ''}`;
    chipText.textContent = counts.alive
      ? (counts.state === 'busy' ? `Worker: processing job #${counts.current_job ?? ''}` : 'Worker running')
      : 'Worker not running';
  } catch { /* the status pill is best-effort */ }
}

async function refreshCounters() {
  try {
    const [overview, jobs] = await Promise.all([
      api('/api/overview'), api('/api/jobs?limit=1'),
    ]);
    const set = (id, value) => {
      const node = $(id);
      if (node) node.textContent = String(value);
    };
    set('#nav-channel-count', overview.totals.channels);
    set('#nav-queue-count', (jobs.counts?.queued || 0) + (jobs.counts?.running || 0));
    set('#nav-clip-count', overview.totals.clips_generated);
    const connected = Object.values(overview.accounts || {}).filter((a) => a.connected).length;
    set('#nav-account-count', connected);
  } catch { /* counters are best-effort */ }
}

/* ══ BOOTSTRAP ═══════════════════════════════════════════════════════════ */

async function boot() {
  document.documentElement.setAttribute('data-theme', State.theme);

  try {
    const data = await api('/api/bootstrap');
    State.token = data.token;
    State.config = data.config || {};
    State.settings = data.settings || {};
  } catch (error) {
    $('#view').innerHTML = '';
    $('#view').append(el('div', { class: 'card' },
      el('div', { class: 'card-body' },
        el('div', { class: 'note err' },
          el('strong', { text: 'Cannot reach the VIRALCLIPS AI API. ' }),
          el('span', { text: error.message })))));
    return;
  }

  // navigation
  $$('.nav-item').forEach((item) => {
    item.addEventListener('click', () => {
      navigate(item.dataset.route);
      $('#sidebar').classList.remove('open');
    });
  });

  // theme
  $('#theme-btn').addEventListener('click', () => {
    State.theme = State.theme === 'dark' ? 'light' : 'dark';
    localStorage.setItem('vc-theme', State.theme);
    document.documentElement.setAttribute('data-theme', State.theme);
  });

  $('#refresh-btn').addEventListener('click', () => { render(); refreshStatus(); refreshCounters(); });
  $('#menu-btn').addEventListener('click', () => {
    $('#sidebar').classList.toggle('open');
  });

  // global search
  $('#global-search').addEventListener('input', (event) => {
    State.search = event.target.value.trim().toLowerCase();
    if (['clips', 'library', 'channels', 'editor'].includes(State.route)) render();
  });

  // route from hash
  const hash = (location.hash || '').replace('#/', '');
  if (hash && ROUTES[hash]) {
    State.route = hash;
    $$('.nav-item').forEach((item) => {
      item.classList.toggle('active', item.dataset.route === hash);
    });
  }
  window.addEventListener('hashchange', () => {
    const next = (location.hash || '').replace('#/', '');
    if (ROUTES[next] && next !== State.route) {
      State.route = next;
      $$('.nav-item').forEach((item) => {
        item.classList.toggle('active', item.dataset.route === next);
      });
      render();
    }
  });

  await render();
  refreshStatus();
  refreshCounters();
  setInterval(refreshStatus, 4000);
  setInterval(refreshCounters, 15000);

  // live job updates
  try {
    const events = new EventSource('/api/events');
    events.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.jobs) {
          const queued = (payload.jobs.queued || 0) + (payload.jobs.running || 0);
          const node = $('#nav-queue-count');
          if (node) node.textContent = String(queued);
        }
        if (['queue', 'overview'].includes(State.route)) refreshCounters();
      } catch { /* ignore malformed events */ }
    };
  } catch { /* SSE is optional */ }
}

document.addEventListener('DOMContentLoaded', boot);
