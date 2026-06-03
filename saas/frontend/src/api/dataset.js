import request from "../utils/request"

export function fetchMyDatasetsApi() {
  return request.get("/datasets/mine")
}

export function uploadDatasetApi({ datasetName, files, relativePaths = [], onUploadProgress }) {
  const formData = new FormData()
  if (datasetName) {
    formData.append("datasetName", datasetName)
  }
  files.forEach((file) => {
    formData.append("files", file)
  })
  relativePaths.forEach((relativePath) => {
    formData.append("relativePaths", relativePath)
  })
  return request.post("/datasets/upload", formData, {
    headers: {
      "Content-Type": "multipart/form-data"
    },
    timeout: 0,
    onUploadProgress
  })
}

export function renameDatasetApi(datasetId, data) {
  return request.put(`/datasets/${datasetId}/name`, data)
}

export function deleteDatasetApi(datasetId) {
  return request.delete(`/datasets/${datasetId}`)
}
