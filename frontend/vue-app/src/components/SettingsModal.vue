<script setup>
import { ref, computed, onMounted } from 'vue'
import { X, Cpu, Monitor } from 'lucide-vue-next'
import { getTheme, setTheme } from '../theme'

const emit = defineEmits(['close', 'saved'])
const settings = ref({})
const theme = ref(getTheme())
const apiConfig = ref({
  deepseek_api_key: '',
  deepseek_base_url: '',
  deepseek_model: '',
  bocha_api_key: ''
})
const hasDeepseekKey = ref(false)
const hasBochaKey = ref(false)
const saving = ref(false)
const executionProviders = ref([])
const executionProvider = ref('')

const webSearch = computed({
  get: () => settings.value.web_search_enabled === '1',
  set: (v) => { settings.value.web_search_enabled = v ? '1' : '0'; saveSetting('web_search_enabled', v ? '1' : '0') }
})

const globalScope = computed({
  get: () => settings.value.default_scope !== 'session',
  set: (v) => { settings.value.default_scope = v ? 'global' : 'session'; saveSetting('default_scope', v ? 'global' : 'session') }
})

function changeTheme(t) {
  theme.value = t
  setTheme(t)
}

function selectProvider(id) {
  executionProvider.value = id
  saveSetting('execution_provider', id)
}

function vendorLabel(v) {
  return { cpu: 'CPU', nvidia: 'NVIDIA', amd: 'AMD', intel: 'Intel', other: 'Other' }[v] || v
}

async function load() {
  try {
    const resp = await fetch('/settings')
    const data = await resp.json()
    settings.value = data.settings || {}
    const api = data.settings?.api_config || {}
    hasDeepseekKey.value = !!api.has_deepseek_key
    hasBochaKey.value = !!api.has_bocha_key
    apiConfig.value.deepseek_base_url = api.deepseek_base_url || ''
    apiConfig.value.deepseek_model = api.deepseek_model || ''
    executionProviders.value = data.settings?.execution_providers || []
    executionProvider.value = data.settings?.execution_provider || ''
  } catch (e) {
    console.error('Failed to load settings:', e)
  }
}

async function saveSetting(key, value) {
  try {
    await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value })
    })
  } catch (e) {
    console.error('Failed to save setting:', e)
  }
}

async function save() {
  saving.value = true
  try {
    const payload = { api: { ...apiConfig.value } }




    await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    alert('Settings saved')
    emit('saved')
    apiConfig.value.deepseek_api_key = ''
    apiConfig.value.bocha_api_key = ''
    await load()
  } catch (e) {
    console.error('Failed to save settings:', e)
    alert('Save failed: ' + e.message)
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <aside class="settings-panel">
    <div class="panel-header">
      <h3>Settings</h3>
      <button class="close-btn" @click="emit('close')"><X :size="18" :stroke-width="1.8" /></button>
    </div>
    <div class="panel-body">
      <div class="section-title">Execution Provider</div>
      <div class="provider-list">
        <div
          v-for="p in executionProviders"
          :key="p.id"
          class="provider-row"
          :class="{ active: executionProvider === p.id }"
          @click="selectProvider(p.id)"
        >
          <Cpu v-if="p.vendor === 'cpu'" :size="17" :stroke-width="1.7" class="provider-icon" />
          <Monitor v-else :size="17" :stroke-width="1.7" class="provider-icon" />
          <div class="provider-info">
            <span class="provider-name">{{ p.name }}</span>
            <span class="provider-meta">{{ vendorLabel(p.vendor) }}{{ p.vram_mb ? ' · ' + p.vram_mb + ' MB' : '' }}</span>
          </div>
          <span class="radio" :class="{ on: executionProvider === p.id }"></span>
        </div>
      </div>
      <p class="hint">Select the device used for document embedding. Applies to subsequent uploads and searches.</p>

      <div class="section-title">Appearance</div>
      <div class="setting-row">
        <label>Theme</label>
        <div class="segmented">
          <button :class="{ active: theme === 'light' }" @click="changeTheme('light')">Light</button>
          <button :class="{ active: theme === 'dark' }" @click="changeTheme('dark')">Dark</button>
          <button :class="{ active: theme === 'black' }" @click="changeTheme('black')">Black</button>
        </div>
      </div>

      <div class="section-title">General</div>
      <div class="setting-row">
        <label>Web Search</label>
        <label class="switch">
          <input type="checkbox" v-model="webSearch" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="setting-row">
        <label>Default to Global KB</label>
        <label class="switch">
          <input type="checkbox" v-model="globalScope" />
          <span class="slider"></span>
        </label>
      </div>
      <div class="setting-row">
        <label>Images per turn (1-8)</label>
        <input v-model="settings.max_images_per_turn" type="number" min="1" max="8" @change="saveSetting('max_images_per_turn', settings.max_images_per_turn)" />
      </div>

      <div class="section-title">API Configuration</div>
      <div class="setting-row">
        <label>DeepSeek API Key</label>
        <input
          v-model="apiConfig.deepseek_api_key"
          type="password"
          class="api-input"
          :placeholder="hasDeepseekKey ? 'Configured; leave blank to keep' : 'Not configured; enter key'"
          autocomplete="off"
        />
      </div>
      <div class="setting-row">
        <label>DeepSeek Base URL</label>
        <input v-model="apiConfig.deepseek_base_url" type="text" class="api-input" placeholder="https://api.deepseek.com" />
      </div>
      <div class="setting-row">
        <label>DeepSeek Model</label>
        <input v-model="apiConfig.deepseek_model" type="text" class="api-input" placeholder="deepseek-flash" />
      </div>
      <div class="setting-row">
        <label>Bocha API Key</label>
        <input
          v-model="apiConfig.bocha_api_key"
          type="password"
          class="api-input"
          :placeholder="hasBochaKey ? 'Configured; leave blank to keep' : 'Not configured; enter key'"
          autocomplete="off"
        />
      </div>
    </div>
    <div class="panel-footer">
      <button class="save-btn" :disabled="saving" @click="save">{{ saving ? 'Saving…' : 'Save' }}</button>
    </div>
  </aside>
</template>

<style scoped>
.settings-panel {
  width: 340px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-left: 1px solid var(--border);
  min-height: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px;
  border-bottom: 1px solid var(--border);
}

.panel-header h3 { font-size: 14px; font-weight: 600; margin: 0; color: var(--text-1); }

.close-btn {
  width: 28px; height: 28px;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; border-radius: var(--radius-sm);
  cursor: pointer; color: var(--text-3); transition: color 0.15s, background 0.15s;
}
.close-btn:hover { color: var(--text-1); background: var(--surface-2); }

.panel-body { padding: 6px 16px 18px; overflow-y: auto; flex: 1; }

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  margin: 16px 0 6px;
}

.hint {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
  margin: 8px 0 0;
}

/* Execution provider list */
.provider-list { display: flex; flex-direction: column; gap: 6px; }

.provider-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: border-color 0.15s;
}
.provider-row:hover { border-color: var(--border-strong); }
.provider-row.active { border-color: var(--accent); }

.provider-icon { color: var(--text-2); flex-shrink: 0; }
.provider-row.active .provider-icon { color: var(--accent); }

.provider-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.provider-name { font-size: 13.5px; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.provider-meta { font-size: 11.5px; color: var(--text-3); }

.radio {
  width: 16px; height: 16px; flex-shrink: 0;
  border-radius: 50%;
  border: 2px solid var(--border-strong);
  transition: border-color 0.15s, background 0.15s;
}
.radio.on { border-color: var(--accent); background: var(--accent); box-shadow: inset 0 0 0 3px var(--surface); }

/* Settings rows */
.setting-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 0;
  border-bottom: 1px solid var(--border);
}

.setting-row label { font-size: 14px; color: var(--text-1); }

.setting-row input[type="number"] {
  padding: 7px 11px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: inherit;
  color: var(--text-1);
  background: var(--surface);
  outline: none;
  width: 80px;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.setting-row input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.setting-row .api-input {
  padding: 7px 11px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: inherit;
  color: var(--text-1);
  background: var(--surface);
  outline: none;
  width: 200px;
  transition: border-color 0.15s, box-shadow 0.15s;
}

/* Segmented control */
.segmented {
  display: inline-flex;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 2px;
  gap: 2px;
}

.segmented button {
  border: none;
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  font-family: inherit;
  padding: 5px 12px;
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.segmented button:hover { color: var(--text-1); }

.segmented button.active {
  background: var(--surface);
  color: var(--accent);
  box-shadow: var(--shadow-sm);
  font-weight: 500;
}

/* Toggle switch */
.switch {
  position: relative;
  display: inline-block;
  width: 42px;
  height: 24px;
  flex-shrink: 0;
}

.switch input { opacity: 0; width: 0; height: 0; }

.switch .slider {
  position: absolute;
  cursor: pointer;
  inset: 0;
  background: var(--border-strong);
  border-radius: var(--radius-full);
  transition: background 0.2s;
}

.switch .slider::before {
  content: '';
  position: absolute;
  height: 18px;
  width: 18px;
  left: 3px;
  top: 3px;
  background: #fff;
  border-radius: 50%;
  transition: transform 0.2s var(--ease);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
}

.switch input:checked + .slider { background: var(--accent); }
.switch input:checked + .slider::before { transform: translateX(18px); }

.panel-footer {
  padding: 14px 16px;
  border-top: 1px solid var(--border);
  display: flex;
  justify-content: flex-end;
}

.save-btn {
  background: var(--accent);
  color: var(--accent-text);
  border: none;
  padding: 9px 22px;
  border-radius: var(--radius);
  font-size: 14px;
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}

.save-btn:hover:not(:disabled) { background: var(--accent-hover); }
.save-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
