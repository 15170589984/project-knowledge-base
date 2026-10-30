import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from './stores/auth'
import AuthView from './views/AuthView.vue'
import ShellView from './views/ShellView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import UsersView from './views/UsersView.vue'
import RolesView from './views/RolesView.vue'
import MenusView from './views/MenusView.vue'
import LogsView from './views/LogsView.vue'
import AccountView from './views/AccountView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/login', component: AuthView, props: { mode: 'login' } },
    { path: '/register', component: AuthView, props: { mode: 'register' } },
    { path: '/recover', component: AuthView, props: { mode: 'recover' } },
    {
      path: '/',
      component: ShellView,
      children: [
        { path: '', redirect: '/workspace' },
        { path: 'workspace', component: WorkspaceView, meta: { permission: 'view_workspace' } },
        { path: 'users', component: UsersView, meta: { permission: 'manage_users' } },
        { path: 'roles', component: RolesView, meta: { permission: 'manage_roles' } },
        { path: 'menus', component: MenusView, meta: { permission: 'manage_menus' } },
        { path: 'logs', component: LogsView, meta: { permission: 'view_logs' } },
        { path: 'account', component: AccountView },
      ],
    },
    { path: '/:pathMatch(.*)*', redirect: '/workspace' },
  ],
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  if (!auth.ready) await auth.refresh()
  const publicPage = ['/login', '/register', '/recover'].includes(to.path)
  if (!auth.user && !publicPage) return '/login'
  if (auth.user && publicPage) return '/workspace'
  if (to.meta.permission && !auth.user?.permissions?.includes(to.meta.permission)) {
    return auth.user?.permissions?.includes('view_workspace') ? '/workspace' : '/account'
  }
})

export default router
