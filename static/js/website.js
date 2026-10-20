/* website: behaviour for the public site (the phone menu, the current page highlight, the header shadow). */
(function () {
  var d = document;
  function ready(fn) { if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', fn); else fn(); }
  ready(function () {
    var body = d.body, toggle = d.getElementById('siteNavToggle'), header = d.querySelector('.site-header');

    if (toggle) {
      toggle.addEventListener('click', function () { body.classList.toggle('site-nav-open'); });
      d.addEventListener('keydown', function (e) { if (e.key === 'Escape') body.classList.remove('site-nav-open'); });
      d.addEventListener('click', function (e) {
        if (e.target.closest && e.target.closest('.site-nav a')) body.classList.remove('site-nav-open');
      });
    }

    /* highlight the current page in the header menu (the longest matching address wins) */
    var best = null, bestLen = -1, path = location.pathname;
    Array.prototype.forEach.call(d.querySelectorAll('.site-nav a:not(.btn)'), function (a) {
      var p = a.pathname, prefix = p.charAt(p.length - 1) === '/' ? p : p + '/';
      if ((p === path || (p.length > 1 && path.indexOf(prefix) === 0)) && p.length > bestLen) { best = a; bestLen = p.length; }
    });
    if (best) { best.classList.add('on'); best.setAttribute('aria-current', 'page'); }

    /* a soft shadow under the header once the page is scrolled */
    function onScroll() { if (header) header.classList.toggle('scrolled', window.scrollY > 8); }
    window.addEventListener('scroll', onScroll, { passive: true }); onScroll();
  });
})();
