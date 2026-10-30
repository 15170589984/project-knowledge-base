import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api, setCsrfToken } from '../api'

export const useAuthStore = defineStore('auth', () => {
  const user = ref(null)
  const ready = ref(false)
  const refreshError = ref('')

  async function refresh() {
    refreshError.value = ''
    try {
      const result = await api('/auth/me')
      user.value = result.user
      setCsrfToken(result.csrf_token)
    } catch (cause) {
      user.value = null
      setCsrfToken('')
      if (cause.status !== 401) refreshError.value = '无法连接服务，请检查后端状态并刷新页面。'
    } finally {
      ready.value = true
    }
  }

  async function login(username, password) {
    const result = await api('/auth/login', {
      method: 'POST',
      body: { username, password },
    })
    user.value = result.user
    setCsrfToken(result.csrf_token)
    refreshError.value = ''
    ready.value = true
  }

  async function logout() {
    await api('/auth/logout', { method: 'POST' })
    user.value = null
    setCsrfToken('')
  }

  return { user, ready, refreshError, refresh, login, logout }
})
