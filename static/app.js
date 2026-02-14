/**
 * Yale Doorman L3S BLE Monitor – Dashboard Frontend
 *
 * Connects to the backend via Server-Sent Events (SSE) for live updates.
 */

(function () {
    'use strict';

    const MAX_TIMELINE_EVENTS = 100;

    // DOM Elements
    const els = {
        connectionStatus: document.getElementById('connectionStatus'),
        lockCard: document.getElementById('lockCard'),
        lockState: document.getElementById('lockState'),
        doorCard: document.getElementById('doorCard'),
        doorState: document.getElementById('doorState'),
        batteryCard: document.getElementById('batteryCard'),
        batteryLevel: document.getElementById('batteryLevel'),
        batteryFill: document.getElementById('batteryFill'),
        doorbellCard: document.getElementById('doorbellCard'),
        doorbellState: document.getElementById('doorbellState'),
        rssiValue: document.getElementById('rssiValue'),
        autoLockValue: document.getElementById('autoLockValue'),
        pollMode: document.getElementById('pollMode'),
        lastUpdated: document.getElementById('lastUpdated'),
        timeline: document.getElementById('timeline'),
        footerModel: document.getElementById('footerModel'),
    };

    let eventSource = null;
    let reconnectTimer = null;

    // ── State Rendering ──

    function capitalize(str) {
        if (!str) return '';
        return str.charAt(0).toUpperCase() + str.slice(1);
    }

    function formatTime(isoStr) {
        if (!isoStr) return '–';
        try {
            const d = new Date(isoStr);
            if (isNaN(d.getTime())) return '–';
            return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch {
            return '–';
        }
    }

    function relativeTime(isoStr) {
        if (!isoStr) return '';
        try {
            const d = new Date(isoStr);
            const diff = (Date.now() - d.getTime()) / 1000;
            if (diff < 60) return 'just now';
            if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
            if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
            return Math.floor(diff / 86400) + 'd ago';
        } catch {
            return '';
        }
    }

    function flashCard(card) {
        card.classList.remove('flash');
        void card.offsetWidth; // trigger reflow
        card.classList.add('flash');
    }

    function updateState(state) {
        if (!state) return;

        // Lock state
        const lockState = state.lock_state || 'unknown';
        els.lockState.textContent = capitalize(lockState);
        els.lockCard.dataset.state = lockState;

        // Door state
        const doorState = state.door_state || 'unknown';
        els.doorState.textContent = capitalize(doorState);
        els.doorCard.dataset.state = doorState;

        // Battery
        const battery = state.battery_level;
        if (battery !== null && battery !== undefined) {
            els.batteryLevel.textContent = battery + '%';
            // Battery fill bar (max width ~14 for the SVG rect)
            const fillWidth = Math.max(0, Math.min(14, (battery / 100) * 14));
            els.batteryFill.setAttribute('width', String(fillWidth));
            if (battery > 50) {
                els.batteryCard.dataset.state = 'battery-good';
            } else if (battery > 20) {
                els.batteryCard.dataset.state = 'battery-medium';
            } else {
                els.batteryCard.dataset.state = 'battery-low';
            }
        } else {
            els.batteryLevel.textContent = '–%';
            els.batteryCard.dataset.state = 'unknown';
        }

        // Doorbell
        const doorbell = state.doorbell_ringing;
        els.doorbellState.textContent = doorbell ? 'Ringing!' : 'Idle';
        els.doorbellCard.dataset.state = doorbell ? 'ringing' : 'idle';

        // Info row
        els.rssiValue.textContent = state.rssi !== null && state.rssi !== undefined
            ? state.rssi + ' dBm' : '– dBm';
        els.autoLockValue.textContent = state.auto_lock_enabled
            ? state.auto_lock_duration + 's' : 'Off';
        els.lastUpdated.textContent = formatTime(state.last_updated);

        // Connection
        updateConnectionStatus(state.connected);

        // Footer
        if (state.lock_model) {
            els.footerModel.textContent = state.lock_model;
        }
    }

    function updateConnectionStatus(connected) {
        const el = els.connectionStatus;
        if (connected) {
            el.className = 'connection-status connected';
            el.querySelector('.status-text').textContent = 'Connected';
        } else {
            el.className = 'connection-status disconnected';
            el.querySelector('.status-text').textContent = 'Disconnected';
        }
    }

    function updatePollMode(scheduler) {
        if (!scheduler) return;
        const mode = scheduler.mode || 'unknown';
        const interval = scheduler.next_interval_sec;
        els.pollMode.textContent = capitalize(mode) + (interval ? ` (${interval}s)` : '');
    }

    // ── Event Timeline ──

    function eventTypeLabel(type) {
        const labels = {
            lock_state: 'Lock',
            door_state: 'Door',
            battery: 'Battery',
            doorbell: 'Doorbell',
            connection: 'Connection',
        };
        return labels[type] || type;
    }

    function createTimelineEvent(event, isNew) {
        const div = document.createElement('div');
        div.className = 'timeline-event' + (isNew ? ' new' : '');

        const dot = document.createElement('span');
        dot.className = 'event-dot ' + (event.event_type || '');

        const content = document.createElement('div');
        content.className = 'event-content';

        const text = document.createElement('div');
        text.className = 'event-text';
        text.textContent = eventTypeLabel(event.event_type) + ': ' +
            capitalize(event.old_value) + ' → ' + capitalize(event.new_value);

        const detail = document.createElement('div');
        detail.className = 'event-detail';
        detail.textContent = 'via ' + (event.source || 'unknown');

        content.appendChild(text);
        content.appendChild(detail);

        const time = document.createElement('span');
        time.className = 'event-time';
        time.textContent = formatTime(event.timestamp);

        div.appendChild(dot);
        div.appendChild(content);
        div.appendChild(time);

        return div;
    }

    function addTimelineEvent(event) {
        // Remove empty message
        const empty = els.timeline.querySelector('.timeline-empty');
        if (empty) empty.remove();

        const el = createTimelineEvent(event, true);
        els.timeline.insertBefore(el, els.timeline.firstChild);

        // Trim excess events
        while (els.timeline.children.length > MAX_TIMELINE_EVENTS) {
            els.timeline.removeChild(els.timeline.lastChild);
        }
    }

    function renderInitialEvents(events) {
        els.timeline.innerHTML = '';
        if (!events || events.length === 0) {
            els.timeline.innerHTML = '<div class="timeline-empty">No events yet</div>';
            return;
        }
        // Reverse so newest is first
        const sorted = [...events].reverse();
        for (const event of sorted) {
            const el = createTimelineEvent(event, false);
            els.timeline.appendChild(el);
        }
    }

    // ── SSE Connection ──

    function connectSSE() {
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource('/api/events/stream');

        eventSource.onopen = () => {
            console.log('SSE connected');
            els.connectionStatus.className = 'connection-status connected';
            els.connectionStatus.querySelector('.status-text').textContent = 'Stream Active';
        };

        eventSource.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);

                if (data.type === 'initial_state') {
                    updateState(data.state);
                    renderInitialEvents(data.events);
                    // Fetch scheduler status
                    fetchDiagnostics();
                } else if (data.type === 'state_update') {
                    updateState(data.state);
                    if (data.event) {
                        addTimelineEvent(data.event);
                        // Flash the relevant card
                        const type = data.event.event_type;
                        if (type === 'lock_state') flashCard(els.lockCard);
                        if (type === 'door_state') flashCard(els.doorCard);
                        if (type === 'battery') flashCard(els.batteryCard);
                        if (type === 'doorbell') flashCard(els.doorbellCard);
                    }
                    fetchDiagnostics();
                }
            } catch (err) {
                console.error('SSE parse error:', err);
            }
        };

        eventSource.onerror = () => {
            console.warn('SSE connection lost, reconnecting...');
            els.connectionStatus.className = 'connection-status disconnected';
            els.connectionStatus.querySelector('.status-text').textContent = 'Reconnecting…';
            eventSource.close();
            eventSource = null;

            // Reconnect after delay
            if (reconnectTimer) clearTimeout(reconnectTimer);
            reconnectTimer = setTimeout(connectSSE, 3000);
        };
    }

    async function fetchDiagnostics() {
        try {
            const resp = await fetch('/api/diagnostics');
            const data = await resp.json();
            if (data.scheduler) {
                updatePollMode(data.scheduler);
            }
        } catch {
            // Ignore
        }
    }

    // ── Init ──

    connectSSE();

    // Periodically update relative times
    setInterval(() => {
        const timeEls = document.querySelectorAll('.event-time');
        // Relative time refresh handled by SSE pushes
    }, 60000);

})();
