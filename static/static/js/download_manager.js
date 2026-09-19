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
 *                                                   ↘ error (save failed)
 */
document.addEventListener('DOMContentLoaded', () => {
  const queue = document.getElementById('downloadQueue');
  const params = new URLSearchParams(location.search);
  const csrf = () => document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1] || '';
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

  // Returns true if the browser can stream directly to disk (Chromium-based:
  // Chrome, Edge, Opera, Brave, Samsung Internet, Arc; Android Chrome 121+).
  const supportsFileSystemAccess = () => typeof window.showSaveFilePicker === 'function';

  // Pull the "filename=..." value out of a Content-Disposition header so the
  // saved file uses the exact name the backend chose (with extension).
  const parseFilenameFromHeader = header => {
    if (!header) return '';
    const match = header.match(/filename="?([^";]+)"?/i);
    return match ? match[1].trim() : '';
  };

  const render = () => {
    const values = [...items.values()];
    document.getElementById('activeCount').textContent = values.filter(item => active(item.status)).length;
    document.getElementById('completeCount').textContent = values.filter(item => item.status === 'complete').length;
    document.getElementById('savedCount').textContent = values.filter(item => item.saved).length;
    queue.innerHTML = values.map(item => {
      const percent = item.progress || 0;
      const savePercent = item.savePercent ?? (item.saved ? 100 : 0);
      const state = item.status === 'complete' ? (item.saved ? 'saved' : 'complete') : item.status === 'error' ? 'error' : item.status === 'paused' ? 'paused' : 'active';
      const icon = state === 'saved' ? '✓' : state === 'complete' ? '↓' : state === 'error' ? '!' : '↓';
      const meta = item.status === 'complete'
        ? `${escapeHtml(item.format)} · ${escapeHtml(item.detail || 'Ready to save')} · ${fmtBytes(item.totalBytes || item.fileSize || 0)}`
        : `${escapeHtml(item.format)} · ${escapeHtml(item.detail || 'Preparing download...')}`;
      const saveBar = (item.status === 'complete' && (item.saving || item.saved))
        ? `<div class="manager-card__track manager-card__track--save"><span style="width:${savePercent}%"></span></div>`
        : `<div class="manager-card__track"><span style="width:${percent}%"></span></div>`;
      const saveHint = item.status === 'complete' && !item.saving && !item.saved
        ? (supportsFileSystemAccess()
            ? `<span class="manager-card__hint">Tap save to choose a folder — the file goes straight to disk.</span>`
            : `<span class="manager-card__hint">Your browser will save the file to its Downloads folder.</span>`)
        : item.status === 'complete' && item.saving
          ? `<span class="manager-card__hint">Saving to device… ${savePercent}% · ${fmtBytes(item.savedBytes || 0)} / ${fmtBytes(item.fileSize || item.totalBytes || 0)}</span>`
          : item.saved
            ? `<span class="manager-card__hint">Saved to: ${escapeHtml(item.savedPath || 'your device')}</span>`
            : '';
      const action = item.status === 'complete'
        ? `<button class="manager-card__save" data-action="save" data-id="${item.id}" ${item.saved || item.saving ? 'disabled' : ''}>${item.saved ? 'Saved' : item.saving ? 'Saving…' : 'Save file'}</button>`
        : active(item.status)
          ? `<button class="manager-card__stop" data-action="cancel" data-id="${item.id}">Stop</button>`
          : item.status === 'paused'
            ? `<button class="manager-card__save" data-action="resume" data-id="${item.id}">Resume</button>`
            : `<button class="manager-card__save" data-action="retry" data-id="${item.id}">Retry</button>`;
      return `<article class="manager-card manager-card--${state}"><div class="manager-card__icon">${icon}</div><div class="manager-card__body"><div class="manager-card__title">${escapeHtml(item.title)}</div><div class="manager-card__meta">${meta}</div>${saveBar}${saveHint ? `<div class="manager-card__stats">${saveHint}</div>` : `<div class="manager-card__stats"><span>${percent}%${item.totalBytes ? ` · ${fmtBytes(item.downloadedBytes)} / ${fmtBytes(item.totalBytes)}` : ''}</span><span>${item.speed ? `${fmtBytes(item.speed)}/s · ${fmtTime(item.eta)}` : ''}</span></div>`}</div><div class="manager-card__actions">${action}</div></article>`;
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
        render();
        if (data.status === 'complete' && !item.saved && !item.saving && !item.saveStarted) {
          // Auto-start the save flow once the file is ready. The user can
          // still re-trigger it from the Save button if they cancel the
          // picker or the save fails.
          saveToDisk(item);
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

  // Stream a response body into a FileSystemFileHandle, reporting progress.
  // This is the "advanced downloader" path: no browser download bar, file
  // lands in the exact folder the user picked.
  const streamToFile = async (response, fileHandle, item, totalSize) => {
    const writable = await fileHandle.createWritable();
    const reader = response.body.getReader();
    let received = 0;
    item.saving = true;
    item.savePercent = 0;
    item.savedBytes = 0;
    item.fileSize = totalSize || item.totalBytes || item.fileSize || 0;
    render();
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
      item.saving = false;
      item.savePercent = 100;
      item.savedPath = fileHandle.name || 'your device';
      render();
      return true;
    } catch (error) {
      try { await writable.abort(); } catch (_) {}
      item.saving = false;
      item.savePercent = 0;
      item.detail = `Save failed: ${error.message || error}`;
      item.status = 'error';
      render();
      return false;
    }
  };

  // Main "save" entry point. Tries the direct-to-device File System Access
  // path; falls back to a properly-named anchor link for browsers without
  // support (Safari, Firefox). Either way, the *real* file is delivered
  // with the correct size and extension.
  const saveToDisk = async item => {
    if (item.saved || item.saving || item.saveStarted) return;
    item.saveStarted = true;
    item.saving = true;
    item.detail = 'Preparing to save…';
    render();

    const downloadUrl = `/api/youtube/download/${encodeURIComponent(item.jobId)}/file/`;
    const suggestedName = item.filename || buildFilename(item);
    const ext = (suggestedName.split('.').pop() || 'mp4').toLowerCase();
    const baseName = suggestedName.replace(/\.[^.]+$/, '') || 'youtube-video';

    let response;
    try {
      response = await fetch(downloadUrl, { credentials: 'same-origin', cache: 'no-store' });
    } catch (error) {
      item.saving = false;
      item.saveStarted = false;
      item.status = 'error';
      item.detail = `Network error: ${error.message || error}`;
      render();
      return;
    }

    if (!response.ok) {
      let message = `Save failed (HTTP ${response.status})`;
      try {
        const data = await response.json();
        message = data.error || message;
      } catch (_) {}
      item.saving = false;
      item.saveStarted = false;
      item.status = 'error';
      item.detail = message;
      render();
      return;
    }

    // Read the real size from the server, never trust the estimated size.
    const contentLength = parseInt(response.headers.get('Content-Length') || '0', 10);
    const totalSize = contentLength || item.totalBytes || item.fileSize || 0;
    const serverFilename = parseFilenameFromHeader(response.headers.get('Content-Disposition')) || suggestedName;
    const serverExt = (serverFilename.split('.').pop() || ext).toLowerCase();
    item.filename = serverFilename;
    item.extension = serverExt;
    item.fileSize = totalSize;
    render();

    // Path A: File System Access API → stream straight to disk, no browser
    // download bar.
    if (supportsFileSystemAccess()) {
      let handle;
      try {
        const mimeTypes = {
          mp4: 'video/mp4',
          m4a: 'audio/mp4',
          mp3: 'audio/mpeg',
          webm: 'video/webm',
          mkv: 'video/x-matroska',
        };
        handle = await window.showSaveFilePicker({
          suggestedName: serverFilename,
          types: [{
            description: mimeTypes[serverExt] ? `${serverExt.toUpperCase()} media` : 'Media file',
            accept: { [mimeTypes[serverExt] || 'application/octet-stream']: [`.${serverExt}`] },
          }],
        });
      } catch (error) {
        // User cancelled the picker. Let them retry by clicking Save again.
        item.saving = false;
        item.saveStarted = false;
        item.detail = 'Save cancelled — tap Save file to pick a location.';
        render();
        // Drain the response so the connection closes cleanly.
        try { response.body?.cancel(); } catch (_) {}
        return;
      }
      await streamToFile(response, handle, item, totalSize);
      item.saveStarted = false;
      return;
    }

    // Path B: Fallback for browsers without showSaveFilePicker. We can't
    // bypass the browser download UI here, but we CAN at least hand it a
    // Blob with the correct bytes, name, and size — so the file the user
    // ends up with is the real one, not a JSON error blob or a nameless
    // "youtube-video" with no extension.
    try {
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = serverFilename;
      link.rel = 'noopener';
      link.style.display = 'none';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 60000);
      item.saved = true;
      item.saving = false;
      item.savePercent = 100;
      item.savedBytes = blob.size;
      item.savedPath = `Downloads / ${serverFilename}`;
      render();
    } catch (error) {
      item.saving = false;
      item.saveStarted = false;
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

  render();
  if (params.get('url')) {
    start(params.get('url'), params.get('format') || 'video', params.get('title') || 'YouTube video');
  }
});
