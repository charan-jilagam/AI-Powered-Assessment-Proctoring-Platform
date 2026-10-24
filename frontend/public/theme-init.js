// Runs before first paint so the page never flashes the wrong theme. Kept as a file so a strict CSP can stay free of inline scripts.
(function () {
  try {
    var m = localStorage.getItem('pai_theme');
    if (m !== 'dark' && m !== 'system') m = 'light';
    var dark = m === 'dark' || (m === 'system' && matchMedia('(prefers-color-scheme: dark)').matches);
    document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light');
    document.documentElement.style.colorScheme = dark ? 'dark' : 'light';
  } catch (e) { document.documentElement.setAttribute('data-theme', 'light'); }
})();
