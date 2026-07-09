# MovieHub — Django + HTMX Movie Streaming Web App

A modern, native-app-feel movie streaming website built with **Django 6**, **HTMX**, and **PWA** technologies, populated with real data scraped from **9jarocks.net**.

## ✨ Features

### Core
- **62 real movies** scraped from 9jarocks.net across 8 categories (Nollywood, Hollywood, K-Drama, Anime, Wrestling, etc.)
- Each movie has: title, poster, plot, year, country, language, genre, type, rating, status, download links, episode thumbnails
- **19 genres** auto-extracted from scraped metadata
- Per-session **watchlist** (no auth required)
- Full-text **search** with live suggestions

### Native-app feel
- 📱 **PWA installable** — manifest + service worker, works offline, "Add to Home Screen"
- 🎯 **Bottom tab navigation** on mobile (Home / Browse / Search / My List) — switches to desktop top-nav at ≥900px
- 📐 **iOS safe-area aware** — respects notch / home indicator via `env(safe-area-inset-*)`
- 🎬 **Hero carousel** with swipe gestures, auto-rotate, dots, prev/next arrows
- 🔄 **Infinite scroll** on Browse page (HTMX-driven, no full page reload)
- ⚡ **Live search suggestions** (HTMX, 250ms debounce)
- 🔖 **One-tap watchlist** toggle (HTMX, partial swap)
- 🌑 **Cinematic dark theme** with Netflix-like red accent
- 📊 **Horizontal content rows** with smooth scroll-snap carousels
- 🚀 **Scroll-to-top** floating button
- 💾 **Install banner** (delayed 8s, auto-dismisses after 33s)
- 📴 **Offline fallback page** served by service worker

### Tech stack
| Layer | Technology |
|-------|-----------|
| Backend | Django 6.0 (Python 3.13) |
| Database | SQLite (default; swap to Postgres for prod) |
| Templates | Django templates + partials |
| Interactivity | HTMX 1.9 (bundled locally, no CDN) |
| Styling | Hand-written CSS (no Tailwind, no framework) — mobile-first, responsive |
| PWA | Web Manifest + Service Worker + Pillow-generated icons |
| Image handling | Pillow |

## 📂 Project structure

```
moviehub/
├── config/                    # Django project config
│   ├── settings.py            # PWA-aware settings
│   └── urls.py                # URL routing
├── movies/                    # Main app
│   ├── models.py              # Category, Genre, Movie, DownloadLink, EpisodeThumbnail, WatchlistItem
│   ├── views.py               # Full pages + HTMX partials
│   ├── context_processors.py  # Global categories
│   ├── management/commands/seed_movies.py  # Seed from scraped JSON
│   ├── templates/movies/
│   │   ├── base.html          # App shell with bottom nav
│   │   ├── home.html          # Hero carousel + content rows
│   │   ├── browse.html        # Grid with filters + infinite scroll
│   │   ├── detail.html        # Movie detail page
│   │   ├── search.html        # Search results
│   │   ├── watchlist.html     # Saved movies
│   │   ├── category.html      # Category landing
│   │   ├── offline.html       # PWA offline fallback
│   │   └── partials/          # HTMX swap targets
│   │       ├── _row_cards.html
│   │       ├── _movie_card.html
│   │       ├── _movie_grid_page.html
│   │       ├── _search_results.html
│   │       ├── _suggestions.html
│   │       └── _watchlist_button.html
│   └── static/movies/
│       ├── css/app.css        # ~1000 lines, mobile-first
│       ├── js/app.js          # Hero carousel, scroll, install banner
│       └── js/htmx.min.js     # Bundled HTMX
├── static/pwa/                # PWA icons (192, 512, 32)
├── scripts/                   # Scrapers and utilities
│   ├── scrape_9jarocks.py     # Initial probe scraper
│   ├── scrape_full.py         # Full concurrent scraper
│   ├── movies_dataset.json    # Scraped data (62 movies)
│   └── generate_pwa_icons.py
└── manage.py
```

## 🚀 Run it

```bash
# 1. Install Django + Pillow
pip install django pillow

# 2. Migrate & seed
cd moviehub
python manage.py migrate
python manage.py seed_movies

# 3. Run
python manage.py runserver 0.0.0.0:8000

# 4. Open
# http://localhost:8000
```

## 🔄 Re-scraping data

To refresh the dataset from 9jarocks.net:

```bash
python scripts/scrape_full.py
# Outputs to scripts/movies_dataset.json

python manage.py seed_movies
# Loads the JSON into the database
```

## 📱 PWA installation

1. Open the site in Chrome/Edge on desktop or Android
2. The install banner appears after 8 seconds (or click the install icon in the address bar)
3. Click "Install" — the app launches in a standalone window
4. On iOS Safari: Share → "Add to Home Screen"

## 🎨 Design decisions

- **Dark theme by default** — cinematic, low-light friendly, less battery drain on OLED
- **Mobile-first** — designed for 414×896 first, then scaled up to desktop 1440×900
- **Bottom nav over hamburger** — thumb-friendly, native-app pattern
- **Horizontal carousels** — Netflix/Prime-style rows, scroll-snap for native feel
- **HTMX over React/Vue** — server-rendered HTML, partial swaps, no SPA complexity
- **Per-session watchlist** — no signup friction, persists across page reloads
- **Bundled HTMX** — no CDN dependency, works offline

## 📊 Data source

All movie data was scraped from **https://9jarocks.net/** for educational/demo purposes. The scraper:
- Visits 8 category pages concurrently
- Extracts movie links from `<article>` blocks
- Fetches detail pages concurrently (8 workers)
- Parses metadata (year, genre, country, type) from the post body
- Captures poster (og:image), plot (first paragraph), thumbnails, related links

Total: **62 movies** across **8 categories** with **19 genres**.
