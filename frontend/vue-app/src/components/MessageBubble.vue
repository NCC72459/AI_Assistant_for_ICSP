<script setup>
import { marked } from 'marked'
import { computed } from 'vue'

const props = defineProps(['msg'])

const renderedContent = computed(() => {
  if (!props.msg.content) return ''
  return marked(props.msg.content, {
    breaks: true,
    gfm: true
  })
})
</script>

<template>
  <div class="message" :class="msg.role">
    <div class="bubble" v-html="renderedContent"></div>
    <div v-if="msg.role === 'assistant' && msg.tokenUsage" class="usage-info">
      Context ≈ {{ msg.tokenUsage.total_tokens }} tokens<template v-if="msg.tokenUsage.image_count"> · {{ msg.tokenUsage.image_count }} images</template>
    </div>
  </div>
</template>

<style scoped>
.message {
  max-width: 82%;
  display: flex;
  flex-direction: column;
}

.message.user { align-self: flex-end; }
.message.assistant { align-self: flex-start; }

.message .bubble {
  padding: 12px 16px;
  border-radius: var(--radius-lg);
  line-height: 1.65;
  font-size: 15px;
  word-break: break-word;
}

.usage-info {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 4px;
  padding-left: 4px;
}

.message .bubble :deep(h1),
.message .bubble :deep(h2),
.message .bubble :deep(h3),
.message .bubble :deep(h4) {
  margin: 8px 0 4px;
  font-weight: 600;
}

.message .bubble :deep(h1) { font-size: 1.3em; }
.message .bubble :deep(h2) { font-size: 1.2em; }
.message .bubble :deep(h3) { font-size: 1.1em; }

.message .bubble :deep(ul),
.message .bubble :deep(ol) {
  padding-left: 20px;
  margin: 4px 0;
}

.message .bubble :deep(li) { margin: 2px 0; }

.message .bubble :deep(code) {
  background: var(--surface-3);
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 0.9em;
  font-family: var(--font-mono);
}

.message .bubble :deep(pre) {
  background: var(--surface-3);
  padding: 12px;
  border-radius: var(--radius);
  overflow-x: auto;
  margin: 8px 0;
}

.message .bubble :deep(pre code) {
  background: none;
  padding: 0;
}

.message .bubble :deep(blockquote) {
  border-left: 3px solid var(--border-strong);
  padding-left: 12px;
  margin: 8px 0;
  color: var(--text-2);
}

.message .bubble :deep(table) {
  border-collapse: collapse;
  margin: 8px 0;
  width: 100%;
}

.message .bubble :deep(th),
.message .bubble :deep(td) {
  border: 1px solid var(--border);
  padding: 6px 10px;
  text-align: left;
}

.message .bubble :deep(th) {
  background: var(--surface-3);
  font-weight: 600;
}

.message .bubble :deep(a) {
  color: var(--accent);
  text-decoration: none;
}

.message .bubble :deep(a:hover) { text-decoration: underline; }

.message .bubble :deep(p) { margin: 4px 0; }

.message .bubble :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: 12px 0;
}

.message.user .bubble {
  background: var(--accent);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message.user .bubble :deep(a) { color: #b3c4ff; }
.message.user .bubble :deep(code) { background: rgba(255, 255, 255, 0.15); }
.message.user .bubble :deep(blockquote) {
  border-left-color: rgba(255, 255, 255, 0.3);
  color: #d0d8ff;
}
.message.user .bubble :deep(th) { background: rgba(255, 255, 255, 0.08); }
.message.user .bubble :deep(th),
.message.user .bubble :deep(td) { border-color: rgba(255, 255, 255, 0.2); }

.message.assistant .bubble {
  background: var(--surface-2);
  border: 1px solid var(--border);
  color: var(--text-1);
  border-bottom-left-radius: 4px;
}
</style>
