// Front end. All decisions come from Python (pywebview.api); JS only draws them.
(function () {
  var $ = function (id) { return document.getElementById(id); };
  var api = null, state = null;
  var START = 7, END = 23.4;

  function fmt(h) {
    var hh = Math.floor(h), mm = Math.round((h - hh) * 60);
    return ((hh + 11) % 12 + 1) + ':' + (mm < 10 ? '0' : '') + mm;
  }
  function esc(s) { var d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

  function toast(msg) {
    var t = $('toast'); t.textContent = msg; t.classList.add('show');
    clearTimeout(toast.h); toast.h = setTimeout(function () { t.classList.remove('show'); }, 2600);
  }

  // ---------- render from Python state ----------
  function render(s, animate) {
    var changed = !state || state.sentence !== s.sentence;
    state = s;
    var draw = function () {
      $('date').textContent = s.date;
      $('sentence').innerHTML = s.sentence;  // trusted: built by rules.py
      $('because').innerHTML = 'because ' + s.because.map(function (c) {
        return '<span class="chip">' + esc(c) + '</span>';
      }).join('');
      renderNext(s.next);
      ['sentence', 'because', 'next'].forEach(function (id) { $(id).classList.remove('fading'); });
    };
    if (animate && changed) {
      ['sentence', 'because', 'next'].forEach(function (id) { $(id).classList.add('fading'); });
      setTimeout(draw, 180);
    } else draw();
    renderDay(s);
    renderJob(s.job);
    $('pendcount').textContent = s.pending ? s.pending + ' pencil' : '';
  }

  function renderNext(n) {
    var el = $('next');
    if (!n) { el.innerHTML = '<div class="lbl">Next</div><div class="what">Nothing left today</div><div class="meta">The rest window is yours.</div>'; return; }
    var acts = n.pencil
      ? '<button class="tbtn primary" data-act="confirm">Confirm</button><button class="tbtn" data-act="decline">Not this</button>'
      : '<button class="tbtn primary" data-act="start">Start</button>';
    el.innerHTML = '<div class="lbl">' + esc(n.label) + '</div><div class="what">' + esc(n.what) +
      '</div><div class="meta">' + esc(n.meta) + '</div><div class="acts">' + acts + '</div>';
    el.dataset.id = (state.blocks.filter(function (b) { return b.title === n.what; })[0] || {}).id || '';
  }

  function renderDay(s) {
    var day = $('day'), H = day.clientHeight || 400, px = H / (END - START);
    var y = function (t) { return (t - START) * px; };
    day.innerHTML = '';
    for (var h = START; h < END; h += 2) {
      var r = document.createElement('div'); r.className = 'hr'; r.style.top = y(h) + 'px';
      r.innerHTML = '<span>' + ((h + 11) % 12 + 1) + (h >= 12 ? 'p' : 'a') + '</span>'; day.appendChild(r);
    }
    s.blocks.forEach(function (b) {
      var el = document.createElement('div');
      el.className = 'blk ' + b.kind + (b.decision === 'decline' ? ' declined' : '');
      el.style.top = (y(b.start) + 1) + 'px';
      el.style.height = Math.max(y(b.end) - y(b.start) - 2, 14) + 'px';
      el.dataset.id = b.id;
      var inner = b.kind === 'pen' ? '<span class="tag">' + (b.decision === 'decline' ? 'Declined' : 'Pencil') + '</span>' : '';
      inner += '<span class="tm">' + fmt(b.start) + '</span><b style="font-weight:600">' + esc(b.title) + '</b><span class="sub">' + esc(b.sub) + '</span>';
      if (b.kind === 'pen') inner += '<span class="pa"><button class="y" data-act="confirm">Confirm</button><button data-act="decline">Decline</button><button class="undo" data-act="undo">Undo</button></span>';
      el.innerHTML = inner; day.appendChild(el);
    });
    if (s.now >= START && s.now <= END) {
      var now = document.createElement('div'); now.className = 'now'; now.style.top = y(s.now) + 'px'; day.appendChild(now);
    }
  }

  function renderJob(j) {
    var booked = j.state === 'confirm';
    $('jobnum').textContent = j.done; $('jobtgt').textContent = j.target;
    $('jobdone').style.width = (j.done / j.target * 100) + '%';
    var p = $('jobpen');
    p.style.width = (j.extra / j.target * 100) + '%';
    p.style.background = booked ? 'var(--violet)' : 'var(--gold)';
    p.style.opacity = booked ? '.55' : '.6';
    $('jobpenlbl').textContent = j.extra ? '+' + j.extra + ' h ' + (booked ? 'booked' : 'pencilled') : 'no job block today';
    $('jobpenlbl').style.color = booked ? 'var(--violet)' : 'var(--gold)';
  }

  // ---------- actions → Python ----------
  function act(id, what) {
    if (what === 'start') { toast('Timers come later. For now: go.'); return; }
    var call = what === 'undo' ? api.undo(id) : api.decide(id, what);
    call.then(function (s) {
      render(s, true);
      if (what === 'confirm') toast('Inked. Saved locally; nothing is written to Calendar yet.');
      if (what === 'decline') toast('Declined. The plan re-ran without it.');
    });
  }

  document.addEventListener('click', function (e) {
    var b = e.target.closest('button[data-act]'); if (!b || !api) return;
    var host = b.closest('[data-id]'); act(host && host.dataset.id, b.dataset.act);
  });

  $('reset').onclick = function () { api && api.reset().then(function (s) { render(s, true); toast('Demo reset.'); }); };
  document.querySelectorAll('[data-push]').forEach(function (b) {
    b.onclick = function () { document.querySelectorAll('[data-push]').forEach(function (o) { o.classList.toggle('on', o === b); }); };
  });
  $('feel').addEventListener('click', function (e) {
    if (e.target.tagName !== 'BUTTON') return;
    this.querySelectorAll('button').forEach(function (o) { o.classList.toggle('on', o === e.target); });
  });
  $('sw').onclick = function () {
    var on = this.getAttribute('aria-pressed') !== 'true'; this.setAttribute('aria-pressed', on);
    $('roast').hidden = !on; $('swl').textContent = on ? 'Roast on (opted in)' : 'Roast off until you opt in';
  };
  $('ask').onclick = function () { $('drawer').classList.toggle('open'); setTimeout(function () { $('q').focus(); }, 200); };
  $('close').onclick = function () { $('drawer').classList.remove('open'); };
  $('theme').onclick = function () {
    var r = document.documentElement;
    var cur = r.getAttribute('data-theme') || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    r.setAttribute('data-theme', cur === 'dark' ? 'light' : 'dark');
  };
  $('compose').onsubmit = function (e) {
    e.preventDefault(); var q = $('q').value.trim(); if (!q || !api) return;
    var msgs = $('msgs');
    msgs.insertAdjacentHTML('beforeend', '<div class="m u">' + esc(q) + '</div><div class="m a pending">…</div>');
    $('q').value = '';
    api.ask(q).then(function (a) { var p = msgs.querySelector('.pending'); p.textContent = a; p.classList.remove('pending'); msgs.scrollTop = 1e6; });
  };

  // ---------- demo horizon ----------
  var load = [2, 2, 3, 2, 3, 1, 1, 2, 3, 3, 2, 2, 1, 1, 4, 4, 3, 5, 5, 1, 1];
  var monday = new Date(); monday.setDate(monday.getDate() - (monday.getDay() + 6) % 7);
  var todayIdx = (new Date().getDay() + 6) % 7;
  load.forEach(function (v, i) {
    var d = document.createElement('div'); d.className = 'd';
    if (i % 7 >= 5) d.className += ' wk'; else if (v >= 4) d.className += ' crunch'; else if (v >= 2) d.className += ' l' + v;
    if (i === todayIdx) d.className += ' today';
    d.style.height = (10 + v * 7) + 'px'; $('days').appendChild(d);
  });
  $('wkl').innerHTML = [0, 7, 14].map(function (k) {
    var d = new Date(monday); d.setDate(d.getDate() + k);
    return '<span>' + d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }) + '</span>';
  }).join('');

  // ---------- boot ----------
  function boot() {
    api = window.pywebview.api;
    api.today().then(function (s) { render(s, false); $('bridge').innerHTML = '<i></i>Python bridge ok'; })
      .catch(function (err) { $('sentence').textContent = 'Python bridge error: ' + err; });
    setInterval(function () { api.today().then(function (s) { render(s, true); }); }, 60000);
    new ResizeObserver(function () { state && renderDay(state); }).observe($('day'));
  }
  if (window.pywebview && window.pywebview.api) boot();
  else window.addEventListener('pywebviewready', boot);
})();
