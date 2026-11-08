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

async function render() {
  const entry = ROUTES[State.route] || ROUTES.overview;
  const view = $('#view');
  view.innerHTML = '';
  try {
    const data = await entry.loader();
    view.innerHTML = '';
    view.append(entry.renderer(data));
  } catch (error) {
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
      el('th', { text: 'Approval' }), el('th', { text: 'Published' }))));
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
        el('td', {}, statusBadge(clip.publish_status))));
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
        el('th', { text: 'Status' }), el('th', { class: 'num', text: '' }))));
      const tbody = el('tbody');
      for (const episode of episodes) {
        tbody.append(el('tr', {},
          el('td', {}, el('div', { style: 'max-width:340px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap',
            text: episode.title || 'Untitled episode' })),
          el('td', { class: 'mono', style: 'font-size:12px;color:var(--fg-muted)',
            text: episode.video_id }),
          el('td', { style: 'font-size:12px;color:var(--fg-muted)',
            text: fmtWhen(episode.published_at) }),
          el('td', { style: 'font-size:12px;color:var(--fg-muted)',
            text: fmtWhen(episode.detected_at) }),
          el('td', {}, statusBadge(episode.processed_at ? 'completed' : 'pending')),
          el('td', { class: 'num' }, el('a', {
            class: 'btn sm ghost',
            href: episode.url, target: '_blank', rel: 'noopener',
          }, 'Open'))));
      }
      table.append(tbody);
      body.append(el('div', { class: 'table-wrap' }, table));
    }
    frag.append(el('div', { class: 'card', style: 'margin-top:16px' },
      el('div', { class: 'card-head' }, el('h3', { text: 'Detected episodes' })),
      body));

    return frag;
  });

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

registerRoute('clips',
  async () => api('/api/clips?limit=300'),
  (data) => {
    const frag = document.createDocumentFragment();
    const clips = data.clips || [];
    const pending = clips.filter((c) => c.approval_status === 'pending');

    frag.append(el('div', { class: 'page-head' },
      el('div', {},
        el('h1', { text: 'Generated Clips' }),
        el('div', { class: 'sub',
          text: `${fmt(clips.length)} clip(s) · ${fmt(pending.length)} awaiting approval.` })),
      el('div', { class: 'actions' },
        pending.length
          ? el('button', { class: 'btn success', onclick: () => batchApprove(pending.map((c) => c.id), 'approve') },
              icon('check'), `Approve all ${pending.length}`)
          : null,
        el('button', { class: 'btn', onclick: () => render() }, icon('refresh'), 'Refresh'))));

    if (!clips.length) {
      frag.append(el('div', { class: 'card' },
        el('div', { class: 'card-body' },
          emptyState('No clips generated yet',
            'Run a task or upload a video. Generated vertical clips will appear here for review.', 'video'))));
      return frag;
    }

    const grid = el('div', { class: 'clip-grid' });
    for (const clip of clips) {
      grid.append(clipCard(clip));
    }
    frag.append(grid);
    return frag;
  });

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

    const player = el('div', { class: 'player' });
    if (full.file_path) {
      player.append(el('video', {
        src: `/media/clip/${full.id}`,
        controls: true,
        preload: 'metadata',
        poster: full.poster_path ? `/media/clip/${full.id}/poster` : null,
      }));
    } else {
      player.append(el('div', { class: 'empty', text: 'No rendered video for this clip.' }));
    }

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
