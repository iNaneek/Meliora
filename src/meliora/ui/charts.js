// Tiny SVG charts for the Body view. No libraries (offline), no animation (battery).
// Colors come from CSS variables, so charts flip with the sky like everything else.
// Every chart also has a table twin (see Charts.table) so no value is hover-only.
(function () {
  var NS = 'http://www.w3.org/2000/svg';
  var PLOT_H = 150, AXIS_H = 22, PAD_L = 34, PAD_R = 58, PAD_T = 18;

  function el(tag, attrs, parent) {
    var e = document.createElementNS(NS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  // Axis range on clean steps (1, 2, 2.5, 5 × 10^n), about 4 gridlines.
  function niceStep(x) {
    var p = Math.pow(10, Math.floor(Math.log10(x))), n = x / p;
    return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p;
  }
  function scale(lo, hi, zero) {
    if (zero) lo = 0; else { var pad = Math.max(1, (hi - lo) * 0.1); lo -= pad; hi += pad; }
    var step = niceStep((hi - lo) / 4 || 1);
    lo = Math.floor(lo / step) * step; hi = Math.ceil(hi / step) * step;
    if (hi <= lo) hi = lo + step;
    return { lo: lo, hi: hi, n: Math.round((hi - lo) / step) };
  }
  function tickFmt(v) { return String(+v.toFixed(2)); }
  function dayIndex(iso, start) { return Math.round((new Date(iso + 'T12:00') - new Date(start + 'T12:00')) / 864e5); }
  function shortDate(iso) { return new Date(iso + 'T12:00').toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); }

  // ---------- shared tooltip ----------
  var tip;
  function showTip(host, x, y, title, rows) {
    if (!tip) { tip = document.createElement('div'); tip.className = 'ctip'; document.body.appendChild(tip); }
    tip.textContent = '';
    var t = document.createElement('div'); t.className = 'ctip-t'; t.textContent = title; tip.appendChild(t);
    rows.forEach(function (r) {
      var row = document.createElement('div'); row.className = 'ctip-r';
      if (r.cls) { var k = document.createElement('i'); k.className = 'key ' + r.cls; row.appendChild(k); }
      var v = document.createElement('b'); v.textContent = r.value; row.appendChild(v);
      var n = document.createElement('span'); n.textContent = r.name; row.appendChild(n);
      tip.appendChild(row);
    });
    var box = host.getBoundingClientRect();
    tip.style.display = 'block';
    var left = box.left + x + 14, w = tip.offsetWidth;
    if (left + w > window.innerWidth - 8) left = box.left + x - w - 14;
    tip.style.left = left + 'px';
    tip.style.top = Math.max(8, box.top + y - tip.offsetHeight / 2) + 'px';
  }
  function hideTip() { if (tip) tip.style.display = 'none'; }

  function frame(host) {
    host.textContent = '';
    var W = Math.max(260, host.clientWidth), H = PAD_T + PLOT_H + AXIS_H;
    var svg = el('svg', { width: W, height: H, viewBox: '0 0 ' + W + ' ' + H, class: 'chart' }, host);
    return { svg: svg, W: W, H: H, x0: PAD_L, x1: W - PAD_R, y0: PAD_T, y1: PAD_T + PLOT_H };
  }
  function grid(f, lo, hi, ticks, fmt) {
    fmt = fmt || tickFmt;
    for (var i = 0; i <= ticks; i++) {
      var v = lo + (hi - lo) * i / ticks, y = f.y1 - (v - lo) / (hi - lo) * PLOT_H;
      el('line', { x1: f.x0, x2: f.x1, y1: y, y2: y, class: i === 0 ? 'axis' : 'grid' }, f.svg);
      el('text', { x: f.x0 - 6, y: y + 3.5, class: 'tick', 'text-anchor': 'end' }, f.svg).textContent = fmt(v);
    }
  }

  // ---------- stacked columns ----------
  // rows: [{label, title, segs: {key: value}}], keys: [{key, name, cls}]
  function columns(host, rows, keys, opts) {
    var f = frame(host), n = rows.length;
    var totals = rows.map(function (r) { return keys.reduce(function (s, k) { return s + (r.segs[k.key] || 0); }, 0); });
    var sc = scale(0, Math.max.apply(null, totals.concat([opts.minMax || 1])), true), max = sc.hi;
    grid(f, 0, max, sc.n);
    var band = (f.x1 - f.x0) / n, bw = Math.min(24, band * 0.6);
    rows.forEach(function (r, i) {
      var cx = f.x0 + band * (i + 0.5), y = f.y1, segsDrawn = [];
      keys.forEach(function (k) {
        var v = r.segs[k.key] || 0; if (!v) return;
        var h = v / max * PLOT_H; segsDrawn.push({ k: k, y: y - h, h: h }); y -= h;
      });
      segsDrawn.forEach(function (s, j) {
        var top = j === segsDrawn.length - 1, gap = j > 0 ? 2 : 0, h = Math.max(0, s.h - gap), x = cx - bw / 2;
        if (top && h > 4) {  // 4px rounded data end, square at the baseline
          el('path', { class: 'mark ' + s.k.cls, d: 'M' + x + ',' + (s.y + h) + 'V' + (s.y + 4) + 'q0,-4 4,-4h' + (bw - 8) +
            'q4,0 4,4V' + (s.y + h) + 'Z' }, f.svg);
        } else el('rect', { class: 'mark ' + s.k.cls, x: x, y: s.y, width: bw, height: h }, f.svg);
      });
      if (totals[i] > 0 && (opts.labelAll || i === n - 1 || totals[i] === Math.max.apply(null, totals))) {
        el('text', { x: cx, y: y - 5, class: 'val', 'text-anchor': 'middle' }, f.svg).textContent = opts.fmt(totals[i]);
      }
      if (i % Math.ceil(n / 7) === 0 || i === n - 1)
        el('text', { x: cx, y: f.y1 + 15, class: 'tick', 'text-anchor': 'middle' }, f.svg).textContent = r.label;
      var hit = el('rect', { class: 'hit', x: cx - band / 2, y: f.y0, width: band, height: PLOT_H, tabindex: 0 }, f.svg);
      var show = function () {
        showTip(host, cx, f.y0 + PLOT_H / 2, r.title, keys.map(function (k) {
          return { cls: k.cls, value: opts.fmt(r.segs[k.key] || 0), name: k.name };
        }).concat(r.extra || []));
      };
      hit.addEventListener('pointermove', show); hit.addEventListener('focus', show);
      hit.addEventListener('pointerleave', hideTip); hit.addEventListener('blur', hideTip);
    });
  }

  // ---------- lines over days ----------
  // points: [{day, ...values}], series: [{key, name, cls, kind: 'line'|'dots'}]; gaps in days break the line
  function lines(host, points, series, opts) {
    var f = frame(host), start = opts.start, span = Math.max(1, dayIndex(opts.end, start));
    var vals = [];
    points.forEach(function (p) { series.forEach(function (s) { if (p[s.key] != null) vals.push(p[s.key]); }); });
    if (!vals.length) { host.textContent = 'No data in this range.'; return; }
    var sc = scale(Math.min.apply(null, vals), Math.max.apply(null, vals), opts.zero), r = [sc.lo, sc.hi];
    grid(f, r[0], r[1], sc.n, opts.tick && function (v) { return opts.tick(tickFmt(v)); });
    if (opts.ref != null) {
      var ry = f.y1 - (opts.ref - r[0]) / (r[1] - r[0]) * PLOT_H;
      el('line', { x1: f.x0, x2: f.x1, y1: ry, y2: ry, class: 'ref' }, f.svg);
      el('text', { x: f.x0 + 4, y: ry - 4, class: 'tick' }, f.svg).textContent = opts.refLabel;
    }
    var X = function (d) { return f.x0 + dayIndex(d, start) / span * (f.x1 - f.x0); };
    var Y = function (v) { return f.y1 - (v - r[0]) / (r[1] - r[0]) * PLOT_H; };
    series.forEach(function (s) {
      var pts = points.filter(function (p) { return p[s.key] != null; });
      if (s.kind === 'dots') {
        pts.forEach(function (p) { el('circle', { cx: X(p.day), cy: Y(p[s.key]), r: 2.5, class: 'dot ' + s.cls }, f.svg); });
        return;
      }
      var d = '', prev = null;
      pts.forEach(function (p) {
        var gap = prev && dayIndex(p.day, prev.day) > 2;
        d += (d && !gap ? 'L' : 'M') + X(p.day).toFixed(1) + ',' + Y(p[s.key]).toFixed(1);
        prev = p;
      });
      el('path', { d: d, class: 'line ' + s.cls }, f.svg);
      var last = pts[pts.length - 1];
      if (last && s.endLabel !== false) {
        el('circle', { cx: X(last.day), cy: Y(last[s.key]), r: 4, class: 'end ' + s.cls }, f.svg);
        el('text', { x: X(last.day) + 7, y: Y(last[s.key]) + 3.5, class: 'val' }, f.svg).textContent = opts.fmt(last[s.key]);
      }
    });
    // x labels: first, middle, last
    [start, points[Math.floor(points.length / 2)] && points[Math.floor(points.length / 2)].day, opts.end].forEach(function (d, i) {
      if (!d) return;
      el('text', { x: X(d), y: f.y1 + 15, class: 'tick', 'text-anchor': i === 0 ? 'start' : i === 2 ? 'end' : 'middle' }, f.svg).textContent = shortDate(d);
    });
    // crosshair snaps to the nearest day that has data
    var cross = el('line', { y1: f.y0, y2: f.y1, class: 'cross', visibility: 'hidden' }, f.svg);
    var hit = el('rect', { class: 'hit', x: f.x0, y: f.y0, width: f.x1 - f.x0, height: PLOT_H, tabindex: 0 }, f.svg);
    var focusIdx = points.length - 1;
    function at(i) {
      var p = points[i]; if (!p) return;
      var x = X(p.day); cross.setAttribute('x1', x); cross.setAttribute('x2', x); cross.setAttribute('visibility', 'visible');
      showTip(host, x, f.y0 + PLOT_H / 2, shortDate(p.day), series.map(function (s) {
        return { cls: s.cls, value: p[s.key] == null ? '—' : opts.fmt(p[s.key]), name: s.name };
      }).concat(opts.extra ? opts.extra(p) : []));
    }
    hit.addEventListener('pointermove', function (e) {
      var bx = host.getBoundingClientRect().left, best = 0, bd = 1e9;
      points.forEach(function (p, i) { var dd = Math.abs(X(p.day) - (e.clientX - bx)); if (dd < bd) { bd = dd; best = i; } });
      focusIdx = best; at(best);
    });
    hit.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowLeft') focusIdx = Math.max(0, focusIdx - 1);
      else if (e.key === 'ArrowRight') focusIdx = Math.min(points.length - 1, focusIdx + 1);
      else return;
      e.preventDefault(); at(focusIdx);
    });
    hit.addEventListener('focus', function () { at(focusIdx); });
    var off = function () { cross.setAttribute('visibility', 'hidden'); hideTip(); };
    hit.addEventListener('pointerleave', off); hit.addEventListener('blur', off);
  }

  // ---------- sparkline (tiles) ----------
  function spark(values) {
    if (values.length < 2) return '';
    var w = 84, h = 22, lo = Math.min.apply(null, values), hi = Math.max.apply(null, values), rg = hi - lo || 1;
    var pts = values.map(function (v, i) { return [(i / (values.length - 1) * (w - 6) + 1).toFixed(1), (h - 3 - (v - lo) / rg * (h - 6)).toFixed(1)]; });
    var last = pts[pts.length - 1];
    return '<svg class="spark" width="' + w + '" height="' + h + '" aria-hidden="true"><polyline points="' +
      pts.map(function (p) { return p.join(','); }).join(' ') + '"/><circle cx="' + last[0] + '" cy="' + last[1] + '" r="2.5"/></svg>';
  }

  // ---------- table twin ----------
  // cols: [{name, get(row) → string}]
  function table(host, rows, cols) {
    host.textContent = '';
    var t = document.createElement('table'); t.className = 'dtable';
    var hr = t.createTHead().insertRow();
    cols.forEach(function (c) { var th = document.createElement('th'); th.textContent = c.name; hr.appendChild(th); });
    var tb = t.createTBody();
    rows.forEach(function (r) {
      var tr = tb.insertRow();
      cols.forEach(function (c) { tr.insertCell().textContent = c.get(r); });
    });
    host.appendChild(t);
  }

  window.Charts = { columns: columns, lines: lines, spark: spark, table: table, hideTip: hideTip, shortDate: shortDate };
})();
