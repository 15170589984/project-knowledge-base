<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { NButton, NDropdown, NTooltip, useMessage } from 'naive-ui'
import {
  Boxes, ChevronDown, ClipboardList, FolderKanban, KeyRound, LayoutList, Menu, Moon, Sun, UsersRound, X,
} from 'lucide-vue-next'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'
import { useCatalogStore } from '../stores/catalog'
import { useThemeStore } from '../stores/theme'

const route = useRoute()
const router = useRouter()
const message = useMessage()
const auth = useAuthStore()
const catalog = useCatalogStore()
const theme = useThemeStore()
const mobileOpen = ref(false)
const loadError = ref('')
const menus = ref([])
const icons = { workspace: FolderKanban, users: UsersRound, roles: KeyRound, menus: LayoutList, logs: ClipboardList }
const menuPermissions = { '/workspace': 'view_workspace', '/users': 'manage_users', '/roles': 'manage_roles', '/menus': 'manage_menus', '/logs': 'view_logs' }
const visibleMenus = computed(() => menus.value.filter((item) => item.is_enabled && (!menuPermissions[item.path] || auth.user?.permissions?.includes(menuPermissions[item.path]))))
const workspaceMenu = computed(() => visibleMenus.value.find((item) => item.key === 'workspace'))
const systemMenus = computed(() => visibleMenus.value.filter((item) => item.key !== 'workspace'))
const currentProjectName = computed(() => {
  if (route.path !== '/workspace') return menus.value.find((item) => item.path === route.path)?.label || '账号安全'
  return catalog.projects.find((item) => item.id === Number(route.query.project_id))?.name || '全部项目'
})
const userActions = [
  { label: '账号安全', key: 'account' },
  { label: '退出登录', key: 'logout' },
]

function handleUserAction(key) {
  if (key === 'account') router.push('/account')
  if (key === 'logout') logout()
}

async function logout() {
  try {
    await auth.logout()
    router.replace('/login')
  } catch (error) {
    message.error(error.message)
  }
}

async function reload() {
  try {
    const [, menuRows] = await Promise.all([
      auth.user?.permissions?.includes('view_workspace') ? catalog.refresh() : Promise.resolve(),
      api('/menus'),
    ])
    menus.value = menuRows
    loadError.value = ''
  } catch (error) {
    loadError.value = error.message
  }
}

async function reloadMenus() {
  try { menus.value = await api('/menus') } catch (cause) { loadError.value = cause.message }
}
onMounted(() => {
  reload()
  window.addEventListener('kb:menus-changed', reloadMenus)
})
onBeforeUnmount(() => window.removeEventListener('kb:menus-changed', reloadMenus))
</script>

<template>
  <div class="app-shell">
    <header class="app-topbar">
      <button class="mobile-menu icon-button" aria-label="打开导航" @click="mobileOpen = true"><menu :size="21" /></button>
      <router-link class="topbar-brand" to="/workspace"><span class="brand-symbol small"><boxes :size="20" /></span><strong>项目知库</strong></router-link>
      <span class="topbar-divider"></span><span class="topbar-project truncate">{{ currentProjectName }}</span>
      <div class="topbar-spacer"></div>
      <n-tooltip trigger="hover"><template #trigger><button class="icon-button theme-toggle" :aria-label="theme.isDark ? '切换浅色主题' : '切换深色主题'" @click="theme.isDark = !theme.isDark"><sun v-if="theme.isDark" :size="19" /><moon v-else :size="19" /></button></template>{{ theme.isDark ? '浅色主题' : '深色主题' }}</n-tooltip>
      <n-dropdown trigger="click" :options="userActions" @select="handleUserAction"><button class="topbar-user"><span class="avatar">{{ auth.user?.display_name?.slice(0, 1) || '用' }}</span><span class="topbar-user-name">{{ auth.user?.display_name || auth.user?.username }}</span><chevron-down :size="15" /></button></n-dropdown>
    </header>
    <div class="app-body">
      <div v-if="mobileOpen" class="mobile-backdrop" @click="mobileOpen = false"></div>
      <aside class="sidebar" :class="{ 'sidebar-open': mobileOpen }">
        <div class="sidebar-top"><strong>导航菜单</strong><button class="mobile-close icon-button" aria-label="关闭导航" @click="mobileOpen = false"><x :size="19" /></button></div>
      <div class="sidebar-scroll">
        <div class="sidebar-section-title"><span>工作空间</span></div>
        <router-link v-if="workspaceMenu" :to="workspaceMenu.path" class="sidebar-item" :class="{ active: route.path === workspaceMenu.path }" @click="mobileOpen = false"><component :is="icons.workspace" :size="17" /> {{ workspaceMenu.label }}</router-link>
        <div v-if="systemMenus.length" class="sidebar-section-title admin-title"><span>系统管理</span></div>
        <router-link v-for="item in systemMenus" :key="item.key" :to="item.path" class="sidebar-item" :class="{ active: route.path === item.path }" @click="mobileOpen = false"><component :is="icons[item.key] || LayoutList" :size="17" /> {{ item.label }}</router-link>
      </div>
    </aside>
    <main class="main-pane">
      <div v-if="loadError" class="top-error">目录加载失败：{{ loadError }} <n-button text @click="reload">重试</n-button></div>
      <router-view />
    </main>
    </div>
  </div>
</template>
