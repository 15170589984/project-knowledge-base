<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { NButton, NDataTable, NInput, NPagination, NSelect, useMessage } from 'naive-ui'
import { RefreshCw } from 'lucide-vue-next'
import { api, queryString } from '../api'

const message = useMessage()
const rows = ref([])
const page = ref(1)
const pageSize = 10
const total = ref(0)
const type = ref(null)
const search = ref('')
const query = ref('')
const loading = ref(false)
let searchTimer
let loadId = 0
const types = [
  { label: '项目', value: 'project' }, { label: '条目', value: 'entry' },
  { label: '用户', value: 'user' }, { label: '角色', value: 'role' },
  { label: '菜单', value: 'menu' }, { label: '分类', value: 'category' }, { label: '登录与账号', value: 'auth' },
]
const actions = {
  create: '新建', update: '修改', delete: '删除', archive: '删除', update_user: '修改用户',
  reset_user_password: '重置密码',
  enable: '启用', disable: '停用', login: '登录', change_password: '修改密码',
  recover_password: '恢复密码', rotate_recovery_codes: '更新恢复码',
  share: '分享', revoke_share: '撤销分享', reveal_view: '查看隐藏值', reveal_copy: '复制隐藏值',
}
const columns = computed(() => [
  { title: '类型', key: 'target_type', minWidth: 100, render: (row) => types.find((item) => item.value === row.target_type)?.label || row.target_type },
  { title: '对象', key: 'object_name', minWidth: 200 },
  { title: '动作', key: 'action', minWidth: 140, render: (row) => actions[row.action] || row.action },
  { title: '操作人', key: 'username', minWidth: 130 },
  { title: '时间', key: 'created_at', minWidth: 180, render: (row) => new Date(row.created_at).toLocaleString('zh-CN') },
])
async function load() {
  const current = ++loadId
  loading.value = true
  try {
    const result = await api('/admin/audit-logs?' + queryString({ page: page.value, page_size: pageSize, target_type: type.value, q: query.value || null }))
    if (current === loadId) { rows.value = result.items; total.value = result.total }
  } catch (cause) { if (current === loadId) message.error(cause.message) }
  finally { if (current === loadId) loading.value = false }
}
watch(page, load)
watch(type, () => { if (page.value === 1) load(); else page.value = 1 })
watch(search, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { query.value = value.trim(); if (page.value === 1) load(); else page.value = 1 }, 300)
})
onMounted(load)
onBeforeUnmount(() => clearTimeout(searchTimer))
function resetFilters() {
  clearTimeout(searchTimer)
  type.value = null
  search.value = ''
  query.value = ''
  page.value = 1
  load()
}
</script>

<template>
  <div class="management-page system-page">
    <header class="page-header"><h1>操作日志</h1></header>
    <div class="system-filters"><n-select v-model:value="type" :options="types" placeholder="全部类型" clearable class="system-filter-select" /><n-input v-model:value="search" clearable placeholder="搜索操作人、动作或对象" class="system-filter-search" /><n-button @click="resetFilters">重置</n-button><div class="system-filter-actions"><n-button secondary :loading="loading" @click="load"><template #icon><refresh-cw :size="16" /></template>刷新</n-button></div></div>
    <n-data-table class="system-data-table" :columns="columns" :data="rows" :loading="loading" :bordered="false" :single-line="false" :scroll-x="900" />
    <div class="pagination-wrap"><span>共 {{ total }} 条 · 每页 {{ pageSize }} 条</span><n-pagination v-model:page="page" :page-count="Math.max(1, Math.ceil(total / pageSize))" /></div>
  </div>
</template>
