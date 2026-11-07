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
    var demo = s.source !== 'calendar';
    $('tag-demo').hidden = !demo; $('reset').hidden = !demo;
    $('allday').textContent = s.all_day && s.all_day.length ? 'All day: ' + s.all_day.join(' · ') : '';
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

  // ---------- day timeline ----------
  // A time grid, 7a–10p by default. It grows to the hour when an event starts earlier or
  // ends later, so a 6 am lift or an 11 pm call still shows without a mostly empty midnight grid.
  var DAY_START = 7, DAY_END = 22, MIN_HOUR_PX = 30, scrolledToNow = false;

  function hourLabel(h) { var hh = h % 24; return ((hh + 11) % 12 + 1) + (hh < 12 ? 'a' : 'p'); }

  // Side-by-side columns for overlapping blocks: each run of overlaps shares the width.
  function layout(blocks) {
    var sorted = blocks.slice().sort(function (a, b) { return a.start - b.start || b.end - a.end; });
    var out = [], cluster = [], cols = [], clusterEnd = -1;
    function flush() { cluster.forEach(function (c) { c.cols = cols.length; }); cluster = []; cols = []; }
    sorted.forEach(function (b) {
      if (b.start >= clusterEnd) { flush(); clusterEnd = -1; }
      var col = cols.findIndex(function (end) { return end <= b.start; });
      if (col < 0) { col = cols.length; cols.push(0); }
      cols[col] = b.end;
      var item = { b: b, col: col, cols: 1 };
      cluster.push(item); out.push(item);
      clusterEnd = Math.max(clusterEnd, b.end);
    });
    flush();
    return out;
  }

  function renderRows(s) {
    var lo = DAY_START, hi = DAY_END;
    s.blocks.forEach(function (b) { lo = Math.min(lo, Math.floor(b.start)); hi = Math.max(hi, Math.ceil(b.end)); });
    lo = Math.max(0, lo); hi = Math.min(24, hi);
    var span = hi - lo, pct = function (h) { return ((h - lo) / span * 100).toFixed(3) + '%'; };
    var wrap = $('rows'), hourPx = Math.max(MIN_HOUR_PX, (wrap.clientHeight - 12) / span);
    var html = '';
    for (var h = lo; h <= hi; h++) {
      html += '<div class="hr" style="top:' + pct(h) + '"><span>' + (h < hi ? hourLabel(h) : '') + '</span></div>';
    }
    layout(s.blocks).forEach(function (it) {
      var b = it.b, dur = b.end - b.start, cls = 'ev ' + b.kind;
      if (b.decision === 'decline') cls += ' declined';
      else if (b.start <= s.now && s.now < b.end) cls += ' now';
      else if (b.end <= s.now) cls += ' past';
      var px = dur * hourPx;  // how much fits: one line, two lines, or title + time + place
      cls += px < 30 ? ' s' : px < 50 ? ' m' : '';
      var acts = '';
      if (b.kind === 'pen') acts = b.decision === 'decline'
        ? '<span class="pa"><button data-act="undo">Undo</button></span>'
        : '<span class="pa"><button class="y" data-act="confirm">Confirm</button><button data-act="decline">Decline</button></span>';
      var when = fmt(b.start) + '–' + fmt(b.end);
      var style = 'top:' + pct(Math.max(b.start, lo)) + ';height:calc(' + pct(Math.min(b.end, hi)) + ' - ' + pct(Math.max(b.start, lo)) + ' - 2px);' +
        'left:calc((100% - 44px) * ' + (it.col / it.cols) + ' + 44px);width:calc((100% - 44px) / ' + it.cols + ' - 3px)';
      html += '<div class="' + cls + '" data-id="' + b.id + '" style="' + style + '" title="' + esc(b.title + ' · ' + when + (b.sub ? ' · ' + b.sub : '')) + '">' +
        '<b>' + esc(b.title) + '</b><span class="tm">' + when + '</span>' +
        (b.sub ? '<span class="sub">' + esc(b.sub) + '</span>' : '') + acts + '</div>';
    });
    if (s.now >= lo && s.now <= hi) html += '<div class="nowline" style="top:' + pct(s.now) + '"></div>';
    if (s.source === 'calendar' && !s.blocks.length) html += '<div class="tl-empty">Nothing on your calendar today</div>';
    wrap.innerHTML = '<div class="tl" style="--span:' + span + '">' + html + '</div>';
    // When the grid is taller than the panel, open it at the current hour once.
    if (!scrolledToNow && wrap.scrollHeight > wrap.clientHeight + 4) {
      scrolledToNow = true;
      wrap.scrollTop = Math.max(0, (s.now - lo - 1) / span * wrap.scrollHeight);
    }
  }

  // ---------- actions → Python ----------
  document.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-act]'); if (!b || !api) return;
    var host = b.closest('[data-id]'), id = host && host.dataset.id, what = b.dataset.act;
    if (what === 'start') { toast('Timers come later. For now: go.'); return; }
    (what === 'undo' ? api.undo(id) : api.decide(id, what)).then(function (s) {
      render(s, true);
      if (s.msg) { toast(s.msg); return; }  // a proposal from Ask: Confirm wrote it to Calendar
      if (what === 'confirm') toast('Inked. Saved locally; nothing is written to Calendar yet.');
      if (what === 'decline') toast('Declined. The plan re-ran without it.');
    });
  });
  $('sync').onclick = function () {
    if (!api) return;
    var b = this; b.disabled = true; $('src-garmin').innerHTML = '<i></i>Garmin · syncing…';
    api.garmin_sync().then(function (r) { b.disabled = false; toast(r.msg); renderSources(); if (!$('bodyv').hidden) { loadBody(); loadOverview(); } });
  };
  $('cal-connect').onclick = function () {
    if (!api) return;
    var b = this; b.disabled = true; $('src-cal').innerHTML = '<i></i>Calendar · waiting for macOS…';
    api.calendar_connect().then(function (r) {
      b.disabled = false; toast(r.msg); renderSources();
      api.today().then(function (s) { render(s, true); });
    });
  };
  $('reset').onclick = function () { api && api.reset().then(function (s) { render(s, true); toast('Demo reset.'); }); };
  document.querySelectorAll('[data-push]').forEach(function (b) {
    b.onclick = function () { document.querySelectorAll('[data-push]').forEach(function (o) { o.classList.toggle('on', o === b); }); };
  });
  // ---------- Ask drawer ----------
  // A local model answers from a briefing Python builds. Opening the drawer loads the model;
  // nothing runs while it's closed.
  var tier = 'fast', history = [], asking = false, claudeTiers = { haiku: 1, sonnet: 1, opus: 1 };
  try { tier = localStorage.getItem('ask-tier') || 'fast'; } catch (e) {}
  function hello() {
    $('hello').textContent = claudeTiers[tier]
      ? 'Ask anything about your day, week, body numbers or training, or have it schedule something. Claude sees today, the next 7 days of your calendar and the last 3 weeks of body data. Events it proposes wait for your Confirm.'
      : 'Ask about today: your schedule, the weather, or how your body numbers look. Answers come from a model on this Mac.';
    $('q').placeholder = claudeTiers[tier] ? 'Ask Claude, or "add a lift tomorrow at 7"…' : 'Ask about your day…';
  }
  function tierButtons(list) {
    return list.map(function (t) {
      var title = t.backend === 'claude'
        ? (t.installed ? 'Claude ' + t.label + ' (online, via Claude Code)' : 'Claude Code isn\'t installed')
        : t.installed ? 'Qwen3 ' + t.label + ' (' + t.model + ')' : 'Qwen3 ' + t.label + ' isn\'t downloaded (' + t.size + ')';
      return '<button data-tier="' + t.tier + '" data-size="' + esc(t.size || '') + '" data-label="' + esc(t.label) + '" data-backend="' + (t.backend || 'ollama') +
        '" class="' + (t.tier === tier ? 'on' : '') + (t.installed ? '' : ' missing') + '" title="' + esc(title) + '">' + esc(t.label) + '</button>';
    }).join('');
  }
  function renderTiers(list) {
    if (!list.some(function (t) { return t.tier === tier && t.installed; })) tier = 'fast';
    $('tiers').innerHTML = tierButtons(list.filter(function (t) { return t.backend !== 'claude'; }));
    $('ctiers').innerHTML = tierButtons(list.filter(function (t) { return t.backend === 'claude'; }));
    hello();
  }
  function pickTier(e) {
    var b = e.target.closest('button[data-tier]'); if (!b) return;
    if (b.classList.contains('missing')) {
      toast(b.dataset.backend === 'claude' ? 'Claude Code isn\'t installed on this Mac.' : 'Qwen3 ' + b.dataset.label + ' isn\'t downloaded yet (' + b.dataset.size + ').');
      return;
    }
    tier = b.dataset.tier;
    try { localStorage.setItem('ask-tier', tier); } catch (err) {}
    document.querySelectorAll('.pick button').forEach(function (o) { o.classList.toggle('on', o === b); });
    hello();
    api.chat_warm(tier);
  }
  $('tiers').onclick = pickTier; $('ctiers').onclick = pickTier;
  hello();

  // A proposed event in the drawer. Same pencil rule as the timeline: Add writes it, Skip drops it.
  function propWhen(p) {
    var s = new Date(p.start), e = new Date(p.end);
    var day = s.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' });
    return day + ' · ' + clock(s) + '–' + clock(e);
  }
  function propCard(p) {
    var state = p.status === 'added' ? '<span class="state">In your Meliora calendar</span>'
      : p.status === 'skipped' ? '<span class="state">Skipped</span>'
      : '<span class="pa"><button class="y" data-prop="add">Add to calendar</button><button data-prop="skip">Skip</button></span>';
    return '<div class="prop ' + (p.status === 'pending' || !p.status ? 'open' : p.status) + '" data-pid="' + p.id + '"><b>' + esc(p.title) + '</b><span class="when">' + esc(propWhen(p)) + '</span>' +
      (p.location ? '<span class="where"> · ' + esc(p.location) + '</span>' : '') + state + '</div>';
  }
  $('msgs').addEventListener('click', function (e) {
    var b = e.target.closest('button[data-prop]'); if (!b || !api) return;
    var card = b.closest('.prop'); card.querySelectorAll('button').forEach(function (x) { x.disabled = true; });
    api.proposal(+card.dataset.pid, b.dataset.prop).then(function (r) {
      toast(r.msg);
      if (r.proposal) card.outerHTML = propCard(r.proposal);
      else card.querySelectorAll('button').forEach(function (x) { x.disabled = false; });
      api.today().then(function (s) { render(s, true); });
    });
  });
  $('ask').onclick = function () {
    var open = $('drawer').classList.toggle('open');
    if (!open && document.activeElement) document.activeElement.blur();
    if (open && api) { api.chat_models().then(function (list) { renderTiers(list); api.chat_warm(tier); }); renderUsage(); }
    setTimeout(function () { $('q').focus(); }, 220);
  };
  $('close').onclick = function () { document.activeElement && document.activeElement.blur(); $('drawer').classList.remove('open'); };
  // Each question owns its reply bubble, so a late or stopped answer can't land in the wrong place.
  var reqId = 0;
  function fmtK(n) { return n >= 1000 ? (n / 1000).toFixed(1) + 'k' : String(n); }
  function renderUsage() {
    if (!api) return;
    api.claude_usage().then(function (u) {
      $('usage').textContent = u.today_calls ? 'Claude today ' + fmtK(u.today) + ' tok' : '';
      $('usage').title = 'Claude tokens (prompt + reply): ' + fmtK(u.today) + ' today in ' + u.today_calls +
        ' calls, ' + fmtK(u.week) + ' in the last 7 days in ' + u.week_calls + ' calls';
    });
  }
  function setAsking(on) { asking = on; $('stop').hidden = !on; }
  $('stop').onclick = function () {
    if (!asking) return;
    var id = reqId, bubble = $('msgs').querySelector('[data-req="' + id + '"]');
    reqId++;  // the answer, if it still arrives, belongs to no one
    if (bubble) { bubble.classList.remove('pending'); bubble.classList.add('err'); bubble.textContent = 'Stopped.'; }
    setAsking(false);
    api.ask_stop().then(renderUsage);
    $('q').focus();
  };
  $('compose').onsubmit = function (e) {
    e.preventDefault(); var q = $('q').value.trim(); if (!q || !api || asking) return;
    var msgs = $('msgs'), id = ++reqId, isClaude = !!claudeTiers[tier];
    msgs.insertAdjacentHTML('beforeend', '<div class="m u">' + esc(q) + '</div><div class="m a pending" data-req="' + id + '">' +
      (isClaude ? 'Asking Claude…' : 'Thinking…') + '</div>');
    var p = msgs.querySelector('[data-req="' + id + '"]');
    msgs.scrollTop = 1e6;
    $('q').value = ''; setAsking(true);
    api.ask(q, tier, history.slice(-8)).then(function (r) {
      if (id !== reqId) return;  // stopped
      p.classList.remove('pending');
      p.textContent = r.text;
      if (!r.ok) p.classList.add('err');
      else {
        history.push({ role: 'user', content: q }, { role: 'assistant', content: r.text });
        var by = r.model === 'rules' ? 'from the plan, no model' : r.model + ' · ' + (r.ms / 1000).toFixed(1) + ' s';
        if (r.backend === 'claude' && r.tokens_in) by += ' · ' + fmtK(r.tokens_in + (r.tokens_out || 0)) + ' tokens';
        p.insertAdjacentHTML('beforeend', '<span class="by">' + esc(by) + '</span>');
        if (r.proposals && r.proposals.length) {
          p.insertAdjacentHTML('afterend', r.proposals.map(propCard).join(''));
          api.today().then(function (s) { render(s, true); });
        }
      }
      msgs.scrollTop = 1e6;
    }).catch(function (err) {
      if (id !== reqId) return;
      p.classList.remove('pending'); p.classList.add('err'); p.textContent = 'Error: ' + err;
    }).then(function () {
      if (id === reqId) setAsking(false);
      if (isClaude) renderUsage();
    });
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
      var c = src.calendar, ct = c.last_ok && new Date(c.last_ok), clabel, showBtn = true;
      if (c.access === 'granted' && ct) { clabel = clock(ct) + (c.detail ? ' · ' + c.detail : ''); showBtn = false; }
      else if (c.access === 'granted') clabel = 'allowed, not read yet';
      else if (c.access === 'unavailable') { clabel = 'EventKit missing'; showBtn = false; }
      else if (c.access === 'not_asked') clabel = 'not connected';
      else clabel = 'access off';
      $('src-cal').parentNode.className = 'src' + (c.access === 'granted' && ct ? '' : ' off');
      $('src-cal').innerHTML = '<i></i>Calendar · ' + esc(clabel);
      $('cal-connect').hidden = !showBtn;
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
    if (v === 'body') { loadBody(); loadOverview(); }
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
      // VO2 max only changes after a qualifying run, so an older date is normal, not stale.
      var stale = t.day === d.end ? '' : t.metric === 'vo2max'
        ? '<span class="d">from your ' + esc(Charts.shortDate(t.day)) + ' run</span>'
        : '<span class="asof">as of ' + esc(Charts.shortDate(t.day)) + '</span>';
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

  // ---------- Body overview (left column) ----------
  // Python picks every fact; the on-device model only writes the top line. The facts render
  // instantly, and the model's line replaces the plain one when it's ready.
  var ovSeq = 0;
  function byLine(h) {
    if (h.pending) return 'Writing on-device…';
    if (h.by === 'plain') return h.offline ? 'Plain summary · on-device model is off' : 'Plain summary';
    return 'Written on-device · ' + h.by;
  }
  function setHeadline(h) {
    var line = $('ov-line'); if (!line) return;
    if (line.textContent === h.text) { $('ov-by').textContent = byLine(h); return; }
    line.classList.add('fading');
    setTimeout(function () { line.textContent = h.text; $('ov-by').textContent = byLine(h); line.classList.remove('fading'); }, 200);
  }
  function loadOverview() {
    if (!api) return;
    var seq = ++ovSeq;
    api.body_overview().then(function (o) {
      if (seq !== ovSeq) return;
      renderOverview(o);
      if (o.headline && o.headline.pending) api.body_headline().then(function (h) { if (seq === ovSeq) setHeadline(h); });
    });
  }
  function renderOverview(o) {
    var el = $('ov');
    if (o.empty) { el.innerHTML = '<div class="ov-h"><b>Overview</b></div><p class="ov-empty">No body data yet.</p>'; return; }
    var rows = o.rows.map(function (r) {
      return '<li class="' + r.tone + '"><i></i><div><div class="ov-top"><b>' + esc(r.label) + '</b><span class="w">' + esc(r.word) + '</span></div>' +
        '<div class="v">' + esc(r.value) + '</div><div class="ov-sub">' + esc(r.receipt) +
        (r.as_of ? (r.receipt ? ' · ' : '') + '<span class="asof">as of ' + esc(r.as_of) + '</span>' : '') + '</div></div></li>';
    }).join('');
    var std = o.standouts.map(function (s) {
      return '<li class="std ' + s.tone + '"><i></i><div><div class="t">' + esc(s.title) + '</div><div class="ov-sub">' + esc(s.value) +
        ' · ' + esc(s.day) + (s.detail ? ' · ' + esc(s.detail) : '') + '</div></div></li>';
    }).join('');
    el.innerHTML = '<div class="ov-h"><b>Overview</b><span>' + (o.source === 'sample' ? 'sample · ' : '') + 'as of ' + esc(o.as_of) + '</span></div>' +
      '<p class="ov-line" id="ov-line">' + esc(o.headline.text) + '</p><div class="ov-by" id="ov-by">' + esc(byLine(o.headline)) + '</div>' +
      '<h4>Right now</h4><ul>' + rows + '</ul>' + (std ? '<h4>Stand-outs</h4><ul>' + std + '</ul>' : '');
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
