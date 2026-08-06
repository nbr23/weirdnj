const NJ_CENTER = [40.05, -74.5];
const NJ_ZOOM = 8;
const SELECTED_ZOOM = 12;
// Marker icons are 41px tall and anchored at their tip, so the top edge needs
// more room than the rest or the northernmost pins are clipped.
const FIT_PADDING_TOP_LEFT = [30, 55];
const FIT_PADDING_BOTTOM_RIGHT = [30, 30];
const NEARBY_COUNT = 10;
const NEARBY_RADIUS_MILES = 75;

const listEl = document.getElementById('location-list');
const searchEl = document.getElementById('search');
const countEl = document.getElementById('count');

// zoomSnap 0 keeps zooming continuous: fitBounds can land on a fractional zoom
// instead of rounding a whole level away, and the wheel never jumps a full
// level at a time. Speed is then wheelPxPerZoomLevel's job - it is the pixels
// of scroll per zoom level, so lower is faster (60 is Leaflet's default).
const map = L.map('map', {
  zoomSnap: 0,
  wheelPxPerZoomLevel: 30,
  wheelDebounceTime: 20
});

const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
});

// Leaflet refuses to add a tile layer before a view exists, but setting a view
// twice makes the map visibly jump. So it is set once, from the data.
function openMap(bounds) {
  if (bounds) {
    map.fitBounds(bounds, {
      paddingTopLeft: FIT_PADDING_TOP_LEFT,
      paddingBottomRight: FIT_PADDING_BOTTOM_RIGHT
    });
  } else {
    map.setView(NJ_CENTER, NJ_ZOOM);
  }
  tiles.addTo(map);
}

const markerFor = new Map();
let activeRow = null;

function setActive(row) {
  if (activeRow) activeRow.classList.remove('active');
  activeRow = row;
  if (row) row.classList.add('active');
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}

function popupHtml(entry) {
  const parts = [`<strong>${escapeHtml(entry.name)}</strong>`];
  if (entry.address) parts.push(escapeHtml(entry.address));
  parts.push(`${escapeHtml(entry.city)}`);
  if (entry.precision === 'city') {
    parts.push('<em class="approx">Approximate — town-level location</em>');
  }
  if (entry.phone) parts.push(escapeHtml(entry.phone));
  if (entry.url) {
    parts.push(`<a href="${escapeHtml(entry.url)}" target="_blank" rel="noopener">Website</a>`);
  }
  parts.push(`<a href="${escapeHtml(entry.maps_url)}" target="_blank" rel="noopener">View on Google Maps</a>`);
  return parts.join('<br>');
}

function milesBetween(a, b) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const dLat = toRad(b[0] - a[0]);
  const dLon = toRad(b[1] - a[1]);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(a[0])) * Math.cos(toRad(b[0])) * Math.sin(dLon / 2) ** 2;
  return 3958.8 * 2 * Math.asin(Math.sqrt(h));
}

function groupByCity(entries) {
  const cities = new Map();
  for (const entry of entries) {
    if (!cities.has(entry.city)) cities.set(entry.city, []);
    cities.get(entry.city).push(entry);
  }
  return [...cities.entries()].sort((a, b) => a[0].localeCompare(b[0]));
}

function buildRow(entry, distance) {
  const row = document.createElement('div');
  row.className = 'location';
  row.innerHTML =
    `<span class="name">${escapeHtml(entry.name)}</span>` +
    (entry.address ? `<span class="address">${escapeHtml(entry.address)}</span>` : '');
  row.dataset.haystack = [entry.city, entry.name, entry.address].filter(Boolean).join(' ').toLowerCase();

  if (distance !== undefined) {
    row.innerHTML += `<span class="distance">${distance.toFixed(1)} mi — ${escapeHtml(entry.city)}</span>`;
  }

  const marker = markerFor.get(entry);
  if (!marker) {
    row.classList.add('unlocated');
    row.innerHTML += '<span class="note">Not found on map — search Google Maps</span>';
    row.addEventListener('click', () => {
      setActive(row);
      window.open(entry.maps_url, '_blank', 'noopener');
    });
    return row;
  }

  if (entry.precision === 'city') {
    row.innerHTML += '<span class="note">Approximate location</span>';
  }
  row.addEventListener('click', () => {
    setActive(row);
    // Zoom in enough to place the store on its street, but never back out
    // from a closer view the user has already chosen.
    map.flyTo([entry.lat, entry.lon], Math.max(map.getZoom(), SELECTED_ZOOM), { duration: 0.6 });
    marker.openPopup();
  });
  return row;
}

function buildSection(title, rows, className) {
  const section = document.createElement('section');
  section.className = className;

  const heading = document.createElement('h2');
  heading.textContent = title;
  section.appendChild(heading);

  for (const row of rows) section.appendChild(row);
  return section;
}

function render(entries) {
  const markers = L.featureGroup();

  for (const entry of entries) {
    if (entry.lat === null || entry.lon === null) continue;
    const marker = L.marker([entry.lat, entry.lon]).bindPopup(popupHtml(entry));
    markerFor.set(entry, marker);
    markers.addLayer(marker);
  }

  openMap(markers.getLayers().length ? markers.getBounds() : null);
  markers.addTo(map);

  for (const [city, stores] of groupByCity(entries)) {
    stores.sort((a, b) => a.name.localeCompare(b.name));
    listEl.appendChild(buildSection(city, stores.map((entry) => buildRow(entry)), 'city'));
  }

  countEl.textContent = `${entries.length} locations`;
  locateUser(entries);
}

function showNearby(entries, position) {
  const here = [position.coords.latitude, position.coords.longitude];

  const ranked = entries
    .filter((entry) => entry.lat !== null && entry.lon !== null)
    .map((entry) => ({ entry, miles: milesBetween(here, [entry.lat, entry.lon]) }))
    .sort((a, b) => a.miles - b.miles)
    .slice(0, NEARBY_COUNT);

  if (!ranked.length) return;

  L.circleMarker(here, {
    radius: 8,
    color: '#fff',
    weight: 2,
    fillColor: '#d94f2b',
    fillOpacity: 1
  })
    .bindPopup('You are here')
    .addTo(map);

  // Recentring on a user hundreds of miles away would show an empty map.
  if (ranked[0].miles <= NEARBY_RADIUS_MILES) map.setView(here, 11);

  const rows = ranked.map(({ entry, miles }) => buildRow(entry, miles));
  listEl.prepend(buildSection('Nearest to you', rows, 'city nearby'));
}

function locateUser(entries) {
  if (!navigator.geolocation) return;
  navigator.geolocation.getCurrentPosition(
    (position) => showNearby(entries, position),
    () => { },
    { timeout: 10000, maximumAge: 300000 }
  );
}

function filter(term) {
  const needle = term.trim().toLowerCase();
  let visible = 0;

  for (const section of listEl.querySelectorAll('section')) {
    let shown = 0;
    for (const row of section.querySelectorAll('.location')) {
      const match = !needle || row.dataset.haystack.includes(needle);
      row.hidden = !match;
      if (match) shown += 1;
    }
    section.hidden = shown === 0;
    if (!section.classList.contains('nearby')) visible += shown;
  }

  const total = listEl.querySelectorAll('.city:not(.nearby) .location').length;
  countEl.textContent = needle ? `${visible} of ${total} locations` : `${visible} locations`;
}

searchEl.addEventListener('input', (event) => filter(event.target.value));

fetch('locations.json')
  .then((response) => {
    if (!response.ok) throw new Error(`locations.json: ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    openMap(null);
    countEl.textContent = 'Could not load locations.';
    console.error(error);
  });
