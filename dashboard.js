document.addEventListener('DOMContentLoaded', () => {
  const dataElement = document.getElementById('dashboard-data');
  let titles = dataElement ? JSON.parse(dataElement.textContent) : [];
  const activityElement = document.getElementById('activity-data');
  let activity = activityElement ? JSON.parse(activityElement.textContent) : [];
  const categoryLabels = {
    'nollywood': 'Nollywood', 'hollywood': 'Hollywood', 'tv-series': 'TV Series',
    'korean-drama': 'Korean Drama', 'chinese-drama': 'Chinese Drama',
    'japanese-drama': 'Japanese Drama', 'filipino-drama': 'Filipino Drama',
    'turkish-drama': 'Turkish Drama', 'thai-drama': 'Thai Drama',
    'anime': 'Anime'
  };
  const labelForCategory = slug => categoryLabels[slug] || slug.replace(/-/g, ' ').replace(/\b\w/g, char => char.toUpperCase());
  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const fmt = value => typeof value === 'number' ? value.toLocaleString() : String(value);
  const categoryCounts = {};
  const typeCounts = {};
  titles.forEach(title => {
    categoryCounts[title.category] = (categoryCounts[title.category] || 0) + 1;
    typeCounts[title.type] = (typeCounts[title.type] || 0) + 1;
  });

  const scrapedDates = titles.map(title => title.scraped_at.slice(0, 10)).filter(Boolean).sort();
  const latestScrape = scrapedDates[scrapedDates.length - 1] || 'No scrape date';
  const stats = [
    ['Total titles', titles.length, `${Object.keys(categoryCounts).length} active categories`],
    ['Categories', Object.keys(categoryCounts).length, 'From scraped records'],
    ['With posters', titles.filter(title => title.thumbnail).length, 'Titles with thumbnails'],
    ['Latest scrape', latestScrape, 'Last catalog update']
  ];
  const statCards = document.getElementById('statCards');
  statCards.innerHTML = stats.map(([label, value, delta]) => `<div class="stat"><div class="stat__label">${label}</div><div class="stat__value">${fmt(value)}</div><div class="stat__delta">${delta}</div>${label === 'Latest scrape' ? `<button class="stat__action" id="runScrapeBtn" type="button">Scrape large catalog</button><div class="scrape-progress" id="scrapeProgress" hidden><div class="scrape-progress__text"></div><div class="scrape-progress__track"><div class="scrape-progress__bar"></div></div></div>` : ''}</div>`).join('');
  const runScrapeButton = document.getElementById('runScrapeBtn');
  const scrapeProgress = document.getElementById('scrapeProgress');
  const progressText = scrapeProgress ? scrapeProgress.querySelector('.scrape-progress__text') : null;
  const progressBar = scrapeProgress ? scrapeProgress.querySelector('.scrape-progress__bar') : null;
  if (runScrapeButton) {
    const updateScrapeProgress = status => {
      if (!scrapeProgress) return;
      scrapeProgress.hidden = !status.running;
      if (status.running) {
        progressText.textContent = status.message || 'Scraping...';
        const percentage = status.total ? Math.min(100, Math.round((status.current / status.total) * 100)) : 0;
        progressBar.style.width = `${percentage}%`;
        progressBar.classList.toggle('is-indeterminate', !status.total);
      }
    };
    runScrapeButton.addEventListener('click', async () => {
      runScrapeButton.disabled = true;
      runScrapeButton.textContent = 'Starting...';
      try {
        const csrfToken = document.querySelector('meta[name="csrf-token"]').content;
        const response = await fetch(statCards.dataset.scrapeUrl, {method: 'POST', headers: {'X-CSRFToken': csrfToken}});
        if (response.ok || response.status === 409) {
          runScrapeButton.textContent = response.status === 409 ? 'Already running' : 'Scraping...';
          const statusTimer = setInterval(async () => {
            const statusResponse = await fetch(statCards.dataset.scrapeStatusUrl);
            const status = await statusResponse.json();
            updateScrapeProgress(status);
            if (!status.running) {
              clearInterval(statusTimer);
              runScrapeButton.disabled = false;
              runScrapeButton.textContent = status.error ? 'Scrape failed' : 'Scrape complete — refresh';
            }
          }, 2000);
        } else {
          throw new Error('Scraper request failed');
        }
      } catch (error) {
        runScrapeButton.disabled = false;
        runScrapeButton.textContent = 'Try again';
      }
    });
  }

  const rangeToggle = document.getElementById('rangeToggle');
  const metricToggle = document.getElementById('metricToggle');
  const lineChart = document.getElementById('lineChart');
  const lcTotal = document.getElementById('lcTotal');
  let currentMetric = 'download';
  function buildDateSeries(days, metric) {
    const counts = {};
    activity.filter(event => event.event_type === metric).forEach(event => { const date = event.created_at.slice(0, 10); counts[date] = (counts[date] || 0) + 1; });
    const activityDates = activity.map(event => event.created_at.slice(0, 10)).sort();
    const endDate = activityDates[activityDates.length - 1] || new Date().toISOString().slice(0, 10);
    const end = new Date(`${endDate}T00:00:00`);
    const series = [];
    for (let offset = days - 1; offset >= 0; offset -= 1) {
      const date = new Date(end); date.setDate(end.getDate() - offset);
      const key = date.toISOString().slice(0, 10); series.push({ key, value: counts[key] || 0 });
    }
    return series;
  }
  function renderLineChart(days, metric) {
    const series = buildDateSeries(days, metric);
    const width = 640, height = 220, padL = 8, padR = 8, padT = 14, padB = 24;
    const max = Math.max(1, ...series.map(point => point.value));
    const stepX = series.length > 1 ? (width - padL - padR) / (series.length - 1) : 0;
    const points = series.map((point, index) => [padL + index * stepX, padT + (1 - point.value / max) * (height - padT - padB)]);
    const linePath = points.map((point, index) => `${index ? 'L' : 'M'}${point[0].toFixed(1)},${point[1].toFixed(1)}`).join(' ');
    const areaPath = `${linePath} L${points[points.length - 1][0].toFixed(1)},${height - padB} L${points[0][0].toFixed(1)},${height - padB} Z`;
    const gridLines = [0.25, 0.5, 0.75].map(fraction => { const y = padT + fraction * (height - padT - padB); return `<line class="lc-grid" x1="${padL}" y1="${y.toFixed(1)}" x2="${width - padR}" y2="${y.toFixed(1)}"/>`; }).join('');
    const labelEvery = Math.max(1, Math.ceil(series.length / 6));
    const labels = series.map((point, index) => { if (index % labelEvery !== 0 && index !== series.length - 1) return ''; const date = new Date(`${point.key}T00:00:00`); return `<text x="${points[index][0].toFixed(1)}" y="${height - 6}" text-anchor="middle">${date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })}</text>`; }).join('');
    const lastPoint = points[points.length - 1];
    lineChart.innerHTML = `${gridLines}${labels}<path class="lc-area" d="${areaPath}"/><path class="lc-line" d="${linePath}"/><circle class="lc-dot" cx="${lastPoint[0].toFixed(1)}" cy="${lastPoint[1].toFixed(1)}" r="4"/>`;
    lcTotal.textContent = `${fmt(series.reduce((sum, point) => sum + point.value, 0))} ${metric === 'download' ? 'downloads' : 'trailer watches'}`;
  }
  renderLineChart(7, currentMetric);
  rangeToggle.addEventListener('click', event => { const button = event.target.closest('button[data-range]'); if (!button) return; rangeToggle.querySelectorAll('button').forEach(item => item.classList.toggle('is-active', item === button)); renderLineChart(Number(button.dataset.range), currentMetric); });
  metricToggle.addEventListener('click', event => { const button = event.target.closest('button[data-metric]'); if (!button) return; metricToggle.querySelectorAll('button').forEach(item => item.classList.toggle('is-active', item === button)); currentMetric = button.dataset.metric; renderLineChart(Number(rangeToggle.querySelector('.is-active').dataset.range), currentMetric); });

  const typeEntries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
  const donutColors = ['var(--accent)', 'var(--accent-2)', 'var(--live)', '#7C93E8'];
  const donutTotal = titles.length || 1;
  let offset = 0;
  const radius = 58, circumference = 2 * Math.PI * radius;
  let circles = `<circle cx="75" cy="75" r="${radius}" fill="none" stroke="var(--bg-elev-3)" stroke-width="20"/>`;
  typeEntries.forEach(([type, count], index) => { const dash = count / donutTotal * circumference; circles += `<circle cx="75" cy="75" r="${radius}" fill="none" stroke="${donutColors[index % donutColors.length]}" stroke-width="20" stroke-dasharray="${dash} ${circumference - dash}" stroke-dashoffset="${-offset}" transform="rotate(-90 75 75)"/>`; offset += dash; });
  circles += `<text x="75" y="73" text-anchor="middle" font-family="var(--font-display)" font-size="18" font-weight="700" fill="var(--text)">${fmt(titles.length)}</text><text x="75" y="91" text-anchor="middle" font-size="10" fill="var(--text-faint)">titles</text>`;
  document.getElementById('donutChart').innerHTML = circles;
  document.getElementById('donutLegend').innerHTML = typeEntries.map(([type, count], index) => `<div class="donut-legend__item"><span class="donut-legend__swatch" style="background:${donutColors[index % donutColors.length]}"></span><span>${type}</span><b>${fmt(count)}</b></div>`).join('');

  const renderBars = (elementId, entries, label) => { const max = Math.max(1, ...entries.map(([, value]) => value)); document.getElementById(elementId).innerHTML = entries.map(([key, value]) => `<div class="barlist__row"><span class="barlist__label">${escapeHtml(label(key))}</span><div class="barlist__track"><div class="barlist__fill" style="width:${(value / max * 100).toFixed(0)}%"></div></div><span class="barlist__value">${fmt(value)}</span></div>`).join(''); };
  renderBars('catBarlist', Object.entries(categoryCounts).sort((a, b) => b[1] - a[1]), labelForCategory);
  const latestTitles = [...titles].sort((a, b) => b.scraped_at.localeCompare(a.scraped_at)).slice(0, 6);
  renderBars('topBarlist', latestTitles.map(title => [title.title, 1]), title => title);

  const tableBody = document.getElementById('tableBody');
  const tableSearch = document.getElementById('tableSearch');
  const filterCategory = document.getElementById('filterCategory');
  const filterType = document.getElementById('filterType');
  const tableCount = document.getElementById('tableCount');
  filterCategory.innerHTML += Object.keys(categoryCounts).sort().map(category => `<option value="${category}">${labelForCategory(category)}</option>`).join('');
  filterType.innerHTML = '<option value="all">All types</option>' + Object.keys(typeCounts).sort().map(type => `<option value="${type}">${type}</option>`).join('');
  let sortKey = 'scraped_at', sortDir = -1;
  document.querySelectorAll('#contentTable th[data-sort]').forEach(header => header.addEventListener('click', () => { if (sortKey === header.dataset.sort) sortDir *= -1; else { sortKey = header.dataset.sort; sortDir = 1; } renderTable(); }));
  function renderTable() {
    const query = tableSearch.value.trim().toLowerCase(), category = filterCategory.value, type = filterType.value;
    const rows = titles.filter(title => (!query || title.title.toLowerCase().includes(query)) && (category === 'all' || title.category === category) && (type === 'all' || title.type === type)).sort((a, b) => { const first = String(a[sortKey] || '').toLowerCase(), second = String(b[sortKey] || '').toLowerCase(); return first < second ? -sortDir : first > second ? sortDir : 0; });
    tableBody.innerHTML = rows.map(title => `<tr><td><div class="dtable__title"><span class="dtable__poster" style="--h:${Math.abs(title.title.length * 37 % 360)}">${escapeHtml(title.title.trim().charAt(0))}</span><a href="/video_detail.html?id=${encodeURIComponent(title.id)}">${escapeHtml(title.title)}</a></div></td><td>${escapeHtml(labelForCategory(title.category))}</td><td>${escapeHtml(title.type)}</td><td>${escapeHtml(title.year || '-')}</td><td>${escapeHtml(title.scraped_at || '-')}</td><td>${fmt(title.download_count)}</td></tr>`).join('') || '<tr><td colspan="6" style="text-align:center; color:var(--text-faint); padding:24px;">No titles match your filters.</td></tr>';
    tableCount.textContent = `${rows.length} of ${titles.length} titles`;
  }
  [tableSearch, filterCategory, filterType].forEach(element => { element.addEventListener('input', renderTable); element.addEventListener('change', renderTable); });
  renderTable();

  function renderDonut() {
    const typeEntries = Object.entries(typeCounts).sort((a, b) => b[1] - a[1]);
    const donutColors = ['var(--accent)', 'var(--accent-2)', 'var(--live)', '#7C93E8'];
    const donutTotal = titles.length || 1;
    let offset = 0;
    const radius = 58, circumference = 2 * Math.PI * radius;
    let circles = `<circle cx="75" cy="75" r="${radius}" fill="none" stroke="var(--bg-elev-3)" stroke-width="20"/>`;
    typeEntries.forEach(([type, count], index) => { const dash = count / donutTotal * circumference; circles += `<circle cx="75" cy="75" r="${radius}" fill="none" stroke="${donutColors[index % donutColors.length]}" stroke-width="20" stroke-dasharray="${dash} ${circumference - dash}" stroke-dashoffset="${-offset}" transform="rotate(-90 75 75)"/>`; offset += dash; });
    circles += `<text x="75" y="73" text-anchor="middle" font-family="var(--font-display)" font-size="18" font-weight="700" fill="var(--text)">${fmt(titles.length)}</text><text x="75" y="91" text-anchor="middle" font-size="10" fill="var(--text-faint)">titles</text>`;
    document.getElementById('donutChart').innerHTML = circles;
    document.getElementById('donutLegend').innerHTML = typeEntries.map(([type, count], index) => `<div class="donut-legend__item"><span class="donut-legend__swatch" style="background:${donutColors[index % donutColors.length]}"></span><span>${type}</span><b>${fmt(count)}</b></div>`).join('');
  }

  function renderHistory(history) {
    const summary = document.getElementById('historySummary');
    const list = document.getElementById('historyList');
    summary.innerHTML = [
      ['Runs', history.total_runs],
      ['Catalog days', history.catalog_days],
      ['Completed', history.completed_runs],
      ['Avg. titles/day', history.average_titles_per_day]
    ].map(([label, value]) => `<div class="history-summary__item"><span>${label}</span><strong>${fmt(value)}</strong></div>`).join('');
    const entries = history.runs.length ? history.runs : history.catalog_history;
    list.innerHTML = entries.map(run => `<div class="history-list__row"><span>${escapeHtml(new Date(run.started_at).toLocaleString())}</span><b class="history-list__status history-list__status--${escapeHtml(run.status)}">${run.status === 'catalog' ? 'Catalog snapshot' : escapeHtml(run.status)}</b><span>${fmt(run.new_titles)} titles</span></div>`).join('') || '<p class="panel__sub">No scrape history recorded yet.</p>';
    document.getElementById('historyUpdated').textContent = `Updated ${new Date().toLocaleTimeString()}`;
  }

  async function refreshDashboard() {
    try {
      const response = await fetch(statCards.dataset.dashboardDataUrl, { cache: 'no-store' });
      if (!response.ok) return;
      const snapshot = await response.json();
      titles = snapshot.titles || [];
      activity = snapshot.activity || [];
      Object.keys(categoryCounts).forEach(key => delete categoryCounts[key]);
      Object.keys(typeCounts).forEach(key => delete typeCounts[key]);
      titles.forEach(title => {
        categoryCounts[title.category] = (categoryCounts[title.category] || 0) + 1;
        typeCounts[title.type] = (typeCounts[title.type] || 0) + 1;
      });
      const dates = titles.map(title => title.scraped_at.slice(0, 10)).filter(Boolean).sort();
      const values = document.querySelectorAll('.stat__value');
      const deltas = document.querySelectorAll('.stat__delta');
      values[0].textContent = fmt(titles.length);
      values[1].textContent = fmt(Object.keys(categoryCounts).length);
      values[2].textContent = fmt(titles.filter(title => title.thumbnail).length);
      values[3].textContent = dates[dates.length - 1] || 'No scrape date';
      deltas[0].textContent = `${Object.keys(categoryCounts).length} active categories`;
      renderLineChart(Number(rangeToggle.querySelector('.is-active').dataset.range), currentMetric);
      renderDonut();
      renderBars('catBarlist', Object.entries(categoryCounts).sort((a, b) => b[1] - a[1]), labelForCategory);
      renderBars('topBarlist', [...titles].sort((a, b) => b.scraped_at.localeCompare(a.scraped_at)).slice(0, 6).map(title => [title.title, 1]), title => title);
      const category = filterCategory.value;
      filterCategory.innerHTML = '<option value="all">All categories</option>' + Object.keys(categoryCounts).sort().map(item => `<option value="${item}">${labelForCategory(item)}</option>`).join('');
      filterCategory.value = categoryCounts[category] ? category : 'all';
      filterType.innerHTML = '<option value="all">All types</option>' + Object.keys(typeCounts).sort().map(type => `<option value="${type}">${type}</option>`).join('');
      renderTable();
      renderHistory(snapshot.history);
      const status = snapshot.scraper || {};
      scrapeProgress.hidden = !status.running;
      if (status.running) {
        progressText.textContent = status.message || 'Scraping...';
        progressBar.style.width = `${status.total ? Math.min(100, Math.round(status.current / status.total * 100)) : 0}%`;
        progressBar.classList.toggle('is-indeterminate', !status.total);
      }
      if (!status.running && status.error) runScrapeButton.textContent = 'Scrape failed';
    } catch (error) {
      // Keep the last successful dashboard snapshot visible during transient failures.
    }
  }

  renderHistory({total_runs: 0, completed_runs: 0, failed_runs: 0, average_new_titles: 0, catalog_days: 0, average_titles_per_day: 0, runs: [], catalog_history: []});
  setInterval(refreshDashboard, 5000);
});
