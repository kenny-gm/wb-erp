<template>
  <div class="products">
    <!-- 筛选和操作 -->
    <el-card class="filter-card">
      <el-form :inline="true">
        <el-form-item label="店铺">
          <el-select v-model="filters.shopId" placeholder="全部店铺" style="width: 150px" @change="fetchProducts">
            <el-option label="全部店铺" :value="null" />
            <el-option v-for="shop in shops" :key="shop.id" :label="shop.name" :value="shop.id" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="负责人">
          <el-select v-model="filters.owner" placeholder="全部" style="width: 150px" @change="fetchProducts">
            <el-option label="全部" :value="null" />
            <el-option v-for="owner in ownerList" :key="owner" :label="owner" :value="owner" />
          </el-select>
        </el-form-item>
        
        <el-form-item label="搜索">
          <el-input v-model="filters.search" placeholder="产品名称/SKU" clearable @keyup.enter="fetchProducts" style="width: 200px">
            <template #append>
              <el-button :icon="Search" @click="fetchProducts" />
            </template>
          </el-input>
        </el-form-item>
        
      </el-form>
      
      <!-- 管理员操作按钮 -->
      <div v-if="authStore.isAdmin" class="action-buttons">
        <el-button type="primary" @click="showSyncDialog = true">同步产品</el-button>
        <el-button @click="downloadTemplate" type="success">下载模板</el-button>
        <el-button @click="showImportDialog = true" type="warning">批量导入</el-button>
      </div>
    </el-card>
    
    <!-- 产品列表 -->
    <el-card>
      <div class="table-scroll-wrapper">
      <el-table :data="products" v-loading="loading" stripe style="min-width: 1100px;">
        <el-table-column prop="nm_id" label="产品ID" width="100" />
        <el-table-column prop="sku" label="SKU" width="150" />
        <el-table-column label="产品名称" min-width="200">
          <template #default="{ row }">
            <span>{{ row.custom_name || row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="owner" label="负责人" width="100" />
        <el-table-column prop="shop_name" label="店铺" width="120" />
        <el-table-column label="重量(kg)" width="100">
          <template #default="{ row }">
            {{ row.weight || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="尺寸(cm)" width="120">
          <template #default="{ row }">
            <span v-if="row.length">{{ row.length }}×{{ row.width }}×{{ row.height }}</span>
            <span v-else>-</span>
          </template>
        </el-table-column>
        <el-table-column label="采购价(CNY)" width="100">
          <template #default="{ row }">
            {{ row.purchase_price || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="头程单价(CNY)" width="100">
          <template #default="{ row }">
            {{ row.shipping_price || '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" size="small" @click="editProduct(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>
      </div>
      
      <!-- 分页 -->
      <el-pagination
        v-model:current-page="pagination.page"
        v-model:page-size="pagination.limit"
        :total="pagination.total"
        :page-sizes="[20, 50, 100, 200]"
        layout="total, sizes, prev, pager, next"
        @size-change="fetchProducts"
        @current-change="fetchProducts"
        style="margin-top: 20px; justify-content: flex-end"
      />
    </el-card>
    
    <!-- 编辑产品对话框 -->
    <el-dialog v-model="editDialogVisible" title="编辑产品" width="500px">
      <el-form :model="editForm" label-width="100px">
        <el-form-item label="产品ID">
          <el-input v-model="editForm.nm_id" disabled />
        </el-form-item>
        <el-form-item label="产品名称">
          <el-input v-model="editForm.custom_name" />
        </el-form-item>
        <el-form-item label="负责人">
          <el-input v-model="editForm.owner" />
        </el-form-item>
        <el-form-item label="重量(kg)">
          <el-input-number v-model="editForm.weight" :min="0" :precision="3" style="width: 100%" disabled />
        </el-form-item>
        <el-form-item label="长度(cm)">
          <el-input-number v-model="editForm.length" :min="0" :precision="1" style="width: 100%" disabled />
        </el-form-item>
        <el-form-item label="宽度(cm)">
          <el-input-number v-model="editForm.width" :min="0" :precision="1" style="width: 100%" disabled />
        </el-form-item>
        <el-form-item label="高度(cm)">
          <el-input-number v-model="editForm.height" :min="0" :precision="1" style="width: 100%" disabled />
        </el-form-item>
        <el-form-item label="采购价(CNY)">
          <el-input-number v-model="editForm.purchase_price" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
        <el-form-item label="头程单价(CNY)">
          <el-input-number v-model="editForm.shipping_price" :min="0" :precision="2" style="width: 100%" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveProduct">保存</el-button>
      </template>
    </el-dialog>
    
    <!-- 同步产品对话框 -->
    <el-dialog v-model="showSyncDialog" title="同步产品" width="500px">
      <el-form label-width="80px">
        <el-form-item label="选择店铺">
          <el-select v-model="syncShopId" placeholder="请选择店铺" style="width: 100%">
            <el-option v-for="shop in shops" :key="shop.id" :label="shop.name" :value="shop.id" />
          </el-select>
        </el-form-item>
        <p style="text-align: center; margin-top: 10px">{{ syncStatus }}</p>
        <p v-if="syncResult?.is_new_shop" style="color: #E6A23C; margin-bottom: 10px">
          新店铺检测到，正在同步历史数据（可能需要几分钟）...
        </p>
      </el-form>
      <template #footer>
        <el-button @click="showSyncDialog = false">取消</el-button>
        <el-button type="primary" @click="syncProducts" :loading="syncing">开始同步</el-button>
      </template>
    </el-dialog>
    
    <!-- 导入对话框 -->
    <el-dialog v-model="showImportDialog" title="批量导入" width="500px">
      <el-form label-width="100px">
        <el-form-item label="上传文件">
          <el-upload
            :auto-upload="false"
            :limit="1"
            accept=".xlsx"
            :on-change="handleFileChange"
          >
            <el-button>选择Excel文件</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showImportDialog = false">取消</el-button>
        <el-button type="primary" @click="handleImport" :loading="importing">导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { useAuthStore } from '@/stores/auth'

const authStore = useAuthStore()

const shops = ref([])
const products = ref([])
const loading = ref(false)
const syncing = ref(false)
const importing = ref(false)
const syncStatus = ref('')
const syncResult = ref(null)
const showSyncDialog = ref(false)
const showImportDialog = ref(false)
const editDialogVisible = ref(false)
const syncShopId = ref(null)
const importFile = ref(null)

const editForm = reactive({
  id: null,
  nm_id: '',
  custom_name: '',
  owner: '',
  weight: 0,
  length: 0,
  width: 0,
  height: 0,
  purchase_price: null,
  shipping_price: null
})

const filters = reactive({
  shopId: null,
  owner: null,
  search: ''
})

const pagination = reactive({
  page: 1,
  limit: 50,
  total: 0
})

const ownerList = computed(() => {
  const owners = new Set(products.value.map(p => p.owner).filter(Boolean))
  return Array.from(owners).sort()
})

async function fetchShops() {
  try {
    const response = await axios.get('/api/shops/')
    shops.value = response.data
  } catch (error) {
    console.error('获取店铺失败', error)
  }
}

async function fetchProducts() {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      limit: pagination.limit
    }
    if (filters.shopId) params.shop_id = filters.shopId
    if (filters.owner) params.owner = filters.owner
    if (filters.search) params.search = filters.search
    
    const response = await axios.get('/api/products/', { params })
    products.value = response.data.products || []
    pagination.total = response.data.total || 0
  } catch (error) {
    console.error('获取产品失败', error)
  } finally {
    loading.value = false
  }
}

function editProduct(product) {
  editForm.id = product.id
  editForm.nm_id = product.nm_id
  editForm.custom_name = product.custom_name || ''
  editForm.owner = product.owner || ''
  editForm.weight = product.weight || 0
  editForm.length = product.length || 0
  editForm.width = product.width || 0
  editForm.height = product.height || 0
  editForm.purchase_price = product.purchase_price || null
  editForm.shipping_price = product.shipping_price || null
  editDialogVisible.value = true
}

async function saveProduct() {
  try {
    await axios.put(`/api/products/${editForm.id}/`, {
      custom_name: editForm.custom_name,
      owner: editForm.owner,
      purchase_price: editForm.purchase_price,
      shipping_price: editForm.shipping_price
    })
    ElMessage.success('保存成功')
    editDialogVisible.value = false
    fetchProducts()
  } catch (error) {
    ElMessage.error('保存失败')
  }
}

async function syncProducts() {
  if (!syncShopId.value) {
    ElMessage.warning('请选择店铺')
    return
  }
  syncing.value = true
  syncStatus.value = '正在同步...'
  syncResult.value = null
  try {
    const response = await axios.post(`/api/shops/${syncShopId.value}/sync/?sync_type=products`)
    syncResult.value = response.data
    syncStatus.value = response.data.success ? '同步成功' : '同步失败'
    if (response.data.success) {
      ElMessage.success('同步成功')
      showSyncDialog.value = false
      fetchProducts()
    } else {
      ElMessage.error('同步失败: ' + (response.data.error || ''))
    }
  } catch (error) {
    syncStatus.value = '同步失败'
    ElMessage.error('同步失败')
  } finally {
    syncing.value = false
  }
}

function downloadTemplate() {
  const token = localStorage.getItem('token') || localStorage.getItem('access_token') || ''
  const url = '/api/products/import-template/'
  fetch(url, {
    headers: { Authorization: `Bearer ${token}` }
  })
    .then(r => r.blob())
    .then(blob => {
      const a = document.createElement('a')
      a.href = URL.createObjectURL(blob)
      a.download = 'products_template.xlsx'
      a.click()
      URL.revokeObjectURL(a.href)
    })
    .catch(() => {
      const a = window.open('/api/products/import-template/', '_blank')
      if (!a) ElMessage.error('下载失败，请允许弹出窗口')
    })
}

function handleFileChange(file) {
  importFile.value = file.raw
}

async function handleImport() {
  if (!importFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  importing.value = true
  try {
    const formData = new FormData()
    formData.append('file', importFile.value)
    await axios.post('/api/products/import/', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
    ElMessage.success('导入成功')
    showImportDialog.value = false
    fetchProducts()
  } catch (error) {
    const msg = error?.response?.data?.detail || error?.response?.data?.message || '导入失败'
    ElMessage.error(msg)
  } finally {
    importing.value = false
  }
}

onMounted(() => {
  fetchShops()
  fetchProducts()
})
</script>

<style scoped>
.filter-card {
  margin-bottom: 20px;
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
  .filter-card {
    padding: 12px;
  }

  .filter-card :deep(.el-form--inline) {
    display: flex;
    flex-direction: column;
    gap: 0;
  }

  .filter-card :deep(.el-form-item) {
    margin-bottom: 10px;
    margin-right: 0;
    width: 100%;
  }

  .filter-card :deep(.el-form-item__content) {
    width: 100%;
  }

  .filter-card :deep(.el-input),
  .filter-card :deep(.el-select),
  .filter-card :deep(.el-input-number) {
    width: 100% !important;
    min-width: 0;
  }

  .filter-card :deep(.el-form-item:last-child) {
    margin-bottom: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
  }

  .table-scroll-wrapper {
    margin: 0 -12px;
    padding: 0 12px;
  }

  .action-buttons {
    margin-top: 12px;
    display: flex;
    flex-wrap: wrap;
    gap: 8px;
    align-items: center;
  }

  @media (max-width: 768px) {
    .action-buttons {
      flex-wrap: nowrap;
      overflow-x: auto;
      gap: 4px;
      padding-bottom: 4px;
    }

    .action-buttons :deep(.el-button) {
      padding: 8px 10px;
      font-size: 12px;
      white-space: nowrap;
    }
  }
}
</style>
