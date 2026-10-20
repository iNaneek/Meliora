// Front end. Decisions come from Python (pywebview.api); the sky comes from sky.js.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var api = null, state = null, live = true, homeName = '';

  function fmt(h) {
    var hh = Math.floor(h), mm = Math.round((h - hh) * 60);
    return ((hh + 11) % 12 + 1) + ':' + (mm < 10 ? '0' : '') + mm;
  }
  function clock(d) { return d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' }).toLowerCase(); }
  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }
  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(toast.h); toast.h = setTimeout(function () { t.classList.remove('show'); }, 2600);
  }

  // ---------- sky + slider ----------
  function skyAt(min) {
    var d = new Date(); d.setHours(0, 0, 0, 0); d.setMinutes(min);
    $('phase').textContent = Sky.paint(d).phase;
    $('time').textContent = clock(d);
  }
  function nowMin() { var n = new Date(); return n.getHours() * 60 + n.getMinutes(); }
  function setLive(on) {
    live = on; $('time').classList.toggle('scrubbed', !on);
    if (on) { $('slider').value = nowMin(); skyAt(nowMin()); }
  }
  $('slider').addEventListener('input', function () { if (live) setLive(false); skyAt(+this.value); });
  $('time').onclick = function () { setLive(true); };

  // ---------- render from Python state ----------
  function render(s, animate) {
    var changed = !state || state.sentence !== s.sentence;
    state = s;
    var draw = function () {
      $('date').textContent = s.date;
      $('sentence').innerHTML = s.sentence;  // trusted: built by rules.py
      $('because').innerHTML = s.because.map(function (c) { return '<span class="chip">' + esc(c) + '</span>'; }).join('');
      renderNext(s.next);
      ['sentence', 'because', 'next'].forEach(function (id) { $(id).classList.remove('fading'); });
    };
    if (animate && changed) {
      ['sentence', 'because', 'next'].forEach(function (id) { $(id).classList.add('fading'); });
      setTimeout(draw, 200);
    } else draw();
    renderRows(s);
    $('pendcount').textContent = s.pending ? s.pending + ' pencil' : '';
  }

  function renderNext(n) {
    var el = $('next');
    if (!n) { el.innerHTML = '<div class="lbl">Next</div><div class="what">Nothing left today</div><div class="meta">The rest window is yours.</div>'; return; }
    var acts = n.pencil
      ? '<button class="btn primary" data-act="confirm">Confirm</button><button class="btn" data-act="decline">Not this</button>'
      : '<button class="btn primary" data-act="start">Start</button>';
    el.innerHTML = '<div class="lbl">' + esc(n.label) + '</div><div class="what">' + esc(n.what) +
      '</div><div class="meta">' + esc(n.meta) + '</div><div class="acts">' + acts + '</div>';
    el.dataset.id = (state.blocks.filter(function (b) { return b.title === n.what; })[0] || {}).id || '';
  }

  function renderRows(s) {
    $('rows').innerHTML = s.blocks.map(function (b) {
      var cls = 'row ' + b.kind;
      if (b.decision === 'decline') cls += ' declined';
      else if (b.start <= s.now && s.now < b.end) cls += ' now';
      else if (b.end <= s.now) cls += ' past';
      var acts = '';
      if (b.kind === 'pen') acts = b.decision === 'decline'
        ? '<span class="pa"><button data-act="undo">Undo</button></span>'
        : '<span class="pa"><button class="y" data-act="confirm">Confirm</button><button data-act="decline">Decline</button></span>';
      return '<div class="' + cls + '" data-id="' + b.id + '"><span class="tm">' + fmt(b.start) + '</span>' +
        '<span><b>' + esc(b.title) + '</b><span class="sub">' + esc(b.sub) + '</span></span>' + acts + '</div>';
    }).join('');
  }

  // ---------- actions → Python ----------
  document.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-act]'); if (!b || !api) return;
    var host = b.closest('[data-id]'), id = host && host.dataset.id, what = b.dataset.act;
    if (what === 'start') { toast('Timers come later. For now: go.'); return; }
    (what === 'undo' ? api.undo(id) : api.decide(id, what)).then(function (s) {
      render(s, true);
      if (what === 'confirm') toast('Inked. Saved locally; nothing is written to Calendar yet.');
      if (what === 'decline') toast('Declined. The plan re-ran without it.');
    });
  });
  $('reset').onclick = function () { api && api.reset().then(function (s) { render(s, true); toast('Demo reset.'); }); };
  document.querySelectorAll('[data-push]').forEach(function (b) {
    b.onclick = function () { document.querySelectorAll('[data-push]').forEach(function (o) { o.classList.toggle('on', o === b); }); };
  });
  $('ask').onclick = function () { $('drawer').classList.toggle('open'); setTimeout(function () { $('q').focus(); }, 220); };
  $('close').onclick = function () { $('drawer').classList.remove('open'); };
  $('compose').onsubmit = function (e) {
    e.preventDefault(); var q = $('q').value.trim(); if (!q || !api) return;
    var msgs = $('msgs');
    msgs.insertAdjacentHTML('beforeend', '<div class="m u">' + esc(q) + '</div><div class="m a pending">…</div>');
    $('q').value = '';
    api.ask(q).then(function (a) { var p = msgs.querySelector('.pending'); p.textContent = a; p.classList.remove('pending'); msgs.scrollTop = 1e6; });
  };

  // Per-source "last synced". Stale is shown, not hidden: the app keeps working on the cache.
  function renderSources() {
    api.sources().then(function (src) {
      var el = $('src-weather'), t = src.weather && new Date(src.weather), label;
      if (!t) label = src.weather_busy ? 'syncing…' : 'not synced yet';
      else {
        var day = t.toDateString() === new Date().toDateString() ? '' : t.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ';
        label = (src.weather_busy ? 'syncing… last ' : '') + day + clock(t);
      }
      var fresh = t && (Date.now() - t) < 6 * 3600e3;
      el.className = 'src' + (fresh ? '' : ' off');
      el.innerHTML = '<i></i>Weather · ' + label;
      var w = src.today;
      $('wx').textContent = [homeName, w && w.high_f + '° / ' + w.low_f + '°', w && w.sky, w && w.precip].filter(Boolean).join(' · ');
    });
  }

  // ---------- boot ----------
  Sky.scatterStars();
  $('slider').style.setProperty('--track', Sky.dayStrip(new Date()));
  setLive(true);
  window.addEventListener('resize', function () { skyAt(+$('slider').value); });
  // Battery: pause sky animations and skip polling while the window is hidden or in the background.
  function away() { return document.hidden || !document.hasFocus(); }
  function every(ms, fn) { setInterval(function () { if (!document.hidden) fn(); }, ms); }
  function onReturn() {
    document.documentElement.classList.toggle('paused', away());
    if (document.hidden) return;
    if (live) setLive(true);
    if (api) { api.today().then(function (s) { render(s, true); }); renderSources(); }
  }
  document.addEventListener('visibilitychange', onReturn);
  window.addEventListener('focus', onReturn);
  window.addEventListener('blur', function () { document.documentElement.classList.add('paused'); });
  document.documentElement.classList.toggle('paused', away());
  every(30000, function () { if (live) setLive(true); });

  function boot() {
    api = window.pywebview.api;
    api.home().then(function (h) {
      homeName = h.name; Sky.setHome(h.lat, h.lon);
      $('slider').style.setProperty('--track', Sky.dayStrip(new Date()));
      skyAt(+$('slider').value); renderSources();
    });
    api.today().then(function (s) { render(s, false); $('bridge').innerHTML = '<i></i>Python bridge ok'; })
      .catch(function (err) { $('sentence').textContent = 'Python bridge error: ' + err; });
    every(60000, function () { api.today().then(function (s) { render(s, true); }); });
    renderSources(); every(60000, renderSources);
  }
  if (window.pywebview && window.pywebview.api) boot();
  else window.addEventListener('pywebviewready', boot);
})();
