<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { X, Trash2, RefreshCw, Terminal } from 'lucide-vue-next'

const emit = defineEmits(['close'])
const logs = ref([])
const timer = ref(null)
const autoScroll = ref(true)
const logBody = ref(null)

async function load() {
  try {
    const resp = await fetch('/logs')
    const data = await resp.json()
    logs.value = data.logs || []
    if (autoScroll.value) {
      await nextTick()
      if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight
    }
  } catch (e) {
    console.error('Failed to load logs:', e)
  }
}

function clear() {
  logs.value = []
}

async function refresh() {
  await load()
}

function toggleScroll() {
  autoScroll.value = !autoScroll.value
  if (autoScroll.value) {
    nextTick(() => {
      if (logBody.value) logBody.value.scrollTop = logBody.value.scrollHeight
    })
  }
}

onMounted(() => {
  load()
  timer.value = setInterval(load, 2000)
})

onUnmounted(() => {
  if (timer.value) clearInterval(timer.value)
})
</script>

<template>
  <aside class="terminal-panel">
    <div class="panel-header">
      <h3><Terminal :size="16" :stroke-width="1.8" /> Terminal</h3>
      <div class="header-actions">
        <button class="icon-btn" title="Refresh" @click="refresh"><RefreshCw :size="15" :stroke-width="1.8" /></button>
        <button class="icon-btn" title="Clear" @click="clear"><Trash2 :size="15" :stroke-width="1.8" /></button>
        <button class="icon-btn" title="Auto-scroll" :class="{ active: autoScroll }" @click="toggleScroll">↓</button>
        <button class="icon-btn" title="Close" @click="emit('close')"><X :size="16" :stroke-width="1.8" /></button>
      </div>
    </div>
    <div ref="logBody" class="log-body">
      <div v-if="!logs.length" class="empty">No logs yet</div>
      <div v-for="(line, i) in logs" :key="i" class="log-line">{{ line }}</div>
    </div>
  </aside>
</template>

<style scoped>
.terminal-panel {
  width: 420px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-left: 1px solid var(--border);
  background: #0d1117;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid #21262d;
  color: #e6edf3;
  flex-shrink: 0;
}

.panel-header h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  margin: 0;
}

.header-actions {
  display: flex;
  gap: 2px;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  border: none;
  background: transparent;
  color: #8b949e;
  border-radius: 6px;
  cursor: pointer;
  font-size: 13px;
  transition: color 0.15s, background 0.15s;
}

.icon-btn:hover {
  color: #e6edf3;
  background: #21262d;
}

.icon-btn.active {
  color: #58a6ff;
}

.log-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  font-family: 'Consolas', 'Menlo', 'Monaco', monospace;
  font-size: 12px;
  line-height: 1.6;
}

.log-line {
  color: #c9d1d9;
  white-space: pre-wrap;
  word-break: break-all;
}

.empty {
  color: #8b949e;
  font-family: var(--font, system-ui);
}
</style>
