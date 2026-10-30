<script setup>
import { computed, h, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NButton, NDataTable, NDropdown, NEmpty, NInput, NInputNumber, NModal, NPagination,
  NPopconfirm, NSelect, NSpin, NTag, NTooltip, useDialog, useMessage,
} from 'naive-ui'
import {
  BookOpenText, ChevronDown, ChevronRight, Clipboard, Eye, FileText, Folder, FolderKanban,
  Link2, MoreHorizontal, Pencil, Plus, RotateCcw, Search, Table2, Trash2, X,
} from 'lucide-vue-next'
import { api, queryString } from '../api'
import { copyText } from '../clipboard'
import { useAuthStore } from '../stores/auth'
import { useCatalogStore } from '../stores/catalog'
import EntryForm from '../components/EntryForm.vue'
import EntryDrawer from '../components/EntryDrawer.vue'
import DocumentEditor from '../components/DocumentEditor.vue'
import SpreadsheetEditor from '../components/SpreadsheetEditor.vue'
import { parseTable } from '../tableField'

const KIND_LABELS = { entry: '条目', document: '文档', spreadsheet: '表格' }
const KIND_TAG_TYPES = { entry: 'default', document: 'info', spreadsheet: 'success' }

const route = useRoute()
const router = useRouter()
const message = useMessage()
const dialog = useDialog()
const auth = useAuthStore()
const catalog = useCatalogStore()
const projectSearch = ref('')
const collapsedProjects = ref(new Set())
const searchText = ref('')
const searchQuery = ref('')
const environment = ref(null)
const page = ref(1)
const pageSize = 10
const loading = ref(false)
const error = ref('')
const items = ref([])
const total = ref(0)
const drawerEntry = ref(null)
const drawerOpen = ref(false)
const formOpen = ref(false)
const editingEntry = ref(null)
const documentOpen = ref(false)
const documentEntry = ref(null)
const spreadsheetOpen = ref(false)
const spreadsheetEntry = ref(null)
const createMenuOpen = ref(false)
const projectModalOpen = ref(false)
const projectEditing = ref(false)
const projectTargetId = ref(null)
const projectForm = reactive({ name: '', description: '', parent_id: null, sort_order: 0 })
const projectSaving = ref(false)
const categoryModalOpen = ref(false)
const categoryEditingId = ref(null)
const categoryForm = reactive({ name: '', sort_order: 0 })
const categorySaving = ref(false)
const categoryError = ref('')
const shareOpen = ref(false)
const shares = ref([])
const availableUsers = ref([])
const shareUser = ref(null)
const auditOpen = ref(false)
const auditRows = ref([])
const dragProjectId = ref(null)
const revealedCells = reactive({})
const cellTimers = new Map()
let searchTimer
let loadId = 0

const projectId = computed(() => Number(route.query.project_id || 0))
const categoryId = computed(() => Number(route.query.category_id || 0))
const selectedProject = computed(() => catalog.projects.find((item) => item.id === projectId.value))
const selectedCategory = computed(() => catalog.categories.find((item) => item.id === categoryId.value))
const ownedProjects = computed(() => catalog.projects.filter((item) => item.is_owner))
const canCreateEntry = computed(() => selectedProject.value ? selectedProject.value.is_owner : ownedProjects.value.length > 0)
const projectRows = computed(() => {
  const projects = catalog.projects
  const term = projectSearch.value.trim().toLowerCase()
  if (term) return projects.filter((item) => item.name.toLowerCase().includes(term)).map((item) => ({ ...item, depth: 0, has_children: false, expanded: false }))
  const ids = new Set(projects.map((item) => item.id))
  const children = new Map()
  for (const project of projects) {
    const parent = ids.has(project.parent_id) ? project.parent_id : null
    if (!children.has(parent)) children.set(parent, [])
    children.get(parent).push(project)
  }
  for (const group of children.values()) group.sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name, 'zh-CN'))
  const rows = []
  const visit = (project, depth) => {
    const descendants = children.get(project.id) || []
    const expanded = !collapsedProjects.value.has(project.id)
    rows.push({ ...project, depth, has_children: descendants.length > 0, expanded })
    if (expanded) descendants.forEach((child) => visit(child, depth + 1))
  }
  for (const root of children.get(null) || []) visit(root, 0)
  return rows
})
const parentOptions = computed(() => {
  const excluded = new Set(projectEditing.value ? [projectTargetId.value] : [])
  let changed = true
  while (changed) {
    changed = false
    for (const project of catalog.projects) {
      if (excluded.has(project.parent_id) && !excluded.has(project.id)) {
        excluded.add(project.id)
        changed = true
      }
    }
  }
  return ownedProjects.value.filter((project) => !excluded.has(project.id)).map((project) => ({ label: project.name, value: project.id }))
})

function filters() {
  return {
    project_id: projectId.value || null,
    include_descendants: Boolean(projectId.value),
    category_id: categoryId.value || null,
    environment: environment.value || null,
  }
}

async function load() {
  const current = ++loadId
  loading.value = true
  error.value = ''
  try {
    const base = filters()
    const params = { ...base, page: page.value, page_size: pageSize }
    const result = searchQuery.value
      ? await api('/entries/search', { method: 'POST', body: { ...params, q: searchQuery.value } })
      : await api('/entries?' + queryString(params))
    if (current === loadId) {
      items.value = result.items
      total.value = result.total
    }
  } catch (cause) {
    if (current === loadId) error.value = cause.message
  } finally {
    if (current === loadId) loading.value = false
  }
}

watch(
  () => [projectId.value, categoryId.value, environment.value],
  () => {
    page.value = 1
    load()
  },
  { immediate: true },
)
watch(() => catalog.categories.map((item) => item.id).join(','), () => {
  if (!catalog.categories.length) return
  if (!selectedCategory.value) {
    router.replace({ path: '/workspace', query: { ...route.query, category_id: String(catalog.categories[0].id) } })
  }
}, { immediate: true })
watch(searchText, (value) => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    searchQuery.value = value.trim()
    page.value = 1
    load()
  }, 300)
})
watch(() => route.query.create_project, (value) => {
  if (value === '1') {
    openProjectModal(false)
    const query = { ...route.query }
    delete query.create_project
    router.replace({ path: '/workspace', query })
  }
}, { immediate: true })
onBeforeUnmount(() => {
  clearTimeout(searchTimer)
  for (const timer of cellTimers.values()) clearTimeout(timer)
})

function resetFilters() {
  environment.value = null
  searchText.value = ''
  searchQuery.value = ''
  page.value = 1
  load()
}

function selectProject(id) {
  const query = { ...route.query }
  if (id) query.project_id = String(id)
  else delete query.project_id
  router.push({ path: '/workspace', query })
}

function selectCategory(id) {
  router.push({ path: '/workspace', query: { ...route.query, category_id: String(id) } })
}

function toggleProject(id) {
  const next = new Set(collapsedProjects.value)
  if (next.has(id)) next.delete(id)
  else next.add(id)
  collapsedProjects.value = next
}

function manageCategory(action) {
  categoryEditingId.value = action === 'edit' ? categoryId.value : null
  categoryForm.name = action === 'edit' ? selectedCategory.value?.name || '' : ''
  categoryForm.sort_order = action === 'edit' ? selectedCategory.value?.sort_order || 0 : 0
  categoryError.value = ''
  categoryModalOpen.value = true
}

async function saveCategory() {
  if (!categoryForm.name.trim()) {
    categoryError.value = '请填写分类名称'
    return
  }
  categorySaving.value = true
  categoryError.value = ''
  try {
    const result = await api(categoryEditingId.value ? '/categories/' + categoryEditingId.value : '/categories', {
      method: categoryEditingId.value ? 'PUT' : 'POST',
      body: { name: categoryForm.name.trim(), sort_order: categoryForm.sort_order ?? 0 },
    })
    categoryModalOpen.value = false
    await catalog.refresh()
    if (!categoryEditingId.value) selectCategory(result.id)
    message.success('分类已保存')
  } catch (cause) {
    categoryError.value = cause.message
  } finally {
    categorySaving.value = false
  }
}

async function deleteCategory() {
  try {
    await api('/categories/' + categoryId.value, { method: 'DELETE' })
    await catalog.refresh()
    const query = { ...route.query }
    query.category_id = catalog.categories[0]?.id ? String(catalog.categories[0].id) : undefined
    await router.replace({ path: '/workspace', query })
    await load()
    message.success('分类已删除')
  } catch (cause) {
    message.error(cause.message)
  }
}

async function openEntry(entry) {
  try {
    drawerEntry.value = await api('/entries/' + entry.id)
    drawerOpen.value = true
  } catch (cause) {
    message.error(cause.message)
  }
}

function editEntry(entry = drawerEntry.value) {
  if (entry?.kind === 'document') {
    documentEntry.value = entry
    documentOpen.value = true
    drawerOpen.value = false
    return
  }
  if (entry?.kind === 'spreadsheet') {
    spreadsheetEntry.value = entry
    spreadsheetOpen.value = true
    drawerOpen.value = false
    return
  }
  editingEntry.value = entry
  drawerOpen.value = false
  formOpen.value = true
}

async function removeEntry(entry) {
  try {
    await api('/entries/' + entry.id, { method: 'DELETE' })
    await load()
    message.success('条目已删除')
  } catch (cause) {
    message.error(cause.message)
  }
}

function newEntry() {
  editingEntry.value = null
  formOpen.value = true
}

function pickCreate(kind) {
  createMenuOpen.value = false
  cancelCloseCreateMenu()
  if (kind === 'document') {
    documentEntry.value = null
    documentOpen.value = true
  } else if (kind === 'spreadsheet') {
    spreadsheetEntry.value = null
    spreadsheetOpen.value = true
  } else {
    newEntry()
  }
}

let createMenuTimer = null

function openCreateMenu() {
  cancelCloseCreateMenu()
  createMenuOpen.value = true
}

function scheduleCloseCreateMenu() {
  cancelCloseCreateMenu()
  createMenuTimer = setTimeout(() => {
    createMenuTimer = null
    createMenuOpen.value = false
  }, 220)
}

function cancelCloseCreateMenu() {
  if (createMenuTimer) {
    clearTimeout(createMenuTimer)
    createMenuTimer = null
  }
}

function closeCreateMenu(event) {
  if (!event.target.closest?.('.create-menu-wrap')) {
    cancelCloseCreateMenu()
    createMenuOpen.value = false
  }
}

watch(createMenuOpen, (open) => {
  if (open) document.addEventListener('pointerdown', closeCreateMenu)
  else document.removeEventListener('pointerdown', closeCreateMenu)
})

onBeforeUnmount(() => {
  cancelCloseCreateMenu()
  document.removeEventListener('pointerdown', closeCreateMenu)
})

async function afterEntrySaved(result) {
  await load()
  if (result?.id) drawerEntry.value = result
}

function formatDate(value) {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN')
}

async function revealCell(entry, field, purpose) {
  try {
    const result = await api('/entries/' + entry.id + '/reveal', {
      method: 'POST',
      body: { field_id: field.id, purpose },
    })
    if (result.unavailable) {
      if (purpose === 'view') revealedCells[entry.id + ':' + field.id] = result.placeholder
      message.error('此字段无法解密，请检查加密密钥')
      return
    }
    if (purpose === 'copy') {
      if (await copyText(result.value)) message.success('已复制')
    } else {
      const key = entry.id + ':' + field.id
      revealedCells[key] = result.value
      if (cellTimers.has(key)) clearTimeout(cellTimers.get(key))
      cellTimers.set(key, setTimeout(() => {
        delete revealedCells[key]
        cellTimers.delete(key)
      }, 30000))
    }
  } catch (cause) {
    message.error(cause.message)
  }
}

async function copyFieldColumn(label) {
  const values = []
  for (const entry of items.value) {
    for (const field of entry.fields.filter((item) => item.label === label)) {
      const text = field.is_sensitive ? revealedCells[entry.id + ':' + field.id] : field.value
      if (text) values.push(text)
    }
  }
  if (!values.length) {
    message.warning('当前页没有可复制的值，敏感字段需先显示')
    return
  }
  try {
    if (await copyText(values.join('\n'))) message.success(`已复制 ${values.length} 个值`)
  } catch (cause) {
    message.error(cause.message)
  }
}

function fieldCell(entry, field) {
  const value = field.value
  if (field.is_sensitive) {
    if (!field.has_value) return h('span', { class: 'muted' }, '—')
    const key = entry.id + ':' + field.id
    return h('div', { class: 'table-secret', onClick: (event) => event.stopPropagation() }, [
      h('span', { class: 'table-secret-value' }, revealedCells[key] || '●●●●●●'),
      entry.can_edit ? h(NTooltip, null, {
        trigger: () => h('button', {
          class: 'icon-button compact',
          'aria-label': '显示' + field.label,
          onClick: () => revealCell(entry, field, 'view'),
        }, [h(Eye, { size: 15 })]),
        default: () => '显示 30 秒',
      }) : null,
      entry.can_edit ? h(NTooltip, null, {
        trigger: () => h('button', {
          class: 'icon-button compact',
          'aria-label': '复制' + field.label,
          onClick: () => revealCell(entry, field, 'copy'),
        }, [h(Clipboard, { size: 15 })]),
        default: () => '复制',
      }) : null,
    ])
  }
  if (!value) return h('span', { class: 'muted' }, '—')
  if (field.field_type === 'table') {
    const rows = parseTable(value)
    return rows ? h('div', { class: 'table-list-preview' }, rows[0].map((cell) => h('span', { class: 'truncate' }, cell || '空'))) : h('span', { class: 'danger' }, '表格数据无效')
  }
  if (field.field_type === 'url' && /^https?:\/\//i.test(value)) {
    return h('a', {
      href: value,
      target: '_blank',
      rel: 'noopener noreferrer',
      class: 'table-link truncate',
      onClick: (event) => event.stopPropagation(),
    }, [value, h(Link2, { size: 14 })])
  }
  return h('span', { class: 'table-text truncate' }, value)
}

const columns = computed(() => {
  const result = [
    { title: '序号', key: 'serial', width: 70, render: (_entry, index) => (page.value - 1) * pageSize + index + 1 },
    {
      title: '名称',
      key: 'title',
      minWidth: 220,
      render: (entry) => h('div', { class: 'table-title-cell' }, [
        h('span', { class: 'table-title-main' }, [
          entry.kind === 'document' ? h(FileText, { size: 14 }) : entry.kind === 'spreadsheet' ? h(Table2, { size: 14 }) : null,
          h('strong', entry.title),
        ]),
        entry.content ? h('span', { class: 'muted truncate' }, entry.content) : null,
      ]),
    },
    {
      title: '类型',
      key: 'kind',
      width: 84,
      render: (entry) => h(NTag, { size: 'small', bordered: false, type: KIND_TAG_TYPES[entry.kind] || 'default' }, { default: () => KIND_LABELS[entry.kind] || '条目' }),
    },
  ]
  if (!projectId.value) result.push({ title: '项目', key: 'project_name', minWidth: 140 })
  if (!categoryId.value) result.push({ title: '分类', key: 'category_name', minWidth: 130 })
  const labels = [...new Set(items.value.flatMap((entry) => entry.fields.map((field) => field.label)))]
  for (const label of labels) {
    result.push({
      title: () => h('div', { class: 'field-head' }, [
        h('span', { class: 'truncate' }, label),
        h(NTooltip, null, {
          trigger: () => h('button', {
            class: 'icon-button compact',
            'aria-label': '复制字段 ' + label,
            onClick: (event) => { event.stopPropagation(); copyFieldColumn(label) },
          }, [h(Clipboard, { size: 14 })]),
          default: () => '复制当前页该字段的值',
        }),
      ]),
      key: 'field:' + label,
      minWidth: 170,
      render: (entry) => {
        const matches = entry.fields.filter((field) => field.label === label)
        return matches.length ? h('div', { class: 'multi-field-cell' }, matches.map((field) => fieldCell(entry, field))) : h('span', { class: 'muted' }, '—')
      },
    })
  }
  result.push({
    title: '环境',
    key: 'environment',
    width: 90,
    render: (entry) => entry.environment ? h(NTag, { size: 'small', bordered: false }, { default: () => entry.environment }) : h('span', { class: 'muted' }, '—'),
  })
  result.push({
    title: '更新时间',
    key: 'updated_at',
    width: 160,
    render: (entry) => h('span', { class: 'table-date' }, formatDate(entry.updated_at)),
  })
  result.push({
    title: '操作', key: 'actions', width: 160, fixed: 'right',
    render: (entry) => h('div', { class: 'row-actions', onClick: (event) => event.stopPropagation() }, [
      h(NButton, { text: true, size: 'small', onClick: () => openEntry(entry) }, { default: () => '查看' }),
      entry.can_edit ? h(NButton, { text: true, size: 'small', onClick: () => editEntry(entry) }, { default: () => '编辑' }) : null,
      entry.can_edit ? h(NPopconfirm, { positiveText: '删除', negativeText: '取消', onPositiveClick: () => removeEntry(entry) }, {
        trigger: () => h(NButton, { text: true, size: 'small', type: 'error' }, { default: () => '删除' }),
        default: () => '确定删除这条信息？',
      }) : null,
    ]),
  })
  return result
})

function openProjectModal(edit, parentId = null, targetId = null) {
  const target = catalog.projects.find((item) => item.id === (targetId || projectId.value))
  projectEditing.value = edit
  projectTargetId.value = edit ? target?.id : null
  projectForm.name = edit ? target?.name || '' : ''
  projectForm.description = edit ? target?.description || '' : ''
  projectForm.parent_id = edit ? target?.parent_id || null : parentId
  projectForm.sort_order = edit ? target?.sort_order || 0 : 0
  projectModalOpen.value = true
}

async function saveProject() {
  if (!projectForm.name.trim()) {
    message.error('请填写项目名称')
    return
  }
  projectSaving.value = true
  try {
    const result = await api(projectEditing.value ? '/projects/' + projectTargetId.value : '/projects', {
      method: projectEditing.value ? 'PATCH' : 'POST',
      body: { name: projectForm.name, description: projectForm.description || null, parent_id: projectForm.parent_id, ...(projectEditing.value ? { sort_order: projectForm.sort_order || 0 } : {}) },
    })
    projectModalOpen.value = false
    await catalog.refresh()
    if (!projectEditing.value) router.push({ path: '/workspace', query: { project_id: String(result.id) } })
    message.success(projectEditing.value ? '项目已更新' : '项目已创建')
  } catch (cause) {
    message.error(cause.message)
  } finally {
    projectSaving.value = false
  }
}

async function deleteProject(targetId = projectId.value) {
  try {
    await api('/projects/' + targetId, { method: 'DELETE' })
    await catalog.refresh()
    if (projectId.value === targetId) router.push('/workspace')
    message.success('项目已删除')
  } catch (cause) {
    message.error(cause.message)
  }
}

async function openShare(targetId = projectId.value) {
  projectTargetId.value = targetId
  try {
    const [current, available] = await Promise.all([
      api('/projects/' + targetId + '/shares'),
      api('/users/available'),
    ])
    shares.value = current
    availableUsers.value = available
    shareUser.value = null
    shareOpen.value = true
  } catch (cause) {
    message.error(cause.message)
  }
}

async function addShare() {
  const person = availableUsers.value.find((item) => item.id === shareUser.value)
  if (!person) return
  try {
    await api('/projects/' + projectTargetId.value + '/shares', {
      method: 'POST',
      body: { username: person.username },
    })
    shares.value = await api('/projects/' + projectTargetId.value + '/shares')
    shareUser.value = null
    message.success('已授予只读权限')
  } catch (cause) {
    message.error(cause.message)
  }
}

async function revokeShare(userId) {
  try {
    await api('/projects/' + projectTargetId.value + '/shares/' + userId, { method: 'DELETE' })
    shares.value = shares.value.filter((item) => item.user_id !== userId)
    message.success('权限已撤销')
  } catch (cause) {
    message.error(cause.message)
  }
}

async function openAudit(targetId = projectId.value) {
  try {
    const result = await api('/projects/' + targetId + '/audit-logs')
    auditRows.value = result.items
    auditOpen.value = true
  } catch (cause) {
    message.error(cause.message)
  }
}

function projectActions(project) {
  return [
    { label: '新建子项目', key: 'child' },
    { label: '编辑 / 移动项目', key: 'edit' },
    { label: '分享', key: 'share' },
    { label: '操作记录', key: 'audit' },
    { type: 'divider', key: 'divider' },
    { label: '删除项目', key: 'delete' },
  ]
}

function handleProjectAction(key, project) {
  if (key === 'child') openProjectModal(false, project.id)
  if (key === 'edit') openProjectModal(true, null, project.id)
  if (key === 'share') openShare(project.id)
  if (key === 'audit') openAudit(project.id)
  if (key === 'delete') dialog.warning({ title: '删除项目', content: '项目有条目或子项目时不能删除。确定删除“' + project.name + '”？', positiveText: '删除', negativeText: '取消', onPositiveClick: () => deleteProject(project.id) })
}

async function dropProject(targetId = null) {
  const sourceId = dragProjectId.value
  dragProjectId.value = null
  if (!sourceId || sourceId === targetId) return
  try {
    await api('/projects/' + sourceId, { method: 'PATCH', body: { parent_id: targetId } })
    await catalog.refresh()
    message.success('项目已移动')
  } catch (cause) {
    message.error(cause.message)
  }
}
</script>

<template>
  <div class="workspace">
    <aside class="project-panel">
      <div class="project-panel-head">
        <strong>项目</strong>
        <n-tooltip trigger="hover"><template #trigger>
          <button class="icon-button compact" aria-label="新建项目" @click="openProjectModal(false)"><plus :size="17" /></button>
        </template>新建项目</n-tooltip>
      </div>
      <div class="project-panel-search">
        <n-input v-model:value="projectSearch" size="small" clearable placeholder="搜索项目">
          <template #prefix><search :size="15" /></template>
        </n-input>
      </div>
      <div class="project-panel-list">
        <button class="project-all" :class="{ active: !projectId }" @click="selectProject(null)" @dragover.prevent @drop.prevent="dropProject(null)"><folder-kanban :size="16" /> 全部</button>
        <div v-for="project in projectRows" :key="project.id" class="project-tree-row" :class="{ active: projectId === project.id }" :style="{ paddingLeft: (10 + project.depth * 16) + 'px' }" :draggable="project.is_owner" @dragstart="dragProjectId = project.id" @dragover.prevent @drop.prevent="dropProject(project.id)">
          <button v-if="project.has_children" class="project-expand" :aria-label="(project.expanded ? '收起' : '展开') + project.name" @click="toggleProject(project.id)">
            <chevron-down v-if="project.expanded" :size="14" /><chevron-right v-else :size="14" />
          </button>
          <span v-else class="project-expand-placeholder"></span>
          <button class="project-tree-name" :title="project.name" @click="selectProject(project.id)">
            <folder :size="15" /><span class="truncate">{{ project.name }}</span>
          </button>
          <n-dropdown v-if="project.is_owner" trigger="click" :options="projectActions(project)" @select="(key) => handleProjectAction(key, project)">
            <button class="project-child-add" :aria-label="project.name + ' 操作'" @click.stop><more-horizontal :size="16" /></button>
          </n-dropdown>
        </div>
        <div v-if="!projectRows.length" class="project-panel-empty">{{ projectSearch ? '没有匹配的项目' : '还没有项目' }}</div>
      </div>
    </aside>

    <section class="workspace-content">
      <div class="category-module">
        <div class="category-tab-bar">
          <div class="category-tab-list" role="tablist" aria-label="信息分类">
            <button v-for="category in catalog.categories" :key="category.id" role="tab" :aria-selected="categoryId === category.id" class="category-tab" :class="{ active: categoryId === category.id }" @click="selectCategory(category.id)">{{ category.name }}</button>
            <span v-if="!catalog.categories.length" class="category-empty">暂无分类</span>
          </div>
          <div v-if="auth.user?.permissions?.includes('manage_categories')" class="category-actions">
            <n-tooltip trigger="hover"><template #trigger><button class="icon-button" aria-label="新建分类" @click="manageCategory('create')"><plus :size="17" /></button></template>新建分类</n-tooltip>
            <n-tooltip v-if="selectedCategory" trigger="hover"><template #trigger><button class="icon-button" aria-label="编辑分类" @click="manageCategory('edit')"><pencil :size="16" /></button></template>编辑分类</n-tooltip>
            <n-popconfirm v-if="selectedCategory" positive-text="删除" negative-text="取消" @positive-click="deleteCategory">
              <template #trigger><button class="icon-button danger" aria-label="删除分类"><trash2 :size="16" /></button></template>
              分类下有条目时无法删除。确定删除 {{ selectedCategory.name }}？
            </n-popconfirm>
          </div>
        </div>
      </div>

      <div class="filter-bar">
        <div class="filter-controls">
          <n-select v-model:value="environment" size="small" class="environment-select" placeholder="所有环境" clearable :options="catalog.environments" />
          <n-input v-model:value="searchText" size="small" clearable class="global-search" placeholder="搜索名称、备注和字段"><template #prefix><search :size="16" /></template></n-input>
          <n-button size="small" @click="resetFilters"><template #icon><rotate-ccw :size="15" /></template>重置</n-button>
        </div>
        <div v-if="canCreateEntry && selectedCategory" class="create-menu-wrap" @mouseenter="openCreateMenu" @mouseleave="scheduleCloseCreateMenu">
          <n-button type="primary" size="small" class="create-entry-button" @mouseenter="openCreateMenu" @mouseleave="scheduleCloseCreateMenu" @click="createMenuOpen = !createMenuOpen">
            <template #icon><plus :size="16" /></template>新建<chevron-down :size="14" class="create-entry-caret" />
          </n-button>
          <div v-if="createMenuOpen" class="create-menu" role="menu" @mouseenter="cancelCloseCreateMenu" @mouseleave="scheduleCloseCreateMenu">
            <button type="button" role="menuitem" class="create-menu-item" @click="pickCreate('entry')"><file-text :size="15" />条目</button>
            <button type="button" role="menuitem" class="create-menu-item" @click="pickCreate('document')"><book-open-text :size="15" />文档</button>
            <button type="button" role="menuitem" class="create-menu-item" @click="pickCreate('spreadsheet')"><table2 :size="15" />表格</button>
          </div>
        </div>
      </div>

      <div v-if="error" class="content-error" role="alert"><strong>加载失败</strong><span>{{ error }}</span><n-button text @click="load">重试</n-button></div>
      <n-spin v-else :show="loading">
        <div v-if="!selectedCategory" class="empty-content"><n-empty description="请先添加分类" /></div>
        <template v-else>
          <n-data-table v-if="items.length" :columns="columns" :data="items" :bordered="false" :single-line="false" :scroll-x="Math.max(800, columns.length * 165)" :row-props="(row) => ({ class: 'entry-row', onClick: () => openEntry(row) })" />
          <div v-else class="empty-content"><n-empty description="当前条件下没有条目" /></div>
          <div class="pagination-wrap"><span>共 {{ total }} 条 · 每页 {{ pageSize }} 条</span><n-pagination v-model:page="page" :page-count="Math.max(1, Math.ceil(total / pageSize))" @update:page="load" /></div>
        </template>
      </n-spin>
    </section>

    <entry-form
      :show="formOpen"
      :entry="editingEntry"
      :projects="catalog.projects"
      :categories="catalog.categories"
      :environments="catalog.environments"
      :initial-project-id="projectId"
      :initial-category-id="categoryId"
      @close="formOpen = false"
      @saved="afterEntrySaved"
    />
    <entry-drawer
      :show="drawerOpen"
      :entry="drawerEntry"
      @close="drawerOpen = false"
      @edit="editEntry"
      @deleted="load"
    />
    <document-editor
      :show="documentOpen"
      :entry="documentEntry"
      :projects="catalog.projects"
      :categories="catalog.categories"
      :environments="catalog.environments"
      :initial-project-id="projectId"
      :initial-category-id="categoryId"
      @close="documentOpen = false"
      @saved="afterEntrySaved"
    />
    <spreadsheet-editor
      :show="spreadsheetOpen"
      :entry="spreadsheetEntry"
      :projects="catalog.projects"
      :categories="catalog.categories"
      :environments="catalog.environments"
      :initial-project-id="projectId"
      :initial-category-id="categoryId"
      @close="spreadsheetOpen = false"
      @saved="afterEntrySaved"
    />

    <n-modal v-model:show="projectModalOpen" preset="card" class="small-modal" :title="projectEditing ? '编辑项目' : '新建项目'">
      <div class="form-grid">
        <div class="form-row"><label class="field-label">项目名称</label><n-input v-model:value="projectForm.name" maxlength="120" placeholder="例如：用户中心" /></div>
        <div class="form-row"><label class="field-label">上级项目</label><n-select v-model:value="projectForm.parent_id" :options="parentOptions" placeholder="顶级项目" clearable filterable /></div>
        <div v-if="projectEditing" class="form-row short-number"><label class="field-label">同级排序</label><n-input-number v-model:value="projectForm.sort_order" :min="-9999" :max="9999" /></div>
        <div class="form-row"><label class="field-label">项目说明</label><n-input v-model:value="projectForm.description" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="可选" /></div>
      </div>
      <template #footer><div class="modal-actions"><n-button @click="projectModalOpen = false">取消</n-button><n-button type="primary" :loading="projectSaving" @click="saveProject">保存</n-button></div></template>
    </n-modal>

    <n-modal v-model:show="categoryModalOpen" preset="card" class="small-modal" :title="categoryEditingId ? '编辑分类' : '新建分类'">
      <div class="form-grid">
        <div class="form-row"><label class="field-label">分类名称</label><n-input v-model:value="categoryForm.name" maxlength="80" placeholder="例如：数据库" /></div>
        <div class="form-row short-number"><label class="field-label">排序</label><n-input-number v-model:value="categoryForm.sort_order" :min="-9999" :max="9999" /></div>
        <div v-if="categoryError" class="form-error">{{ categoryError }}</div>
      </div>
      <template #footer><div class="modal-actions"><n-button @click="categoryModalOpen = false">取消</n-button><n-button type="primary" :loading="categorySaving" @click="saveCategory">保存</n-button></div></template>
    </n-modal>

    <n-modal v-model:show="shareOpen" preset="card" class="small-modal" title="项目分享">
      <div class="share-intro">被分享的成员只能查看非敏感信息，不能修改或揭示密钥。</div>
      <div class="share-add">
        <n-select v-model:value="shareUser" filterable placeholder="选择成员" :options="availableUsers.filter((item) => !shares.some((share) => share.user_id === item.id)).map((item) => ({ label: item.display_name + ' · ' + item.username, value: item.id }))" />
        <n-button type="primary" :disabled="!shareUser" @click="addShare"><template #icon><plus :size="16" /></template>添加</n-button>
      </div>
      <div class="share-list">
        <div v-for="share in shares" :key="share.id" class="share-row">
          <span class="avatar small-avatar">{{ share.display_name.slice(0, 1) }}</span>
          <span class="share-person"><strong>{{ share.display_name }}</strong><small>{{ share.username }}</small></span>
          <n-tag size="small" :bordered="false">只读</n-tag>
          <n-popconfirm positive-text="撤销" negative-text="取消" @positive-click="revokeShare(share.user_id)">
            <template #trigger><button class="icon-button" :aria-label="'撤销 ' + share.display_name + ' 的权限'"><x :size="17" /></button></template>
            撤销后此成员将无法继续访问该项目。
          </n-popconfirm>
        </div>
        <div v-if="!shares.length" class="muted share-empty">尚未分享给其他成员</div>
      </div>
    </n-modal>

    <n-modal v-model:show="auditOpen" preset="card" class="small-modal" title="项目操作记录">
      <div v-if="auditRows.length" class="audit-list">
        <div v-for="row in auditRows" :key="row.id" class="audit-row">
          <span class="audit-action">{{ row.action }}</span>
          <span class="muted">{{ row.detail || row.target_type + ' #' + row.target_id }}</span>
          <time>{{ formatDate(row.created_at) }}</time>
        </div>
      </div>
      <n-empty v-else description="暂无操作记录" />
    </n-modal>
  </div>
</template>
