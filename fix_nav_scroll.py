r"""Fixes menu links jumping to the top instead of scrolling to their section.
Put this file next to manage.py and run:  python fix_nav_scroll.py
The old script is kept as static/js/home-nav.js.bak. Safe to run again."""
import os, shutil, sys

PATH = os.path.join("static", "js", "home-nav.js")
if not os.path.exists("manage.py") or not os.path.isdir(os.path.dirname(PATH)):
    sys.exit("Put this file in the project folder (the one with manage.py) and run it there.")

JS = r'''/* Home page navigation.
   1. A link to a section of the page you are on (menu, footer, buttons) scrolls there smoothly,
      without reloading the page, so it never jumps to the top.
   2. Arriving from another page with #section in the address scrolls to that section.
   3. The menu link of the section being read is highlighted; the phone menu closes after a tap. */
(function () {
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function targetFor(a) {
    if (!a || !a.hash || a.hash.length < 2) { return null; }
    if (a.origin !== window.location.origin || a.pathname !== window.location.pathname) { return null; }
    var id;
    try { id = decodeURIComponent(a.hash.slice(1)); } catch (e) { return null; }
    return document.getElementById(id);
  }

  function scrollToTarget(el, smooth) {
    el.scrollIntoView({ behavior: smooth && !reduce ? 'smooth' : 'auto', block: 'start' });
  }

  /* 1. same-page section links: handled here, before any other click code can reload the page */
  window.addEventListener('click', function (e) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) { return; }
    var a = e.target.closest ? e.target.closest('a[href]') : null;
    if (!a || (a.target && a.target !== '_self')) { return; }
    var el = targetFor(a);
    if (!el) { return; }
    e.preventDefault();
    e.stopImmediatePropagation();
    document.body.classList.remove('leaving');
    document.body.classList.remove('site-nav-open');
    scrollToTarget(el, true);
    if (window.location.hash !== a.hash && window.history && window.history.pushState) {
      window.history.pushState(null, '', a.pathname + a.search + a.hash);
    }
  }, true);

  /* 2. arriving with #section in the address */
  function scrollToHash() {
    if (!window.location.hash || window.location.hash.length < 2) { return; }
    var el;
    try { el = document.getElementById(decodeURIComponent(window.location.hash.slice(1))); } catch (e) { return; }
    if (el) { scrollToTarget(el, false); }
  }
  window.addEventListener('load', function () { setTimeout(scrollToHash, 60); });
  window.addEventListener('popstate', scrollToHash);

  /* 3. highlight the section being read */
  var onPage = [];
  var byId = {};
  Array.prototype.slice.call(document.querySelectorAll('.site-nav a[href*="#"]')).forEach(function (a) {
    var el = targetFor(a);
    if (el) { onPage.push(a); byId[el.id] = a; }
  });
  if (!onPage.length) { return; }

  var ids = onPage.map(function (a) { return a.hash.slice(1); });
  var ticking = false;

  function update() {
    ticking = false;
    var current = null;
    ids.forEach(function (id) {
      var el = document.getElementById(id);
      if (el && el.getBoundingClientRect().top <= 140) { current = id; }
    });
    if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) {
      current = ids[ids.length - 1];
    }
    onPage.forEach(function (a) { a.classList.remove('on'); });
    if (current && byId[current]) { byId[current].classList.add('on'); }
  }

  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
  }, { passive: true });
  window.addEventListener('hashchange', update);
  update();
})();
'''

if os.path.exists(PATH) and not os.path.exists(PATH + ".bak"):
    shutil.copyfile(PATH, PATH + ".bak")
open(PATH, "w", encoding="utf-8", newline="\n").write(JS)
print("Updated", PATH)
print("Done. Press Ctrl+F5 on the home page.")
