import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

export const useThemeStore = defineStore('theme', () => {
  const isDark = ref(localStorage.getItem('kb_theme') === 'dark')
  watch(isDark, (value) => {
    document.documentElement.classList.toggle('theme-dark', value)
    localStorage.setItem('kb_theme', value ? 'dark' : 'light')
  }, { immediate: true })
  return { isDark }
})
