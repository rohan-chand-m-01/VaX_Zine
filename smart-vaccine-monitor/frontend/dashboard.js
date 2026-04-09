/**
 * Smart Vaccine Monitor — Premium Dashboard JavaScript
 * Handles WebSocket, Chart.js, real-time UI, toast notifications,
 * count-up animations, critical flash, and Sehat Saathi chatbot.
 */

// ============================================================
// CONFIGURATION
// ============================================================
const WS_URL = `ws://${window.location.host}/ws`;
const API_BASE = window.location.origin;
const MAX_CHART_POINTS = 60;
const MAX_TABLE_ROWS = 10;

// ============================================================
// STATE
// ============================================================
let ws = null;
let reconnectDelay = 1000;
const maxReconnectDelay = 30000;
let previousStatus = null;

// ── CRITICAL PDF download guard — one download per CRITICAL transition ──
let _criticalPdfDownloaded = false;   // reset each time we enter a fresh CRITICAL event

// ============================================================
// INITIALIZATION
// ============================================================
document.addEventListener('DOMContentLoaded', () => {
    initChart();
    initHumidityChart();
    initRiskDmgChart();
    // Live polling from ngrok
    fetchLatestData();
    setInterval(fetchLatestData, 3000);

    // Provide initial loading status
    document.getElementById('connection-text').textContent = 'Loading...';

    // Refresh report button
    document.getElementById('refresh-report-btn').addEventListener('click', fetchReport);
});

async function fetchLatestData() {
    try {
        const response = await fetch("https://alva-unsystematising-butyrically.ngrok-free.dev/api/readings/latest", {
            headers: {
                "ngrok-skip-browser-warning": "true"
            }
        });
        if (!response.ok) {
             console.error('Connection Error');
             showToast('Connection Error to external API', 'info', '⚠️', 3000);
             updateConnectionStatus(false);
             return;
        }
        const data = await response.json();
        
        // Map external payload to internal format for seamless UI/UX updates
        const mappedData = {
            timestamp: data.timestamp || new Date().toISOString(),
            temp_internal: data.internal_temp,
            temp_external: data.external_temp,
            humidity: data.humidity,
            exposure_minutes: data.unsafe_mins,
            vvm_damage: data.damage,
            risk_score: data.risk,
            status: data.status,
            is_anomaly: data.anomaly === 1 || data.anomaly === true,
            potency_percent: data.potency,
            eta_to_critical: data.eta
        };

        // ── PDF auto-download: fires every time status enters CRITICAL ──
        const currentStatus = mappedData.status;
        const wasCritical = previousStatus === 'CRITICAL';

        if (currentStatus === 'CRITICAL') {
            // Fresh CRITICAL transition (was not CRITICAL before)
            if (!wasCritical) {
                _criticalPdfDownloaded = false;  // new event — allow download
            }
            // Download once per CRITICAL entry
            if (!_criticalPdfDownloaded) {
                _criticalPdfDownloaded = true;
                setTimeout(() => {
                    showToast('🚨 CRITICAL — downloading incident PDF…', 'critical', '📄', 5000);
                    showDownloadButton();
                    autoDownloadPdf();
                }, 2000);
            }
        } else if (wasCritical) {
            // Left CRITICAL — reset 
            _criticalPdfDownloaded = false;
        }

        handleDataUpdate(mappedData);
        updateConnectionStatus(true);
    } catch (e) {
        console.error('Failed to fetch from ngrok:', e);
        showToast('Connection Error', 'info', '⚠️', 3000);
        updateConnectionStatus(false);
    }
}

// ============================================================
// TOAST NOTIFICATION SYSTEM
// ============================================================
function showToast(message, type = 'info', icon = 'ℹ️', duration = 5000) {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `<span class="toast-icon">${icon}</span><span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('removing');
        setTimeout(() => toast.remove(), 400);
    }, duration);
}

// ============================================================
// CRITICAL FLASH EFFECT
// ============================================================
function triggerCriticalFlash() {
    const flash = document.getElementById('critical-flash');
    flash.classList.add('active');
    setTimeout(() => flash.classList.remove('active'), 600);
}

// ============================================================
// WEBSOCKET CONNECTION
// ============================================================
function connectWebSocket() {
    try {
        ws = new WebSocket(WS_URL);

        ws.onopen = () => {
            console.log('WebSocket connected');
            reconnectDelay = 1000;
            updateConnectionStatus(true);
            showToast('Connected to live data stream', 'safe', '🟢', 3000);

            setInterval(() => {
                if (ws && ws.readyState === WebSocket.OPEN) {
                    ws.send('ping');
                }
            }, 30000);
        };

        ws.onmessage = (event) => {
            try {
                if (event.data === 'pong') return;
                const data = JSON.parse(event.data);

                // Check if this is a trigger event (not a sensor reading)
                if (data._trigger_event) {
                    handleTriggerEvent(data);
                    return;
                }

                handleDataUpdate(data);
            } catch (e) {
                console.error('Failed to parse WebSocket message:', e);
            }
        };

        ws.onclose = () => {
            console.log('WebSocket disconnected');
            updateConnectionStatus(false);
            scheduleReconnect();
        };

        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            updateConnectionStatus(false);
        };
    } catch (e) {
        console.error('WebSocket connection failed:', e);
        updateConnectionStatus(false);
        scheduleReconnect();
    }
}

function scheduleReconnect() {
    console.log(`Reconnecting in ${reconnectDelay / 1000}s...`);
    setTimeout(() => {
        reconnectDelay = Math.min(reconnectDelay * 2, maxReconnectDelay);
        connectWebSocket();
    }, reconnectDelay);
}

function updateConnectionStatus(online) {
    const badge = document.getElementById('connection-status');
    const text = document.getElementById('connection-text');
    if (online) {
        badge.className = 'connection-badge online';
        text.textContent = 'LIVE';
    } else {
        badge.className = 'connection-badge offline';
        text.textContent = 'OFFLINE';
    }
}

// ============================================================
// DATA FETCHING
// ============================================================
async function fetchInitialData() {
    try {
        const response = await fetch(`${API_BASE}/api/readings?limit=${MAX_CHART_POINTS}`);
        if (!response.ok) return;
        const readings = await response.json();

        if (readings && readings.length > 0) {
            readings.forEach(r => {
                addChartPoint(r.timestamp, r.temp_internal, r.humidity, r.risk_score, r.vvm_damage);
            });
            chartInstance.update('none');

            const latest = readings[readings.length - 1];
            handleDataUpdate(latest);

            readings.slice(-MAX_TABLE_ROWS).forEach(r => {
                addTableRow(r);
            });
        }
    } catch (e) {
        console.error('Failed to fetch initial data:', e);
    }
}

async function fetchReport() {
    try {
        const response = await fetch(`${API_BASE}/api/report/latest`);
        if (!response.ok) return;
        const data = await response.json();

        const reportEl = document.getElementById('report-content');
        if (data.report) {
            reportEl.innerHTML = '';
            reportEl.textContent = data.report;
        }
    } catch (e) {
        console.error('Failed to fetch report:', e);
    }
}

async function fetchHealthStatus() {
    try {
        const response = await fetch(`${API_BASE}/health`);
        if (!response.ok) return;
        const data = await response.json();

        const modeText = document.getElementById('mode-text');
        const dataSourceText = document.getElementById('data-source-text');
        const isLive = data.mode !== 'simulation';
        modeText.textContent = isLive ? 'LIVE' : 'SIMULATION';
        dataSourceText.textContent = isLive ? 'Data Source: Live Sensor' : 'Data Source: Simulation';
    } catch (e) {
        console.error('Failed to fetch health status:', e);
    }
}

// ============================================================
// TRIGGER EVENT HANDLING (WebSocket)
// ============================================================
function handleTriggerEvent(data) {
    console.log('Trigger event received:', data);

    const fromStatus = data.from || '?';
    const toStatus = data.to || '?';

    // Show status change toast
    showToast(
        `🚨 Status changed: ${fromStatus} → ${toStatus}`,
        toStatus === 'CRITICAL' ? 'critical' : (toStatus === 'WARNING' ? 'warning' : 'safe'),
        toStatus === 'CRITICAL' ? '🚨' : (toStatus === 'WARNING' ? '⚠️' : '✅'),
        6000
    );

    // Show SMS result toast
    if (data.sms_sent) {
        showToast('📱 SMS alert delivered to your phone!', 'safe', '📱', 5000);
    } else {
        showToast('📱 SMS alert logged (check server logs)', 'info', '📱', 4000);
    }

    // Show PDF result toast, enable download button, and auto-download
    if (data.pdf_generated) {
        showToast('📄 PDF incident report generated — downloading...', 'safe', '📄', 5000);
        showDownloadButton();

        // Auto-download the PDF (visible browser download)
        setTimeout(() => {
            autoDownloadPdf();
        }, 1500);
    }

    // Refresh the incident report text
    setTimeout(fetchReport, 1000);
}

function autoDownloadPdf() {
    // Create a temporary link to trigger browser download
    const link = document.createElement('a');
    link.href = `${API_BASE}/api/pdf/latest/download`;
    link.download = '';  // Triggers download instead of navigation
    link.style.display = 'none';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('⬇️ PDF report download started!', 'safe', '⬇️', 3000);
}

function showDownloadButton() {
    const btn = document.getElementById('download-pdf-btn');
    if (btn) {
        btn.style.display = 'inline-flex';
        btn.classList.add('pulse');
        // Remove pulse after animation completes
        setTimeout(() => btn.classList.remove('pulse'), 6000);
    }
}

async function checkPdfStatus() {
    try {
        const response = await fetch(`${API_BASE}/api/pdf/latest/status`);
        if (!response.ok) return;
        const data = await response.json();

        if (data.available) {
            showDownloadButton();
        }
    } catch (e) {
        console.error('Failed to check PDF status:', e);
    }
}

// ============================================================
// DATA HANDLING
// ============================================================
function handleDataUpdate(data) {
    updateTemperature(data);
    updateRiskGauge(data);
    updateStatusHero(data);
    updateVVM(data);
    updateETA(data);
    updateHumidity(data);
    addChartPoint(data.timestamp, data.temp_internal, data.humidity, data.risk_score, data.vvm_damage);
    addTableRow(data);

    // Status change detection → toast + flash
    if (previousStatus && previousStatus !== data.status) {
        if (data.status === 'CRITICAL') {
            showToast('⚠️ Status changed to CRITICAL — Immediate action required!', 'critical', '🚨', 8000);
            triggerCriticalFlash();
        } else if (data.status === 'WARNING') {
            showToast('Status changed to WARNING — Monitor closely', 'warning', '⚠️', 6000);
        } else if (data.status === 'SAFE') {
            showToast('Status restored to SAFE — All parameters normal', 'safe', '✅', 4000);
        }
    }
    previousStatus = data.status;

    // Fetch updated report on status change
    if (data.status === 'WARNING' || data.status === 'CRITICAL') {
        setTimeout(fetchReport, 2000);
    }
}

// ============================================================
// ANIMATED NUMBER UPDATE
// ============================================================
function animateValue(element, start, end, duration = 600, decimals = 1, suffix = '') {
    const startTime = performance.now();
    const diff = end - start;

    function step(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        // easeOutCubic
        const ease = 1 - Math.pow(1 - progress, 3);
        const current = start + diff * ease;
        element.textContent = current.toFixed(decimals) + suffix;
        if (progress < 1) {
            requestAnimationFrame(step);
        }
    }
    requestAnimationFrame(step);
}

// ============================================================
// UI UPDATE FUNCTIONS
// ============================================================
function updateTemperature(data) {
    const tempValue = document.getElementById('temp-value');
    const tempExt = document.getElementById('temp-ext');
    const tempCard = document.getElementById('temp-card');
    const anomalyBadge = document.getElementById('anomaly-badge');

    // Animated number
    const oldVal = parseFloat(tempValue.textContent) || 0;
    const newVal = data.temp_internal;
    if (oldVal !== newVal && !isNaN(oldVal)) {
        animateValue(tempValue, oldVal, newVal, 500, 1);
    } else {
        tempValue.textContent = newVal.toFixed(1);
    }

    tempExt.textContent = `Ext: ${data.temp_external.toFixed(1)}°C`;

    tempCard.classList.remove('warning', 'critical', 'anomaly');
    if (data.status === 'CRITICAL') {
        tempCard.classList.add('critical');
    } else if (data.status === 'WARNING') {
        tempCard.classList.add('warning');
    }

    if (data.is_anomaly) {
        tempCard.classList.add('anomaly');
        anomalyBadge.style.display = 'block';
    } else {
        anomalyBadge.style.display = 'none';
    }
}

function updateRiskGauge(data) {
    const score = Math.min(100, Math.max(0, data.risk_score));
    const gaugeText = document.getElementById('risk-gauge-text');
    const gaugeFill = document.getElementById('gauge-fill');

    gaugeText.textContent = Math.round(score);

    const arcLength = (score / 100) * 142;
    gaugeFill.setAttribute('stroke-dasharray', `${arcLength} 142`);

    if (score < 30) {
        gaugeText.style.fill = '#22C55E';
        gaugeFill.style.stroke = '#22C55E';
    } else if (score < 70) {
        gaugeText.style.fill = '#F5C518';
        gaugeFill.style.stroke = '#F5C518';
    } else {
        gaugeText.style.fill = '#EF4444';
        gaugeFill.style.stroke = '#EF4444';
    }
}

function updateStatusHero(data) {
    const badge = document.getElementById('status-badge');
    const text = document.getElementById('status-text');
    const hero = document.getElementById('status-card');
    const heroIcon = document.getElementById('status-hero-icon');
    const heroSub = document.getElementById('status-hero-sub');

    text.textContent = data.status;
    badge.className = 'status-badge-large ' + data.status.toLowerCase();
    hero.classList.remove('safe-glow', 'warning-glow', 'critical-glow');

    if (data.status === 'SAFE') {
        hero.classList.add('safe-glow');
        heroIcon.textContent = '🛡️';
        heroSub.textContent = 'All parameters within safe range';
    } else if (data.status === 'WARNING') {
        hero.classList.add('warning-glow');
        heroIcon.textContent = '⚠️';
        heroSub.textContent = 'Temperature excursion detected — monitoring closely';
    } else {
        hero.classList.add('critical-glow');
        heroIcon.textContent = '🚨';
        heroSub.textContent = 'IMMEDIATE ACTION REQUIRED — Isolate affected batches';
    }

    // Also update the old status badge function for compatibility
    updateStatusBadge(data);
}

// Keep for backward compatibility
function updateStatusBadge(data) {
    // Already handled in updateStatusHero
}

function updateVVM(data) {
    const fill = document.getElementById('vvm-fill');
    const damageText = document.getElementById('vvm-damage-text');
    const potencyText = document.getElementById('potency-text');

    const damagePercent = Math.min(100, data.vvm_damage * 100);
    fill.style.width = `${damagePercent}%`;

    damageText.textContent = `VVM: ${data.vvm_damage.toFixed(6)}`;

    const potency = data.potency_percent;
    potencyText.textContent = `${potency.toFixed(1)}%`;

    if (potency > 80) {
        potencyText.style.color = '#22C55E';
    } else if (potency > 50) {
        potencyText.style.color = '#F59E0B';
    } else {
        potencyText.style.color = '#EF4444';
    }
}

function updateETA(data) {
    const etaValue = document.getElementById('eta-value');
    const etaUnit = document.getElementById('eta-unit');
    const etaSub = document.getElementById('eta-sub');
    const etaCard = document.getElementById('eta-card');
    const exposureDisplay = document.getElementById('exposure-display');

    etaCard.classList.remove('warning', 'critical');

    if (data.status === 'CRITICAL') {
        etaValue.textContent = '!!';
        etaUnit.textContent = '';
        etaSub.textContent = 'CRITICAL NOW';
        etaCard.classList.add('critical');
    } else if (data.eta_to_critical !== null && data.eta_to_critical !== undefined) {
        etaValue.textContent = data.eta_to_critical;
        etaUnit.textContent = 'min';
        etaSub.textContent = 'until CRITICAL status';
        etaCard.classList.add('warning');
    } else {
        etaValue.textContent = '--';
        etaUnit.textContent = 'min';
        etaSub.textContent = 'No risk detected';
    }

    exposureDisplay.textContent = `Exposure: ${data.exposure_minutes} min`;
}

function updateHumidity(data) {
    const humidityValue = document.getElementById('humidity-value');
    const humidityDisplay = document.getElementById('humidity-display');

    if (humidityValue) {
        const oldVal = parseFloat(humidityValue.textContent) || 0;
        const newVal = data.humidity;
        if (oldVal !== newVal && !isNaN(oldVal) && oldVal > 0) {
            animateValue(humidityValue, oldVal, newVal, 500, 1);
        } else {
            humidityValue.textContent = newVal.toFixed(1);
        }
    }
    // Keep hidden element for backward compat
    if (humidityDisplay) {
        humidityDisplay.textContent = `Humidity: ${data.humidity.toFixed(1)}%`;
    }
}


// ============================================================
// CHART STATE — 3 SEPARATE CHARTS
// ============================================================
let chartInstance    = null;   // Chart 1: Temperature Trace
let humidityChart    = null;   // Chart 2: Humidity bar
let riskDmgChart     = null;   // Chart 3: Risk vs VVM Damage

let chartLabels      = [];
let chartTempData    = [];
let chartSafeMaxData = [];
let chartSafeMinData = [];
let chartHumidData   = [];
let chartRiskData    = [];
let chartDmgData     = [];

const SHARED_SCALES_X = {
    display: true,
    grid: { color: 'rgba(245,197,24,0.04)', drawBorder: false },
    ticks: { color: '#555', font: { family: 'Rajdhani', size: 10 }, maxRotation: 0, maxTicksLimit: 6 },
};
const SHARED_TOOLTIP = {
    backgroundColor: '#111',
    titleColor: '#F0F0F0',
    bodyColor: '#888',
    borderColor: 'rgba(245,197,24,0.3)',
    borderWidth: 1,
    padding: 10,
    cornerRadius: 6,
};
const SHARED_LEGEND = {
    display: true,
    position: 'top',
    labels: { color: '#888', font: { family: 'Inter', size: 10 }, usePointStyle: true, pointStyle: 'line', padding: 14 },
};

// ── CHART 1: Stepped temperature line + safe-zone boundaries ──
function initChart() {
    const ctx = document.getElementById('temp-chart').getContext('2d');
    chartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: 'Internal Temp',
                    data: chartTempData,
                    borderColor: '#F5C518',
                    backgroundColor: 'rgba(245,197,24,0.07)',
                    borderWidth: 2,
                    stepped: 'before',
                    fill: true,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    pointHoverBackgroundColor: '#F5C518',
                    pointHoverBorderColor: '#000',
                },
                {
                    label: 'Safe Max (8°C)',
                    data: chartSafeMaxData,
                    borderColor: 'rgba(239,68,68,0.5)',
                    borderWidth: 1.5,
                    borderDash: [5, 4],
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                },
                {
                    label: 'Safe Min (2°C)',
                    data: chartSafeMinData,
                    borderColor: 'rgba(245,197,24,0.22)',
                    borderWidth: 1.5,
                    borderDash: [5, 4],
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 350 },
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: SHARED_LEGEND, tooltip: SHARED_TOOLTIP },
            scales: {
                x: SHARED_SCALES_X,
                y: {
                    display: true,
                    grid: { color: 'rgba(245,197,24,0.04)', drawBorder: false },
                    ticks: { color: '#555', font: { family: 'Rajdhani', size: 11 }, callback: v => v + '°C' },
                    suggestedMin: 0,
                    suggestedMax: 20,
                },
            },
        },
    });
}

// ── CHART 2: Humidity bar chart with threshold line ──
function initHumidityChart() {
    const ctx = document.getElementById('humidity-chart').getContext('2d');
    humidityChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: 'Humidity (%)',
                    data: chartHumidData,
                    backgroundColor: chartHumidData.map(v =>
                        v > 70 ? 'rgba(239,68,68,0.72)' :
                        v > 60 ? 'rgba(245,197,24,0.65)' :
                                 'rgba(245,197,24,0.32)'
                    ),
                    borderColor: 'transparent',
                    borderRadius: 3,
                    categoryPercentage: 0.85,
                    barPercentage: 0.9,
                },
                {
                    label: 'Safe Max (60%)',
                    data: chartLabels.map(() => 60),
                    type: 'line',
                    borderColor: 'rgba(239,68,68,0.4)',
                    borderWidth: 1.5,
                    borderDash: [5, 4],
                    fill: false,
                    pointRadius: 0,
                    pointHoverRadius: 0,
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 350 },
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: SHARED_LEGEND, tooltip: SHARED_TOOLTIP },
            scales: {
                x: SHARED_SCALES_X,
                y: {
                    display: true,
                    grid: { color: 'rgba(245,197,24,0.04)', drawBorder: false },
                    ticks: { color: '#555', font: { family: 'Rajdhani', size: 11 }, callback: v => v + '%' },
                    min: 0,
                    max: 100,
                },
            },
        },
    });
}

// ── CHART 3: Dual-axis Risk (left) vs VVM Damage ×1000 (right) ──
function initRiskDmgChart() {
    const ctx = document.getElementById('risk-damage-chart').getContext('2d');
    riskDmgChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: chartLabels,
            datasets: [
                {
                    label: 'Risk Score',
                    data: chartRiskData,
                    borderColor: '#EF4444',
                    backgroundColor: 'rgba(239,68,68,0.08)',
                    borderWidth: 2,
                    fill: true,
                    tension: 0.35,
                    pointRadius: 0,
                    pointHoverRadius: 5,
                    yAxisID: 'yRisk',
                },
                {
                    label: 'VVM Dmg ×1k',
                    data: chartDmgData,
                    borderColor: '#F5C518',
                    backgroundColor: 'rgba(245,197,24,0.05)',
                    borderWidth: 1.5,
                    fill: false,
                    tension: 0.5,
                    borderDash: [4, 3],
                    pointRadius: 2,
                    pointBackgroundColor: '#F5C518',
                    pointHoverRadius: 5,
                    yAxisID: 'yDmg',
                },
            ],
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: { duration: 350 },
            interaction: { mode: 'index', intersect: false },
            plugins: { legend: SHARED_LEGEND, tooltip: SHARED_TOOLTIP },
            scales: {
                x: SHARED_SCALES_X,
                yRisk: {
                    type: 'linear',
                    position: 'left',
                    grid: { color: 'rgba(239,68,68,0.06)', drawBorder: false },
                    ticks: { color: '#EF4444', font: { family: 'Rajdhani', size: 10 } },
                    title: { display: true, text: 'RISK', color: '#EF4444', font: { size: 9, family: 'Rajdhani', weight: '700' } },
                    min: 0, max: 100,
                },
                yDmg: {
                    type: 'linear',
                    position: 'right',
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#F5C518', font: { family: 'Rajdhani', size: 10 }, callback: v => v.toFixed(1) },
                    title: { display: true, text: 'DMG ×1k', color: '#F5C518', font: { size: 9, family: 'Rajdhani', weight: '700' } },
                },
            },
        },
    });
}

// ── Push new point into all 3 charts simultaneously ──
function addChartPoint(timestamp, temp, humidity, risk, dmg) {
    const label = formatTime(timestamp);

    chartLabels.push(label);
    chartTempData.push(temp);
    chartSafeMaxData.push(8);
    chartSafeMinData.push(2);
    chartHumidData.push(humidity != null ? +humidity.toFixed(1) : null);
    chartRiskData.push(risk != null ? +risk.toFixed(1) : null);
    chartDmgData.push(dmg != null ? +(dmg * 1000).toFixed(4) : null);

    if (chartLabels.length > MAX_CHART_POINTS) {
        chartLabels.shift();
        chartTempData.shift();
        chartSafeMaxData.shift();
        chartSafeMinData.shift();
        chartHumidData.shift();
        chartRiskData.shift();
        chartDmgData.shift();
    }

    // Refresh humidity bar colours dynamically
    if (humidityChart) {
        humidityChart.data.datasets[0].backgroundColor = chartHumidData.map(v =>
            v > 70 ? 'rgba(239,68,68,0.72)' :
            v > 60 ? 'rgba(245,197,24,0.65)' :
                     'rgba(245,197,24,0.32)'
        );
        humidityChart.data.datasets[1].data = chartLabels.map(() => 60);
        humidityChart.update('none');
    }
    if (chartInstance) chartInstance.update('none');
    if (riskDmgChart)  riskDmgChart.update('none');
}



function formatTime(timestamp) {
    try {
        const date = new Date(timestamp);
        return date.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: false,
        });
    } catch {
        return timestamp.substring(11, 19);
    }
}

// ============================================================
// TABLE
// ============================================================
function addTableRow(data) {
    const tbody = document.getElementById('readings-tbody');

    const emptyRow = tbody.querySelector('.empty-table');
    if (emptyRow) {
        emptyRow.parentElement.remove();
    }

    const row = document.createElement('tr');
    row.className = `row-${data.status.toLowerCase()}`;

    const statusClass = data.status.toLowerCase();
    const anomalyHtml = data.is_anomaly
        ? '<span class="anomaly-dot" title="Anomaly detected"></span>'
        : '<span class="anomaly-none">—</span>';

    row.innerHTML = `
        <td>${formatTime(data.timestamp)}</td>
        <td>${data.temp_internal.toFixed(1)}</td>
        <td>${data.temp_external.toFixed(1)}</td>
        <td>${data.humidity.toFixed(1)}</td>
        <td>${data.risk_score.toFixed(1)}</td>
        <td><span class="status-pill ${statusClass}">${data.status}</span></td>
        <td>${data.vvm_damage.toFixed(4)}</td>
        <td>${anomalyHtml}</td>
    `;

    tbody.insertBefore(row, tbody.firstChild);

    while (tbody.children.length > MAX_TABLE_ROWS) {
        tbody.removeChild(tbody.lastChild);
    }

    // Entrance animation
    row.style.opacity = '0';
    row.style.transform = 'translateY(-10px)';
    requestAnimationFrame(() => {
        row.style.transition = 'all 0.3s ease';
        row.style.opacity = '1';
        row.style.transform = 'translateY(0)';
    });
}

// ============================================================
// SEHAT SAATHI — MULTILINGUAL CHATBOT
// ============================================================
(function initChatbot() {
    const toggle = document.getElementById('chatbot-toggle');
    const panel = document.getElementById('chatbot-panel');
    const closeBtn = document.getElementById('chatbot-close');
    const input = document.getElementById('chatbot-input');
    const sendBtn = document.getElementById('chatbot-send');
    const messages = document.getElementById('chatbot-messages');
    const suggestions = document.getElementById('chatbot-suggestions');
    const toggleIcon = document.getElementById('chatbot-toggle-icon');
    const langSelect = document.getElementById('language-select');
    const subtitle = document.getElementById('chatbot-subtitle');
    const welcomeBubble = document.getElementById('chatbot-welcome');

    let isOpen = false;
    let currentLang = 'en';

    // ── Multilingual Suggestions ──
    const suggestionsMap = {
        en: [
            { icon: '🛡️', label: 'Is it safe?', query: 'Is the vaccine safe?' },
            { icon: '🌡️', label: 'Temperature', query: 'Current temperature' },
            { icon: '📊', label: 'Risk analysis', query: 'Why is risk high?' },
            { icon: '⏱️', label: 'ETA to critical', query: 'When will it become critical?' },
            { icon: '💉', label: 'Potency', query: 'Potency and VVM damage' },
            { icon: '🏗️', label: 'How it works', query: 'How does the system work?' },
            { icon: '🔌', label: 'Sensors', query: 'What sensors are used?' },
            { icon: '🧠', label: 'ML models', query: 'What ML models are used?' },
        ],
        hi: [
            { icon: '🛡️', label: 'सुरक्षित है?', query: 'क्या वैक्सीन सुरक्षित है?' },
            { icon: '🌡️', label: 'तापमान', query: 'वर्तमान तापमान क्या है?' },
            { icon: '📊', label: 'जोखिम', query: 'जोखिम क्यों बढ़ा है?' },
            { icon: '⏱️', label: 'कब गंभीर?', query: 'कब गंभीर होगा?' },
            { icon: '💉', label: 'क्षमता', query: 'वैक्सीन क्षमता और VVM' },
            { icon: '🏗️', label: 'कैसे काम करता है', query: 'सिस्टम कैसे काम करता है?' },
            { icon: '🔌', label: 'सेंसर', query: 'कौन से सेंसर हैं?' },
            { icon: '🧠', label: 'ML मॉडल', query: 'कौन से ML मॉडल हैं?' },
        ],
        kn: [
            { icon: '🛡️', label: 'ಸುರಕ್ಷಿತವೇ?', query: 'ಲಸಿಕೆ ಸುರಕ್ಷಿತವೇ?' },
            { icon: '🌡️', label: 'ತಾಪಮಾನ', query: 'ಪ್ರಸ್ತುತ ತಾಪಮಾನ ಏನು?' },
            { icon: '📊', label: 'ಅಪಾಯ', query: 'ಅಪಾಯ ಏಕೆ ಹೆಚ್ಚಾಗಿದೆ?' },
            { icon: '⏱️', label: 'ಯಾವಾಗ ಗಂಭೀರ?', query: 'ಯಾವಾಗ ಗಂಭೀರವಾಗುತ್ತದೆ?' },
            { icon: '💉', label: 'ಸಾಮರ್ಥ್ಯ', query: 'ಲಸಿಕೆ ಸಾಮರ್ಥ್ಯ ಮತ್ತು VVM' },
            { icon: '🏗️', label: 'ಹೇಗೆ ಕೆಲಸ', query: 'ವ್ಯವಸ್ಥೆ ಹೇಗೆ ಕೆಲಸ ಮಾಡುತ್ತದೆ?' },
            { icon: '🔌', label: 'ಸೆನ್ಸರ್', query: 'ಯಾವ ಸೆನ್ಸರ್‌ಗಳನ್ನು ಬಳಸಲಾಗಿದೆ?' },
            { icon: '🧠', label: 'ML ಮಾಡೆಲ್', query: 'ಯಾವ ML ಮಾಡೆಲ್‌ಗಳನ್ನು ಬಳಸಲಾಗಿದೆ?' },
        ],
    };

    const uiStrings = {
        en: { subtitle: 'Online • Ask me anything', placeholder: 'Ask about temperature, safety, system...',
              welcome: '👋 Hi! I\'m <strong>Sehat Saathi</strong> — your Vaccine Monitor Assistant.<br><br>Ask anything or click a suggestion!' },
        hi: { subtitle: 'ऑनलाइन • कुछ भी पूछें', placeholder: 'तापमान, सुरक्षा, सिस्टम के बारे में पूछें...',
              welcome: '👋 नमस्ते! मैं <strong>सेहत साथी</strong> हूँ — आपका वैक्सीन मॉनिटर सहायक।<br><br>कोई भी सवाल पूछें या सुझाव पर क्लिक करें!' },
        kn: { subtitle: 'ಆನ್‌ಲೈನ್ • ಏನಾದರೂ ಕೇಳಿ', placeholder: 'ತಾಪಮಾನ, ಸುರಕ್ಷತೆ, ವ್ಯವಸ್ಥೆ ಬಗ್ಗೆ ಕೇಳಿ...',
              welcome: '👋 ನಮಸ್ಕಾರ! ನಾನು <strong>ಸೆಹತ್ ಸಾಥಿ</strong> — ನಿಮ್ಮ ಲಸಿಕೆ ಮಾನಿಟರ್ ಸಹಾಯಕ.<br><br>ಏನಾದರೂ ಕೇಳಿ ಅಥವಾ ಸಲಹೆಯ ಮೇಲೆ ಕ್ಲಿಕ್ ಮಾಡಿ!' },
    };

    function renderSuggestions() {
        const items = suggestionsMap[currentLang] || suggestionsMap.en;
        suggestions.innerHTML = items.map(s =>
            `<button class="suggestion-btn" data-query="${s.query}">${s.icon} ${s.label}</button>`
        ).join('');
    }

    function updateUILanguage() {
        const strings = uiStrings[currentLang] || uiStrings.en;
        subtitle.textContent = strings.subtitle;
        input.placeholder = strings.placeholder;
        welcomeBubble.innerHTML = strings.welcome;
        renderSuggestions();
    }

    renderSuggestions();

    langSelect.addEventListener('change', () => {
        currentLang = langSelect.value;
        updateUILanguage();
    });

    toggle.addEventListener('click', () => {
        isOpen = !isOpen;
        panel.classList.toggle('open', isOpen);
        toggle.classList.toggle('active', isOpen);
        toggleIcon.textContent = isOpen ? '✕' : '💬';
        if (isOpen) {
            setTimeout(() => input.focus(), 300);
        }
    });

    closeBtn.addEventListener('click', () => {
        isOpen = false;
        panel.classList.remove('open');
        toggle.classList.remove('active');
        toggleIcon.textContent = '💬';
    });

    function sendMessage(text) {
        if (!text.trim()) return;

        appendMessage(text, 'user');
        input.value = '';

        const typingEl = showTyping();

        fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ query: text, language: currentLang }),
        })
        .then(res => res.json())
        .then(data => {
            removeTyping(typingEl);
            appendMessage(data.response || data.reply, 'bot');
        })
        .catch(err => {
            removeTyping(typingEl);
            const errMsg = {
                en: '❌ Failed to get response. Is the backend running?',
                hi: '❌ प्रतिक्रिया प्राप्त करने में विफल। क्या बैकएंड चल रहा है?',
                kn: '❌ ಪ್ರತಿಕ್ರಿಯೆ ಪಡೆಯಲು ವಿಫಲವಾಗಿದೆ. ಬ್ಯಾಕೆಂಡ್ ಚಾಲನೆಯಲ್ಲಿದೆಯೇ?',
            };
            appendMessage(errMsg[currentLang] || errMsg.en, 'bot');
            console.error('Chat error:', err);
        });
    }

    function appendMessage(text, sender) {
        const wrapper = document.createElement('div');
        wrapper.className = `chat-msg ${sender}`;

        const bubble = document.createElement('div');
        bubble.className = `chat-bubble ${sender}`;
        bubble.innerHTML = formatBotText(text);

        wrapper.appendChild(bubble);
        messages.appendChild(wrapper);

        wrapper.style.opacity = '0';
        wrapper.style.transform = sender === 'user' ? 'translateX(20px)' : 'translateX(-20px)';
        requestAnimationFrame(() => {
            wrapper.style.transition = 'all 0.3s ease';
            wrapper.style.opacity = '1';
            wrapper.style.transform = 'translateX(0)';
        });

        messages.scrollTop = messages.scrollHeight;
    }

    function formatBotText(text) {
        return text
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\n/g, '<br>');
    }

    function showTyping() {
        const wrapper = document.createElement('div');
        wrapper.className = 'chat-msg bot typing-wrapper';
        wrapper.innerHTML = `
            <div class="chat-bubble bot typing">
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
                <span class="typing-dot"></span>
            </div>
        `;
        messages.appendChild(wrapper);
        messages.scrollTop = messages.scrollHeight;
        return wrapper;
    }

    function removeTyping(el) {
        if (el && el.parentNode) el.parentNode.removeChild(el);
    }

    sendBtn.addEventListener('click', () => sendMessage(input.value));

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            sendMessage(input.value);
        }
    });

    suggestions.addEventListener('click', (e) => {
        const btn = e.target.closest('.suggestion-btn');
        if (btn) sendMessage(btn.getAttribute('data-query'));
    });
})();
