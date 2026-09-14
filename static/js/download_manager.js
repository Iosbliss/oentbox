document.addEventListener('DOMContentLoaded', () => {
  const queueEl = document.getElementById('downloadQueue');
  if (!queueEl) return;

  const toolbarEl = document.getElementById('downloadToolbar');
  const tabsEl = document.getElementById('downloadTabs');
  const clearBtn = document.getElementById('downloadClear');
  const STORAGE_KEY = 'nw_downloads_v1';
  const POLL_MS = 900;
  let filter = 'all';
  const timers = new Map();

  const escapeHtml = (value) => String(value || '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));

  /* ---------- persistence ---------- */
  const loadItems = () => {
    try {
      const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      return Array.isArray(raw) ? raw : [];
    } catch (error) {
      return [];
    }
  };
  const saveItems = (items) => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(items)); } catch (error) { /* storage unavailable */ }
  };
  let items = loadItems();
  const findItem = (id) => items.find((entry) => entry.id === id);
  const upsertItem = (id, patch) => {
    const entry = findItem(id);
    if (entry) Object.assign(entry, patch);
    saveItems(items);
    return entry;
  };

  /* ---------- helpers ---------- */
  const isYouTubeUrl = (url) => {
    try { return /(^|\.)youtube\.com$|(^|\.)youtu\.be$/.test(new URL(url).hostname); }
    catch (error) { return false; }
  };
  const formatBytes = (bytes) => {
    if (!bytes) return '';
    const units = ['B', 'KB', 'MB', 'GB'];
    let value = bytes; let unit = 0;
    while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit += 1; }
    return `${value.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
  };
  const formatSpeed = (bytesPerSec) => (bytesPerSec ? `${formatBytes(bytesPerSec)}/s` : '');
  const formatEta = (seconds) => {
    if (!seconds && seconds !== 0) return '';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return m > 0 ? `${m}m ${s}s left` : `${s}s left`;
  };
  const typeLabel = (item) => {
    if (item.kind !== 'youtube') return item.label || 'Download';
    if (item.format === 'audio' || item.format === 'audio_mp3') return 'YouTube · Audio';
    return 'YouTube · Video';
  };
  const isActiveStatus = (status) => ['starting', 'downloading', 'pausing', 'cancelling'].includes(status);

  const ICONS = {
    video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M15 10l4.5-3v10L15 14"/><rect x="2.5" y="6" width="12.5" height="12" rx="2.2"/></svg>',
    audio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/></svg>',
    file: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>',
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>',
    alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01"/><circle cx="12" cy="12" r="9"/></svg>',
    pause: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M7 4l14 8-14 8V4z"/></svg>',
    close: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    retry: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11A8 8 0 105.5 16.5M20 11V5m0 6h-6"/></svg>',
    save: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>',
    external: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><path d="M15 3h6v6M10 14L21 3"/></svg>',
  };
  const rowIcon = (item) => {
    if (item.status === 'complete') return ICONS.check;
    if (item.status === 'error') return ICONS.alert;
    if (item.kind === 'youtube') return item.format && item.format.startsWith('audio') ? ICONS.audio : ICONS.video;
    return ICONS.file;
  };

  /* ---------- rendering ---------- */
  const statusText = (item) => {
    switch (item.status) {
      case 'starting': return 'Starting...';
      case 'downloading': {
        const parts = [item.progress != null ? `${item.progress}%` : 'Downloading'];
        const speed = formatSpeed(item.speed);
        const eta = formatEta(item.eta);
        if (speed) parts.push(speed);
        if (eta) parts.push(eta);
        return parts.join(' · ');
      }
      case 'pausing': return 'Pausing...';
      case 'paused': return `Paused${item.progress ? ` at ${item.progress}%` : ''}`;
      case 'cancelling': return 'Cancelling...';
      case 'complete': return item.autoSaved ? 'Saved to your device' : 'Ready to save';
      case 'error': return item.detail || 'Download failed';
      case 'ready': return 'Ready — hosted by an external provider';
      default: return item.detail || '';
    }
  };

  const rowActions = (item) => {
    const btn = (key, icon, label, extra = '') => `<button class="download-row__btn ${extra}" data-action="${key}" data-id="${item.id}" aria-label="${label}" title="${label}">${icon}</button>`;
    if (item.kind === 'external') {
      return `${btn('open', ICONS.external, 'Open download')}${btn('remove', ICONS.close, 'Remove', 'download-row__btn--danger')}`;
    }
    switch (item.status) {
      case 'starting':
      case 'downloading':
        return `${btn('pause', ICONS.pause, 'Pause')}${btn('cancel', ICONS.close, 'Cancel', 'download-row__btn--danger')}`;
      case 'pausing':
        return btn('pause', ICONS.pause, 'Pausing', 'is-spinning') + `<button class="download-row__btn" disabled aria-hidden="true">${ICONS.close}</button>`;
      case 'paused':
        return `${btn('resume', ICONS.play, 'Resume', 'download-row__btn--primary')}${btn('cancel', ICONS.close, 'Remove', 'download-row__btn--danger')}`;
      case 'cancelling':
        return `<button class="download-row__btn is-spinning" disabled aria-hidden="true">${ICONS.retry}</button>`;
      case 'complete':
        return `${btn('save', ICONS.save, item.autoSaved ? 'Save again' : 'Save file', item.autoSaved ? '' : 'download-row__btn--primary')}${btn('remove', ICONS.close, 'Remove', 'download-row__btn--danger')}`;
      case 'error':
        return `${btn('retry', ICONS.retry, 'Retry')}${btn('remove', ICONS.close, 'Remove', 'download-row__btn--danger')}`;
      default:
        return btn('remove', ICONS.close, 'Remove', 'download-row__btn--danger');
    }
  };

  const rowClass = (item) => {
    const map = { complete: 'is-complete', error: 'is-error', paused: 'is-paused' };
    return map[item.status] || '';
  };

  const emptyState = () => `<div class="download-empty">
    <svg width="46" height="46" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4"/><path d="M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
    <strong>Nothing downloading yet</strong>
    <span>Downloads you start from Browse or YouTube videos will show up here — you can pause and resume anytime.</span>
    <a class="btn btn--primary" href="/youtube.html">Find videos</a>
  </div>`;

  const visibleItems = () => items.filter((item) => {
    if (filter === 'active') return isActiveStatus(item.status);
    if (filter === 'done') return item.status === 'complete' || item.status === 'error';
    return true;
  });

  /* Rows are patched in place on every poll tick instead of being torn down and
     rebuilt, so only the text/width/class that actually changed repaints — a full
     innerHTML rebuild would replay the row's entrance animation every tick and
     look like the whole list is blinking. */
  const rowRefs = new Map();

  const rowMarkup = (item) => {
    const progress = item.status === 'complete' ? 100 : (item.progress || 0);
    const indeterminate = item.status === 'starting' && !item.progress;
    return `<article class="download-row ${rowClass(item)} ${indeterminate ? 'is-indeterminate' : ''}" data-id="${item.id}">
        <div class="download-row__icon" aria-hidden="true">${rowIcon(item)}</div>
        <div class="download-row__body">
          <p class="download-row__title">${escapeHtml(item.title)}</p>
          <div class="download-row__meta"><span class="${isActiveStatus(item.status) ? 'is-live' : ''}">${escapeHtml(typeLabel(item))}</span><span>·</span><span>${escapeHtml(statusText(item))}</span></div>
          ${item.kind === 'external' ? '' : `<div class="download-row__track"><span style="width:${progress}%"></span></div>`}
        </div>
        <div class="download-row__actions" data-sig="${item.status}">${rowActions(item)}</div>
      </article>`;
  };

  const createRowElement = (item) => {
    const wrapper = document.createElement('div');
    wrapper.innerHTML = rowMarkup(item).trim();
    const el = wrapper.firstElementChild;
    el.classList.add('is-entering');
    el.addEventListener('animationend', () => el.classList.remove('is-entering'), { once: true });
    return el;
  };

  const patchRowElement = (el, item) => {
    const indeterminate = item.status === 'starting' && !item.progress;
    const entering = el.classList.contains('is-entering');
    el.className = `download-row ${rowClass(item)} ${indeterminate ? 'is-indeterminate' : ''} ${entering ? 'is-entering' : ''}`.trim();

    const icon = el.querySelector('.download-row__icon');
    const nextIcon = rowIcon(item);
    if (icon.innerHTML !== nextIcon) icon.innerHTML = nextIcon;

    const title = el.querySelector('.download-row__title');
    if (title.textContent !== item.title) title.textContent = item.title;

    const meta = el.querySelector('.download-row__meta');
    const nextMeta = `<span class="${isActiveStatus(item.status) ? 'is-live' : ''}">${escapeHtml(typeLabel(item))}</span><span>·</span><span>${escapeHtml(statusText(item))}</span>`;
    if (meta.innerHTML !== nextMeta) meta.innerHTML = nextMeta;

    const trackSpan = el.querySelector('.download-row__track span');
    if (trackSpan) {
      const progress = item.status === 'complete' ? 100 : (item.progress || 0);
      trackSpan.style.width = `${progress}%`;
    }

    const actions = el.querySelector('.download-row__actions');
    if (actions.dataset.sig !== item.status) {
      actions.innerHTML = rowActions(item);
      actions.dataset.sig = item.status;
    }
  };

  const render = () => {
    const hasAny = items.length > 0;
    if (toolbarEl) toolbarEl.hidden = !hasAny;
    if (clearBtn) clearBtn.disabled = !items.some((item) => item.status === 'complete' || item.status === 'error');

    const visible = visibleItems();
    const visibleIds = new Set(visible.map((item) => item.id));

    rowRefs.forEach((el, id) => {
      if (!visibleIds.has(id)) { el.remove(); rowRefs.delete(id); }
    });

    if (!visible.length) {
      queueEl.innerHTML = hasAny
        ? '<div class="download-empty"><strong>No downloads in this view</strong><span>Switch tabs to see other downloads.</span></div>'
        : emptyState();
      return;
    }

    if (queueEl.querySelector('.download-empty')) queueEl.innerHTML = '';

    let previousEl = null;
    visible.forEach((item) => {
      let el = rowRefs.get(item.id);
      if (!el) {
        el = createRowElement(item);
        rowRefs.set(item.id, el);
        if (previousEl) previousEl.after(el); else queueEl.prepend(el);
      } else if (previousEl ? previousEl.nextElementSibling !== el : queueEl.firstElementChild !== el) {
        if (previousEl) previousEl.after(el); else queueEl.prepend(el);
      }
      patchRowElement(el, item);
      previousEl = el;
    });
  };

  /* ---------- polling ---------- */
  const stopPolling = (id) => {
    const timer = timers.get(id);
    if (timer) { clearTimeout(timer); timers.delete(id); }
  };

  const pollStatus = (id) => {
    const item = findItem(id);
    if (!item || item.kind !== 'youtube' || !item.jobId) return;
    stopPolling(id);
    const tick = async () => {
      const current = findItem(id);
      if (!current || !isActiveStatus(current.status)) return;
      try {
        const response = await fetch(`/api/youtube/download/${encodeURIComponent(current.jobId)}/`);
        if (response.status === 404) {
          upsertItem(id, { status: 'error', detail: 'Download session ended. Please retry.' });
          render();
          return;
        }
        const job = await response.json();
        if (!response.ok) throw new Error(job.error || 'Status unavailable.');
        upsertItem(id, {
          status: job.status, progress: job.progress || 0, detail: job.detail || '',
          speed: job.speed || 0, eta: job.eta, totalBytes: job.total_bytes || 0,
        });
        // The moment a job finishes, save it straight to the device — no extra
        // tap needed. Guarded by autoSaved so it only fires once per job, even
        // though this tick can re-run after a re-render.
        if (job.status === 'complete' && !current.autoSaved) {
          upsertItem(id, { autoSaved: true });
          saveFile(id);
        }
        render();
        if (isActiveStatus(job.status)) {
          timers.set(id, setTimeout(tick, POLL_MS));
        }
      } catch (error) {
        upsertItem(id, { status: 'error', detail: error.message || 'Download failed.' });
        render();
      }
    };
    tick();
  };

  /* ---------- actions ---------- */
  const startYouTubeJob = async (id) => {
    const item = findItem(id);
    if (!item) return;
    upsertItem(id, { status: 'starting', progress: 0, detail: 'Preparing your download...', jobId: '' });
    render();
    try {
      const response = await fetch('/api/youtube/download/', {
        method: 'POST',
        headers: {...(window.nwCsrfHeaders?.() || {}), 'Content-Type': 'application/json'},
        body: JSON.stringify({url: item.url, format: item.format}),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Could not start download.');
      upsertItem(id, { jobId: payload.job_id, status: 'starting' });
      render();
      pollStatus(id);
    } catch (error) {
      upsertItem(id, { status: 'error', detail: error.message || 'Download failed.' });
      render();
    }
  };

  const controlJob = async (id, action) => {
    const item = findItem(id);
    if (!item || !item.jobId) return;
    try {
      const csrfCookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
      const csrfToken = csrfCookie ? decodeURIComponent(csrfCookie.split('=')[1]) : '';
      const response = await fetch(`/api/youtube/download/${encodeURIComponent(item.jobId)}/${action}/`, {
        method: 'POST',
        headers: window.nwCsrfHeaders?.() || {'X-CSRFToken': csrfToken},
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload.error || 'Action failed.');
      upsertItem(id, { status: payload.status || item.status });
      render();
      if (action === 'resume') pollStatus(id);
      if (['pause', 'cancel'].includes(action)) {
        // let the next poll tick (already scheduled) or a quick one pick up the final state
        setTimeout(() => pollStatus(id), 400);
      }
    } catch (error) {
      render();
    }
  };

  const removeItem = async (id) => {
    const item = findItem(id);
    if (!item) return;
    stopPolling(id);
    if (item.kind === 'youtube' && item.jobId) {
      const csrfCookie = document.cookie.split('; ').find(row => row.startsWith('csrftoken='));
      const csrfToken = csrfCookie ? decodeURIComponent(csrfCookie.split('=')[1]) : '';
      try { await fetch(`/api/youtube/download/${encodeURIComponent(item.jobId)}/cancel/`, { method: 'POST', headers: window.nwCsrfHeaders?.() || {'X-CSRFToken': csrfToken} }); }
      catch (error) { /* best effort */ }
    }
    items = items.filter((entry) => entry.id !== id);
    saveItems(items);
    render();
  };

  const saveFile = (id) => {
    const item = findItem(id);
    if (!item || !item.jobId) return;
    const link = document.createElement('a');
    link.href = `/api/youtube/download/${encodeURIComponent(item.jobId)}/file/`;
    link.click();
  };

  queueEl.addEventListener('click', (event) => {
    const button = event.target.closest('.download-row__btn[data-action]');
    if (!button) return;
    const { action, id } = button.dataset;
    if (action === 'pause') controlJob(id, 'pause');
    else if (action === 'resume') controlJob(id, 'resume');
    else if (action === 'cancel') removeItem(id);
    else if (action === 'remove') removeItem(id);
    else if (action === 'save') saveFile(id);
    else if (action === 'retry') startYouTubeJob(id);
    else if (action === 'open') {
      const item = findItem(id);
      if (item) window.open(item.url, '_blank', 'noopener');
    }
  });

  if (tabsEl) {
    tabsEl.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (!chip) return;
      filter = chip.dataset.filter || 'all';
      tabsEl.querySelectorAll('.chip').forEach((el) => {
        const active = el === chip;
        el.classList.toggle('is-active', active);
        el.setAttribute('aria-selected', String(active));
      });
      render();
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', async () => {
      const toRemove = items.filter((item) => item.status === 'complete' || item.status === 'error');
      for (const item of toRemove) {
        if (item.kind === 'youtube' && item.jobId) {
          try { await fetch(`/api/youtube/download/${encodeURIComponent(item.jobId)}/cancel/`, { method: 'POST', headers: window.nwCsrfHeaders?.() }); }
          catch (error) { /* best effort */ }
        }
      }
      const removeIds = new Set(toRemove.map((item) => item.id));
      items = items.filter((item) => !removeIds.has(item.id));
      saveItems(items);
      render();
    });
  }

  /* ---------- bootstrap: add item from query params, then resume any in-flight jobs ---------- */
  const params = new URLSearchParams(window.location.search);
  const incomingUrl = params.get('url');
  if (incomingUrl) {
    const format = params.get('format') || 'video';
    const title = params.get('title') || 'Download';
    const label = params.get('label') || format.replace('_', ' ').toUpperCase();
    const youTube = isYouTubeUrl(incomingUrl);
    const id = `dl_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    const newItem = {
      id, kind: youTube ? 'youtube' : 'external', url: incomingUrl, format, title, label,
      status: youTube ? 'starting' : 'ready', progress: 0, detail: '', jobId: '', addedAt: Date.now(),
    };
    items.unshift(newItem);
    saveItems(items);
    window.history.replaceState({}, '', window.location.pathname);
    render();
    if (youTube) startYouTubeJob(id);
  } else {
    render();
  }

  items.filter((item) => item.kind === 'youtube' && isActiveStatus(item.status) && item.jobId).forEach((item) => pollStatus(item.id));
});
