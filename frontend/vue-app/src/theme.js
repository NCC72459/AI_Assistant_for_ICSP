const THEMES = ['light', 'dark', 'black']
const KEY = 'app-theme'

export function getTheme() {
  const t = localStorage.getItem(KEY)
  return THEMES.includes(t) ? t : 'light'
}

export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
}

export function setTheme(theme) {
  const t = THEMES.includes(theme) ? theme : 'light'
  localStorage.setItem(KEY, t)
  applyTheme(t)
}

export function initTheme() {
  applyTheme(getTheme())
}
