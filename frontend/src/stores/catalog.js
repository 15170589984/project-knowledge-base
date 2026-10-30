import { defineStore } from 'pinia'
import { ref } from 'vue'
import { api } from '../api'

export const useCatalogStore = defineStore('catalog', () => {
  const projects = ref([])
  const categories = ref([])
  const environments = ref([])
  const loading = ref(false)

  async function refresh() {
    loading.value = true
    try {
      const [projectRows, categoryRows, environmentRows] = await Promise.all([
        api('/projects'),
        api('/categories'),
        api('/environments'),
      ])
      projects.value = projectRows
      categories.value = categoryRows
      environments.value = environmentRows
    } finally {
      loading.value = false
    }
  }

  return { projects, categories, environments, loading, refresh }
})
