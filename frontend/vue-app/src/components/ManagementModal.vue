<script setup>
import { ref, onMounted } from 'vue'
import { FileText, Image as ImageIcon, Trash2, X } from 'lucide-vue-next'

const props = defineProps(['chat'])
const emit = defineEmits(['close'])

const documents = ref([])
const images = ref([])
const loading = ref(true)

async function load() {
  loading.value = true
  try {
    const resp = await fetch('/admin/resources')
    const data = await resp.json()
    documents.value = data.documents || []
    images.value = data.images || []
  } catch (e) {
    console.error('Failed to load resources:', e)
  } finally {
    loading.value = false
  }
}

async function removeDocument(fileId) {
  if (!confirm('Delete this document?')) return
  try {
    await fetch(`/files/global/${fileId}`, { method: 'DELETE' })
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

onMounted(load)
</script>

<template>
  <div class="modal-overlay" @click.self="emit('close')">
    <div class="modal">
      <div class="modal-header">
        <h3>Documents & Images</h3>
        <button class="close-btn" @click="emit('close')"><X :size="18" :stroke-width="1.8" /></button>
      </div>
      <div class="modal-body">
        <h4><FileText :size="15" :stroke-width="1.8" /> Documents ({{ documents.length }})</h4>
        <div v-if="documents.length" class="resource-list">
          <div v-for="d in documents" :key="d.file_id" class="resource-row">
            <div class="resource-icon"><FileText :size="17" :stroke-width="1.7" /></div>
            <div class="resource-info">
              <span class="resource-name">{{ d.filename }}</span>
              <span class="resource-meta">{{ d.chunk_count }} chunks · {{ fmtSize(d.file_size) }} · {{ d.scope === 'global' ? 'Global' : 'Session' }}</span>
            </div>
            <button class="icon-danger" @click="removeDocument(d.file_id)" title="Delete">
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
    </div>
  </div>
</template>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(16, 24, 40, 0.45);
  backdrop-filter: blur(3px);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal {
  background: var(--surface);
  border-radius: var(--radius-lg);
  width: 580px;
  max-width: 90vw;
  max-height: 82vh;
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-lg);
  animation: modal-in 0.16s var(--ease);
}

@keyframes modal-in {
  from { opacity: 0; transform: scale(0.97) translateY(6px); }
  to { opacity: 1; transform: none; }
}

.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--border);
}

.modal-header h3 { font-size: 15px; font-weight: 600; margin: 0; color: var(--text-1); }

.close-btn {
  width: 30px; height: 30px;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; border-radius: var(--radius-sm);
  cursor: pointer; color: var(--text-3); transition: color 0.15s, background 0.15s;
}
.close-btn:hover { color: var(--text-1); background: var(--surface-2); }

.modal-body { padding: 16px 22px 22px; overflow-y: auto; flex: 1; }

.modal-body h4 {
  display: flex; align-items: center; gap: 7px;
  font-size: 12px; font-weight: 600; letter-spacing: 0.03em;
  text-transform: uppercase;
  margin: 14px 0 8px; color: var(--text-3);
}
.modal-body h4:first-child { margin-top: 0; }

.resource-list { display: flex; flex-direction: column; gap: 6px; }

.resource-row {
  display: flex; align-items: center; gap: 12px;
  padding: 10px 12px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  transition: border-color 0.15s;
}
.resource-row:hover { border-color: var(--border-strong); }

.resource-icon {
  width: 34px; height: 34px; flex-shrink: 0;
  display: flex; align-items: center; justify-content: center;
  border-radius: var(--radius-sm);
  background: var(--surface-3);
  color: var(--text-2);
}

.thumb { width: 34px; height: 34px; object-fit: cover; border-radius: var(--radius-sm); flex-shrink: 0; }

.resource-info { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.resource-name { font-size: 13.5px; color: var(--text-1); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.resource-meta { font-size: 12px; color: var(--text-3); }

.icon-danger {
  width: 32px; height: 32px; flex-shrink: 0;
  display: inline-flex; align-items: center; justify-content: center;
  border: none; background: transparent; border-radius: var(--radius-sm);
  cursor: pointer; color: var(--text-3); transition: color 0.15s, background 0.15s;
}
.icon-danger:hover { color: var(--danger); background: var(--danger-soft); }

.empty { font-size: 13px; color: var(--text-3); padding: 10px 2px; }
</style>
