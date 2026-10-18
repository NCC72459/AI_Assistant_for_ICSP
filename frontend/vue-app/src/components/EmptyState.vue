<script setup>
import { MessageSquare } from 'lucide-vue-next'
</script>

<template>
  <div class="empty-state">
    <div class="icon"><MessageSquare :size="34" :stroke-width="1.4" /></div>
    <div>Start a conversation</div>
  </div>
</template>

<style scoped>
.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
  font-size: 14px;
  gap: 16px;
}

.empty-state .icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 64px;
  height: 64px;
  border-radius: var(--radius-lg);
  background: var(--surface-2);
  color: var(--text-3);
}
</style>
