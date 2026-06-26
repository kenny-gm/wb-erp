import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'

// 设置基础URL为空，使用相对路径（通过nginx代理）
axios.defaults.baseURL = ''

export const useAuthStore = defineStore('auth', () => {
  const token = ref(localStorage.getItem('token') || '')
  const user = ref(JSON.parse(localStorage.getItem('user') || 'null'))

  const isLoggedIn = computed(() => !!token.value)
  const isAdmin = computed(() => user.value?.role === 'admin')
  
  // 从API获取菜单列表，失败时使用默认菜单
  const availableMenus = ref([
    { key: 'dashboard', name: '销售看板', path: '/dashboard' },
    { key: 'ads', name: '广告分析', path: '/ads' },
    { key: 'operation-logs', name: '运营日志', path: '/operation-logs' },
    { key: 'customer-service', name: '客服工作台', path: '/customer-service' },
    { key: 'admin', name: '系统管理', path: '/admin' }
  ])
  
  async function fetchMenus() {
    try {
      const response = await axios.get('/api/admin/menus/')
      if (response.data && response.data.length > 0) {
        availableMenus.value = response.data.map(m => ({
          key: m.key,
          name: m.name,
          path: m.path
        }))
      }
    } catch (e) {
      console.warn('获取菜单列表失败，使用默认菜单')
    }
  }
  
  // 检查用户是否有权限访问某个菜单
  const canAccess = (menuKey) => {
    if (!user.value) return false
    // 管理员可以访问所有菜单
    if (user.value.role === 'admin') return true
    // 如果没有设置 allowed_menus，则可以访问所有菜单
    const allowedMenus = user.value.allowed_menus || []
    if (allowedMenus.length === 0) return true
    // 检查是否在允许的菜单列表中
    return allowedMenus.includes(menuKey)
  }

  // 设置 axios 默认 header
  if (token.value) {
    axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
  }

  async function login(username, password) {
    const formData = new FormData()
    formData.append('username', username)
    formData.append('password', password)

    const response = await axios.post('/api/auth/login/', formData)
    const data = response.data

    token.value = data.access_token
    localStorage.setItem('token', data.access_token)
    axios.defaults.headers.common['Authorization'] = `Bearer ${data.access_token}`

    // 获取用户信息
    await fetchUser()
  }

  async function fetchUser() {
    const response = await axios.get('/api/auth/me/')
    user.value = response.data
    localStorage.setItem('user', JSON.stringify(response.data))
  }

  function logout() {
    token.value = ''
    user.value = null
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    delete axios.defaults.headers.common['Authorization']
  }

  return {
    token,
    user,
    isLoggedIn,
    isAdmin,
    canAccess,
    availableMenus,
    fetchMenus,
    login,
    logout,
    fetchUser
  }
})
