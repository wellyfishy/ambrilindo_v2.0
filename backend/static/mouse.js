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
    { a: ['b', 'c'], b: ['a', 'c'], c: ['a', 'b'] },
    { d: ['e', 'f'], e: ['d', 'f'], f: ['d', 'e'] },
    { g: ['h', 'i'], h: ['g', 'i'], i: ['g', 'h'] },
    { j: ['k', 'l'], k: ['j', 'l'], l: ['j', 'k'] },
    { n: ['m', 'o'], m: ['n', 'o'], o: ['n', 'm'] },
    { p: ['q', 'r'], q: ['p', 'r'], r: ['p', 'q'] },
    { s: ['t', 'u'], t: ['s', 'u'], u: ['s', 't'] },
    { v: ['w', 'x'], w: ['v', 'x'], x: ['v', 'w'] }
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
