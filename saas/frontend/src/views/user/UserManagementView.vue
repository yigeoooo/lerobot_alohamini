<template>
  <section class="page-grid">
    <article class="glass-panel form-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">用户管理</h2>
          <div class="section-subtitle">仅管理员可见，支持用户查询、增删改查与密码重置。</div>
        </div>
        <div class="toolbar-actions">
          <el-input v-model="keyword" placeholder="按姓名/邮箱/组织模糊查询" clearable @keyup.enter="loadUsers" />
          <el-select v-model="organizationId" clearable placeholder="筛选组织">
            <el-option v-for="organization in organizations" :key="organization.id" :label="organization.organizationName" :value="organization.id" />
          </el-select>
          <el-button @click="loadUsers">查询</el-button>
          <el-button type="primary" @click="openCreate">新增用户</el-button>
        </div>
      </div>
      <el-table :data="users" style="margin-top: 18px">
        <el-table-column prop="name" label="姓名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column prop="organizationName" label="组织" min-width="140" />
        <el-table-column prop="avatarIconName" label="头像图标" min-width="130" />
        <el-table-column label="管理员" width="110">
          <template #default="scope">
            <el-tag :type="scope.row.systemAdmin ? 'danger' : 'info'">{{ scope.row.systemAdmin ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rawPassword" label="原始密码" min-width="120" />
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
            <el-button link type="primary" @click="openReset(scope.row)">重置密码</el-button>
            <el-button link type="danger" @click="removeUser(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </article>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑用户' : '新增用户'" width="680px">
      <el-form :model="form" label-position="top" class="form-grid">
        <el-form-item label="姓名">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="form.gender">
            <el-option label="男" :value="1" />
            <el-option label="女" :value="2" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属组织">
          <el-select v-model="form.organizationId">
            <el-option v-for="organization in organizations" :key="organization.id" :label="organization.organizationName" :value="organization.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" />
        </el-form-item>
        <el-form-item v-if="!editingId" label="初始密码">
          <el-input v-model="form.rawPassword" placeholder="为空则默认 123456" />
        </el-form-item>
        <el-form-item label="头像图标">
          <el-select v-model="form.avatarIconId" filterable>
            <el-option v-for="icon in icons" :key="icon.id" :label="icon.componentName" :value="icon.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="系统管理员">
          <el-switch v-model="form.systemAdmin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置密码" width="420px">
      <el-form :model="resetForm" label-position="top">
        <el-form-item label="新密码">
          <el-input v-model="resetForm.newPassword" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resetVisible = false">取消</el-button>
        <el-button type="primary" @click="submitReset">确认重置</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { fetchIconsApi } from '../../api/icon'
import { fetchOrganizationsApi } from '../../api/organization'
import { createUserApi, deleteUserApi, fetchUsersApi, resetUserPasswordApi, updateUserApi } from '../../api/user'

const users = ref([])
const organizations = ref([])
const icons = ref([])
const keyword = ref('')
const organizationId = ref('')
const dialogVisible = ref(false)
const resetVisible = ref(false)
const editingId = ref('')
const resetUserId = ref('')
const form = reactive({
  name: '',
  gender: 1,
  organizationId: '',
  email: '',
  rawPassword: '',
  avatarIconId: '',
  systemAdmin: false
})
const resetForm = reactive({
  newPassword: '123456'
})

async function loadUsers() {
  users.value = await fetchUsersApi({ keyword: keyword.value, organizationId: organizationId.value })
}

async function loadOrganizations() {
  organizations.value = await fetchOrganizationsApi()
}

async function loadIcons() {
  icons.value = await fetchIconsApi()
}

function resetEditForm() {
  editingId.value = ''
  form.name = ''
  form.gender = 1
  form.organizationId = organizations.value[0]?.id || ''
  form.email = ''
  form.rawPassword = ''
  form.avatarIconId = icons.value[0]?.id || ''
  form.systemAdmin = false
}

function openCreate() {
  resetEditForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.name = row.name
  form.gender = row.gender
  form.organizationId = row.organizationId
  form.email = row.email
  form.rawPassword = ''
  form.avatarIconId = row.avatarIconId
  form.systemAdmin = row.systemAdmin
  dialogVisible.value = true
}

async function submit() {
  if (editingId.value) {
    await updateUserApi(editingId.value, form)
    ElMessage.success('用户更新成功')
  } else {
    await createUserApi(form)
    ElMessage.success('用户创建成功')
  }
  dialogVisible.value = false
  await loadUsers()
}

function openReset(row) {
  resetUserId.value = row.id
  resetForm.newPassword = '123456'
  resetVisible.value = true
}

async function submitReset() {
  await resetUserPasswordApi(resetUserId.value, resetForm)
  ElMessage.success('密码重置成功')
  resetVisible.value = false
  await loadUsers()
}

async function removeUser(row) {
  await ElMessageBox.confirm(`确认删除用户 ${row.name} 吗？`, '提示', { type: 'warning' })
  await deleteUserApi(row.id)
  ElMessage.success('用户删除成功')
  await loadUsers()
}

onMounted(async () => {
  await Promise.all([loadOrganizations(), loadIcons()])
  resetEditForm()
  await loadUsers()
})
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 20px;
}

.form-panel {
  padding: 24px;
  border-radius: 28px;
}

.toolbar-row {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}

.toolbar-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.toolbar-actions :deep(.el-input) {
  width: 240px;
}

.toolbar-actions :deep(.el-select) {
  width: 180px;
}

@media (max-width: 960px) {
  .toolbar-row,
  .toolbar-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
