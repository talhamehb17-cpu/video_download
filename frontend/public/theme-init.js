// Runs before the app loads so the page never flashes the wrong theme.
(function () {
  try {
    var saved = localStorage.getItem('lumora-theme')
    var theme = saved === 'light' || saved === 'dark' ? saved : 'dark'
    document.documentElement.dataset.theme = theme
    var meta = document.querySelector('meta[name="theme-color"]')
    if (meta) meta.setAttribute('content', theme === 'light' ? '#f5f6ff' : '#05060f')
  } catch {
    document.documentElement.dataset.theme = 'dark'
  }
})()
