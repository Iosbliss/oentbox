/* ===================================================================
   oentbox — shared placeholder dataset
   (Sample data only — not real titles or content.)
=================================================================== */

const NW_CATEGORIES = [
  { slug: 'nollywood-movies', label: 'Nollywood Movies', group: 'Nollywood' },
  { slug: 'nollywood-series', label: 'Nollywood Series', group: 'Nollywood' },
  { slug: 'hollywood-movies', label: 'Hollywood Movies', group: 'Hollywood' },
  { slug: 'hollywood-series', label: 'Hollywood Series', group: 'Hollywood' },
  { slug: 'korean-drama',    label: 'Korean Drama',   group: 'World Drama' },
  { slug: 'turkish-drama',   label: 'Turkish Drama',  group: 'World Drama' },
  { slug: 'chinese-drama',   label: 'Chinese Drama',  group: 'World Drama' },
  { slug: 'japanese-drama',  label: 'Japanese Drama', group: 'World Drama' },
  { slug: 'filipino-drama',  label: 'Filipino Drama', group: 'World Drama' },
  { slug: 'anime',           label: 'Anime',          group: 'Anime' },
];

const NW_TITLES = [
  { id: 'echoes-of-lagos', title: 'Echoes of Lagos', category: 'nollywood-series', type: 'Series', year: 2026, meta: 'Season 1 · Ep 8', badge: 'NEW', featured: true,
    synopsis: 'A family empire, a buried scandal, and the daughter who won\u2019t let it stay buried. As old debts come due, loyalty inside the family starts to crack.', episodes: 8 },
  { id: 'the-quiet-tenant', title: 'The Quiet Tenant', category: 'nollywood-movies', type: 'Movie', year: 2026, meta: '2h 04m', badge: 'HD', featured: true,
    synopsis: 'A new tenant moves into a quiet compound and slowly unsettles everyone in it, one small favour at a time.' },
  { id: 'bronze-coast', title: 'Bronze Coast', category: 'nollywood-series', type: 'Series', year: 2025, meta: 'Season 2 · Ep 3', badge: '', featured: true,
    synopsis: 'Two rival trading families along the coast are forced into an uneasy partnership when a shared shipment goes missing.', episodes: 14 },
  { id: 'harmattan-house', title: 'Harmattan House', category: 'nollywood-movies', type: 'Movie', year: 2025, meta: '1h 52m', badge: '', featured: false,
    synopsis: 'Four siblings return to their late father\u2019s house for one dry season, and find the will is not what anyone expected.' },
  { id: 'nightfall-market', title: 'Nightfall Market', category: 'nollywood-series', type: 'Series', year: 2025, meta: 'Complete', badge: 'HD', featured: true,
    synopsis: 'Between dusk and dawn, a Lagos market hides a world traders don\u2019t talk about in daylight.', episodes: 10 },
  { id: 'second-skin', title: 'Second Skin', category: 'nollywood-series', type: 'Series', year: 2026, meta: 'Season 1 · Ep 12', badge: 'NEW', featured: false,
    synopsis: 'An identity-fraud investigator gets pulled into the one case that might expose her own past.', episodes: 12 },
  { id: 'the-last-static', title: 'The Last Static', category: 'hollywood-movies', type: 'Movie', year: 2026, meta: '1h 58m', badge: 'NEW', featured: false,
    synopsis: 'When a city-wide blackout hits, a radio engineer becomes the only voice keeping a neighbourhood calm.' },
  { id: 'painted-silence', title: 'Painted Silence', category: 'hollywood-series', type: 'Series', year: 2026, meta: 'Season 1 · Ep 2', badge: 'NEW', featured: false,
    synopsis: 'A forger of fine art is recruited by the very museum she used to fool.', episodes: 2 },
  { id: 'ivory-junction', title: 'Ivory Junction', category: 'hollywood-movies', type: 'Movie', year: 2025, meta: '2h 10m', badge: '', featured: false,
    synopsis: 'Two estranged detectives are paired for one last case at the crossroads where they first met.' },
  { id: 'between-the-rains', title: 'Between the Rains', category: 'hollywood-series', type: 'Series', year: 2026, meta: 'Season 3 · Ep 1', badge: 'NEW', featured: false,
    synopsis: 'A weather-forecasting team races to warn a coastal town before the next storm season.', episodes: 21 },
  { id: 'glass-bridge', title: 'Glass Bridge', category: 'hollywood-movies', type: 'Movie', year: 2025, meta: '1h 47m', badge: 'HD', featured: false,
    synopsis: 'An architect\u2019s masterpiece becomes the site of a hostage standoff on opening night.' },
  { id: 'crimson-harbour', title: 'Crimson Harbour', category: 'hollywood-series', type: 'Series', year: 2025, meta: 'Season 1 · Ep 6', badge: '', featured: false,
    synopsis: 'A harbourmaster uncovers a smuggling ring hiding in plain sight among the fishing fleet.', episodes: 6 },
  { id: 'frostfall-chronicles', title: 'Frostfall Chronicles', category: 'anime', type: 'Series', year: 2026, meta: 'Season 2 · Ep 14', badge: 'NEW', featured: true,
    synopsis: 'A wandering swordswoman searches for the source of an endless winter creeping across the continent.', episodes: 14 },
  { id: 'ashen-blade', title: 'Ashen Blade', category: 'anime', type: 'Series', year: 2024, meta: 'Complete', badge: 'HD', featured: false,
    synopsis: 'A disgraced knight is given one final chance to reclaim his name in a tournament with impossible stakes.', episodes: 24 },
  { id: 'paper-lantern', title: 'Paper Lantern', category: 'anime', type: 'Series', year: 2025, meta: 'Season 1 · Ep 9', badge: '', featured: false,
    synopsis: 'A shy lantern-maker discovers her paper creations can carry real memories between worlds.', episodes: 9 },
  { id: 'iron-orchard', title: 'Iron Orchard', category: 'anime', type: 'Series', year: 2026, meta: 'Season 1 · Ep 21', badge: 'NEW', featured: false,
    synopsis: 'In a future where farmland is rationed by machines, one orchard keeper refuses to give up her family\u2019s plot.', episodes: 21 },
  { id: 'sky-ronin', title: 'Sky Ronin', category: 'anime', type: 'Movie', year: 2025, meta: '1h 40m', badge: '', featured: false,
    synopsis: 'A masterless pilot takes on one last airship contract to pay off a debt that isn\u2019t his own.' },
  { id: 'nine-tailed-hour', title: 'Nine Tailed Hour', category: 'anime', type: 'Series', year: 2025, meta: 'Season 4 · Ep 3', badge: '', featured: false,
    synopsis: 'A detective who can see one hour into the future teams up with a fox spirit to solve cold cases.', episodes: 3 },
  { id: 'winter-plum', title: 'Winter Plum', category: 'korean-drama', type: 'Series', year: 2026, meta: 'Ep 16', badge: 'NEW', featured: true,
    synopsis: 'A conservatory-trained chef returns to her hometown to save her grandmother\u2019s failing restaurant.', episodes: 16 },
  { id: 'istanbul-nights', title: 'Istanbul Nights', category: 'turkish-drama', type: 'Series', year: 2025, meta: 'Ep 22', badge: '', featured: false,
    synopsis: 'A gallery owner and a rare-book dealer are drawn together by a forged manuscript.', episodes: 22 },
  { id: 'the-silk-ledger', title: 'The Silk Ledger', category: 'chinese-drama', type: 'Series', year: 2025, meta: 'Ep 30', badge: 'HD', featured: false,
    synopsis: 'A textile merchant\u2019s daughter secretly runs the family business from behind a ledger book.', episodes: 30 },
  { id: 'sakura-static', title: 'Sakura Static', category: 'japanese-drama', type: 'Series', year: 2026, meta: 'Ep 10', badge: '', featured: false,
    synopsis: 'A retro radio station in Kyoto becomes an unlikely meeting point for four strangers each spring.', episodes: 10 },
  { id: 'manila-heights', title: 'Manila Heights', category: 'filipino-drama', type: 'Series', year: 2026, meta: 'Ep 40', badge: 'NEW', featured: false,
    synopsis: 'Three sisters inherit their father\u2019s apartment building and must decide whether to sell or rebuild.', episodes: 40 },
  { id: 'second-chances', title: 'Second Chances', category: 'korean-drama', type: 'Series', year: 2024, meta: 'Complete', badge: '', featured: false,
    synopsis: 'A former Olympic swimmer becomes the reluctant coach of the team that once cut her.', episodes: 16 },
];

function nwTitlesByCategory(slug) {
  return NW_TITLES.filter(t => t.category === slug);
}
function nwTitlesByGroup(group) {
  const slugs = NW_CATEGORIES.filter(c => c.group === group).map(c => c.slug);
  return NW_TITLES.filter(t => slugs.includes(t.category));
}
function nwCategoryLabel(slug) {
  const c = NW_CATEGORIES.find(c => c.slug === slug);
  return c ? c.label : 'Library';
}
function nwHue(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (h * 31 + str.charCodeAt(i)) % 360;
  return h;
}
function nwCardHTML(t) {
  const initial = t.title.trim().charAt(0);
  return `
    <a class="card" href="video_detail.html?id=${t.id}">
      <div class="card__poster" style="--h:${nwHue(t.title)}" data-initial="${initial}">
        ${t.badge ? `<span class="card__badge">${t.badge}</span>` : ''}
      </div>
      <h3 class="card__title">${t.title}</h3>
      <span class="card__meta">${t.meta}</span>
    </a>`;
}
