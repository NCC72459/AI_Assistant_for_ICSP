<script setup>
import { ref } from 'vue'
import { AlertTriangle } from 'lucide-vue-next'
import ChatHeader from './ChatHeader.vue'
import MessageList from './MessageList.vue'
import InputArea from './InputArea.vue'
import KnowledgePanel from './KnowledgePanel.vue'
import SettingsModal from './SettingsModal.vue'
import TerminalPanel from './TerminalPanel.vue'

const props = defineProps(['chat'])
const showManagement = ref(false)
const showSettings = ref(false)
const showTerminal = ref(false)

function onSettingsSaved() {
  if (props.chat?.apiKeyMissing) {
    props.chat.apiKeyMissing.value = false
  }
}
</script>

<template>
  <div class="chat-area-wrapper">
    <div class="chat-area">
    <ChatHeader
      :title="chat.chatTitle.value"
      @open-settings="showSettings = true"
      @open-management="showManagement = true"
      @open-terminal="showTerminal = true"
    />
    <div v-if="chat.apiKeyMissing?.value" class="api-key-banner">
      <span class="banner-text"><AlertTriangle :size="15" :stroke-width="2" /> API key not configured; unable to chat</span>
      <button class="banner-btn" @click="showSettings = true">Configure</button>
    </div>
    <MessageList :chat="chat" />
    <InputArea
      :inputText="chat.inputText"
      :isStreaming="chat.isStreaming"
      :chat="chat"
      @send="chat.send"
      @resize="chat.autoResize"
      @upload-files="chat.uploadFiles"
    />
    </div>
    <KnowledgePanel v-if="showManagement" :chat="chat" @close="showManagement = false" />
    <SettingsModal v-if="showSettings" @close="showSettings = false" @saved="onSettingsSaved" />
    <TerminalPanel v-if="showTerminal" @close="showTerminal = false" />
  </div>
</template>

<style scoped>
.chat-area-wrapper {
  flex: 1;
  display: flex;
  min-width: 0;
}

.chat-area {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  min-width: 0;
}

.api-key-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 22px;
  background: var(--banner-bg);
  border-bottom: 1px solid var(--banner-border);
  font-size: 13.5px;
  color: var(--banner-text);
}

.banner-text { display: inline-flex; align-items: center; gap: 7px; }

.banner-btn {
  background: var(--banner-btn);
  color: #fff;
  border: none;
  padding: 6px 14px;
  border-radius: var(--radius-sm);
  font-size: 13px;
  font-family: inherit;
  cursor: pointer;
  transition: background 0.15s;
  flex-shrink: 0;
}

.banner-btn:hover { background: var(--banner-btn-hover); }
</style>
