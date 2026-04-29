<template>
  <div class="login-container minimal-white" :style="{ background: gradientStyle }">
    <div class="login-card">
      <div class="login-header">
        <img v-if="isLoginLogoImage" :src="uiSettings.login_logo" class="logo-img" alt="logo" />
        <div v-else class="logo">{{ uiSettings.login_logo }}</div>
        <h1>{{ uiSettings.login_title }}</h1>
        <p>{{ uiSettings.login_subtitle }}</p>
      </div>
      
      <el-form :model="form" :rules="rules" ref="formRef" @submit.prevent="handleLogin">
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            placeholder="用户名"
            :prefix-icon="User"
            size="large"
          />
        </el-form-item>
        
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            placeholder="密码"
            :prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            @click="handleLogin"
            class="login-btn"
          >
            {{ loading ? '登录中...' : '登录' }}
          </el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import axios from 'axios'

const router = useRouter()
const authStore = useAuthStore()

const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  username: '',
  password: ''
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

// UI设置
const uiSettings = ref({
  system_name: 'WB ERP',
  login_logo: '',
  login_title: 'TINTO GROUP',
  login_subtitle: 'Wildberries 跨境电商管理系统',
  primary_color: '#8b5cf6'
})

// 启动时先读取缓存，避免闪烁
;(function() {
  const cached = localStorage.getItem('ui_settings_cache')
  if (cached) {
    try { Object.assign(uiSettings.value, JSON.parse(cached)) } catch(e) {}
  }
})()

// 判断 login_logo 是否为图片（URL / data:image / 相对路径）
const isLoginLogoImage = computed(() => {
  const val = uiSettings.value.login_logo || ''
  return val.startsWith('http://') || val.startsWith('https://') ||
         val.startsWith('/') || val.startsWith('data:image/')
})

// 计算渐变背景
const gradientStyle = computed(() => {
  const color = uiSettings.value.primary_color || '#8b5cf6'
  return `linear-gradient(135deg, ${color} 0%, ${lightenColor(color, 20)} 100%)`
})

function lightenColor(color, percent) {
  const num = parseInt(color.replace('#', ''), 16)
  const amt = Math.round(2.55 * percent)
  const R = (num >> 16) + amt
  const G = (num >> 8 & 0x00FF) + amt
  const B = (num & 0x0000FF) + amt
  return '#' + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 + (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 + (B < 255 ? B < 1 ? 0 : B : 255)).toString(16).slice(1)
}

// 获取UI设置
async function fetchUISettings() {
  try {
    const response = await axios.get('/api/admin/ui-settings/')
    if (response.data) {
      Object.assign(uiSettings.value, response.data)
      localStorage.setItem('ui_settings_cache', JSON.stringify(response.data))
      // 更新浏览器标题
      if (response.data.system_name) {
        document.title = response.data.system_name
      }
    }
  } catch (error) {
    // 使用默认值
  }
}

async function handleLogin() {
  if (!formRef.value) return
  
  await formRef.value.validate(async (valid) => {
    if (!valid) return
    
    loading.value = true
    try {
      await authStore.login(form.username, form.password)
      ElMessage.success('登录成功')
      router.push('/dashboard')
    } catch (error) {
      ElMessage.error(error.response?.data?.detail || '登录失败')
    } finally {
      loading.value = false
    }
  })
}

onMounted(() => {
  fetchUISettings()
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



.login-container {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.login-card {
  width: 100%;
  max-width: 380px;
  background: white;
  border-radius: 12px;
  padding: 32px;
  box-shadow: 0 20px 60px rgba(0, 0, 0, 0.15);
}

.login-header {
  text-align: center;
  margin-bottom: 28px;
}

.logo {
  font-size: 48px;
  margin-bottom: 12px;
}
.logo-img {
  height: 64px;
  max-width: 200px;
  object-fit: contain;
  margin-bottom: 12px;
}

.login-header h1 {
  font-size: 24px;
  font-weight: 600;
  color: #1f2937;
  margin: 0 0 8px 0;
}

.login-header p {
  font-size: 14px;
  color: #6b7280;
  margin: 0;
}

.login-btn {
  width: 100%;
  height: 44px;
  font-size: 16px;
}

:deep(.el-input__prefix) {
  font-size: 16px;
}

:deep(.el-input__inner) {
  font-size: 15px;
}

/* 移动端适配 */
@media (max-width: 480px) {
  .login-card {
    padding: 24px 20px;
  }
  
  .logo {
    font-size: 40px;
  }
  
  .login-header h1 {
    font-size: 20px;
  }
  
  .login-header p {
    font-size: 12px;
  }
}
</style>
