'use strict';

/**
 * Load packaged x86_64 libSecShell-x86.so through NativeBridge, and serve a
 * Frida-filtered copy of /proc/self/maps so the shell's maps parser does not
 * SIGSEGV in fclose.
 */

const TAG = '[secshell-arm]';
const PKG = 'com.kuangxiangciweimao.novel';
const DUMP_DIR = '/data/data/' + PKG + '/code_cache/';
const FAKE_MAPS = DUMP_DIR + 'maps.filtered';
const dumped = {};
const hideRe = /frida|gum-js|linjector|re\.frida|frida-agent|libfrida|hluda/i;

function log(msg) {
    console.log(TAG + ' ' + msg);
}

function dumpDex(ptr, size, tag) {
    if (size < 0x70 || size > 80 * 1024 * 1024) return;
    const key = tag + ':' + size + ':' + ptr;
    if (dumped[key]) return;
    dumped[key] = true;
    try {
        if (ptr.readCString(4) !== 'dex') return;
        const path = DUMP_DIR + tag + '_' + size + '.dex';
        const file = new File(path, 'wb');
        file.write(ptr.readByteArray(size));
        file.close();
        log('dumped ' + path);
    } catch (err) {
        log('dump fail ' + tag + ' ' + err);
    }
}

function writeFilteredMaps() {
    const libc = Process.getModuleByName('libc.so');
    const openatPtr = libc.getExportByName('openat');
    const readPtr = libc.getExportByName('read');
    log('openat=' + openatPtr + ' read=' + readPtr);
    const openatFn = new NativeFunction(openatPtr, 'int', ['int', 'pointer', 'int']);
    const readFn = new NativeFunction(readPtr, 'int', ['int', 'pointer', 'int']);
    const AT_FDCWD = -100;
    const fd = openatFn(AT_FDCWD, Memory.allocUtf8String('/proc/self/maps'), 0);
    log('openat maps fd=' + fd);
    if (fd < 0) {
        log('openat real maps failed');
        return null;
    }
    let raw = '';
    const buf = Memory.alloc(4097);
    while (true) {
        const n = readFn(fd, buf, 4096);
        if (n <= 0) break;
        buf.add(n).writeU8(0);
        raw += buf.readCString();
    }
    log('maps bytes=' + raw.length);
    const lines = raw.split('\n').filter(function (line) {
        return line.length > 0 &&
            line.indexOf('frida') === -1 &&
            line.indexOf('gum-js') === -1 &&
            line.indexOf('linjector') === -1;
    });
    const body = lines.join('\n') + '\n';
    const out = new File(FAKE_MAPS, 'w');
    out.write(body);
    out.flush();
    out.close();
    log('filtered maps lines=' + lines.length + ' -> ' + FAKE_MAPS);
    return FAKE_MAPS;
}

let mapsFp = NULL;

function hideMaps() {
    const fake = writeFilteredMaps();
    if (!fake) return;
    const fakePtr = Memory.allocUtf8String(fake);
    const libc = Process.getModuleByName('libc.so');
    const fopenPtr = libc.getExportByName('fopen');
    Interceptor.attach(fopenPtr, {
        onEnter(args) {
            const path = args[0].isNull() ? '' : args[0].readCString();
            this.redirect = !!(path && path.indexOf('/proc/') !== -1 && path.indexOf('maps') !== -1);
            if (this.redirect) {
                args[0] = fakePtr;
                log('fopen maps ' + path + ' -> ' + fake);
            }
        },
        onLeave(retval) {
            if (this.redirect && !retval.isNull()) {
                mapsFp = retval;
                log('maps FILE*=' + retval);
            }
        }
    });
    log('fopen maps redirect installed');
}

function patchSecshellMapsCheck(mod) {
    let addr = mod.base.add(0x7f540);
    const end = mod.base.add(0x7f5c0);
    while (addr.compare(end) < 0) {
        let insn;
        try {
            insn = Instruction.parse(addr);
        } catch (err) {
            addr = addr.add(1);
            continue;
        }
        log('disasm ' + addr + ' ' + insn.toString());
        if (insn.mnemonic === 'call') {
            log('nop call at ' + addr + ' ' + insn.toString());
            Memory.patchCode(addr, insn.size, function (code) {
                const writer = new X86Writer(code, { pc: addr });
                writer.putNopPadding(insn.size);
                writer.flush();
            });
        }
        addr = addr.add(insn.size);
    }
}

function hookNativeBridge() {
    const nb = Process.findModuleByName('libnb.so');
    if (!nb) return;
    const itf = nb.getExportByName('NativeBridgeItf');
    log('NativeBridgeItf version=' + itf.readU32());
    const loadExt = itf.add(8 + 13 * 8).readPointer();
    Interceptor.attach(loadExt, {
        onEnter(args) {
            this.path = args[0].isNull() ? '' : args[0].readCString();
            if (this.path && this.path.indexOf('SecShell') !== -1) {
                log('nb.loadLibraryExt ' + this.path);
            }
        },
        onLeave(retval) {
            if (this.path && this.path.indexOf('SecShell') !== -1) {
                log('nb.loadLibraryExt ret=' + retval);
                const mods = Process.enumerateModules().filter(function (m) {
                    return m.name.indexOf('SecShell') !== -1;
                });
                mods.forEach(function (mod) {
                    log('module ' + mod.name + ' ' + mod.base + ' size=' + mod.size);
                    try {
                        const dumpPath = DUMP_DIR + 'libSecShell-x86.mem.so';
                        const dumpFile = new File(dumpPath, 'wb');
                        let dumped = 0;
                        for (let off = 0; off < mod.size; off += 0x1000) {
                            const n = Math.min(0x1000, mod.size - off);
                            try {
                                dumpFile.write(mod.base.add(off).readByteArray(n));
                                dumped += n;
                            } catch (err) {
                                dumpFile.write(new Uint8Array(n).buffer);
                            }
                        }
                        dumpFile.close();
                        log('dumped so pages ' + dumped + ' / ' + mod.size);
                    } catch (err) {
                        log('so dump fail ' + err);
                    }
                    // maps fclose is swallowed globally; skip instruction NOP.
                });
            }
        }
    });
    log('hooked nb.loadLibraryExt @ ' + loadExt);
}

function hookOpenCommon() {
    const art = Process.findModuleByName('libart.so') || Process.findModuleByName('libdexfile.so');
    if (!art) return;
    art.enumerateExports().forEach(function (exp) {
        if (exp.type !== 'function') return;
        if (exp.name.indexOf('OpenCommon') === -1) return;
        if (exp.name.indexOf('DexFile') === -1 && exp.name.indexOf('DexFileLoader') === -1) return;
        Interceptor.attach(exp.address, {
            onEnter(args) {
                this.base = null;
                this.size = 0;
                for (let i = 0; i < 4; i++) {
                    try {
                        const mag = args[i].readCString(4);
                        if (mag === 'dex' || mag === 'dey') {
                            this.base = args[i];
                            this.size = this.base.add(0x20).readU32();
                            log('OpenCommon dex arg' + i + ' size=' + this.size);
                            break;
                        }
                    } catch (err) {
                    }
                }
            },
            onLeave() {
                if (this.base && this.size) dumpDex(this.base, this.size, 'opencommon');
            }
        });
        log('hooked OpenCommon');
    });
}

hideMaps();
hookNativeBridge();
hookOpenCommon();
log('agent loaded');
