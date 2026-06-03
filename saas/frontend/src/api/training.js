import request from "../utils/request"

export function fetchMyTrainingTasksApi() {
  return request.get("/training-tasks/mine")
}

export function createTrainingTaskApi(data) {
  return request.post("/training-tasks", data, { timeout: 0 })
}

export function fetchTrainingTaskLogApi(taskId) {
  return request.get(`/training-tasks/${taskId}/log`, { timeout: 0 })
}

export function stopTrainingTaskApi(taskId) {
  return request.put(`/training-tasks/${taskId}/stop`)
}

export function downloadTrainingTaskModelApi(taskId) {
  return request.get(`/training-tasks/${taskId}/download`, {
    responseType: "blob",
    timeout: 0
  })
}

export function fetchSavedModelsApi() {
  return request.get("/training-tasks/saved-models", { timeout: 0 })
}

export function downloadSavedModelApi(name) {
  return request.get("/training-tasks/saved-models/download", {
    params: { name },
    responseType: "blob",
    timeout: 0
  })
}
