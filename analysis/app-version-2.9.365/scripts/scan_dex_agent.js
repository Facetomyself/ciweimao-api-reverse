'use strict';

const TAG = '[scan-dex]';
function log(msg) { console.log(TAG + ' ' + msg); }

function u32(ptr) {
    return ptr.readU32();
}

function looksLikeDex(ptr, maxLen) {
    try {
        const magic = ptr.readCString(4);
        if (magic !== 'dex') return null;
        const headerSize = u32(ptr.add(0x24));
        const fileSize = u32(ptr.add(0x20));
        const classDefs = u32(ptr.add(0x60));
        if (headerSize !== 0x70) return null;
        if (fileSize < 0x70 || fileSize > maxLen) return null;
        if (classDefs < 1) return null;
        return { fileSize: fileSize, classDefs: classDefs };
    } catch (e) {
        return null;
    }
}

const found = [];
const ranges = Process.enumerateRanges('r--');
log('ranges=' + ranges.length);
let pending = ranges.length;
if (pending === 0) {
    send({ type: 'dex-hits', hits: found });
}
ranges.forEach(function (range) {
    if (range.size < 0x70) {
        pending -= 1;
        if (pending === 0) send({ type: 'dex-hits', hits: found });
        return;
    }
    Memory.scan(range.base, range.size, '64 65 78 0a', {
        onMatch(address) {
            const info = looksLikeDex(address, range.size - address.sub(range.base).toInt32());
            if (info) {
                found.push({
                    base: address.toString(),
                    size: info.fileSize,
                    classDefs: info.classDefs,
                    prot: range.protection,
                    file: range.file ? range.file.path : ''
                });
            }
            return 'continue';
        },
        onComplete() {
            pending -= 1;
            if (pending === 0) {
                found.sort(function (a, b) { return b.size - a.size; });
                log('dexHits=' + found.length);
                found.slice(0, 30).forEach(function (item) {
                    log(JSON.stringify(item));
                });
                send({ type: 'dex-hits', hits: found });
            }
        }
    });
});
