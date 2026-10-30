<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { NButton, NCheckbox, NInput, NInputNumber, NModal, NSelect, useDialog, useMessage } from 'naive-ui'
import { Plus, Save as SaveIcon, Table2, Trash2, X } from 'lucide-vue-next'
import { api } from '../api'
import { createTable, parseTable, resizeTable, serializeTable } from '../tableField'

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
const dialog = useDialog()
const saving = ref(false)
const error = ref('')
const form = reactive({ project_id: null, category_id: null, title: '', environment: '', content: '' })
const fields = ref([])
const tableOpen = ref(false)
const tableField = ref(null)
const tableRows = ref([])
const tableRowCount = ref(2)
const tableColumnCount = ref(3)
const fieldTypes = [
  { label: '文本', value: 'text' },
  { label: '网址', value: 'url' },
  { label: '多行文本', value: 'textarea' },
  { label: '密码', value: 'password' },
  { label: '表格', value: 'table' },
]
const projectOptions = computed(() => props.projects.filter((item) => item.is_owner).map((item) => ({ label: item.name, value: item.id })))
const categoryOptions = computed(() => props.categories.map((item) => ({ label: item.name, value: item.id })))
const environmentOptions = computed(() => {
  const options = [...props.environments]
  const previous = props.entry?.environment
  if (previous && !options.some((option) => option.value === previous)) {
    options.push({ value: previous, label: previous + '（旧环境）' })
  }
  return options
})

watch(
  () => [props.show, props.entry, props.initialProjectId, props.initialCategoryId],
  () => {
    if (!props.show) return
    form.project_id = props.entry?.project_id || props.initialProjectId || projectOptions.value[0]?.value || null
    form.category_id = props.entry?.category_id || props.initialCategoryId || categoryOptions.value[0]?.value || null
    form.title = props.entry?.title || ''
    form.environment = props.entry?.environment || null
    form.content = props.entry?.content || ''
    fields.value = (props.entry?.fields || []).map((field) => ({
      id: field.id, label: field.label, field_type: field.field_type,
      is_sensitive: field.is_sensitive, value: field.is_sensitive ? null : field.value || '',
      keep_existing: field.is_sensitive && field.has_value,
    }))
    error.value = ''
  },
  { immediate: true },
)

function addField(label = '', field_type = 'text') {
  fields.value.push({ label, field_type, is_sensitive: field_type === 'password', value: '', keep_existing: false })
}

function changeFieldType(field, type) {
  if (type === field.field_type) return
  const apply = () => {
    if (type === 'table' || field.field_type === 'table' || field.keep_existing) {
      field.value = type === 'table' ? serializeTable(createTable()) : ''
      field.keep_existing = false
    }
    field.field_type = type
    if (type === 'password') field.is_sensitive = true
    if (type === 'table') field.is_sensitive = false
  }
  if (field.value || field.keep_existing) {
    dialog.warning({ title: '切换字段类型', content: '切换类型会清空当前字段值。', positiveText: '切换并清空', negativeText: '取消', onPositiveClick: apply })
  } else apply()
}

async function setSensitive(field, checked) {
  if (!checked && field.keep_existing && field.id && props.entry) {
    field.busy = true
    try {
      const result = await api('/entries/' + props.entry.id + '/reveal', { method: 'POST', body: { field_id: field.id, purpose: 'view' } })
      if (result.unavailable) throw new Error('隐藏值无法解密，未更改隐藏状态')
      field.value = result.value
      field.keep_existing = false
      field.is_sensitive = false
    } catch (cause) { message.error(cause.message) }
    finally { field.busy = false }
    return
  }
  field.is_sensitive = checked
}

function previewTable(field) {
  if (field.keep_existing) return ['已保存隐藏表格']
  const rows = parseTable(field.value)
  return rows ? rows[0] : ['表格数据无效']
}

async function editTable(field) {
  if (field.keep_existing && field.id && props.entry) {
    field.busy = true
    try {
      const result = await api('/entries/' + props.entry.id + '/reveal', { method: 'POST', body: { field_id: field.id, purpose: 'view' } })
      if (result.unavailable) throw new Error('表格无法解密')
      field.value = result.value
      field.keep_existing = false
    } catch (cause) { message.error(cause.message); return }
    finally { field.busy = false }
  }
  const rows = field.value ? parseTable(field.value) : createTable()
  if (!rows) { message.error('表格数据无效，无法编辑'); return }
  tableField.value = field
  tableRows.value = rows.map((row) => [...row])
  tableRowCount.value = rows.length
  tableColumnCount.value = rows[0].length
  tableOpen.value = true
}

function changeTableSize(rowCount, columnCount) {
  if (!rowCount || !columnCount) return
  tableRowCount.value = rowCount
  tableColumnCount.value = columnCount
  tableRows.value = resizeTable(tableRows.value, rowCount, columnCount)
}

function saveTable() {
  if (serializeTable(tableRows.value).length > 10000) { message.error('表格内容不能超过 10000 字符'); return }
  tableField.value.value = serializeTable(tableRows.value)
  tableField.value.keep_existing = false
  tableOpen.value = false
}

async function save() {
  error.value = ''
  if (fields.value.some((field) => field.busy)) return
  if (!form.project_id || !form.category_id || !form.title.trim()) {
    error.value = '请选择项目、分类并填写标题'
    return
  }
  if (fields.value.some((field) => !field.label.trim())) {
    error.value = '请填写所有字段名称'
    return
  }
  const body = {
    title: form.title.trim(),
    environment: form.environment || null,
    content: form.content || null,
    fields: fields.value.map((field) => ({
      ...(field.id ? { id: field.id } : {}), label: field.label.trim(), field_type: field.field_type,
      is_sensitive: field.is_sensitive, value: field.keep_existing ? null : field.value || null,
      keep_existing: field.keep_existing,
    })),
  }
  if (!props.entry) {
    body.project_id = form.project_id
    body.category_id = form.category_id
  } else if (form.environment === props.entry.environment) {
    delete body.environment
  }
  saving.value = true
  try {
    const result = await api(props.entry ? '/entries/' + props.entry.id : '/entries', {
      method: props.entry ? 'PATCH' : 'POST',
      body,
    })
    message.success(props.entry ? '条目已更新' : '条目已创建')
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
  <n-modal :show="show" preset="card" class="entry-modal" :title="entry ? '编辑条目' : '新建条目'" :mask-closable="false" @close="emit('close')">
    <div class="form-grid">
      <div class="form-row two-columns">
        <div>
          <label class="field-label">所属项目</label>
          <n-select v-model:value="form.project_id" :options="projectOptions" placeholder="选择项目" :disabled="!!entry" />
        </div>
        <div>
          <label class="field-label">分类</label>
          <n-select v-model:value="form.category_id" :options="categoryOptions" placeholder="选择分类" :disabled="!!entry" />
        </div>
      </div>
      <div class="form-row two-columns">
        <div>
          <label class="field-label">条目名称 <span class="required">*</span></label>
          <n-input v-model:value="form.title" maxlength="160" placeholder="例如：生产数据库" />
        </div>
        <div>
          <label class="field-label">环境</label>
          <n-select v-model:value="form.environment" :options="environmentOptions" placeholder="不区分环境" clearable />
        </div>
      </div>
      <div class="form-row">
        <label class="field-label">备注</label>
        <n-input v-model:value="form.content" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" placeholder="补充说明" />
      </div>
      <div class="dynamic-fields">
        <div class="form-divider"><span>自定义字段</span><n-button size="small" secondary @click="addField()"><template #icon><plus :size="15" /></template>添加字段</n-button></div>
        <div class="quick-fields">
          <n-button size="tiny" tertiary @click="addField('地址', 'url')">+ 地址</n-button>
          <n-button size="tiny" tertiary @click="addField('账号')">+ 账号</n-button>
          <n-button size="tiny" tertiary @click="addField('密码', 'password')">+ 密码</n-button>
          <n-button size="tiny" tertiary @click="addField('谷歌验证码', 'password')">+ 谷歌验证码</n-button>
        </div>
        <div v-for="(field, index) in fields" :key="field.id || index" class="entry-field-editor">
          <n-input v-model:value="field.label" placeholder="字段名称" />
          <n-select :value="field.field_type" :options="fieldTypes" @update:value="(value) => changeFieldType(field, value)" />
          <button v-if="field.field_type === 'table'" type="button" class="table-field-preview" :disabled="field.busy" @click="editTable(field)"><table2 :size="16" /><span v-for="(cell, cellIndex) in previewTable(field)" :key="cellIndex" class="table-preview-cell">{{ cell || '空' }}</span></button>
          <n-input v-else v-model:value="field.value" :type="field.is_sensitive ? 'password' : field.field_type === 'textarea' ? 'textarea' : 'text'" :placeholder="field.keep_existing ? '已保存隐藏值' : '字段值'" @update:value="field.keep_existing = false" />
          <n-checkbox :checked="field.is_sensitive" :disabled="field.busy" @update:checked="(checked) => setSensitive(field, checked)">隐藏</n-checkbox>
          <button class="icon-button danger" :aria-label="'删除字段 ' + field.label" @click="fields.splice(index, 1)"><trash2 :size="17" /></button>
        </div>
        <div v-if="!fields.length" class="muted">尚未添加字段</div>
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
  <n-modal v-model:show="tableOpen" preset="card" class="table-editor-modal" :title="tableField?.label || '编辑表格'" :mask-closable="false">
    <div class="table-size-controls"><label>行数 <n-input-number :value="tableRowCount" :min="1" :max="30" @update:value="(value) => changeTableSize(value, tableColumnCount)" /></label><label>列数 <n-input-number :value="tableColumnCount" :min="1" :max="20" @update:value="(value) => changeTableSize(tableRowCount, value)" /></label></div>
    <div class="table-editor-scroll"><div v-for="(row, rowIndex) in tableRows" :key="rowIndex" class="table-editor-row"><span class="table-row-number">{{ rowIndex + 1 }}</span><n-input v-for="(_, columnIndex) in row" :key="columnIndex" v-model:value="tableRows[rowIndex][columnIndex]" :placeholder="rowIndex === 0 ? '列 ' + (columnIndex + 1) : ''" /></div></div>
    <template #footer><div class="modal-actions"><n-button @click="tableOpen = false">取消</n-button><n-button type="primary" @click="saveTable">确定</n-button></div></template>
  </n-modal>
</template>
