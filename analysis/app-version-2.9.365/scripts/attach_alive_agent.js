'use strict';

const TAG = '[alive]';
function log(msg) { console.log(TAG + ' ' + msg); }

function hideMaps() {
    const openPtr = Module.findGlobalExportByName('open');
    const readPtr = Module.findGlobalExportByName('read');
    if (!openPtr || !readPtr) return;
    const mapFds = {};
    Interceptor.attach(openPtr, {
        onEnter(args) {
            this.path = args[0].isNull() ? '' : args[0].readCString();
        },
        onLeave(retval) {
            const fd = retval.toInt32();
            if (fd >= 0 && this.path && this.path.indexOf('/maps') !== -1) {
                mapFds[fd] = true;
                log('open maps fd=' + fd);
            }
        }
    });
    Interceptor.attach(readPtr, {
        onEnter(args) {
            this.fd = args[0].toInt32();
            this.buf = args[1];
            this.len = args[2].toInt32();
        },
        onLeave(retval) {
            if (!mapFds[this.fd]) return;
            const n = retval.toInt32();
            if (n <= 0) return;
            const raw = this.buf.readUtf8String(n);
            if (!raw) return;
            const filtered = raw.split('\n').filter(function (line) {
                const low = line.toLowerCase();
                return low.indexOf('frida') === -1 && low.indexOf('gadget') === -1 && low.indexOf('linjector') === -1;
            }).join('\n');
            const bytes = Memory.allocUtf8String(filtered);
            const copyLen = Math.min(filtered.length, this.len);
            Memory.copy(this.buf, bytes, copyLen);
            retval.replace(copyLen);
        }
    });
    log('maps filter installed');
}

function listClasses() {
    if (typeof Java === 'undefined') {
        log('Java global missing');
        return;
    }
    Java.perform(function () {
        const names = Java.enumerateLoadedClassesSync();
        const hits = names.filter(function (n) {
            return n.indexOf('kuangxiang') !== -1 || n.indexOf('happybooker') !== -1 || n.indexOf('cwm') !== -1;
        });
        log('loaded classes=' + names.length + ' businessHits=' + hits.length);
        hits.slice(0, 40).forEach(function (n) { log('class ' + n); });
        try {
            const app = Java.use('android.app.ActivityThread').currentApplication();
            log('application=' + app.getClass().getName());
        } catch (e) {
            log('application err ' + e);
        }
    });
}

hideMaps();
setTimeout(listClasses, 300);
log('attach agent ready pid');
