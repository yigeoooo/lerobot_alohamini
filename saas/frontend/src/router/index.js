import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const MainLayout = () => import('../layout/MainLayout.vue')
const MissingPageView = () => import('../views/common/MissingPageView.vue')
const viewModules = import.meta.glob('../views/**/*.vue')
const dynamicRouteKeys = new Set()

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/login',
      name: 'login',
      component: () => import('../views/login/LoginView.vue'),
      meta: { public: true }
    },
    {
      path: '/',
      name: 'layout',
      component: MainLayout,
      children: []
    }
  ]
})

function resolveViewComponent(componentPath) {
  const moduleKey = `../${componentPath}.vue`
  return viewModules[moduleKey] || MissingPageView
}

function resolveChildPath(routePath) {
  if (routePath === '/') {
    return ''
  }
  return routePath.startsWith('/') ? routePath.slice(1) : routePath
}

export function registerDynamicRoutes(routePermissions = []) {
  routePermissions.forEach((permission) => {
    if (dynamicRouteKeys.has(permission.routePath)) {
      return
    }
    router.addRoute('layout', {
      path: resolveChildPath(permission.routePath),
      name: `route-${permission.id}`,
      component: resolveViewComponent(permission.componentPath),
      meta: {
        title: permission.title,
        icon: permission.icon,
        permissionPath: permission.routePath,
        componentPath: permission.componentPath
      },
      props: {
        permission: permission
      }
    })
    dynamicRouteKeys.add(permission.routePath)
  })
}

async function ensureAuthRoutes() {
  const authStore = useAuthStore()
  if (!authStore.token) {
    return authStore
  }
  if (!authStore.initialized) {
    const profile = await authStore.fetchProfile()
    registerDynamicRoutes(profile.routePermissions)
  }
  return authStore
}

router.beforeEach(async (to) => {
  const authStore = useAuthStore()

  if (to.meta.public) {
    if (to.path === '/login' && authStore.token) {
      const store = await ensureAuthRoutes()
      return store.defaultRoute
    }
    return true
  }

  if (!authStore.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  const store = await ensureAuthRoutes()

  if (to.matched.length === 0) {
    if (store.canAccess(to.path)) {
      return { path: to.fullPath, replace: true }
    }
    return store.defaultRoute
  }

  if (to.meta.permissionPath && !store.canAccess(to.meta.permissionPath)) {
    return store.defaultRoute
  }

  if (to.path === '/' && store.defaultRoute !== '/') {
    return store.defaultRoute
  }

  return true
})

export default router
