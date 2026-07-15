const form = document.querySelector('#search-form');
const emptyState = document.querySelector('#empty-state');
const jobPanel = document.querySelector('#job-panel');
const jobKind = document.querySelector('#job-kind');
const jobTitle = document.querySelector('#job-title');
const jobState = document.querySelector('#job-state');
const jobProgress = document.querySelector('#job-progress');
const jobError = document.querySelector('#job-error');
const progressBar = document.querySelector('#progress-bar');
const scenesSection = document.querySelector('#scenes-section');
const sceneList = document.querySelector('#scene-list');
const sceneSummary = document.querySelector('#scene-summary');
const resultSection = document.querySelector('#result-section');
const resultSummary = document.querySelector('#result-summary');
const resultContent = document.querySelector('#result-content');
const submitButton = form.querySelector('button[type="submit"]');
const sceneTemplate = document.querySelector('#scene-template');
const aoiMetrics = document.querySelector('#aoi-metrics');

const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
  return payload;
}

function setJobView(kind, status, progress, error = null) {
  emptyState.classList.add('hidden');
  jobPanel.classList.remove('hidden');
  jobKind.textContent = kind === 'search' ? '01 → 02 · Поиск сцен' : '02 → 03 · Анализ сцены';
  jobTitle.textContent = status === 'completed' ? 'Задание завершено' : status === 'failed' ? 'Задание остановлено' : 'Pipeline выполняется';
  jobState.textContent = status.toUpperCase();
  jobState.className = `state-badge ${status}`;
  jobProgress.textContent = progress || 'Подготовка…';
  const stage = Number((progress || '').match(/^(\d)/)?.[1] || 1);
  progressBar.style.width = status === 'completed' ? '100%' : status === 'failed' ? '100%' : `${Math.max(14, stage * 19)}%`;
  progressBar.style.background = status === 'failed' ? 'var(--danger)' : 'var(--sonar)';
  jobError.textContent = error || '';
  jobError.classList.toggle('hidden', !error);
}

async function waitForJob(initialJob) {
  let job = initialJob;
  while (job.status === 'queued' || job.status === 'running') {
    setJobView(job.kind, job.status, job.progress);
    await sleep(900);
    job = await api(`/api/jobs/${job.id}`);
  }
  setJobView(job.kind, job.status, job.progress, job.error);
  if (job.status === 'failed') throw new Error(job.error || 'Задание завершилось с ошибкой');
  return job.result;
}

function applyPreset(raw) {
  const [west, south, east, north] = raw.split(',');
  form.elements.west.value = west;
  form.elements.south.value = south;
  form.elements.east.value = east;
  form.elements.north.value = north;
  updateAoiMetrics();
}

function updateAoiMetrics() {
  const west = Number(form.elements.west.value);
  const south = Number(form.elements.south.value);
  const east = Number(form.elements.east.value);
  const north = Number(form.elements.north.value);
  if (![west, south, east, north].every(Number.isFinite) || east <= west || north <= south) {
    aoiMetrics.textContent = 'AOI: проверьте координаты';
    return;
  }
  const midLatitudeRadians = ((south + north) / 2) * Math.PI / 180;
  const widthKm = (east - west) * 111.32 * Math.cos(midLatitudeRadians);
  const heightKm = (north - south) * 111.32;
  const areaKm2 = widthKm * heightKm;
  const limitState = areaKm2 > 400 ? ' · превышает лимит 400 км²' : '';
  aoiMetrics.textContent = `Прямоугольный AOI: ${widthKm.toFixed(1)} × ${heightKm.toFixed(1)} км · ≈ ${Math.round(areaKm2)} км²${limitState}`;
}

document.querySelectorAll('.preset').forEach((button) => {
  button.addEventListener('click', () => applyPreset(button.dataset.bbox));
});

form.querySelectorAll('.coordinates input').forEach((input) => {
  input.addEventListener('input', updateAoiMetrics);
});
updateAoiMetrics();

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  submitButton.disabled = true;
  scenesSection.classList.add('hidden');
  resultSection.classList.add('hidden');
  try {
    const body = {
      sensor: form.elements.sensor.value,
      hours: Number(form.elements.hours.value),
      bbox: {
        west: Number(form.elements.west.value),
        south: Number(form.elements.south.value),
        east: Number(form.elements.east.value),
        north: Number(form.elements.north.value),
      },
    };
    const job = await api('/api/search', { method: 'POST', body: JSON.stringify(body) });
    const result = await waitForJob(job);
    renderScenes(result);
  } catch (error) {
    setJobView('search', 'failed', 'Поиск не выполнен', error.message);
  } finally {
    submitButton.disabled = false;
  }
});

function renderScenes(result) {
  sceneList.replaceChildren();
  sceneSummary.textContent = `${result.count} сцен · ${result.provider} · cache ${result.cache_hit ? 'hit' : 'refresh'}`;
  for (const scene of result.scenes) {
    const card = sceneTemplate.content.firstElementChild.cloneNode(true);
    const image = card.querySelector('img');
    if (scene.preview_url) {
      image.src = scene.preview_url;
      image.addEventListener('error', () => image.remove());
    } else {
      image.remove();
    }
    card.querySelector('.sensor-chip').textContent = scene.sensor.toUpperCase();
    card.querySelector('time').textContent = new Date(scene.acquisition_time).toLocaleString('ru-RU', { timeZone: 'UTC' }) + ' UTC';
    card.querySelector('h3').textContent = scene.product_id;
    card.querySelector('.provider').textContent = scene.provider;
    card.querySelector('.beam').textContent = scene.beam_mode || '—';
    card.querySelector('.polarization').textContent = scene.polarization || '—';
    card.querySelector('.detect-action').addEventListener('click', (event) => runDetection(scene, event.currentTarget));
    sceneList.append(card);
  }
  scenesSection.classList.remove('hidden');
  scenesSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

async function runDetection(scene, button) {
  document.querySelectorAll('.detect-action').forEach((item) => { item.disabled = true; });
  button.querySelector(':scope > span').textContent = '…';
  resultSection.classList.add('hidden');
  try {
    const job = await api('/api/detect', { method: 'POST', body: JSON.stringify({ token: scene.token }) });
    const result = await waitForJob(job);
    renderResult(result);
  } catch (error) {
    setJobView('detection', 'failed', 'Детекция не выполнена', error.message);
  } finally {
    document.querySelectorAll('.detect-action').forEach((item) => { item.disabled = false; });
    button.querySelector(':scope > span').textContent = '→';
  }
}

function fact(label, value) {
  const node = document.createElement('div');
  node.className = 'result-fact';
  const caption = document.createElement('span');
  caption.textContent = label;
  const data = document.createElement('b');
  data.textContent = value;
  node.append(caption, data);
  return node;
}

function heading(text) {
  const node = document.createElement('h3');
  node.className = 'subheading';
  node.textContent = text;
  return node;
}

function renderResult(result) {
  resultContent.replaceChildren();
  resultSummary.textContent = `${result.candidate_count} vessel_candidate · ${result.sensor} · ${result.provider}`;

  const overviewGrid = document.createElement('div');
  overviewGrid.className = 'overview-grid';
  const overview = document.createElement('img');
  overview.className = 'overview-image';
  overview.src = result.overview_url;
  overview.alt = 'Обзор сцены с отмеченными кандидатами';
  const facts = document.createElement('div');
  facts.className = 'result-facts';
  facts.append(
    fact('Кандидаты', result.candidate_count),
    fact('AOI crop', result.aoi_cropped ? 'да' : 'нет'),
    fact('Raster cache', result.raster_cache_hit ? 'hit' : 'created'),
    fact('Wake research', result.wake_research_enabled ? 'включён' : 'выключен'),
  );
  overviewGrid.append(overview, facts);
  resultContent.append(overviewGrid);

  const downloads = document.createElement('div');
  downloads.className = 'downloads';
  Object.entries(result.downloads).forEach(([label, url]) => {
    const link = document.createElement('a');
    link.href = url;
    link.textContent = `↓ ${label}`;
    link.target = '_blank';
    downloads.append(link);
  });
  resultContent.append(downloads);

  if (result.crop_urls.length) {
    resultContent.append(heading('Фрагменты кандидатов'));
    const crops = document.createElement('div');
    crops.className = 'crop-grid';
    result.crop_urls.forEach((url, index) => {
      const image = document.createElement('img');
      image.src = url;
      image.alt = `Кандидат ${index + 1}`;
      image.loading = 'lazy';
      crops.append(image);
    });
    resultContent.append(crops);
  }

  resultContent.append(heading('Координаты и признаки'));
  if (!result.detections.length) {
    const empty = document.createElement('p');
    empty.className = 'job-progress';
    empty.textContent = 'В этой сцене кандидаты не обнаружены. Это не подтверждает отсутствие судов.';
    resultContent.append(empty);
  } else {
    const wrap = document.createElement('div');
    wrap.className = 'candidate-table-wrap';
    const table = document.createElement('table');
    table.innerHTML = '<thead><tr><th>ID</th><th>Lon</th><th>Lat</th><th>Ranking score</th><th>Heading</th><th>AIS reference</th></tr></thead>';
    const tbody = document.createElement('tbody');
    result.detections.forEach((candidate) => {
      const row = document.createElement('tr');
      const values = [
        candidate.detection_id,
        Number(candidate.lon).toFixed(5),
        Number(candidate.lat).toFixed(5),
        Number(candidate.ranking_score).toFixed(3),
        candidate.heading_deg == null ? '—' : `${Number(candidate.heading_deg).toFixed(1)}°`,
        candidate.references?.ais?.mmsi || '—',
      ];
      values.forEach((value) => {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
      });
      tbody.append(row);
    });
    table.append(tbody);
    wrap.append(table);
    resultContent.append(wrap);
  }

  resultSection.classList.remove('hidden');
  resultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}
