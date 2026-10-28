/* Home page navigation: highlights the section being read, and closes the phone menu
   after a menu link is tapped. Does nothing on pages that are not the home page. */
(function () {
  var links = Array.prototype.slice.call(document.querySelectorAll('.site-nav a[href*="#"]'));
  var onPage = [];   /* menu links that point at a section of the page we are on */
  var byId = {};

  links.forEach(function (a) {
    var id = a.hash.replace('#', '');
    if (a.pathname === window.location.pathname && id && document.getElementById(id)) {
      onPage.push(a);
      byId[id] = a;
      a.addEventListener('click', function () {
        document.body.classList.remove('site-nav-open');
      });
    }
  });
  if (!onPage.length) { return; }

  var ids = onPage.map(function (a) { return a.hash.replace('#', ''); });
  var ticking = false;

  function update() {
    ticking = false;
    var current = null;
    ids.forEach(function (id) {
      if (document.getElementById(id).getBoundingClientRect().top <= 140) { current = id; }
    });
    var atBottom = window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4;
    if (atBottom) { current = ids[ids.length - 1]; }
    onPage.forEach(function (a) { a.classList.remove('on'); });
    if (current && byId[current]) { byId[current].classList.add('on'); }
  }

  window.addEventListener('scroll', function () {
    if (!ticking) { ticking = true; window.requestAnimationFrame(update); }
  }, { passive: true });
  window.addEventListener('hashchange', update);
  update();
})();
