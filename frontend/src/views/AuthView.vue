<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { NButton, NInput, useMessage } from 'naive-ui'
import { ArrowRight, LockKeyhole, UserRound, KeyRound } from 'lucide-vue-next'
import { api } from '../api'
import { useAuthStore } from '../stores/auth'

const props = defineProps({ mode: { type: String, required: true } })
const router = useRouter()
const message = useMessage()
const auth = useAuthStore()
const username = ref('')
const displayName = ref('')
const password = ref('')
const recoveryCode = ref('')
const busy = ref(false)
const error = ref('')

const heading = computed(() => ({
  login: '欢迎回来',
  register: '申请加入知库',
  recover: '恢复账号访问',
})[props.mode])

async function submit() {
  error.value = ''
  busy.value = true
  try {
    if (props.mode === 'login') {
      await auth.login(username.value, password.value)
      router.replace('/workspace')
    } else if (props.mode === 'register') {
      await api('/auth/register', {
        method: 'POST',
        body: { username: username.value, display_name: displayName.value, password: password.value },
      })
      message.success('申请已提交，管理员启用账号后即可登录')
      router.replace('/login')
    } else {
      await api('/auth/recover', {
        method: 'POST',
        body: {
          username: username.value,
          recovery_code: recoveryCode.value,
          new_password: password.value,
        },
      })
      message.success('密码已更新，请重新登录')
      router.replace('/login')
    }
  } catch (cause) {
    error.value = cause.message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <main class="auth-page">
    <div class="auth-brand">
      <div class="brand-symbol"><lock-keyhole :size="22" :stroke-width="2" /></div>
      <div>
        <div class="brand-name">项目知库</div>
        <div class="brand-subtitle">部门项目信息工作台</div>
      </div>
    </div>
    <section class="auth-panel">
      <div class="auth-eyebrow">PROJECT KNOWLEDGE BASE</div>
      <h1>{{ heading }}</h1>
      <p v-if="mode === 'login'" class="muted">使用你的部门账号继续。</p>
      <p v-else-if="mode === 'register'" class="muted">提交申请后，管理员会核验并启用账号。</p>
      <p v-else class="muted">输入你保存的一次性恢复码。</p>
      <form class="auth-form" @submit.prevent="submit">
        <label class="field-label" for="username">用户名</label>
        <n-input id="username" v-model:value="username" placeholder="请输入用户名" size="large" autocomplete="username" />
        <template v-if="mode === 'register'">
          <label class="field-label" for="display-name">显示名称</label>
          <n-input id="display-name" v-model:value="displayName" placeholder="你的姓名或称呼" size="large" />
        </template>
        <template v-if="mode === 'recover'">
          <label class="field-label" for="recovery-code">恢复码</label>
          <n-input id="recovery-code" v-model:value="recoveryCode" placeholder="一次性恢复码" size="large" />
        </template>
        <label class="field-label" for="password">{{ mode === 'recover' ? '新密码' : '密码' }}</label>
        <n-input id="password" v-model:value="password" type="password" show-password-on="click" :placeholder="mode === 'login' ? '请输入密码' : '至少 6 位'" size="large" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" />
        <div v-if="error || auth.refreshError" class="form-error" role="alert">{{ error || auth.refreshError }}</div>
        <n-button attr-type="submit" type="primary" size="large" :loading="busy" class="submit-button">
          {{ mode === 'login' ? '登录' : mode === 'register' ? '提交申请' : '重设密码' }}
          <template #icon><arrow-right :size="18" /></template>
        </n-button>
      </form>
      <div class="auth-links">
        <router-link v-if="mode !== 'login'" to="/login">返回登录</router-link>
        <template v-else>
          <router-link to="/register"><user-round :size="15" /> 申请账号</router-link>
          <router-link to="/recover"><key-round :size="15" /> 忘记密码</router-link>
        </template>
      </div>
    </section>
    <div class="auth-bottom">项目信息，仅对获得授权的成员开放</div>
  </main>
</template>
