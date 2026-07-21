<template>
  <div class="dashboard">
    <!-- 数据时间与口径说明 -->
    <div v-if="dataInfo.data_updated_at || dataInfo.data_staleness || dataInfo.exchange_rate" class="data-info-bar">
      <span v-if="dataInfo.data_updated_at" class="data-info-item">
        <el-icon><Clock /></el-icon> 数据更新时间：{{ dataInfo.data_updated_at }}
      </span>
      <span v-if="dataInfo.exchange_rate" class="data-info-item">
        <el-icon><Coin /></el-icon> 汇率：{{ dataInfo.exchange_rate }}
      </span>
      <span v-if="dataInfo.data_staleness" class="data-info-item data-info-warning">
        <el-icon><Warning /></el-icon> {{ dataInfo.data_staleness }}
      </span>
    </div>

    <div class="filter-bar">
      <div class="filter-item quick-filter">
        <el-button-group>
          <el-button :type="quickType === 'today' ? 'primary' : ''" @click="setQuickDate('today')">今天</el-button>
          <el-button :type="quickType === 'yesterday' ? 'primary' : ''" @click="setQuickDate('yesterday')">昨日</el-button>
          <el-button :type="quickType === '7d' ? 'primary' : ''" @click="setQuickDate('7d')">7天</el-button>
          <el-button :type="quickType === '30d' ? 'primary' : ''" @click="setQuickDate('30d')">30天</el-button>
        </el-button-group>
      </div>
      <div class="filter-item date-filter">
        <el-date-picker v-model="filters.dateRange" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" format="YYYY-MM-DD" value-format="YYYY-MM-DD" @change="handleDateChange" style="width: 240px" />
      </div>
      <div class="filter-item owner-filter">
        <el-select v-model="filters.owner" placeholder="全部负责人" clearable style="width: 120px">
          <el-option v-for="o in owners" :key="o" :label="o" :value="o" />
        </el-select>
      </div>
      <div class="filter-item product-filter flex-1">
        <el-select v-model="filters.productId" placeholder="全部产品" clearable filterable style="width: 100%">
          <el-option v-for="p in uniqueProducts" :key="p" :label="p" :value="p" />
        </el-select>
      </div>
      <el-button class="query-button" type="primary" @click="fetchData">查询</el-button>
    </div>

    <section class="metric-matrix-section">
      <div class="metric-matrix">
        <div class="matrix-fixed-column">
          <div class="matrix-fixed-cell matrix-metric-heading">指标</div>
          <div v-for="card in metricCards" :key="card.key" class="matrix-fixed-cell matrix-metric-label">
            <el-icon><component :is="card.icon" /></el-icon>
            <span>{{ card.label }}</span>
          </div>
        </div>

        <div class="matrix-scroll-pane">
          <div class="matrix-scroll-content">
            <div class="matrix-scroll-row matrix-header-row">
              <div v-for="section in metricSections" :key="section.key" class="matrix-section-heading">
                <div class="matrix-section-title">{{ section.title }}</div>
                <div class="matrix-section-subtitle">{{ section.subtitle }}</div>
                <el-select
                  v-if="section.currency"
                  v-model="section.shopIds"
                  class="section-shop-filter"
                  :placeholder="section.currency + ' 全部店铺'"
                  clearable
                  multiple
                  collapse-tags
                  collapse-tags-tooltip
                  filterable
                >
                  <el-option
                    v-for="shop in getSectionShopOptions(section.currency)"
                    :key="shop.id"
                    :label="shop.name"
                    :value="shop.id"
                  />
                </el-select>
              </div>
            </div>

            <div v-for="card in metricCards" :key="card.key" class="matrix-scroll-row">
              <div v-for="section in metricSections" :key="section.key + '-' + card.key" class="matrix-value-cell">
                <div class="matrix-value-line">
                  <span class="matrix-value">{{ formatMetricValue(section, card) }}</span>
                  <span class="matrix-change" :class="getChangeClass(section.summary[card.changeKey], card.reverseChange)">
                    {{ formatChange(section.summary[card.changeKey]) }}
                  </span>
                </div>
                <div class="matrix-chart" v-if="hasDateRange && section.trend[card.trendKey].length">
                  <svg class="matrix-line-chart" viewBox="0 0 100 50" preserveAspectRatio="none">
                    <path :d="getAreaPath(section.trend[card.trendKey], section.trend.max[card.trendKey])" :fill="card.color" fill-opacity="0.14" />
                    <polyline :points="getLinePoints(section.trend[card.trendKey], section.trend.max[card.trendKey])" fill="none" :stroke="card.color" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                  </svg>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
    <ProductSalesTable 
      :items="productList"
      :loading="loading"
      :start-date="filters.start_date" 
      :end-date="filters.end_date" 
      :selected-shops="[]"
      :selected-owner="filters.owner"
      :selected-product="filters.productId"
      :quick-type="quickType" 
    />

    <el-dialog v-model="logDialogVisible" title="产品日志" width="600px"><div class="log-header"><h4>{{ selectedProduct?.product_name }}</h4><span style="color:#909399">共 {{ logList.length }} 条日志</span></div><el-timeline v-if="logList.length > 0"><el-timeline-item v-for="log in logList" :key="log.id" :timestamp="log.created_at" placement="top"><div class="log-item"><div class="log-content">{{ log.action }}</div><div class="log-meta" v-if="log.operator">操作人: {{ log.operator }}</div></div></el-timeline-item></el-timeline><div v-else style="text-align:center;color:#909399;padding:32px">暂无日志记录</div></el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'
import { Money, User, ShoppingCart, Document, Notification, TrendCharts, DataLine, PieChart, Clock, Warning, Coin } from '@element-plus/icons-vue'
import ProductSalesTable from './ProductSalesTable.vue'

const loading = ref(false)
const shops = ref([])
const products = ref([])
const productList = ref([])
const owners = ref([])
const logCounts = ref({})
const quickType = ref('yesterday')

const filters = reactive({ dateRange: null, start_date: '', end_date: '', productId: null, owner: null })
const pagination = reactive({ page: 1, pageSize: 50 })
const expandedRows = ref([])
const logDialogVisible = ref(false)
const selectedProduct = ref(null)
const logList = ref([])

const dataInfo = reactive({ data_updated_at: '', data_staleness: '', exchange_rate: null })
const thresholds = reactive({ cart_rate: null, conversion_rate: null, ad_ratio: null })

const hasDateRange = computed(() => { if (!filters.start_date || !filters.end_date) return false; const days = Math.ceil((new Date(filters.end_date) - new Date(filters.start_date)) / 86400000) + 1; return days > 1; })
const displayProducts = computed(() => { const start = (pagination.page - 1) * pagination.pageSize; return productList.value.slice(start, start + pagination.pageSize) })
const uniqueProducts = computed(() => { const names = new Set(); products.value.forEach(p => { const name = p.custom_name || p.name; if (name) names.add(name); }); return Array.from(names).sort(); })

function createSummary() {
  return { total_sales: 0, total_visitors: 0, total_cart: 0, total_orders: 0, total_ad_cost: 0, avg_cart_rate: 0, avg_conversion_rate: 0, avg_ad_ratio: 0, sales_change: 0, visitors_change: 0, cart_change: 0, orders_change: 0, ad_cost_change: 0, cart_rate_change: 0, avg_conversion_rate_change: 0, ad_ratio_change: 0 }
}

function createTrend() {
  return { sales: [], visitors: [], cart: [], cart_rate: [], orders: [], conversion_rate: [], ad_cost: [], ad_ratio: [], max: { sales: 1, visitors: 1, cart: 1, cart_rate: 1, orders: 1, conversion_rate: 1, ad_cost: 1, ad_ratio: 1 } }
}

const metricSections = reactive([
  { key: 'unified', title: '统一卢布', subtitle: '全部店铺统一折算为 RUB', currency: null, displayCurrency: 'RUB', amountUnit: '₽', shopIds: [], summary: createSummary(), trend: createTrend() },
  { key: 'rub', title: 'RUB 店铺', subtitle: '可单独筛选 RUB 店铺', currency: 'RUB', displayCurrency: 'RUB', amountUnit: '₽', shopIds: [], summary: createSummary(), trend: createTrend() },
  { key: 'cny', title: 'CNY 店铺', subtitle: '可单独筛选 CNY 店铺，金额显示原始 CNY', currency: 'CNY', displayCurrency: 'NATIVE', amountUnit: '¥', shopIds: [], summary: createSummary(), trend: createTrend() },
])

const metricCards = [
  { key: 'sales', label: '销售额', icon: Money, valueKey: 'total_sales', changeKey: 'sales_change', trendKey: 'sales', unit: 'amount', color: '#10b981' },
  { key: 'visitors', label: '访客数', icon: User, valueKey: 'total_visitors', changeKey: 'visitors_change', trendKey: 'visitors', color: '#3b82f6' },
  { key: 'cart', label: '加购数', icon: ShoppingCart, valueKey: 'total_cart', changeKey: 'cart_change', trendKey: 'cart', color: '#8b5cf6' },
  { key: 'cart_rate', label: '加购率', icon: TrendCharts, valueKey: 'avg_cart_rate', changeKey: 'cart_rate_change', trendKey: 'cart_rate', unit: '%', color: '#a855f7', fixed: 2 },
  { key: 'orders', label: '订单数', icon: Document, valueKey: 'total_orders', changeKey: 'orders_change', trendKey: 'orders', color: '#f97316' },
  { key: 'conversion_rate', label: '转化率', icon: DataLine, valueKey: 'avg_conversion_rate', changeKey: 'avg_conversion_rate_change', trendKey: 'conversion_rate', unit: '%', color: '#06b6d4', fixed: 2 },
  { key: 'ad_cost', label: '广告费', icon: Notification, valueKey: 'total_ad_cost', changeKey: 'ad_cost_change', trendKey: 'ad_cost', unit: 'amount', color: '#ef4444', reverseChange: true },
  { key: 'ad_ratio', label: '广告占比', icon: PieChart, valueKey: 'avg_ad_ratio', changeKey: 'ad_ratio_change', trendKey: 'ad_ratio', unit: '%', color: '#ec489a', fixed: 2, reverseChange: true },
]

function getX(index, total) { return total <= 1 ? 50 : (index / (total - 1)) * 100 }
function getY(value, max) { return 50 - (value / max) * 45 }
function getLinePoints(data, max) { return data.map((d, i) => getX(i, data.length) + ',' + getY(d.value, max)).join(' ') }
function getAreaPath(data, max) { if (!data || data.length < 2) return ''; const pts = data.map((d, i) => getX(i, data.length) + ',' + getY(d.value, max)); return 'M' + pts.join('L') + 'V50H' + getX(0, data.length) + 'Z'; }
function getMetricLinePoints(data, metric, max) { return data.map((d, i) => getX(i, data.length) + ',' + getY(d[metric] || 0, max)).join(' ') }
function getMetricLabel(metric) { const labels = { visitors: '访客数', orders: '订单', sales: '销售额', ad_cost: '广告费' }; return labels[metric] || metric }
function getMetricStroke(metric) { const colors = { visitors: '#3b82f6', orders: '#f97316', sales: '#10b981', ad_cost: '#ef4444' }; return colors[metric] || '#3b82f6' }

async function fetchShops() { try { shops.value = (await axios.get('/api/shops/')).data } catch (e) { console.error(e) } }
async function fetchProducts() { try { const res = (await axios.get('/api/products/')).data; products.value = res.products || res || [] } catch (e) { console.error(e) } }
async function fetchOwners() { try { owners.value = (await axios.get('/api/dashboard/owners/')).data } catch (e) { console.error(e) } }
async function fetchThresholds() { try { const items = (await axios.get('/api/metric-thresholds/')).data || []; items.forEach(i => { thresholds[i.metric_name] = i }) } catch (e) { console.error(e) } }

function setQuickDate(type) {
  quickType.value = type
  const today = new Date()
  const y = today.getFullYear(), m = String(today.getMonth() + 1).padStart(2, '0'), d = String(today.getDate()).padStart(2, '0')
  const todayStr = y + '-' + m + '-' + d
  if (type === 'yesterday') {
    const yd = new Date(today); yd.setDate(yd.getDate() - 1)
    const yesterdayStr = yd.getFullYear() + '-' + String(yd.getMonth() + 1).padStart(2, '0') + '-' + String(yd.getDate()).padStart(2, '0')
    filters.dateRange = [yesterdayStr, yesterdayStr]
    filters.start_date = yesterdayStr; filters.end_date = yesterdayStr
  } else if (type === 'today') {
    filters.dateRange = [todayStr, todayStr]
    filters.start_date = todayStr; filters.end_date = todayStr
  } else {
    // 7天/30天: 从昨天开始往前推，不包含今天
    const yd = new Date(today); yd.setDate(yd.getDate() - 1)  // yesterday
    const daysBack = type === '7d' ? 6 : 29
    const sd = new Date(yd); sd.setDate(sd.getDate() - daysBack)
    const startStr = sd.getFullYear() + '-' + String(sd.getMonth() + 1).padStart(2, '0') + '-' + String(sd.getDate()).padStart(2, '0')
    const endStr = yd.getFullYear() + '-' + String(yd.getMonth() + 1).padStart(2, '0') + '-' + String(yd.getDate()).padStart(2, '0')
    filters.dateRange = [startStr, endStr]
    filters.start_date = startStr; filters.end_date = endStr
  }
}

function handleDateChange(val) { if (val && val.length === 2) { filters.start_date = val[0]; filters.end_date = val[1]; quickType.value = '' } }

async function fetchData() {
  loading.value = true; expandedRows.value = []
  try {
    const sectionShopIds = getSectionShopIds()
    const productRequests = metricSections.map(section => fetchDashboardProducts(sectionShopIds[section.key], section.displayCurrency))
    const trendRequests = metricSections.map(section => fetchDashboardTrend(sectionShopIds[section.key], section.displayCurrency))
    const [productResponses, trendResponses] = await Promise.all([
      Promise.all(productRequests),
      Promise.all(trendRequests)
    ])

    productList.value = productResponses[0].items || []
    metricSections.forEach((section, index) => {
      assignSummary(section.summary, productResponses[index])
      assignTrend(section.trend, trendResponses[index] || [])
    })

    const s = productResponses[0].summary || {}
    // 数据时间信息
    dataInfo.data_updated_at = s.data_updated_at || ''
    dataInfo.data_staleness = s.data_staleness || ''
    dataInfo.exchange_rate = s.exchange_rate || null
    fetchLogCounts()
  } catch (e) { ElMessage.error('获取数据失败') } finally { loading.value = false }
}

function buildProductRequest(shopIds, displayCurrency = 'RUB') {
  return {
    start_date: filters.start_date,
    end_date: filters.end_date,
    shop_ids: shopIds,
    owners: filters.owner ? [filters.owner] : [],
    product_name: filters.productId || undefined,
    display_currency: displayCurrency
  }
}

function getProductIdsForTrend() {
  if (!filters.productId) return []
  return products.value
    .filter(p => (p.custom_name || p.name) === filters.productId)
    .map(p => p.id)
}

async function fetchDashboardProducts(shopIds, displayCurrency = 'RUB') {
  if (shopIds === null) return { items: [], summary: {}, comparison: {} }
  const resp = await axios.post('/api/dashboard/products/', buildProductRequest(shopIds, displayCurrency))
  return resp.data || { items: [], summary: {}, comparison: {} }
}

async function fetchDashboardTrend(shopIds, displayCurrency = 'RUB') {
  if (shopIds === null) return []
  const resp = await axios.post('/api/dashboard/trend/', {
    start_date: filters.start_date,
    end_date: filters.end_date,
    shop_ids: shopIds,
    product_ids: getProductIdsForTrend(),
    display_currency: displayCurrency
  })
  return resp.data || []
}

function getSectionShopIds() {
  const idsByCurrency = section => {
    const selectedSet = section.shopIds.length ? new Set(section.shopIds) : null
    const ids = shops.value
      .filter(shop => (shop.currency || 'RUB') === section.currency)
      .map(shop => shop.id)
      .filter(id => !selectedSet || selectedSet.has(id))
    return ids.length ? ids : null
  }
  return {
    unified: [],
    rub: idsByCurrency(metricSections.find(section => section.key === 'rub')),
    cny: idsByCurrency(metricSections.find(section => section.key === 'cny'))
  }
}

function getSectionShopOptions(currency) {
  return shops.value.filter(shop => (shop.currency || 'RUB') === currency)
}

function assignSummary(target, data) {
  const s = data.summary || {}
  Object.assign(target, {
    total_sales: s.sales_amount || 0,
    total_visitors: s.visitors || 0,
    total_cart: s.add_to_cart || 0,
    total_orders: s.order_count || 0,
    total_ad_cost: s.ad_cost || 0,
    avg_cart_rate: s.add_to_cart_rate || 0,
    avg_conversion_rate: s.conversion_rate || 0,
    avg_ad_ratio: s.ad_ratio || 0,
    sales_change: data.comparison?.sales_amount || 0,
    visitors_change: data.comparison?.visitors || 0,
    cart_change: data.comparison?.add_to_cart || 0,
    orders_change: data.comparison?.order_count || 0,
    ad_cost_change: data.comparison?.ad_cost || 0,
    cart_rate_change: data.comparison?.add_to_cart_rate || 0,
    avg_conversion_rate_change: data.comparison?.conversion_rate || 0,
    ad_ratio_change: data.comparison?.ad_ratio || 0
  })
}

function assignTrend(target, data) {
  target.sales = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.sales || 0 }))
  target.visitors = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.visitors || 0 }))
  target.cart = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.cart || 0 }))
  target.orders = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.orders || 0 }))
  target.ad_cost = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.ad_cost || 0 }))
  target.cart_rate = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.visitors ? parseFloat(((d.cart || 0) / d.visitors * 100).toFixed(2)) : 0 }))
  target.conversion_rate = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.visitors ? parseFloat(((d.orders || 0) / d.visitors * 100).toFixed(2)) : 0 }))
  target.ad_ratio = data.map(d => ({ date: d.date, label: d.date.slice(5), value: d.sales ? parseFloat(((d.ad_cost || 0) / d.sales * 100).toFixed(2)) : 0 }))
  Object.keys(target.max).forEach(key => {
    target.max[key] = Math.max(...target[key].map(d => d.value), 1)
  })
}

async function fetchLogCounts() {
  if (!productList.value.length) return
  try { const resp = await axios.get('/api/operation-logs/counts'); logCounts.value = resp.data || {}; productList.value.forEach(p => { p.log_count = logCounts.value[p.product_id] || 0 }) } catch (e) { console.error(e) }
}

async function handleExpandChange(row, expanded) {
  if (expanded && !row.expanded) {
    row.isDateRange = hasDateRange.value
    row.shops = []
    row.shopDailyData = null
    
    try {
      if (hasDateRange.value) {
        // 时间范围模式：获取每个店铺每日数据
        const resp = await axios.post('/api/dashboard/trend/', {
          start_date: filters.start_date,
          end_date: filters.end_date,
          shop_ids: [],
          product_ids: [row.product_id]
        })
        const data = resp.data || []
        row.shopDailyData = data.map(d => ({
          date: d.date,
          shop_id: d.shop_id,
          shop_name: d.shop_name || '店铺' + d.shop_id,
          visitors: d.visitors || 0,
          add_to_cart: d.cart || 0,
          cart_rate: d.visitors ? ((d.cart || 0) / d.visitors * 100).toFixed(2) : '0.00',
          orders: d.orders || 0,
          sales: d.sales || 0,
          ad_cost: d.ad_cost || 0,
          ad_ratio: d.ad_ratio || '0.00'
        }))
      } else {
        // 单日模式：获取各店铺汇总
        row.shops = [
          { id: 1, name: '炊恒跨境1', currency: 'CNY', visitors: 1234, add_to_cart: 89, orders: 45, sales: 89500, ad_cost: 1200, ad_ratio: '1.34' },
          { id: 2, name: '炊恒跨境2', currency: 'CNY', visitors: 2345, add_to_cart: 156, orders: 78, sales: 156000, ad_cost: 2300, ad_ratio: '1.47' },
        ]
      }
      row.expanded = true
    } catch (e) {
      console.error('Failed to fetch expand data:', e)
    }
  } else if (!expanded) {
    row.expanded = false
  }
  expandedRows.value = expanded ? [row.product_id] : []
}

function openLogDialog(product) { selectedProduct.value = product; logDialogVisible.value = true; fetchProductLogs(product.product_id) }
async function fetchProductLogs(productId) { try { logList.value = (await axios.get('/api/operation-logs/', { params: { product_id: productId } })).data || [] } catch (e) { console.error(e); logList.value = [] } }
function handleSizeChange() { pagination.page = 1; fetchData() }
function handlePageChange() { fetchData() }
function formatNumber(n) {
  if (!n && n !== 0) return '0'
  const value = Number.parseFloat(String(n).replace(/,/g, ''))
  if (!Number.isFinite(value)) return '0'
  const rounded = Math.round((value + Number.EPSILON) * 100) / 100
  const [integerPart, decimalPart] = String(rounded).split('.')
  const integer = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return decimalPart ? `${integer}.${decimalPart}` : integer
}
function formatChange(c) { return c || c === 0 ? (c >= 0 ? '+' : '') + c.toFixed(1) + '%' : '0%' }
function formatMetricValue(section, card) {
  const value = section.summary[card.valueKey] || 0
  if (card.unit === '%') return Number(value).toFixed(card.fixed ?? 2) + '%'
  const unit = card.unit === 'amount' ? section.amountUnit : card.unit
  return formatNumber(value) + (unit ? ' ' + unit : '')
}
function getChangeClass(value, reverse = false) {
  const positive = (value || 0) >= 0
  return reverse ? (positive ? 'negative' : 'positive') : (positive ? 'positive' : 'negative')
}
function getRateClass(rate, metric) { const t = thresholds[metric]; if (!t || !rate) return ''; return rate <= t.danger_threshold ? 'rate-danger' : rate <= t.warning_threshold ? 'rate-warning' : 'rate-success' }

// initialized 防止 setQuickDate 触发 watch 与 onMounted 手动调用重复请求
const initialized = ref(false)
watch(
  () => [
    filters.start_date,
    filters.end_date,
    filters.owner,
    filters.productId,
    metricSections.find(section => section.key === 'rub').shopIds.join(','),
    metricSections.find(section => section.key === 'cny').shopIds.join(',')
  ],
  () => { if (initialized.value) fetchData() }
)
onMounted(async () => {
  await Promise.all([fetchShops(), fetchProducts(), fetchOwners(), fetchThresholds()])
  setQuickDate('yesterday')
  initialized.value = true
  await fetchData()
})
</script>

<style scoped>
.dashboard {
  padding: 16px;
  background: var(--surface-page);
  display: grid;
  gap: 12px;
  min-height: 100%;
}

.data-info-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  padding: 8px 10px;
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  color: var(--text-main);
  font-size: 13px;
  align-items: center;
}

.data-info-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 28px;
  padding: 0 10px;
  border-radius: var(--radius-md);
  border: 1px solid var(--border-subtle);
  background: var(--surface-panel);
  color: var(--text-subtle);
}

.data-info-warning { color: var(--color-warning); }

.filter-bar {
  display: grid;
  grid-template-columns: auto auto auto minmax(220px, 1fr) auto;
  gap: 8px;
  align-items: center;
  padding: 10px;
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}

.filter-item { display: flex; align-items: center; }
.filter-item.flex-1 { flex: 1; min-width: 0; }

.filter-bar :deep(.el-select),
.filter-bar :deep(.el-date-editor),
.filter-bar :deep(.el-input) {
  width: 100%;
  height: 32px;
  border-radius: var(--radius-md);
  font-size: 13px;
}

.filter-bar :deep(.el-button-group) { display: inline-flex; }
.filter-bar :deep(.el-button-group .el-button) {
  height: 32px;
  padding: 0 14px;
  border-radius: 0;
  font-size: 13px;
  font-weight: 700;
}
.filter-bar :deep(.el-button-group .el-button:first-child) { border-radius: var(--radius-md) 0 0 var(--radius-md); }
.filter-bar :deep(.el-button-group .el-button:last-child) { border-radius: 0 var(--radius-md) var(--radius-md) 0; }
.filter-bar > .el-button {
  height: 32px;
  border-radius: var(--radius-md);
  font-weight: 700;
  padding: 0 14px;
}

.metric-matrix-section {
  margin: 0;
  max-width: 100%;
}
.metric-matrix {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.matrix-fixed-column {
  position: relative;
  z-index: 3;
  background: var(--surface-muted);
  border-right: 1px solid var(--border-subtle);
  box-shadow: 8px 0 12px -12px rgba(15, 23, 42, 0.35);
}

.matrix-scroll-pane {
  min-width: 0;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
  overscroll-behavior-x: contain;
  touch-action: pan-x pan-y;
}

.matrix-scroll-content {
  min-width: 660px;
}

.matrix-fixed-cell,
.matrix-scroll-row {
  min-height: 58px;
  border-top: 1px solid var(--border-subtle);
}

.matrix-fixed-cell:first-child,
.matrix-scroll-row:first-child {
  min-height: 112px;
  border-top: 0;
}

.matrix-scroll-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(220px, 1fr));
}

.matrix-header-row { background: var(--surface-muted); }

.matrix-metric-heading {
  display: flex;
  align-items: center;
  padding: 14px 16px;
  font-size: 13px;
  font-weight: 750;
  color: var(--text-subtle);
}

.matrix-section-heading {
  min-width: 0;
  padding: 12px 14px;
  border-right: 1px solid var(--border-subtle);
}
.matrix-section-heading:last-child { border-right: none; }
.matrix-section-title {
  font-size: 14px;
  font-weight: 800;
  color: var(--text-strong);
  line-height: 1.2;
}
.matrix-section-subtitle {
  margin-top: 3px;
  font-size: 12px;
  color: var(--text-subtle);
}
.section-shop-filter { margin-top: 8px; width: 100%; }

.matrix-metric-label {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  background: var(--surface-muted);
  font-size: 13px;
  font-weight: 700;
  color: var(--text-subtle);
}

.matrix-value-cell {
  padding: 12px 14px;
  border-right: 1px solid var(--border-subtle);
  min-width: 0;
}
.matrix-value-cell:last-child { border-right: none; }

.matrix-value-line {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  min-height: 24px;
}

.matrix-value {
  font-family: var(--font-number);
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum';
  font-size: 17px;
  font-weight: 800;
  color: var(--text-strong);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.matrix-change {
  flex: 0 0 auto;
  font-family: var(--font-number);
  font-variant-numeric: tabular-nums;
  font-feature-settings: 'tnum';
  font-size: 12px;
  font-weight: 800;
  padding: 2px 7px;
  border-radius: var(--radius-full);
  white-space: nowrap;
}

.matrix-change.positive {
  color: var(--color-success);
  background: var(--color-success-soft);
}

.matrix-change.negative {
  color: var(--color-danger);
  background: var(--color-danger-soft);
}

.matrix-chart {
  margin-top: 8px;
  width: 100%;
  height: 28px;
}

.matrix-line-chart {
  width: 100%;
  height: 28px;
  display: block;
}

.product-table-card {
  background: var(--surface-panel);
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  overflow: hidden;
}

.product-table-card :deep(.el-card__header),
.product-table-card :deep(.el-card__body) {
  padding: 12px 14px;
  background: var(--surface-panel);
}

.product-table-card :deep(.el-table th.el-table__cell) {
  background: var(--surface-muted);
  color: var(--text-subtle);
  font-weight: 800;
  border-bottom-color: var(--border-subtle);
  height: 36px;
}

.product-table-card :deep(.el-table td.el-table__cell) {
  border-bottom-color: var(--border-subtle);
  color: var(--text-main);
  font-size: 13px;
}

.product-table-card :deep(.el-table tr:hover > td) {
  background: var(--surface-hover);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header h3 {
  margin: 0;
  font-size: 14px;
  font-weight: 800;
  color: var(--text-strong);
}

.product-count {
  color: var(--text-subtle);
  font-size: 13px;
}

.product-link {
  color: var(--color-info);
  text-decoration: none;
}
.product-link:hover { text-decoration: underline; }

.log-icon { cursor: pointer; color: var(--color-info); }
.log-badge :deep(.el-badge__content) {
  background: var(--color-info);
  border: none;
}

.expand-hint {
  color: var(--text-subtle);
  font-size: 12px;
  text-align: center;
  padding: 16px;
}

.product-detail {
  padding: 16px;
  background: var(--surface-muted);
}

.detail-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
  flex-wrap: wrap;
  gap: 8px;
}
.detail-title { font-weight: 800; color: var(--text-strong); }
.detail-chart { margin-bottom: 16px; overflow-x: auto; }
.chart-metrics { display: flex; gap: 24px; padding-bottom: 8px; }
.chart-metric { min-width: 150px; }
.day-labels {
  display: flex;
  gap: 6px;
  margin-top: 4px;
}
.day-labels span {
  font-size: 9px;
  color: var(--text-subtle);
  flex: 1;
  text-align: center;
  min-width: 20px;
}
.detail-table { overflow-x: auto; }
.detail-data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.detail-data-table th,
.detail-data-table td {
  padding: 8px 12px;
  text-align: right;
  border-bottom: 1px solid var(--border-subtle);
}
.detail-data-table th {
  background: var(--surface-muted);
  font-weight: 800;
  color: var(--text-subtle);
}
.detail-data-table td:first-child,
.detail-data-table th:first-child { text-align: left; }

.log-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 16px;
}
.log-header h4 {
  margin: 0;
  font-weight: 800;
  color: var(--text-strong);
}
.log-item { padding: 4px 0; }
.log-content { font-size: 14px; color: var(--text-strong); }
.log-meta {
  font-size: 12px;
  color: var(--text-subtle);
  margin-top: 4px;
}

.expand-detail { padding: 8px 0; }
.expand-row { display: flex; align-items: center; flex-wrap: wrap; }
.expand-cell {
  flex: 1;
  min-width: 60px;
  text-align: center;
  padding: 4px 8px;
}
.expand-cell.shop-cell {
  min-width: 100px;
  text-align: left;
}
.shop-name-item { font-size: 12px; color: var(--text-strong); }
.shop-sep { color: var(--text-subtle); margin: 0 2px; }
.shop-metric-item { font-size: 12px; color: var(--text-main); }

.expand-daily-row { display: flex; flex-direction: column; gap: 4px; }
.daily-item {
  display: flex;
  align-items: center;
  font-size: 12px;
  background: var(--surface-muted);
  border-radius: var(--radius-md);
  padding: 4px 8px;
}
.daily-date { width: 80px; color: var(--text-subtle); }
.daily-shop {
  width: 100px;
  font-weight: 700;
  color: var(--text-strong);
}
.daily-metric {
  flex: 1;
  text-align: right;
  color: var(--text-main);
}

.log-badge-small {
  background: var(--color-brand);
  color: #fff;
  padding: 2px 6px;
  border-radius: 10px;
  font-size: 10px;
  margin-left: 8px;
}

@media (max-width: 980px) {
  .filter-bar { grid-template-columns: 1fr; }
  .metric-matrix {
    grid-template-columns: 112px minmax(0, 1fr);
  }
  .matrix-scroll-content {
    min-width: 540px;
  }
  .matrix-scroll-row {
    grid-template-columns: repeat(3, minmax(180px, 1fr));
  }
}

@media (max-width: 768px) {
  .filter-bar {
    display: grid !important;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: stretch;
    gap: 6px;
    padding: 8px;
  }

  .filter-item,
  .filter-item.flex-1 {
    width: 100%;
    min-width: 0 !important;
    padding: 0 !important;
  }

  .quick-filter,
  .date-filter,
  .product-filter,
  .query-button {
    grid-column: 1 / -1;
  }

  .owner-filter {
    grid-column: 1;
  }

  .filter-bar :deep(.el-button-group) {
    width: 100% !important;
    display: grid !important;
    grid-template-columns: repeat(4, minmax(0, 1fr)) !important;
  }

  .filter-bar :deep(.el-button-group .el-button),
  .query-button {
    width: auto !important;
    min-height: 34px !important;
    height: 34px !important;
    padding: 0 6px !important;
    font-size: 12px !important;
    white-space: nowrap !important;
  }

  .filter-bar :deep(.el-select),
  .filter-bar :deep(.el-date-editor),
  .filter-bar :deep(.el-input) {
    width: 100% !important;
    height: 34px !important;
    min-height: 34px !important;
    font-size: 12px !important;
  }

  .filter-bar :deep(.el-input__wrapper),
  .filter-bar :deep(.el-select__wrapper),
  .filter-bar :deep(.el-date-editor.el-input__wrapper) {
    min-height: 34px !important;
    padding-inline: 8px !important;
  }

  .metric-matrix {
    margin-inline: -2px;
    grid-template-columns: 92px minmax(0, 1fr);
  }

  .matrix-scroll-content {
    min-width: 600px;
  }

  .matrix-scroll-row {
    grid-template-columns: repeat(3, 200px);
  }

  .matrix-metric-heading,
  .matrix-section-heading,
  .matrix-metric-label,
  .matrix-value-cell {
    padding: 10px;
  }

  .matrix-value {
    font-size: 15px;
  }

  .matrix-metric-heading,
  .matrix-metric-label {
    box-shadow: 8px 0 12px -12px rgba(15, 23, 42, 0.35);
  }

  .card-header,
  .detail-toolbar,
  .log-header {
    flex-direction: column;
    align-items: flex-start;
    gap: 8px;
  }

  .product-detail {
    padding: 10px;
  }
}
</style>
