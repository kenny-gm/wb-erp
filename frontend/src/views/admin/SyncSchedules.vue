<template>
  <div class="sync-schedules">
    <div class="toolbar">
      <el-select v-model="shopFilter" clearable placeholder="全部店铺" class="filter">
        <el-option
          v-for="shop in shops"
          :key="shop.id"
          :label="shop.name"
          :value="shop.id"
        />
      </el-select>
      <el-select v-model="typeFilter" clearable placeholder="全部类型" class="filter">
        <el-option
          v-for="item in syncTypes"
          :key="item.value"
          :label="item.label"
          :value="item.value"
        />
      </el-select>
      <el-button :loading="loading" @click="fetchSchedules">刷新</el-button>
      <el-button type="primary" :loading="initializing" @click="initializeSchedules">补齐默认计划</el-button>
    </div>

    <el-table :data="filteredSchedules" v-loading="loading" stripe>
      <el-table-column prop="shop_name" label="店铺" min-width="160" />
      <el-table-column prop="platform" label="平台" width="120">
        <template #default="{ row }">
          <el-tag :type="row.platform === 'yandex' ? 'warning' : 'primary'">
            {{ row.platform === 'yandex' ? 'Yandex' : 'Wildberries' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="sync_type_label" label="数据类型" width="140" />
      <el-table-column prop="enabled" label="启用" width="90">
        <template #default="{ row }">
          <el-switch
            v-model="row.enabled"
            :loading="savingId === row.id"
            @change="saveSchedule(row)"
          />
        </template>
      </el-table-column>
      <el-table-column label="间隔" width="190">
        <template #default="{ row }">
          <div class="interval-control">
            <el-input-number
              v-model="row.interval_minutes"
              :min="1"
              :max="10080"
              :step="intervalStep(row.interval_minutes)"
              controls-position="right"
              size="small"
              @change="saveSchedule(row)"
            />
            <span class="unit">{{ formatInterval(row.interval_minutes) }}</span>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="last_run_at" label="上次同步" width="170">
        <template #default="{ row }">{{ row.last_run_at || '-' }}</template>
      </el-table-column>
      <el-table-column prop="next_run_at" label="下次同步" width="170">
        <template #default="{ row }">{{ row.next_run_at || '-' }}</template>
      </el-table-column>
      <el-table-column prop="last_status" label="上次状态" width="110">
        <template #default="{ row }">
          <el-tag v-if="row.last_status" :type="row.last_status === 'success' ? 'success' : 'danger'">
            {{ row.last_status === 'success' ? '成功' : '失败' }}
          </el-tag>
          <span v-else>-</span>
        </template>
      </el-table-column>
      <el-table-column prop="last_message" label="信息" min-width="180" show-overflow-tooltip />
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" :loading="runningId === row.id" @click="runNow(row)">
            立即同步
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const schedules = ref([])
const loading = ref(false)
const initializing = ref(false)
const savingId = ref(null)
const runningId = ref(null)
const shopFilter = ref(null)
const typeFilter = ref('')

const syncTypes = [
  { value: 'customer_service', label: '客服' },
  { value: 'orders', label: '订单/销售' },
  { value: 'product_sales', label: '产品销售/漏斗' },
  { value: 'products', label: '商品' },
  { value: 'inventory', label: '库存' },
  { value: 'ads', label: '广告' },
  { value: 'keywords', label: '关键词' }
]

const shops = computed(() => {
  const map = new Map()
  schedules.value.forEach((item) => {
    if (!map.has(item.shop_id)) {
      map.set(item.shop_id, { id: item.shop_id, name: item.shop_name })
    }
  })
  return Array.from(map.values())
})

const filteredSchedules = computed(() => {
  return schedules.value.filter((item) => {
    if (shopFilter.value && item.shop_id !== shopFilter.value) return false
    if (typeFilter.value && item.sync_type !== typeFilter.value) return false
    return true
  })
})

function intervalStep(minutes) {
  if (minutes < 60) return 5
  if (minutes < 720) return 30
  return 60
}

function formatInterval(minutes) {
  if (minutes < 60) return '分钟'
  if (minutes % 1440 === 0) return `${minutes / 1440}天`
  if (minutes % 60 === 0) return `${minutes / 60}小时`
  return '分钟'
}

async function fetchSchedules() {
  loading.value = true
  try {
    const response = await axios.get('/api/sync-schedules/')
    schedules.value = response.data
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '获取同步设置失败')
  } finally {
    loading.value = false
  }
}

async function initializeSchedules() {
  initializing.value = true
  try {
    const response = await axios.post('/api/sync-schedules/initialize/')
    ElMessage.success(`已补齐 ${response.data.created || 0} 条默认计划`)
    await fetchSchedules()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '初始化失败')
  } finally {
    initializing.value = false
  }
}

async function saveSchedule(row) {
  savingId.value = row.id
  try {
    const response = await axios.put(`/api/sync-schedules/${row.id}/`, {
      enabled: row.enabled,
      interval_minutes: row.interval_minutes
    })
    const index = schedules.value.findIndex((item) => item.id === row.id)
    if (index >= 0) schedules.value[index] = response.data
    ElMessage.success('已保存')
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '保存失败')
    await fetchSchedules()
  } finally {
    savingId.value = null
  }
}

async function runNow(row) {
  runningId.value = row.id
  try {
    const response = await axios.post(`/api/sync-schedules/${row.id}/run-now/`)
    ElMessage.success(response.data.message || '同步任务已启动')
    await fetchSchedules()
  } catch (error) {
    ElMessage.error(error.response?.data?.detail || '启动同步失败')
  } finally {
    runningId.value = null
  }
}

onMounted(fetchSchedules)
</script>

<style scoped>
.sync-schedules {
  padding: 20px;
}

.toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.filter {
  width: 180px;
}

.interval-control {
  display: flex;
  align-items: center;
  gap: 8px;
}

.interval-control :deep(.el-input-number) {
  width: 108px;
}

.unit {
  color: #606266;
  font-size: 13px;
  min-width: 42px;
}

@media (max-width: 768px) {
  .sync-schedules {
    padding: 12px;
  }

  .filter {
    width: 100%;
  }
}
</style>
