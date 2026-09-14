document.addEventListener('DOMContentLoaded', () => {

  /* ---------- Populate rows from shared dataset ---------- */
  const rowConfigs = [
    { headingId: 'row-trending', items: NW_TITLES.filter(t => t.featured).slice(0, 8) },
    { headingId: 'row-new', items: NW_TITLES.filter(t => t.badge === 'NEW').slice(0, 8) },
    { headingId: 'row-drama', items: nwTitlesByGroup('World Drama').slice(0, 8) },
  ];

  rowConfigs.forEach(({ headingId, items }) => {
    const heading = document.getElementById(headingId);
    if (!heading) return;
    const track = heading.closest('.row').querySelector('.row__track');
    track.innerHTML = items.map(nwCardHTML).join('');
  });

  /* ---------- Hero carousel ---------- */
  const heroTrack = document.getElementById('heroTrack');
  const heroDots = document.getElementById('heroDots');
  const slides = Array.from(heroTrack.children);

  slides.forEach((_, i) => {
    const dot = document.createElement('button');
    if (i === 0) dot.classList.add('is-active');
    dot.setAttribute('aria-label', `Go to slide ${i + 1}`);
    dot.addEventListener('click', () => {
      heroTrack.scrollTo({ left: heroTrack.clientWidth * i, behavior: 'smooth' });
    });
    heroDots.appendChild(dot);
  });
  const dots = Array.from(heroDots.children);
  const setActiveDot = (i) => dots.forEach((d, di) => d.classList.toggle('is-active', di === i));

  let heroIndex = 0;
  let scrollTimeout;
  heroTrack.addEventListener('scroll', () => {
    clearTimeout(scrollTimeout);
    scrollTimeout = setTimeout(() => {
      const i = Math.round(heroTrack.scrollLeft / heroTrack.clientWidth);
      heroIndex = i;
      setActiveDot(i);
    }, 80);
  });

  let autoplay = setInterval(() => {
    heroIndex = (heroIndex + 1) % slides.length;
    heroTrack.scrollTo({ left: heroTrack.clientWidth * heroIndex, behavior: 'smooth' });
  }, 6000);
  heroTrack.addEventListener('pointerdown', () => clearInterval(autoplay));

  /* ---------- "Add to home screen" hint ---------- */
  const installBtn = document.getElementById('installBtn');
  if (installBtn) {
    installBtn.addEventListener('click', () => {
      alert('On mobile: open your browser menu and choose "Add to Home Screen" for a fullscreen, app-like view.');
    });
  }

});
