import request from '../utils/request'

export function fetchRoutePermissionsApi() {
  return request.get('/route-permissions')
}

export function createRoutePermissionApi(data) {
  return request.post('/route-permissions', data)
}

export function fetchOrganizationRouteIdsApi(organizationId) {
  return request.get(`/route-permissions/organizations/${organizationId}`)
}

export function assignOrganizationRoutesApi(organizationId, data) {
  return request.post(`/route-permissions/organizations/${organizationId}`, data)
}
