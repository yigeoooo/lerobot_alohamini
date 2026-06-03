import request from '../utils/request'

export function fetchIconsApi() {
  return request.get('/icons')
}
