<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, useMessage } from 'naive-ui'
import { Copy, KeyRound, LockKeyhole, RefreshCw } from 'lucide-vue-next'
import { api } from '../api'
import { copyText } from '../clipboard'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const router = useRouter()
const message = useMessage()
const currentPassword = ref('')
const newPassword = ref('')
const codes = ref([])
const busy = ref(false)

async function changePassword() {
  busy.value = true
  try {
    await api('/auth/change-password', {
      method: 'POST',
      body: { current_password: currentPassword.value, new_password: newPassword.value },
    })
    auth.user = null
    message.success('密码已更新，请重新登录')
    router.replace('/login')
  } catch (error) {
    message.error(error.message)
  } finally {
    busy.value = false
  }
}

async function generateCodes() {
  busy.value = true
  try {
    const result = await api('/auth/recovery-codes', { method: 'POST' })
    codes.value = result.codes
    message.success('新的恢复码已生成，旧恢复码已失效')
  } catch (error) {
    message.error(error.message)
  } finally {
    busy.value = false
  }
}

async function copyCodes() {
  try {
    if (await copyText(codes.value.join('\n'))) message.success('恢复码已复制')
  } catch (error) {
    message.error(error.message)
  }
}
</script>

<template>
  <div class="management-page account-page">
    <header class="page-header"><h1>账号安全</h1></header>
    <div class="account-profile">
      <span class="avatar account-avatar">{{ auth.user?.display_name?.slice(0, 1) }}</span>
      <div><strong>{{ auth.user?.display_name }}</strong><span>{{ auth.user?.username }} · {{ auth.user?.role === 'admin' ? '管理员' : '成员' }}</span></div>
    </div>
    <section class="account-section">
      <div class="section-heading"><lock-keyhole :size="19" /><h2>修改密码</h2></div>
      <div class="account-form">
        <div><label class="field-label">当前密码</label><n-input v-model:value="currentPassword" type="password" show-password-on="click" autocomplete="current-password" /></div>
        <div><label class="field-label">新密码</label><n-input v-model:value="newPassword" type="password" show-password-on="click" autocomplete="new-password" placeholder="至少 6 位" /></div>
        <n-button type="primary" :loading="busy" @click="changePassword">更新密码</n-button>
      </div>
    </section>
    <section class="account-section">
      <div class="section-heading"><key-round :size="19" /><h2>恢复码</h2></div>
      <p class="muted">忘记密码时，可用一次性恢复码自行重设。生成新码后，旧码立即失效。</p>
      <n-button secondary :loading="busy" @click="generateCodes"><template #icon><refresh-cw :size="16" /></template>生成恢复码</n-button>
      <div v-if="codes.length" class="recovery-panel">
        <div class="recovery-panel-head"><strong>请妥善保存，离开此页后不再显示</strong><n-button size="small" @click="copyCodes"><template #icon><copy :size="15" /></template>复制全部</n-button></div>
        <div class="recovery-grid"><code v-for="code in codes" :key="code">{{ code }}</code></div>
      </div>
    </section>
  </div>
</template>
