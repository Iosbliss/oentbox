document.addEventListener('DOMContentLoaded', () => {
  const escapeHtml = (value) => String(value || '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[character]));

  // Hydrates any avatar placeholder in `root` that carries a data-channel-url
  // attribute (the search grid, the video detail header, and the "similar
  // videos" grid all use this). channel_id from yt-dlp's flat/search
  // extraction is frequently null, so channel_url (or uploader_url) is the
  // more reliable field to hydrate from.
  const hydrateChannelAvatars = async (root = document) => {
    const nodes = [...root.querySelectorAll('[data-channel-url]')]
      .filter((node) => node.dataset.channelUrl && !node.querySelector('img'));
    const channels = [...new Map(nodes.map((node) => [
      `${node.dataset.channelId || ''}|${node.dataset.channelUrl}`,
      { id: node.dataset.channelId || '', url: node.dataset.channelUrl },
    ])).values()];
    const responses = await Promise.all(channels.map(async ({ id, url }) => {
      try {
        const params = new URLSearchParams({ url });
        if (id) params.set('id', id);
        const response = await fetch(`/api/youtube/channel-avatar/?${params}`, { signal: AbortSignal.timeout(10000) });
        const payload = await response.json();
        return [url, response.ok ? payload.thumbnail : ''];
      } catch (error) {
        return [url, ''];
      }
    }));
    const thumbnails = new Map(responses);
    nodes.forEach((node) => {
      const thumbnail = thumbnails.get(node.dataset.channelUrl);
      if (!thumbnail) return;
      const image = new Image();
      image.alt = '';
      image.loading = 'lazy';
      image.onload = () => { node.replaceChildren(image); };
      image.src = thumbnail;
    });
  };

  hydrateChannelAvatars();

  const downloadPanel = document.querySelector('.youtube-download');
  const downloadButton = document.getElementById('youtubeDownloadButton');
  const downloadFormat = document.getElementById('youtubeDownloadFormat');
  const downloadProgress = document.getElementById('youtubeDownloadProgress');
  const downloadBar = document.getElementById('youtubeDownloadBar');
  const downloadStatus = document.getElementById('youtubeDownloadStatus');
  const fileSize = document.getElementById('youtubeFileSize');
  const formatSizes = document.getElementById('youtube-format-sizes');
  if (downloadFormat && fileSize && formatSizes) {
    const sizes = JSON.parse(formatSizes.textContent || '{}');
    const updateFileSize = () => {
      fileSize.dataset.format = downloadFormat.value;
      fileSize.querySelector('strong').textContent = sizes[downloadFormat.value] || 'Available after download';
    };
    downloadFormat.addEventListener('change', updateFileSize);
    updateFileSize();
  }
  if (downloadPanel && downloadButton) {
    downloadButton.addEventListener('click', () => {
      downloadButton.disabled = true;
      downloadButton.setAttribute('aria-busy', 'true');
      downloadButton.lastChild.textContent = ' Starting...';
      const managerUrl = new URL('/downloads.html', window.location.origin);
      managerUrl.searchParams.set('url', downloadPanel.dataset.downloadUrl);
      managerUrl.searchParams.set('format', downloadFormat.value);
      managerUrl.searchParams.set('title', document.querySelector('.youtube-detail-copy h1')?.textContent.trim() || 'YouTube video');
      window.location.href = managerUrl.href;
    });
  }

  const form = document.getElementById('youtubeSearchForm');
  const input = document.getElementById('youtubeQuery');
  const clearBtn = document.getElementById('youtubeClear');
  const results = document.getElementById('youtubeResults');
  const status = document.getElementById('youtubeStatus');
  const chips = document.getElementById('youtubeChips');
  const loadMoreWrap = document.getElementById('youtubeLoadMoreWrap');
  const loadMoreBtn = document.getElementById('youtubeLoadMore');
  if (!form || !results || !status) return;

  const BASE_LIMIT = 50;
  const STEP = 50;
  const MAX_LIMIT = 100;
  let currentQuery = '';
  let currentLimit = BASE_LIMIT;
  let isLoading = false;
  let searchTimer;
  let queuedSearch = null;

  const skeletonCard = () => `<div class="youtube-card youtube-card--skeleton" aria-hidden="true">
    <span class="youtube-card__image"><span class="youtube-skeleton youtube-skeleton--img"></span></span>
    <span class="youtube-card__body">
      <span class="youtube-skeleton youtube-skeleton--avatar"></span>
      <span class="youtube-card__text">
        <span class="youtube-skeleton youtube-skeleton--line" style="width:88%"></span>
        <span class="youtube-skeleton youtube-skeleton--line" style="width:55%"></span>
        <span class="youtube-skeleton youtube-skeleton--line" style="width:38%"></span>
      </span>
    </span>
  </div>`;

  const renderSkeletons = (count = 8) => { results.innerHTML = Array.from({ length: count }, skeletonCard).join(''); };

  const cardMarkup = (video) => {
    const initial = escapeHtml((video.channel || 'Y').trim().charAt(0).toUpperCase() || 'Y');
    const avatar = video.channel_thumbnail
      ? `<img src="${escapeHtml(video.channel_thumbnail)}" alt="">`
      : initial;
    const channelAttr = video.channel_url ? ` data-channel-url="${escapeHtml(video.channel_url)}"${video.channel_id ? ` data-channel-id="${escapeHtml(video.channel_id)}"` : ''}` : '';
    return `<a class="youtube-card" data-video-id="${escapeHtml(video.id)}" href="/youtube/video.html?id=${encodeURIComponent(video.id)}">
    <span class="youtube-card__image">
      <img src="${escapeHtml(video.thumbnail)}" alt="" loading="lazy">
      <span class="youtube-card__source">YouTube</span>
      <span class="youtube-play" aria-hidden="true"><svg viewBox="0 0 24 24" width="22" height="22"><circle cx="12" cy="12" r="11" fill="rgba(0,0,0,.55)"/><path d="M10 8l7 4-7 4z" fill="#fff"/></svg></span>
      ${video.duration ? `<span class="youtube-duration">${escapeHtml(video.duration)}</span>` : ''}
    </span>
    <span class="youtube-card__body">
      <span class="youtube-card__avatar"${channelAttr}>${avatar}</span>
      <span class="youtube-card__text">
        <strong>${escapeHtml(video.title)}</strong>
        <span class="youtube-card__channel">${escapeHtml(video.channel)}</span>
        <span class="youtube-card__stats-row"><span class="youtube-card__published" data-publish-date${video.published ? '' : ' data-publish-pending'}>${escapeHtml(video.published || 'Publish date unavailable')}</span><span class="youtube-card__stats">${video.views ? `${escapeHtml(video.views)} views` : 'Views unavailable'}${video.likes ? ` · ${escapeHtml(video.likes)} likes` : ''}</span></span>
      </span>
    </span>
  </a>`;
  };

  const hydratePublishDates = async (root = document) => {
    const cards = [...root.querySelectorAll('.youtube-card[data-video-id]')]
      .filter((card) => card.querySelector('[data-publish-pending]'));
    await Promise.all(cards.map(async (card) => {
      const label = card.querySelector('[data-publish-date]');
      if (!label || !label.hasAttribute('data-publish-pending')) return;
      try {
        const response = await fetch(`/api/youtube/publish-date/?id=${encodeURIComponent(card.dataset.videoId)}`);
        const payload = await response.json();
        if (payload.published) label.textContent = payload.published;
        label.removeAttribute('data-publish-pending');
        label.dataset.loaded = 'true';
      } catch (error) {
        label.removeAttribute('data-publish-pending');
        label.dataset.loaded = 'true';
      }
    }));
  };

  const render = (videos) => {
    results.innerHTML = videos.map(cardMarkup).join('');
    hydrateChannelAvatars(results);
    hydratePublishDates(results);
  };

  const renderEmpty = (title, message) => {
    results.innerHTML = `<div class="youtube-empty">
      <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true"><circle cx="11" cy="11" r="7" fill="none" stroke="currentColor" stroke-width="2"/><line x1="21" y1="21" x2="16.6" y2="16.6" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>
      <strong>${escapeHtml(title)}</strong>
      <span>${escapeHtml(message)}</span>
    </div>`;
  };

  const setActiveChip = (query) => {
    if (!chips) return;
    chips.querySelectorAll('.chip').forEach((chip) => chip.classList.toggle('is-active', (chip.dataset.query || '') === query));
  };

  const search = async (query = '', { limit = BASE_LIMIT, isLoadMore = false } = {}) => {
    if (isLoading) {
      queuedSearch = { query, limit, isLoadMore };
      return;
    }
    isLoading = true;
    currentQuery = query;
    currentLimit = limit;
    status.classList.remove('is-error');

    if (isLoadMore) {
      loadMoreBtn.disabled = true;
      loadMoreBtn.textContent = 'Loading...';
      status.textContent = 'Loading more videos...';
    } else {
      renderSkeletons();
      loadMoreWrap.hidden = true;
      status.textContent = query ? `Searching for "${query}"...` : 'Loading a random mix...';
    }

    try {
      const response = await fetch(`/api/youtube/search/?q=${encodeURIComponent(query)}&limit=${limit}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || 'Search failed.');

      if (!payload.videos.length) {
        renderEmpty('No videos found', query
          ? `Nothing matched "${query}". Try a different search or pick a topic below.`
          : 'YouTube did not return any videos this time. Try searching for something specific.');
        status.textContent = '0 videos found';
        loadMoreWrap.hidden = true;
        return;
      }

      render(payload.videos);
      const resultLabel = query ? ` for "${query}"` : ' trending near you';
      status.textContent = `${payload.videos.length} video${payload.videos.length === 1 ? '' : 's'} found${resultLabel}`;
      loadMoreWrap.hidden = payload.videos.length < limit || limit >= MAX_LIMIT;
    } catch (error) {
      status.classList.add('is-error');
      status.textContent = error.message;
      renderEmpty('Something went wrong', 'We could not load videos right now. Please try again in a moment.');
      loadMoreWrap.hidden = true;
    } finally {
      isLoading = false;
      loadMoreBtn.disabled = false;
      loadMoreBtn.textContent = 'Show more videos';
      if (queuedSearch) {
        const nextSearch = queuedSearch;
        queuedSearch = null;
        search(nextSearch.query, nextSearch);
      }
    }
  };

  const scheduleSearch = (query) => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => {
      setActiveChip(query);
      search(query);
    }, 400);
  };

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    const query = input.value.trim();
    window.clearTimeout(searchTimer);
    setActiveChip(query);
    search(query);
  });

  if (input && clearBtn) {
    input.addEventListener('input', () => {
      clearBtn.hidden = !input.value;
      scheduleSearch(input.value.trim());
    });
    clearBtn.addEventListener('click', () => {
      window.clearTimeout(searchTimer);
      input.value = '';
      clearBtn.hidden = true;
      input.focus();
      setActiveChip('');
      search('');
    });
  }

  if (chips) {
    chips.addEventListener('click', (event) => {
      const chip = event.target.closest('.chip');
      if (!chip) return;
      const query = chip.dataset.query || '';
      input.value = query;
      if (clearBtn) clearBtn.hidden = !query;
      setActiveChip(query);
      search(query);
    });
  }

  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', () => {
      search(currentQuery, { limit: Math.min(currentLimit + STEP, MAX_LIMIT), isLoadMore: true });
    });
  }

  search();
});
