/* Public website: the phone menu button, and a shadow on the header once the page is scrolled. */
(function () {
  var body = document.body;
  var button = document.querySelector(".menu-btn");
  var header = document.querySelector(".site-header");

  function closeMenu() {
    body.classList.remove("site-nav-open");
    if (button) { button.setAttribute("aria-expanded", "false"); }
  }

  if (button) {
    button.addEventListener("click", function () {
      var open = body.classList.toggle("site-nav-open");
      button.setAttribute("aria-expanded", open ? "true" : "false");
    });
    document.querySelectorAll(".site-nav a").forEach(function (link) {
      link.addEventListener("click", closeMenu);
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") { closeMenu(); }
    });
  }

  function onScroll() {
    if (header) { header.classList.toggle("scrolled", window.scrollY > 8); }
  }
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();
})();
