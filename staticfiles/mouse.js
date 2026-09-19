let keyTimestamps = new Map();
let keyCleanupTimer = null;
const TIMER_DURATION = 3000; // 3 seconds match scoring window

function getActiveKeys() {
    const now = Date.now();
    for (const [k, exp] of keyTimestamps.entries()) {
        if (exp <= now) {
            keyTimestamps.delete(k);
        }
    }
    return Array.from(keyTimestamps.keys());
}

function scheduleKeyCleanup() {
    if (keyCleanupTimer) {
        clearTimeout(keyCleanupTimer);
        keyCleanupTimer = null;
    }

    const now = Date.now();
    let minRemaining = null;

    for (const exp of keyTimestamps.values()) {
        const rem = exp - now;
        if (rem > 0) {
            if (minRemaining === null || rem < minRemaining) {
                minRemaining = rem;
            }
        }
    }

    if (minRemaining !== null) {
        keyCleanupTimer = setTimeout(() => {
            const active = getActiveKeys();
            sendKeyState(active, true);
            if (active.length > 0) {
                scheduleKeyCleanup();
            } else {
                keyCleanupTimer = null;
            }
        }, Math.max(minRemaining, 10));
    }
}

function clearAllStickKeys() {
    keyTimestamps.clear();
    if (keyCleanupTimer) {
        clearTimeout(keyCleanupTimer);
        keyCleanupTimer = null;
    }
}
window.clearAllStickKeys = clearAllStickKeys;

function sendKeyState(keys, isDecay = false) {
    const aka_1 = ['a', 'g', 'n', 's'];
    const aka_2 = ['b', 'h', 'm', 't'];
    const aka_3 = ['c', 'i', 'o', 'u'];

    const ao_1 = ['d', 'j', 'p', 'v'];
    const ao_2 = ['e', 'k', 'q', 'w'];
    const ao_3 = ['f', 'l', 'r', 'x'];

    const count = (arr) => arr.filter(k => keys.includes(k)).length;

    const countAka1 = count(aka_1);
    const countAka2 = count(aka_2);
    const countAka3 = count(aka_3);

    const countAo1 = count(ao_1);
    const countAo2 = count(ao_2);
    const countAo3 = count(ao_3);

    let akaResult = "";
    let aoResult = "";

    if (countAka3 >= 2) akaResult = "Aka Ippon";
    else if (countAka2 >= 2) akaResult = "Aka Waza-ari";
    else if (countAka1 >= 2) akaResult = "Aka Yuko";
    else if ((countAka3 === 1 && countAka2 === 1 && countAka1 === 1) ||
             (countAka3 === 1 && countAka2 === 1) ||
             (countAka3 === 1 && countAka1 === 1))
        akaResult = "Aka Ippon";
    else if (countAka2 === 1 && countAka1 === 1)
        akaResult = "Aka Waza-ari";

    if (countAo3 >= 2) aoResult = "Ao Ippon";
    else if (countAo2 >= 2) aoResult = "Ao Waza-ari";
    else if (countAo1 >= 2) aoResult = "Ao Yuko";
    else if ((countAo3 === 1 && countAo2 === 1 && countAo1 === 1) ||
             (countAo3 === 1 && countAo2 === 1) ||
             (countAo3 === 1 && countAo1 === 1))
        aoResult = "Ao Ippon";
    else if (countAo2 === 1 && countAo1 === 1)
        aoResult = "Ao Waza-ari";

    const isHanteiActive = ($('#hantei').length ? $('#hantei').is(':checked') : false) || (typeof window.hantei === 'number' && window.hantei === 1);

    if (isHanteiActive) {
        const akaAll = ['a','b','c','g','h','i','m','n','o','s','t','u'];
        const aoAll = ['d','e','f','j','k','l','p','q','r','v','w','x'];
        const countAka = count(akaAll);
        const countAo = count(aoAll);
        if (countAka > countAo) {
            akaResult = `Hantei Aka (${countAka} - ${countAo})`;
        } else if (countAo > countAka) {
            aoResult = `Hantei Ao (${countAo} - ${countAka})`;
        } else if (countAka > 0 && countAka === countAo) {
            akaResult = `Hantei Seri (${countAka} - ${countAo})`;
        }
    }

    const curSec = typeof totalSeconds !== 'undefined' ? totalSeconds : 0;
    const curMs = typeof milliseconds !== 'undefined' ? milliseconds : 0;
    const payload = JSON.stringify([akaResult, aoResult, keys, curSec, curMs, isDecay]);

    // Direct local live monitor update if available on control panel
    if (typeof handleMouseStickSignal === 'function') {
        try {
            handleMouseStickSignal([akaResult, aoResult, keys, curSec, curMs, isDecay]);
        } catch(e) {}
    }

    // Safety: only broadcast mouse combinations when match timer is running, or during stick check, or during hantei
    const isTimerRunning = typeof isRunning !== 'undefined' ? isRunning : false;
    const isCheckMode = ($('#ms-check').length ? $('#ms-check').is(':checked') : false) || (typeof window.ms_check === 'number' && window.ms_check === 1);

    if (isTimerRunning || isCheckMode || isHanteiActive) {
        // High-speed WebSocket dispatch if control panel socket is open
        if (typeof window.sendControlAction === 'function') {
            window.sendControlAction('mouse', payload, 'all');
        } else {
            // Fallback HTTP AJAX dispatch
            const csrfToken = $('input[name=csrfmiddlewaretoken]').val() || (typeof csrftoken !== 'undefined' ? csrftoken : '');
            const targetTatamiPk = typeof tatamiPk !== 'undefined' ? tatamiPk : '';

            if (targetTatamiPk) {
                $.ajax({
                    url: `/scoring-board/${targetTatamiPk}/message-retriever`,
                    type: 'POST',
                    data: {
                        action: 'mouse',
                        details: payload,
                        csrfmiddlewaretoken: csrfToken
                    },
                });

                $.ajax({
                    url: `/admin-control/${targetTatamiPk}/message-retriever`,
                    type: 'POST',
                    data: {
                        action: 'mouse',
                        details: payload,
                        csrfmiddlewaretoken: csrfToken
                    },
                });
            }
        }
    }

    console.log(`[StickJuri] Sent state: [${keys.join(", ")}] -> AKA: "${akaResult}" AO: "${aoResult}" (decay: ${isDecay})`);
}

// Remove conflicting keys within each individual judge's controller
const conflictGroups = [
    { a: ['b', 'c', 'd', 'e', 'f'], b: ['a', 'c', 'd', 'e', 'f'], c: ['a', 'b', 'd', 'e', 'f'] },
    { d: ['a', 'b', 'c', 'e', 'f'], e: ['a', 'b', 'c', 'd', 'f'], f: ['a', 'b', 'c', 'd', 'e'] },
    { g: ['h', 'i', 'j', 'k', 'l'], h: ['g', 'i', 'j', 'k', 'l'], i: ['g', 'h', 'j', 'k', 'l'] },
    { j: ['g', 'h', 'i', 'k', 'l'], k: ['g', 'h', 'i', 'j', 'l'], l: ['g', 'h', 'i', 'j', 'k'] },
    { n: ['m', 'o', 'p', 'q', 'r'], m: ['n', 'o', 'p', 'q', 'r'], o: ['n', 'm', 'p', 'q', 'r'] },
    { p: ['n', 'm', 'o', 'q', 'r'], q: ['n', 'm', 'o', 'p', 'r'], r: ['n', 'm', 'o', 'p', 'q'] },
    { s: ['t', 'u', 'v', 'w', 'x'], t: ['s', 'u', 'v', 'w', 'x'], u: ['s', 't', 'v', 'w', 'x'] },
    { v: ['s', 't', 'u', 'w', 'x'], w: ['s', 't', 'u', 'v', 'x'], x: ['s', 't', 'u', 'v', 'w'] }
];

document.addEventListener("keydown", (e) => {
    // Don't intercept typing if user is in an input, textarea, or select field
    const activeTag = document.activeElement ? document.activeElement.tagName.toLowerCase() : '';
    if (['input', 'textarea', 'select'].includes(activeTag)) return;

    const key = e.key.toLowerCase();
    if (!/^[a-z]$/.test(key)) return;

    // Check if key belongs to judge button matrix (a to x)
    if (key < 'a' || key > 'x') return;

    const now = Date.now();

    // Remove conflicting keys for that judge from keyTimestamps
    for (const group of conflictGroups) {
        if (group[key]) {
            for (const conflictKey of group[key]) {
                keyTimestamps.delete(conflictKey);
            }
        }
    }

    // Set expiration for current key
    keyTimestamps.set(key, now + TIMER_DURATION);

    // Send immediately on each press with active unexpired keys (not decay)
    sendKeyState(getActiveKeys(), false);

    // Schedule cleanup for when the earliest key expires
    scheduleKeyCleanup();
});
