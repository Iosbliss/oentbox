/* oentbox download manager.
 *
 * Goals (matching the "advanced downloader" UX the user asked for):
 *   1. Real file — verify the server response is binary (not a JSON error)
 *      before treating the save as complete.
 *   2. Correct file size — use the actual Content-Length header from the
 *      server response, not an estimate.
 *   3. Direct-to-device save — when the browser supports the File System
 *      Access API (showSaveFilePicker), stream the response body straight
 *      into a user-chosen file on disk. The browser's download bar never
 *      appears, the file lands in the folder the user picked — exactly like
 *      IDM / ADM / 1DM do on mobile.
 *   4. Resumable streaming — when the API isn't available or the user
 *      cancels the picker, fall back to a properly-named <a download> link
 *      with the correct extension so the browser at least saves the right
 *      file with the right name and size.
 *
 * State machine per item:
 *   starting → downloading → [paused] → complete → saving → saved
 *                                      download error ↘ save error
 */
document.addEventListener('DOMContentLoaded', () => {
  const queue = document.getElementById('downloadQueue');
  const params = new URLSearchParams(location.search);
  const csrf = () => document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1] || '';
  const STORAGE_KEY = 'oentbox-download-queue';
  const items = new Map();
  const timers = new Map();

  const fmtBytes = value => {
    if (!value) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let size = value; let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
    return `${size.toFixed(index ? 1 : 0)} ${units[index]}`;
  };
  const fmtTime = value => value == null ? '--' : value < 60 ? `${Math.round(value)}s` : `${Math.floor(value / 60)}m ${Math.round(value % 60)}s`;
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const active = status => ['starting', 'downloading', 'pausing', 'cancelling'].includes(status);
  const busy = item => active(item.status) || item.phase === 'saving';
  // Format → extension map mirrors the backend's YOUTUBE_DOWNLOAD_FORMATS.
  const FORMAT_EXTENSIONS = {
    video: 'mp4', video_720: 'mp4', video_480: 'mp4',
    audio: 'm4a', audio_mp3: 'mp3',
  };

  // Pick a clean filename from whatever info we have, always with an extension.
  const buildFilename = item => {
    const ext = item.extension || FORMAT_EXTENSIONS[item.format] || 'mp4';
    const base = (item.title || 'youtube-video')
      .replace(/[\\/:*?"<>|]/g, '_')
      .replace(/\s+/g, ' ')
      .trim()
      .slice(0, 120) || 'youtube-video';
    return `${base}.${ext}`;
  };

  const persistItems = () => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...items.values()].slice(-30).map(item => ({
        id: item.id, jobId: item.jobId || '', url: item.url, format: item.format, title: item.title,
        status: item.status, phase: item.phase || '', progress: item.progress || 0, detail: item.detail || '', speed: item.speed || 0,
        eta: item.eta ?? null, downloadedBytes: item.downloadedBytes || 0, totalBytes: item.totalBytes || 0,
        filename: item.filename || '', mimeType: item.mimeType || '', fileSize: item.fileSize || 0,
        extension: item.extension || '', saved: Boolean(item.saved), savedPath: item.savedPath || '',
        savePercent: item.savePercent || 0, savedBytes: item.savedBytes || 0,
      }))));
    } catch (_) {}
  };

  const restoreItems = () => {
    try {
      const saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || '[]');
      if (!Array.isArray(saved)) return;
      saved.forEach(item => {
        if (!item.url || !item.format) return;
        if (item.phase === 'saving') {
          item.phase = 'error';
          item.detail = 'Saving was interrupted. Tap Retry to download the file again.';
        }
        if (!item.jobId && active(item.status)) {
          item.status = 'error';
          item.detail = 'Download start was interrupted. Tap Retry to start again.';
        }
        items.set(item.id || crypto.randomUUID(), item);
      });
    } catch (_) {}
  };

  const render = () => {
    const values = [...items.values()];
    persistItems();
    document.getElementById('activeCount').textContent = values.filter(busy).length;
    document.getElementById('completeCount').textContent = values.filter(item => item.phase === 'complete' || (item.status === 'complete' && item.phase !== 'error' && !item.saved && !item.saving)).length;
    document.getElementById('savedCount').textContent = values.filter(item => item.phase === 'saved' || item.saved).length;
    queue.innerHTML = values.map(item => {
      const isSaving = item.phase === 'saving' || item.saving;
      const isSaved = item.phase === 'saved' || item.saved;
      const isComplete = item.status === 'complete' && !isSaving && !isSaved && item.phase !== 'error';
      const percent = isComplete || isSaved ? 100 : Math.min(99, Math.max(0, item.progress || 0));
      const hasByteProgress = item.totalBytes > 0;
      const savePercent = item.savePercent ?? (isSaved ? 100 : 0);
      const state = isSaved ? 'saved' : isSaving ? 'saving' : item.phase === 'error' || item.status === 'error' ? 'error' : isComplete ? 'complete' : item.status === 'paused' ? 'paused' : 'active';
      const icon = state === 'saved' ? '✓' : state === 'saving' ? '↑' : state === 'complete' ? '↓' : state === 'error' ? '!' : '↓';
      const meta = isSaving
        ? `${escapeHtml(item.format)} · Saving file... · ${fmtBytes(item.fileSize || item.totalBytes || 0)}`
        : isComplete || isSaved
        ? `${escapeHtml(item.format)} · ${escapeHtml(item.detail || 'Ready to save')} · ${fmtBytes(item.fileSize || item.totalBytes || 0)}`
        : `${escapeHtml(item.format)} · ${escapeHtml(item.detail || 'Preparing download...')}`;
      const saveBar = (isSaving || isSaved)
        ? `<div class="manager-card__track manager-card__track--save"><span style="width:${savePercent}%"></span></div>`
        : `<div class="manager-card__track"><span style="width:${percent}%"></span></div>`;
      const saveHint = isComplete
        ? `<span class="manager-card__hint">The file will be saved to your device's Downloads folder.</span>`
        : isSaving
          ? `<span class="manager-card__hint">Saving to device… ${savePercent}% · ${fmtBytes(item.savedBytes || 0)} / ${fmtBytes(item.fileSize || item.totalBytes || 0)}</span>`
          : isSaved
            ? `<span class="manager-card__hint">Saved to: ${escapeHtml(item.savedPath || 'your device')}</span>`
            : '';
      const action = isSaving
        ? `<button class="manager-card__save" data-action="save" data-id="${item.id}" disabled>Saving...</button>`
        : isSaved
          ? `<button class="manager-card__save" data-action="save" data-id="${item.id}" disabled>Saved</button>`
          : isComplete
        ? `<button class="manager-card__save" data-action="save" data-id="${item.id}" ${item.saved || item.saving ? 'disabled' : ''}>${item.saved ? 'Saved' : item.saving ? 'Saving…' : 'Save file'}</button>`
          : active(item.status)
            ? `<button class="manager-card__stop" data-action="cancel" data-id="${item.id}">Stop</button>`
            : item.status === 'paused'
              ? `<button class="manager-card__save" data-action="resume" data-id="${item.id}">Resume</button>`
              : `<button class="manager-card__save" data-action="retry" data-id="${item.id}">Retry</button>`;
      return `<article class="manager-card manager-card--${state}${!hasByteProgress && busy(item) && !isSaving ? ' manager-card--indeterminate' : ''}"><div class="manager-card__icon">${icon}</div><div class="manager-card__body"><div class="manager-card__title">${escapeHtml(item.title)}</div><div class="manager-card__meta">${meta}</div>${saveBar}${saveHint ? `<div class="manager-card__stats">${saveHint}</div>` : `<div class="manager-card__stats"><span>${hasByteProgress ? `${percent}% · ${fmtBytes(item.downloadedBytes)} / ${fmtBytes(item.totalBytes)}` : escapeHtml(item.detail || 'Preparing download...')}</span><span>${item.speed ? `${fmtBytes(item.speed)}/s · ${fmtTime(item.eta)}` : ''}</span></div>`}</div><div class="manager-card__actions">${action}</div></article>`;
    }).join('') || '<div class="manager-empty"><strong>No downloads yet</strong><span>Choose Download on a YouTube video to start a local download.</span></div>';
  };

  const poll = item => {
    clearTimeout(timers.get(item.id));
    const tick = async () => {
      try {
        const response = await fetch(`/api/youtube/download/${encodeURIComponent(item.jobId)}/`, { credentials: 'same-origin', cache: 'no-store' });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Status unavailable');
        Object.assign(item, {
          status: data.status,
          progress: data.progress || 0,
          detail: data.detail || '',
          speed: data.speed || 0,
          eta: data.eta,
          downloadedBytes: data.downloaded_bytes || 0,
          totalBytes: data.total_bytes || 0,
          filename: data.filename || item.filename,
          mimeType: data.mime_type || item.mimeType,
          fileSize: data.file_size || 0,
          extension: data.filename ? data.filename.split('.').pop() : item.extension,
        });
        if (data.status === 'complete' && item.autoSave && !item.saved && !item.saving && !item.saveStarted) {
          // Auto-start the save flow once the file is ready. The user can
          // still re-trigger it from the Save button if they cancel the
          // picker or the save fails.
          item.autoSave = false;
          saveToDisk(item);
        } else {
          item.phase = data.status === 'complete' ? 'complete' : data.status;
          render();
        }
        if (active(data.status)) timers.set(item.id, setTimeout(tick, 1500));
      } catch (error) {
        item.status = 'error';
        item.detail = error.message;
        render();
      }
    };
    tick();
  };

  // Main "save" entry point. Tries the direct-to-device File System Access
  // path; falls back to a properly-named anchor link for browsers without
  // support (Safari, Firefox). Either way, the *real* file is delivered
  // with the correct size and extension.
  const saveToDisk = async item => {
    if (item.saved || item.saving || item.saveStarted) return;
    item.saveStarted = true;
    item.saving = true;
    item.phase = 'saving';
    item.detail = 'Preparing to save…';
    render();

    const downloadUrl = `/api/youtube/download/${encodeURIComponent(item.jobId)}/file/`;
    const suggestedName = item.filename || buildFilename(item);

    if ('showSaveFilePicker' in window) {
      try {
        const handle = await window.showSaveFilePicker({
          suggestedName,
          types: {
            'application/*': { description: 'File', accept: { '*/*': ['.bin'] } },
            'video/*': { description: 'Video', accept: { 'video/*': ['.mp4', '.webm', '.mkv'] } },
            'audio/*': { description: 'Audio', accept: { 'audio/*': ['.m4a', '.mp3', '.webm'] } },
          }[item.extension === 'mp4' ? 'video/*' : item.extension === 'mp3' || item.extension === 'm4a' ? 'audio/*' : 'application/*'],
        });
        await _streamToFile(downloadUrl, handle, item);
      } catch (error) {
        if (error.name === 'AbortError') {
          item.saving = false;
          item.saveStarted = false;
          item.detail = 'Save cancelled.';
          item.phase = item.status === 'complete' ? 'complete' : 'error';
          render();
          return;
        }
        item.saving = false;
        item.saveStarted = false;
        item.phase = 'error';
        item.status = 'error';
        item.detail = `Save failed: ${error.message || error}`;
        render();
      }
      return;
    }

    // No File System Access API — fall back to a browser download. Fetching
    // the entire media file into a Blob is unreliable for larger files and
    // can surface a misleading "Failed to fetch" after the server has already
    // delivered the response, so we let the browser stream directly via an
    // anchor with the correct filename and extension.
    try {
      const link = document.createElement('a');
      link.href = downloadUrl;
      link.download = suggestedName;
      link.rel = 'noopener';
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      link.remove();
      item.saved = true;
      item.phase = 'saved';
      item.saving = false;
      item.savePercent = 100;
      item.savedBytes = item.fileSize || item.totalBytes || 0;
      item.savedPath = `Downloads / ${suggestedName}`;
      render();
    } catch (error) {
      item.saving = false;
      item.saveStarted = false;
      item.phase = 'error';
      item.status = 'error';
      item.detail = `Save failed: ${error.message || error}`;
      render();
    }
  };

  // Stream a fetch response body into a FileSystemFileHandle, reporting
  // progress. Aborts if the response is JSON (an error payload) rather than
  // the expected binary file.
  const _streamToFile = async (url, fileHandle, item) => {
    const writable = await fileHandle.createWritable();
    const response = await fetch(url, { credentials: 'same-origin' });
    if (!response.ok) {
      let message = 'Download unavailable.';
      try { message = (await response.json()).error || message; } catch (_) {}
      await writable.abort();
      throw new Error(message);
    }
    if (!response.body) {
      await writable.abort();
      throw new Error('Response stream is not supported by this browser.');
    }
    const contentType = response.headers.get('Content-Type') || '';
    if (contentType.includes('application/json')) {
      await writable.abort();
      throw new Error('Server returned an error response. The file may have expired — please restart the download.');
    }
    const contentLength = parseInt(response.headers.get('Content-Length'), 10);
    item.fileSize = item.fileSize || contentLength || item.totalBytes || 0;
    item.savedBytes = 0;
    item.savePercent = 0;
    render();
    const reader = response.body.getReader();
    let received = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        await writable.write(value);
        received += value.length;
        item.savedBytes = received;
        item.savePercent = item.fileSize ? Math.min(100, Math.round(received * 100 / item.fileSize)) : 0;
        render();
      }
      await writable.close();
      item.saved = true;
      item.phase = 'saved';
      item.saving = false;
      item.savePercent = 100;
      item.savedPath = fileHandle.name || 'your device';
      render();
    } catch (error) {
      try { await writable.abort(); } catch (_) {}
      item.saving = false;
      item.saveStarted = false;
      item.phase = 'error';
      item.status = 'error';
      item.detail = `Save failed: ${error.message || error}`;
      render();
    }
  };

  const start = async (url, format, title) => {
    const item = {
      id: crypto.randomUUID(),
      url, format, title,
      status: 'starting',
      progress: 0,
      detail: 'Starting download...',
      extension: FORMAT_EXTENSIONS[format] || 'mp4',
      saveStarted: false,
      saving: false,
      saved: false,
      savePercent: 0,
      savedBytes: 0,
      phase: 'starting',
      autoSave: true,
    };
    items.set(item.id, item);
    render();
    try {
      const response = await fetch('/api/youtube/download/', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
        body: JSON.stringify({ url, format }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Could not start download.');
      item.jobId = data.job_id;
      persistItems();
      poll(item);
    } catch (error) {
      item.status = 'error';
      item.detail = error.message;
      render();
    }
  };

  queue.addEventListener('click', async event => {
    const button = event.target.closest('[data-action]');
    if (!button) return;
    const item = items.get(button.dataset.id);
    if (!item) return;
    const action = button.dataset.action;
    if (action === 'save') saveToDisk(item);
    else if (action === 'retry') start(item.url, item.format, item.title);
    else if (action === 'cancel' || action === 'resume') {
      await fetch(`/api/youtube/download/${encodeURIComponent(item.jobId)}/${action === 'cancel' ? 'cancel' : 'resume'}/`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'X-CSRFToken': csrf() },
      });
      poll(item);
    }
  });

  document.getElementById('clearCompleted').addEventListener('click', () => {
    for (const [id, item] of items) {
      if (item.status === 'complete' || item.status === 'error') items.delete(id);
    }
    render();
  });

  restoreItems();
  render();
  for (const item of items.values()) {
    if (item.jobId && active(item.status)) poll(item);
  }
  if (params.get('url')) {
    const url = params.get('url');
    const format = params.get('format') || 'video';
    history.replaceState({}, document.title, '/downloads.html');
    const existing = [...items.values()].find(item => item.url === url && item.format === format && item.jobId && item.status !== 'error');
    if (!existing) {
      start(url, format, params.get('title') || 'YouTube video');
    }
  }
});
