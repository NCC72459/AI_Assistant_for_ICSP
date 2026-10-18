<script setup>
import { ref, onMounted } from 'vue'
import Sidebar from './components/sidebar.vue'
import ChatArea from './components/ChatArea.vue'
import FirstRunSetup from './components/FirstRunSetup.vue'
import { useChat } from './composables/useChat.js'

const chat = useChat()
const needsSetup = ref(false)

onMounted(async () => {
  await checkSetup()
  if (!needsSetup.value) {
    chat.loadConversations()
  }
})

async function checkSetup() {
  try {
    const resp = await fetch('/settings')
    const data = await resp.json()
    needsSetup.value = !(data.settings?.api_config?.has_deepseek_key)
  } catch (e) {
    console.error('Failed to check setup:', e)
  }
}

function onSetupComplete() {
  needsSetup.value = false
  chat.loadConversations()
}
</script>

<template>
  <div class="app-container">
    <Sidebar :chat="chat" />
    <ChatArea :chat="chat" />
  </div>
  <FirstRunSetup v-if="needsSetup" @complete="onSetupComplete" @skip="needsSetup = false" />
</template>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: var(--font);
  height: 100vh;
  background: var(--bg);
  color: var(--text-1);
  display: flex;
  justify-content: center;
  align-items: center;
  transition: background 0.2s ease, color 0.2s ease;
}

.app-container {
  width: 1200px;
  height: 800px;
  max-width: 100%;
  max-height: 100vh;
  display: flex;
  background: var(--surface);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-lg);
  overflow: hidden;
  transition: background 0.2s ease;
}

/* In dark / pure-black the floating shadow is invisible; use a hairline border
   so the app frame stays legible, and flatten the corners a touch. */
[data-theme="dark"] .app-container,
[data-theme="black"] .app-container {
  box-shadow: none;
  border: 1px solid var(--border);
}

/* Scrollbars */
.chat-messages::-webkit-scrollbar,
.conversation-list::-webkit-scrollbar,
.meta-body::-webkit-scrollbar {
  width: 7px;
  height: 7px;
}

.chat-messages::-webkit-scrollbar-thumb,
.conversation-list::-webkit-scrollbar-thumb,
.meta-body::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 4px;
}

.chat-messages::-webkit-scrollbar-thumb:hover,
.conversation-list::-webkit-scrollbar-thumb:hover,
.meta-body::-webkit-scrollbar-thumb:hover {
  background: var(--text-3);
}

/* Responsive layout */
@media (max-width: 768px) {
  .app-container {
    flex-direction: column;
    height: 100vh;
    border-radius: 0;
  }
  .sidebar {
    width: 100%;
    min-width: unset;
    height: 50px;
    flex-direction: row;
    align-items: center;
    padding: 0 12px;
    border-right: none;
    border-bottom: 1px solid var(--border);
  }
  .sidebar-header {
    padding: 0;
    border: none;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .sidebar-header h2 { font-size: 13px; margin: 0; }
  .new-chat-btn { width: auto; padding: 6px 12px; font-size: 13px; }
  .conversation-list {
    display: none;
    position: absolute;
    top: 50px;
    left: 0;
    right: 0;
    background: var(--surface);
    box-shadow: var(--shadow);
    max-height: 200px;
    z-index: 100;
  }
  .conversation-list.show { display: block; }
  .sidebar-footer { display: none; }
}
</style>
