import { ref, reactive, computed } from 'vue'

export function useChat() {
  // ── Reactive State ──
  const conversations = reactive({})
  const conversationOrder = reactive([])
  const currentId = ref(null)
  const inputText = ref('')
  const isStreaming = ref(false)
  const messagesContainer = ref(null)
  let eventSource = null
  // Documents indexed in the current conversation: [{ file_id, filename, chunk_count }]
  const uploadedFiles = ref([])
  // Images uploaded in the current conversation: [{ file_id, filename, mime_type }]
  const uploadedImages = ref([])
  const isUploading = ref(false)
const apiKeyMissing = ref(false)

  function genId() {
    return Date.now().toString(36) + Math.random().toString(36).substr(2, 5)
  }

  function scrollToBottom() {
    setTimeout(() => {
      if (messagesContainer.value) {
        messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
      }
    }, 10)
  }

  // ── Computed Properties ──
  const currentConv = computed(() => currentId.value ? conversations[currentId.value] : null)
  const currentMessages = computed(() => currentConv.value?.messages || [])
  const chatTitle = computed(() => currentConv.value?.title || 'New Chat')

  // ── Parse assistant message metadata (including reasoningContent) ──
  function parseAssistantMessage(msg) {
    let intentInfo = '', toolInfo = '', reasoningContent = ''
    if (msg.metadata) {
      try {
        const meta = typeof msg.metadata === 'string'
          ? JSON.parse(msg.metadata)
          : msg.metadata
        intentInfo = meta.intentInfo || ''
        toolInfo = meta.toolInfo || ''
        reasoningContent = meta.reasoningContent || ''
      } catch (e) {
        // metadata parse failed, use empty values
      }
    }
    return {
      ...msg,
      intentInfo,
      intentDetail: '',
      toolInfo,
      reasoningContent,
      showIntent: false,
      showTool: false,
      showReasoning: false,
      reasoningDone: true
    }
  }

  // ── Conversation Management ──
  function createNewConversation() {
    if (eventSource) { eventSource.close(); eventSource = null }
    isStreaming.value = false
    uploadedFiles.value = []
    uploadedImages.value = []
    const id = genId()
    conversations[id] = { title: 'New Chat', messages: [] }
    conversationOrder.unshift(id)
    currentId.value = id
    localStorage.setItem('session_id', id)
  }

  // Refresh conversation data from API (parse metadata)
  async function refreshConversation(sessionId) {
    try {
      const resp = await fetch('/conversations')
      if (!resp.ok) return
      const data = await resp.json()
      if (data[sessionId]) {
        const newMessages = (data[sessionId].messages || []).map(m => {
          if (m.role === 'assistant') {
            return parseAssistantMessage(m)
          }
          return m
        })
        if (conversations[sessionId]) {
          const existing = conversations[sessionId]
          existing.title = data[sessionId].title
          existing.messages.splice(0, existing.messages.length, ...newMessages)
        } else {
          conversations[sessionId] = { title: data[sessionId].title, messages: newMessages }
        }
      }
    } catch (e) {
      console.error('Failed to refresh conversation:', e)
    }
  }

  // Switch conversation (refresh data first, then switch currentId)
  async function switchConversation(id) {
    if (eventSource) {
        eventSource.close();
        eventSource = null;
    }
    isStreaming.value = false
    await new Promise(resolve => setTimeout(resolve, 300))
    await refreshConversation(id)
    currentId.value = id

    // Refresh the knowledge base when switching conversations
    await refreshFileStatus(id)
    await refreshImageStatus(id)
  }

  // ════════════════════════════════════════════════════
  // Personal knowledge base
  // ════════════════════════════════════════════════════

  // ── Serial upload queue ──────────────────────────────────────────────
  // Files selected / pasted / dropped in one gesture are submitted as a
  // single list and drained one at a time, so processing order matches the
  // user's order and the backend never sees overlapping uploads from this
  // client. Each queued item pins the session id captured at enqueue time,
  // so switching conversations mid-upload never re-homes a file.
  const uploadQueue = []
  let uploadDraining = false
  let uploadDrainPromise = null
  const lastUploadSummary = ref(null)  // { ok, failed, results: [...] }

  /**
   * Submit one or more files to the current conversation's knowledge base.
   * Returns a promise resolving to the batch summary once the queue drains.
   */
  function uploadFiles(fileList) {
    const files = (Array.isArray(fileList) ? fileList : [fileList]).filter(Boolean)
    if (!files.length) return Promise.resolve(lastUploadSummary.value)

    const sessionId = currentId.value
    for (const file of files) {
      uploadQueue.push({ file, sessionId })
    }
    if (!uploadDraining) {
      return drainUploadQueue()
    }
    // A drain is already running; it will pick these up.
    return uploadDrainPromise
  }

  // Backwards-compatible single-file entry point.
  function uploadFile(file) {
    return uploadFiles([file])
  }

  async function drainUploadQueue() {
    uploadDraining = true
    isUploading.value = true
    const summary = { ok: 0, failed: 0, results: [] }

    uploadDrainPromise = (async () => {
      while (uploadQueue.length) {
        const item = uploadQueue.shift()
        try {
          const res = await uploadSingle(item.file, item.sessionId)
          summary.ok += 1
          summary.results.push({ filename: item.file.name, status: 'ok', ...res })
        } catch (e) {
          // Record the failure and keep going with the rest of the queue.
          summary.failed += 1
          summary.results.push({ filename: item.file.name, status: 'error', message: e.message })
          console.error(`Upload failed for ${item.file.name}:`, e)
        }
      }
      return summary
    })()

    let result
    try {
      result = await uploadDrainPromise
    } finally {
      uploadDrainPromise = null
      uploadDraining = false
      // Cleared only once the WHOLE queue has finished.
      isUploading.value = false
      lastUploadSummary.value = summary
    }

    if (summary.failed) {
      const lines = summary.results
        .filter(r => r.status === 'error')
        .map(r => `- ${r.filename}: ${r.message}`)
      alert(`Upload finished with ${summary.failed} failure(s):\n${lines.join('\n')}`)
    }
    return result
  }

  /**
   * Upload exactly one file into the given conversation. Throws on failure so
   * the queue can record the reason and continue with the next item.
   */
  async function uploadSingle(file, sessionId) {
    const ext = file.name.toLowerCase().split('.').pop()
    const isImage = ['jpg', 'jpeg', 'png', 'gif', 'webp'].includes(ext)

    if (!isImage && ext !== 'pdf') {
      throw new Error('Only PDF documents and images (jpg/png/gif/webp) are supported')
    }
    if (isImage && file.size > 10 * 1024 * 1024) {
      throw new Error('Image is too large. Maximum size is 10MB')
    }
    if (!isImage && file.size > 200 * 1024 * 1024) {
      throw new Error('File is too large. Maximum size is 200MB')
    }

    const formData = new FormData()
    formData.append('file', file)
    formData.append('session', sessionId)

    const resp = await fetch('/upload', {
      method: 'POST',
      body: formData
    })

    if (!resp.ok) {
      let message = 'Upload failed'
      try {
        const err = await resp.json()
        if (err && err.message) message = err.message
      } catch (e) { /* non-JSON error body */ }
      throw new Error(message)
    }

    const result = await resp.json()
    // Chips mirror the ACTIVE conversation only. A batch item whose session was
    // switched away from is still uploaded to its original session.
    const isCurrent = sessionId === currentId.value

    if (result.type === 'image') {
      if (isCurrent) {
        const imgEntry = {
          file_id: result.file_id,
          filename: result.filename,
          mime_type: result.mime_type
        }
        uploadedImages.value = [
          ...uploadedImages.value.filter(i => i.filename !== result.filename),
          imgEntry
        ]
      }
      console.log(`Image uploaded: ${result.filename}`)
      return { type: 'image', file_id: result.file_id }
    }

    if (isCurrent) {
      const entry = {
        file_id: result.file_id,
        filename: result.filename,
        chunk_count: result.chunk_count
      }
      // A re-upload supersedes the previous copy of the same filename.
      uploadedFiles.value = [
        ...uploadedFiles.value.filter(f => f.filename !== entry.filename),
        entry
      ]
    }
    console.log(`File indexed: ${result.filename} (${result.chunk_count} chunks)`)
    return { type: 'file', file_id: result.file_id, chunk_count: result.chunk_count,
             duplicate: !!result.duplicate }
  }

  /**
   * Remove a single document from the current conversation.
   */
  async function removeFile(fileId) {
    if (!fileId) return
    try {
      const resp = await fetch(`/files/${currentId.value}/${fileId}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error('Delete failed')
      uploadedFiles.value = uploadedFiles.value.filter(f => f.file_id !== fileId)
      console.log(`File removed: ${fileId}`)
    } catch (e) {
      console.error('Failed to remove file:', e)
      alert('Failed to remove file: ' + e.message)
    }
  }

  /**
   * Refresh the knowledge base listing for a session.
   */
  async function refreshFileStatus(sessionId) {
    if (!sessionId) {
      uploadedFiles.value = []
      return
    }
    try {
      const resp = await fetch(`/files/${sessionId}`)
      if (!resp.ok) return
      const data = await resp.json()
      // Attachment chips are per-turn only (cleared on send); never reload
      // the knowledge-base listing into them on refresh or conversation switch.
      uploadedFiles.value = []
    } catch (e) {
      console.error('Failed to refresh knowledge base:', e)
    }
  }

  /**
   * Remove a single image from the current conversation.
   */
  async function removeImage(fileId) {
    if (!fileId) return
    try {
      const resp = await fetch(`/image/${fileId}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error('Delete failed')
      uploadedImages.value = uploadedImages.value.filter(i => i.file_id !== fileId)
    } catch (e) {
      console.error('Failed to remove image:', e)
    }
  }

  /**
   * Refresh the image listing for a session.
   */
  async function refreshImageStatus(sessionId) {
    if (!sessionId) {
      uploadedImages.value = []
      return
    }
    try {
      const resp = await fetch(`/images/${sessionId}`)
      if (!resp.ok) return
      const data = await resp.json()
      uploadedImages.value = []
    } catch (e) {
      console.error('Failed to refresh images:', e)
    }
  }

  // ════════════════════════════════════════════════════

  async function deleteConversation(id) {
    if (conversationOrder.length <= 1) { 
      alert('Keep at least one conversation'); return 
    }
    if (!confirm('Delete this conversation?')) return
    try{
      const resp = await fetch(`/conversations/${id}`, { method: 'DELETE' })
      if (!resp.ok) throw new Error('Delete failed')
    } catch (e) {
      console.error('Failed to delete conversation:', e)
    }

    delete conversations[id]
    const idx = conversationOrder.indexOf(id)
    if (idx > -1) conversationOrder.splice(idx, 1)
    if (currentId.value === id) {
      currentId.value = conversationOrder[0]
      refreshFileStatus(currentId.value)
    }
  }

  // ── Send Message ──
  async function send() {
    const msg = inputText.value.trim()
    // Block sending while an upload batch is in flight; the draft is kept.
    if (!msg || isStreaming.value || isUploading.value) return

    inputText.value = ''
    // Per-turn attachment chips only: clear on send so the input area mirrors
    // ChatGPT/DeepSeek (attachments show only during the upload turn).
    uploadedFiles.value = []
    uploadedImages.value = []
    const conv = conversations[currentId.value]
    if (!conv) return

    conv.messages.push({ role: 'user', content: msg })

    if (conv.messages.length === 1) {
      // Title from the first message: collapse whitespace, prefer the first
      // sentence, then truncate so the sidebar stays readable.
      const cleaned = String(msg).replace(/\s+/g, ' ').trim()
      const firstSentence = cleaned.split(/[。！？!?；;]/)[0] || cleaned
      conv.title = firstSentence.length > 24 ? firstSentence.slice(0, 24) + '…' : firstSentence
    }

    // aiMsg with reasoning fields
    const aiMsg = reactive({
      role: 'assistant',
      content: '',
      intentInfo: '',
      intentDetail: '',
      toolInfo: '',
      showIntent: false,
      showTool: false,
      reasoningContent: '',
      showReasoning: false,
      reasoningDone: true,
      _backupIntentInfo: '',
      _backupToolInfo: '',
      tokenUsage: null
    })
    conv.messages.push(aiMsg)
    isStreaming.value = true
    scrollToBottom()

    eventSource = new EventSource(`/stream?msg=${encodeURIComponent(msg)}&session=${currentId.value}`)

    // SSE event handling (supports reasoning events)
    eventSource.onmessage = function(e) {
      try {
        const d = JSON.parse(e.data)

        // Intent detection → backup
        if (d.type === 'intent_info') {
          aiMsg.intentInfo = d.content
          aiMsg._backupIntentInfo = d.content
          apiKeyMissing.value = false
          return
        }

        // Retrieved passages / tool result → backup
        if (d.type === 'tool_info') {
          aiMsg.toolInfo = d.content
          aiMsg._backupToolInfo = d.content
          return
        }

        // Context token usage estimate
        if (d.type === 'usage_info') {
          aiMsg.tokenUsage = d.content
          return
        }

        // No API key configured → surface a prompt to open settings
        if (d.type === 'needs_setup') {
          apiKeyMissing.value = true
          return
        }

        // Reasoning process events
        if (d.type === 'reasoning_start') {
          aiMsg.reasoningContent = ''
          aiMsg.showReasoning = true
          aiMsg.reasoningDone = false
          scrollToBottom()
          return
        }

        if (d.type === 'reasoning_token') {
          aiMsg.reasoningContent += d.content
          scrollToBottom()
          return
        }

        if (d.type === 'reasoning_done') {
          aiMsg.reasoningDone = true
          return
        }

        // token / done / error
        if (d.type === 'token') {
          aiMsg.content += d.content
          scrollToBottom()
        } else if (d.type === 'done') {
          eventSource.close()
          eventSource = null
          isStreaming.value = false

          // Restore from backup
          if (aiMsg._backupIntentInfo && !aiMsg.intentInfo) {
            aiMsg.intentInfo = aiMsg._backupIntentInfo
          }
          if (aiMsg._backupToolInfo && !aiMsg.toolInfo) {
            aiMsg.toolInfo = aiMsg._backupToolInfo
          }
        } else if (d.type === 'error') {
          aiMsg.content = 'Error: ' + d.content
          eventSource.close()
          eventSource = null
          isStreaming.value = false
        }
      } catch (err) {
        console.error('SSE parse error:', err)
      }
    }

    // Handle abnormal disconnection
    eventSource.onerror = function() {
      if (isStreaming.value) {
        console.warn('[SSE] Connection lost')
        eventSource.close()
        eventSource = null
        isStreaming.value = false
      }
    }
  }

  function autoResize(event) {
    const el = event.target
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 120) + 'px'
  }

  // Load existing conversations (parse metadata, including reasoningContent)
  async function loadConversations() {
    try {
      const resp = await fetch('/conversations')
      const data = await resp.json()

      let hasData = false
      for (const [id, conv] of Object.entries(data)) {
        const messages = (conv.messages || []).map(m => {
          if (m.role === 'assistant') {
            return parseAssistantMessage(m)
          }
          return m
        })
        conversations[id] = { title: conv.title, messages }
        if (!conversationOrder.includes(id)) {
          conversationOrder.push(id)
        }
        hasData = true
      }

      if (hasData) {
        currentId.value = conversationOrder[0]
        refreshFileStatus(currentId.value)
      } else {
        createNewConversation()
      }
    } catch (err) {
      console.error('Failed to load conversations:', err)
      createNewConversation()
    }
  }

  return {
    conversations,
    conversationOrder,
    currentId,
    inputText,
    isStreaming,
    messagesContainer,
    currentMessages,
    chatTitle,
    uploadedFiles,
    uploadedImages,
    isUploading,
    apiKeyMissing,
    createNewConversation,
    switchConversation,
    deleteConversation,
    send,
    autoResize,
    scrollToBottom,
    loadConversations,
    refreshConversation,
    uploadFile,
    uploadFiles,
    lastUploadSummary,
    removeFile,
    refreshFileStatus,
    removeImage,
    refreshImageStatus
  }
}
