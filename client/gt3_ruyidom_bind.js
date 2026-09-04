// GT3 fullpage bind black-box: load official gt.js, initGeetest(bind), verify,
// read getValidate(). Input via RUYIDOM_INPUT_FILE / RUYIDOM_INPUT_JSON.
// stdout: one JSON line. Does not print helper commentary.

function readInput() {
  var env = Components.classes["@mozilla.org/process/environment;1"]
    .getService(Components.interfaces.nsIEnvironment);
  var raw = "{}";
  if (env.exists("RUYIDOM_INPUT_FILE")) {
    var path = env.get("RUYIDOM_INPUT_FILE");
    var file = Components.classes["@mozilla.org/file/local;1"]
      .createInstance(Components.interfaces.nsIFile);
    file.initWithPath(path);
    var fstream = Components.classes["@mozilla.org/network/file-input-stream;1"]
      .createInstance(Components.interfaces.nsIFileInputStream);
    fstream.init(file, 1, 0, 0);
    var cstream = Components.classes["@mozilla.org/intl/converter-input-stream;1"]
      .createInstance(Components.interfaces.nsIConverterInputStream);
    cstream.init(fstream, "UTF-8", 0, 0);
    var data = {};
    var str = "";
    while (cstream.readString(4096, data) !== 0) {
      str += data.value;
    }
    cstream.close();
    raw = str;
  } else if (env.exists("RUYIDOM_INPUT_JSON")) {
    raw = env.get("RUYIDOM_INPUT_JSON");
  }
  return JSON.parse(raw || "{}");
}

function fail(error, extra) {
  var payload = extra || {};
  payload.ok = false;
  payload.error = String(error || "unknown");
  print(JSON.stringify(payload));
  RuyiDOM.exit(1);
}

RuyiDOM.main(function () {
  var input = {};
  try {
    input = readInput();
  } catch (error) {
    fail("input-parse:" + error);
    return;
  }
  var gt = String(input.gt || "");
  var challenge = String(input.challenge || "");
  var gtJs = String(input.gt_js_url || "https://static.geetest.com/static/tools/gt.js");
  var apiServer = String(input.api_server || "api.geetest.com");
  var product = String(input.product || "bind");
  var lang = String(input.lang || "zh-cn");
  if (!gt || !challenge) {
    fail("missing-gt-or-challenge");
    return;
  }

  var html = "<!DOCTYPE html><html><head></head><body></body></html>";
  var dom = new RuyiDOM(html, {
    url: "https://www.geetest.com/demo/bind-app.html",
    secure: true,
    profile: false,
    webgl: true,
  });

  try {
    dom.evalInPage(
      "window.__gt3 = {scriptLoaded:false, ready:false, success:false, closed:false, error:null, validate:null, ajaxSeen:false};"
    );
    dom.evalInPage(
      "(function(){" +
      "  function noteW(src){" +
      "    var text = String(src || '');" +
      "    if (text.indexOf('ajax.php') < 0) return;" +
      "    window.__gt3.ajaxSeen = true;" +
      "    var q = text.split('?')[1] || '';" +
      "    var w = '';" +
      "    q.split('&').forEach(function(part){" +
      "      var kv = part.split('=');" +
      "      if (decodeURIComponent(kv[0] || '') === 'w') {" +
      "        try { w = decodeURIComponent(kv.slice(1).join('=') || ''); }" +
      "        catch (e) { w = kv.slice(1).join('=') || ''; }" +
      "      }" +
      "    });" +
      "    if (!w) return;" +
      "    var alpha = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789()';" +
      "    var body = w.length >= 256 ? w.slice(0, w.length - 256) : w;" +
      "    var tail = w.length >= 256 ? w.slice(w.length - 256) : '';" +
      "    var bodyOk = true;" +
      "    for (var i = 0; i < body.length; i++) {" +
      "      if (alpha.indexOf(body.charAt(i)) < 0) { bodyOk = false; break; }" +
      "    }" +
      "    window.__gt3.wShape = {" +
      "      len: w.length," +
      "      body_len: body.length," +
      "      rsa_hex_len: tail.length," +
      "      alphabet_ok: bodyOk," +
      "      rsa_hex_ok: /^[0-9a-fA-F]*$/.test(tail)," +
      "      has_paren: w.indexOf('(') >= 0 || w.indexOf(')') >= 0" +
      "    };" +
      "  }" +
      "  var orig = Node.prototype.appendChild;" +
      "  Node.prototype.appendChild = function(node){" +
      "    try {" +
      "      if (node && node.tagName === 'SCRIPT') {" +
      "        noteW(node.src || node.getAttribute('src') || '');" +
      "      }" +
      "    } catch (e) {}" +
      "    return orig.apply(this, arguments);" +
      "  };" +
      "  var setAttr = Element.prototype.setAttribute;" +
      "  Element.prototype.setAttribute = function(name, value){" +
      "    try { if (String(name).toLowerCase() === 'src') noteW(value); } catch (e) {}" +
      "    return setAttr.apply(this, arguments);" +
      "  };" +
      "})();"
    );
    var loadSrc = JSON.stringify(gtJs);
    dom.evalInPage(
      "(function(){" +
      "  var s = document.createElement('script');" +
      "  s.src = " + loadSrc + ";" +
      "  s.onload = function(){ window.__gt3.scriptLoaded = true; };" +
      "  s.onerror = function(){ window.__gt3.error = 'gt-js-load'; };" +
      "  (document.head || document.documentElement).appendChild(s);" +
      "})();"
    );
    var loaded = dom.pumpUntil(function () {
      return dom.eval("window.__gt3.scriptLoaded === true || window.__gt3.error != null");
    }, { timeout: 20000, interval: 200 });
    if (!loaded) {
      fail("gt-js-timeout", { script_loaded: false });
      return;
    }
    var loadError = dom.eval("window.__gt3.error", { mode: "string" });
    if (loadError && loadError !== "null") {
      fail(loadError, { script_loaded: false });
      return;
    }
    var hasInit = dom.eval("typeof initGeetest === 'function'");
    if (!hasInit) {
      fail("initGeetest-missing", { script_loaded: true });
      return;
    }

    var configJson = JSON.stringify({
      gt: gt,
      challenge: challenge,
      offline: false,
      new_captcha: input.new_captcha !== false,
      product: product,
      https: true,
      api_server: apiServer,
      lang: lang,
      width: "300px",
    });
    dom.evalInPage(
      "(function(){" +
      "  var cfg = " + configJson + ";" +
      "  initGeetest(cfg, function(captchaObj){" +
      "    window.__gt3.objReady = true;" +
      "    captchaObj.onReady(function(){" +
      "      window.__gt3.ready = true;" +
      "      try { captchaObj.verify(); } catch (e) { window.__gt3.error = String(e); }" +
      "    });" +
      "    captchaObj.onSuccess(function(){" +
      "      window.__gt3.success = true;" +
      "      try { window.__gt3.validate = captchaObj.getValidate(); }" +
      "      catch (e) { window.__gt3.error = String(e); }" +
      "    });" +
      "    captchaObj.onError(function(err){" +
      "      window.__gt3.error = (err && (err.error_code || err.msg || err.message)) || 'onError';" +
      "    });" +
      "    captchaObj.onClose(function(){ window.__gt3.closed = true; });" +
      "  });" +
      "})();"
    );

    var done = dom.pumpUntil(function () {
      return dom.eval("window.__gt3.success === true || window.__gt3.error != null");
    }, { timeout: 45000, interval: 250 });
    var state = dom.eval(
      "({scriptLoaded: window.__gt3.scriptLoaded, ready: window.__gt3.ready," +
      " success: window.__gt3.success, ajaxSeen: window.__gt3.ajaxSeen," +
      " error: window.__gt3.error, validate: window.__gt3.validate," +
      " wShape: window.__gt3.wShape || null})"
    ) || {};
    if (!done && !state.success) {
      fail("verify-timeout", {
        script_loaded: !!state.scriptLoaded,
        ready: !!state.ready,
        ajax_seen: !!state.ajaxSeen,
      });
      return;
    }
    if (!state.success || !state.validate) {
      fail(state.error || "no-validate", {
        script_loaded: !!state.scriptLoaded,
        ready: !!state.ready,
        ajax_seen: !!state.ajaxSeen,
      });
      return;
    }
    var triple = state.validate || {};
    var challengeOut = String(triple.geetest_challenge || triple.challenge || challenge);
    var validateOut = String(triple.geetest_validate || triple.validate || "");
    var seccodeOut = String(triple.geetest_seccode || triple.seccode || "");
    print(JSON.stringify({
      ok: true,
      script_loaded: true,
      ready: !!state.ready,
      success: true,
      ajax_seen: !!state.ajaxSeen,
      w_shape: state.wShape || null,
      challenge: challengeOut,
      validate: validateOut,
      seccode: seccodeOut,
      challenge_len: challengeOut.length,
      validate_len: validateOut.length,
      seccode_len: seccodeOut.length,
    }));
    RuyiDOM.exit(0);
  } catch (error) {
    fail(error);
  } finally {
    try { dom.close(); } catch (e) {}
  }
});
