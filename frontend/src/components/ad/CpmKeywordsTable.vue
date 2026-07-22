<template>
  <div class="keywords-card">
    <div class="card-header">
      <h3>CPM搜索关键词</h3>
      <div class="header-info">
        <span class="total-spend">总花费: {{ formatNumber(totalSpend) }} {{ currencySymbol }}</span>
      </div>
    </div>
    
    <!-- 概览卡片 -->
    <div class="overview-cards">
      <div class="overview-card">
        <div class="card-label">关键词数</div>
        <div class="card-value">{{ keywords.length }}</div>
      </div>
      <div class="overview-card">
        <div class="card-label">总点击</div>
        <div class="card-value">{{ formatNumber(totalClicks) }}</div>
      </div>
      <div class="overview-card">
        <div class="card-label">总订单</div>
        <div class="card-value">{{ formatNumber(totalOrders) }}</div>
      </div>
      <div class="overview-card">
        <div class="card-label">平均CPC</div>
        <div class="card-value">{{ avgCpc.toFixed(2) }} {{ currencySymbol }}</div>
      </div>
      <div class="overview-card">
        <div class="card-label">平均排名</div>
        <div class="card-value">{{ avgPosition.toFixed(1) }}</div>
      </div>
    </div>
    
    <!-- 筛选 -->
    <div class="filter-row">
      <el-input
        v-model="searchKeyword"
        placeholder="搜索关键词..."
        style="width: 250px"
        clearable
      />
      <el-select v-model="sortBy" style="width: 150px">
        <el-option label="按花费排序" value="spend" />
        <el-option label="按点击排序" value="clicks" />
        <el-option label="按订单排序" value="orders" />
        <el-option label="按排名排序" value="avg_position" />
      </el-select>
      <div class="filter-right">
        <span class="page-size-label">每页显示</span>
        <el-select v-model="pageSize" style="width: 100px">
          <el-option label="20" :value="20" />
          <el-option label="50" :value="50" />
          <el-option label="100" :value="100" />
        </el-select>
      </div>
    </div>
    
    <!-- 关键词表格 -->
    <el-table 
      :data="paginatedKeywords" 
      stripe
      style="width: 100%; min-width: 900px;"
      :show-header="true"
      :fit="true"
      :default-sort="{ prop: 'spend', order: 'descending' }"
      row-key="keyword"
      :expand-row-keys="expandedKeys"
      @expand-change="handleExpandChange"
    >
      <el-table-column type="expand" width="50" fixed="left">
        <template #default="props">
          <div v-if="expandedKeys.includes(props.row.keyword)" class="daily-detail">
            <div v-if="detailLoading" class="detail-loading">
              <el-icon class="is-loading"><Loading /></el-icon> 加载中...
            </div>
            <div v-else-if="detailData.length === 0" class="detail-empty">
              暂无每日明细数据
            </div>
            <div v-else class="detail-table-wrap">
              <div class="detail-header-bar">
                <span class="detail-title">每日明细 - {{ props.row.keyword }}</span>
                <span class="detail-meta">总花费: {{ formatNumber(detailTotalSpend) }} {{ currencySymbol }} | 总点击: {{ formatNumber(detailTotalClicks) }} | 总订单: {{ formatNumber(detailTotalOrders) }}</span>
              </div>
              <el-table :data="detailData" size="small" :show-header="true">
                <el-table-column prop="date" label="日期" min-width="100" align="center" />
                <el-table-column label="花费" align="right" min-width="90">
                  <template #default="d">{{ formatNumber(d.row.spend) }} {{ currencySymbol }}</template>
                </el-table-column>
                <el-table-column label="点击" align="right" min-width="70">
                  <template #default="d">{{ formatNumber(d.row.clicks) }}</template>
                </el-table-column>
                <el-table-column label="CPC" align="right" min-width="70">
                  <template #default="d">{{ d.row.cpc.toFixed(2) }} {{ currencySymbol }}</template>
                </el-table-column>
                <el-table-column label="订单" align="right" min-width="60">
                  <template #default="d">{{ formatNumber(d.row.orders) }}</template>
                </el-table-column>
                <el-table-column label="转化率" align="right" min-width="80">
                  <template #default="d">{{ d.row.conv_rate.toFixed(2) }}%</template>
                </el-table-column>
                <el-table-column label="购物车" align="right" min-width="70">
                  <template #default="d">{{ formatNumber(d.row.atbs) }}</template>
                </el-table-column>
                <el-table-column label="已购数" align="right" min-width="70">
                  <template #default="d">{{ formatNumber(d.row.shks) }}</template>
                </el-table-column>
                <el-table-column label="平均排名" align="right" min-width="90">
                  <template #default="d">{{ d.row.avg_position.toFixed(1) }}</template>
                </el-table-column>
                <el-table-column label="购物车率" align="right" min-width="80">
                  <template #default="d">{{ d.row.cart_rate.toFixed(2) }}%</template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </template>
      </el-table-column>
      <el-table-column prop="keyword" label="搜索词" min-width="200" fixed="left">
        <template #default="props">
          <span class="keyword-text" :class="{ 'keyword-expanded': expandedKeys.includes(props.row.keyword) }">
            {{ props.row.keyword }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="花费" align="right" min-width="100" sortable prop="spend" :sort-orders="['descending', 'ascending']">
        <template #default="props">
          {{ formatNumber(props.row.spend) }} {{ currencySymbol }}
        </template>
      </el-table-column>
      <el-table-column label="点击" align="right" min-width="80" sortable prop="clicks" :sort-orders="['descending', 'ascending']">
        <template #default="props">
          {{ formatNumber(props.row.clicks) }}
        </template>
      </el-table-column>
      <el-table-column label="CPC" align="right" min-width="80">
        <template #default="props">
          {{ props.row.cpc.toFixed(2) }} {{ currencySymbol }}
        </template>
      </el-table-column>
      <el-table-column label="订单" align="right" min-width="70" sortable prop="orders" :sort-orders="['descending', 'ascending']">
        <template #default="props">
          {{ formatNumber(props.row.orders) }}
        </template>
      </el-table-column>
      <el-table-column label="转化率" align="right" min-width="80">
        <template #default="props">
          {{ props.row.conv_rate.toFixed(2) }}%
        </template>
      </el-table-column>
      <el-table-column label="购物车" align="right" min-width="80">
        <template #default="props">
          {{ formatNumber(props.row.atbs) }}
        </template>
      </el-table-column>
      <el-table-column label="已购数" align="right" min-width="80">
        <template #default="props">
          {{ formatNumber(props.row.shks) }}
        </template>
      </el-table-column>
      <el-table-column label="平均排名" align="right" min-width="90" sortable prop="avg_position" :sort-orders="['ascending', 'descending']">
        <template #default="props">
          {{ props.row.avg_position.toFixed(1) }}
        </template>
      </el-table-column>
      <el-table-column label="购物车率" align="right" min-width="90">
        <template #default="props">
          {{ props.row.cart_rate.toFixed(2) }}%
        </template>
      </el-table-column>
    </el-table>

    <!-- 分页 -->
    <div class="pagination-row">
      <el-pagination
        v-model:current-page="currentPage"
        v-model:page-size="pageSize"
        :page-sizes="[20, 50, 100]"
        :total="filteredKeywords.length"
        layout="total, prev, pager, next, sizes"
        background
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'
import { Loading } from '@element-plus/icons-vue'

const props = defineProps({
  keywords: {
    type: Array,
    default: () => []
  },
  dateFrom: {
    type: String,
    default: ''
  },
  dateTo: {
    type: String,
    default: ''
  },
  productId: {
    type: Number,
    default: null
  },
  currencySymbol: {
    type: String,
    default: '₽'
  }
})

const searchKeyword = ref('')
const sortBy = ref('spend')

// 分页
const pageSize = ref(20)
const currentPage = ref(1)

// 展开状态
const expandedKeys = ref([])
const detailLoading = ref(false)
const detailData = ref([])

// 计算属性
const totalSpend = computed(() => {
  return props.keywords.reduce((sum, k) => sum + (k.spend || 0), 0)
})

const totalClicks = computed(() => {
  return props.keywords.reduce((sum, k) => sum + (k.clicks || 0), 0)
})

const totalOrders = computed(() => {
  return props.keywords.reduce((sum, k) => sum + (k.orders || 0), 0)
})

const avgCpc = computed(() => {
  if (totalClicks.value === 0) return 0
  return totalSpend.value / totalClicks.value
})

const avgPosition = computed(() => {
  const withPos = props.keywords.filter(k => k.avg_position > 0)
  if (withPos.length === 0) return 0
  const sumPos = withPos.reduce((sum, k) => sum + k.avg_position, 0)
  return sumPos / withPos.length
})

const filteredKeywords = computed(() => {
  let result = [...props.keywords]
  
  if (searchKeyword.value) {
    const kw = searchKeyword.value.toLowerCase()
    result = result.filter(k => k.keyword.toLowerCase().includes(kw))
  }
  
  result.sort((a, b) => {
    if (sortBy.value === 'spend') return (b.spend || 0) - (a.spend || 0)
    if (sortBy.value === 'clicks') return (b.clicks || 0) - (a.clicks || 0)
    if (sortBy.value === 'orders') return (b.orders || 0) - (a.orders || 0)
    if (sortBy.value === 'avg_position') return (a.avg_position || 999) - (b.avg_position || 999)
    return 0
  })
  
  return result
})

const paginatedKeywords = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value
  const end = start + pageSize.value
  return filteredKeywords.value.slice(start, end)
})

// 每日明细统计
const detailTotalSpend = computed(() => detailData.value.reduce((s, d) => s + (d.spend || 0), 0))
const detailTotalClicks = computed(() => detailData.value.reduce((s, d) => s + (d.clicks || 0), 0))
const detailTotalOrders = computed(() => detailData.value.reduce((s, d) => s + (d.orders || 0), 0))

async function handleExpandChange(row) {
  // 自行判断当前行是否已被展开（不受 Element Plus expand 参数干扰）
  const isCurrentlyExpanded = expandedKeys.value.includes(row.keyword)
  if (isCurrentlyExpanded) {
    // 收回
    expandedKeys.value = []
    detailData.value = []
  } else {
    // 展开
    expandedKeys.value = [row.keyword]
    await fetchDailyDetail(row.keyword)
  }
}

async function fetchDailyDetail(keyword) {
  if (!props.productId) return
  detailLoading.value = true
  detailData.value = []
  try {
    const response = await axios.get(`/api/products/${props.productId}/keyword-daily/`, {
      params: { keyword, date_from: props.dateFrom, date_to: props.dateTo }
    })
    detailData.value = response.data.daily_data || []
  } catch (e) {
    console.error('获取每日明细失败', e)
    ElMessage.error('获取每日明细失败')
  } finally {
    detailLoading.value = false
  }
}

function formatNumber(n) {
  if (!n && n !== 0) return '0'
  const value = Number.parseFloat(String(n).replace(/,/g, ''))
  if (!Number.isFinite(value)) return '0'
  const rounded = Math.round((value + Number.EPSILON) * 100) / 100
  const [integerPart, decimalPart] = String(rounded).split('.')
  const integer = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return decimalPart ? `${integer}.${decimalPart}` : integer
}

watch(pageSize, () => { currentPage.value = 1 })
watch(searchKeyword, () => { currentPage.value = 1 })
</script>

<style scoped>
.keywords-card {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

.keywords-card :deep(.el-table) {
  table-layout: auto;
  overflow-x: auto;
  max-width: none;
}

.keywords-card :deep(.el-table__body-wrapper) {
  overflow-x: auto;
}

.keywords-card :deep(.cell) {
  white-space: nowrap;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.total-spend {
  font-size: 14px;
  color: #3b82f6;
  font-weight: 500;
}

.overview-cards {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.overview-card {
  background: #f9fafb;
  border-radius: 8px;
  padding: 12px 16px;
  min-width: 100px;
  text-align: center;
}

.overview-card .card-label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 4px;
}

.overview-card .card-value {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.filter-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
  align-items: center;
}

.filter-right {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-left: auto;
}

.page-size-label {
  font-size: 14px;
  color: #6b7280;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.keyword-text {
  font-size: 13px;
  color: #374151;
  cursor: pointer;
}

.keyword-text.keyword-expanded {
  color: #3b82f6;
  font-weight: 600;
}

/* 展开明细样式 */
.daily-detail {
  padding: 12px 16px;
  background: #f8fafc;
}

.detail-loading, .detail-empty {
  text-align: center;
  color: #9ca3af;
  padding: 20px 0;
  font-size: 14px;
}

.detail-table-wrap {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  overflow: hidden;
}

.detail-header-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #f1f5f9;
  border-bottom: 1px solid #e5e7eb;
}

.detail-title {
  font-size: 13px;
  font-weight: 600;
  color: #374151;
}

.detail-meta {
  font-size: 12px;
  color: #6b7280;
}

.daily-detail :deep(.el-table) {
  background: #fff;
}

@media (max-width: 768px) {
  .overview-cards { gap: 8px; }
  .overview-card { min-width: 80px; padding: 8px 12px; }
  .overview-card .card-value { font-size: 16px; }
  .filter-row { flex-direction: column; }
  .filter-row > * { width: 100% !important; }
}
</style>
