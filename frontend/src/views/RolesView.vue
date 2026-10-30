<script setup>
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import { NButton, NCheckbox, NCheckboxGroup, NDataTable, NInput, NModal, NPagination, NPopconfirm, NSwitch, useDialog, useMessage } from 'naive-ui'
import { Pencil, Plus, Trash2 } from 'lucide-vue-next'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

const message = useMessage()
const dialog = useDialog()
const auth = useAuthStore()
const roles = ref([])
const search = ref('')
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const editing = ref(false)
const editingKey = ref(null)
const saving = ref(false)
const error = ref('')
const draft = reactive({ key: '', name: '', permissions: [] })
const permissions = [
  { value: 'view_workspace', label: '项目资料' },
  { value: 'manage_users', label: '用户管理' },
  { value: 'manage_roles', label: '角色管理' },
  { value: 'manage_menus', label: '菜单管理' },
  { value: 'manage_categories', label: '分类维护' },
  { value: 'view_logs', label: '操作日志' },
]
const filtered = computed(() => roles.value.filter((role) => `${role.name} ${role.key}`.toLowerCase().includes(search.value.trim().toLowerCase())))
const pageRows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch(search, () => { page.value = 1 })
const columns = computed(() => [
  { title: '序号', key: 'index', width: 70, render: (_, index) => (page.value - 1) * pageSize + index + 1 },
  { title: '角色名称', key: 'name', minWidth: 150 },
  { title: '标识', key: 'key', minWidth: 140 },
  { title: '用户数', key: 'user_count', width: 100 },
  { title: '系统权限', key: 'permissions', minWidth: 230, render: (role) => role.permissions.map((key) => permissions.find((item) => item.value === key)?.label || key).join('、') || '无' },
  { title: '状态', key: 'is_enabled', width: 90, render: (role) => h(NSwitch, { value: role.is_enabled, size: 'small', disabled: role.key === 'admin', 'onUpdate:value': (value) => toggle(role, value) }) },
  { title: '操作', key: 'actions', width: 140, render: (role) => h('div', { class: 'row-actions' }, [
    h(NButton, { text: true, size: 'small', onClick: () => open(role) }, { default: () => '编辑' }),
    role.is_builtin ? null : h(NPopconfirm, { positiveText: '删除', negativeText: '取消', onPositiveClick: () => remove(role) }, {
      trigger: () => h(NButton, { text: true, size: 'small', type: 'error' }, { default: () => '删除' }),
      default: () => '有用户使用时不能删除。确定删除角色？',
    }),
  ]) },
])

async function load() {
  loading.value = true
  try { roles.value = await api('/roles'); page.value = Math.min(page.value, Math.max(1, Math.ceil(filtered.value.length / pageSize))) } catch (cause) { message.error(cause.message) }
  finally { loading.value = false }
}
function open(role = null) {
  editingKey.value = role?.key || null
  draft.key = role?.key || ''
  draft.name = role?.name || ''
  draft.permissions = [...(role?.permissions || [])]
  error.value = ''
  editing.value = true
}
async function save() {
  saving.value = true
  error.value = ''
  try {
    await api(editingKey.value ? '/roles/' + editingKey.value : '/roles', {
      method: editingKey.value ? 'PUT' : 'POST',
      body: { key: draft.key, name: draft.name, permissions: draft.permissions },
    })
    editing.value = false
    await load()
    if (auth.user?.role === draft.key) await auth.refresh()
    message.success('角色已保存')
  } catch (cause) { error.value = cause.message }
  finally { saving.value = false }
}
async function remove(role) {
  try { await api('/roles/' + role.key, { method: 'DELETE' }); await load(); message.success('角色已删除') }
  catch (cause) { message.error(cause.message) }
}
async function toggle(role, value) {
  if (!value && role.user_count > 0) {
    dialog.warning({
      title: '停用角色',
      content: `停用后，${role.user_count} 名用户将立即失去该角色的页面权限。`,
      positiveText: '确认停用',
      negativeText: '取消',
      onPositiveClick: () => applyRoleStatus(role, value),
    })
    return
  }
  await applyRoleStatus(role, value)
}
async function applyRoleStatus(role, value) {
  try { await api('/roles/' + role.key + '/status', { method: 'PATCH', body: { is_enabled: value } }); await load(); message.success('角色状态已更新') }
  catch (cause) { message.error(cause.message) }
}
function resetFilters() { search.value = ''; page.value = 1 }
onMounted(load)
</script>

<template>
  <div class="management-page system-page">
    <header class="page-header"><h1>角色管理</h1></header>
    <div class="system-filters"><n-input v-model:value="search" clearable placeholder="搜索角色名称或标识" class="system-filter-search" /><n-button @click="resetFilters">重置</n-button><div class="system-filter-actions"><n-button type="primary" @click="open()"><template #icon><plus :size="16" /></template>新建角色</n-button></div></div>
    <n-data-table class="system-data-table" :columns="columns" :data="pageRows" :loading="loading" :bordered="false" :single-line="false" :scroll-x="900" />
    <div class="pagination-wrap"><span>共 {{ filtered.length }} 条 · 每页 {{ pageSize }} 条</span><n-pagination v-model:page="page" :page-count="Math.max(1, Math.ceil(filtered.length / pageSize))" /></div>
    <n-modal v-model:show="editing" preset="card" class="small-modal" :title="editingKey ? '编辑角色' : '新建角色'">
      <div class="form-grid"><div class="form-row"><label class="field-label">角色标识</label><n-input v-model:value="draft.key" :disabled="!!editingKey" placeholder="例如：reviewer" /></div><div class="form-row"><label class="field-label">角色名称</label><n-input v-model:value="draft.name" placeholder="例如：资料审核" /></div><div class="form-row"><label class="field-label">系统权限</label><n-checkbox-group v-model:value="draft.permissions"><div class="permission-grid"><n-checkbox v-for="item in permissions" :key="item.value" :value="item.value">{{ item.label }}</n-checkbox></div></n-checkbox-group></div><div v-if="error" class="form-error">{{ error }}</div></div>
      <template #footer><div class="modal-actions"><n-button @click="editing = false">取消</n-button><n-button type="primary" :loading="saving" @click="save">保存</n-button></div></template>
    </n-modal>
  </div>
</template>
