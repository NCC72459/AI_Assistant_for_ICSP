<script setup>
import EmptyState from './EmptyState.vue'
import DebugPanel from './DebugPanel.vue'
import MessageBubble from './MessageBubble.vue'
import TypingIndicator from './TypingIndicator.vue'

const props = defineProps(['chat'])
</script>

<template>
  <div class="chat-messages" ref="chat.messagesContainer">
    <EmptyState v-if="chat.currentMessages.value.length === 0" />

    <template v-for="(msg, idx) in chat.currentMessages.value" :key="idx">
      <!-- Use v-show (not v-if) to preserve reasoning state; also supports reasoningContent -->
      <DebugPanel
        v-show="msg.role === 'assistant' && (msg.intentInfo || msg.toolInfo || msg.reasoningContent)"
        :msg="msg" />
      <MessageBubble :msg="msg" />
    </template>

    <TypingIndicator :active="chat.isStreaming.value" />
  </div>
</template>

<style scoped>
.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
</style>
