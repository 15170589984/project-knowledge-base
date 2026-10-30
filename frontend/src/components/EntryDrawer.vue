<script setup>
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { NButton, NDrawer, NDrawerContent, NPopconfirm, NTag, NTooltip, useMessage } from 'naive-ui'
import { Clipboard, Eye, EyeOff, Pencil, Trash2 } from 'lucide-vue-next'
import { api } from '../api'
import { copyText } from '../clipboard'
import { parseTable } from '../tableField'
import { parseSheet } from '../sheet'
import { sanitizeHtml } from '../sanitize'

const KIND_LABELS = { entry: '条目', document: '文档', spreadsheet: '表格' }
const KIND_TAG_TYPES = { entry: 'default', document: 'info', spreadsheet: 'success' }

const props = defineProps({
  show: Boolean,
  entry: { type: Object, default: null },
})
const emit = defineEmits(['close', 'edit', 'deleted'])
const message = useMessage()
const revealed = reactive({})
const timers = new Map()
const deleting = ref(false)
const safeBody = computed(() => sanitizeHtml(props.entry?.body))
const sheetRows = computed(() => parseSheet(props.entry?.sheet_json))

function clearRevealed() {
  for (const timer of timers.values()) clearTimeout(timer)
  timers.clear()
  for (const key of Object.keys(revealed)) delete revealed[key]
}

watch(() => [props.show, props.entry?.id], clearRevealed)
onBeforeUnmount(clearRevealed)

async function reveal(field, purpose) {
  try {
    const result = await api('/entries/' + props.entry.id + '/reveal', {
      method: 'POST',
      body: { field_id: field.id, purpose },
    })
    if (result.unavailable) {
      if (purpose === 'view') revealed[field.id] = result.placeholder
      message.error('此字段无法解密，请检查加密密钥')
      return
    }
    if (purpose === 'copy') {
      if (await copyText(result.value)) message.success('已复制')
    } else {
      revealed[field.id] = result.value
      if (timers.has(field.id)) clearTimeout(timers.get(field.id))
      timers.set(field.id, setTimeout(() => {
        delete revealed[field.id]
        timers.delete(field.id)
      }, 30000))
    }
  } catch (error) {
    message.error(error.message)
  }
}

async function remove() {
  deleting.value = true
  try {
    await api('/entries/' + props.entry.id, { method: 'DELETE' })
    message.success('条目已删除')
    emit('deleted')
    emit('close')
  } catch (error) {
    message.error(error.message)
  } finally {
    deleting.value = false
  }
}

async function copyField(field) {
  if (field.is_sensitive) {
    if (!field.has_value) {
      message.warning('该字段没有值')
      return
    }
    await reveal(field, 'copy')
    return
  }
  if (!field.value) {
    message.warning('该字段没有值')
    return
  }
  try {
    if (await copyText(field.value)) message.success('已复制')
  } catch (error) {
    message.error(error.message)
  }
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString('zh-CN') : '—'
}

function tableRows(field) {
  return parseTable(field.is_sensitive ? revealed[field.id] : field.value)
}
</script>

<template>
  <n-drawer :show="show" width="min(580px, 100vw)" placement="right" @update:show="(value) => { if (!value) emit('close') }">
    <n-drawer-content :title="entry?.title || '条目详情'" closable>
      <template v-if="entry">
        <div class="detail-meta">
          <n-tag size="small" :bordered="false" :type="KIND_TAG_TYPES[entry.kind] || 'default'">{{ KIND_LABELS[entry.kind] || '条目' }}</n-tag>
          <n-tag size="small" :bordered="false" type="success">{{ entry.project_name }}</n-tag>
          <n-tag size="small" :bordered="false">{{ entry.category_name }}</n-tag>
          <n-tag v-if="entry.environment" size="small" :bordered="false" type="warning">{{ entry.environment }}</n-tag>
        </div>
        <div v-if="entry.content" class="detail-note">{{ entry.content }}</div>
        <template v-if="entry.kind === 'document'">
          <div class="detail-section-title">文档内容</div>
          <div v-if="safeBody" class="rich-viewer" v-html="safeBody"></div>
          <div v-else class="muted">文档内容为空</div>
        </template>
        <template v-else-if="entry.kind === 'spreadsheet'">
          <div class="detail-section-title">表格内容</div>
          <div v-if="sheetRows" class="detail-table-scroll">
            <table class="detail-table">
              <thead><tr><th v-for="(cell, index) in sheetRows[0]" :key="index">{{ cell }}</th></tr></thead>
              <tbody><tr v-for="(row, rowIndex) in sheetRows.slice(1)" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td></tr></tbody>
            </table>
          </div>
          <span v-else class="danger">表格数据无效</span>
        </template>
        <template v-else>
          <div class="detail-section-title">字段</div>
          <div v-if="!entry.fields?.length" class="muted">此条目没有自定义字段</div>
          <div v-for="field in entry.fields" :key="field.id" class="detail-field">
            <div class="detail-label">
              {{ field.label }}
              <button class="icon-button compact" :aria-label="'复制 ' + field.label" @click="copyField(field)"><clipboard :size="14" /></button>
              <template v-if="field.is_sensitive && field.has_value && entry.can_edit">
                <button v-if="revealed[field.id]" class="icon-button compact" aria-label="隐藏敏感值" @click="delete revealed[field.id]"><eye-off :size="14" /></button>
                <button v-else class="icon-button compact" aria-label="显示敏感值" @click="reveal(field, 'view')"><eye :size="14" /></button>
              </template>
            </div>
            <div v-if="field.field_type === 'table'">
              <div v-if="field.is_sensitive && !revealed[field.id]" class="secret-line">
                <span v-if="!field.has_value" class="muted">未设置</span><span v-else class="secret-mask">●●●●●●</span>
              </div>
              <template v-else>
                <div v-if="tableRows(field)" class="detail-table-scroll"><table class="detail-table"><thead><tr><th v-for="(cell, index) in tableRows(field)[0]" :key="index">{{ cell }}</th></tr></thead><tbody><tr v-for="(row, rowIndex) in tableRows(field).slice(1)" :key="rowIndex"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ cell }}</td></tr></tbody></table></div>
                <span v-else class="danger">表格数据无效</span>
              </template>
            </div>
            <div v-else-if="field.is_sensitive" class="secret-line">
              <span v-if="!field.has_value" class="muted">未设置</span>
              <span v-else-if="revealed[field.id]" class="secret-value">{{ revealed[field.id] }}</span>
              <span v-else class="secret-mask">●●●●●●</span>
            </div>
            <a v-else-if="field.field_type === 'url' && field.value" class="detail-link" :href="field.value" target="_blank" rel="noopener noreferrer">{{ field.value }}</a>
            <div v-else class="detail-value" :class="{ muted: !field.value }">{{ field.value || '—' }}</div>
          </div>
        </template>
        <div class="detail-section-title">记录</div>
        <div class="record-grid">
          <span>创建人</span><strong>{{ entry.created_by_name || '—' }}</strong>
          <span>创建时间</span><strong>{{ formatDate(entry.created_at) }}</strong>
          <span>最后修改</span><strong>{{ entry.updated_by_name || '—' }}</strong>
          <span>修改时间</span><strong>{{ formatDate(entry.updated_at) }}</strong>
        </div>
      </template>
      <template #footer>
        <div v-if="entry?.can_edit" class="drawer-actions">
          <n-button @click="emit('edit')"><template #icon><pencil :size="16" /></template>编辑</n-button>
          <n-popconfirm positive-text="删除" negative-text="取消" @positive-click="remove">
            <template #trigger><n-button type="error" ghost :loading="deleting"><template #icon><trash2 :size="16" /></template>删除</n-button></template>
            确定删除这条信息？
          </n-popconfirm>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>
