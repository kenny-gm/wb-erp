<template>
  <el-container class="layout-container">
    <!-- 移动端遮罩层 -->
    <div v-if="sidebarVisible && isMobile" class="sidebar-overlay" @click="closeSidebar"></div>

    <!-- 侧边栏 -->
    <el-aside :class="['sidebar', { 'sidebar-visible': sidebarVisible, 'sidebar-mobile': isMobile }]">
      <div class="logo">
        <span class="logo-text">{{ uiSettings.sidebar_logo || '🍀 WB ERP' }}</span>
      </div>

      <el-menu
        :default-active="activeMenu"
        :collapse="isCollapsed && !isMobile"
        background-color="#7B2D8E"
        text-color="#ffffff"
        :active-text-color="'#ffffff'"
        :collapse-transition="false"
        @select="handleMenuSelect"
        @contextmenu.native.prevent="handleContextMenu"
      >
        <el-menu-item v-if="authStore.canAccess('dashboard')" index="/dashboard">
          <el-icon><DataLine /></el-icon>
          <span>销售看板</span>
        </el-menu-item>
        
        <el-menu-item v-if="authStore.canAccess('ads')" index="/ads">
          <el-icon><TrendCharts /></el-icon>
          <span>广告分析</span>
        </el-menu-item>
        
        <el-menu-item v-if="authStore.canAccess('operation-logs')" index="/operation-logs">
          <el-icon><Document /></el-icon>
          <span>运营日志</span>
        </el-menu-item>

        <el-menu-item v-if="authStore.canAccess('customer-service')" index="/customer-service">
          <el-icon><ChatDotRound /></el-icon>
          <span>客服工作台</span>
        </el-menu-item>
        
        <el-menu-item v-if="authStore.isAdmin" index="/admin">
          <el-icon><Setting /></el-icon>
          <span>系统管理</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-left">
          <!-- 移动端菜单按钮 -->
          <el-icon v-if="isMobile" class="menu-toggle" @click="toggleSidebar">
            <Menu />
          </el-icon>
          <span class="page-title">{{ pageTitle }}</span>
        </div>

        <div class="header-right">
          <el-dropdown @command="handleCommand">
            <span class="user-info">
              <el-icon><User /></el-icon>
              <span class="username">{{ authStore.user?.username }}</span>
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="logout">退出登录</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { DataLine, TrendCharts, Document, Setting, User, Menu, ChatDotRound } from '@element-plus/icons-vue'
import axios from 'axios'

const router = useRouter()
const route = useRoute()
const authStore = useAuthStore()
const sidebarVisible = ref(false)
const isCollapsed = ref(false)
const isMobile = ref(false)
const uiSettings = ref({})

const pageTitle = computed(() => route.meta?.title || 'WB ERP')
const activeMenu = computed(() => route.path)

// 获取菜单列表
authStore.fetchMenus()

// 检测移动端
function checkMobile() {
  isMobile.value = window.innerWidth < 768
  if (!isMobile.value) {
    sidebarVisible.value = false
  }
}

// 切换侧边栏(移动端)
function toggleSidebar() {
  sidebarVisible.value = !sidebarVisible.value
}

// 关闭侧边栏
function closeSidebar() {
  sidebarVisible.value = false
}

const handleMenuSelect = (index) => {
  // 导航到对应页面
  router.push(index)
  // 移动端选择菜单后关闭侧边栏
  if (isMobile.value) {
    sidebarVisible.value = false
  }
}

// 右键菜单 - 在新标签页打开
function handleContextMenu(event) {
  const target = event.target.closest('.el-menu-item')
  if (!target) return
  const path = target.getAttribute('index')
  if (path) {
    window.open(path, '_blank')
  }
}

const handleCommand = async (command) => {
  if (command === 'logout') {
    authStore.logout()
    router.push('/login')
  }
}

onMounted(async () => {
  // 检测移动端
  checkMobile()
  window.addEventListener('resize', checkMobile)

  // 先从 localStorage 读取缓存，避免侧边栏 logo 闪烁
  const cached = localStorage.getItem('ui_settings_cache')
  if (cached) {
    try {
      const cachedSettings = JSON.parse(cached)
      uiSettings.value = cachedSettings
      if (cachedSettings.system_name) document.title = cachedSettings.system_name
    } catch (e) {}
  }

  try {
    const res = await axios.get('/api/admin/ui-settings/')
    if (res.data) {
      uiSettings.value = res.data
      localStorage.setItem('ui_settings_cache', JSON.stringify(res.data))
      document.title = res.data.system_name || 'WB ERP'
      if (res.data.browser_logo) {
        let link = document.querySelector("link[rel='icon']")
        if (!link) {
          link = document.createElement('link')
          link.rel = 'icon'
          document.head.appendChild(link)
        }
        link.href = res.data.browser_logo
      }
    }
  } catch (e) {}

  // 获取未读预警数量
  })

onUnmounted(() => {
  window.removeEventListener('resize', checkMobile)
})
</script>

<style scoped>
/* 极简纯白全局样式 */
.minimal-white {
  padding: 16px;
  min-height: 100vh;
  background: #f8fafc;
  color: #0f172a;
}

/* 白色卡片 */
.el-card, .card, .metric-card, .chart-card, .table-card {
  background: white !important;
  border: 1px solid #e2e8f0 !important;
  border-radius: 12px !important;
  box-shadow: 0 1px 3px rgba(0,0,0,0.04) !important;
}

/* 按钮 - 深色主题 */
.el-button--primary {
  background: #0f172a !important;
  border-color: #0f172a !important;
}
.el-button--primary:hover {
  background: #334155 !important;
}

/* 筛选栏 */
.filter-bar, .filter-section {
  background: white;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
}

/* 表格 */
.el-table {
  --el-table-bg-color: white;
  --el-table-tr-bg-color: white;
  --el-table-header-bg-color: #f8fafc;
  --el-table-row-hover-bg-color: #f8fafc;
  --el-table-border-color: #e2e8f0;
  --el-table-text-color: #334155;
  --el-table-header-text-color: #475569;
}

/* 对话框 */
.el-dialog {
  background: white !important;
  border-radius: 12px;
}
.el-dialog__title {
  color: #0f172a !important;
}

/* 输入框 */
.el-input__wrapper {
  background: white !important;
  border: 1px solid #e2e8f0 !important;
  box-shadow: none !important;
}

/* 文字颜色 */
h1, h2, h3, h4, h5, h6, p, span, div {
  color: #0f172a;
}

/* 次要文字 */
.text-muted, .subtitle, .desc, .label {
  color: #64748b !important;
}

/* 正面绿色 */
.positive, .up, .growth {
  color: #16a34a !important;
}

/* 负面红色 */
.negative, .down, .decline {
  color: #dc2626 !important;
}

/* 分页 */
.el-pagination {
  justify-content: flex-end;
}



.layout-container { height: 100vh; }

/* 遮罩层 */
.sidebar-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  z-index: 900;
}

/* 侧边栏 */
.sidebar {
  width: 180px !important;
  min-width: 180px !important;
  background: #FFFFFF !important;
  box-shadow: 1px 0 4px rgba(0,0,0,0.06);
  transition: all 0.3s ease;
  z-index: 1000;
}

/* 移动端侧边栏 */
.sidebar-mobile {
  position: fixed !important;
  left: 0;
  top: 0;
  bottom: 0;
  width: 200px !important;
  transform: translateX(-100%);
}

.sidebar-mobile.sidebar-visible {
  transform: translateX(0);
}

.sidebar :deep(.el-menu) {
  border-right: none;
  background: transparent !important;
}

.sidebar :deep(.el-menu-item),
.sidebar :deep(.el-sub-menu__title) {
  height: 40px;
  line-height: 40px;
  margin: 4px 12px;
  border-radius: 8px;
  color: #6b7280 !important;
  font-weight: 500;
  transition: all 0.2s ease;
}

.sidebar :deep(.el-menu-item:hover),
.sidebar :deep(.el-sub-menu__title:hover) {
  background: #f3f4f6 !important;
  color: #374151 !important;
}

.sidebar :deep(.el-menu-item.is-active),
.sidebar :deep(.el-sub-menu__title.is-active) {
  background: rgba(139, 92, 246, 0.1) !important;
  color: #8b5cf6 !important;
  font-weight: 600;
}

.logo {
  height: 56px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-bottom: 1px solid #f3f4f6;
}
.logo-text {
  font-size: 17px;
  font-weight: 700;
  color: #8b5cf6;
  letter-spacing: 1px;
}

.header {
  background: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.menu-toggle {
  font-size: 20px;
  cursor: pointer;
  padding: 10px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.2s;
  min-width: 44px;
  min-height: 44px;
}
.menu-toggle:hover { background: #f5f7fa; }
.menu-toggle:active { transform: scale(0.95); }

@media (max-width: 767px) {
  .menu-toggle {
    font-size: 24px;
    padding: 12px;
    min-width: 48px;
    min-height: 48px;
  }
}

@media (min-width: 768px) and (max-width: 1023px) {
  .menu-toggle {
    font-size: 18px;
    padding: 6px;
  }
}

@media (min-width: 1024px) {
  .menu-toggle {
    font-size: 16px;
    padding: 4px;
  }
}
.page-title { font-size: 16px; font-weight: 600; color: #303133; }

.header-right { display: flex; align-items: center; gap: 16px; }

.alert-badge {
  cursor: pointer;
}

.alert-icon {
  font-size: 20px;
  padding: 8px;
  border-radius: 6px;
  cursor: pointer;
  transition: background 0.2s;
}

.alert-icon:hover {
  background: #f5f7fa;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
  padding: 8px 12px;
  border-radius: 8px;
}
.user-info:hover { background: #f5f7fa; }
.username { font-size: 14px; color: #606266; }

.main-content { background: #f5f7fa; padding: 20px; }

/* 移动端适配 */
@media (max-width: 767px) {
  .main-content {
    padding: 12px;
  }

  .header {
    padding: 0 12px;
    height: 50px;
  }

  .page-title {
    font-size: 14px;
    max-width: 120px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .username {
    font-size: 12px;
    max-width: 80px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .sidebar {
    width: 200px !important;
    min-width: 200px !important;
  }

  .logo {
    height: 50px;
  }

  .logo-text {
    font-size: 15px;
  }

  .header-left {
    gap: 8px;
  }

  .header-right {
    gap: 8px;
  }

  .alert-icon {
    font-size: 18px;
    padding: 6px;
  }
}

/* 平板适配 */
@media (min-width: 768px) and (max-width: 1023px) {
  .main-content {
    padding: 16px;
  }

  .page-title {
    font-size: 15px;
  }
}

/* 桌面适配 */
@media (min-width: 1024px) {
  .header {
    padding: 0 24px;
  }
}
</style>
