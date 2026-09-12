// GBV Explorer India - Interactive Map & Admin Management Logic

let map;
let markersGroup;
let allIncidents = [];
let filteredIncidents = [];
let markerMap = new Map(); // incident.id -> Leaflet marker
let indianStatesList = [];
let isStaticMode = false;

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

// Initialize Leaflet Map (100% Open-Source Tiles, No API Key required)
function initMap() {
    map = L.map('map', {
        center: [22.8, 80.0], // Geographic center of India
        zoom: 5,
        minZoom: 4,
        maxZoom: 14
    });

    // Open-source OpenStreetMap and CartoDB base tiles (Zero API key needed)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
        maxZoom: 19
    }).addTo(map);

    markersGroup = L.markerClusterGroup({
        showCoverageOnHover: false,
        maxClusterRadius: 40,
        spiderfyOnMaxZoom: true
    });
    map.addLayer(markersGroup);
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
            res = await fetch('./data/incidents.json');
        }

        const data = await res.json();
        allIncidents = data.incidents || [];
        populateStateFilter(allIncidents);
        applyFilters();
        fetchStats();
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
            res = await fetch('./data/stats.json');
        }

        const stats = await res.json();
        document.getElementById('stat-total').textContent = stats.total_incidents || allIncidents.length;
        document.getElementById('stat-geocoded').textContent = stats.geocoded_incidents || 0;
        
        let topCat = '-';
        if (stats.categories && Object.keys(stats.categories).length > 0) {
            topCat = Object.keys(stats.categories)[0];
        }
        document.getElementById('stat-top-cat').textContent = topCat;
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
                    <div class="popup-title">${escapeHtml(inc.title)}</div>
                    <div class="popup-meta">
                        <i class="fa-solid fa-location-dot"></i> ${inc.district || inc.location_name || inc.state || 'India'} &bull; ${inc.incident_date || 'Recent'}
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

// Render Side Drawer List
function renderIncidentList() {
    const listContainer = document.getElementById('incident-list');
    document.getElementById('drawer-count').textContent = filteredIncidents.length;
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
                <span class="incident-card-title">${escapeHtml(inc.title)}</span>
                <span class="badge ${CATEGORY_BADGES[inc.category] || 'badge-other'}">${inc.category}</span>
            </div>
            <div class="incident-card-meta">
                <span><i class="fa-solid fa-location-dot"></i> ${inc.district || inc.location_name || inc.state || 'India'}</span>
                <span><i class="fa-solid fa-calendar"></i> ${inc.incident_date || 'Recent'}</span>
                <span><i class="fa-solid fa-newspaper"></i> ${inc.source_count || 1} report(s)</span>
            </div>
        `;
        card.addEventListener('click', () => {
            if (inc.latitude && inc.longitude) {
                map.flyTo([inc.latitude, inc.longitude], 10, { duration: 1.2 });
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

    document.getElementById('modal-title').textContent = inc.title;
    const badge = document.getElementById('modal-category-badge');
    badge.className = `badge ${CATEGORY_BADGES[inc.category] || 'badge-other'}`;
    badge.textContent = inc.category;

    document.getElementById('modal-date').textContent = inc.incident_date || 'Not specified';
    document.getElementById('modal-location').textContent = `${inc.district || inc.location_name || 'Unspecified'}, ${inc.state || 'India'}`;
    document.getElementById('modal-status').textContent = inc.legal_status || 'Under Investigation';
    document.getElementById('modal-summary').textContent = inc.summary || inc.title;

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
                            <div style="font-size: 0.85rem; font-weight: 600;">${escapeHtml(inc.title)}</div>
                            <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(inc.publishers || 'News Outlet')}</div>
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
                        <div style="font-size: 0.85rem; font-weight: 600; margin-bottom: 2px;">${escapeHtml(src.headline)}</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(src.publisher || 'Media Outlet')} &bull; ${src.published_at ? src.published_at.slice(0, 10) : ''}</div>
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
                        <div style="font-size: 0.85rem; font-weight: 600;">${escapeHtml(inc.title)}</div>
                        <div style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(inc.publishers || 'News Outlet')}</div>
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

// ----------------- ADMIN SECURITY & PORTAL -----------------

// Check authentication before opening admin
function handleAdminClick() {
    if (sessionStorage.getItem('gbv_admin_auth') === 'true') {
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
        sessionStorage.setItem('gbv_admin_auth', 'true');
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
                <td style="max-width: 250px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;" title="${escapeHtml(inc.title)}">${escapeHtml(inc.title)}</td>
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
    document.getElementById('edit-title').value = inc.title || '';
    document.getElementById('edit-category').value = inc.category || 'Other GBV';
    document.getElementById('edit-date').value = inc.incident_date || '';
    document.getElementById('edit-location').value = inc.location_name || '';
    document.getElementById('edit-district').value = inc.district || '';
    document.getElementById('edit-state').value = inc.state || '';
    document.getElementById('edit-lat').value = inc.latitude || '';
    document.getElementById('edit-lon').value = inc.longitude || '';
    document.getElementById('edit-status').value = inc.legal_status || 'Under Investigation';
    document.getElementById('edit-summary').value = inc.summary || '';

    document.getElementById('edit-incident-modal').classList.add('active');
}

// Close Edit Modal
function closeEditModal() {
    document.getElementById('edit-incident-modal').classList.remove('active');
}

// Delete Incident
async function deleteIncident(id) {
    if (!confirm(`Are you sure you want to delete incident #${id}?`)) return;
    try {
        const res = await fetch(`/api/admin/incidents/${id}`, { method: 'DELETE' });
        if (res.ok) {
            loadAdminIncidents();
            fetchIncidents();
        } else {
            alert('Failed to delete incident.');
        }
    } catch (err) {
        alert('Network error while deleting incident.');
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
            const res = await fetch('./data/feeds.json');
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
        document.getElementById('filter-date').value = '30d';
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

    // CSV Export button trigger
    document.getElementById('export-csv-btn').addEventListener('click', exportCSV);

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

        try {
            const res = await fetch('/api/admin/incidents', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                alert('Incident added successfully!');
                document.getElementById('add-incident-form').reset();
                loadAdminIncidents();
                fetchIncidents();
            } else {
                alert('Failed to add incident.');
            }
        } catch (err) {
            alert('Error adding incident.');
        }
    });

    // Edit Incident Form Submit
    document.getElementById('edit-incident-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const id = document.getElementById('edit-id').value;
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

        try {
            const res = await fetch(`/api/admin/incidents/${id}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                closeEditModal();
                loadAdminIncidents();
                fetchIncidents();
            } else {
                alert('Failed to update incident.');
            }
        } catch (err) {
            alert('Error updating incident.');
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

    setupAdminTabs();
}

// Boot
window.addEventListener('DOMContentLoaded', () => {
    initMap();
    setupEvents();
    fetchIncidents();
});
