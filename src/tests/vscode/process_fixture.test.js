const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const test = require('node:test');
const { readChildPid } = require('./process_fixture');

test('PID publication cannot turn an empty or invalid file into a cleanup target', (t) => {
    const directory = fs.mkdtempSync(path.join(os.tmpdir(), 'btrc-pid-publication-'));
    t.after(() => fs.rmSync(directory, { recursive: true, force: true }));
    const filename = path.join(directory, 'child.pid');
    for (const contents of ['', ' ', '0', '1', '-1', '-42', '12x', '1e3', '2147483648', String(process.pid)]) {
        fs.writeFileSync(filename, contents);
        let cleanupPid;
        assert.throws(() => { cleanupPid = readChildPid(filename); });
        assert.equal(cleanupPid, undefined, `invalid cleanup target from ${JSON.stringify(contents)}`);
    }
    const expected = process.pid === 42 ? 43 : 42;
    fs.writeFileSync(filename, String(expected));
    assert.equal(readChildPid(filename), expected);
});
