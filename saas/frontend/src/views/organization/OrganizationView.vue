<template>
  <section class="page-grid">
    <article class="glass-panel form-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">组织管理</h2>
          <div class="section-subtitle">支持组织新增、编辑、逻辑删除和模糊查询。</div>
        </div>
        <div class="toolbar-actions">
          <el-input v-model="keyword" placeholder="按名称/编码/说明搜索" clearable @keyup.enter="loadOrganizations" />
          <el-button @click="loadOrganizations">查询</el-button>
          <el-button type="primary" @click="openCreate">新增组织</el-button>
        </div>
      </div>
      <el-table :data="organizations" style="margin-top: 18px">
        <el-table-column prop="organizationName" label="组织名称" min-width="150" />
        <el-table-column prop="organizationCode" label="组织编码" min-width="140" />
        <el-table-column prop="description" label="说明" min-width="180" />
        <el-table-column prop="createdTime" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
            <el-button link type="danger" @click="removeOrganization(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </article>

    <article class="glass-panel form-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">组织成员</h2>
          <div class="section-subtitle">通过组织下拉框查看并维护该组织下的成员。</div>
        </div>
        <div class="toolbar-actions">
          <el-select
            v-model="selectedOrganizationId"
            filterable
            clearable
            placeholder="请选择组织"
            @change="handleOrganizationSelect"
          >
            <el-option
              v-for="organization in organizations"
              :key="organization.id"
              :label="organization.organizationName"
              :value="organization.id"
            />
          </el-select>
          <el-input
            v-model="memberKeyword"
            placeholder="按姓名/邮箱搜索成员"
            clearable
            :disabled="!currentOrganization"
            @keyup.enter="loadMembers"
          />
          <el-button :disabled="!currentOrganization" @click="loadMembers">查询</el-button>
          <el-button type="primary" :disabled="!currentOrganization" @click="openCreateMember">新增成员</el-button>
        </div>
      </div>
      <div class="section-subtitle" style="margin-top: 8px;">
        当前组织：{{ currentOrganization?.organizationName || '未选择组织' }}
      </div>
      <el-table :data="members" style="margin-top: 18px">
        <el-table-column prop="name" label="姓名" min-width="120" />
        <el-table-column prop="email" label="邮箱" min-width="180" />
        <el-table-column prop="avatarIconName" label="头像图标" min-width="130" />
        <el-table-column label="管理员" width="110">
          <template #default="scope">
            <el-tag :type="scope.row.systemAdmin ? 'danger' : 'info'">{{ scope.row.systemAdmin ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="rawPassword" label="原始密码" min-width="120" />
        <el-table-column label="操作" width="240" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEditMember(scope.row)">编辑</el-button>
            <el-button link type="primary" @click="openResetMember(scope.row)">重置密码</el-button>
            <el-button link type="danger" @click="removeMember(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </article>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑组织' : '新增组织'" width="520px">
      <el-form :model="form" label-position="top" class="form-grid">
        <el-form-item label="组织名称">
          <el-input v-model="form.organizationName" />
        </el-form-item>
        <el-form-item label="组织编码">
          <el-input v-model="form.organizationCode" />
        </el-form-item>
        <el-form-item label="组织说明" style="grid-column: 1 / -1">
          <el-input v-model="form.description" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="memberDialogVisible" :title="editingMemberId ? '编辑成员' : '新增成员'" width="680px">
      <el-form :model="memberForm" label-position="top" class="form-grid">
        <el-form-item label="姓名">
          <el-input v-model="memberForm.name" />
        </el-form-item>
        <el-form-item label="性别">
          <el-select v-model="memberForm.gender">
            <el-option label="男" :value="1" />
            <el-option label="女" :value="2" />
          </el-select>
        </el-form-item>
        <el-form-item label="所属组织">
          <el-input :model-value="currentOrganization?.organizationName || ''" disabled />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="memberForm.email" />
        </el-form-item>
        <el-form-item v-if="!editingMemberId" label="初始密码">
          <el-input v-model="memberForm.rawPassword" placeholder="为空则默认 123456" />
        </el-form-item>
        <el-form-item label="头像图标">
          <el-select v-model="memberForm.avatarIconId" filterable>
            <el-option
              v-for="icon in icons"
              :key="icon.id"
              :label="icon.componentName"
              :value="icon.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="系统管理员">
          <el-switch v-model="memberForm.systemAdmin" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="memberDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitMember">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="resetVisible" title="重置成员密码" width="420px">
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
import { createOrganizationApi, deleteOrganizationApi, fetchOrganizationsApi, updateOrganizationApi } from '../../api/organization'
import { createUserApi, deleteUserApi, fetchUsersApi, resetUserPasswordApi, updateUserApi } from '../../api/user'

const organizations = ref([])
const members = ref([])
const icons = ref([])
const currentOrganization = ref(null)
const selectedOrganizationId = ref('')

const keyword = ref('')
const memberKeyword = ref('')
const dialogVisible = ref(false)
const memberDialogVisible = ref(false)
const resetVisible = ref(false)
const editingId = ref('')
const editingMemberId = ref('')
const resetMemberId = ref('')

const form = reactive({
  organizationName: '',
  organizationCode: '',
  description: ''
})

const memberForm = reactive({
  name: '',
  gender: 1,
  email: '',
  rawPassword: '',
  avatarIconId: '',
  systemAdmin: false
})

const resetForm = reactive({
  newPassword: '123456'
})

async function loadOrganizations() {
  organizations.value = await fetchOrganizationsApi(keyword.value)
  if (organizations.value.length === 0) {
    currentOrganization.value = null
    selectedOrganizationId.value = ''
    members.value = []
    return
  }

  const matchedOrganization = organizations.value.find((item) => item.id === selectedOrganizationId.value)
  currentOrganization.value = matchedOrganization || organizations.value[0]
  selectedOrganizationId.value = currentOrganization.value.id
  await loadMembers()
}

async function loadMembers() {
  if (!currentOrganization.value) {
    members.value = []
    return
  }
  members.value = await fetchUsersApi({
    keyword: memberKeyword.value,
    organizationId: currentOrganization.value.id
  })
}

async function loadIcons() {
  icons.value = await fetchIconsApi()
}

function resetFormFields() {
  editingId.value = ''
  form.organizationName = ''
  form.organizationCode = ''
  form.description = ''
}

function resetMemberForm() {
  editingMemberId.value = ''
  memberForm.name = ''
  memberForm.gender = 1
  memberForm.email = ''
  memberForm.rawPassword = ''
  memberForm.avatarIconId = icons.value[0]?.id || ''
  memberForm.systemAdmin = false
}

function openCreate() {
  resetFormFields()
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.organizationName = row.organizationName
  form.organizationCode = row.organizationCode
  form.description = row.description
  dialogVisible.value = true
}

async function submit() {
  if (editingId.value) {
    await updateOrganizationApi(editingId.value, form)
    ElMessage.success('组织更新成功')
  } else {
    await createOrganizationApi(form)
    ElMessage.success('组织创建成功')
  }
  dialogVisible.value = false
  await loadOrganizations()
}

async function removeOrganization(row) {
  await ElMessageBox.confirm(`确认删除组织 ${row.organizationName} 吗？`, '提示', { type: 'warning' })
  await deleteOrganizationApi(row.id)
  ElMessage.success('组织删除成功')
  await loadOrganizations()
}

function handleOrganizationSelect(value) {
  currentOrganization.value = organizations.value.find((item) => item.id === value) || null
  memberKeyword.value = ''
  loadMembers()
}

function openCreateMember() {
  resetMemberForm()
  memberDialogVisible.value = true
}

function openEditMember(row) {
  editingMemberId.value = row.id
  memberForm.name = row.name
  memberForm.gender = row.gender
  memberForm.email = row.email
  memberForm.rawPassword = ''
  memberForm.avatarIconId = row.avatarIconId
  memberForm.systemAdmin = row.systemAdmin
  memberDialogVisible.value = true
}

async function submitMember() {
  const payload = {
    ...memberForm,
    organizationId: currentOrganization.value.id
  }

  if (editingMemberId.value) {
    await updateUserApi(editingMemberId.value, payload)
    ElMessage.success('成员更新成功')
  } else {
    await createUserApi(payload)
    ElMessage.success('成员创建成功')
  }
  memberDialogVisible.value = false
  await loadMembers()
}

function openResetMember(row) {
  resetMemberId.value = row.id
  resetForm.newPassword = '123456'
  resetVisible.value = true
}

async function submitReset() {
  await resetUserPasswordApi(resetMemberId.value, resetForm)
  ElMessage.success('密码重置成功')
  resetVisible.value = false
  await loadMembers()
}

async function removeMember(row) {
  await ElMessageBox.confirm(`确认删除成员 ${row.name} 吗？`, '提示', { type: 'warning' })
  await deleteUserApi(row.id)
  ElMessage.success('成员删除成功')
  await loadMembers()
}

onMounted(async () => {
  await Promise.all([loadIcons(), loadOrganizations()])
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
  width: 260px;
}

.toolbar-actions :deep(.el-select) {
  width: 220px;
}

@media (max-width: 960px) {
  .toolbar-row,
  .toolbar-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
