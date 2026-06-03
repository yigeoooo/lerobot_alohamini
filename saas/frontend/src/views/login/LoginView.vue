<template>
  <div class="login-shell page-shell">
    <section class="login-card glass-panel">
      <div class="login-copy">
        <div class="login-badge">{{ appTitle }}</div>
        <h1>训练推理一体化平台</h1>
        <p>
          基于组织的页面权限控制，登录后自动加载可见页面。
          开发环境和测试环境已分离，方便后续部署到服务器。
        </p>
        <div class="login-tip">
          默认管理员：632084210@qq.com / Admin@123456
        </div>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @submit.prevent>
        <el-form-item label="邮箱" prop="email">
          <el-input v-model="form.email" placeholder="请输入邮箱" size="large" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="form.password" type="password" show-password placeholder="请输入密码" size="large" />
        </el-form-item>
        <el-button type="primary" size="large" class="submit-button" :loading="submitting" @click="handleLogin">
          登录并进入主页
        </el-button>
      </el-form>
    </section>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../../stores/auth'
import { registerDynamicRoutes } from '../../router'

const appTitle = import.meta.env.VITE_APP_TITLE
const authStore = useAuthStore()
const router = useRouter()
const route = useRoute()
const formRef = ref()
const submitting = ref(false)
const form = reactive({
  email: '632084210@qq.com',
  password: 'Admin@123456'
})

const rules = {
  email: [{ required: true, message: '请输入邮箱', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

async function handleLogin() {
  await formRef.value.validate()
  submitting.value = true
  try {
    const result = await authStore.login(form)
    registerDynamicRoutes(result.routePermissions)
    ElMessage.success('登录成功')
    router.replace(route.query.redirect || authStore.defaultRoute)
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.login-shell {
  display: grid;
  place-items: center;
  padding: 24px;
  background:
    radial-gradient(circle at top left, rgba(90, 150, 255, 0.22), transparent 30%),
    radial-gradient(circle at bottom right, rgba(176, 214, 255, 0.35), transparent 28%),
    var(--app-bg);
}

.login-card {
  width: min(980px, 100%);
  display: grid;
  grid-template-columns: 1.15fr 0.85fr;
  gap: 36px;
  padding: 34px;
  border-radius: 32px;
}

.login-badge {
  display: inline-flex;
  padding: 8px 14px;
  border-radius: 999px;
  color: var(--primary-color);
  background: rgba(47, 107, 255, 0.1);
  font-weight: 600;
}

.login-copy h1 {
  margin: 18px 0 14px;
  font-size: 42px;
  line-height: 1.1;
}

.login-copy p,
.login-tip {
  color: var(--text-sub);
  line-height: 1.8;
}

.submit-button {
  width: 100%;
  margin-top: 8px;
}

@media (max-width: 860px) {
  .login-card {
    grid-template-columns: 1fr;
  }
}
</style>
