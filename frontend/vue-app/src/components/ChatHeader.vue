<script setup>
import { FolderOpen, Settings, Terminal } from 'lucide-vue-next'

const props = defineProps(['title'])
const emit = defineEmits(['open-settings', 'open-management', 'open-terminal'])
</script>

<template>
  <div class="chat-header">
    <span class="header-title">{{ title }}</span>
    <div class="header-actions">
      <button class="icon-btn" title="Documents & Images" @click="emit('open-management')">
        <FolderOpen :size="18" :stroke-width="1.8" />
      </button>
      <button class="icon-btn" title="Terminal" @click="emit('open-terminal')">
        <Terminal :size="18" :stroke-width="1.8" />
      </button>
      <button class="icon-btn" title="Settings" @click="emit('open-settings')">
        <Settings :size="18" :stroke-width="1.8" />
      </button>
    </div>
  </div>
</template>

<style scoped>
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 22px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  flex-shrink: 0;
}

.header-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.header-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: none;
  background: transparent;
  color: var(--text-3);
  border-radius: var(--radius);
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
}

.icon-btn:hover {
  color: var(--text-1);
  background: var(--surface-2);
}
</style>
