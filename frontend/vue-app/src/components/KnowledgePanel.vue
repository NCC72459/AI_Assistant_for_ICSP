<script setup>
import { ref, onMounted, watch } from 'vue'
import { FileText, Image as ImageIcon, Trash2, X, Star } from 'lucide-vue-next'

const props = defineProps(['chat'])
const emit = defineEmits(['close'])

const documents = ref([])
const images = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const session = props.chat?.currentId?.value || 'global'
    const resp = await fetch('/admin/resources?session=' + encodeURIComponent(session))
    const data = await resp.json()
    documents.value = data.documents || []
    images.value = data.images || []
  } catch (e) {
    console.error('Failed to load resources:', e)
  } finally {
    loading.value = false
  }
}

async function togglePriority(doc) {
  const newPriority = doc.priority > 0 ? 0 : 1
  try {
    await fetch('/files/priority', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: doc.file_id, priority: newPriority })
    })
    doc.priority = newPriority
  } catch (e) {
    console.error('Failed to update priority:', e)
  }
}

async function removeDocument(doc) {
  if (!confirm('Delete this document?')) return
  try {
    const target = doc.scope === 'global'
      ? 'global'
      : (doc.session_id || props.chat?.currentId?.value || 'global')
    const resp = await fetch(`/files/${encodeURIComponent(target)}/${doc.file_id}`, { method: 'DELETE' })
    if (!resp.ok) throw new Error('delete failed')
    await load()
    props.chat?.refreshFileStatus?.(props.chat.currentId?.value)
  } catch (e) {
    console.error('Failed to delete document:', e)
  }
}

async function removeImage(fileId) {
  if (!confirm('Delete this image?')) return
  try {
    await fetch(`/image/${fileId}`, { method: 'DELETE' })
    await load()
    props.chat?.refreshImageStatus?.(props.chat.currentId?.value)
  } catch (e) {
    console.error('Failed to delete image:', e)
  }
}

function fmtSize(bytes) {
  if (!bytes) return '-'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1024 / 1024).toFixed(1) + ' MB'
}

watch(() => props.chat?.currentId?.value, load)
watch(() => props.chat?.uploadedFiles?.value?.length, load)
watch(() => props.chat?.uploadedImages?.value?.length, load)

onMounted(load)
</script>

<template>
  <aside class="knowledge-panel">
    <div class="panel-header">
      <h3>Knowledge Base</h3>
      <button class="close-btn" @click="emit('close')"><X :size="18" :stroke-width="1.8" /></button>
    </div>
    <div class="panel-body">
      <p class="hint">Star a file to mark it high-priority (ranked first in retrieval); files uploaded in this conversation are high-priority automatically.</p>

      <h4><FileText :size="15" :stroke-width="1.8" /> Documents ({{ documents.length }})</h4>
      <div v-if="loading" class="empty">Loading…</div>
      <div v-else-if="documents.length" class="resource-list">
        <div
          v-for="d in documents"
          :key="d.file_id"
          class="resource-row"
          :class="{ selected: d.priority > 0 }"
        >
          <button
            class="star-btn"
            :class="{ on: d.priority > 0 }"
            @click="togglePriority(d)"
            :title="d.priority > 0 ? 'Unmark high-priority' : 'Mark high-priority'"
          >
            <Star :size="16" :stroke-width="1.8" :fill="d.priority > 0 ? 'currentColor' : 'none'" />
          </button>
          <div class="resource-icon"><FileText :size="17" :stroke-width="1.7" /></div>
          <div class="resource-info">
            <span class="resource-name">{{ d.filename }}</span>
            <span class="resource-meta">{{ d.chunk_count }} chunks · {{ fmtSize(d.file_size) }} · {{ d.scope === 'global' ? 'Global' : 'Session' }}</span>
          </div>
          <button class="icon-danger" @click="removeDocument(d)" title="Delete">
            <Trash2 :size="16" :stroke-width="1.8" />
          </button>
        </div>
      </div>
      <div v-else class="empty">No documents</div>

      <h4><ImageIcon :size="15" :stroke-width="1.8" /> Images ({{ images.length }})</h4>
      <div v-if="images.length" class="resource-list">
        <div v-for="img in images" :key="img.file_id" class="resource-row">
          <img :src="`/image/${img.file_id}`" class="thumb" :alt="img.filename" />
          <div class="resource-info">
            <span class="resource-name">{{ img.filename }}</span>
            <span class="resource-meta">{{ img.created_at }}</span>
          </div>
          <button class="icon-danger" @click="removeImage(img.file_id)" title="Delete">
            <Trash2 :size="16" :stroke-width="1.8" />
          </button>
        </div>
      </div>
      <div v-else class="empty">No images</div>
    </div>
  </aside>
</template>

<style scoped>
.knowledge-panel {
  width: 300px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--surface);
  border-left: 1px solid var(--border);
  min-height: 0;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 16px;
  border-bottom: 1px solid var(--border);
}

.panel-header h3 { font-size: 14px; font-weight: 600; margin: 0; color: var(--text-1); }

.close-btn {
  width: 28px; height: 28px;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; border-radius: var(--radius-sm);
  cursor: pointer; color: var(--text-3); transition: color 0.15s, background 0.15s;
}
.close-btn:hover { color: var(--text-1); background: var(--surface-2); }

.panel-body { padding: 14px 14px 20px; overflow-y: auto; flex: 1; }

.hint {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.5;
  margin: 0 0 6px;
  padding: 9px 11px;
  background: var(--surface-2);
  border-radius: var(--radius-sm);
}

.panel-body h4 {
  display: flex; align-items: center; gap: 7px;
  font-size: 12px; font-weight: 600; letter-spacing: 0.03em;
  text-transform: uppercase;
  margin: 16px 0 8px; color: var(--text-3);
}

.resource-list { display: flex; flex-direction: column; gap: 6px; }

.resource-row {
  display: flex; align-items: center; gap: 9px;
  padding: 9px 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color 0.15s;
}
.resource-row:hover { border-color: var(--border-strong); }
.resource-row.selected { border-color: var(--accent); }

.star-btn {
  width: 28px; height: 28px; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; border-radius: var(--radius-sm);
  cursor: pointer; color: var(--text-3); transition: color 0.15s, background 0.15s;
}
.star-btn:hover { color: var(--accent); background: var(--surface-3); }
.star-btn.on { color: var(--accent); }

.resource-icon {
  width: 32px; height: 32px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--surface-3);
  color: var(--text-2);
}

.thumb { width: 32px; height: 32px; object-fit: cover; border-radius: var(--radius-sm); flex-shrink: 0; }

.resource-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.resource-name { font-size: 13px; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-meta { font-size: 11.5px; color: var(--text-3); }

.icon-danger {
  width: 30px; height: 30px; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; border-radius: var(--radius-sm);
  cursor: pointer; color: var(--text-3); transition: color 0.15s, background 0.15s;
}
.icon-danger:hover { color: var(--danger); background: var(--danger-soft); }

.empty { font-size: 13px; color: var(--text-3); padding: 10px 2px; }
</style>
