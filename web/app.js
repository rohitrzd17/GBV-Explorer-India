// GBV Explorer India - Interactive Map & Admin Management Logic

let map;
let markersGroup;
let allIncidents = [];
let filteredIncidents = [];
let markerMap = new Map(); // incident.id -> Leaflet marker
let indianStatesList = [];
let isStaticMode = false;
let isAdminAuthenticated = false; // In-memory only: resets on page refresh

// IIPMaps-inspired Choropleth & Spatial State Variables
let currentLayerMode = 'clusters'; // 'clusters' | 'choropleth' | 'hybrid'
let stateBoundariesGeoJSON = null;
let choroplethLayer = null;

// Utility: Clean HTML tags and entities from plain text
function cleanHtmlText(text) {
    if (!text) return '';
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = text;
    let clean = tempDiv.textContent || tempDiv.innerText || '';
    clean = clean.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
    return clean;
}

// Client-side Overrides for GitHub Pages (Offline / Static editing)
function applyLocalStorageOverrides() {
    try {
        const stored = localStorage.getItem('gbv_client_overrides');
        if (stored) {
            const overrides = JSON.parse(stored);
            if (overrides.edited && Array.isArray(overrides.edited)) {
                overrides.edited.forEach(editedInc => {
                    const idx = allIncidents.findIndex(i => i.id === editedInc.id);
                    if (idx !== -1) {
                        allIncidents[idx] = { ...allIncidents[idx], ...editedInc };
                    }
                });
            }
            if (overrides.deleted && Array.isArray(overrides.deleted)) {
                const delSet = new Set(overrides.deleted);
                allIncidents = allIncidents.filter(i => !delSet.has(i.id));
            }
            if (overrides.added && Array.isArray(overrides.added)) {
                overrides.added.forEach(addedInc => {
                    if (!allIncidents.some(i => i.id === addedInc.id)) {
                        allIncidents.unshift(addedInc);
                    }
                });
            }
        }
    } catch (e) {
        console.warn('Error applying client overrides:', e);
    }
}

function saveClientEdit(incident) {
    try {
        let overrides = JSON.parse(localStorage.getItem('gbv_client_overrides') || '{"edited":[],"deleted":[],"added":[]}');
        overrides.edited = overrides.edited.filter(i => i.id !== incident.id);
        overrides.edited.push(incident);
        localStorage.setItem('gbv_client_overrides', JSON.stringify(overrides));
    } catch (e) {
        console.error('Error saving edit to localStorage:', e);
    }
}

function saveClientDelete(id) {
    try {
        let overrides = JSON.parse(localStorage.getItem('gbv_client_overrides') || '{"edited":[],"deleted":[],"added":[]}');
        if (!overrides.deleted.includes(id)) overrides.deleted.push(id);
        overrides.edited = overrides.edited.filter(i => i.id !== id);
        overrides.added = overrides.added.filter(i => i.id !== id);
        localStorage.setItem('gbv_client_overrides', JSON.stringify(overrides));
    } catch (e) {
        console.error('Error saving delete to localStorage:', e);
    }
}

function saveClientAdd(incident) {
    try {
        let overrides = JSON.parse(localStorage.getItem('gbv_client_overrides') || '{"edited":[],"deleted":[],"added":[]}');
        overrides.added.push(incident);
        localStorage.setItem('gbv_client_overrides', JSON.stringify(overrides));
    } catch (e) {
        console.error('Error saving add to localStorage:', e);
    }
}

// SHA-256 hash of admin password (plaintext is NEVER stored in source code)
const ADMIN_PASS_HASH = "ed8c9cfe75c84b881f159ca0a98cdc37b6f93422b6888c3ef29d5acd43fba239";

// Category Color Mapping
const CATEGORY_COLORS = {
    "Sexual Assault": "#ef4444",
    "POCSO / Minor": "#f43f5e",
    "Domestic Violence": "#a855f7",
    "Dowry Violence": "#f59e0b",
    "Harassment & Stalking": "#0ea5e9",
    "Acid Attack": "#eab308",
    "Other GBV": "#64748b"
};

const CATEGORY_BADGES = {
    "Sexual Assault": "badge-assault",
    "POCSO / Minor": "badge-pocso",
    "Domestic Violence": "badge-domestic",
    "Dowry Violence": "badge-dowry",
    "Harassment & Stalking": "badge-harassment",
    "Acid Attack": "badge-acid",
    "Other GBV": "badge-other"
};

// Cryptographic SHA-256 using Browser WebCrypto API
async function sha256(str) {
    const buffer = new TextEncoder().encode(str);
    const hashBuffer = await crypto.subtle.digest('SHA-256', buffer);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}

// Load Official India Borders (Survey of India / OpenStreetMap India osm-in.github.io compliance)
async function loadIndiaBoundaries() {
    const canvasRenderer = L.canvas();

    try {
        // 1. Mask disputed lines that standard OSM tiles render incorrectly
        const dispRes = await fetch('./data/osm-india-disputed-lines.geojson');
        if (dispRes.ok) {
            const dispData = await dispRes.json();
            
            // Mask layer: covers disputed/dashed internal lines with land background color
            L.geoJSON(dispData, {
                renderer: canvasRenderer,
                filter: (feature) => feature.properties && feature.properties.disputed_by === 'IN',
                style: {
                    color: '#f2efe9',
                    weight: 6,
                    opacity: 1.0,
                    interactive: false
                }
            }).addTo(map);

            // Claimed boundary lines: renders official sovereign boundaries of India (J&K, Ladakh, Arunachal)
            L.geoJSON(dispData, {
                renderer: canvasRenderer,
                filter: (feature) => feature.properties && feature.properties.claimed_by === 'IN',
                style: {
                    color: '#1e293b',
                    weight: 2.5,
                    opacity: 0.9,
                    interactive: false
                }
            }).addTo(map);
        }
    } catch (err) {
        console.warn('Could not load disputed lines GeoJSON:', err);
    }

    try {
        // 2. Official Survey of India outline polygon (from Datameet / osm-in.github.io)
        const bndRes = await fetch('./data/india-boundary.geojson');
        if (bndRes.ok) {
            const bndData = await bndRes.json();
            L.geoJSON(bndData, {
                renderer: canvasRenderer,
                style: {
                    color: '#0f172a',
                    weight: 2,
                    opacity: 0.85,
                    fill: false,
                    interactive: false
                }
            }).addTo(map);
        }
    } catch (err) {
        console.warn('Could not load India boundary GeoJSON:', err);
    }
}

// Initialize Leaflet Map (with OpenStreetMap India boundaries compliance & smooth zooming)
function initMap() {
    map = L.map('map', {
        center: [22.8, 80.0], // Geographic center of India
        zoom: 5,
        minZoom: 4,
        maxZoom: 18,
        zoomControl: false,
        preferCanvas: true,            // GPU canvas rendering for vector layers (eliminates choppy SVG re-rendering)
        zoomAnimation: true,           // Smooth zoom animation
        zoomAnimationThreshold: 8,     // Animate zooms even when jumping multiple zoom levels
        fadeAnimation: true,           // Smooth tile fading
        markerZoomAnimation: true,     // Smooth pin repositioning during zoom
        zoomSnap: 0.5,                 // Finer fractional zoom levels instead of jarring integer jumps
        zoomDelta: 0.5,                // Gentle zoom steps for buttons & gestures
        wheelPxPerZoomLevel: 120,      // Smooth mousewheel zooming
        wheelDebounceTime: 40          // Throttle wheel zoom events
    });

    // Clean top-right zoom control
    L.control.zoom({ position: 'topright' }).addTo(map);

    // Open-source base tiles with OpenStreetMap India attribution
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors | Borders as per <a href="https://osm-in.github.io" target="_blank">OpenStreetMap India / Survey of India</a>',
        maxZoom: 19,
        updateWhenZooming: false,      // Don't thrash network during zoom animation; keep current tiles stretched
        updateWhenIdle: true,          // Fetch new tiles only when pan/zoom settles
        keepBuffer: 4                  // Keep off-screen tiles in memory for seamless panning & zooming
    }).addTo(map);

    // Apply official boundaries compliance
    loadIndiaBoundaries();
    loadIndiaStateBoundaries();

    markersGroup = L.markerClusterGroup({
        showCoverageOnHover: false,
        maxClusterRadius: 40,
        spiderfyOnMaxZoom: true,
        animate: true,
        animateAddingMarkers: false,
        chunkedLoading: true,
        chunkInterval: 100,
        chunkDelay: 25,
        disableClusteringAtZoom: 16
    });
    map.addLayer(markersGroup);

    // Click outside in blank area (ocean, neighboring countries, non-state areas) resets to whole country view
    map.on('click', (e) => {
        const tooltipEl = document.getElementById('state-tooltip');
        if (tooltipEl) tooltipEl.classList.add('hidden');

        const stateSelect = document.getElementById('filter-state');
        const isStateFiltered = stateSelect && stateSelect.value !== 'All';

        if (isStateFiltered) {
            resetToWholeCountryView();
        } else if (map.getZoom() > 5.2 && (currentLayerMode === 'choropleth' || currentLayerMode === 'hybrid')) {
            resetToWholeCountryView();
        }
    });
}

// Reset view to whole country view (All States)
function resetToWholeCountryView() {
    const stateSelect = document.getElementById('filter-state');
    const wasFiltered = stateSelect && stateSelect.value !== 'All';
    if (stateSelect) {
        stateSelect.value = 'All';
    }
    if (wasFiltered) {
        applyFilters();
    }
    if (map) {
        map.flyTo([22.8, 80.0], 5, {
            duration: 0.8,
            easeLinearity: 0.25
        });
    }
}

// Load Official India State Boundaries for Thematic Choropleth (Survey of India Compliant)
async function loadIndiaStateBoundaries() {
    try {
        const cacheBuster = `?t=${Date.now()}`;
        const res = await fetch(`./data/india-states.geojson${cacheBuster}`, { cache: 'no-store' });
        if (res.ok) {
            stateBoundariesGeoJSON = await res.json();
            if (currentLayerMode !== 'clusters') {
                renderChoroplethLayer();
            }
        }
    } catch (err) {
        console.warn('Could not load india-states.geojson:', err);
    }
}

// Create custom pin icon
function createMarkerIcon(category) {
    const color = CATEGORY_COLORS[category] || CATEGORY_COLORS["Other GBV"];
    return L.divIcon({
        className: 'custom-pin-wrapper',
        html: `<div class="custom-pin" style="background-color: ${color};"></div>`,
        iconSize: [22, 22],
        iconAnchor: [11, 11]
    });
}

// Fetch Incidents (Dual Mode: Dynamic API or Static GitHub Pages JSON)
async function fetchIncidents() {
    try {
        let res;
        try {
            res = await fetch('/api/incidents?only_geocoded=false');
            if (!res.ok) throw new Error('API unavailable');
        } catch (apiErr) {
            // Static mode fallback for GitHub Pages
            isStaticMode = true;
            console.log('[DualMode] Serving from static dataset for GitHub Pages.');
            const cacheBuster = `?t=${Date.now()}`;
            res = await fetch(`./data/incidents.json${cacheBuster}`, { cache: 'no-store' });
        }

        const data = await res.json();
        allIncidents = data.incidents || [];
        if (isStaticMode || window.location.hostname.includes('github.io')) {
            applyLocalStorageOverrides();
        }
        populateStateFilter(allIncidents);
        applyFilters();
        await fetchStats();
    } catch (err) {
        console.error('Failed to load incidents:', err);
    }
}

// Fetch System Stats (Dual Mode)
async function fetchStats() {
    try {
        let res;
        try {
            res = await fetch('/api/stats');
            if (!res.ok) throw new Error('Stats API unavailable');
        } catch (apiErr) {
            const cacheBuster = `?t=${Date.now()}`;
            res = await fetch(`./data/stats.json${cacheBuster}`, { cache: 'no-store' });
        }

        const stats = await res.json();
        const total = stats.total_incidents || allIncidents.length;
        const geocoded = (stats.geocoded_incidents !== undefined && stats.geocoded_incidents !== null)
            ? stats.geocoded_incidents
            : allIncidents.filter(i => i.latitude && i.longitude).length;
        let topCat = '-';
        if (stats.categories && Object.keys(stats.categories).length > 0) {
            topCat = Object.keys(stats.categories)[0];
        }

        if (document.getElementById('stat-total')) document.getElementById('stat-total').textContent = total;
        if (document.getElementById('stat-geocoded')) document.getElementById('stat-geocoded').textContent = geocoded;
        if (document.getElementById('stat-top-cat')) document.getElementById('stat-top-cat').textContent = topCat;

        // Mobile header, menu, and floating buttons
        if (document.getElementById('mobile-stat-total')) document.getElementById('mobile-stat-total').textContent = total;
        if (document.getElementById('mobile-menu-geocoded')) document.getElementById('mobile-menu-geocoded').textContent = geocoded;
        if (document.getElementById('mobile-menu-top-cat')) document.getElementById('mobile-menu-top-cat').textContent = topCat;
        if (document.getElementById('zoom-inc-badge')) document.getElementById('zoom-inc-badge').textContent = total;
    } catch (err) {
        console.error('Failed to fetch stats:', err);
    }
}

// Populate State Filter Options
function populateStateFilter(incidents) {
    const stateSelect = document.getElementById('filter-state');
    const addStateSelect = document.getElementById('add-state');
    const existing = new Set();
    
    incidents.forEach(inc => {
        if (inc.state && inc.state.trim()) {
            existing.add(inc.state.trim());
        }
    });

    indianStatesList = Array.from(existing).sort();
    
    stateSelect.innerHTML = '<option value="All">All States / UTs</option>';
    if (addStateSelect) addStateSelect.innerHTML = '<option value="">Select State (Optional)</option>';

    indianStatesList.forEach(st => {
        const opt = document.createElement('option');
        opt.value = st;
        opt.textContent = st;
        stateSelect.appendChild(opt);

        if (addStateSelect) {
            const opt2 = document.createElement('option');
            opt2.value = st;
            opt2.textContent = st;
            addStateSelect.appendChild(opt2);
        }
    });
}

// Filter and Render Map
function applyFilters() {
    const categoryVal = document.getElementById('filter-category').value;
    const stateVal = document.getElementById('filter-state').value;
    const timeVal = document.getElementById('filter-date').value;
    const searchVal = document.getElementById('filter-search').value.toLowerCase().trim();

    const now = new Date();
    let cutoffDate = null;
    if (timeVal === '7d') {
        cutoffDate = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
    } else if (timeVal === '30d') {
        cutoffDate = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
    } else if (timeVal === '60d') {
        cutoffDate = new Date(now.getTime() - 60 * 24 * 60 * 60 * 1000);
    } else if (timeVal === '90d') {
        cutoffDate = new Date(now.getTime() - 90 * 24 * 60 * 60 * 1000);
    } else if (timeVal === '180d') {
        cutoffDate = new Date(now.getTime() - 195 * 24 * 60 * 60 * 1000); // Full 6-month coverage back to March 1, 2026
    }

    filteredIncidents = allIncidents.filter(inc => {
        if (categoryVal !== 'All' && inc.category !== categoryVal) return false;
        if (stateVal !== 'All' && inc.state !== stateVal) return false;

        if (cutoffDate && inc.incident_date) {
            const incDate = new Date(inc.incident_date);
            if (!isNaN(incDate) && incDate < cutoffDate) return false;
        }

        if (searchVal) {
            const haystack = `${inc.title} ${inc.summary} ${inc.location_name} ${inc.district} ${inc.state}`.toLowerCase();
            if (!haystack.includes(searchVal)) return false;
        }

        return true;
    });

    renderMapMarkers();
    renderIncidentList();
    renderChoroplethLayer();
}

// Render Leaflet Markers
function renderMapMarkers() {
    markersGroup.clearLayers();
    markerMap.clear();

    filteredIncidents.forEach(inc => {
        if (inc.latitude && inc.longitude) {
            const marker = L.marker([inc.latitude, inc.longitude], {
                icon: createMarkerIcon(inc.category)
            });

            const popupHtml = `
                <div style="min-width: 190px;">
                    <span class="badge ${CATEGORY_BADGES[inc.category] || 'badge-other'}">${inc.category}</span>
                    <div class="popup-title">${escapeHtml(cleanHtmlText(inc.title))}</div>
                    <div class="popup-meta">
                        <i class="fa-solid fa-location-dot"></i> ${escapeHtml(inc.district || inc.location_name || inc.state || 'India')} &bull; ${inc.incident_date || 'Recent'}
                    </div>
                    <button class="popup-btn" onclick="openModal(${inc.id})">Details & Sources (${inc.source_count || 1})</button>
                </div>
            `;
            marker.bindPopup(popupHtml);
            markersGroup.addLayer(marker);
            markerMap.set(inc.id, marker);
        }
    });
}

// State Name Normalization
function normalizeStateName(name) {
    if (!name) return '';
    const n = name.trim().toLowerCase();
    if (n === 'jammu and kashmir' || n === 'jammu & kashmir') return 'Jammu and Kashmir';
    if (n === 'andaman and nicobar islands' || n === 'andaman & nicobar') return 'Andaman and Nicobar Islands';
    if (n.includes('dadra') || n.includes('daman')) return 'Dadra and Nagar Haveli';
    if (n === 'nct of delhi' || n === 'delhi') return 'Delhi';
    if (n === 'orissa' || n === 'odisha') return 'Odisha';
    if (n === 'telengana' || n === 'telangana') return 'Telangana';
    if (n === 'pondicherry' || n === 'puducherry') return 'Puducherry';
    return name.trim();
}

// Compute Aggregated Incident Stats by State
function getIncidentStatsByState() {
    const statsMap = new Map();
    const sourceList = (filteredIncidents && filteredIncidents.length > 0) ? filteredIncidents : allIncidents;
    sourceList.forEach(inc => {
        const rawState = inc.state;
        if (!rawState) return;
        const stateKey = normalizeStateName(rawState);
        if (!statsMap.has(stateKey)) {
            statsMap.set(stateKey, {
                name: stateKey,
                count: 0,
                categories: {},
                statuses: {}
            });
        }
        const s = statsMap.get(stateKey);
        s.count += 1;
        s.categories[inc.category] = (s.categories[inc.category] || 0) + 1;
        const status = inc.legal_status || 'Under Investigation';
        s.statuses[status] = (s.statuses[status] || 0) + 1;
    });
    return statsMap;
}

// Sequential Color Scale (IIPMaps-inspired D3 Red/Crimson gradient)
function getChoroplethColor(count, maxCount) {
    if (!count || count === 0) {
        return 'rgba(241, 245, 249, 0.25)'; // Muted translucent slate for 0 reports
    }
    const ratio = Math.min(1, Math.max(0, count / (maxCount || 1)));
    if (ratio < 0.15) return '#fee2e2'; // Very light red
    if (ratio < 0.35) return '#fca5a5'; // Soft coral
    if (ratio < 0.55) return '#f87171'; // Medium red
    if (ratio < 0.75) return '#dc2626'; // Vivid crimson
    return '#7f1d1d';                   // Deep dark burgundy
}

// Render Thematic State Choropleth Layer
function renderChoroplethLayer() {
    if (choroplethLayer && map.hasLayer(choroplethLayer)) {
        map.removeLayer(choroplethLayer);
        choroplethLayer = null;
    }

    const choroplethLegend = document.getElementById('choropleth-legend');
    const pinLegend = document.getElementById('map-legend');

    if (currentLayerMode === 'clusters') {
        if (choroplethLegend) choroplethLegend.classList.add('hidden');
        if (pinLegend) pinLegend.classList.remove('hidden');
        if (!map.hasLayer(markersGroup)) map.addLayer(markersGroup);
        return;
    }

    if (currentLayerMode === 'choropleth') {
        if (map.hasLayer(markersGroup)) map.removeLayer(markersGroup);
        if (choroplethLegend) choroplethLegend.classList.remove('hidden');
        if (pinLegend) pinLegend.classList.add('hidden');
    } else if (currentLayerMode === 'hybrid') {
        if (!map.hasLayer(markersGroup)) map.addLayer(markersGroup);
        if (choroplethLegend) choroplethLegend.classList.remove('hidden');
        if (pinLegend) pinLegend.classList.remove('hidden');
    }

    if (!stateBoundariesGeoJSON) return;

    const stateStats = getIncidentStatsByState();
    let maxCount = 1;
    stateStats.forEach(s => {
        if (s.count > maxCount) maxCount = s.count;
    });

    const rangeLabel = document.getElementById('choropleth-range-label');
    if (rangeLabel) {
        rangeLabel.textContent = `0 – ${maxCount}+ Reports`;
    }
    const t25 = document.getElementById('tick-25');
    const t50 = document.getElementById('tick-50');
    const t75 = document.getElementById('tick-75');
    const t100 = document.getElementById('tick-100');
    if (t25) t25.textContent = Math.round(maxCount * 0.25);
    if (t50) t50.textContent = Math.round(maxCount * 0.50);
    if (t75) t75.textContent = Math.round(maxCount * 0.75);
    if (t100) t100.textContent = `${maxCount}+`;

    const tooltipEl = document.getElementById('state-tooltip');

    choroplethLayer = L.geoJSON(stateBoundariesGeoJSON, {
        style: (feature) => {
            const stName = normalizeStateName(feature.properties.st_nm);
            const stats = stateStats.get(stName);
            const count = stats ? stats.count : 0;
            const fillCol = getChoroplethColor(count, maxCount);
            const fillOp = (currentLayerMode === 'hybrid') ? 0.38 : 0.72;

            return {
                fillColor: fillCol,
                weight: 1.2,
                opacity: 0.85,
                color: '#1e293b',
                fillOpacity: fillOp
            };
        },
        onEachFeature: (feature, layer) => {
            const stName = normalizeStateName(feature.properties.st_nm);
            const stats = stateStats.get(stName);
            const count = stats ? stats.count : 0;

            layer.on({
                mouseover: (e) => {
                    const l = e.target;
                    l.setStyle({
                        weight: 2.8,
                        color: '#38bdf8',
                        fillOpacity: (currentLayerMode === 'hybrid') ? 0.65 : 0.9
                    });
                    if (!L.Browser.ie && !L.Browser.opera && !L.Browser.edge) {
                        l.bringToFront();
                    }

                    if (tooltipEl) {
                        let topCat = 'None';
                        if (stats && stats.categories) {
                            const sortedCats = Object.entries(stats.categories).sort((a, b) => b[1] - a[1]);
                            if (sortedCats.length > 0) topCat = `${sortedCats[0][0]} (${sortedCats[0][1]})`;
                        }

                        const totalActive = filteredIncidents.length || 1;
                        const pct = ((count / totalActive) * 100).toFixed(1);

                        tooltipEl.innerHTML = `
                            <div class="state-tooltip-title">
                                <span>${escapeHtml(feature.properties.st_nm)}</span>
                                <span class="state-tooltip-count">${count} ${count === 1 ? 'Report' : 'Reports'}</span>
                            </div>
                            <div class="state-tooltip-row">
                                <span>% of Active Reports:</span>
                                <strong>${pct}%</strong>
                            </div>
                            <div class="state-tooltip-row">
                                <span>Top Category:</span>
                                <strong>${escapeHtml(topCat)}</strong>
                            </div>
                            <div class="state-tooltip-hint"><i class="fa-solid fa-arrow-pointer"></i> Click to filter & zoom into state</div>
                        `;
                        tooltipEl.classList.remove('hidden');
                    }
                },
                mousemove: (e) => {
                    if (tooltipEl) {
                        const mapContainer = document.getElementById('map-container');
                        const rect = mapContainer.getBoundingClientRect();
                        const x = e.originalEvent.clientX - rect.left;
                        const y = e.originalEvent.clientY - rect.top;
                        tooltipEl.style.left = `${x}px`;
                        tooltipEl.style.top = `${y}px`;
                    }
                },
                mouseout: (e) => {
                    if (choroplethLayer) {
                        choroplethLayer.resetStyle(e.target);
                    }
                    if (tooltipEl) {
                        tooltipEl.classList.add('hidden');
                    }
                },
                click: (e) => {
                    L.DomEvent.stopPropagation(e);
                    if (tooltipEl) tooltipEl.classList.add('hidden');

                    const stateSelect = document.getElementById('filter-state');
                    const currentState = stateSelect ? stateSelect.value : 'All';

                    // Toggle: clicking the currently highlighted state resets back to whole country
                    if (normalizeStateName(currentState) === stName || currentState === feature.properties.st_nm) {
                        resetToWholeCountryView();
                        return;
                    }

                    map.fitBounds(e.target.getBounds(), { padding: [30, 30], maxZoom: 8 });

                    if (stateSelect) {
                        for (let opt of stateSelect.options) {
                            if (normalizeStateName(opt.value) === stName || opt.value === feature.properties.st_nm) {
                                stateSelect.value = opt.value;
                                applyFilters();
                                break;
                            }
                        }
                    }
                }
            });
        }
    });

    choroplethLayer.addTo(map);
}

// Switch Map Layer Mode (Clusters / Choropleth / Hybrid)
function setLayerMode(mode) {
    if (mode !== 'clusters' && mode !== 'choropleth' && mode !== 'hybrid') return;
    currentLayerMode = mode;

    // Update active state in desktop header
    document.querySelectorAll('.layer-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    // Update active state in mobile menu
    document.querySelectorAll('.mobile-layer-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.mode === mode);
    });

    renderChoroplethLayer();
}

// Render Side Drawer List
function renderIncidentList() {
    const listContainer = document.getElementById('incident-list');
    document.getElementById('drawer-count').textContent = filteredIncidents.length;
    if (document.getElementById('zoom-inc-badge')) {
        document.getElementById('zoom-inc-badge').textContent = filteredIncidents.length;
    }
    listContainer.innerHTML = '';

    if (filteredIncidents.length === 0) {
        listContainer.innerHTML = '<div style="color: var(--text-muted); text-align: center; padding: 20px;">No incidents matching current filters.</div>';
        return;
    }

    filteredIncidents.forEach(inc => {
        const card = document.createElement('div');
        card.className = 'incident-card';
        card.innerHTML = `
            <div class="incident-card-header">
                <span class="incident-card-title">${escapeHtml(cleanHtmlText(inc.title))}</span>
                <span class="badge ${CATEGORY_BADGES[inc.category] || 'badge-other'}">${inc.category}</span>
            </div>
            <div class="incident-card-meta">
                <span><i class="fa-solid fa-location-dot"></i> ${escapeHtml(inc.district || inc.location_name || inc.state || 'India')}</span>
                <span><i class="fa-solid fa-calendar"></i> ${inc.incident_date || 'Recent'}</span>
                <span><i class="fa-solid fa-newspaper"></i> ${inc.source_count || 1} report(s)</span>
            </div>
        `;
        card.addEventListener('click', () => {
            // If on mobile, close the full-page incidents drawer so the map is visible
            if (window.innerWidth <= 820) {
                closeDrawer();
            }
            if (inc.latitude && inc.longitude) {
                map.flyTo([inc.latitude, inc.longitude], 11, { duration: 1.2 });
                const marker = markerMap.get(inc.id);
                if (marker) {
                    setTimeout(() => marker.openPopup(), 1300);
                }
            } else {
                openModal(inc.id);
            }
        });
        listContainer.appendChild(card);
    });
}

// Open Detailed Modal & Fetch Media Sources
async function openModal(incidentId) {
    const inc = allIncidents.find(i => i.id === incidentId);
    if (!inc) return;

    document.getElementById('modal-title').textContent = cleanHtmlText(inc.title);
    const badge = document.getElementById('modal-category-badge');
    badge.className = `badge ${CATEGORY_BADGES[inc.category] || 'badge-other'}`;
    badge.textContent = inc.category;

    document.getElementById('modal-date').textContent = inc.incident_date || 'Not specified';
    document.getElementById('modal-location').textContent = `${inc.district || inc.location_name || 'Unspecified'}, ${inc.state || 'India'}`;
    document.getElementById('modal-status').textContent = inc.legal_status || 'Under Investigation';
    document.getElementById('modal-summary').textContent = cleanHtmlText(inc.summary || inc.title);

    const sourcesContainer = document.getElementById('modal-sources-list');
    sourcesContainer.innerHTML = '<div style="color: var(--text-muted);">Loading verified sources...</div>';

    document.getElementById('incident-modal').classList.add('active');

    try {
        const res = await fetch(`/api/incidents/${incidentId}/sources`);
        const data = await res.json();
        const sources = data.sources || [];
        sourcesContainer.innerHTML = '';

        if (sources.length === 0) {
            // Fallback for static mode using primary_url
            if (inc.primary_url) {
                sourcesContainer.innerHTML = `
                    <div class="source-item">
                        <div>
                            <div style="font-size: 0.85rem; font-weight: 600;">${escapeHtml(cleanHtmlText(inc.title))}</div>
                            <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(cleanHtmlText(inc.publishers || 'News Outlet'))}</div>
                        </div>
                        <a href="${inc.primary_url}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i> Read Article</a>
                    </div>
                `;
            } else {
                sourcesContainer.innerHTML = '<div style="color: var(--text-muted);">No external links recorded.</div>';
            }
        } else {
            sources.forEach(src => {
                const item = document.createElement('div');
                item.className = 'source-item';
                item.innerHTML = `
                    <div>
                        <div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 2px;">${escapeHtml(cleanHtmlText(src.headline))}</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(cleanHtmlText(src.publisher || 'Media Outlet'))} &bull; ${src.published_at ? src.published_at.slice(0, 10) : ''}</div>
                    </div>
                    <a href="${src.url}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i> Read Article</a>
                `;
                sourcesContainer.appendChild(item);
            });
        }
    } catch (err) {
        if (inc.primary_url) {
            sourcesContainer.innerHTML = `
                <div class="source-item">
                    <div>
                        <div style="font-size: 0.85rem; font-weight: 600;">${escapeHtml(cleanHtmlText(inc.title))}</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(cleanHtmlText(inc.publishers || 'News Outlet'))}</div>
                    </div>
                    <a href="${inc.primary_url}" target="_blank" rel="noopener noreferrer"><i class="fa-solid fa-arrow-up-right-from-square"></i> Read Article</a>
                </div>
            `;
        } else {
            sourcesContainer.innerHTML = '<div style="color: var(--text-muted);">No external links recorded.</div>';
        }
    }
}

// ----------------- CSV EXPORT -----------------

function exportCSV() {
    const listToExport = (filteredIncidents && filteredIncidents.length > 0) ? filteredIncidents : allIncidents;
    if (listToExport.length === 0) {
        alert('No incidents to export.');
        return;
    }

    const headers = [
        "Incident ID", "Title", "Category", "Incident Date", "Location",
        "District", "State", "Latitude", "Longitude", "Legal Status",
        "Source Count", "Publishers", "Primary URL", "Summary"
    ];

    const escapeCsvField = (val) => {
        if (val === null || val === undefined) return '""';
        const str = String(val).replace(/"/g, '""');
        return `"${str}"`;
    };

    let csvContent = "\uFEFF"; // UTF-8 Byte Order Mark for Excel
    csvContent += headers.join(",") + "\r\n";

    listToExport.forEach(inc => {
        const row = [
            escapeCsvField(inc.id),
            escapeCsvField(inc.title),
            escapeCsvField(inc.category),
            escapeCsvField(inc.incident_date),
            escapeCsvField(inc.location_name),
            escapeCsvField(inc.district),
            escapeCsvField(inc.state),
            escapeCsvField(inc.latitude),
            escapeCsvField(inc.longitude),
            escapeCsvField(inc.legal_status),
            escapeCsvField(inc.source_count || 1),
            escapeCsvField(inc.publishers),
            escapeCsvField(inc.primary_url),
            escapeCsvField(inc.summary)
        ];
        csvContent += row.join(",") + "\r\n";
    });

    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const link = document.createElement("a");
    const today = new Date().toISOString().slice(0, 10);
    link.href = URL.createObjectURL(blob);
    link.download = `gbv_incidents_report_${today}.csv`;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
}

// ----------------- SHEETJS EXCEL (.XLSX) EXPORT (IIPMaps Stack) -----------------

function exportXLSX() {
    if (typeof XLSX === 'undefined') {
        alert('Excel export library is loading, please try again in a moment.');
        return;
    }

    const listToExport = (filteredIncidents && filteredIncidents.length > 0) ? filteredIncidents : allIncidents;
    if (listToExport.length === 0) {
        alert('No incidents to export.');
        return;
    }

    // 1. Incidents dataset sheet
    const incidentRows = listToExport.map(inc => ({
        "Incident ID": inc.id,
        "Title": cleanHtmlText(inc.title),
        "Category": inc.category,
        "Incident Date": inc.incident_date || '',
        "Location": inc.location_name || '',
        "District": inc.district || '',
        "State": inc.state || '',
        "Latitude": inc.latitude || '',
        "Longitude": inc.longitude || '',
        "Legal Status": inc.legal_status || '',
        "Source Count": inc.source_count || 1,
        "Publishers": inc.publishers || '',
        "Primary URL": inc.primary_url || '',
        "Summary": cleanHtmlText(inc.summary || '')
    }));

    // 2. Thematic State Summary Sheet
    const stateStats = getIncidentStatsByState();
    const stateSummaryRows = [];
    stateStats.forEach((st, name) => {
        const sortedCats = Object.entries(st.categories).sort((a, b) => b[1] - a[1]);
        stateSummaryRows.push({
            "State / UT": name,
            "Total Incidents": st.count,
            "Top Category": sortedCats.length > 0 ? sortedCats[0][0] : '-',
            "Sexual Assault": st.categories["Sexual Assault"] || 0,
            "POCSO / Minor": st.categories["POCSO / Minor"] || 0,
            "Domestic Violence": st.categories["Domestic Violence"] || 0,
            "Dowry Violence": st.categories["Dowry Violence"] || 0,
            "Harassment & Stalking": st.categories["Harassment & Stalking"] || 0,
            "Acid Attack": st.categories["Acid Attack"] || 0,
            "Other GBV": st.categories["Other GBV"] || 0
        });
    });
    stateSummaryRows.sort((a, b) => b["Total Incidents"] - a["Total Incidents"]);

    const wb = XLSX.utils.book_new();
    const wsIncidents = XLSX.utils.json_to_sheet(incidentRows);
    const wsSummary = XLSX.utils.json_to_sheet(stateSummaryRows);

    XLSX.utils.book_append_sheet(wb, wsIncidents, "Incidents");
    XLSX.utils.book_append_sheet(wb, wsSummary, "State Density Summary");

    const dateStr = new Date().toISOString().split('T')[0];
    XLSX.writeFile(wb, `GBV_Explorer_India_Report_${dateStr}.xlsx`);
}

// ----------------- HIGH-RES MAP IMAGE EXPORT (IIPMaps Stack) -----------------

async function exportMapImage() {
    if (typeof html2canvas === 'undefined') {
        alert('Map image exporter is still loading. Please try again in a few seconds.');
        return;
    }

    const mapEl = document.getElementById('map-container');
    if (!mapEl) return;

    const origCursor = document.body.style.cursor;
    document.body.style.cursor = 'wait';

    try {
        // Temporarily hide floating interactive controls during capture
        const floatingCtrls = document.querySelector('.zoom-floating-controls');
        const filterBar = document.getElementById('filter-bar');
        const sideDrawer = document.getElementById('side-drawer');
        const zoomCtrl = document.querySelector('.leaflet-control-zoom');
        
        const prevFloating = floatingCtrls ? floatingCtrls.style.display : '';
        const prevFilter = filterBar ? filterBar.style.display : '';
        const prevDrawer = sideDrawer ? sideDrawer.style.display : '';
        const prevZoom = zoomCtrl ? zoomCtrl.style.display : '';
        
        if (floatingCtrls) floatingCtrls.style.display = 'none';
        if (filterBar) filterBar.style.display = 'none';
        if (sideDrawer) sideDrawer.style.display = 'none';
        if (zoomCtrl) zoomCtrl.style.display = 'none';

        const canvas = await html2canvas(mapEl, {
            useCORS: true,
            allowTaint: true,
            scale: 2, // 2x Retina high-resolution render
            logging: false,
            backgroundColor: '#0f172a'
        });

        // Restore styles
        if (floatingCtrls) floatingCtrls.style.display = prevFloating;
        if (filterBar) filterBar.style.display = prevFilter;
        if (sideDrawer) sideDrawer.style.display = prevDrawer;
        if (zoomCtrl) zoomCtrl.style.display = prevZoom;
        document.body.style.cursor = origCursor;

        // Compose final image with branded banner and Survey of India compliance footer
        const finalCanvas = document.createElement('canvas');
        finalCanvas.width = canvas.width;
        finalCanvas.height = canvas.height + 130;
        const ctx = finalCanvas.getContext('2d');

        // Header Background
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, 0, finalCanvas.width, 75);

        // Header Title
        ctx.fillStyle = '#f8fafc';
        ctx.font = 'bold 26px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        ctx.fillText('GBV Explorer India — Spatial Incident Distribution', 28, 45);

        // Header Subtitle / Stats Chip
        ctx.fillStyle = '#94a3b8';
        ctx.font = '500 14px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        const statsTxt = `Reports: ${filteredIncidents.length} | Mode: ${currentLayerMode.toUpperCase()} | ${new Date().toLocaleDateString('en-IN')}`;
        ctx.fillText(statsTxt, finalCanvas.width - 28 - ctx.measureText(statsTxt).width, 45);

        // Draw Map
        ctx.drawImage(canvas, 0, 75);

        // Footer Background
        ctx.fillStyle = '#0f172a';
        ctx.fillRect(0, finalCanvas.height - 55, finalCanvas.width, 55);

        // Footer Attribution
        ctx.fillStyle = '#64748b';
        ctx.font = '13px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
        ctx.fillText('Boundaries: OpenStreetMap India / Survey of India compliant • Verified News Monitoring', 28, finalCanvas.height - 22);

        const brandTxt = 'https://rohitrzd17.github.io/GBV-Explorer-India/';
        ctx.fillText(brandTxt, finalCanvas.width - 28 - ctx.measureText(brandTxt).width, finalCanvas.height - 22);

        // Trigger Download
        const link = document.createElement('a');
        link.download = `GBV_Explorer_India_Map_${new Date().toISOString().split('T')[0]}.png`;
        link.href = finalCanvas.toDataURL('image/png');
        link.click();
    } catch (err) {
        document.body.style.cursor = origCursor;
        console.error('Error generating map image:', err);
        alert('Could not export map image: ' + err.message);
    }
}

// ----------------- ADMIN SECURITY & PORTAL -----------------

// Check authentication before opening admin
function handleAdminClick() {
    if (isAdminAuthenticated) {
        openAdminModal();
    } else {
        openAdminAuthModal();
    }
}

// Open Password Authentication Modal
function openAdminAuthModal() {
    document.getElementById('admin-password-input').value = '';
    document.getElementById('auth-error-msg').style.display = 'none';
    document.getElementById('admin-auth-modal').classList.add('active');
    document.getElementById('admin-password-input').focus();
}

function closeAdminAuthModal() {
    document.getElementById('admin-auth-modal').classList.remove('active');
}

// Authenticate Passphrase (Protected via cryptographic SHA-256)
async function submitAdminAuth(e) {
    e.preventDefault();
    const enteredPassword = document.getElementById('admin-password-input').value;
    const computedHash = await sha256(enteredPassword);

    // Verify hash against precomputed standard hash
    if (computedHash === ADMIN_PASS_HASH) {
        isAdminAuthenticated = true;
        sessionStorage.removeItem('gbv_admin_auth');
        closeAdminAuthModal();
        openAdminModal();
    } else {
        const errEl = document.getElementById('auth-error-msg');
        errEl.style.display = 'block';
        document.getElementById('admin-password-input').value = '';
        document.getElementById('admin-password-input').focus();
    }
}

// Open Admin Modal
function openAdminModal() {
    document.getElementById('admin-modal').classList.add('active');
    loadAdminIncidents();
    loadAdminFeeds();
    loadAdminSources();
}

// Close Admin Modal
function closeAdminModal() {
    document.getElementById('admin-modal').classList.remove('active');
}

// Tab Switching
function setupAdminTabs() {
    const tabBtns = document.querySelectorAll('.admin-tab-btn');
    tabBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            tabBtns.forEach(b => b.classList.remove('active'));
            document.querySelectorAll('.admin-tab-pane').forEach(p => p.classList.remove('active'));

            btn.classList.add('active');
            const targetPane = document.getElementById(btn.dataset.tab);
            if (targetPane) targetPane.classList.add('active');
        });
    });
}

// Load Incidents in Admin Table
async function loadAdminIncidents(search = '') {
    const tbody = document.getElementById('admin-inc-tbody');
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-muted);">Loading incidents...</td></tr>';
    try {
        let incs = [];
        if (!isStaticMode) {
            const url = search ? `/api/admin/incidents?search=${encodeURIComponent(search)}` : '/api/admin/incidents';
            const res = await fetch(url);
            const data = await res.json();
            incs = data.incidents || [];
        } else {
            incs = allIncidents;
            if (search) {
                const s = search.toLowerCase();
                incs = incs.filter(i => (i.title || '').toLowerCase().includes(s) || (i.district || '').toLowerCase().includes(s));
            }
        }

        document.getElementById('admin-inc-count').textContent = incs.length;
        tbody.innerHTML = '';

        if (incs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; color: var(--text-muted);">No incidents found.</td></tr>';
            return;
        }

        incs.forEach(inc => {
            const tr = document.createElement('tr');
            const hasCoords = inc.latitude && inc.longitude;
            tr.innerHTML = `
                <td><strong>#${inc.id}</strong></td>
                <td style="max-width: 250px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(cleanHtmlText(inc.title))}">${escapeHtml(cleanHtmlText(inc.title))}</td>
                <td><span class="badge ${CATEGORY_BADGES[inc.category] || 'badge-other'}">${inc.category}</span></td>
                <td>${escapeHtml(inc.district || inc.location_name || inc.state || 'Unmapped')}</td>
                <td>${inc.incident_date || '-'}</td>
                <td>${hasCoords ? `<span style="color:#10b981;">✓ ${inc.latitude.toFixed(2)}, ${inc.longitude.toFixed(2)}</span>` : '<span style="color:#f59e0b;">Unmapped</span>'}</td>
                <td>
                    <button class="action-btn action-edit" title="Edit Incident" onclick="openEditModal(${inc.id})"><i class="fa-solid fa-pen"></i></button>
                    <button class="action-btn action-delete" title="Delete Incident" onclick="deleteIncident(${inc.id})"><i class="fa-solid fa-trash"></i></button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="7" style="color: #ef4444; text-align:center;">Failed to load incidents.</td></tr>';
    }
}

// Open Edit Incident Modal
function openEditModal(incidentId) {
    const inc = allIncidents.find(i => i.id === incidentId);
    if (!inc) return;

    document.getElementById('edit-id').value = inc.id;
    document.getElementById('edit-inc-id-display').textContent = inc.id;
    document.getElementById('edit-title').value = cleanHtmlText(inc.title || '');
    document.getElementById('edit-category').value = inc.category || 'Other GBV';
    document.getElementById('edit-date').value = inc.incident_date || '';
    document.getElementById('edit-location').value = inc.location_name || '';
    document.getElementById('edit-district').value = inc.district || '';
    document.getElementById('edit-state').value = inc.state || '';
    document.getElementById('edit-lat').value = inc.latitude || '';
    document.getElementById('edit-lon').value = inc.longitude || '';
    document.getElementById('edit-status').value = inc.legal_status || 'Under Investigation';
    document.getElementById('edit-summary').value = cleanHtmlText(inc.summary || '');

    document.getElementById('edit-incident-modal').classList.add('active');
}

// Close Edit Modal
function closeEditModal() {
    document.getElementById('edit-incident-modal').classList.remove('active');
}

// Delete Incident
async function deleteIncident(id) {
    if (!confirm(`Are you sure you want to delete incident #${id}?`)) return;
    let deletedOnServer = false;
    try {
        const res = await fetch(`/api/admin/incidents/${id}`, { method: 'DELETE' });
        if (res.ok) deletedOnServer = true;
    } catch (err) {
        console.warn('Backend DELETE failed or static mode, applying client-side deletion.');
    }

    if (deletedOnServer || isStaticMode || window.location.hostname.includes('github.io')) {
        allIncidents = allIncidents.filter(i => i.id !== id);
        saveClientDelete(id);
        loadAdminIncidents();
        applyFilters();
        fetchStats();
        alert(`Incident #${id} removed successfully.`);
    } else {
        alert('Failed to delete incident.');
    }
}

// Load Feeds in Admin Table
async function loadAdminFeeds() {
    const tbody = document.getElementById('admin-feeds-tbody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color: var(--text-muted);">Loading feeds...</td></tr>';
    try {
        let feeds = [];
        if (!isStaticMode) {
            const res = await fetch('/api/admin/feeds');
            const data = await res.json();
            feeds = data.feeds || [];
        } else {
            const cacheBuster = `?t=${Date.now()}`;
            const res = await fetch(`./data/feeds.json${cacheBuster}`, { cache: 'no-store' });
            const data = await res.json();
            feeds = data.feeds || [];
        }
        tbody.innerHTML = '';

        feeds.forEach(f => {
            const tr = document.createElement('tr');
            const typeBadge = (f.feed_type === 'rss_url' || (f.query && f.query.startsWith('http')))
                ? '<span class="badge" style="background:#0ea5e9; color:#fff; font-size:0.65rem; padding:2px 5px; border-radius:3px;">RSS XML</span>'
                : '<span class="badge" style="background:#8b5cf6; color:#fff; font-size:0.65rem; padding:2px 5px; border-radius:3px;">Google News</span>';

            const constraintBadge = (f.constraints === 'gbv_strict')
                ? '<span class="badge" style="background:#10b981; color:#fff; font-size:0.65rem; padding:2px 5px; border-radius:3px;" title="Strict multi-category GBV filtering active"><i class="fa-solid fa-shield-halved"></i> Strict GBV</span>'
                : `<span class="badge" style="background:#f59e0b; color:#fff; font-size:0.65rem; padding:2px 5px; border-radius:3px;" title="${escapeHtml(f.constraints)}">${escapeHtml(f.constraints || 'Custom')}</span>`;

            tr.innerHTML = `
                <td>
                    <div style="font-weight:600; font-size:0.85rem;">${escapeHtml(f.name)}</div>
                    <div style="display:flex; align-items:center; gap:6px; margin-top:2px;">
                        ${typeBadge}
                        <span style="font-size:0.7rem; color:var(--text-muted); max-width:200px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" title="${escapeHtml(f.query)}">${escapeHtml(f.query)}</span>
                    </div>
                </td>
                <td>${escapeHtml(f.region || 'India')}</td>
                <td>${constraintBadge}</td>
                <td>
                    <label class="toggle-switch">
                        <input type="checkbox" ${f.is_active ? 'checked' : ''} onchange="toggleFeedActive(${f.id}, this.checked)">
                        <span class="slider"></span>
                    </label>
                </td>
                <td style="font-size:0.7rem; color:var(--text-muted);">${f.last_fetched_at ? f.last_fetched_at.slice(0, 16) : 'Never'}</td>
                <td>
                    <button class="action-btn action-run" title="Fetch now" onclick="triggerFeedFetch(${f.id})"><i class="fa-solid fa-play"></i></button>
                    <button class="action-btn action-delete" title="Delete feed" onclick="deleteFeed(${f.id})"><i class="fa-solid fa-trash"></i></button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="6" style="color: #ef4444; text-align:center;">Failed to load feeds.</td></tr>';
    }
}

// Toggle Feed Active
async function toggleFeedActive(feedId, isActive) {
    try {
        await fetch(`/api/admin/feeds/${feedId}/toggle`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_active: isActive })
        });
    } catch (err) {
        console.error('Failed to toggle feed:', err);
    }
}

// Trigger Feed Fetch
async function triggerFeedFetch(feedId) {
    try {
        const res = await fetch(`/api/admin/feeds/${feedId}/fetch`, { method: 'POST' });
        if (res.ok) {
            alert(`Fetch initiated for feed #${feedId}. New articles will process in the background.`);
            setTimeout(() => {
                loadAdminFeeds();
                fetchIncidents();
            }, 3000);
        }
    } catch (err) {
        alert('Failed to trigger feed fetch.');
    }
}

// Delete Feed
async function deleteFeed(feedId) {
    if (!confirm(`Delete feed #${feedId}?`)) return;
    try {
        const res = await fetch(`/api/admin/feeds/${feedId}`, { method: 'DELETE' });
        if (res.ok) {
            loadAdminFeeds();
        }
    } catch (err) {
        alert('Failed to delete feed.');
    }
}

// Load Raw Sources in Admin Table
async function loadAdminSources(search = '') {
    const tbody = document.getElementById('admin-src-tbody');
    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color: var(--text-muted);">Loading sources...</td></tr>';
    try {
        const url = search ? `/api/admin/sources?search=${encodeURIComponent(search)}` : '/api/admin/sources';
        const res = await fetch(url);
        const data = await res.json();
        const sources = data.sources || [];
        tbody.innerHTML = '';

        if (sources.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color: var(--text-muted);">No news sources found.</td></tr>';
            return;
        }

        sources.forEach(src => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>#${src.id}</strong></td>
                <td style="max-width: 280px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">
                    <a href="${src.url}" target="_blank" style="color:var(--accent); text-decoration:none;">${escapeHtml(src.headline)}</a>
                </td>
                <td>${escapeHtml(src.publisher || 'Unknown')}</td>
                <td>${src.published_at ? src.published_at.slice(0, 10) : '-'}</td>
                <td>${src.incident_id ? `<span style="color:#10b981;">#${src.incident_id}</span>` : '<span style="color:var(--text-muted);">Unlinked</span>'}</td>
                <td>
                    <button class="action-btn action-delete" title="Delete source" onclick="deleteSource(${src.id})"><i class="fa-solid fa-trash"></i></button>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        tbody.innerHTML = '<tr><td colspan="6" style="color: #ef4444; text-align:center;">Failed to load sources.</td></tr>';
    }
}

// Delete Source
async function deleteSource(sourceId) {
    if (!confirm(`Delete news report #${sourceId}?`)) return;
    try {
        const res = await fetch(`/api/admin/sources/${sourceId}`, { method: 'DELETE' });
        if (res.ok) {
            loadAdminSources();
        }
    } catch (err) {
        alert('Failed to delete source.');
    }
}

// Purge Foreign Stories
async function purgeForeignStories() {
    if (!confirm('Purge all non-India news stories and foreign court cases from database?')) return;
    try {
        const res = await fetch('/api/admin/purge-foreign', { method: 'POST' });
        const data = await res.json();
        alert(`Purge completed! Deleted ${data.result.deleted_incidents} incidents and ${data.result.deleted_sources} sources.`);
        loadAdminIncidents();
        loadAdminSources();
        fetchIncidents();
    } catch (err) {
        alert('Failed to purge foreign records.');
    }
}

// Utility: Escape HTML
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Setup Event Listeners
function setupEvents() {
    document.getElementById('filter-category').addEventListener('change', applyFilters);
    document.getElementById('filter-state').addEventListener('change', applyFilters);
    document.getElementById('filter-date').addEventListener('change', applyFilters);
    document.getElementById('filter-search').addEventListener('input', applyFilters);

    document.getElementById('reset-filters-btn').addEventListener('click', () => {
        document.getElementById('filter-category').value = 'All';
        document.getElementById('filter-state').value = 'All';
        document.getElementById('filter-date').value = '180d';
        document.getElementById('filter-search').value = '';
        applyFilters();
    });

    document.getElementById('toggle-list-btn').addEventListener('click', () => {
        document.getElementById('side-drawer').classList.toggle('hidden');
    });

    document.getElementById('close-drawer-btn').addEventListener('click', () => {
        document.getElementById('side-drawer').classList.add('hidden');
    });

    document.getElementById('close-modal-btn').addEventListener('click', () => {
        document.getElementById('incident-modal').classList.remove('active');
    });

    document.getElementById('incident-modal').addEventListener('click', (e) => {
        if (e.target === document.getElementById('incident-modal')) {
            document.getElementById('incident-modal').classList.remove('active');
        }
    });

    // Layer Mode Switcher (Clusters / Choropleth / Hybrid)
    document.querySelectorAll('.layer-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const mode = e.currentTarget.dataset.mode;
            setLayerMode(mode);
        });
    });

    // Export Dropdown Trigger
    const exportDropdownBtn = document.getElementById('export-dropdown-btn');
    const exportDropdownMenu = document.getElementById('export-dropdown-menu');
    if (exportDropdownBtn && exportDropdownMenu) {
        exportDropdownBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            exportDropdownMenu.classList.toggle('hidden');
        });
        document.addEventListener('click', (e) => {
            if (!exportDropdownBtn.contains(e.target) && !exportDropdownMenu.contains(e.target)) {
                exportDropdownMenu.classList.add('hidden');
            }
        });
    }

    // Export Action Triggers
    const exportCsvBtn = document.getElementById('export-csv-btn');
    if (exportCsvBtn) {
        exportCsvBtn.addEventListener('click', () => {
            if (exportDropdownMenu) exportDropdownMenu.classList.add('hidden');
            exportCSV();
        });
    }

    const exportXlsxBtn = document.getElementById('export-xlsx-btn');
    if (exportXlsxBtn) {
        exportXlsxBtn.addEventListener('click', () => {
            if (exportDropdownMenu) exportDropdownMenu.classList.add('hidden');
            exportXLSX();
        });
    }

    const exportImgBtn = document.getElementById('export-image-btn');
    if (exportImgBtn) {
        exportImgBtn.addEventListener('click', () => {
            if (exportDropdownMenu) exportDropdownMenu.classList.add('hidden');
            exportMapImage();
        });
    }

    // Admin Auth & Modal triggers
    document.getElementById('admin-btn').addEventListener('click', handleAdminClick);
    document.getElementById('admin-auth-form').addEventListener('submit', submitAdminAuth);
    document.getElementById('close-auth-btn').addEventListener('click', closeAdminAuthModal);
    document.getElementById('cancel-auth-btn').addEventListener('click', closeAdminAuthModal);

    document.getElementById('close-admin-btn').addEventListener('click', closeAdminModal);
    document.getElementById('admin-purge-btn').addEventListener('click', purgeForeignStories);

    // Edit Modal triggers
    document.getElementById('close-edit-btn').addEventListener('click', closeEditModal);
    document.getElementById('cancel-edit-btn').addEventListener('click', closeEditModal);

    // Admin Incidents search
    document.getElementById('admin-inc-search-btn').addEventListener('click', () => {
        loadAdminIncidents(document.getElementById('admin-inc-search').value);
    });
    document.getElementById('admin-inc-search').addEventListener('keyup', (e) => {
        if (e.key === 'Enter') loadAdminIncidents(e.target.value);
    });

    // Admin Sources search
    document.getElementById('admin-src-search-btn').addEventListener('click', () => {
        loadAdminSources(document.getElementById('admin-src-search').value);
    });
    document.getElementById('admin-src-search').addEventListener('keyup', (e) => {
        if (e.key === 'Enter') loadAdminSources(e.target.value);
    });

    // Add Incident Form Submit
    document.getElementById('add-incident-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            title: document.getElementById('add-title').value,
            category: document.getElementById('add-category').value,
            incident_date: document.getElementById('add-date').value || null,
            location_name: document.getElementById('add-location').value || null,
            state: document.getElementById('add-state').value || null,
            latitude: document.getElementById('add-lat').value ? parseFloat(document.getElementById('add-lat').value) : null,
            longitude: document.getElementById('add-lon').value ? parseFloat(document.getElementById('add-lon').value) : null,
            legal_status: document.getElementById('add-status').value,
            summary: document.getElementById('add-summary').value || '',
            source_url: document.getElementById('add-source-url').value || null,
            publisher: document.getElementById('add-publisher').value || 'Manual Entry'
        };

        let added = false;
        try {
            const res = await fetch('/api/admin/incidents', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) added = true;
        } catch (err) {
            console.warn('Backend POST failed or static mode, applying client-side add.');
        }

        if (added || isStaticMode || window.location.hostname.includes('github.io')) {
            const newId = Math.max(0, ...allIncidents.map(i => i.id || 0)) + 1;
            const newInc = { id: newId, ...payload, source_count: 1 };
            allIncidents.unshift(newInc);
            saveClientAdd(newInc);
            alert('Incident added successfully!');
            document.getElementById('add-incident-form').reset();
            loadAdminIncidents();
            applyFilters();
            fetchStats();
        } else {
            alert('Failed to add incident.');
        }
    });

    // Edit Incident Form Submit
    document.getElementById('edit-incident-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const id = parseInt(document.getElementById('edit-id').value, 10);
        const payload = {
            title: document.getElementById('edit-title').value,
            category: document.getElementById('edit-category').value,
            incident_date: document.getElementById('edit-date').value || null,
            location_name: document.getElementById('edit-location').value || null,
            district: document.getElementById('edit-district').value || null,
            state: document.getElementById('edit-state').value || null,
            latitude: document.getElementById('edit-lat').value ? parseFloat(document.getElementById('edit-lat').value) : null,
            longitude: document.getElementById('edit-lon').value ? parseFloat(document.getElementById('edit-lon').value) : null,
            legal_status: document.getElementById('edit-status').value,
            summary: document.getElementById('edit-summary').value || ''
        };

        let updated = false;
        try {
            const res = await fetch(`/api/admin/incidents/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) updated = true;
        } catch (err) {
            console.warn('Backend PUT failed or static mode, applying client-side edit.');
        }

        if (updated || isStaticMode || window.location.hostname.includes('github.io')) {
            const idx = allIncidents.findIndex(i => i.id === id);
            if (idx !== -1) {
                allIncidents[idx] = { ...allIncidents[idx], ...payload };
            }
            saveClientEdit({ id, ...payload });
            closeEditModal();
            loadAdminIncidents();
            applyFilters();
            fetchStats();
            alert(`Incident #${id} updated successfully!`);
        } else {
            alert('Failed to update incident.');
        }
    });

    // Add Feed Form Submit
    document.getElementById('add-feed-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
            name: document.getElementById('feed-name').value,
            feed_type: document.getElementById('feed-type') ? document.getElementById('feed-type').value : 'rss_url',
            query: document.getElementById('feed-query').value,
            region: document.getElementById('feed-region').value || 'India',
            category_hint: document.getElementById('feed-cat-hint').value,
            constraints: document.getElementById('feed-constraints') ? document.getElementById('feed-constraints').value : 'gbv_strict'
        };

        try {
            const res = await fetch('/api/admin/feeds', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                alert('Feed added successfully!');
                document.getElementById('add-feed-form').reset();
                if (document.getElementById('feed-constraints')) {
                    document.getElementById('feed-constraints').value = 'gbv_strict';
                }
                loadAdminFeeds();
            } else {
                alert('Failed to add feed.');
            }
        } catch (err) {
            alert('Error adding feed.');
        }
    });

    // Refresh button trigger
    document.getElementById('refresh-btn').addEventListener('click', async () => {
        const icon = document.getElementById('refresh-icon');
        icon.classList.add('fa-spin');
        try {
            await fetch('/api/pipeline/refresh', { method: 'POST' });
            setTimeout(() => {
                fetchIncidents();
                icon.classList.remove('fa-spin');
            }, 3000);
        } catch (err) {
            icon.classList.remove('fa-spin');
        }
    });

    // Admin Export JSON button trigger
    const adminExportBtn = document.getElementById('admin-export-btn');
    if (adminExportBtn) {
        adminExportBtn.addEventListener('click', () => {
            const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify({ incidents: allIncidents }, null, 2));
            const dlAnchor = document.createElement('a');
            dlAnchor.setAttribute("href", dataStr);
            dlAnchor.setAttribute("download", `incidents_export_${new Date().toISOString().slice(0, 10)}.json`);
            document.body.appendChild(dlAnchor);
            dlAnchor.click();
            dlAnchor.remove();
        });
    }

    // Drawer & Filter Sheet DOM Elements
    const sideDrawer = document.getElementById('side-drawer');
    const drawerBackdrop = document.getElementById('drawer-backdrop');
    const toggleListBtn = document.getElementById('toggle-list-btn');
    const closeDrawerBtn = document.getElementById('close-drawer-btn');
    const closeDrawerMobileBtn = document.getElementById('close-drawer-mobile-btn');
    const floatingIncidentsBtn = document.getElementById('floating-incidents-btn');
    const floatingFilterBtn = document.getElementById('floating-filter-btn');
    const closeFilterSheetBtn = document.getElementById('close-filter-sheet-btn');
    const applyFiltersBtn = document.getElementById('apply-filters-btn');
    const filterBar = document.getElementById('filter-bar');

    // Drawer Open/Close Logic (NO backdrop/blur on PC!)
    function openDrawer() {
        sideDrawer.classList.remove('hidden');
        sideDrawer.classList.add('active');
        // Never show backdrop blur on PC; on mobile, drawer is 100% full screen
        if (drawerBackdrop) drawerBackdrop.classList.remove('active');
    }

    function closeDrawer() {
        sideDrawer.classList.add('hidden');
        sideDrawer.classList.remove('active');
    }

    if (toggleListBtn) {
        toggleListBtn.addEventListener('click', () => {
            if (sideDrawer.classList.contains('hidden') || !sideDrawer.classList.contains('active')) {
                openDrawer();
            } else {
                closeDrawer();
            }
        });
    }
    if (floatingIncidentsBtn) floatingIncidentsBtn.addEventListener('click', openDrawer);
    if (closeDrawerBtn) closeDrawerBtn.addEventListener('click', closeDrawer);
    if (closeDrawerMobileBtn) closeDrawerMobileBtn.addEventListener('click', closeDrawer);

    // Mobile Filters Sheet Logic
    function openFiltersSheet() {
        if (filterBar) filterBar.classList.add('active');
        if (drawerBackdrop && window.innerWidth <= 820) drawerBackdrop.classList.add('active');
    }

    function closeFiltersSheet() {
        if (filterBar) filterBar.classList.remove('active');
        if (drawerBackdrop) drawerBackdrop.classList.remove('active');
    }

    if (floatingFilterBtn) floatingFilterBtn.addEventListener('click', openFiltersSheet);
    if (closeFilterSheetBtn) closeFilterSheetBtn.addEventListener('click', closeFiltersSheet);
    if (applyFiltersBtn) applyFiltersBtn.addEventListener('click', closeFiltersSheet);
    if (filterBar) {
        filterBar.addEventListener('click', (e) => {
            if (e.target === filterBar) {
                closeFiltersSheet();
            }
        });
    }

    // Mobile Menu Dropdown Logic
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const mobileMenuSheet = document.getElementById('mobile-menu-sheet');
    const closeMobileMenuBtn = document.getElementById('close-mobile-menu-btn');

    function toggleMobileMenu() {
        if (!mobileMenuSheet) return;
        const isActive = mobileMenuSheet.classList.toggle('active');
        if (drawerBackdrop && window.innerWidth <= 820) {
            drawerBackdrop.classList.toggle('active', isActive);
        }
    }

    function closeMobileMenu() {
        if (mobileMenuSheet) mobileMenuSheet.classList.remove('active');
        if (drawerBackdrop) drawerBackdrop.classList.remove('active');
    }

    if (mobileMenuBtn) mobileMenuBtn.addEventListener('click', toggleMobileMenu);
    if (closeMobileMenuBtn) closeMobileMenuBtn.addEventListener('click', closeMobileMenu);

    // Mobile Layer Switcher
    document.querySelectorAll('.mobile-layer-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const mode = e.currentTarget.dataset.mode;
            setLayerMode(mode);
        });
    });

    const mobileExportBtn = document.getElementById('mobile-export-csv-btn');
    if (mobileExportBtn) {
        mobileExportBtn.addEventListener('click', () => {
            closeMobileMenu();
            exportCSV();
        });
    }

    const mobileExportXlsxBtn = document.getElementById('mobile-export-xlsx-btn');
    if (mobileExportXlsxBtn) {
        mobileExportXlsxBtn.addEventListener('click', () => {
            closeMobileMenu();
            exportXLSX();
        });
    }

    const mobileExportImgBtn = document.getElementById('mobile-export-img-btn');
    if (mobileExportImgBtn) {
        mobileExportImgBtn.addEventListener('click', () => {
            closeMobileMenu();
            exportMapImage();
        });
    }

    const mobileAdminBtn = document.getElementById('mobile-admin-btn');
    if (mobileAdminBtn) {
        mobileAdminBtn.addEventListener('click', () => {
            closeMobileMenu();
            handleAdminClick();
        });
    }

    const mobileRefreshBtn = document.getElementById('mobile-refresh-btn');
    if (mobileRefreshBtn) {
        mobileRefreshBtn.addEventListener('click', () => {
            closeMobileMenu();
            const refBtn = document.getElementById('refresh-btn');
            if (refBtn) refBtn.click();
        });
    }

    // Backdrop click dismisses mobile sheets
    if (drawerBackdrop) {
        drawerBackdrop.addEventListener('click', () => {
            closeFiltersSheet();
            closeMobileMenu();
        });
    }

    // Drawer Live Search
    const drawerSearch = document.getElementById('drawer-quick-search');
    if (drawerSearch) {
        drawerSearch.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();
            const cards = document.querySelectorAll('#incident-list .incident-card');
            cards.forEach(card => {
                const text = card.textContent.toLowerCase();
                card.style.display = text.includes(query) ? '' : 'none';
            });
        });
    }

    // Collapsible Map Legend
    const toggleLegendBtn = document.getElementById('toggle-legend-btn');
    const legendHeader = document.getElementById('legend-header');
    function toggleLegend() {
        const legend = document.getElementById('map-legend');
        if (!legend) return;
        legend.classList.toggle('collapsed');
        const chevron = document.getElementById('legend-chevron');
        if (chevron) {
            chevron.classList.toggle('fa-chevron-down');
            chevron.classList.toggle('fa-chevron-up');
        }
    }
    if (toggleLegendBtn) toggleLegendBtn.addEventListener('click', (e) => { e.stopPropagation(); toggleLegend(); });
    if (legendHeader) legendHeader.addEventListener('click', toggleLegend);

    setupAdminTabs();
}

// Boot
window.addEventListener('DOMContentLoaded', () => {
    sessionStorage.removeItem('gbv_admin_auth'); // Reset session auth on page load
    if (window.innerWidth <= 820) {
        const legend = document.getElementById('map-legend');
        if (legend) legend.classList.add('collapsed');
        const legendChevron = document.getElementById('legend-chevron');
        if (legendChevron) {
            legendChevron.classList.remove('fa-chevron-up');
            legendChevron.classList.add('fa-chevron-down');
        }
    }
    initMap();
    setupEvents();
    fetchIncidents();
});
