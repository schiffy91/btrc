const assert = require('node:assert/strict');
const fs = require('node:fs');

/** Read only a complete child PID before assigning it to a cleanup owner. */
function readChildPid(filename) {
    const text = fs.readFileSync(filename, 'utf8');
    assert.match(text, /^[1-9][0-9]*$/, 'child PID file is incomplete or malformed');
    const pid = Number(text);
    assert(Number.isSafeInteger(pid) && pid > 1 && pid <= 0x7fffffff,
        'child PID must identify one process');
    assert.notEqual(pid, process.pid, 'child PID must not identify the test runner');
    return pid;
}

module.exports = { readChildPid };
