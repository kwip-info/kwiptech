/* Apply before paint; local preference never affects account or agent access. */
(() => {
  let theme = 'dark';
  try { if (localStorage.getItem('kwip-theme') === 'light') theme = 'light'; } catch {}
  function apply(value) {
    document.documentElement.dataset.theme = value;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', value === 'dark' ? '#151515' : '#fbfaf7');
    const button = document.getElementById('theme-toggle');
    if (button) {
      button.textContent = value === 'dark' ? 'Light mode' : 'Dark mode';
      button.setAttribute('aria-label', 'Switch to ' + (value === 'dark' ? 'light' : 'dark') + ' mode');
    }
  }
  apply(theme);
  document.addEventListener('DOMContentLoaded', () => {
    apply(theme);
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      apply(theme);
      try { localStorage.setItem('kwip-theme', theme); } catch {}
    });
    document.querySelectorAll('.header nav a, .header .account-link').forEach(a => {
      const path = new URL(a.href).pathname;
      if (path === location.pathname || (path === '/account' && location.pathname.startsWith('/account/'))) a.setAttribute('aria-current', 'page');
    });
  });
})();
