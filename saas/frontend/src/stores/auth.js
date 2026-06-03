import { defineStore } from 'pinia'
import { loginApi, profileApi } from '../api/auth'

const TOKEN_KEY = 'LEROBOT_SAAS_TOKEN'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: null,
    routePermissions: [],
    initialized: false
  }),
  getters: {
    displayName: (state) => state.user?.name || '未登录',
    defaultRoute: (state) => state.routePermissions[0]?.routePath || '/'
  },
  actions: {
    async login(payload) {
      const result = await loginApi(payload)
      this.applySession(result)
      return result
    },
    async fetchProfile() {
      const result = await profileApi()
      this.applySession({ ...result, token: this.token })
      return result
    },
    applySession(result) {
      this.token = result.token || this.token
      this.user = result.user
      this.routePermissions = result.routePermissions || []
      this.initialized = true
      localStorage.setItem(TOKEN_KEY, this.token)
    },
    reset() {
      this.token = ''
      this.user = null
      this.routePermissions = []
      this.initialized = false
      localStorage.removeItem(TOKEN_KEY)
    },
    canAccess(routePath) {
      return this.routePermissions.some((item) => item.routePath === routePath)
    }
  }
})
