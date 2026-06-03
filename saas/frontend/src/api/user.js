import request from '../utils/request'

export function fetchCurrentUserApi() {
  return request.get('/users/me')
}

export function updateCurrentUserProfileApi(data) {
  return request.put('/users/me/profile', data)
}

export function updateCurrentUserPasswordApi(data) {
  return request.put('/users/me/password', data)
}

export function fetchUsersApi(params) {
  return request.get('/users', { params })
}

export function createUserApi(data) {
  return request.post('/users', data)
}

export function updateUserApi(userId, data) {
  return request.put(`/users/${userId}`, data)
}

export function deleteUserApi(userId) {
  return request.delete(`/users/${userId}`)
}

export function resetUserPasswordApi(userId, data) {
  return request.put(`/users/${userId}/reset-password`, data)
}
