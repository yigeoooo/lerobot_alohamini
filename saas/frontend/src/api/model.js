import request from '../utils/request'

export function fetchPolicyDirectoriesApi() {
  return request.get('/models/policies')
}

export function fetchModelsApi() {
  return request.get('/models')
}

export function createModelApi(data) {
  return request.post('/models', data)
}

export function updateModelApi(modelId, data) {
  return request.put(`/models/${modelId}`, data)
}

export function deleteModelApi(modelId) {
  return request.delete(`/models/${modelId}`)
}
