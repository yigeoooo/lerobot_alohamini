<template>
  <section class="page-grid">
    <article class="glass-panel upload-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">数据集上传</h2>
          <div class="section-subtitle">支持 tar.gz、tgz、zip 和文件夹上传。上传后目录统一保存为 存放位置/组织id/个人id/数据集名。</div>
        </div>
        <el-tag type="primary">仅显示当前用户上传成功的数据集</el-tag>
      </div>

      <div class="upload-grid">
        <div>
          <div class="field-label">上传方式</div>
          <el-radio-group v-model="uploadMode">
            <el-radio-button label="archive">压缩包</el-radio-button>
            <el-radio-button label="folder">文件夹</el-radio-button>
          </el-radio-group>
        </div>
        <div>
          <div class="field-label">数据集名称</div>
          <el-input v-model="datasetName" placeholder="可选，不填则自动使用文件名或目录名" />
        </div>
      </div>

      <div class="selector-panel">
        <div>
          <div class="selector-title">{{ uploadMode === "archive" ? "选择归档文件" : "选择文件夹" }}</div>
          <div class="section-subtitle">{{ uploadHint }}</div>
        </div>
        <div class="selector-actions">
          <el-button @click="triggerSelect">选择</el-button>
          <el-button type="primary" :loading="uploading" :disabled="!hasSelection" @click="submitUpload">开始上传</el-button>
          <el-button :disabled="!hasSelection || uploading" @click="resetSelection">清空</el-button>
        </div>
      </div>

      <input ref="archiveInputRef" type="file" accept=".tar.gz,.tgz,.zip" hidden @change="handleArchiveChange" />
      <input ref="folderInputRef" type="file" hidden multiple webkitdirectory @change="handleFolderChange" />

      <div class="metric-grid">
        <article class="metric-card">
          <div class="field-label">当前选择</div>
          <div class="metric-value small">{{ selectionTitle }}</div>
        </article>
        <article class="metric-card">
          <div class="field-label">文件数</div>
          <div class="metric-value">{{ selectedFiles.length }}</div>
        </article>
        <article class="metric-card">
          <div class="field-label">总大小</div>
          <div class="metric-value">{{ formatFileSize(selectedTotalBytes) }}</div>
        </article>
      </div>

      <div v-if="uploading || uploadProgress > 0" class="progress-block">
        <div class="progress-head">
          <span>上传进度</span>
          <span>{{ uploadProgress }}%</span>
        </div>
        <el-progress :percentage="uploadProgress" :stroke-width="14" />
      </div>
    </article>

    <section class="summary-grid">
      <article class="glass-panel summary-card">
        <div class="field-label">我的成功数据集</div>
        <div class="metric-value">{{ datasets.length }}</div>
      </article>
      <article class="glass-panel summary-card">
        <div class="field-label">总数据条数</div>
        <div class="metric-value">{{ totalFrames }}</div>
      </article>
      <article class="glass-panel summary-card">
        <div class="field-label">总 Episode 数</div>
        <div class="metric-value">{{ totalEpisodes }}</div>
      </article>
    </section>

    <article class="glass-panel table-panel">
      <div class="toolbar-row">
        <div>
          <h2 class="section-title">我的数据集</h2>
          <div class="section-subtitle">支持查看详情、修改数据集名称以及物理删除。</div>
        </div>
        <el-button @click="loadDatasets">刷新列表</el-button>
      </div>

      <el-table :data="datasets" style="margin-top: 18px">
        <el-table-column prop="datasetName" label="数据集名称" min-width="180" />
        <el-table-column prop="storagePath" label="保存路径" min-width="260" />
        <el-table-column prop="totalFrames" label="数据条数" min-width="110" />
        <el-table-column prop="totalEpisodes" label="Episodes" min-width="100" />
        <el-table-column prop="robotType" label="机器人类型" min-width="140" />
        <el-table-column prop="createdTime" label="上传时间" min-width="180" />
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="scope">
            <el-button link type="primary" @click="openDetail(scope.row)">详情</el-button>
            <el-button link type="primary" @click="openRename(scope.row)">改名</el-button>
            <el-button link type="danger" @click="removeDataset(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </article>

    <el-dialog v-model="renameVisible" title="修改数据集名称" width="420px">
      <el-form :model="renameForm" label-position="top">
        <el-form-item label="新名称">
          <el-input v-model="renameForm.datasetName" placeholder="请输入新的数据集名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameVisible = false">取消</el-button>
        <el-button type="primary" @click="submitRename">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="detailVisible" title="数据集详情" width="900px">
      <template v-if="currentDataset">
        <el-descriptions :column="2" border>
          <el-descriptions-item label="数据集名称">{{ currentDataset.datasetName }}</el-descriptions-item>
          <el-descriptions-item label="保存路径">{{ currentDataset.storagePath }}</el-descriptions-item>
          <el-descriptions-item label="数据条数">{{ currentDataset.totalFrames }}</el-descriptions-item>
          <el-descriptions-item label="Episode 数">{{ currentDataset.totalEpisodes }}</el-descriptions-item>
          <el-descriptions-item label="任务数">{{ currentDataset.totalTasks }}</el-descriptions-item>
          <el-descriptions-item label="机器人类型">{{ currentDataset.robotType || "-" }}</el-descriptions-item>
          <el-descriptions-item label="代码版本">{{ currentDataset.codebaseVersion || "-" }}</el-descriptions-item>
          <el-descriptions-item label="FPS">{{ currentDataset.fps || "-" }}</el-descriptions-item>
          <el-descriptions-item label="特征数">{{ currentDataset.featureCount || 0 }}</el-descriptions-item>
          <el-descriptions-item label="相机数">{{ currentDataset.cameraCount || 0 }}</el-descriptions-item>
          <el-descriptions-item label="数据MB">{{ currentDataset.dataFilesSizeMb || "-" }}</el-descriptions-item>
          <el-descriptions-item label="视频MB">{{ currentDataset.videoFilesSizeMb || "-" }}</el-descriptions-item>
        </el-descriptions>

        <div class="detail-block">
          <div class="field-label">相机通道</div>
          <div class="tag-group">
            <el-tag v-for="item in splitCsv(currentDataset.cameraKeys)" :key="item">{{ item }}</el-tag>
            <span v-if="splitCsv(currentDataset.cameraKeys).length === 0">-</span>
          </div>
        </div>

        <div class="detail-block">
          <div class="field-label">特征键</div>
          <div class="tag-group">
            <el-tag v-for="item in splitCsv(currentDataset.featureKeys)" :key="item" type="info">{{ item }}</el-tag>
          </div>
        </div>

        <div class="detail-block">
          <div class="field-label">原始元数据</div>
          <pre class="metadata-box">{{ formatMetadata(currentDataset.metadataJson) }}</pre>
        </div>
      </template>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, reactive, ref } from "vue"
import { ElMessage, ElMessageBox } from "element-plus"
import { deleteDatasetApi, fetchMyDatasetsApi, renameDatasetApi, uploadDatasetApi } from "../../api/dataset"

const uploadMode = ref("archive")
const datasetName = ref("")
const selectedFiles = ref([])
const selectedRelativePaths = ref([])
const selectionTitle = ref("未选择")
const uploadProgress = ref(0)
const uploading = ref(false)
const datasets = ref([])
const detailVisible = ref(false)
const renameVisible = ref(false)
const currentDataset = ref(null)
const renamingDatasetId = ref("")
const archiveInputRef = ref()
const folderInputRef = ref()
const renameForm = reactive({
  datasetName: ""
})

const hasSelection = computed(() => selectedFiles.value.length > 0)
const selectedTotalBytes = computed(() => selectedFiles.value.reduce((sum, file) => sum + (file.size || 0), 0))
const totalFrames = computed(() => datasets.value.reduce((sum, item) => sum + Number(item.totalFrames || 0), 0))
const totalEpisodes = computed(() => datasets.value.reduce((sum, item) => sum + Number(item.totalEpisodes || 0), 0))
const uploadHint = computed(() => uploadMode.value === "archive"
  ? "压缩包模式适合 Linux 和 Windows 用户，支持 tar.gz、tgz、zip。"
  : "文件夹模式会保留目录结构，用于直接还原完整数据集目录。")

async function loadDatasets() {
  datasets.value = await fetchMyDatasetsApi()
}

function triggerSelect() {
  if (uploadMode.value === "archive") {
    archiveInputRef.value?.click()
    return
  }
  folderInputRef.value?.click()
}

function handleArchiveChange(event) {
  const files = Array.from(event.target.files || [])
  selectedFiles.value = files
  selectedRelativePaths.value = []
  selectionTitle.value = files[0] ? files[0].name : "未选择"
}

function handleFolderChange(event) {
  const files = Array.from(event.target.files || [])
  selectedFiles.value = files
  selectedRelativePaths.value = files.map((file) => file.webkitRelativePath || file.name)
  if (files[0]?.webkitRelativePath) {
    selectionTitle.value = files[0].webkitRelativePath.split("/")[0]
    return
  }
  selectionTitle.value = files[0] ? files[0].name : "未选择"
}

function resetSelection() {
  selectedFiles.value = []
  selectedRelativePaths.value = []
  selectionTitle.value = "未选择"
  uploadProgress.value = 0
  if (archiveInputRef.value) {
    archiveInputRef.value.value = ""
  }
  if (folderInputRef.value) {
    folderInputRef.value.value = ""
  }
}

async function submitUpload() {
  if (!hasSelection.value) {
    ElMessage.warning("请先选择要上传的数据集")
    return
  }

  uploading.value = true
  uploadProgress.value = 0
  try {
    await uploadDatasetApi({
      datasetName: datasetName.value,
      files: selectedFiles.value,
      relativePaths: selectedRelativePaths.value,
      onUploadProgress: (event) => {
        if (!event.total) {
          return
        }
        uploadProgress.value = Math.min(100, Math.round(event.loaded * 100 / event.total))
      }
    })
    ElMessage.success("数据集上传成功")
    resetSelection()
    datasetName.value = ""
    await loadDatasets()
  } finally {
    uploading.value = false
  }
}

function openDetail(row) {
  currentDataset.value = row
  detailVisible.value = true
}

function openRename(row) {
  renamingDatasetId.value = row.id
  renameForm.datasetName = row.datasetName
  renameVisible.value = true
}

async function submitRename() {
  await renameDatasetApi(renamingDatasetId.value, { datasetName: renameForm.datasetName })
  ElMessage.success("数据集名称修改成功")
  renameVisible.value = false
  await loadDatasets()
}

async function removeDataset(row) {
  await ElMessageBox.confirm(`确认删除数据集 ${row.datasetName} 吗？该操作会同时删除物理目录。`, "提示", { type: "warning" })
  await deleteDatasetApi(row.id)
  ElMessage.success("数据集删除成功")
  await loadDatasets()
}

function splitCsv(value) {
  if (!value) {
    return []
  }
  return value.split(",").map((item) => item.trim()).filter(Boolean)
}

function formatMetadata(metadataJson) {
  if (!metadataJson) {
    return "-"
  }
  try {
    return JSON.stringify(JSON.parse(metadataJson), null, 2)
  } catch {
    return metadataJson
  }
}

function formatFileSize(bytes) {
  if (!bytes) {
    return "0 B"
  }
  if (bytes < 1024) {
    return `${bytes} B`
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(2)} KB`
  }
  if (bytes < 1024 * 1024 * 1024) {
    return `${(bytes / 1024 / 1024).toFixed(2)} MB`
  }
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

loadDatasets()
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 20px;
}

.upload-panel,
.table-panel,
.summary-card {
  padding: 24px;
  border-radius: 28px;
}

.toolbar-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.upload-grid,
.metric-grid,
.summary-grid {
  display: grid;
  gap: 16px;
}

.upload-grid {
  grid-template-columns: 260px 1fr;
  margin-top: 20px;
}

.metric-grid,
.summary-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.selector-panel,
.metric-card {
  border: 1px solid rgba(47, 107, 255, 0.12);
  background: rgba(255, 255, 255, 0.55);
  border-radius: 22px;
}

.selector-panel {
  margin-top: 18px;
  padding: 20px;
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: center;
}

.metric-card {
  padding: 18px;
}

.selector-actions,
.tag-group {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}

.selector-title,
.metric-value {
  font-weight: 700;
}

.selector-title {
  font-size: 18px;
  margin-bottom: 8px;
}

.field-label {
  color: var(--text-sub);
  margin-bottom: 10px;
}

.metric-grid,
.summary-grid,
.progress-block,
.detail-block {
  margin-top: 18px;
}

.metric-value {
  font-size: 24px;
}

.metric-value.small {
  font-size: 18px;
  word-break: break-all;
}

.progress-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 10px;
}

.metadata-box {
  margin: 0;
  padding: 16px;
  border-radius: 18px;
  background: rgba(12, 24, 46, 0.06);
  max-height: 320px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

@media (max-width: 960px) {
  .upload-grid,
  .metric-grid,
  .summary-grid {
    grid-template-columns: 1fr;
  }

  .selector-panel {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
