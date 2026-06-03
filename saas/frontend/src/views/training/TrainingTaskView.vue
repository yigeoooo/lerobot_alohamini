<template>
  <section class="page-grid">
    <section class="summary-grid">
      <article class="glass-panel summary-card">
        <div class="field-label">可训练数据集</div>
        <div class="metric-value">{{ datasets.length }}</div>
      </article>
      <article class="glass-panel summary-card">
        <div class="field-label">可用模型</div>
        <div class="metric-value">{{ models.length }}</div>
      </article>
      <article class="glass-panel summary-card">
        <div class="field-label">运行中任务</div>
        <div class="metric-value">{{ runningTaskCount }}</div>
      </article>
      <article class="glass-panel summary-card">
        <div class="field-label">已保存模型</div>
        <div class="metric-value">{{ savedModels.length }}</div>
      </article>
    </section>

    <article class="glass-panel form-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">新增模型训练</h2>
        </div>
        <div class="toolbar-actions">
          <el-button :loading="loading" @click="loadAll">刷新</el-button>
          <el-button type="primary" :loading="submitting" @click="submitTraining">开始训练</el-button>
        </div>
      </div>

      <el-form :model="form" label-position="top" class="train-form">
        <el-form-item label="任务名称">
          <el-input v-model="form.taskName" placeholder="例如：ACT aloha mini 训练" />
        </el-form-item>
        <el-form-item label="训练数据集">
          <el-select v-model="form.datasetId" filterable placeholder="选择我的成功数据集">
            <el-option
              v-for="item in datasets"
              :key="item.id"
              :label="datasetOptionLabel(item)"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="训练模型">
          <el-select v-model="form.modelId" filterable placeholder="选择已配置模型" @change="handleModelChange">
            <el-option
              v-for="item in models"
              :key="item.id"
              :label="`${item.modelName} (${item.modelCode})`"
              :value="item.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Policy Repo ID">
          <el-input v-model="form.policyRepoId"/>
        </el-form-item>
        <el-form-item label="设备">
          <el-select v-model="form.device">
            <el-option label="cuda" value="cuda" />
            <el-option label="cpu" value="cpu" />
          </el-select>
        </el-form-item>
        <el-form-item label="训练步数 steps">
          <el-input-number v-model="form.steps" :min="1" :step="1000" />
        </el-form-item>
        <el-form-item label="Batch Size">
          <el-input-number v-model="form.batchSize" :min="1" :step="1" />
        </el-form-item>
        <!-- <el-form-item label="WandB">
          <el-switch v-model="form.wandbEnable" active-text="启用" inactive-text="关闭" />
        </el-form-item> -->
        <el-form-item label="优化器">
          <el-input v-model="form.optimizerType" />
        </el-form-item>
        <el-form-item label="学习率">
          <el-input v-model="form.optimizerLr" />
        </el-form-item>
        <el-form-item label="Weight Decay">
          <el-input v-model="form.optimizerWeightDecay" />
        </el-form-item>
        <el-form-item label="Grad Clip Norm">
          <el-input v-model="form.optimizerGradClipNorm" />
        </el-form-item>
        <el-form-item label="Log Freq">
          <el-input-number v-model="form.logFreq" :min="1" :step="100" />
        </el-form-item>
        <el-form-item label="Save Freq">
          <el-input-number v-model="form.saveFreq" :min="1" :step="1000" />
        </el-form-item>
        <el-form-item label="Chunk Size">
          <el-input-number v-model="form.policyChunkSize" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="Action Steps">
          <el-input-number v-model="form.policyActionSteps" :min="1" :step="1" />
        </el-form-item>
        <el-form-item label="AMP">
          <el-switch v-model="form.useAmp" active-text="启用" inactive-text="关闭" />
        </el-form-item>
      </el-form>
    </article>

    <article class="glass-panel table-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">个人已保存模型</h2>
        </div>
        <el-button @click="loadSavedModels">刷新</el-button>
      </div>

      <el-table :data="savedModels" empty-text="当前还没有可下载的模型目录" style="margin-top: 18px">
        <el-table-column prop="name" label="目录名" min-width="180" />
        <el-table-column prop="path" label="保存路径" min-width="320" />
        <el-table-column label="大小" min-width="120">
          <template #default="scope">{{ formatBytes(scope.row.sizeBytes) }}</template>
        </el-table-column>
        <el-table-column prop="updatedTime" label="最近修改" min-width="180" />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="downloadSavedModel(scope.row)">下载</el-button>
          </template>
        </el-table-column>
      </el-table>
    </article>

    <article class="glass-panel table-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">训练任务</h2>
          <div class="section-subtitle">任务在后台执行，可查看日志、中断运行中任务，成功后下载模型归档。</div>
        </div>
        <el-button @click="loadTasks">刷新</el-button>
      </div>

      <el-table :data="tasks" empty-text="暂无训练任务" style="margin-top: 18px">
        <el-table-column prop="taskName" label="任务名称" min-width="180" />
        <el-table-column prop="datasetName" label="数据集" min-width="180" />
        <el-table-column label="模型" min-width="160">
          <template #default="scope">{{ scope.row.modelName }} / {{ scope.row.modelCode }}</template>
        </el-table-column>
        <el-table-column label="状态" width="120">
          <template #default="scope">
            <el-tag :type="statusTag(scope.row.taskStatus)">{{ statusText(scope.row.taskStatus) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="outputDir" label="输出目录" min-width="320" />
        <el-table-column prop="processId" label="PID" min-width="100" />
        <el-table-column prop="createdTime" label="创建时间" min-width="180" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openLog(scope.row)">日志</el-button>
            <el-button v-if="canStop(scope.row)" link type="danger" @click="stopTask(scope.row)">中断</el-button>
            <el-button v-if="canDownload(scope.row)" link type="primary" @click="downloadTaskModel(scope.row)">下载</el-button>
          </template>
        </el-table-column>
      </el-table>
    </article>

    <el-dialog v-model="logVisible" title="训练日志" width="1600px" @closed="stopLogPolling">
      <div class="log-toolbar">
        <span>{{ currentLogTask?.taskName || "-" }}</span>
        <el-button :loading="logLoading" @click="loadCurrentLog">刷新日志</el-button>
      </div>
      <pre class="log-box">{{ currentLog || "暂无日志" }}</pre>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, reactive, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { fetchMyDatasetsApi } from "../../api/dataset"
import { fetchModelsApi } from "../../api/model"
import {
  createTrainingTaskApi,
  downloadSavedModelApi,
  downloadTrainingTaskModelApi,
  fetchMyTrainingTasksApi,
  fetchSavedModelsApi,
  fetchTrainingTaskLogApi,
  stopTrainingTaskApi
} from "../../api/training"

const datasets = ref([])
const models = ref([])
const tasks = ref([])
const savedModels = ref([])
const loading = ref(false)
const submitting = ref(false)
const logVisible = ref(false)
const logLoading = ref(false)
const currentLog = ref("")
const currentLogTask = ref(null)
let logTimer = null

const form = reactive({
  taskName: "",
  datasetId: "",
  modelId: "",
  policyRepoId: "",
  device: "cuda",
  wandbEnable: false,
  steps: 50000,
  batchSize: 4,
  useAmp: true,
  optimizerType: "adamw",
  optimizerLr: "1e-5",
  optimizerWeightDecay: "0.0",
  optimizerGradClipNorm: "10.0",
  logFreq: 100,
  saveFreq: 5000,
  policyChunkSize: 40,
  policyActionSteps: 40
})

const runningTaskCount = computed(() => tasks.value.filter((item) => canStop(item)).length)

async function loadAll() {
  loading.value = true
  try {
    await Promise.all([loadDatasets(), loadModels(), loadTasks(), loadSavedModels()])
    applyDefaultSelection()
  } finally {
    loading.value = false
  }
}

async function loadDatasets() {
  datasets.value = await fetchMyDatasetsApi()
}

async function loadModels() {
  models.value = await fetchModelsApi()
}

async function loadTasks() {
  tasks.value = await fetchMyTrainingTasksApi()
}

async function loadSavedModels() {
  savedModels.value = await fetchSavedModelsApi()
}

function applyDefaultSelection() {
  if (!form.datasetId && datasets.value[0]) {
    form.datasetId = datasets.value[0].id
  }
  if (!form.modelId && models.value[0]) {
    form.modelId = models.value[0].id
    handleModelChange(form.modelId)
  }
}

function handleModelChange(modelId) {
  const model = models.value.find((item) => item.id === modelId)
  if (!model) {
    return
  }
  if (!form.taskName) {
    form.taskName = `${model.modelName}训练`
  }
  if (!form.policyRepoId && model.modelCode === "act") {
    form.policyRepoId = "WinterSpire/act_alohamini_v7"
  }
}

async function submitTraining() {
  if (!form.taskName || !form.datasetId || !form.modelId || !form.policyRepoId) {
    ElMessage.warning("请完整填写任务名称、数据集、模型和 Policy Repo ID")
    return
  }

  submitting.value = true
  try {
    await createTrainingTaskApi({ ...form })
    ElMessage.success("训练任务已创建，后台开始执行")
    await Promise.all([loadTasks(), loadSavedModels()])
  } finally {
    submitting.value = false
  }
}

async function openLog(row) {
  currentLogTask.value = row
  currentLog.value = ""
  logVisible.value = true
  await loadCurrentLog()
  startLogPolling()
}

async function loadCurrentLog() {
  if (!currentLogTask.value) {
    return
  }
  logLoading.value = true
  try {
    currentLog.value = await fetchTrainingTaskLogApi(currentLogTask.value.id)
  } finally {
    logLoading.value = false
  }
}

function startLogPolling() {
  stopLogPolling()
  logTimer = window.setInterval(async () => {
    if (currentLogTask.value && canStop(currentLogTask.value)) {
      await loadCurrentLog()
      await loadTasks()
      currentLogTask.value = tasks.value.find((item) => item.id === currentLogTask.value.id) || currentLogTask.value
    }
  }, 3000)
}

function stopLogPolling() {
  if (logTimer) {
    window.clearInterval(logTimer)
    logTimer = null
  }
}

async function stopTask(row) {
  await ElMessageBox.confirm(`确认中断训练任务 ${row.taskName} 吗？`, "提示", { type: "warning" })
  await stopTrainingTaskApi(row.id)
  ElMessage.success("训练任务已中断")
  await Promise.all([loadTasks(), loadSavedModels()])
}

async function downloadTaskModel(row) {
  const response = await downloadTrainingTaskModelApi(row.id)
  triggerBlobDownload(response, `${row.taskName}.tar.gz`)
}

async function downloadSavedModel(row) {
  const response = await downloadSavedModelApi(row.name)
  triggerBlobDownload(response, `${row.name}.tar.gz`)
}

function triggerBlobDownload(response, fallbackName) {
  const blob = new Blob([response.data], { type: response.headers["content-type"] || "application/octet-stream" })
  const url = URL.createObjectURL(blob)
  const link = document.createElement("a")
  link.href = url
  link.download = resolveDownloadFileName(response, fallbackName)
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  URL.revokeObjectURL(url)
}

function resolveDownloadFileName(response, fallbackName) {
  const contentDisposition = response.headers["content-disposition"] || ""
  const match = contentDisposition.match(/filename="?([^";]+)"?/)
  if (!match) {
    return fallbackName
  }
  try {
    return decodeURIComponent(match[1])
  } catch {
    return match[1]
  }
}

function canStop(row) {
  return row.taskStatus === "RUNNING" || row.taskStatus === "PENDING"
}

function canDownload(row) {
  return row.taskStatus === "SUCCESS"
}

function statusText(status) {
  const statusMap = {
    PENDING: "等待中",
    RUNNING: "训练中",
    SUCCESS: "成功",
    FAILED: "失败",
    STOPPED: "已中断"
  }
  return statusMap[status] || status || "-"
}

function statusTag(status) {
  const tagMap = {
    PENDING: "info",
    RUNNING: "warning",
    SUCCESS: "success",
    FAILED: "danger",
    STOPPED: "info"
  }
  return tagMap[status] || "info"
}

function datasetOptionLabel(item) {
  return `${item.datasetName} (${item.totalFrames || 0} frames)`
}

function formatBytes(bytes) {
  const value = Number(bytes || 0)
  if (value < 1024) {
    return `${value} B`
  }
  if (value < 1024 * 1024) {
    return `${(value / 1024).toFixed(2)} KB`
  }
  if (value < 1024 * 1024 * 1024) {
    return `${(value / 1024 / 1024).toFixed(2)} MB`
  }
  return `${(value / 1024 / 1024 / 1024).toFixed(2)} GB`
}

onMounted(loadAll)
onUnmounted(stopLogPolling)
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 20px;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 20px;
}

.summary-card,
.form-panel,
.table-panel {
  padding: 24px;
  border-radius: 28px;
}

.toolbar-row,
.toolbar-actions,
.log-toolbar {
  display: flex;
  gap: 16px;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
}

.toolbar-actions {
  justify-content: flex-end;
}

.metric-value {
  font-size: 34px;
  font-weight: 700;
}

.train-form {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 4px 18px;
  margin-top: 20px;
}

.train-form :deep(.el-input-number),
.train-form :deep(.el-select) {
  width: 100%;
}

.log-toolbar {
  margin-bottom: 14px;
}

.log-box {
  min-height: 420px;
  max-height: 62vh;
  overflow: auto;
  padding: 18px;
  border-radius: 18px;
  background: #111827;
  color: #d1fae5;
  font-size: 13px;
  line-height: 1.55;
  white-space: pre-wrap;
}

@media (max-width: 1180px) {
  .summary-grid,
  .train-form {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 760px) {
  .summary-grid,
  .train-form {
    grid-template-columns: 1fr;
  }

  .toolbar-row,
  .toolbar-actions,
  .log-toolbar {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
