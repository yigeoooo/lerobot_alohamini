import request from '../utils/request'

export function loginApi(data) {
  return request.post('/auth/login', data)
}

export function profileApi() {
  return request.get('/auth/profile')
}
