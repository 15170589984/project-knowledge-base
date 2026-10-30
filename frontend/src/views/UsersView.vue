<script setup>
import { computed, h, onMounted, reactive, ref, watch } from 'vue'
import { NButton, NDataTable, NInput, NModal, NPagination, NPopconfirm, NSelect, NSwitch, useMessage } from 'naive-ui'
import { Plus, RefreshCw } from 'lucide-vue-next'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const message = useMessage()
const users = ref([])
const roles = ref([])
const loading = ref(false)
const search = ref('')
const status = ref(null)
const page = ref(1)
const pageSize = 10
const modalOpen = ref(false)
const editingUser = ref(null)
const saving = ref(false)
const form = reactive({ username: '', display_name: '', password: '', role: 'member' })
const formError = ref('')
const roleOptions = computed(() => roles.value.filter((role) => role.is_enabled).map((role) => ({ label: role.name, value: role.key })))
const statusOptions = [{ label: '已启用', value: 'active' }, { label: '未启用', value: 'inactive' }]
const filtered = computed(() => users.value.filter((user) => {
  const term = search.value.trim().toLowerCase()
  return (!term || `${user.username} ${user.display_name}`.toLowerCase().includes(term)) &&
    (!status.value || user.is_active === (status.value === 'active'))
}))
const pageRows = computed(() => filtered.value.slice((page.value - 1) * pageSize, page.value * pageSize))
watch([search, status], () => { page.value = 1 })

async function load() {
  loading.value = true
  try {
    const [people, roleRows] = await Promise.all([api('/users'), api('/roles')])
    users.value = people
    roles.value = roleRows
    page.value = Math.min(page.value, Math.max(1, Math.ceil(filtered.value.length / pageSize)))
  } catch (cause) { message.error(cause.message) }
  finally { loading.value = false }
}
function openUser(user = null) {
  editingUser.value = user
  form.username = user?.username || ''
  form.display_name = user?.display_name || ''
  form.password = ''
  form.role = user?.role || 'member'
  formError.value = ''
  modalOpen.value = true
}
async function saveUser() {
  formError.value = ''
  saving.value = true
  try {
    if (editingUser.value) await api('/users/' + editingUser.value.id, { method: 'PATCH', body: { display_name: form.display_name, role: form.role } })
    else await api('/users', { method: 'POST', body: { ...form } })
    modalOpen.value = false
    await load()
    message.success('用户已保存')
  } catch (cause) { formError.value = cause.message }
  finally { saving.value = false }
}
async function patchUser(user, changes) {
  try { await api('/users/' + user.id, { method: 'PATCH', body: changes }); await load(); message.success('用户状态已更新') }
  catch (cause) { message.error(cause.message) }
}
async function removeUser(user) {
  try { await api('/users/' + user.id, { method: 'DELETE' }); await load(); message.success('用户已删除') }
  catch (cause) { message.error(cause.message) }
}
async function resetPassword(user) {
  try {
    const result = await api('/users/' + user.id + '/reset-password', { method: 'POST' })
    await load()
    message.success(`密码已重置为 ${result.password}`)
  } catch (cause) { message.error(cause.message) }
}
function formatDate(value) { return value ? new Date(value).toLocaleString('zh-CN') : '—' }
function resetFilters() { search.value = ''; status.value = null; page.value = 1 }
const columns = computed(() => [
  { title: '序号', key: 'index', width: 70, render: (_, index) => (page.value - 1) * pageSize + index + 1 },
  { title: '用户', key: 'username', minWidth: 190, render: (user) => h('div', { class: 'user-cell' }, [h('span', [h('strong', user.display_name), h('small', user.username)])]) },
  { title: '角色', key: 'role', minWidth: 130, render: (user) => roles.value.find((role) => role.key === user.role)?.name || user.role },
  { title: '状态', key: 'is_active', width: 110, render: (user) => h(NSwitch, { value: user.is_active, size: 'small', disabled: user.id === auth.user?.id, 'onUpdate:value': (value) => patchUser(user, { is_active: value }) }) },
  { title: '创建时间', key: 'created_at', minWidth: 170, render: (user) => formatDate(user.created_at) },
  { title: '操作', key: 'actions', width: 260, render: (user) => h('div', { class: 'row-actions' }, [
    h(NButton, { text: true, size: 'small', onClick: () => openUser(user) }, { default: () => '编辑' }),
    user.id !== auth.user?.id ? h(NPopconfirm, { positiveText: '重置', negativeText: '取消', onPositiveClick: () => resetPassword(user) }, {
      trigger: () => h(NButton, { text: true, size: 'small' }, { default: () => '重置密码' }),
      default: () => '密码将重置为默认密码 123456，该用户当前登录会话会立即失效。',
    }) : null,
    user.id !== auth.user?.id ? h(NPopconfirm, { positiveText: '删除', negativeText: '取消', onPositiveClick: () => removeUser(user) }, {
      trigger: () => h(NButton, { text: true, size: 'small', type: 'error' }, { default: () => '删除' }),
      default: () => '删除后用户无法登录，历史记录保留；有项目的用户不能删除。',
    }) : null,
  ]) },
])
onMounted(load)
</script>

<template>
  <div class="management-page system-page">
    <header class="page-header"><h1>用户管理</h1></header>
    <div class="system-filters"><n-select v-model:value="status" :options="statusOptions" placeholder="全部状态" clearable class="system-filter-select" /><n-input v-model:value="search" clearable placeholder="搜索用户名或姓名" class="system-filter-search" /><n-button @click="resetFilters">重置</n-button><div class="system-filter-actions"><n-button secondary :loading="loading" @click="load"><template #icon><refresh-cw :size="16" /></template>刷新</n-button><n-button type="primary" @click="openUser()"><template #icon><plus :size="16" /></template>新增用户</n-button></div></div>
    <n-data-table class="system-data-table" :columns="columns" :data="pageRows" :loading="loading" :bordered="false" :single-line="false" :scroll-x="900" />
    <div class="pagination-wrap"><span>共 {{ filtered.length }} 条 · 每页 {{ pageSize }} 条</span><n-pagination v-model:page="page" :page-count="Math.max(1, Math.ceil(filtered.length / pageSize))" /></div>
    <n-modal v-model:show="modalOpen" preset="card" class="small-modal" :title="editingUser ? '编辑用户' : '新增用户'"><div class="form-grid"><div class="form-row"><label class="field-label">用户名</label><n-input v-model:value="form.username" :disabled="!!editingUser" /></div><div class="form-row"><label class="field-label">显示名称</label><n-input v-model:value="form.display_name" /></div><div v-if="!editingUser" class="form-row"><label class="field-label">初始密码</label><n-input v-model:value="form.password" type="password" placeholder="至少 6 位" /></div><div class="form-row"><label class="field-label">角色</label><n-select v-model:value="form.role" :options="roleOptions" :disabled="editingUser?.id === auth.user?.id" /></div><div v-if="formError" class="form-error">{{ formError }}</div></div><template #footer><div class="modal-actions"><n-button @click="modalOpen = false">取消</n-button><n-button type="primary" :loading="saving" @click="saveUser">保存</n-button></div></template></n-modal>
  </div>
</template>
