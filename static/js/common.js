/* ---------- PWA: install the service worker so the app works offline and can be added to a home screen ---------- */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => { /* offline support is a nice-to-have, never block the page on it */ });
  });
}

document.addEventListener('DOMContentLoaded', () => {

  /* ---------- Mobile menu ---------- */
  const menuBtn = document.getElementById('menuBtn');
  const mobileMenu = document.getElementById('mobileMenu');
  const scrim = document.getElementById('scrim');

  const closeMenu = () => {
    if (!menuBtn) return;
    menuBtn.classList.remove('menu-open');
    menuBtn.setAttribute('aria-expanded', 'false');
    mobileMenu.classList.remove('is-open');
    scrim.classList.remove('is-open');
  };
  const toggleMenu = () => {
    const opening = !mobileMenu.classList.contains('is-open');
    menuBtn.classList.toggle('menu-open', opening);
    menuBtn.setAttribute('aria-expanded', String(opening));
    mobileMenu.classList.toggle('is-open', opening);
    scrim.classList.toggle('is-open', opening);
  };
  if (menuBtn) {
    menuBtn.addEventListener('click', toggleMenu);
    scrim.addEventListener('click', closeMenu);
  }

  /* ---------- Search overlay ---------- */
  const searchBtn = document.getElementById('searchBtn');
  const tabSearch = document.getElementById('tabSearch');
  const searchOverlay = document.getElementById('searchOverlay');
  const closeSearchBtn = document.getElementById('closeSearch');
  const searchInput = searchOverlay ? searchOverlay.querySelector('input') : null;

  const openSearch = () => {
    searchOverlay.classList.add('is-open');
    setTimeout(() => searchInput.focus(), 150);
  };
  const closeSearch = () => searchOverlay.classList.remove('is-open');
  const submitSearch = () => {
    const q = searchInput.value.trim();
    if (q) window.location.href = `/browse.html?q=${encodeURIComponent(q)}`;
  };

  if (searchBtn) {
    searchBtn.addEventListener('click', openSearch);
    tabSearch.addEventListener('click', openSearch);
    closeSearchBtn.addEventListener('click', closeSearch);
    searchOverlay.addEventListener('click', (e) => { if (e.target === searchOverlay) closeSearch(); });
    searchInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') submitSearch(); });
  }
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { closeSearch(); closeMenu(); } });

  /* ---------- Theme toggle ---------- */
  const themeBtn = document.getElementById('themeBtn');
  const root = document.documentElement;
  const savedTheme = localStorage.getItem('oentbox-theme');
  let currentTheme = savedTheme === 'light' || savedTheme === 'dark' ? savedTheme : 'dark';
  root.setAttribute('data-theme', currentTheme);
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      currentTheme = currentTheme === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', currentTheme);
      localStorage.setItem('oentbox-theme', currentTheme);
    });
  }

  /* ---------- My list ---------- */
  const savedKey = 'oentbox-saved';
  const csrfToken = () => document.cookie.split('; ').find(row => row.startsWith('csrftoken='))?.split('=')[1] || '';
  window.nwCsrfHeaders = () => ({'X-CSRFToken': decodeURIComponent(csrfToken())});
  const apiHeaders = () => ({...window.nwCsrfHeaders(), 'Content-Type': 'application/json'});
  const getSavedIds = () => {
    try {
      const saved = JSON.parse(localStorage.getItem(savedKey) || '[]');
      return Array.isArray(saved) ? saved : [];
    } catch (error) {
      return [];
    }
  };
  const setSavedIds = (ids) => localStorage.setItem(savedKey, JSON.stringify(ids));
  let accountSavedIds = null;

  const syncAccountSaved = async () => {
    try {
      const response = await fetch('/api/saved/');
      if (!response.ok) return;
      const data = await response.json();
      accountSavedIds = data.movie_ids.map(String);
      setSavedIds(accountSavedIds);
      document.querySelectorAll('.js-my-list-button[data-movie-id]').forEach(button => button.dispatchEvent(new Event('saved-sync')));
    } catch (error) {
      accountSavedIds = null;
    }
  };

  document.querySelectorAll('.js-my-list-button[data-movie-id]').forEach(button => {
    const movieId = button.dataset.movieId;
    const updateButton = () => {
      const isSaved = getSavedIds().includes(movieId);
      button.textContent = isSaved ? '✓ In my list' : '+ My list';
      button.setAttribute('aria-pressed', String(isSaved));
    };

    updateButton();
    button.addEventListener('saved-sync', updateButton);
    button.addEventListener('click', async () => {
      const savedIds = getSavedIds();
      const nextIds = savedIds.includes(movieId)
        ? savedIds.filter(id => id !== movieId)
        : [...savedIds, movieId];
      if (accountSavedIds) {
        const action = savedIds.includes(movieId) ? 'remove' : 'add';
        const response = await fetch(`/api/saved/${encodeURIComponent(movieId)}/${action}/`, {method: 'POST', headers: apiHeaders()});
        if (!response.ok) return;
      }
      setSavedIds(nextIds);
      if (accountSavedIds) accountSavedIds = nextIds;
      updateButton();
    });
  });
  syncAccountSaved();

  /* ---------- Active state for bottom tab bar + desktop nav ---------- */
  const page = document.body.dataset.page || 'home';
  document.querySelectorAll('.tabbar__item[data-tab]').forEach(tab => {
    tab.classList.toggle('is-active', tab.dataset.tab === page);
  });
  document.querySelectorAll('.navrow__link[data-navkey]').forEach(link => {
    link.classList.toggle('is-current', link.dataset.navkey === page);
  });

});
