<script setup>
import { ref } from 'vue'
import { Paperclip, Image as ImageIcon, FileText, Send } from 'lucide-vue-next'

const props = defineProps(['inputText', 'isStreaming', 'chat'])
const emit = defineEmits(['send', 'resize', 'upload-files'])

function handleKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    emit('send')
  }
}

function handleInput(event) {
  emit('resize', event)
}

const fileInput = ref(null)
const imageInput = ref(null)

// Drag & drop: collect the whole drop as one list, exactly like a multi-select.
const isDragging = ref(false)

function onDragOver(event) {
  event.preventDefault()
  isDragging.value = true
}

function onDragLeave() {
  isDragging.value = false
}

function onDrop(event) {
  event.preventDefault()
  isDragging.value = false
  const files = Array.from(event.dataTransfer?.files || [])
  if (files.length) emit('upload-files', files)
}

function handleFileSelect(event) {
  const files = Array.from(event.target.files || [])
  if (files.length) emit('upload-files', files)
  event.target.value = ''
}

function triggerFileInput() {
  if (fileInput.value) {
    fileInput.value.click()
  }
}

function triggerImageInput() {
  if (imageInput.value) {
    imageInput.value.click()
  }
}

function handlePaste(event) {
  const items = event.clipboardData?.items || []
  const files = []
  for (const item of items) {
    if (item.kind === 'file' && item.type && item.type.startsWith('image/')) {
      const blob = item.getAsFile()
      if (!blob) continue
      const sub = item.type.split('/')[1] || 'png'
      const ext = sub === 'jpeg' ? 'jpg' : sub
      files.push(new File([blob], `pasted-image-${Date.now()}-${files.length}.${ext}`, { type: item.type }))
      event.preventDefault()
    }
  }
  if (files.length) emit('upload-files', files)
}
</script>

<template>
  <div class="input-area">
    <div class="input-shell" :class="{ dragging: isDragging }" @dragover="onDragOver" @dragleave="onDragLeave" @drop="onDrop">

      <!-- Attachment chips -->
      <div v-if="chat?.uploadedFiles?.value?.length || chat?.uploadedImages?.value?.length || chat?.isUploading?.value" class="chip-list">
        <div v-for="f in chat.uploadedFiles.value" :key="f.file_id" class="chip">
          <FileText :size="13" :stroke-width="1.8" />
          <span class="chip-name">{{ f.filename }}</span>
          <span class="chip-meta">{{ f.chunk_count }}</span>
        </div>
        <div v-for="img in chat.uploadedImages.value" :key="img.file_id" class="chip">
          <img :src="`/image/${img.file_id}`" :alt="img.filename" class="chip-thumb" />
          <span class="chip-name">{{ img.filename }}</span>
        </div>
        <div v-if="chat?.isUploading?.value" class="chip chip-uploading">
          <span class="chip-name">Uploading…</span>
        </div>
      </div>

      <div class="input-row">
        <button
          class="upload-btn"
          :disabled="props.isStreaming.value"
          @click="triggerFileInput"
          title="Upload PDF"
        >
          <Paperclip :size="18" :stroke-width="1.8" />
        </button>
        <button
          class="upload-btn"
          :disabled="props.isStreaming.value"
          @click="triggerImageInput"
          title="Upload image"
        >
          <ImageIcon :size="18" :stroke-width="1.8" />
        </button>
        <input ref="fileInput" type="file" accept=".pdf" multiple style="display: none" @change="handleFileSelect" />
        <input ref="imageInput" type="file" accept=".jpg,.jpeg,.png,.gif,.webp" multiple style="display: none" @change="handleFileSelect" />

        <textarea
          v-model="props.inputText.value"
          placeholder="Type a message; Enter to send, Shift+Enter for newline…"
          rows="1"
          :disabled="props.isStreaming.value"
          @keydown="handleKeydown"
          @input="handleInput"
          @paste="handlePaste"
        ></textarea>

        <button class="send-btn" :disabled="props.isStreaming.value || chat?.isUploading?.value" @click="emit('send')" title="Send">
          <Send :size="18" :stroke-width="2" />
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.input-area {
  padding: 8px 22px 18px;
  background: var(--surface);
}

.input-shell {
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-lg);
  background: var(--surface);
  padding: 6px 8px 6px 10px;
  transition: border-color 0.18s, box-shadow 0.18s;
}

.input-shell:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.input-shell.dragging {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-soft);
}

.chip-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 6px 2px 10px;
}

.chip {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 4px 9px;
  border-radius: var(--radius-full);
  font-size: 12.5px;
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--text-2);
  max-width: 100%;
}

.chip-uploading { color: var(--text-3); font-style: italic; }

.chip-thumb {
  width: 20px;
  height: 20px;
  object-fit: cover;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.chip-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
}

.chip-meta {
  font-size: 11px;
  color: var(--text-3);
  background: var(--surface-3);
  padding: 1px 7px;
  border-radius: var(--radius-full);
  flex-shrink: 0;
}

.input-row {
  display: flex;
  gap: 4px;
  align-items: flex-end;
}

textarea {
  flex: 1;
  padding: 11px 6px;
  border: none;
  background: transparent;
  font-size: 15px;
  font-family: inherit;
  color: var(--text-1);
  resize: none;
  outline: none;
  min-height: 40px;
  max-height: 140px;
  line-height: 1.5;
  box-sizing: border-box;
}

textarea::placeholder { color: var(--text-3); }

.upload-btn {
  width: 40px;
  height: 40px;
  border: none;
  background: transparent;
  color: var(--text-3);
  border-radius: var(--radius);
  cursor: pointer;
  transition: color 0.15s, background 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.upload-btn:hover:not(:disabled) {
  color: var(--accent);
  background: var(--accent-soft);
}

.upload-btn:disabled { cursor: not-allowed; opacity: 0.4; }

.send-btn {
  width: 40px;
  height: 40px;
  border: none;
  background: var(--accent);
  color: var(--accent-text);
  border-radius: var(--radius);
  cursor: pointer;
  transition: background 0.15s, transform 0.1s, opacity 0.15s;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin: 0 0 4px 2px;
}

.send-btn:hover:not(:disabled) { background: var(--accent-hover); }
.send-btn:active:not(:disabled) { transform: scale(0.94); }

.send-btn:disabled {
  background: var(--surface-3);
  color: var(--text-3);
  cursor: not-allowed;
}
</style>
