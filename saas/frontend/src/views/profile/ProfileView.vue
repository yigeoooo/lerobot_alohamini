<template>
  <section class="page-grid">
    <article class="glass-panel profile-panel">
      <div class="profile-header">
        <div>
          <h2 class="section-title">个人中心</h2>
        </div>
        <el-avatar :size="72" :icon="resolveIcon(profile.avatarIconName)" class="profile-avatar" />
      </div>
      <el-form :model="profile" label-position="top" class="form-grid" style="margin-top: 18px">
        <el-form-item label="姓名">
          <el-input v-model="profile.name" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="profile.gender">
            <el-option label="男" :value="1" />
            <el-option label="女" :value="2" />
          </el-select>
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="profile.email" />
        </el-form-item>
        <el-form-item label="所属组织">
          <el-input :model-value="profile.organizationName" disabled />
        </el-form-item>
        <el-form-item label="头像图标" style="grid-column: 1 / -1">
          <el-radio-group v-model="profile.avatarIconId" class="icon-grid">
            <el-radio-button v-for="icon in icons" :key="icon.id" :label="icon.id">
              <span class="icon-option">
                <el-icon><component :is="resolveIcon(icon.componentName)" /></el-icon>
                {{ icon.componentName }}
              </span>
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <el-button type="primary" @click="saveProfile">保存资料</el-button>
    </article>

    <article class="glass-panel profile-panel">
      <h2 class="section-title">修改密码</h2>
      <div class="section-subtitle">修改成功后建议重新登录。</div>
      <el-form :model="passwordForm" label-position="top" class="form-grid" style="margin-top: 18px">
        <el-form-item label="旧密码">
          <el-input v-model="passwordForm.oldPassword" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="passwordForm.newPassword" type="password" show-password />
        </el-form-item>
      </el-form>
      <el-button type="primary" @click="savePassword">修改密码</el-button>
    </article>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import * as ElementPlusIconsVue from '@element-plus/icons-vue'
import { Operation } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { fetchIconsApi } from '../../api/icon'
import { fetchCurrentUserApi, updateCurrentUserPasswordApi, updateCurrentUserProfileApi } from '../../api/user'
import { useAuthStore } from '../../stores/auth'

const authStore = useAuthStore()
const icons = ref([])
const profile = reactive({
  name: '',
  gender: 1,
  email: '',
  organizationName: '',
  avatarIconId: '',
  avatarIconName: ''
})
const passwordForm = reactive({
  oldPassword: '',
  newPassword: ''
})

function resolveIcon(iconName) {
  return ElementPlusIconsVue[iconName] || Operation
}

async function loadProfile() {
  const result = await fetchCurrentUserApi()
  Object.assign(profile, result)
}

async function loadIcons() {
  icons.value = await fetchIconsApi()
}

async function saveProfile() {
  await updateCurrentUserProfileApi({
    name: profile.name,
    gender: profile.gender,
    email: profile.email,
    avatarIconId: profile.avatarIconId
  })
  ElMessage.success('个人资料已更新')
  await authStore.fetchProfile()
  await loadProfile()
}

async function savePassword() {
  await updateCurrentUserPasswordApi(passwordForm)
  ElMessage.success('密码修改成功')
  passwordForm.oldPassword = ''
  passwordForm.newPassword = ''
}

onMounted(async () => {
  await Promise.all([loadProfile(), loadIcons()])
})
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 20px;
}

.profile-panel {
  padding: 24px;
  border-radius: 28px;
}

.profile-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.profile-avatar {
  background: rgba(47, 107, 255, 0.12);
  color: var(--primary-color);
}

.icon-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.icon-option {
  display: inline-flex;
  gap: 6px;
  align-items: center;
}
</style>
