document.addEventListener('DOMContentLoaded', () => {
  fetch('/api/saved/').then(response => response.ok ? response.json() : null).then(data => {
    if (!data) return;
    const savedIds = new Set(data.movie_ids.map(String));
    document.querySelectorAll('[data-saved-card]').forEach(card => { card.hidden = !savedIds.has(card.dataset.movieId); });
    const visibleCount = document.querySelectorAll('[data-saved-card]:not([hidden])').length;
    document.getElementById('savedGrid').hidden = visibleCount === 0;
    document.getElementById('savedEmpty').hidden = visibleCount !== 0;
  }).catch(() => {});

  let savedIds = [];
  try {
    const stored = JSON.parse(localStorage.getItem('oentbox-saved') || '[]');
    savedIds = Array.isArray(stored) ? stored : [];
  } catch (error) {
    savedIds = [];
  }

  const cards = document.querySelectorAll('[data-saved-card]');
  let visibleCount = 0;
  cards.forEach(card => {
    const isSaved = savedIds.includes(card.dataset.movieId);
    card.hidden = !isSaved;
    if (isSaved) visibleCount += 1;
  });

  document.getElementById('savedGrid').hidden = visibleCount === 0;
  document.getElementById('savedEmpty').hidden = visibleCount !== 0;
});