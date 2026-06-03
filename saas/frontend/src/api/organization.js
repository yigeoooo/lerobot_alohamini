import request from '../utils/request'

export function fetchOrganizationsApi(keyword = '') {
  return request.get('/organizations', { params: { keyword } })
}

export function createOrganizationApi(data) {
  return request.post('/organizations', data)
}

export function updateOrganizationApi(organizationId, data) {
  return request.put(`/organizations/${organizationId}`, data)
}

export function deleteOrganizationApi(organizationId) {
  return request.delete(`/organizations/${organizationId}`)
}
