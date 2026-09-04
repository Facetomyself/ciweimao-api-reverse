// Node black-box for official gt.js bind. No RuyiDOM.
// Input: argv[2] JSON file or RUYIDOM_INPUT_FILE / RUYIDOM_INPUT_JSON.
// stdout: one JSON line. Does not print gt/challenge/validate/w originals
// except the bind triple required by the caller.

import { readFileSync } from "node:fs";
import http from "node:http";
import https from "node:https";
import { webcrypto } from "node:crypto";
import vm from "node:vm";

const NativeDate = Date;
const nativeNow = Date.now.bind(Date);
const nativeSetTimeout = setTimeout;
const nativeClearTimeout = clearTimeout;

function SandboxDate(...args) {
  if (new.target) {
    return new NativeDate(...args);
  }
  return NativeDate(...args);
}
SandboxDate.now = () => NativeDate.now();
SandboxDate.parse = NativeDate.parse.bind(NativeDate);
SandboxDate.UTC = NativeDate.UTC.bind(NativeDate);
Object.setPrototypeOf(SandboxDate, NativeDate);
SandboxDate.prototype = NativeDate.prototype;

const NATIVE_UA =
  "Mozilla/5.0 (Linux; Android 15; Pixel 6 Build/AP3A.241005.015) " +
  "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/124.0.0.0 " +
  "Mobile Safari/537.36";
const PAGE_URL = "https://www.geetest.com/demo/bind-app.html";

function readInput() {
  const file = process.env.RUYIDOM_INPUT_FILE || process.argv[2] || "";
  if (file) {
    const raw = readFileSync(file, "utf8").replace(/^\uFEFF/, "");
    return JSON.parse(raw);
  }
  if (process.env.RUYIDOM_INPUT_JSON) {
    return JSON.parse(process.env.RUYIDOM_INPUT_JSON);
  }
  throw new Error("missing-input");
}

function fail(error, extra) {
  const payload = extra || {};
  payload.ok = false;
  payload.error = String(error || "unknown");
  process.stdout.write(JSON.stringify(payload) + "\n");
  process.exit(1);
}

function log(msg) {
  process.stderr.write("[gt3-node] " + String(msg) + "\n");
}

function publicUrl(src) {
  try {
    const parsed = new URL(String(src), PAGE_URL);
    return parsed.host + parsed.pathname;
  } catch {
    return String(src || "").split("?")[0].slice(0, 120);
  }
}

function resolveUrl(src, base) {
  const text = String(src || "");
  if (!text) {
    return text;
  }
  if (text.startsWith("//")) {
    return "https:" + text;
  }
  try {
    return new URL(text, base || PAGE_URL).href;
  } catch {
    return text;
  }
}

function fetchText(url, cookie) {
  const abs = resolveUrl(url, PAGE_URL);
  const work = new Promise((resolve, reject) => {
    const lib = abs.startsWith("http://") ? http : https;
    const req = lib.get(
      abs,
      {
        headers: {
          Accept: "*/*",
          "Accept-Language": "zh-CN,zh;q=0.9",
          "Accept-Encoding": "identity",
          "User-Agent": NATIVE_UA,
          Referer: PAGE_URL,
          Cookie: cookie || "",
        },
      },
      (res) => {
        const status = res.statusCode || 0;
        if (status >= 300 && status < 400 && res.headers.location) {
          const next = new URL(res.headers.location, abs).href;
          res.resume();
          fetchText(next, cookie).then(resolve, reject);
          return;
        }
        const chunks = [];
        res.on("data", (c) => chunks.push(c));
        res.on("end", () => {
          const buf = Buffer.concat(chunks);
          if (status >= 400) {
            reject(new Error("http-" + status + ":" + publicUrl(abs)));
            return;
          }
          resolve({
            url: abs,
            text: buf.toString("utf8"),
            setCookie: res.headers["set-cookie"] || [],
          });
        });
      },
    );
    req.on("error", reject);
    req.setTimeout(15000, () => {
      req.destroy(new Error("fetch-timeout:" + publicUrl(abs)));
    });
  });
  return Promise.race([
    work,
    new Promise((_, reject) => {
      nativeSetTimeout(
        () => reject(new Error("fetch-race:" + publicUrl(abs))),
        18000,
      );
    }),
  ]);
}

function noteW(gt3, src) {
  const text = String(src || "");
  if (text.indexOf("ajax.php") < 0) {
    return;
  }
  gt3.ajaxSeen = true;
  const q = text.split("?")[1] || "";
  let w = "";
  for (const part of q.split("&")) {
    const kv = part.split("=");
    if (decodeURIComponent(kv[0] || "") === "w") {
      try {
        w = decodeURIComponent(kv.slice(1).join("=") || "");
      } catch {
        w = kv.slice(1).join("=") || "";
      }
    }
  }
  if (!w) {
    return;
  }
  const alpha = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()";
  const body = w.length >= 256 ? w.slice(0, w.length - 256) : w;
  const tail = w.length >= 256 ? w.slice(w.length - 256) : "";
  let bodyOk = true;
  for (let i = 0; i < body.length; i += 1) {
    if (alpha.indexOf(body.charAt(i)) < 0) {
      bodyOk = false;
      break;
    }
  }
  gt3.wShape = {
    len: w.length,
    body_len: body.length,
    rsa_hex_len: tail.length,
    alphabet_ok: bodyOk,
    rsa_hex_ok: /^[0-9a-fA-F]*$/.test(tail),
    has_paren: w.indexOf("(") >= 0 || w.indexOf(")") >= 0,
  };
}

function make2d(el) {
  el = el || {};
  const ops = el._canvasOps || (el._canvasOps = []);
  const ctx = {
    fillStyle: "#000",
    strokeStyle: "#000",
    font: "14px Arial",
    textBaseline: "alphabetic",
    shadowBlur: 0,
    shadowColor: "rgba(0,0,0,0)",
    globalCompositeOperation: "source-over",
    lineWidth: 1,
    canvas: el,
    fillRect(x, y, w, h) {
      ops.push("fr:" + [x, y, w, h].join(","));
    },
    clearRect() {},
    fillText(text, x, y) {
      ops.push("ft:" + String(text) + "@" + x + "," + y);
    },
    strokeText(text) {
      ops.push("st:" + String(text));
    },
    beginPath() {},
    closePath() {},
    moveTo() {},
    lineTo(x, y) {
      ops.push("lt:" + x + "," + y);
    },
    arc() {},
    stroke() {},
    fill() {},
    save() {},
    restore() {},
    translate() {},
    scale() {},
    rotate() {},
    rect() {},
    clip() {},
    measureText(text) {
      return { width: String(text || "").length * 8, actualBoundingBoxAscent: 10, actualBoundingBoxDescent: 3 };
    },
    getImageData(x, y, w, h) {
      const width = Math.max(1, w || 1);
      const height = Math.max(1, h || 1);
      const data = new Uint8ClampedArray(width * height * 4);
      const seed = ops.join("|").length || 1;
      for (let i = 0; i < data.length; i += 1) {
        data[i] = (i * 17 + seed * 13 + (i % 7) * 29) & 255;
      }
      return { data, width, height };
    },
    putImageData() {},
    createLinearGradient() {
      return { addColorStop() {} };
    },
    createPattern() {
      return {};
    },
    drawImage() {},
    isPointInPath() {
      return false;
    },
  };
  return ctx;
}

function makeWebgl() {
  const debug = {
    UNMASKED_VENDOR_WEBGL: 37445,
    UNMASKED_RENDERER_WEBGL: 37446,
  };
  return {
    VERTEX_SHADER: 35633,
    FRAGMENT_SHADER: 35632,
    COMPILE_STATUS: 35713,
    LINK_STATUS: 35714,
    VENDOR: 7936,
    RENDERER: 7937,
    VERSION: 7938,
    getExtension(name) {
      if (String(name).indexOf("debug_renderer") >= 0) {
        return debug;
      }
      return {};
    },
    getParameter(name) {
      if (name === 7936 || name === 37445) {
        return "ARM";
      }
      if (name === 7937 || name === 37446) {
        return "Mali-G78";
      }
      if (name === 7938) {
        return "WebGL 1.0 (OpenGL ES 2.0 Chromium)";
      }
      return 0;
    },
    getSupportedExtensions() {
      return ["WEBGL_debug_renderer_info", "OES_texture_float"];
    },
    createBuffer() {
      return {};
    },
    createProgram() {
      return {};
    },
    createShader() {
      return {};
    },
    shaderSource() {},
    compileShader() {},
    attachShader() {},
    linkProgram() {},
    getShaderParameter() {
      return true;
    },
    getProgramParameter() {
      return true;
    },
    getShaderInfoLog() {
      return "";
    },
    getProgramInfoLog() {
      return "";
    },
    getContextAttributes() {
      return { alpha: true, antialias: true };
    },
    viewport() {},
    clearColor() {},
    clear() {},
  };
}

function makeEl(tag, owner) {
  const name = String(tag || "div").toUpperCase();
  const el = {
    tagName: name,
    nodeName: name,
    nodeType: 1,
    style: {},
    className: "",
    id: "",
    innerHTML: "",
    innerText: "",
    textContent: "",
    value: "",
    href: "",
    type: "",
    width: name === "CANVAS" ? 300 : 0,
    height: name === "CANVAS" ? 150 : 0,
    clientWidth: name === "CANVAS" ? 300 : 412,
    clientHeight: name === "CANVAS" ? 150 : 915,
    offsetWidth: name === "CANVAS" ? 300 : 412,
    offsetHeight: name === "CANVAS" ? 150 : 915,
    children: [],
    childNodes: [],
    parentNode: null,
    ownerDocument: owner || null,
    cookie: "",
    charset: "UTF-8",
    async: true,
    defer: false,
    crossOrigin: "",
    readyState: "",
    onload: null,
    onerror: null,
    onreadystatechange: null,
    _src: "",
    _loading: false,
    _loaded: false,
    getAttribute(key) {
      const k = String(key || "");
      if (k.toLowerCase() === "src") {
        return el._src;
      }
      return el[k];
    },
    setAttribute(key, value) {
      const k = String(key || "");
      if (k.toLowerCase() === "src") {
        el.src = value;
        return;
      }
      el[k] = value;
    },
    appendChild(child) {
      el.children.push(child);
      el.childNodes.push(child);
      if (child) {
        child.parentNode = el;
      }
      return child;
    },
    insertBefore(child, _ref) {
      return el.appendChild(child);
    },
    removeChild(child) {
      el.children = el.children.filter((item) => item !== child);
      el.childNodes = el.childNodes.filter((item) => item !== child);
      return child;
    },
    cloneNode() {
      return makeEl(name, owner);
    },
    addEventListener(type, fn) {
      if (type === "load") {
        el.onload = fn;
      }
      if (type === "error") {
        el.onerror = fn;
      }
    },
    removeEventListener() {},
    dispatchEvent() {
      return true;
    },
    getBoundingClientRect() {
      return {
        x: 0,
        y: 0,
        width: el.clientWidth,
        height: el.clientHeight,
        top: 0,
        left: 0,
        right: el.clientWidth,
        bottom: el.clientHeight,
      };
    },
    getContext(type) {
      if (String(type || "").toLowerCase().includes("webgl")) {
        return makeWebgl();
      }
      return make2d(el);
    },
    toDataURL() {
      const seed = (el._canvasOps || []).join("|") || "empty";
      return "data:image/png;base64," + Buffer.from(seed, "utf8").toString("base64");
    },
  };
  if (name === "IFRAME") {
    el.contentWindow = null;
    el.contentDocument = null;
  }
  return el;
}

async function main() {
  process.on("uncaughtException", (err) => {
    fail("uncaught:" + String(err && err.message ? err.message : err).slice(0, 180));
  });
  process.on("unhandledRejection", (err) => {
    fail("unhandled:" + String(err && err.message ? err.message : err).slice(0, 180));
  });
  const input = readInput();
  const gt = String(input.gt || "");
  const challenge = String(input.challenge || "");
  const gtJs = String(input.gt_js_url || "https://static.geetest.com/static/tools/gt.js");
  const apiServer = String(input.api_server || "api.geetest.com");
  const product = String(input.product || "bind");
  const lang = String(input.lang || "zh-cn");
  if (!gt || !challenge) {
    fail("missing-gt-or-challenge");
  }

  const gt3 = {
    scriptLoaded: false,
    ready: false,
    success: false,
    error: null,
    validate: null,
    ajaxSeen: false,
    wShape: null,
    loaded: [],
    cookie: "",
    miss: [],
  };

  const scripts = [];
  const documentRef = { current: null };
  const body = makeEl("body");
  const head = makeEl("head");
  const html = makeEl("html");
  html.appendChild(head);
  html.appendChild(body);
  html.clientWidth = 412;
  html.clientHeight = 915;
  html.documentElement = html;

  const document = {
    documentElement: html,
    head,
    body,
    cookie: "",
    readyState: "complete",
    hidden: false,
    visibilityState: "visible",
    compatMode: "CSS1Compat",
    nodeType: 9,
    currentScript: null,
    createElement(tag) {
      const el = makeEl(tag, document);
      if (String(tag).toLowerCase() === "script") {
        attachSrc(el);
        scripts.push(el);
      }
      if (String(tag).toLowerCase() === "iframe") {
        el.contentWindow = sandbox.window || sandbox;
        el.contentDocument = document;
      }
      return el;
    },
    createElementNS(_ns, tag) {
      return document.createElement(tag);
    },
    createTextNode(text) {
      return { nodeType: 3, textContent: String(text || ""), data: String(text || "") };
    },
    getElementsByTagName(tag) {
      const name = String(tag || "").toLowerCase();
      if (name === "head") {
        return [head];
      }
      if (name === "body") {
        return [body];
      }
      if (name === "html") {
        return [html];
      }
      if (name === "script") {
        return scripts.slice();
      }
      return [];
    },
    getElementById() {
      return null;
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
    removeEventListener() {},
    createEvent() {
      return { initEvent() {} };
    },
    hasFocus() {
      return true;
    },
  };
  documentRef.current = document;
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get() {
      return gt3.cookie;
    },
    set(value) {
      const piece = String(value || "").split(";")[0];
      if (piece) {
        gt3.cookie = gt3.cookie ? gt3.cookie + "; " + piece : piece;
      }
    },
  });
  body.ownerDocument = document;
  head.ownerDocument = document;
  html.ownerDocument = document;

  const perfBase = nativeNow() - 800;

  function AudioParam(value) {
    this.value = value;
    this.setValueAtTime = function (v) {
      this.value = v;
    };
    this.linearRampToValueAtTime = function () {};
    this.exponentialRampToValueAtTime = function () {};
  }
  function OscillatorNode() {
    this.type = "triangle";
    this.frequency = new AudioParam(10000);
    this.connect = function () { return this; };
    this.disconnect = function () {};
    this.start = function () {};
    this.stop = function () {};
  }
  function DynamicsCompressorNode() {
    this.threshold = new AudioParam(-50);
    this.knee = new AudioParam(40);
    this.ratio = new AudioParam(12);
    this.reduction = new AudioParam(-20);
    this.attack = new AudioParam(0);
    this.release = new AudioParam(0.25);
    this.connect = function () { return this; };
    this.disconnect = function () {};
  }
  function GainNode() {
    this.gain = new AudioParam(0);
    this.connect = function () { return this; };
    this.disconnect = function () {};
  }
  function AnalyserNode() {
    this.fftSize = 2048;
    this.frequencyBinCount = 1024;
    this.connect = function () { return this; };
    this.disconnect = function () {};
    this.getFloatFrequencyData = function (arr) {
      for (let i = 0; i < arr.length; i += 1) {
        arr[i] = -90 + (i % 17) + Math.sin(i / 9) * 4;
      }
    };
    this.getByteFrequencyData = function (arr) {
      for (let i = 0; i < arr.length; i += 1) {
        arr[i] = (i * 3) & 255;
      }
    };
  }
  function AudioContext() {
    this.sampleRate = 44100;
    this.currentTime = 0;
    this.state = "running";
    this.destination = { maxChannelCount: 2, connect() {}, disconnect() {} };
    this.createOscillator = function () { return new OscillatorNode(); };
    this.createDynamicsCompressor = function () { return new DynamicsCompressorNode(); };
    this.createGain = function () { return new GainNode(); };
    this.createAnalyser = function () { return new AnalyserNode(); };
    this.createScriptProcessor = function () {
      return { connect() {}, disconnect() {}, onaudioprocess: null };
    };
    this.createBuffer = function (ch, len, rate) {
      return {
        numberOfChannels: ch,
        length: len,
        sampleRate: rate,
        getChannelData() {
          return new Float32Array(len);
        },
      };
    };
    this.resume = function () { this.state = "running"; return Promise.resolve(); };
    this.close = function () { this.state = "closed"; return Promise.resolve(); };
  }
  function OfflineAudioContext(ch, len, rate) {
    AudioContext.call(this);
    this.length = len;
    this.sampleRate = rate || 44100;
    this.oncomplete = null;
    this.startRendering = function () {
      const buffer = this.createBuffer(ch || 1, len || 44100, this.sampleRate);
      const data = buffer.getChannelData(0);
      for (let i = 0; i < data.length; i += 1) {
        data[i] = Math.sin(i / 24) * 0.12;
      }
      const ev = { renderedBuffer: buffer };
      if (typeof this.oncomplete === "function") {
        nativeSetTimeout(() => this.oncomplete(ev), 0);
      }
      return Promise.resolve(buffer);
    };
  }
  OfflineAudioContext.prototype = Object.create(AudioContext.prototype);

  function wrappedTimer(fn, ms, ...args) {
    return nativeSetTimeout(function () {
      try {
        fn.apply(null, args);
      } catch (err) {
        const msg = String(err && err.message ? err.message : err);
        log("timer-err " + msg.slice(0, 180));
        gt3.error = gt3.error || msg.slice(0, 180);
      }
    }, ms);
  }
  function wrappedInterval(fn, ms, ...args) {
    return setInterval(function () {
      try {
        fn.apply(null, args);
      } catch (err) {
        const msg = String(err && err.message ? err.message : err);
        log("interval-err " + msg.slice(0, 180));
        gt3.error = gt3.error || msg.slice(0, 180);
      }
    }, ms);
  }

  const sandbox = {
    console: {
      log() {},
      info() {},
      warn() {},
      debug() {},
      error(...args) {
        log("page-err " + args.map(String).join(" ").slice(0, 180));
      },
    },
    setTimeout: wrappedTimer,
    clearTimeout: nativeClearTimeout,
    setInterval: wrappedInterval,
    clearInterval,
    Date: SandboxDate,
    Math,
    JSON,
    Number,
    String,
    Boolean,
    Array,
    Object,
    Error,
    TypeError,
    RangeError,
    SyntaxError,
    URIError,
    RegExp,
    parseInt,
    parseFloat,
    isNaN,
    isFinite,
    NaN,
    Infinity,
    undefined,
    encodeURIComponent,
    decodeURIComponent,
    encodeURI,
    decodeURI,
    escape,
    unescape,
    atob: (s) => Buffer.from(String(s), "base64").toString("binary"),
    btoa: (s) => Buffer.from(String(s), "binary").toString("base64"),
    Uint8Array,
    Uint8ClampedArray,
    Uint16Array,
    Uint32Array,
    Int8Array,
    Int16Array,
    Int32Array,
    Float32Array,
    Float64Array,
    ArrayBuffer,
    DataView,
    Promise,
    Map,
    Set,
    WeakMap,
    WeakSet,
    Symbol,
    Proxy,
    Reflect,
    performance: {
      now: () => nativeNow() - perfBase + 18.75,
      timeOrigin: perfBase,
      timing: {
        navigationStart: perfBase,
        fetchStart: perfBase + 4,
        domainLookupStart: perfBase + 6,
        domainLookupEnd: perfBase + 10,
        connectStart: perfBase + 10,
        connectEnd: perfBase + 18,
        requestStart: perfBase + 20,
        responseStart: perfBase + 40,
        responseEnd: perfBase + 55,
        domLoading: perfBase + 56,
        domInteractive: perfBase + 120,
        domContentLoadedEventStart: perfBase + 130,
        domContentLoadedEventEnd: perfBase + 132,
        domComplete: perfBase + 180,
        loadEventStart: perfBase + 181,
        loadEventEnd: perfBase + 190,
      },
    },
    crypto: webcrypto,
    AudioContext,
    webkitAudioContext: AudioContext,
    OfflineAudioContext,
    webkitOfflineAudioContext: OfflineAudioContext,
    navigator: {
      userAgent: NATIVE_UA,
      appVersion: NATIVE_UA,
      appName: "Netscape",
      appCodeName: "Mozilla",
      platform: "Linux armv8l",
      language: "zh-CN",
      languages: ["zh-CN", "zh"],
      hardwareConcurrency: 8,
      deviceMemory: 8,
      maxTouchPoints: 5,
      webdriver: false,
      vendor: "Google Inc.",
      product: "Gecko",
      productSub: "20030107",
      cookieEnabled: true,
      onLine: true,
      doNotTrack: null,
      plugins: { length: 0, item() { return null; }, namedItem() { return null; } },
      mimeTypes: { length: 0, item() { return null; }, namedItem() { return null; } },
      connection: { effectiveType: "4g", rtt: 50, downlink: 10 },
    },
    screen: {
      width: 412,
      height: 915,
      availWidth: 412,
      availHeight: 915,
      colorDepth: 24,
      pixelDepth: 24,
      orientation: { type: "portrait-primary", angle: 0 },
    },
    innerWidth: 412,
    innerHeight: 915,
    outerWidth: 412,
    outerHeight: 915,
    devicePixelRatio: 2.625,
    pageXOffset: 0,
    pageYOffset: 0,
    scrollX: 0,
    scrollY: 0,
    location: {
      protocol: "https:",
      href: PAGE_URL,
      host: "www.geetest.com",
      hostname: "www.geetest.com",
      pathname: "/demo/bind-app.html",
      origin: "https://www.geetest.com",
      search: "",
      hash: "",
      port: "",
    },
    history: { length: 1, pushState() {}, replaceState() {} },
    localStorage: {
      _data: {},
      getItem(k) {
        return Object.prototype.hasOwnProperty.call(this._data, k) ? this._data[k] : null;
      },
      setItem(k, v) {
        this._data[k] = String(v);
      },
      removeItem(k) {
        delete this._data[k];
      },
      clear() {
        this._data = {};
      },
    },
    sessionStorage: {
      _data: {},
      getItem(k) {
        return Object.prototype.hasOwnProperty.call(this._data, k) ? this._data[k] : null;
      },
      setItem(k, v) {
        this._data[k] = String(v);
      },
      removeItem(k) {
        delete this._data[k];
      },
      clear() {
        this._data = {};
      },
    },
    Image: function Image() {
      this.src = "";
      this.onload = null;
      this.onerror = null;
      this.width = 1;
      this.height = 1;
      this.complete = true;
    },
    MutationObserver: function MutationObserver() {
      this.observe = function () {};
      this.disconnect = function () {};
    },
    requestAnimationFrame: (cb) => setTimeout(() => cb(Date.now()), 16),
    cancelAnimationFrame: (id) => clearTimeout(id),
    getComputedStyle() {
      return {
        getPropertyValue() {
          return "";
        },
      };
    },
    matchMedia() {
      return { matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} };
    },
    addEventListener() {},
    removeEventListener() {},
    dispatchEvent() {
      return true;
    },
    ontouchstart: null,
    document,
    __gt3: gt3,
    Blob: function Blob() {},
    URL: {
      createObjectURL() {
        return "blob:https://www.geetest.com/node-stub";
      },
      revokeObjectURL() {},
    },
    Worker: function Worker() {
      this.postMessage = function () {};
      this.terminate = function () {};
      this.addEventListener = function () {};
      this.removeEventListener = function () {};
      this.onmessage = null;
      this.onerror = null;
    },
    OffscreenCanvas: function OffscreenCanvas(w, h) {
      this.width = w || 1;
      this.height = h || 1;
      this.getContext = function (type) {
        if (String(type || "").includes("webgl")) {
          return makeWebgl();
        }
        return make2d();
      };
    },
  };
  function noteMiss(label) {
    const name = String(label || "");
    if (!name || name === "undefined" || name === "NaN" || name === "then") {
      return;
    }
    if (gt3.miss.indexOf(name) < 0 && gt3.miss.length < 40) {
      gt3.miss.push(name);
      log("miss " + name);
    }
  }
  const tracked = new Proxy(sandbox, {
    get(target, prop, recv) {
      if (typeof prop === "string" && !Object.prototype.hasOwnProperty.call(target, prop)
          && !(prop in target)) {
        noteMiss(prop);
      }
      return Reflect.get(target, prop, recv);
    },
  });
  sandbox.window = tracked;
  sandbox.self = tracked;
  sandbox.top = tracked;
  sandbox.parent = tracked;
  sandbox.globalThis = tracked;
  sandbox.HTMLElement = function HTMLElement() {};
  sandbox.HTMLScriptElement = function HTMLScriptElement() {};
  sandbox.HTMLCanvasElement = function HTMLCanvasElement() {};
  sandbox.HTMLIFrameElement = function HTMLIFrameElement() {};
  sandbox.Element = function Element() {};
  sandbox.Node = function Node() {};
  sandbox.Event = function Event(type) {
    this.type = type;
  };
  sandbox.CustomEvent = function CustomEvent(type, init) {
    this.type = type;
    this.detail = init && init.detail;
  };

  sandbox.XMLHttpRequest = function XMLHttpRequest() {
    this.readyState = 0;
    this.status = 0;
    this.responseText = "";
    this.response = "";
    this.responseType = "";
    this.onreadystatechange = null;
    this.onload = null;
    this.onerror = null;
    this._headers = {};
    this._url = "";
    this._method = "GET";
    this.withCredentials = false;
  };
  sandbox.XMLHttpRequest.prototype.open = function open(method, url) {
    this._method = method;
    this._url = resolveUrl(url, PAGE_URL);
    noteW(gt3, this._url);
    this.readyState = 1;
  };
  sandbox.XMLHttpRequest.prototype.setRequestHeader = function setRequestHeader(k, v) {
    this._headers[k] = v;
  };
  sandbox.XMLHttpRequest.prototype.getAllResponseHeaders = function getAllResponseHeaders() {
    return "";
  };
  sandbox.XMLHttpRequest.prototype.getResponseHeader = function getResponseHeader() {
    return null;
  };
  sandbox.XMLHttpRequest.prototype.abort = function abort() {};
  sandbox.XMLHttpRequest.prototype.send = function send() {
    const xhr = this;
    fetchText(xhr._url, gt3.cookie)
      .then((got) => {
        xhr.readyState = 4;
        xhr.status = 200;
        xhr.responseText = got.text;
        xhr.response = got.text;
        if (xhr.onreadystatechange) {
          xhr.onreadystatechange();
        }
        if (xhr.onload) {
          xhr.onload();
        }
      })
      .catch((err) => {
        xhr.readyState = 4;
        xhr.status = 0;
        gt3.error = gt3.error || String(err && err.message ? err.message : err);
        if (xhr.onerror) {
          xhr.onerror(err);
        }
      });
  };

  const context = vm.createContext(tracked);
  context.eval = function evalInVm(code) {
    return vm.runInContext(String(code), context, { timeout: 20000 });
  };
  context.Function = function VMFunction(...args) {
    const body = String(args.pop() ?? "");
    const names = args.map((n) => String(n));
    return vm.runInContext(
      "(function(" + names.join(",") + "){\n" + body + "\n})",
      context,
      { timeout: 20000 },
    );
  };

  function runScript(code, filename) {
    vm.runInContext(code, context, { filename: String(filename || "script.js"), timeout: 20000 });
  }

  async function loadSrc(el, src) {
    if (!src || el._loading || el._loaded) {
      return;
    }
    el._loading = true;
    const abs = resolveUrl(src, PAGE_URL);
    noteW(gt3, abs);
    gt3.loaded.push(publicUrl(abs));
    document.currentScript = el;
    try {
      log("load " + publicUrl(abs));
      const got = await fetchText(abs, gt3.cookie);
      log("run " + publicUrl(abs) + " bytes=" + got.text.length);
      runScript(got.text, abs);
      log("done " + publicUrl(abs));
      el._loaded = true;
      el.readyState = "complete";
      if (typeof el.onload === "function") {
        el.onload();
      }
      if (typeof el.onreadystatechange === "function") {
        el.onreadystatechange();
      }
    } catch (err) {
      el._loading = false;
      if (typeof el.onerror === "function") {
        el.onerror(err);
      } else {
        throw err;
      }
    } finally {
      if (document.currentScript === el) {
        document.currentScript = null;
      }
    }
  }

  function attachSrc(el) {
    Object.defineProperty(el, "src", {
      configurable: true,
      get() {
        return el._src;
      },
      set(value) {
        el._src = String(value || "");
        if (el._src) {
          Promise.resolve().then(() => loadSrc(el, el._src)).catch((err) => {
            gt3.error = String(err && err.message ? err.message : err);
          });
        }
      },
    });
  }

  function maybeLoadChild(child) {
    if (child && child.tagName === "SCRIPT" && child._src) {
      Promise.resolve().then(() => loadSrc(child, child._src)).catch((err) => {
        gt3.error = String(err && err.message ? err.message : err);
      });
    }
  }

  const origHeadAppend = head.appendChild;
  head.appendChild = function appendChild(child) {
    origHeadAppend.call(head, child);
    maybeLoadChild(child);
    return child;
  };
  const origBodyAppend = body.appendChild;
  body.appendChild = function appendChild(child) {
    origBodyAppend.call(body, child);
    maybeLoadChild(child);
    return child;
  };
  const origHtmlAppend = html.appendChild;
  html.appendChild = function appendChild(child) {
    origHtmlAppend.call(html, child);
    maybeLoadChild(child);
    return child;
  };

  try {
    log("loader " + publicUrl(gtJs));
    const loader = await fetchText(gtJs, gt3.cookie);
    runScript(loader.text, gtJs);
    gt3.scriptLoaded = true;
    gt3.loaded.push(publicUrl(gtJs));
    log("loader-ok");
  } catch (err) {
    fail("gt-js-load:" + err);
  }

  const hasInit = vm.runInContext("typeof initGeetest === 'function'", context);
  if (!hasInit) {
    fail("initGeetest-missing", {
      script_loaded: true,
      loaded: gt3.loaded,
    });
  }

  const cfg = {
    gt,
    challenge,
    offline: false,
    new_captcha: input.new_captcha !== false,
    product,
    https: true,
    api_server: apiServer,
    lang,
    width: "300px",
  };
  sandbox.__cfg = cfg;
  vm.runInContext(
    "(function(){" +
      "initGeetest(window.__cfg, function(captchaObj){" +
      "  window.__gt3.objReady = true;" +
      "  captchaObj.onReady(function(){" +
      "    window.__gt3.ready = true;" +
      "    try { captchaObj.verify(); } catch (e) { window.__gt3.error = String(e); }" +
      "  });" +
      "  captchaObj.onSuccess(function(){" +
      "    window.__gt3.success = true;" +
      "    try {" +
      "      var v = captchaObj.getValidate() || {};" +
      "      window.__gt3.validate = {" +
      "        geetest_challenge: String(v.geetest_challenge || v.challenge || '')," +
      "        geetest_validate: String(v.geetest_validate || v.validate || '')," +
      "        geetest_seccode: String(v.geetest_seccode || v.seccode || '')" +
      "      };" +
      "    } catch (e) { window.__gt3.error = String(e); }" +
      "  });" +
      "  captchaObj.onError(function(err){" +
      "    window.__gt3.error = (err && (err.error_code || err.msg || err.message)) || 'onError';" +
      "  });" +
      "  captchaObj.onClose(function(){ window.__gt3.closed = true; });" +
      "});" +
      "})();",
    context,
  );

  const deadline = nativeNow() + 45000;
  while (nativeNow() < deadline) {
    if (gt3.success || gt3.error) {
      break;
    }
    await new Promise((resolve) => nativeSetTimeout(resolve, 50));
  }
  log("wait-end success=" + !!gt3.success + " ready=" + !!gt3.ready + " err=" + (gt3.error || ""));
  if (!gt3.success || !gt3.validate) {
    fail(gt3.error || "verify-timeout", {
      script_loaded: gt3.scriptLoaded,
      ready: gt3.ready,
      ajax_seen: gt3.ajaxSeen,
      w_shape: gt3.wShape,
      loaded: gt3.loaded,
      miss: gt3.miss,
    });
  }
  const triple = gt3.validate || {};
  const challengeOut = String(triple.geetest_challenge || triple.challenge || challenge);
  const validateOut = String(triple.geetest_validate || triple.validate || "");
  const seccodeOut = String(triple.geetest_seccode || triple.seccode || "");
  process.stdout.write(JSON.stringify({
    ok: true,
    origin: "node",
    script_loaded: true,
    ready: !!gt3.ready,
    success: true,
    ajax_seen: !!gt3.ajaxSeen,
    w_shape: gt3.wShape,
    loaded: gt3.loaded,
    miss: gt3.miss,
    challenge: challengeOut,
    validate: validateOut,
    seccode: seccodeOut,
    challenge_len: challengeOut.length,
    validate_len: validateOut.length,
    seccode_len: seccodeOut.length,
  }) + "\n");
  process.exit(0);
}

main().catch((err) => fail(err && err.stack ? err.stack : err));
