<script setup>
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import { NButton, NDataTable, NInput, NInputNumber, NModal, NPagination, NPopconfirm, NSelect, NSwitch, useMessage } from 'naive-ui'
import { Pencil, Plus, Trash2 } from 'lucide-vue-next'
import { api } from '../api'

const message = useMessage()
const menus = ref([])
const search = ref('')
const page = ref(1)
const pageSize = 10
const editing = ref(false)
const editingKey = ref(null)
const saving = ref(false)
const error = ref('')
const draft = reactive({ key: '', label: '', path: '/workspace', sort_order: 0, is_enabled: true })
const pages = [
  { label: '项目资料', value: '/workspace' }, { label: '用户管理', value: '/users' },
  { label: '角色管理', value: '/roles' }, { label: '菜单管理', value: '/menus' }, { label: '操作日志', value: '/logs' },
]
const filtered = computed(() => menus.value.filter((menu) => `${menu.label} ${menu.key} ${menu.path}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const pageRows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch(search, () => { page.value = 1 })
const columns = computed(() => [
  { title: '序号', key: 'index', width: 70, render: (_, index) => (page.value - 1) * pageSize + index + 1 },
  { title: '菜单名称', key: 'label', minWidth: 150 },
  { title: '标识', key: 'key', minWidth: 150 },
  { title: '目标页面', key: 'path', minWidth: 160 },
  { title: '排序', key: 'sort_order', width: 90 },
  { title: '状态', key: 'is_enabled', width: 90, render: (menu) => h(NSwitch, { value: menu.is_enabled, size: 'small', 'onUpdate:value': (value) => toggle(menu, value) }) },
  { title: '操作', key: 'actions', width: 150, render: (menu) => h('div', { class: 'row-actions' }, [
    h(NButton, { text: true, size: 'small', onClick: () => open(menu) }, { default: () => '编辑' }),
    menu.is_builtin ? null : h(NPopconfirm, { positiveText: '删除', negativeText: '取消', onPositiveClick: () => remove(menu) }, {
      trigger: () => h(NButton, { text: true, size: 'small', type: 'error' }, { default: () => '删除' }),
      default: () => '确定删除菜单？',
    }),
  ]) },
])
async function load() {
  try { menus.value = await api('/menus'); page.value = Math.min(page.value, Math.max(1, Math.ceil(filtered.value.length / pageSize))); window.dispatchEvent(new Event('kb:menus-changed')) } catch (cause) { message.error(cause.message) }
}
function open(menu = null) {
  editingKey.value = menu?.key || null
  Object.assign(draft, menu || { key: '', label: '', path: '/workspace', sort_order: 0, is_enabled: true })
  error.value = ''
  editing.value = true
}
async function save() {
  saving.value = true
  error.value = ''
  const existing = !!editingKey.value
  try {
    await api(existing ? '/menus/' + draft.key : '/menus', {
      method: existing ? 'PATCH' : 'POST',
      body: existing ? { label: draft.label, path: draft.path, sort_order: draft.sort_order, is_enabled: draft.is_enabled } : { ...draft },
    })
    editing.value = false
    await load()
    message.success('菜单已保存')
  } catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
async function toggle(menu, value) {
  try { await api('/menus/' + menu.key, { method: 'PATCH', body: { is_enabled: value } }); await load() }
  catch (cause) { message.error(cause.message) }
}
async function remove(menu) {
  try { await api('/menus/' + menu.key, { method: 'DELETE' }); await load(); message.success('菜单已删除') }
  catch (cause) { message.error(cause.message) }
}
function resetFilters() { search.value = ''; page.value = 1 }
onMounted(load)
</script>

<template>
  <div class="management-page system-page">
    <header class="page-header"><h1>菜单管理</h1></header>
    <div class="system-filters"><n-input v-model:value="search" clearable placeholder="搜索菜单名称、标识或页面" class="system-filter-search" /><n-button @click="resetFilters">重置</n-button><div class="system-filter-actions"><n-button type="primary" @click="open()"><template #icon><plus :size="16" /></template>新建菜单</n-button></div></div>
    <n-data-table class="system-data-table" :columns="columns" :data="pageRows" :bordered="false" :single-line="false" :scroll-x="900" />
    <div class="pagination-wrap"><span>共 {{ filtered.length }} 条 · 每页 {{ pageSize }} 条</span><n-pagination v-model:page="page" :page-count="Math.max(1, Math.ceil(filtered.length / pageSize))" /></div>
    <n-modal v-model:show="editing" preset="card" class="small-modal" :title="editingKey ? '编辑菜单' : '新建菜单'"><div class="form-grid"><div class="form-row"><label class="field-label">菜单标识</label><n-input v-model:value="draft.key" :disabled="!!editingKey" placeholder="例如：workspace_alt" /></div><div class="form-row"><label class="field-label">显示名称</label><n-input v-model:value="draft.label" /></div><div class="form-row"><label class="field-label">目标页面</label><n-select v-model:value="draft.path" :options="pages" :disabled="!!editingKey && menus.find((item) => item.key === editingKey)?.is_builtin" /></div><div class="form-row short-number"><label class="field-label">排序</label><n-input-number v-model:value="draft.sort_order" :min="-9999" :max="9999" /></div><div v-if="error" class="form-error">{{ error }}</div></div><template #footer><div class="modal-actions"><n-button @click="editing = false">取消</n-button><n-button type="primary" :loading="saving" @click="save">保存</n-button></div></template></n-modal>
  </div>
</template>
