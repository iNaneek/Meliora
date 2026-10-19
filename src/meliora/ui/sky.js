// Sky engine: sun elevation over Golden, CO → sky gradient, accents, and ink colors.
// Pure presentation. Exposes window.Sky = { elevation, paint, phaseName, sunTimes }.
(function () {
  var LAT = 39.7555, LON = -105.2211;
  var rad = Math.PI / 180;

  // Sun elevation in degrees, plus whether it's rising (morning side of solar noon).
  function elevation(date) {
    var start = Date.UTC(date.getUTCFullYear(), 0, 0);
    var n = Math.floor((date - start) / 864e5);
    var decl = -23.44 * Math.cos(2 * Math.PI / 365 * (n + 10));
    var B = 2 * Math.PI * (n - 81) / 364;
    var eot = 9.87 * Math.sin(2 * B) - 7.53 * Math.cos(B) - 1.5 * Math.sin(B);
    var utcMin = date.getUTCHours() * 60 + date.getUTCMinutes() + date.getUTCSeconds() / 60;
    var solarMin = utcMin + LON * 4 + eot;
    var hour = ((solarMin / 60 - 12) * 15 + 540) % 360 - 180;  // hour angle, -180..180
    var s = Math.sin(LAT * rad) * Math.sin(decl * rad) +
            Math.cos(LAT * rad) * Math.cos(decl * rad) * Math.cos(hour * rad);
    return { el: Math.asin(s) / rad, rising: hour < 0, hour: hour };
  }

  function sunTimes(day) {
    var d = new Date(day); d.setHours(0, 0, 0, 0);
    var prev = elevation(d).el, out = {};
    for (var m = 1; m < 1440; m++) {
      var t = new Date(d.getTime() + m * 6e4), e = elevation(t).el;
      if (prev < 0 && e >= 0) out.rise = t;
      if (prev >= 0 && e < 0) out.set = t;
      prev = e;
    }
    return out;
  }

  // Phase anchors: [elevation, sky top, sky bottom]. Colors interpolate between neighbours.
  var NIGHT = [-24, '#0B1026', '#121C33'], TWI = [-12, '#14214A', '#2E3A6B'], NOON = [30, '#2F7FD1', '#A9D6F2'];
  var RISE = [NIGHT, TWI, [-3, '#3A4A8C', '#C88BB0'], [3, '#8FA7D6', '#F7C6B0'], [13, '#7FB8E6', '#DDEFF7'], NOON];
  var SET = [NIGHT, TWI, [-3, '#45407F', '#D9909E'], [3, '#4A3F86', '#F08A5D'], [13, '#6FA3D8', '#E9C48A'], NOON];

  function phaseName(el, rising) {
    if (el < -18) return 'Night';
    if (el < -6) return 'Twilight';
    if (el < 0) return rising ? 'Blue hour' : 'Dusk';
    if (el < 6) return rising ? 'Alpenglow' : 'Sunset';
    if (el < 20) return rising ? 'Morning' : 'Golden hour';
    return 'Midday';
  }

  // ---------- color helpers ----------
  function hex(h) { return [1, 3, 5].map(function (i) { return parseInt(h.slice(i, i + 2), 16); }); }
  function css(c) { return 'rgb(' + c.map(Math.round).join(',') + ')'; }
  function mix(a, b, t) { return a.map(function (v, i) { return v + (b[i] - v) * t; }); }
  function lum(c) {
    var l = c.map(function (v) { v /= 255; return v <= .03928 ? v / 12.92 : Math.pow((v + .055) / 1.055, 2.4); });
    return .2126 * l[0] + .7152 * l[1] + .0722 * l[2];
  }
  function clamp(x) { return Math.max(0, Math.min(1, x)); }
  function tri(x, a, peak, b) { return x <= peak ? clamp((x - a) / (peak - a)) : clamp((b - x) / (b - peak)); }

  function skyColors(el, rising) {
    var A = rising ? RISE : SET, e = Math.max(-24, Math.min(30, el));
    for (var i = 0; i < A.length - 1; i++) {
      if (e <= A[i + 1][0]) {
        var t = (e - A[i][0]) / (A[i + 1][0] - A[i][0]);
        return { top: mix(hex(A[i][1]), hex(A[i + 1][1]), t), bottom: mix(hex(A[i][2]), hex(A[i + 1][2]), t) };
      }
    }
    return { top: hex(NOON[1]), bottom: hex(NOON[2]) };
  }

  // ---------- paint ----------
  var $ = function (id) { return document.getElementById(id); };

  function paint(date) {
    var s = elevation(date), el = s.el, c = skyColors(el, s.rising), root = document.documentElement.style;
    $('sky').style.background = 'linear-gradient(to bottom,' + css(c.top) + ',' + css(c.bottom) + ')';

    // Glass and ink flip with how bright the sky is.
    var light = (lum(c.top) + lum(c.bottom)) / 2 > .34;
    document.documentElement.dataset.ink = light ? 'light' : 'dark';
    // Text sitting straight on the sky (the Sentence) picks whichever ink contrasts more.
    var behind = mix(c.top, c.bottom, .35), L = lum(behind);
    root.setProperty('--sky-ink', (1.05 / (L + .05)) > ((L + .05) / .06) ? '#FFFFFF' : '#0F1424');

    // Accents, each with a weight from 0 to 1.
    var night = clamp((-12 - el) / 6);
    $('aurora').style.opacity = night;
    $('stars').style.opacity = clamp((-3 - el) / 12);
    var belt = tri(el, -7, -3, 1);
    $('belt').style.opacity = belt * (s.rising ? .55 : .65);
    $('belt').style.setProperty('--belt', s.rising ? '200,139,176' : '228,150,170');
    $('glow').style.opacity = s.rising ? 0 : tri(el, 1, 9, 22) * .55;

    // Ridge: hazy by day, lit at alpenglow, dark at sunset.
    var far = mix(c.bottom, hex('#1B2238'), .5), near = mix(c.bottom, hex('#0D1222'), .74);
    var dark = s.rising ? 0 : tri(el, -5, 2, 9);
    near = mix(near, hex('#0E0B1A'), dark * .85); far = mix(far, hex('#1A1530'), dark * .7);
    $('ridge-far').setAttribute('fill', css(far));
    $('ridge-near').setAttribute('fill', css(near));
    $('ridge-lit').style.opacity = s.rising ? tri(el, -1.5, 3, 8.5) : 0;

    // Sun disk travels east→west and sinks behind the ridge.
    var sun = $('sun'), H = $('sky').clientHeight, W = $('sky').clientWidth;
    // Keep its path inside the open sky between the sidebar and the agenda.
    sun.style.left = (W * (.27 + clamp((s.hour + 100) / 200) * .4)) + 'px';
    sun.style.top = (H * .82 - (el / 42) * H * .7) + 'px';
    sun.style.opacity = clamp((el + 4) / 5);
    var warm = clamp(1 - el / 14);
    sun.style.setProperty('--sun', css(mix(hex('#FFF7E0'), hex('#FFB36B'), warm)));

    return { el: el, rising: s.rising, phase: phaseName(el, s.rising), bottom: c.bottom };
  }

  // A strip of the whole day's horizon colors, for the slider track.
  function dayStrip(day) {
    var d = new Date(day); d.setHours(0, 0, 0, 0);
    var stops = [];
    for (var m = 0; m <= 1440; m += 30) {
      var s = elevation(new Date(d.getTime() + m * 6e4)), c = skyColors(s.el, s.rising);
      stops.push(css(mix(c.top, c.bottom, .55)) + ' ' + (m / 14.4).toFixed(1) + '%');
    }
    return 'linear-gradient(to right,' + stops.join(',') + ')';
  }

  // Stars, scattered once with a fixed seed so they don't jump between launches.
  function scatterStars() {
    var svg = $('stars'), seed = 7, out = '';
    var rnd = function () { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    for (var i = 0; i < 110; i++) {
      var r = rnd() < .12 ? 1.4 : .8;
      out += '<circle cx="' + (rnd() * 100).toFixed(2) + '%" cy="' + (rnd() * 62).toFixed(2) + '%" r="' + r +
        '" style="animation-delay:-' + (rnd() * 6).toFixed(1) + 's"/>';
    }
    svg.innerHTML = out;
  }

  window.Sky = { elevation: elevation, paint: paint, phaseName: phaseName, sunTimes: sunTimes,
                 dayStrip: dayStrip, scatterStars: scatterStars };
})();
