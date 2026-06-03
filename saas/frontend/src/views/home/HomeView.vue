<template>
  <section class="dashboard">
    <div class="hero glass-panel">
      <div>
        <h2 class="section-title">欢迎回来，{{ authStore.displayName }}</h2>
        <div class="section-subtitle">登录后基于组织自动加载页面权限，管理员默认可见全部页面。</div>
      </div>
      <el-tag type="primary" size="large">{{ authStore.user?.organizationName }}</el-tag>
    </div>

    <div class="card-grid">
      <article class="metric-card glass-panel">
        <div class="metric-label">当前组织</div>
        <div class="metric-value">{{ authStore.user?.organizationName || '-' }}</div>
      </article>
      <article class="metric-card glass-panel">
        <div class="metric-label">可见页面</div>
        <div class="metric-value">{{ authStore.routePermissions.length }}</div>
      </article>
      <article class="metric-card glass-panel">
        <div class="metric-label">运行环境</div>
        <div class="metric-value">{{ appTitle }}</div>
      </article>
    </div>

    <article class="glass-panel list-panel">
      <h3 class="section-title">当前页面权限</h3>
      <div class="section-subtitle">以下列表来自数据库路由权限表和组织赋权关系。</div>
      <el-table :data="authStore.routePermissions" style="margin-top: 18px">
        <el-table-column prop="title" label="页面标题" min-width="160" />
        <el-table-column prop="routePath" label="路由路径" min-width="140" />
        <el-table-column prop="componentPath" label="组件路径" min-width="220" />
      </el-table>
    </article>
  </section>
</template>

<script setup>
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()
const appTitle = import.meta.env.VITE_APP_TITLE
</script>

<style scoped>
.dashboard {
  display: grid;
  gap: 20px;
}

.hero,
.list-panel {
  padding: 24px;
  border-radius: 28px;
}

.hero {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
}

.metric-card {
  border-radius: 24px;
  padding: 20px;
}

.metric-label {
  color: var(--text-sub);
  margin-bottom: 14px;
}

.metric-value {
  font-size: 28px;
  font-weight: 700;
}

@media (max-width: 960px) {
  .card-grid {
    grid-template-columns: 1fr;
  }

  .hero {
    flex-direction: column;
    align-items: flex-start;
    gap: 16px;
  }
}
</style>
