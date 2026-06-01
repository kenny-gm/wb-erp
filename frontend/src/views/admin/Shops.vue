<template>
  <div class="admin-shops">
    <el-card>
      <template #header>
        <el-button type="primary" @click="openCreateDialog">新增店铺</el-button>
      </template>

      <div class="table-scroll-wrapper">
      <el-table :data="shops" v-loading="loading" stripe style="min-width: 1100px;">
        <el-table-column prop="id" label="店铺ID" width="80" />
        <el-table-column prop="name" label="店铺名称" width="180" />
        <el-table-column prop="currency" label="货币" width="80" />
        <el-table-column prop="platform" label="平台" width="100">
          <template #default="{ row }">
            <el-tag :type="row.platform === 'yandex' ? 'warning' : 'primary'">
              {{ row.platform === 'yandex' ? 'Yandex' : 'Wildberries' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sync_enabled" label="自动同步" width="100">
          <template #default="{ row }">
            <el-tag :type="row.sync_enabled ? 'success' : 'info'">
              {{ row.sync_enabled ? '开启' : '关闭' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="sync_interval_hours" label="同步间隔" width="100">
          <template #default="{ row }">
            {{ row.sync_interval_hours }}小时
          </template>
        </el-table-column>
        <el-table-column prop="last_sync_at" label="上次同步" width="160">
          <template #default="{ row }">
            {{ row.last_sync_at ? formatDate(row.last_sync_at) : '从未同步' }}
          </template>
        </el-table-column>
        <el-table-column prop="is_active" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'">
              {{ row.is_active ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="testConnection(row)">测试</el-button>
            <el-button size="small" type="primary" @click="syncData(row)">同步</el-button>
            <el-button size="small" type="info" @click="viewSyncLogs(row)">日志</el-button>
            <el-button size="small" @click="editShop(row)">编辑</el-button>
            <el-button size="small" type="danger" @click="deleteShop(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
    </el-card>

    <!-- 创建/编辑店铺对话框 -->
    <el-dialog v-model="showCreateDialog" :title="editMode ? '编辑店铺' : '新增店铺'" width="540px">
      <el-form :model="shopForm" :rules="shopRules" ref="shopFormRef" label-width="110px">
        <el-form-item label="店铺名称" prop="name">
          <el-input v-model="shopForm.name" :placeholder="editMode ? '留空使用 Yandex 店铺名' : '输入店铺名称'" />
        </el-form-item>

        <el-form-item label="平台" prop="platform">
          <el-select v-model="shopForm.platform" style="width: 100%" @change="onPlatformChange" :disabled="editMode">
            <el-option label="Wildberries" value="wildberries" />
            <el-option label="Yandex" value="yandex" />
          </el-select>
        </el-form-item>

        <el-form-item label="API Token" prop="api_token">
          <el-input
            v-model="shopForm.api_token"
            type="textarea"
            rows="3"
            :placeholder="editMode ? '已保存，如需修改请输入新值' : '请输入 API Token'"
          />
          <span v-if="editMode && currentShop?.has_token" style="font-size: 12px; color: #909399; margin-top: 4px; display: block">
            当前Token: {{ currentShop.api_token }}
          </span>
        </el-form-item>

        <template v-if="shopForm.platform === 'yandex'">
          <el-alert type="info" :closable="false" style="margin-bottom: 12px">
            保存时将自动从 Yandex API 获取 business 和 campaign 信息，
            无需手动填写。
          </el-alert>

          <el-form-item label="货币类型">
            <el-select v-model="shopForm.currency" style="width: 100%">
              <el-option label="人民币 (CNY)" value="CNY" />
            </el-select>
          </el-form-item>
        </template>

        <template v-else>
          <el-form-item label="货币类型">
            <el-select v-model="shopForm.currency" style="width: 100%">
              <el-option label="卢布 (RUB)" value="RUB" />
              <el-option label="人民币 (CNY)" value="CNY" />
            </el-select>
          </el-form-item>
        </template>

        <el-form-item label="自动同步">
          <el-switch v-model="shopForm.sync_enabled" />
        </el-form-item>

        <el-form-item label="同步间隔">
          <el-input-number v-model="shopForm.sync_interval_hours" :min="1" :max="168" />
          <span style="margin-left: 10px">小时</span>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" @click="saveShop">保存</el-button>
      </template>
    </el-dialog>

    <!-- 同步进度对话框 -->
    <el-dialog v-model="showSyncDialog" title="同步数据" width="500px">
      <div v-if="syncing">
        <el-progress :percentage="syncProgress" :status="syncProgress < 100 ? '' : 'success'" />
        <p style="text-align: center; margin-top: 10px">{{ syncStatus }}</p>
      </div>
      <div v-else>
        <p v-if="syncResult?.is_new_shop" style="color: #E6A23C; margin-bottom: 10px">
          ⚠️ 新店铺检测，已自动同步90天历史数据
        </p>
        <div v-if="syncResult?.results">
          <p v-for="(val, key) in syncResult.results" :key="key">
            <strong>{{ key }}:</strong>
            <template v-if="val && typeof val === 'object'">
              {{ val.count ?? val.message ?? '' }}
            </template>
            <template v-else>{{ val }}</template>
          </p>
        </div>
      </div>
    </el-dialog>

    <!-- 同步日志对话框 -->
    <el-dialog v-model="showLogsDialog" title="同步日志" width="700px">
      <el-table :data="syncLogs" v-loading="logsLoading" stripe>
        <el-table-column prop="sync_type" label="类型" width="100" />
        <el-table-column prop="status" label="状态" width="80">
          <template #default="{ row }">
            <el-tag :type="row.status === 'success' ? 'success' : row.status === 'failed' ? 'danger' : 'warning'">
              {{ row.status === 'success' ? '成功' : row.status === 'failed' ? '失败' : '进行中' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="records_count" label="记录数" width="80" />
        <el-table-column prop="message" label="信息" min-width="150">
          <template #default="{ row }">
            {{ row.message || '-' }}
          </template>
        </el-table-column>
        <el-table-column prop="started_at" label="开始时间" width="160">
          <template #default="{ row }">
            {{ formatDate(row.started_at) }}
          </template>
        </el-table-column>
        <el-table-column prop="duration_seconds" label="耗时" width="80">
          <template #default="{ row }">
            {{ row.duration_seconds ? row.duration_seconds.toFixed(1) + 's' : '-' }}
          </template>
        </el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const shops = ref([])
const loading = ref(false)
const showCreateDialog = ref(false)
const showSyncDialog = ref(false)
const editMode = ref(false)
const syncing = ref(false)
const syncProgress = ref(0)
const syncStatus = ref('')
const syncResult = ref(null)
let pollInterval = null

const showLogsDialog = ref(false)
const logsLoading = ref(false)
const syncLogs = ref([])
const currentShop = ref(null)

const shopForm = reactive({
  id: null,
  name: '',
  api_token: '',
  platform: 'wildberries',
  currency: 'RUB',
  sync_enabled: true,
  sync_interval_hours: 24
})

const shopRules = {
  name: [{ required: true, message: '请输入店铺名称', trigger: 'blur' }],
  api_token: []
}

function formatDate(dateStr) {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')
  const hours = String(date.getHours()).padStart(2, '0')
  const minutes = String(date.getMinutes()).padStart(2, '0')
  const seconds = String(date.getSeconds()).padStart(2, '0')
  return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} (UTC+8)`
}

function onPlatformChange(platform) {
  if (platform === 'yandex') {
    shopForm.currency = 'CNY'
  } else {
    shopForm.currency = 'RUB'
  }
}

function openCreateDialog() {
  editMode.value = false
  currentShop.value = null
  Object.assign(shopForm, {
    id: null,
    name: '',
    api_token: '',
    platform: 'wildberries',
    currency: 'RUB',
    sync_enabled: true,
    sync_interval_hours: 24
  })
  showCreateDialog.value = true
}

async function fetchShops() {
  loading.value = true
  try {
    const response = await axios.get('/api/shops/')
    shops.value = response.data
  } catch (error) {
    ElMessage.error('获取店铺列表失败')
  } finally {
    loading.value = false
  }
}

function editShop(shop) {
  editMode.value = true
  currentShop.value = shop
  Object.assign(shopForm, {
    id: shop.id,
    name: shop.name,
    api_token: '',
    platform: shop.platform || 'wildberries',
    currency: shop.currency,
    sync_enabled: shop.sync_enabled,
    sync_interval_hours: shop.sync_interval_hours
  })
  showCreateDialog.value = true
}

async function saveShop() {
  if (!editMode.value && !shopForm.api_token) {
    ElMessage.error('请输入 API Token')
    return
  }
  try {
    const payload = {
      name: shopForm.name,
      platform: shopForm.platform,
      currency: shopForm.currency,
      sync_enabled: shopForm.sync_enabled,
      sync_interval_hours: shopForm.sync_interval_hours
    }
    if (shopForm.api_token) {
      payload.api_token = shopForm.api_token
    }

    if (editMode.value) {
      await axios.put(`/api/shops/${shopForm.id}/`, payload)
      ElMessage.success('更新成功')
    } else {
      const response = await axios.post('/api/shops/', payload)
      const data = Array.isArray(response.data) ? response.data : [response.data]
      ElMessage.success(`${data.length} 个店铺已创建/更新`)
    }

    showCreateDialog.value = false
    fetchShops()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
  }
}

async function testConnection(shop) {
  try {
    const response = await axios.post(`/api/shops/${shop.id}/test-connection/`)
    if (response.data.success) {
      ElMessage.success(response.data.message || '连接成功')
    } else {
      ElMessage.error(response.data.message || '连接失败')
    }
  } catch (error) {
    ElMessage.error('连接测试失败')
  }
}

async function viewSyncLogs(shop) {
  currentShop.value = shop
  showLogsDialog.value = true
  logsLoading.value = true
  try {
    const response = await axios.get(`/api/shops/${shop.id}/sync-logs/`)
    syncLogs.value = response.data
  } catch (error) {
    ElMessage.error('获取日志失败')
  } finally {
    logsLoading.value = false
  }
}

async function syncData(shop) {
  showSyncDialog.value = true
  syncing.value = true
  syncProgress.value = 0
  syncResult.value = null

  try {
    syncStatus.value = '正在同步...'

    // 启动异步任务
    const response = await axios.post(`/api/shops/${shop.id}/sync-async/?sync_type=all`)
    const jobId = response.data.job_id

    // 轮询任务状态
    pollInterval = setInterval(async () => {
      try {
        const res = await axios.get(`/api/shops/sync-jobs/${jobId}`)
        const job = res.data

        syncProgress.value = job.progress || 0
        syncStatus.value = job.message || '同步中...'

        if (job.status === 'success') {
          clearInterval(pollInterval)
          pollInterval = null
          syncing.value = false
          syncStatus.value = '同步完成'
          syncResult.value = job.result_json ? JSON.parse(job.result_json) : {}
          fetchShops()
          ElMessage.success('同步完成')
        } else if (job.status === 'failed') {
          clearInterval(pollInterval)
          pollInterval = null
          syncing.value = false
          syncStatus.value = '同步失败'
          syncResult.value = { error: job.error || '同步失败' }
          ElMessage.error('同步失败: ' + (job.error || '未知错误'))
        }
        // pending/running: 继续轮询
      } catch (e) {
        clearInterval(pollInterval)
        pollInterval = null
        syncing.value = false
        syncStatus.value = '查询失败'
        ElMessage.error('查询同步状态失败')
      }
    }, 3000)

  } catch (error) {
    if (pollInterval) clearInterval(pollInterval)
    syncing.value = false
    syncStatus.value = '启动失败'
    ElMessage.error('同步任务启动失败')
  }
}

async function deleteShop(shop) {
  await ElMessageBox.confirm(`确定删除店铺 ${shop.name}？`, '确认删除', { type: 'warning' })

  try {
    await axios.delete(`/api/shops/${shop.id}/`)
    ElMessage.success('删除成功')
    fetchShops()
  } catch (error) {
    ElMessage.error('删除失败')
  }
}

onMounted(() => {
  fetchShops()
})
</script>

<style scoped>
.admin-shops {
  padding: 20px;
}

.table-scroll-wrapper {
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.table-scroll-wrapper::-webkit-scrollbar {
  height: 4px;
}

.table-scroll-wrapper::-webkit-scrollbar-thumb {
  background: #dcdfe6;
  border-radius: 2px;
}

@media (max-width: 768px) {
  .admin-shops {
    padding: 12px;
  }

  .table-scroll-wrapper {
    margin: 0 -12px;
    padding: 0 12px;
  }

  .el-dialog {
    width: 95% !important;
    margin: 10px auto;
  }
}
</style>