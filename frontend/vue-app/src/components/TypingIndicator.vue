<script setup>
const props = defineProps(['active'])
</script>

<template>
  <div class="typing-indicator" :class="{ active: props.active }">
    <span></span><span></span><span></span>
  </div>
</template>

<style scoped>
.typing-indicator {
  display: none;
  align-self: flex-start;
  padding: 14px 18px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  border-bottom-left-radius: 4px;
}

.typing-indicator.active {
  display: flex;
  gap: 5px;
}

.typing-indicator span {
  width: 7px;
  height: 7px;
  background: var(--text-3);
  border-radius: 50%;
  animation: typing 1.4s infinite ease-in-out;
}

.typing-indicator span:nth-child(2) { animation-delay: 0.2s; }
.typing-indicator span:nth-child(3) { animation-delay: 0.4s; }

@keyframes typing {
  0%, 60%, 100% { opacity: 0.35; transform: translateY(0); }
  30% { opacity: 1; transform: translateY(-5px); }
}
</style>
