<template>
  <div class="ui-settings-page">
    <el-form :model="uiForm" label-width="120px">
      <el-divider>浏览器设置</el-divider>
      
      <el-form-item label="浏览器标题">
        <el-input v-model="uiForm.system_name" placeholder="WB ERP" />
        <div class="form-tip">显示在浏览器标签页的名称</div>
      </el-form-item>
      
      <el-form-item label="浏览器Logo">
        <div class="upload-area">
          <el-input v-model="uiForm.browser_logo" placeholder="输入图片URL或上传图片">
            <template #append>
              <el-upload
                :show-file-list="false"
                :before-upload="beforeBrowserLogoUpload"
                accept="image/*"
              >
                <el-button :icon="Upload">上传</el-button>
              </el-upload>
            </template>
          </el-input>
          <div class="preview-row" v-if="uiForm.browser_logo">
            <span>预览：</span>
            <img :src="uiForm.browser_logo" class="favicon-preview" />
          </div>
        </div>
        <div class="form-tip">推荐尺寸：32x32 或 64x64 像素，支持 PNG/ICO 格式</div>
      </el-form-item>
      
      <el-divider>登录界面设置</el-divider>
      
      <el-form-item label="登录Logo">
        <div class="upload-area">
          <el-input v-model="uiForm.login_logo" placeholder="输入emoji或图片URL">
            <template #append>
              <el-upload
                :show-file-list="false"
                :before-upload="beforeLoginLogoUpload"
                accept="image/*"
              >
                <el-button :icon="Upload">上传</el-button>
              </el-upload>
            </template>
          </el-input>
          <div class="preview-row">
            <span>预览：</span>
            <span v-if="!isImageUrl(uiForm.login_logo)" class="emoji-preview">{{ uiForm.login_logo }}</span>
            <img v-else :src="uiForm.login_logo" class="logo-preview" />
          </div>
        </div>
        <div class="form-tip">可以是emoji表情（如 🌿、🍀），或上传图片</div>
      </el-form-item>
      
      <el-form-item label="登录主标题">
        <el-input v-model="uiForm.login_title" placeholder="WB ERP" />
      </el-form-item>
      
      <el-form-item label="登录副标题">
        <el-input v-model="uiForm.login_subtitle" placeholder="Wildberries 跨境电商管理系统" />
      </el-form-item>
      
      <el-divider>侧边栏设置</el-divider>
      
      <el-form-item label="侧边栏Logo">
        <el-input v-model="uiForm.sidebar_logo" placeholder="🍀 WB ERP">
          <template #append>
            <span class="preview">{{ uiForm.sidebar_logo }}</span>
          </template>
        </el-input>
      </el-form-item>
      
      <el-form-item label="主题色">
        <el-color-picker v-model="uiForm.primary_color" show-alpha />
        <span class="color-value">{{ uiForm.primary_color }}</span>
      </el-form-item>
      
      <el-divider>其他设置</el-divider>
      
      <el-form-item label="页脚文字">
        <el-input v-model="uiForm.footer_text" placeholder="留空则不显示" type="textarea" :rows="2" />
      </el-form-item>
      
      <el-form-item>
        <el-button type="primary" @click="saveSettings" :loading="saving">保存设置</el-button>
        <el-button @click="resetToDefault">恢复默认</el-button>
      </el-form-item>
    </el-form>
    
    <!-- 预览 -->
    <el-divider>登录页预览</el-divider>
    <div class="preview-box">
      <div class="login-preview" :style="{ background: `linear-gradient(135deg, ${uiForm.primary_color} 0%, ${lightenColor(uiForm.primary_color, 20)} 100%)` }">
        <div class="login-card">
          <div class="login-header">
            <div class="logo">
              <span v-if="!isImageUrl(uiForm.login_logo)">{{ uiForm.login_logo }}</span>
              <img v-else :src="uiForm.login_logo" class="logo-img" />
            </div>
            <h1>{{ uiForm.login_title }}</h1>
            <p>{{ uiForm.login_subtitle }}</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Upload } from '@element-plus/icons-vue'
import axios from 'axios'

const saving = ref(false)
const uiForm = ref({
  system_name: 'WB ERP',
  login_logo: '🌿',
  login_title: 'WB ERP',
  login_subtitle: 'Wildberries 跨境电商管理系统',
  sidebar_logo: '🍀 WB ERP',
  primary_color: '#7B2D8E',
  browser_logo: '',
  footer_text: ''
})

const defaultSettings = {
  system_name: 'WB ERP',
  login_logo: '🌿',
  login_title: 'WB ERP',
  login_subtitle: 'Wildberries 跨境电商管理系统',
  sidebar_logo: '🍀 WB ERP',
  primary_color: '#7B2D8E',
  browser_logo: '',
  footer_text: ''
}

function isImageUrl(str) {
  if (!str) return false
  return str.startsWith('http') || str.startsWith('data:image') || str.startsWith('/')
}

function lightenColor(color, percent) {
  const num = parseInt(color.replace('#', ''), 16)
  const amt = Math.round(2.55 * percent)
  const R = (num >> 16) + amt
  const G = (num >> 8 & 0x00FF) + amt
  const B = (num & 0x0000FF) + amt
  return '#' + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 + (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 + (B < 255 ? B < 1 ? 0 : B : 255)).toString(16).slice(1)
}

async function fetchSettings() {
  try {
    const response = await axios.get('/api/admin/ui-settings/')
    if (response.data) {
      Object.assign(uiForm.value, response.data)
    }
  } catch (error) {
    console.error('获取设置失败', error)
  }
}

async function saveSettings() {
  saving.value = true
  try {
    await axios.put('/api/admin/ui-settings/', uiForm.value)
    ElMessage.success('设置已保存')
    // 保存后重新加载最新数据
    await fetchSettings()
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

function resetToDefault() {
  Object.assign(uiForm.value, defaultSettings)
  ElMessage.info('已恢复默认值，请保存生效')
}

// 图片上传处理
function beforeBrowserLogoUpload(file) {
  if (file.size > 500 * 1024) {
    ElMessage.warning('图片大小不能超过500KB')
    return false
  }
  uploadLogoFile(file, 'browser')
  return false
}

function beforeLoginLogoUpload(file) {
  if (file.size > 2 * 1024 * 1024) {
    ElMessage.warning('图片大小不能超过2MB')
    return false
  }
  uploadLogoFile(file, 'login')
  return false
}

async function uploadLogoFile(file, logoType) {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('logo_type', logoType)
  try {
    const res = await axios.post('/api/admin/upload-logo/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    const url = res.data.url
    if (logoType === 'browser') {
      uiForm.value.browser_logo = url
    } else {
      uiForm.value.login_logo = url
    }
    ElMessage.success('上传成功')
  } catch (e) {
    ElMessage.error('上传失败')
  }
}

onMounted(() => {
  fetchSettings()
})
</script>

<style scoped>
.ui-settings-page {
  max-width: 600px;
}

.upload-area {
  width: 100%;
}

.preview-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 10px;
}

.favicon-preview {
  width: 32px;
  height: 32px;
  object-fit: contain;
  border: 1px solid #ddd;
  border-radius: 4px;
}

.emoji-preview {
  font-size: 32px;
}

.logo-preview {
  width: 48px;
  height: 48px;
  object-fit: contain;
}

.form-tip {
  font-size: 12px;
  color: #909399;
  margin-top: 5px;
}

.color-value {
  margin-left: 10px;
  color: #606266;
  font-family: monospace;
}

.preview-box {
  margin-top: 20px;
}

.login-preview {
  height: 300px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

.login-card {
  background: white;
  padding: 30px 40px;
  border-radius: 8px;
  text-align: center;
}

.login-header .logo {
  font-size: 48px;
  margin-bottom: 12px;
}

.login-header .logo-img {
  width: 64px;
  height: 64px;
  object-fit: contain;
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

@media (max-width: 768px) {
  .ui-settings {
    padding: 12px;
  }
  
  .el-form :deep(.el-form-item__label) {
    font-size: 13px;
  }
  
  .color-inputs {
    flex-direction: column;
    gap: 8px;
  }
  
  .login-preview {
    height: 200px;
  }
  
  .login-card {
    padding: 20px;
  }
  
  .login-header .logo {
    font-size: 36px;
  }
  
  .login-header h1 {
    font-size: 18px;
  }
}
</style>
