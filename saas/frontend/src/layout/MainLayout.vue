<template>
  <div class="layout-shell page-shell">
    <aside class="layout-aside glass-panel">
      <div class="brand-block">
        <div class="brand-mark">L</div>
        <div>
          <div class="brand-title">LeRobot 平台</div>
          <div class="brand-subtitle">训练 / 推理一体化</div>
        </div>
      </div>
      <el-menu
        :default-active="activePath"
        class="nav-menu"
        @select="handleSelect"
      >
        <el-menu-item
          v-for="item in menuItems"
          :key="item.routePath"
          :index="item.routePath"
        >
          <el-icon><component :is="resolveIcon(item.icon)" /></el-icon>
          <span>{{ item.title }}</span>
        </el-menu-item>
      </el-menu>
    </aside>

    <div class="layout-main">
      <header class="layout-header glass-panel">
        <div>
          <div class="header-title">{{ currentTitle }}</div>
          <div class="header-subtitle">{{ authStore.user?.organizationName || '未绑定组织' }}</div>
        </div>
        <div class="header-actions">
          <el-tag effect="dark" type="primary">
            {{ authStore.user?.systemAdmin ? '系统管理员' : '组织成员' }}
          </el-tag>
          <el-dropdown>
            <div class="user-trigger">
              <el-avatar class="user-avatar" :icon="resolveIcon(authStore.user?.avatarIconName)" />
              <span>{{ authStore.displayName }}</span>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item @click="handleSelect('/profile')">个人中心</el-dropdown-item>
                <el-dropdown-item @click="handleLogout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </header>

      <main class="layout-content">
        <router-view />
      </main>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { Operation } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const authStore = useAuthStore()

const menuItems = computed(() => authStore.routePermissions)
const activePath = computed(() => route.meta.permissionPath || route.path)
const currentTitle = computed(() => route.meta.title || '平台首页')

function resolveIcon(iconName) {
  return ElementPlusIconsVue[iconName] || Operation
}

function handleSelect(path) {
  router.push(path)
}

function handleLogout() {
  authStore.reset()
  router.replace('/login')
}
</script>

<style scoped>
.layout-shell {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 20px;
  padding: 20px;
}

.layout-aside {
  padding: 24px 18px;
  border-radius: 28px;
}

.brand-block {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 30px;
}

.brand-mark {
  width: 48px;
  height: 48px;
  border-radius: 18px;
  display: grid;
  place-items: center;
  font-size: 26px;
  font-weight: 700;
  color: #fff;
  background: linear-gradient(135deg, #2f6bff, #6ba6ff);
}

.brand-title {
  font-size: 18px;
  font-weight: 700;
}

.brand-subtitle,
.header-subtitle {
  color: var(--text-sub);
  font-size: 13px;
}

.nav-menu {
  border: none;
  background: transparent;
}

.nav-menu :deep(.el-menu-item) {
  border-radius: 14px;
  color: var(--text-main);
  margin-bottom: 8px;
}

.nav-menu :deep(.el-menu-item.is-active) {
  background: rgba(47, 107, 255, 0.1);
  color: var(--primary-color);
}

.layout-main {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.layout-header {
  border-radius: 24px;
  padding: 18px 22px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-title {
  font-size: 22px;
  font-weight: 700;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 14px;
}

.user-trigger {
  cursor: pointer;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 10px;
}

.user-avatar {
  background: rgba(47, 107, 255, 0.12);
  color: var(--primary-color);
}

.layout-content {
  min-height: calc(100vh - 140px);
}

@media (max-width: 960px) {
  .layout-shell {
    grid-template-columns: 1fr;
  }
}
</style>
