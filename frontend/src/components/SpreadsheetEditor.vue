<script setup>
import { nextTick, reactive, ref, watch } from 'vue'
import { NButton, NInput, NModal, NSelect, useMessage } from 'naive-ui'
import {
  ArrowDownToLine, ArrowRightToLine, Minus, Save as SaveIcon, X,
} from 'lucide-vue-next'
import { api } from '../api'
import {
  SHEET_LIMITS, columnLabel, createSheet, parseClipboardGrid, parseSheet, serializeSheet,
} from '../sheet'

const props = defineProps({
  show: Boolean,
  entry: { type: Object, default: null },
  projects: { type: Array, required: true },
  categories: { type: Array, required: true },
  environments: { type: Array, required: true },
  initialProjectId: { type: Number, default: 0 },
  initialCategoryId: { type: Number, default: 0 },
})
const emit = defineEmits(['close', 'saved'])
const message = useMessage()
const saving = ref(false)
const error = ref('')
const rows = ref(createSheet())
const active = ref({ row: 0, column: 0 })
const cellRefs = new Map()
const form = reactive({ project_id: null, category_id: null, title: '', environment: '', content: '' })

const projectOptions = () => props.projects.filter((item) => item.is_owner).map((item) => ({ label: item.name, value: item.id }))
const categoryOptions = () => props.categories.map((item) => ({ label: item.name, value: item.id }))
const environmentOptions = () => {
  const options = [...props.environments]
  const previous = props.entry?.environment
  if (previous && !options.some((option) => option.value === previous)) {
    options.push({ value: previous, label: previous + '（旧环境）' })
  }
  return options
}

watch(
  () => [props.show, props.entry?.id],
  async () => {
    if (!props.show) return
    form.project_id = props.entry?.project_id || props.initialProjectId || props.projects.find((item) => item.is_owner)?.id || null
    form.category_id = props.entry?.category_id || props.initialCategoryId || props.categories[0]?.id || null
    form.title = props.entry?.title || ''
    form.environment = props.entry?.environment || null
    form.content = props.entry?.content || ''
    error.value = ''
    let value = props.entry?.sheet_json
    if (props.entry && !value) {
      try {
        value = (await api('/entries/' + props.entry.id)).sheet_json
      } catch (cause) {
        error.value = cause.message
      }
    }
    rows.value = parseSheet(value) || createSheet()
    active.value = { row: 0, column: 0 }
  },
  { immediate: true },
)

function setCellRef(element, row, column) {
  const key = row + ':' + column
  if (element) cellRefs.set(key, element)
  else cellRefs.delete(key)
}

function focusCell(row, column) {
  const maxRow = rows.value.length - 1
  const maxColumn = (rows.value[0]?.length || 1) - 1
  const target = { row: Math.max(0, Math.min(row, maxRow)), column: Math.max(0, Math.min(column, maxColumn)) }
  active.value = target
  nextTick(() => {
    const element = cellRefs.get(target.row + ':' + target.column)
    element?.focus()
    element?.select()
  })
}

function onKeydown(event, row, column) {
  if (event.isComposing) return
  if (event.key === 'Enter' || event.key === 'ArrowDown') {
    event.preventDefault()
    focusCell(row + 1, column)
    return
  }
  if (event.key === 'ArrowUp') {
    event.preventDefault()
    focusCell(row - 1, column)
    return
  }
  if (event.key === 'ArrowRight' && event.target.selectionStart === event.target.value.length) {
    event.preventDefault()
    focusCell(row, column + 1)
    return
  }
  if (event.key === 'ArrowLeft' && event.target.selectionStart === 0) {
    event.preventDefault()
    focusCell(row, column - 1)
  }
}

function onPaste(event, row, column) {
  const text = event.clipboardData?.getData('text/plain') || ''
  if (!text.includes('\t') && !text.replace(/\n$/, '').includes('\n')) return
  event.preventDefault()
  applyGrid(parseClipboardGrid(text), row, column)
}

function applyGrid(grid, startRow, startColumn) {
  const width = Math.max(...grid.map((line) => line.length))
  const neededRows = Math.max(rows.value.length, startRow + grid.length)
  const neededColumns = Math.max(rows.value[0]?.length || 1, startColumn + width)
  if (neededRows > SHEET_LIMITS.rows || neededColumns > SHEET_LIMITS.columns) {
    message.warning(`表格最多 ${SHEET_LIMITS.rows} 行、${SHEET_LIMITS.columns} 列`)
    return
  }
  const next = rows.value.map((line) => [...line])
  while (next.length < neededRows) next.push(Array(neededColumns).fill(''))
  for (const line of next) while (line.length < neededColumns) line.push('')
  grid.forEach((line, rowOffset) => line.forEach((cell, columnOffset) => {
    next[startRow + rowOffset][startColumn + columnOffset] = cell
  }))
  rows.value = next
  focusCell(startRow, startColumn)
}

function addRow() {
  if (rows.value.length >= SHEET_LIMITS.rows) {
    message.warning(`最多 ${SHEET_LIMITS.rows} 行`)
    return
  }
  const width = rows.value[0]?.length || 1
  const at = active.value.row + 1
  rows.value.splice(at, 0, Array(width).fill(''))
  focusCell(at, active.value.column)
}

function removeRow() {
  if (rows.value.length <= 1) {
    message.warning('至少保留 1 行')
    return
  }
  rows.value.splice(active.value.row, 1)
  focusCell(active.value.row, active.value.column)
}

function addColumn() {
  const width = rows.value[0]?.length || 0
  if (width >= SHEET_LIMITS.columns) {
    message.warning(`最多 ${SHEET_LIMITS.columns} 列`)
    return
  }
  const at = active.value.column + 1
  rows.value = rows.value.map((line) => {
    const next = [...line]
    next.splice(at, 0, '')
    return next
  })
  focusCell(active.value.row, at)
}

function removeColumn() {
  const width = rows.value[0]?.length || 0
  if (width <= 1) {
    message.warning('至少保留 1 列')
    return
  }
  rows.value = rows.value.map((line) => {
    const next = [...line]
    next.splice(active.value.column, 1)
    return next
  })
  focusCell(active.value.row, active.value.column - 1)
}

async function save() {
  error.value = ''
  if (!form.project_id || !form.category_id || !form.title.trim()) {
    error.value = '请选择项目、分类并填写表格名称'
    return
  }
  const value = serializeSheet(rows.value)
  if (value.length > 500000) {
    error.value = '表格内容过大，请精简后再保存'
    return
  }
  const body = {
    title: form.title.trim(),
    environment: form.environment || null,
    content: form.content || null,
    sheet_json: value,
  }
  if (!props.entry) {
    body.project_id = form.project_id
    body.category_id = form.category_id
    body.kind = 'spreadsheet'
  }
  saving.value = true
  try {
    const result = await api(props.entry ? '/entries/' + props.entry.id : '/entries', {
      method: props.entry ? 'PATCH' : 'POST',
      body,
    })
    message.success(props.entry ? '表格已更新' : '表格已创建')
    emit('saved', result)
    emit('close')
  } catch (cause) {
    error.value = cause.message
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <n-modal :show="show" preset="card" class="sheet-editor-modal" :title="entry ? '编辑表格' : '新建表格'" :mask-closable="false" @close="emit('close')">
    <div class="form-grid">
      <div class="form-row two-columns">
        <div>
          <label class="field-label">所属项目</label>
          <n-select v-model:value="form.project_id" :options="projectOptions()" placeholder="选择项目" :disabled="!!entry" />
        </div>
        <div>
          <label class="field-label">分类</label>
          <n-select v-model:value="form.category_id" :options="categoryOptions()" placeholder="选择分类" :disabled="!!entry" />
        </div>
      </div>
      <div class="form-row two-columns">
        <div>
          <label class="field-label">表格名称 <span class="required">*</span></label>
          <n-input v-model:value="form.title" maxlength="160" placeholder="例如：上线检查清单" />
        </div>
        <div>
          <label class="field-label">环境</label>
          <n-select v-model:value="form.environment" :options="environmentOptions()" placeholder="不区分环境" clearable />
        </div>
      </div>
      <div class="form-row">
        <label class="field-label">备注</label>
        <n-input v-model:value="form.content" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="补充说明" />
      </div>
      <div class="sheet-toolbar">
        <n-button size="small" secondary @click="addRow"><template #icon><arrow-down-to-line :size="15" /></template>插入行</n-button>
        <n-button size="small" secondary @click="removeRow"><template #icon><minus :size="15" /></template>删除行</n-button>
        <n-button size="small" secondary @click="addColumn"><template #icon><arrow-right-to-line :size="15" /></template>插入列</n-button>
        <n-button size="small" secondary @click="removeColumn"><template #icon><minus :size="15" /></template>删除列</n-button>
        <span class="sheet-meta">{{ rows.length }} 行 × {{ rows[0]?.length || 0 }} 列 · 支持从 Excel 粘贴</span>
      </div>
      <div class="sheet-grid">
        <table class="sheet-table">
          <thead>
            <tr>
              <th></th>
              <th v-for="(_, column) in rows[0]" :key="column">{{ columnLabel(column) }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, rowIndex) in rows" :key="rowIndex">
              <th>{{ rowIndex + 1 }}</th>
              <td v-for="(_, columnIndex) in row" :key="columnIndex" :class="{ active: active.row === rowIndex && active.column === columnIndex }">
                <input
                  :ref="(element) => setCellRef(element, rowIndex, columnIndex)"
                  v-model="rows[rowIndex][columnIndex]"
                  class="sheet-cell"
                  @focus="active = { row: rowIndex, column: columnIndex }"
                  @keydown="onKeydown($event, rowIndex, columnIndex)"
                  @paste="onPaste($event, rowIndex, columnIndex)"
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="error" class="form-error" role="alert">{{ error }}</div>
    </div>
    <template #footer>
      <div class="modal-actions">
        <n-button @click="emit('close')"><template #icon><x :size="16" /></template>取消</n-button>
        <n-button type="primary" :loading="saving" @click="save"><template #icon><save-icon :size="16" /></template>保存</n-button>
      </div>
    </template>
  </n-modal>
</template>
