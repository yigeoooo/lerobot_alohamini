<template>
  <section class="page-grid">
    <article class="glass-panel form-panel">
      <h2 class="section-title">录入页面路由</h2>
      <div class="section-subtitle">新页面开发后，在这里录入路由、组件路径和图标，再到组织赋权页面分配权限。</div>
      <el-form :model="form" label-position="top" class="form-grid" style="margin-top: 18px">
        <el-form-item label="路由名称">
          <el-input v-model="form.routeName" placeholder="例如：training-list" />
        </el-form-item>
        <el-form-item label="路由路径">
          <el-input v-model="form.routePath" placeholder="例如：/training-tasks" />
        </el-form-item>
        <el-form-item label="页面标题">
          <el-input v-model="form.title" placeholder="例如：训练任务" />
        </el-form-item>
        <el-form-item label="图标">
          <el-select v-model="form.icon" filterable placeholder="请选择图标">
            <el-option
              v-for="icon in icons"
              :key="icon.id"
              :label="icon.componentName"
              :value="icon.componentName"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="管理员专属页面">
          <el-switch v-model="form.adminOnly" />
        </el-form-item>
        <el-form-item label="组件路径" style="grid-column: 1 / -1">
          <el-input v-model="form.componentPath" placeholder="例如：views/training/TrainingTaskListView" />
        </el-form-item>
      </el-form>
      <el-button type="primary" @click="submit">保存路由权限</el-button>
    </article>

    <article class="glass-panel table-panel">
      <h2 class="section-title">已登记页面</h2>
      <div class="section-subtitle">管理员默认可见全部页面，普通组织用户只会看到已赋权且非管理员专属的页面。</div>
      <el-table :data="routePermissions" style="margin-top: 18px">
        <el-table-column prop="title" label="页面标题" min-width="140" />
        <el-table-column prop="routeName" label="路由名称" min-width="130" />
        <el-table-column prop="routePath" label="路由路径" min-width="140" />
        <el-table-column prop="componentPath" label="组件路径" min-width="220" />
        <el-table-column prop="icon" label="图标" min-width="120" />
        <el-table-column label="管理员专属" width="120">
          <template #default="scope">
            <el-tag :type="scope.row.adminOnly ? 'danger' : 'info'">{{ scope.row.adminOnly ? '是' : '否' }}</el-tag>
          </template>
        </el-table-column>
      </el-table>
    </article>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { fetchIconsApi } from '../../api/icon'
import { createRoutePermissionApi, fetchRoutePermissionsApi } from '../../api/permission'

const routePermissions = ref([])
const icons = ref([])
const form = reactive({
  routeName: '',
  routePath: '',
  componentPath: '',
  title: '',
  icon: '',
  adminOnly: false
})

async function loadRoutePermissions() {
  routePermissions.value = await fetchRoutePermissionsApi()
}

async function loadIcons() {
  icons.value = await fetchIconsApi()
  if (!form.icon && icons.value.length > 0) {
    form.icon = icons.value[0].componentName
  }
}

async function submit() {
  await createRoutePermissionApi(form)
  ElMessage.success('页面路由已保存')
  form.routeName = ''
  form.routePath = ''
  form.componentPath = ''
  form.title = ''
  form.adminOnly = false
  form.icon = icons.value[0]?.componentName || ''
  await loadRoutePermissions()
}

onMounted(async () => {
  await Promise.all([loadRoutePermissions(), loadIcons()])
})
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 20px;
}

.form-panel,
.table-panel {
  padding: 24px;
  border-radius: 28px;
}
</style>
