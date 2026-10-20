/* GOOD HEALTH HOSPITAL: shared page behaviour. Plain JavaScript, no libraries. Loaded on every page. */
(function () {
  var d = document, root = d.documentElement;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var viewTransitions = 'onpagereveal' in window;   // browser animates page changes itself
  var bar = null, leaveTimer = null;

  function each(list, fn) { Array.prototype.forEach.call(list, fn); }
  function ready(fn) { if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', fn); else fn(); }

  function resetLeave() {
    d.body.classList.remove('leaving');
    if (bar) bar.classList.remove('on');
    each(d.querySelectorAll('button.loading'), function (b) { b.classList.remove('loading'); });
    clearTimeout(leaveTimer);
  }
  function showBar() {
    if (bar) bar.classList.add('on');
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(resetLeave, 8000);   // downloads never leave the page, so undo after a while
  }

  ready(function () {
    var body = d.body, main = d.querySelector('main');
    bar = d.getElementById('loadBar');

    /* 1. highlight the current menu item (longest matching address wins) */
    var links = d.querySelectorAll('.nav-link'), best = null, bestLen = -1, path = location.pathname;
    each(links, function (a, i) {
      a.style.setProperty('--i', Math.min(i, 24));
      var p = a.pathname, prefix = p.charAt(p.length - 1) === '/' ? p : p + '/';
      var hit = p === path || (p.length > 1 && path.indexOf(prefix) === 0);
      if (hit && p.length > bestLen) { best = a; bestLen = p.length; }
    });
    if (best) { best.classList.add('active'); best.setAttribute('aria-current', 'page'); }

    if (main) {
      /* 2. wrap bare tables so wide ones scroll sideways instead of breaking the page */
      each(main.querySelectorAll('table'), function (t) {
        if (t.closest('.table-wrap, .wrap')) return;
        var w = d.createElement('div'); w.className = 'table-wrap';
        t.parentNode.insertBefore(w, t); w.appendChild(t);
      });

      /* 3. staggered entrance: page blocks, stat tiles, table rows */
      each(main.children, function (k, i) { k.style.setProperty('--i', Math.min(i, 10)); });
      each(main.querySelectorAll('.stat-grid'), function (g) {
        each(g.children, function (k, i) { k.style.setProperty('--i', Math.min(i, 12)); });
      });
      each(main.querySelectorAll('table'), function (t) {
        each(t.querySelectorAll('tr'), function (tr, i) { tr.style.setProperty('--r', Math.min(i, 24)); });
      });

      /* 4. turn plain status words into coloured badges */
      var tones = {
        ok: ['completed', 'dispensed', 'released', 'approved', 'present', 'active', 'resolved', 'handled', 'paid'],
        info: ['scheduled', 'prescribed', 'assigned', 'open', 'pending', 'in treatment', 'new', 'submitted', 'admitted', 'in progress', 'on duty', 'waiting', 'waiting to be dispensed'],
        warn: ['partly dispensed', 'late', 'in review', 'awaiting', 'processing', 'under review', 'low stock'],
        bad: ['cancelled', 'canceled', 'rejected', 'no-show', 'no show', 'absent', 'expired', 'declined', 'failed', 'overdue'],
        neutral: ['closed', 'inactive', 'discharged', 'archived', 'withdrawn']
      };
      var toneOf = {};
      Object.keys(tones).forEach(function (t) { tones[t].forEach(function (w) { toneOf[w] = t; }); });
      each(main.querySelectorAll('td, .status'), function (el) {
        if (el.children.length) return;
        var text = el.textContent.trim(), tone = toneOf[text.toLowerCase()];
        if (!tone) return;
        el.innerHTML = '';
        var s = d.createElement('span'); s.className = 'badge ' + tone; s.textContent = text; el.appendChild(s);
      });

      /* 5. red style for buttons that undo something */
      each(main.querySelectorAll('button, input[type=submit]'), function (b) {
        if (/\b(cancel|remove|delete|reject|withdraw|discharge)/i.test(b.textContent + ' ' + (b.value || ''))) b.classList.add('danger');
      });

      /* 6. number count-up: any element with data-count, .countup, .stat-number or .big-number */
      each(main.querySelectorAll('[data-count], .countup, .stat-number, .big-number'), function (el) {
        var finalText = el.textContent.trim();
        var raw = (el.getAttribute('data-count') || finalText).replace(/,/g, '');
        if (!/^-?\d+(\.\d+)?$/.test(raw) || reduce) return;
        var target = parseFloat(raw), dec = (raw.split('.')[1] || '').length;
        var commas = finalText.indexOf(',') > -1 || Math.abs(target) >= 10000;
        function fmt(v) { return commas ? v.toLocaleString(undefined, { minimumFractionDigits: dec, maximumFractionDigits: dec }) : v.toFixed(dec); }
        el.textContent = fmt(0);
        function run() {
          var start = null, dur = 1200;
          function step(ts) {
            if (start === null) start = ts;
            var p = Math.min((ts - start) / dur, 1), e = 1 - Math.pow(1 - p, 3);
            el.textContent = p < 1 ? fmt(target * e) : finalText;
            if (p < 1) requestAnimationFrame(step);
          }
          requestAnimationFrame(step);
        }
        if ('IntersectionObserver' in window) {
          var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (en) { if (en.isIntersecting) { io.disconnect(); run(); } });
          }, { threshold: .3 });
          io.observe(el);
        } else run();
      });
    }

    var first = d.querySelector('.auth-card input:not([type=hidden])');
    if (first) first.focus();

    /* 7. toasts: auto-dismiss, close button, pause while hovered */
    each(d.querySelectorAll('.toast'), function (t) {
      var life = t.classList.contains('error') ? 9000 : 6000, timer;
      t.style.setProperty('--life', life + 'ms');
      function close() { clearTimeout(timer); t.classList.add('out'); setTimeout(function () { t.remove(); }, 380); }
      function arm(ms) { clearTimeout(timer); timer = setTimeout(close, ms); }
      var x = t.querySelector('.toast-x'); if (x) x.addEventListener('click', close);
      t.addEventListener('mouseenter', function () { clearTimeout(timer); });
      t.addEventListener('mouseleave', function () { arm(2500); });
      arm(life);
    });

    /* 8. sidebar: phone drawer and desktop collapse */
    var toggle = d.getElementById('navToggle'), scrim = d.getElementById('scrim'), collapse = d.getElementById('collapseBtn');
    function closeNav() { body.classList.remove('nav-open'); }
    if (toggle) toggle.addEventListener('click', function () { body.classList.toggle('nav-open'); });
    if (scrim) scrim.addEventListener('click', closeNav);
    d.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeNav(); });
    if (collapse) collapse.addEventListener('click', function () {
      var on = root.classList.toggle('collapsed');
      collapse.setAttribute('aria-pressed', on ? 'true' : 'false');
      try { localStorage.setItem('hp-collapsed', on ? '1' : '0'); } catch (e) {}
    });
  });

  /* 9. ripple on buttons */
  d.addEventListener('pointerdown', function (e) {
    if (reduce || !e.target.closest) return;
    var b = e.target.closest('.btn, main button, .logout-btn, .collapse-btn');
    if (!b || b.disabled || b.tagName === 'INPUT') return;
    var r = b.getBoundingClientRect(), size = Math.max(r.width, r.height) * 2, s = d.createElement('span');
    s.className = 'ripple';
    s.style.cssText = 'width:' + size + 'px;height:' + size + 'px;left:' + (e.clientX - r.left - size / 2) + 'px;top:' + (e.clientY - r.top - size / 2) + 'px';
    b.appendChild(s); setTimeout(function () { s.remove(); }, 700);
  });

  /* 10. loading bar and a short fade when moving to another page */
  d.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || !e.target.closest) return;
    var a = e.target.closest('a[href]');
    if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download')) return;
    if (/^(mailto|tel|javascript):/i.test(a.getAttribute('href')) || a.origin !== location.origin) return;
    if (a.pathname === location.pathname && a.search === location.search && a.hash) return;
    showBar();
    if (viewTransitions || reduce) return;
    e.preventDefault(); d.body.classList.add('leaving');
    setTimeout(function () { location.href = a.href; }, 170);
  });
  d.addEventListener('submit', function (e) {
    if (e.defaultPrevented) return;
    var f = e.target; if (f.target && f.target !== '_self') return;
    showBar();
    var s = e.submitter;
    if (s && s.tagName === 'BUTTON' && s.closest('main')) setTimeout(function () { s.classList.add('loading'); }, 0);
  });
  window.addEventListener('pageshow', function (e) { if (e.persisted) resetLeave(); });
})();
