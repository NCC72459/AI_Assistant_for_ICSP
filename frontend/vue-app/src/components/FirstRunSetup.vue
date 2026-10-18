<script setup>
import { ref, onMounted } from 'vue'
import { Cpu, Monitor } from 'lucide-vue-next'

const emit = defineEmits(['complete', 'skip'])

const form = ref({
  deepseek_api_key: '',
  deepseek_base_url: 'https://api.deepseek.com',
  deepseek_model: 'deepseek-flash',
  bocha_api_key: ''
})
const executionProviders = ref([])
const executionProvider = ref('')
const saving = ref(false)
const error = ref('')

function vendorLabel(v) {
  return { cpu: 'CPU', nvidia: 'NVIDIA', amd: 'AMD', intel: 'Intel', other: 'Other' }[v] || v
}

async function loadProviders() {
  try {
    const resp = await fetch('/settings')
    const data = await resp.json()
    executionProviders.value = data.settings?.execution_providers || []
    const saved = data.settings?.execution_provider || ''
    executionProvider.value = saved || (executionProviders.value.length ? executionProviders.value[0].id : '')
  } catch (e) {
    console.error('Failed to load execution providers:', e)
  }
}

async function submit() {
  if (!form.value.deepseek_api_key.trim()) {
    error.value = 'Please enter a DeepSeek API Key first'
    return
  }
  saving.value = true
  error.value = ''
  try {
    const resp = await fetch('/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ api: { ...form.value }, execution_provider: executionProvider.value })
    })
    if (!resp.ok) throw new Error('Configuration failed')
    emit('complete')
  } catch (e) {
    error.value = 'Save failed: ' + e.message
  } finally {
    saving.value = false
  }
}

onMounted(loadProviders)
</script>

<template>
  <div class="setup-overlay">
    <div class="setup-card">
      <h1>Welcome</h1>
      <p class="subtitle">Configure your API key and select the device for document embedding before getting started.</p>

      <div class="field">
        <label>DeepSeek API Key <span class="required">*</span></label>
        <input v-model="form.deepseek_api_key" type="password" placeholder="sk-..." autocomplete="off" />
      </div>
      <div class="field">
        <label>DeepSeek Base URL</label>
        <input v-model="form.deepseek_base_url" type="text" placeholder="https://api.deepseek.com" />
      </div>
      <div class="field">
        <label>DeepSeek Model</label>
        <input v-model="form.deepseek_model" type="text" placeholder="deepseek-flash" />
      </div>
      <div class="field">
        <label>Bocha API Key (for web search, optional)</label>
        <input v-model="form.bocha_api_key" type="password" placeholder="Optional" autocomplete="off" />
      </div>

      <div class="field">
        <label>Execution Provider</label>
        <div class="provider-list">
          <div
            v-for="p in executionProviders"
            :key="p.id"
            class="provider-row"
            :class="{ active: executionProvider === p.id }"
            @click="executionProvider = p.id"
          >
            <Cpu v-if="p.vendor === 'cpu'" :size="16" :stroke-width="1.7" class="provider-icon" />
            <Monitor v-else :size="16" :stroke-width="1.7" class="provider-icon" />
            <div class="provider-info">
              <span class="provider-name">{{ p.name }}</span>
              <span class="provider-meta">{{ vendorLabel(p.vendor) }}{{ p.vram_mb ? ' · ' + p.vram_mb + ' MB' : '' }}</span>
            </div>
            <span class="radio" :class="{ on: executionProvider === p.id }"></span>
          </div>
        </div>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <button class="start-btn" :disabled="saving" @click="submit">
        {{ saving ? 'Configuring…' : 'Get Started' }}
      </button>
      <button class="skip-btn" @click="emit('skip')">Skip for now</button>
    </div>
  </div>
</template>

<style scoped>
.setup-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  display: flex;
  align-items: center;
  justify-content: center;
  background:
    radial-gradient(circle at 50% -10%, var(--accent-soft), transparent 55%),
    var(--bg);
}

.setup-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 36px 36px 28px;
  width: 460px;
  max-width: 92vw;
  max-height: 92vh;
  overflow-y: auto;
  box-shadow: var(--shadow-lg);
  animation: modal-in 0.2s var(--ease);
}

@keyframes modal-in {
  from { opacity: 0; transform: scale(0.97) translateY(8px); }
  to { opacity: 1; transform: none; }
}

h1 { font-size: 23px; font-weight: 600; margin: 0 0 6px; color: var(--text-1); }
.subtitle { font-size: 14px; color: var(--text-3); margin: 0 0 22px; }

.field { margin-bottom: 14px; }
.field label { display: block; font-size: 13px; color: var(--text-2); margin-bottom: 6px; }

.field input {
  width: 100%;
  padding: 10px 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--radius);
  font-size: 14px;
  font-family: inherit;
  color: var(--text-1);
  background: var(--surface);
  box-sizing: border-box;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.field input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.provider-list { display: flex; flex-direction: column; gap: 6px; }

.provider-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
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

.required { color: var(--danger); }
.error { color: var(--danger); font-size: 13px; margin: 0 0 12px; }

.start-btn {
  width: 100%;
  padding: 12px;
  background: var(--accent);
  color: var(--accent-text);
  border: none;
  border-radius: var(--radius);
  font-size: 15px;
  font-family: inherit;
  font-weight: 500;
  cursor: pointer;
  margin-top: 4px;
  transition: background 0.15s;
}

.start-btn:hover:not(:disabled) { background: var(--accent-hover); }
.start-btn:disabled { opacity: 0.6; cursor: not-allowed; }

.skip-btn {
  width: 100%;
  padding: 9px;
  background: transparent;
  color: var(--text-3);
  border: none;
  border-radius: var(--radius);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  margin-top: 8px;
  transition: color 0.15s;
}

.skip-btn:hover { color: var(--text-2); }
</style>
