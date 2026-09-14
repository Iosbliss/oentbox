document.addEventListener('DOMContentLoaded', () => {
  const params = new URLSearchParams(window.location.search);
  const cat = params.get('cat');
  const q = (params.get('q') || '').trim().toLowerCase();

  const titleEl = document.getElementById('browseTitle');
  const subEl = document.getElementById('browseSub');
  const grid = document.getElementById('browseGrid');
  const sidebarList = document.getElementById('categoryList');
  const emptyState = document.getElementById('browseEmpty');

  // The Django version of the page is already server-rendered.
  // Only run the legacy placeholder renderer when its old DOM is present.
  if (!titleEl || !subEl || !grid || !sidebarList || !emptyState) return;

  /* ---------- Build sidebar / chip category list ---------- */
  const allLink = (label, href, active) =>
    `<a href="${href}" class="catlist__item${active ? ' is-active' : ''}">${label}</a>`;

  let sidebarHTML = allLink('All titles', 'browse.html?cat=all', !cat || cat === 'all');
  const groups = [...new Set(NW_CATEGORIES.map(c => c.group))];
  groups.forEach(group => {
    sidebarHTML += `<span class="catlist__group">${group}</span>`;
    NW_CATEGORIES.filter(c => c.group === group).forEach(c => {
      sidebarHTML += allLink(c.label, `browse.html?cat=${c.slug}`, cat === c.slug);
    });
  });
  sidebarList.innerHTML = sidebarHTML;

  /* ---------- Resolve result set ---------- */
  let results;
  let heading;
  let sub = '';

  if (q) {
    results = NW_TITLES.filter(t => t.title.toLowerCase().includes(q));
    heading = `Results for “${params.get('q')}”`;
    sub = `${results.length} title${results.length === 1 ? '' : 's'} found`;
  } else if (cat && cat !== 'all') {
    results = nwTitlesByCategory(cat);
    heading = nwCategoryLabel(cat);
    sub = `${results.length} title${results.length === 1 ? '' : 's'}`;
  } else {
    results = [...NW_TITLES].sort((a, b) => a.title.localeCompare(b.title));
    heading = 'A\u2013Z Library';
    sub = `${results.length} titles`;
  }

  titleEl.textContent = heading;
  subEl.textContent = sub;

  if (results.length === 0) {
    grid.innerHTML = '';
    emptyState.hidden = false;
  } else {
    emptyState.hidden = true;
    grid.innerHTML = results.map(nwCardHTML).join('');
  }
});
