import { createApp } from 'vue'
import './style.css'
import { initTheme } from './theme'
import App from './App.vue'

initTheme()

createApp(App).mount('#app')
