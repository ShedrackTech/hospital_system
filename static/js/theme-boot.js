/* Runs before the page is drawn, so the sidebar does not flash open when it was left collapsed. */
try { if (localStorage.getItem('hp-collapsed') === '1') document.documentElement.classList.add('collapsed'); } catch (e) {}
