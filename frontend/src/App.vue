<script setup>
import { NConfigProvider, NDialogProvider, NMessageProvider, darkTheme, zhCN, dateZhCN } from 'naive-ui'
import { useThemeStore } from './stores/theme'

const theme = useThemeStore()

const themeOverrides = {
  common: {
    primaryColor: '#16866b',
    primaryColorHover: '#0f745c',
    primaryColorPressed: '#0b614d',
    primaryColorSuppl: '#16866b',
    borderRadius: '6px',
  },
}
</script>

<template>
  <n-config-provider :locale="zhCN" :date-locale="dateZhCN" :theme="theme.isDark ? darkTheme : null" :theme-overrides="themeOverrides">
    <n-dialog-provider>
      <n-message-provider>
        <router-view />
      </n-message-provider>
    </n-dialog-provider>
  </n-config-provider>
</template>
