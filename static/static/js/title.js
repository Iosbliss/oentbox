document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const id = params.get('id');
  const t = NW_TITLES.find(x => x.id === id) || NW_TITLES[0];

  // The Django-rendered detail page no longer uses the legacy placeholder DOM.
  if (
    !document.getElementById('detailInitial') ||
    !document.getElementById('detailBreadcrumb') ||
    !document.getElementById('detailTitle') ||
    !document.getElementById('detailMeta') ||
    !document.getElementById('detailSynopsis') ||
    !document.getElementById('relatedTrack')
  ) {
    return;
  }

  const hue = nwHue(t.title);
  document.title = `${t.title} — oentbox`;

  document.getElementById('detailHero').style.setProperty('--h', hue);
  document.getElementById('detailInitial').textContent = t.title.trim().charAt(0);
  document.getElementById('detailBreadcrumb').innerHTML =
    `<a href="browse.html?cat=${t.category}">${nwCategoryLabel(t.category)}</a> <span>/</span> ${t.title}`;
  document.getElementById('detailTitle').textContent = t.title;
  document.getElementById('detailMeta').textContent = `${t.type} · ${t.year} · ${t.meta}`;
  document.getElementById('detailSynopsis').textContent = t.synopsis;

  const badgeEl = document.getElementById('detailBadge');
  if (t.badge) {
    badgeEl.textContent = t.badge;
    badgeEl.hidden = false;
  } else {
    badgeEl.hidden = true;
  }

  /* ---------- Episode list (series only) ---------- */
  const epSection = document.getElementById('episodeSection');
  if (t.episodes) {
    const epList = document.getElementById('episodeList');
    let items = '';
    for (let i = 1; i <= t.episodes; i++) {
      items += `
        <button class="episode">
          <span class="episode__num">${String(i).padStart(2, '0')}</span>
          <span class="episode__info">
            <span class="episode__title">Episode ${i}</span>
            <span class="episode__len">~${38 + (i % 5) * 2} min</span>
          </span>
          <svg viewBox="0 0 24 24" width="18" height="18"><path fill="currentColor" d="M8 5v14l11-7z"/></svg>
        </button>`;
    }
    epList.innerHTML = items;
    epSection.hidden = false;
  } else {
    epSection.hidden = true;
  }

  /* ---------- Related titles ---------- */
  const related = nwTitlesByCategory(t.category).filter(x => x.id !== t.id).slice(0, 8);
  document.getElementById('relatedTrack').innerHTML = related.map(nwCardHTML).join('');
});
