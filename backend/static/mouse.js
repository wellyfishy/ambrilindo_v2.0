let pressedKeys = new Set();
let timer = null;

function keySend(keys) {
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

    // Aka results
    if (countAka3 >= 2) akaResult = "Aka Ippon";
    else if (countAka2 >= 2) akaResult = "Aka Waza-ari";
    else if (countAka1 >= 2) akaResult = "Aka Yuko";
    else if ((countAka3 === 1 && countAka2 === 1 && countAka1 === 1) ||
             (countAka3 === 1 && countAka2 === 1) ||
             (countAka3 === 1 && countAka1 === 1))
        akaResult = "Aka Ippon";
    else if (countAka2 === 1 && countAka1 === 1)
        akaResult = "Aka Waza-ari";

    // Ao results
    if (countAo3 >= 2) aoResult = "Ao Ippon";
    else if (countAo2 >= 2) aoResult = "Ao Waza-ari";
    else if (countAo1 >= 2) aoResult = "Ao Yuko";
    else if ((countAo3 === 1 && countAo2 === 1 && countAo1 === 1) ||
             (countAo3 === 1 && countAo2 === 1) ||
             (countAo3 === 1 && countAo1 === 1))
        aoResult = "Ao Ippon";
    else if (countAo2 === 1 && countAo1 === 1)
        aoResult = "Ao Waza-ari";

    console.log("Keys pressed:", keys);
    console.log("Aka Result:", akaResult);
    console.log("Ao Result:", aoResult);
    const url = `/scoring-board/${tatamiPk}/message-retriever`;

    $.ajax({
        url: url,
        type: 'POST',
        data: {
            action: 'mouse',
            details: JSON.stringify([akaResult, aoResult]),
            csrfmiddlewaretoken: $('input[name=csrfmiddlewaretoken]').val()
        },
    });

    // Clear keys after processing
    pressedKeys.clear();
    timer = null; // reset timer
}

function startTimer() {
    // Only start the timer once
    if (!timer) {
        timer = setTimeout(() => {
            if (pressedKeys.size > 0) {
                keySend([...pressedKeys]);
            }
        }, 1250);
    }
}

// Conflict keys dictionary
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

// Key press handler
document.addEventListener("keydown", (e) => {
    const key = e.key.toLowerCase();

    // Only letters
    if (!/^[a-z]$/.test(key)) return;

    if (!pressedKeys.has(key)) {
        pressedKeys.add(key);

        // Remove conflicting keys
        for (const group of conflictGroups) {
            if (group[key]) {
                for (const conflictKey of group[key]) {
                    pressedKeys.delete(conflictKey);
                }
            }
        }

        console.log("Current keys:", [...pressedKeys]);
        startTimer(); // timer starts only once
    }
});
