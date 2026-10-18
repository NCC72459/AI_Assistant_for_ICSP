<script setup>
import { MessageSquare, Plus, X } from 'lucide-vue-next'

const props = defineProps(['chat'])
</script>

<template>
  <div class="sidebar">
    <div class="sidebar-header">
      <h2><MessageSquare :size="15" :stroke-width="2" /> Conversations</h2>
      <button class="new-chat-btn" @click="chat.createNewConversation()">
        <Plus :size="16" :stroke-width="2.2" /> New Chat
      </button>
    </div>
    <div class="conversation-list">
      <div v-for="id in chat.conversationOrder" :key="id"
           class="conversation-item"
           :class="{ active: id === chat.currentId.value }"
           @click="chat.switchConversation(id)">
        <span class="title">{{ chat.conversations[id].title }}</span>
        <button class="delete-btn" @click.stop="chat.deleteConversation(id)" title="Delete conversation">
          <X :size="14" :stroke-width="2" />
        </button>
      </div>
    </div>
    <div class="sidebar-footer">AI Assistant v2026.10.01</div>
  </div>
</template>

<style scoped>
.sidebar {
  width: 280px;
  min-width: 280px;
  background: var(--surface-2);
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 18px 14px 12px;
  border-bottom: 1px solid var(--border);
}

.sidebar-header h2 {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
  margin-bottom: 12px;
}

.new-chat-btn {
  width: 100%;
  padding: 10px;
  background: var(--accent);
  color: var(--accent-text);
  border: none;
  border-radius: var(--radius);
  font-size: 14px;
  font-weight: 500;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s, transform 0.1s;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.new-chat-btn:hover { background: var(--accent-hover); }
.new-chat-btn:active { transform: scale(0.985); }

.conversation-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.conversation-item {
  padding: 10px 12px;
  margin: 2px 0;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: background 0.15s;
  display: flex;
  align-items: center;
  justify-content: space-between;
  position: relative;
}

.conversation-item:hover { background: var(--surface-3); }

.conversation-item.active { background: var(--accent-soft); }

.conversation-item.active::before {
  content: '';
  position: absolute;
  left: 0;
  top: 22%;
  bottom: 22%;
  width: 3px;
  border-radius: 0 3px 3px 0;
  background: var(--accent);
}

.conversation-item .title {
  font-size: 13.5px;
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 1;
  margin-right: 8px;
}

.conversation-item.active .title {
  color: var(--text-1);
  font-weight: 500;
}

.conversation-item .delete-btn {
  width: 22px;
  height: 22px;
  border: none;
  background: transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  color: var(--text-3);
  opacity: 0;
  transition: opacity 0.15s, background 0.15s, color 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.conversation-item:hover .delete-btn { opacity: 1; }

.conversation-item .delete-btn:hover {
  background: var(--danger-soft);
  color: var(--danger);
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-3);
  text-align: center;
}
</style>
