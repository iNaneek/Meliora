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
  $('sync').onclick = function () {
    if (!api) return;
    var b = this; b.disabled = true; $('src-garmin').innerHTML = '<i></i>Garmin · syncing…';
    api.garmin_sync().then(function (r) { b.disabled = false; toast(r.msg); renderSources(); if (!$('bodyv').hidden) loadBody(); });
  };
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
      var g = src.garmin, gt = g.last_ok && new Date(g.last_ok), glabel;
      if (!g.connected) glabel = 'not connected';
      else if (g.busy) glabel = 'syncing…';
      else if (!gt) glabel = 'not synced yet';
      else glabel = (gt.toDateString() === new Date().toDateString() ? '' :
        gt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + ' ') + clock(gt) +
        (g.detail === 'waiting on sleep' ? ' · no sleep yet' : '');
      var gfresh = gt && gt.toDateString() === new Date().toDateString() && g.detail !== 'waiting on sleep';
      $('src-garmin').parentNode.className = 'src' + (gfresh ? '' : ' off');
      $('src-garmin').innerHTML = '<i></i>Garmin · ' + glabel;
      var w = src.today;
      $('wx').textContent = [homeName, w && w.high_f + '° / ' + w.low_f + '°', w && w.sky, w && w.precip].filter(Boolean).join(' · ');
    });
  }

  // ---------- Body view ----------
  var bodyData = null, bodyDays = 90;
  function num(v, dec) { return v == null ? '—' : (+v).toFixed(dec); }
  function hm(h) { if (h == null) return '—'; var m = Math.round(h * 60); return Math.floor(m / 60) + 'h ' + (m % 60 < 10 ? '0' : '') + m % 60 + 'm'; }
  function clockH(h) { if (h == null) return '—'; var hh = Math.floor(h), mm = Math.round((h - hh) * 60); return ((hh + 11) % 12 + 1) + ':' + (mm < 10 ? '0' : '') + mm + (hh < 12 ? ' am' : ' pm'); }
  function dur(s) { if (!s) return '—'; var m = Math.round(s / 60); return m >= 60 ? Math.floor(m / 60) + 'h ' + (m % 60 < 10 ? '0' : '') + m % 60 + 'm' : m + 'm'; }
  function pace(s) { return s ? Math.floor(s / 60) + ':' + (s % 60 < 10 ? '0' : '') + s % 60 + ' /mi' : '—'; }
  function typeName(t) { return (t || '').replace(/_/g, ' ').replace(/^./, function (c) { return c.toUpperCase(); }); }

  function setView(v) {
    document.querySelector('.app').dataset.view = v;
    $('bodyv').hidden = v !== 'body';
    document.querySelectorAll('.nav[data-view]').forEach(function (n) { n.classList.toggle('on', n.dataset.view === v); });
    Charts.hideTip();
    if (v === 'body') loadBody();
  }
  document.querySelectorAll('.nav[data-view]').forEach(function (n) {
    n.style.cursor = 'pointer';
    n.onclick = function () { setView(n.dataset.view); };
  });
  document.querySelectorAll('#bv-range button').forEach(function (b) {
    b.onclick = function () {
      bodyDays = +b.dataset.days;
      document.querySelectorAll('#bv-range button').forEach(function (o) { o.classList.toggle('on', o === b); });
      loadBody();
    };
  });
  document.querySelectorAll('.card .tbl').forEach(function (b) {
    b.onclick = function () { b.classList.toggle('on'); renderCard(b.closest('.card')); };
  });

  function loadBody() {
    if (!api) return;
    $('bodyv').style.opacity = bodyData ? .6 : 1;  // keep the old render while refetching
    api.body(bodyDays).then(function (d) { bodyData = d; $('bodyv').style.opacity = 1; renderBody(); });
  }

  function renderBody() {
    var d = bodyData; if (!d) return;
    if (d.empty) { $('bv-src').textContent = 'No Garmin data yet. Connect Garmin or run `uv run meliora-garmin sample`.'; return; }
    $('bv-src').textContent = (d.source === 'sample' ? 'Sample data' : 'Garmin') + ' · ' +
      Charts.shortDate(d.start) + ' – ' + Charts.shortDate(d.end);
    $('tiles').innerHTML = d.tiles.map(function (t) {
      var v = t.metric === 'sleep_h' ? hm(t.value) : num(t.value, t.dec);
      var delta = '';
      if (t.avg != null && t.n > 1) {
        var diff = t.value - t.avg, sign = diff > 0 ? '+' : diff < 0 ? '−' : '±';
        delta = sign + (t.metric === 'sleep_h' ? hm(Math.abs(diff)) : Math.abs(diff).toFixed(t.dec)) +
          ' vs ' + d.days + '-day avg ' + (t.metric === 'sleep_h' ? hm(t.avg) : t.avg.toFixed(t.dec));
      }
      var stale = t.day !== d.end ? '<span class="asof">as of ' + esc(Charts.shortDate(t.day)) + '</span>' : '';
      return '<div class="tile glass"><span class="lbl">' + esc(t.label) + '</span><span class="v">' + esc(v) +
        (t.unit && t.metric !== 'sleep_h' ? '<small>' + esc(t.unit) + '</small>' : '') + '</span>' +
        '<span class="d">' + esc(delta) + '</span>' + stale + Charts.spark(t.spark) + '</div>';
    }).join('');
    document.querySelectorAll('.card[data-chart]').forEach(renderCard);
    Charts.table($('acts'), d.activities, [
      { name: 'Date', get: function (a) { return Charts.shortDate(a.start.slice(0, 10)); } },
      { name: 'Activity', get: function (a) { return a.name || ''; } },
      { name: 'Type', get: function (a) { return typeName(a.type); } },
      { name: 'Distance', get: function (a) { return a.mi ? a.mi.toFixed(1) + ' mi' : '—'; } },
      { name: 'Time', get: function (a) { return dur(a.dur_s); } },
      { name: 'Pace', get: function (a) { return pace(a.pace_s); } },
      { name: 'Elev gain', get: function (a) { return a.elev_ft ? a.elev_ft.toLocaleString() + ' ft' : '—'; } },
      { name: 'Avg HR', get: function (a) { return a.avg_hr ? Math.round(a.avg_hr) + '' : '—'; } }
    ]);
    if (!d.activities.length) $('acts').textContent = 'No activities in this range.';
  }

  function renderCard(card) {
    var d = bodyData; if (!d || d.empty) return;
    var host = card.querySelector('.plot'), asTable = card.querySelector('.tbl').classList.contains('on');
    var kind = card.dataset.chart, daily = d.daily;
    if (kind === 'weeks') {
      var rows = d.weeks.map(function (w) {
        return { label: Charts.shortDate(w.week), title: 'Week of ' + Charts.shortDate(w.week),
          segs: { run: w.run_mi, hike: w.hike_mi },
          extra: [{ value: w.runs + ' runs, ' + w.hikes + ' hikes', name: '' }] };
      });
      if (asTable) return Charts.table(host, d.weeks.slice().reverse(), [
        { name: 'Week of', get: function (w) { return Charts.shortDate(w.week); } },
        { name: 'Run mi', get: function (w) { return w.run_mi.toFixed(1); } },
        { name: 'Hike mi', get: function (w) { return w.hike_mi.toFixed(1); } },
        { name: 'Runs', get: function (w) { return w.runs; } },
        { name: 'Hikes', get: function (w) { return w.hikes; } }]);
      return Charts.columns(host, rows, [{ key: 'run', name: 'Runs', cls: 's1' }, { key: 'hike', name: 'Hikes', cls: 's2' }],
        { fmt: function (v) { return v.toFixed(1) + ' mi'; }, minMax: 10 });
    }
    var withKey = function (k) { return daily.filter(function (p) { return p[k] != null; }); };
    if (kind === 'sleep') {
      if (asTable) return Charts.table(host, withKey('sleep_h').reverse(), [
        { name: 'Night ending', get: function (p) { return Charts.shortDate(p.day); } },
        { name: 'Sleep', get: function (p) { return hm(p.sleep_h); } },
        { name: 'Score', get: function (p) { return num(p.sleep_score, 0); } },
        { name: 'Bed', get: function (p) { return clockH(p.bed_time); } },
        { name: 'Wake', get: function (p) { return clockH(p.wake_time); } },
        { name: 'Deep', get: function (p) { return hm(p.sleep_deep_h); } },
        { name: 'REM', get: function (p) { return hm(p.sleep_rem_h); } }]);
      return Charts.lines(host, withKey('sleep_h'), [{ key: 'sleep_h', name: 'asleep', cls: 's1' }],
        { start: d.start, end: d.end, zero: true, ref: 8, refLabel: '8h', fmt: hm,
          tick: function (v) { return v + 'h'; },
          extra: function (p) { return [{ value: num(p.sleep_score, 0), name: 'score' },
            { value: clockH(p.bed_time) + ' → ' + clockH(p.wake_time), name: '' }]; } });
    }
    if (kind === 'hrv') {
      if (asTable) return Charts.table(host, withKey('hrv_night_ms').reverse(), [
        { name: 'Night ending', get: function (p) { return Charts.shortDate(p.day); } },
        { name: 'Nightly ms', get: function (p) { return num(p.hrv_night_ms, 0); } },
        { name: '7-day avg ms', get: function (p) { return num(p.hrv_week_ms, 0); } }]);
      return Charts.lines(host, withKey('hrv_night_ms'), [
        { key: 'hrv_night_ms', name: 'nightly', cls: 'm0', kind: 'dots' },
        { key: 'hrv_week_ms', name: '7-day avg', cls: 's1' }],
        { start: d.start, end: d.end, fmt: function (v) { return Math.round(v) + ' ms'; } });
    }
    if (kind === 'rhr') {
      if (asTable) return Charts.table(host, withKey('rhr').reverse(), [
        { name: 'Day', get: function (p) { return Charts.shortDate(p.day); } },
        { name: 'Resting HR', get: function (p) { return num(p.rhr, 0) + ' bpm'; } }]);
      return Charts.lines(host, withKey('rhr'), [{ key: 'rhr', name: 'resting', cls: 's1' }],
        { start: d.start, end: d.end, fmt: function (v) { return Math.round(v) + ' bpm'; } });
    }
  }
  var resizeT;
  window.addEventListener('resize', function () {
    clearTimeout(resizeT);
    resizeT = setTimeout(function () { if (!$('bodyv').hidden) document.querySelectorAll('.card[data-chart]').forEach(renderCard); }, 150);
  });

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
