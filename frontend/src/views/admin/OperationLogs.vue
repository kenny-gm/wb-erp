<template>
  <div class="logs-container">
    <el-card>
      <template #header>
        <div class="card-header">
          <span>📋 运营日志</span>
          <el-button type="primary" size="small" @click="showCreateDialog">添加日志</el-button>
        </div>
      </template>
      
      <el-form :inline="true" class="filter-form">
        <el-form-item label="产品">
          <el-select v-model="filter.productId" placeholder="选择产品" clearable filterable @change="fetchLogs">
            <el-option v-for="p in products" :key="p.id" :label="(p.shop_name || p.name) + ' - ' + (p.custom_name || p.name) + ' (' + (p.nm_id || '-') + ')'" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="天数">
          <el-select v-model="filter.days" placeholder="选择天数">
            <el-option label="7天" :value="7" />
            <el-option label="30天" :value="30" />
            <el-option label="90天" :value="90" />
          </el-select>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="fetchLogs">查询</el-button>
        </el-form-item>
      </el-form>
      
      <el-table :data="logs" stripe v-loading="loading">
        <el-table-column prop="date" label="日期" width="120" />
        <el-table-column prop="shop_name" label="店铺" width="120" />
        <el-table-column prop="product_name" label="产品" min-width="180" show-overflow-tooltip />
        <el-table-column prop="nm_id" label="NM_ID" width="110" />

        <el-table-column prop="action_type" label="操作类型" width="100">
          <template #default="{ row }">
            <el-tag size="small">{{ getActionTypeText(row.action_type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="effect" label="效果" width="80">
          <template #default="{ row }">
            <el-tag :type="getEffectType(row.effect)" size="small">{{ getEffectText(row.effect) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="detail" label="详情" min-width="200" show-overflow-tooltip />
        <el-table-column prop="effect_analysis" label="效果分析" min-width="200" show-overflow-tooltip />
        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" link @click="editLog(row)">编辑</el-button>
            <el-button v-if="isAdmin" type="danger" size="small" link @click="deleteLog(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>
    
    <el-dialog v-model="createDialogVisible" title="添加运营日志" width="500px">
      <el-form :model="logForm" label-width="100px">
        <el-form-item label="产品">
          <el-select v-model="logForm.product_id" placeholder="选择产品" filterable>
            <el-option v-for="p in products" :key="p.id" :label="(p.shop_name || p.name) + ' - ' + (p.custom_name || p.name) + ' (' + (p.nm_id || '-') + ')'" :value="p.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="操作类型">
          <el-select v-model="logForm.action_type" placeholder="请选择">
            <el-option label="调整广告" value="adjust_ad" />
            <el-option label="优化价格" value="update_price" />
            <el-option label="优化页面" value="optimize_page" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="logForm.title" placeholder="请输入标题" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="logForm.content" type="textarea" :rows="3" placeholder="请输入内容" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitLog">提交</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" title="编辑运营日志" width="500px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="操作类型">
          <el-select v-model="editForm.action_type" placeholder="请选择">
            <el-option label="调整广告" value="adjust_ad" />
            <el-option label="优化价格" value="update_price" />
            <el-option label="优化页面" value="optimize_page" />
            <el-option label="忽略" value="ignore" />
            <el-option label="其他" value="other" />
          </el-select>
        </el-form-item>
        <el-form-item label="标题">
          <el-input v-model="editForm.title" placeholder="请输入标题" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="editForm.content" type="textarea" :rows="3" placeholder="请输入内容" />
        </el-form-item>
        <el-form-item label="效果">
          <el-select v-model="editForm.effect" placeholder="请选择">
            <el-option label="正向" value="positive" />
            <el-option label="中性" value="neutral" />
            <el-option label="负向" value="negative" />
            <el-option label="待追踪" value="pending" />
          </el-select>
        </el-form-item>
        <el-form-item label="效果分析">
          <el-input v-model="editForm.effect_analysis" type="textarea" :rows="3" placeholder="请输入效果分析" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { useAuthStore } from '../../stores/auth'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.user?.role === 'admin')

const loading = ref(false)
const logs = ref([])
const products = ref([])
const createDialogVisible = ref(false)
const editDialogVisible = ref(false)
const currentEditLog = ref(null)

const filter = reactive({
  productId: null,
  days: 365
})

const logForm = reactive({
  product_id: null,
  action_type: 'adjust_ad',
  tracking_days: 7,
  title: '',
  content: ''
})

const editForm = reactive({
  title: '',
  content: '',
  action_type: '',
  effect: '',
  effect_analysis: ''
})

function getActionTypeText(type) {
  const map = { adjust_ad: '调整广告', update_price: '优化价格', optimize_page: '优化页面', ignore: '忽略', other: '其他' }
  return map[type] || type
}

function getEffectType(effect) {
  const map = { positive: 'success', neutral: 'info', negative: 'danger', pending: 'warning' }
  return map[effect] || 'info'
}

function getEffectText(effect) {
  const map = { positive: '正向', neutral: '中性', negative: '负向', pending: '待追踪' }
  return map[effect] || effect
}

async function fetchLogs() {
  loading.value = true
  try {
    let url, params
    if (filter.productId) {
      url = '/api/operation-logs/product/' + filter.productId
      params = { days: filter.days }
    } else {
      url = '/api/operation-logs/'
      const endDate = new Date().toISOString().split('T')[0]
      const startDate = new Date(Date.now() - filter.days * 24 * 60 * 60 * 1000).toISOString().split('T')[0]
      params = { start_date: startDate, end_date: endDate, limit: 500 }
    }
    const response = await axios.get(url, { params })
    logs.value = response.data
  } catch (error) {
    ElMessage.error('获取日志失败')
  } finally {
    loading.value = false
  }
}

async function fetchProducts() {
  try {
    const response = await axios.get('/api/products/', { params: { limit: 100 } })
    products.value = response.data.products || response.data || []
  } catch (error) {
    console.error('获取产品失败', error)
  }
}

async function submitLog() {
  if (!logForm.product_id || !logForm.title) {
    ElMessage.warning('请填写必填项')
    return
  }
  try {
    await axios.post('/api/operation-logs/', logForm)
    ElMessage.success('日志添加成功')
    createDialogVisible.value = false
    fetchLogs()
  } catch (error) {
    ElMessage.error('添加失败')
  }
}

function showCreateDialog() {
  logForm.product_id = filter.productId
  logForm.title = ''
  logForm.content = ''
  createDialogVisible.value = true
}

function editLog(row) {
  currentEditLog.value = row
  editForm.title = row.title || ''
  editForm.content = row.detail || ''
  editForm.action_type = row.action_type || ''
  editForm.effect = row.effect || ''
  editForm.effect_analysis = row.effect_analysis || ''
  editDialogVisible.value = true
}

async function submitEdit() {
  if (!currentEditLog.value) return
  try {
    await axios.patch('/api/operation-logs/' + currentEditLog.value.id, {
      title: editForm.title,
      content: editForm.content,
      action_type: editForm.action_type,
      effect: editForm.effect,
      effect_analysis: editForm.effect_analysis
    })
    ElMessage.success('日志更新成功')
    editDialogVisible.value = false
    fetchLogs()
  } catch (error) {
    ElMessage.error('更新失败')
  }
}

async function deleteLog(row) {
  try {
    await ElMessageBox.confirm('确定要删除这条日志吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    })
    await axios.delete('/api/operation-logs/' + row.id)
    ElMessage.success('日志删除成功')
    fetchLogs()
  } catch (error) {
    if (error !== 'cancel') {
      ElMessage.error('删除失败')
    }
  }
}

onMounted(() => {
  fetchProducts()
  fetchLogs()
})
</script>

<style scoped>
.logs-container {
  padding: 16px;
  background: var(--surface-page);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  color: var(--text-strong);
  font-size: 16px;
  font-weight: 800;
}

.filter-form {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 10px;
  margin-bottom: 12px;
  padding: 10px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-muted);
}

.filter-form :deep(.el-select) {
  width: 220px;
}

.filter-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.logs-container :deep(.el-card) {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.logs-container :deep(.el-card__header) {
  padding: 12px 14px;
  background: var(--surface-panel);
  border-bottom-color: var(--border-subtle);
}

.logs-container :deep(.el-card__body) {
  padding: 12px;
}

.logs-container :deep(.el-table th.el-table__cell) {
  background: var(--surface-muted);
  color: var(--text-subtle);
}

.logs-container :deep(.el-table .el-table__cell) {
  padding: 8px 0;
}

@media (max-width: 768px) {
  .logs-container { padding: 12px; }
  
  .filter-form {
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  
  .filter-form :deep(.el-form-item) {
    margin-bottom: 0;
    width: 100%;
  }
  
  .filter-form :deep(.el-form-item__content) {
    width: 100%;
  }
  
  .filter-form :deep(.el-select) {
    width: 100%;
  }
  
  .card-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 12px;
  }
  
  .el-dialog {
    width: 95% !important;
    margin: 10px auto;
  }
}
</style>
