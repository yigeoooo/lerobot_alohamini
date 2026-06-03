<template>
  <section class="page-grid">
    <article class="glass-panel selector-panel">
      <h2 class="section-title">组织赋权</h2>
      <el-select v-model="selectedOrganizationId" placeholder="请选择组织" style="width: 320px; margin-top: 18px" @change="loadOrganizationRoutes">
        <el-option
          v-for="organization in organizations"
          :key="organization.id"
          :label="organization.organizationName"
          :value="organization.id"
        />
      </el-select>
      <el-transfer
        v-model="selectedRouteIds"
        style="margin-top: 24px"
        filterable
        :titles="['未授权页面', '已授权页面']"
        :data="transferData"
      />
      <el-button type="primary" style="margin-top: 20px" :disabled="!selectedOrganizationId" @click="submit">
        保存组织权限
      </el-button>
    </article>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchOrganizationsApi } from '../../api/organization'
import { assignOrganizationRoutesApi, fetchOrganizationRouteIdsApi, fetchRoutePermissionsApi } from '../../api/permission'

const organizations = ref([])
const routePermissions = ref([])
const selectedOrganizationId = ref('')
const selectedRouteIds = ref([])

const transferData = computed(() => routePermissions.value.map((item) => ({
  key: item.id,
  label: `${item.title} (${item.routePath})`
})))

async function loadOrganizations() {
  organizations.value = await fetchOrganizationsApi()
  if (!selectedOrganizationId.value && organizations.value.length > 0) {
    selectedOrganizationId.value = organizations.value[0].id
  }
}

async function loadRoutePermissions() {
  routePermissions.value = await fetchRoutePermissionsApi()
}

async function loadOrganizationRoutes() {
  if (!selectedOrganizationId.value) {
    return
  }
  selectedRouteIds.value = await fetchOrganizationRouteIdsApi(selectedOrganizationId.value)
}

async function submit() {
  await assignOrganizationRoutesApi(selectedOrganizationId.value, {
    routePermissionIds: selectedRouteIds.value
  })
  ElMessage.success('组织权限保存成功')
}

onMounted(async () => {
  await Promise.all([loadOrganizations(), loadRoutePermissions()])
  await loadOrganizationRoutes()
})
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 20px;
}

.selector-panel {
  padding: 24px;
  border-radius: 28px;
}

:deep(.el-transfer) {
  width: 100%;
}

:deep(.el-transfer-panel) {
  width: min(100%, 360px);
}
</style>
