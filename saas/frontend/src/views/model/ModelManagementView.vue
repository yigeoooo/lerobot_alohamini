<template>
  <section class="page-grid">
    <section class="summary-grid">
      <article class="glass-panel summary-card">
        <div class="field-label">当前策略目录数</div>
        <div class="metric-value">{{ policyDirectories.length }}</div>
      </article>
      <article class="glass-panel summary-card">
        <div class="field-label">已配置模型数</div>
        <div class="metric-value">{{ models.length }}</div>
      </article>
    </section>

    <article class="glass-panel form-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">模型管理</h2>
        </div>
        <div class="toolbar-actions">
          <el-button @click="reloadAll">刷新</el-button>
          <el-button type="primary" @click="openCreate">新增模型</el-button>
        </div>
      </div>

      <div class="detail-block" style="margin-top: 18px">
        <div class="field-label">可用策略目录</div>
        <div class="tag-group">
          <el-tag v-for="item in policyDirectories" :key="item.policyCode" size="large">{{ item.policyCode }}</el-tag>
          <span v-if="policyDirectories.length === 0">未扫描到策略目录</span>
        </div>
      </div>
    </article>

    <article class="glass-panel table-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">已配置训练模型</h2>
        </div>
      </div>

      <el-table :data="models" style="margin-top: 18px">
        <el-table-column prop="modelCode" label="模型 Code" min-width="160" />
        <el-table-column prop="modelName" label="模型名称" min-width="180" />
        <el-table-column prop="sort" label="排序" width="90" />
        <el-table-column prop="createdTime" label="创建时间" min-width="180" />
        <el-table-column prop="updatedTime" label="修改时间" min-width="180" />
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openEdit(scope.row)">编辑</el-button>
            <el-button link type="danger" @click="removeModel(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </article>

    <el-dialog v-model="dialogVisible" :title="editingId ? '编辑模型' : '新增模型'" width="520px">
      <el-form :model="form" label-position="top" class="form-grid">
        <el-form-item label="模型 Code">
          <el-select v-model="form.modelCode" filterable placeholder="请选择策略目录">
            <el-option
              v-for="item in policyDirectories"
              :key="item.policyCode"
              :label="item.policyCode"
              :value="item.policyCode"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名称">
          <el-input v-model="form.modelName" placeholder="例如：ACT 基础模型" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" :step="1" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submit">保存</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createModelApi, deleteModelApi, fetchModelsApi, fetchPolicyDirectoriesApi, updateModelApi } from '../../api/model'

const policyDirectories = ref([])
const models = ref([])
const dialogVisible = ref(false)
const editingId = ref('')
const form = reactive({
  modelCode: '',
  modelName: '',
  sort: 0
})

async function loadPolicyDirectories() {
  policyDirectories.value = await fetchPolicyDirectoriesApi()
}

async function loadModels() {
  models.value = await fetchModelsApi()
}

async function reloadAll() {
  await Promise.all([loadPolicyDirectories(), loadModels()])
}

function resetForm() {
  editingId.value = ''
  form.modelCode = policyDirectories.value[0]?.policyCode || ''
  form.modelName = ''
  form.sort = 0
}

function openCreate() {
  resetForm()
  dialogVisible.value = true
}

function openEdit(row) {
  editingId.value = row.id
  form.modelCode = row.modelCode
  form.modelName = row.modelName
  form.sort = row.sort ?? 0
  dialogVisible.value = true
}

async function submit() {
  const payload = {
    modelCode: form.modelCode,
    modelName: form.modelName,
    sort: form.sort
  }

  if (editingId.value) {
    await updateModelApi(editingId.value, payload)
    ElMessage.success('模型更新成功')
  } else {
    await createModelApi(payload)
    ElMessage.success('模型创建成功')
  }
  dialogVisible.value = false
  await loadModels()
}

async function removeModel(row) {
  await ElMessageBox.confirm(`确认删除模型 ${row.modelName} 吗？`, '提示', { type: 'warning' })
  await deleteModelApi(row.id)
  ElMessage.success('模型删除成功')
  await loadModels()
}

onMounted(async () => {
  await reloadAll()
  resetForm()
})
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 20px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 20px;
}

.summary-card,
.form-panel,
.table-panel {
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

.metric-value {
  font-size: 34px;
  font-weight: 700;
}

.detail-block {
  display: grid;
  gap: 12px;
}

.tag-group {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

@media (max-width: 960px) {
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .toolbar-row,
  .toolbar-actions {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
