<script setup>
import { Brain, Sparkles, Wrench } from 'lucide-vue-next'

const props = defineProps(['msg'])
</script>

<template>
  <div class="msg-meta">

    <!-- Reasoning -->
    <div v-if="msg.reasoningContent" class="meta-item">
      <button
        class="meta-pill"
        :class="{ active: msg.showReasoning }"
        @click="msg.showReasoning = !msg.showReasoning"
      >
        <Brain :size="13" />
        <span>{{ msg.reasoningDone ? 'Reasoning' : 'Thinking' }}</span>
        <span v-if="!msg.reasoningDone" class="thinking-dot" />
      </button>
      <div v-show="msg.showReasoning" class="meta-body reasoning">{{ msg.reasoningContent }}</div>
    </div>

    <!-- Intent / knowledge sources -->
    <div v-show="!!msg.intentInfo" class="meta-item">
      <button
        class="meta-pill"
        :class="{ active: msg.showIntent }"
        @click="msg.showIntent = !msg.showIntent"
      >
        <Sparkles :size="13" />
        <span>{{ msg.intentInfo }}</span>
      </button>
      <div v-show="msg.showIntent" class="meta-body">{{ msg.intentInfo }}</div>
    </div>

    <!-- Retrieved passages / raw tool output -->
    <div v-show="!!msg.toolInfo" class="meta-item">
      <button
        class="meta-pill"
        :class="{ active: msg.showTool }"
        @click="msg.showTool = !msg.showTool"
      >
        <Wrench :size="13" />
        <span>Retrieval Details</span>
      </button>
      <div v-show="msg.showTool" class="meta-body mono">{{ msg.toolInfo }}</div>
    </div>

  </div>
</template>

<style scoped>
.msg-meta {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 6px;
  margin-bottom: 8px;
}

.meta-item { max-width: 100%; }

.meta-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-family: inherit;
  color: var(--text-3);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-full);
  padding: 4px 11px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}

.meta-pill:hover {
  color: var(--text-2);
  border-color: var(--border-strong);
}

.meta-pill.active {
  color: var(--accent);
  background: var(--accent-soft);
  border-color: transparent;
}

.meta-body {
  font-size: 12px;
  color: var(--text-2);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
  margin-top: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
  max-width: 660px;
  line-height: 1.6;
}

.meta-body.reasoning {
  background: var(--reason-bg);
  border-color: var(--reason-border);
  color: var(--reason-text);
}

.meta-body.mono { font-family: var(--font-mono); }

.thinking-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: blink 1s infinite;
}

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.25; }
}
</style>
