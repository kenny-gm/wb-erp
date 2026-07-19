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
      <div class="filter-item">
        <el-button-group>
          <el-button :type="quickType === 'today' ? 'primary' : ''" @click="setQuickDate('today')">今天</el-button>
          <el-button :type="quickType === 'yesterday' ? 'primary' : ''" @click="setQuickDate('yesterday')">昨日</el-button>
          <el-button :type="quickType === '7d' ? 'primary' : ''" @click="setQuickDate('7d')">7天</el-button>
          <el-button :type="quickType === '30d' ? 'primary' : ''" @click="setQuickDate('30d')">30天</el-button>
        </el-button-group>
      </div>
      <div class="filter-item">
        <el-date-picker v-model="filters.dateRange" type="daterange" range-separator="至" start-placeholder="开始日期" end-placeholder="结束日期" format="YYYY-MM-DD" value-format="YYYY-MM-DD" @change="handleDateChange" style="width: 240px" />
      </div>
      <div class="filter-item">
        <el-select v-model="filters.owner" placeholder="全部负责人" clearable style="width: 120px">
          <el-option v-for="o in owners" :key="o" :label="o" :value="o" />
        </el-select>
      </div>
      <div class="filter-item flex-1">
        <el-select v-model="filters.productId" placeholder="全部产品" clearable filterable style="width: 100%">
          <el-option v-for="p in uniqueProducts" :key="p" :label="p" :value="p" />
        </el-select>
      </div>
      <el-button type="primary" @click="fetchData">查询</el-button>
    </div>

    <section class="metric-matrix-section">
      <div class="metric-matrix">
        <div class="matrix-row matrix-header-row">
          <div class="matrix-metric-heading">指标</div>
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

        <div v-for="card in metricCards" :key="card.key" class="matrix-row">
          <div class="matrix-metric-label">
            <el-icon><component :is="card.icon" /></el-icon>
            <span>{{ card.label }}</span>
          </div>
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
.dashboard { padding: 16px; background: #f5f7fa; min-height: 100vh; }
.filter-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; padding: 12px 16px; background: #fff; border-radius: 8px; }
.data-info-bar { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 12px; padding: 8px 16px; background: #f0f9eb; border: 1px solid #e1f3d8; border-radius: 6px; font-size: 13px; align-items: center; }
.data-info-item { display: flex; align-items: center; gap: 4px; color: #606266; }
.data-info-warning { color: #e6a23c; font-weight: 500; }
.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-item.flex-1 { flex: 1; min-width: 150px; }
.metric-matrix-section { margin-bottom: 18px; }
.metric-matrix { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow-x: auto; box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04); }
.matrix-row { display: grid; grid-template-columns: 150px repeat(3, minmax(220px, 1fr)); min-width: 850px; border-top: 1px solid #eef2f7; }
.matrix-row:first-child { border-top: none; }
.matrix-header-row { background: #f8fafc; }
.matrix-metric-heading { padding: 14px 16px; font-size: 13px; font-weight: 700; color: #475569; border-right: 1px solid #e5e7eb; }
.matrix-section-heading { padding: 12px 14px; border-right: 1px solid #e5e7eb; min-width: 0; }
.matrix-section-heading:last-child { border-right: none; }
.matrix-section-title { font-size: 14px; font-weight: 700; color: #0f172a; line-height: 1.2; }
.matrix-section-subtitle { margin-top: 3px; font-size: 12px; color: #64748b; line-height: 1.25; }
.section-shop-filter { width: 260px; flex-shrink: 0; }
.matrix-section-heading .section-shop-filter { width: 100%; margin-top: 10px; }
.matrix-metric-label { display: flex; align-items: center; gap: 8px; padding: 14px 16px; min-height: 74px; border-right: 1px solid #e5e7eb; font-size: 13px; font-weight: 600; color: #334155; background: #fbfdff; }
.matrix-value-cell { padding: 12px 14px; min-height: 74px; border-right: 1px solid #e5e7eb; }
.matrix-value-cell:last-child { border-right: none; }
.matrix-value-line { display: flex; align-items: center; justify-content: space-between; gap: 10px; min-height: 24px; }
.matrix-value { min-width: 0; font-size: 16px; font-weight: 700; color: #0f172a; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.matrix-change { flex-shrink: 0; font-size: 12px; font-weight: 600; padding: 3px 8px; border-radius: 999px; background-color: #f8fafc; white-space: nowrap; }
.matrix-change.positive { color: #10b981; background-color: rgba(16, 185, 129, 0.1); }
.matrix-change.negative { color: #ef4444; background-color: rgba(239, 68, 68, 0.08); }
.matrix-chart { margin-top: 8px; padding-top: 8px; border-top: 1px solid #f1f5f9; }
.matrix-line-chart { width: 100%; height: 32px; display: block; }
.metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 16px; align-items: stretch; }
@media (max-width: 1200px) { .metrics-grid { grid-template-columns: repeat(3, 1fr); gap: 12px; } }
@media (max-width: 768px) { 
  .filter-bar { flex-direction: column; align-items: stretch; gap: 8px; padding: 12px; }
  .filter-bar .filter-item { width: 100%; }
  .filter-bar .filter-item .el-button-group { width: 100%; display: flex; }
  .filter-bar .filter-item .el-button-group .el-button { flex: 1; padding: 8px 4px; font-size: 12px; }
  .filter-bar .filter-item .el-date-picker { width: 100% !important; }
  .filter-bar .filter-item .el-select { width: 100% !important; }
  .filter-bar .flex-1 { width: 100%; }
  .filter-bar > .el-button { width: 100%; margin-top: 8px; }
  .matrix-row { grid-template-columns: 112px repeat(3, minmax(170px, 1fr)); min-width: 640px; }
  .matrix-metric-heading,
  .matrix-metric-label {
    position: sticky;
    left: 0;
    z-index: 3;
    box-shadow: 8px 0 12px rgba(15, 23, 42, 0.06);
  }
  .matrix-metric-heading {
    background: #f8fafc;
    z-index: 4;
  }
  .matrix-metric-label {
    background: #fbfdff;
  }
  .matrix-metric-heading,
  .matrix-metric-label { padding: 12px 10px; }
  .matrix-section-heading,
  .matrix-value-cell { padding: 10px; }
  .matrix-value-line { align-items: flex-start; flex-direction: column; gap: 4px; }
  .matrix-value { font-size: 14px; }
  .matrix-change { font-size: 10px; padding: 2px 6px; }
  .section-shop-filter { width: 100%; }
  .metrics-grid { grid-template-columns: repeat(2, 1fr); gap: 8px; align-items: stretch; }
  .metric-value { font-size: 16px; min-height: 20px; line-height: 1.2; }
  .metric-label { font-size: 11px; }
  .metric-change { font-size: 9px; padding: 2px 6px; }
  .metric-header { min-height: 20px !important; margin-bottom: 4px !important; }
  .metric-card { padding: 12px 10px 10px; border-radius: 12px; }
}
.metric-card { background: #fff; border-radius: 20px; padding: 18px 18px 16px; box-shadow: 0 4px 12px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03); transition: transform 0.2s ease, box-shadow 0.2s ease; display: flex; flex-direction: column; }
.metric-card:hover { transform: translateY(-2px); box-shadow: 0 12px 24px rgba(0,0,0,0.08); }
.metric-header { position: relative !important; display: flex !important; justify-content: space-between !important; align-items: center !important; margin-bottom: 0 !important; gap: 8px !important; flex-wrap: nowrap !important; overflow: visible !important; min-height: 24px !important; height: auto !important; flex-shrink: 0 !important; width: 100% !important; box-sizing: border-box !important; }
.metric-label { display: inline-flex !important; align-items: center !important; gap: 6px; font-size: 14px; font-weight: 500; color: #5b6e8c; flex-shrink: 0 !important; white-space: nowrap !important; min-width: 0 !important; }
.metric-value { display: flex; align-items: center; justify-content: flex-start; width: 100%; font-size: 16px; font-weight: 700; color: #0f172a; line-height: 1.1; letter-spacing: -0.02em; word-break: keep-all; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-height: 24px; flex-shrink: 0; }
.metric-change { position: absolute !important; right: 0 !important; top: 50% !important; transform: translateY(-50%) !important; font-size: 12px; font-weight: 600; padding: 4px 10px; border-radius: 30px; white-space: nowrap; background-color: #f8fafc; flex-shrink: 0 !important; margin-left: auto !important; }
.metric-change.positive { color: #10b981; background-color: rgba(16, 185, 129, 0.1); }
.metric-change.negative { color: #ef4444; background-color: rgba(239, 68, 68, 0.08); }
.chart-area { width: 100%; margin-top: 6px; padding-top: 12px; border-top: 1px solid #eef2ff; }
.line-chart { width: 100%; height: 54px; display: block; }
.product-table-card { margin-bottom: 16px; }
.card-header { display: flex; justify-content: space-between; align-items: center; }
.card-header h3 { margin: 0; font-size: 16px; }
.product-count { color: #909399; font-size: 13px; }
.product-link { color: #409eff; text-decoration: none; }
.product-link:hover { text-decoration: underline; }
.el-table .cell { white-space: nowrap !important; overflow: visible !important; text-overflow: unset !important; max-width: none !important; }
.el-table td { overflow: visible !important; white-space: nowrap !important; }
.el-table .el-table__body-wrapper { overflow: visible !important; }
.el-table__cell { overflow: visible !important; white-space: nowrap !important; }
.product-table-card .el-table th .cell,
.product-table-card .el-table td .cell { white-space: nowrap !important; overflow: visible !important; text-overflow: unset !important; }
/* 店铺列专用样式 */
.shop-column .cell,
.owner-column .cell { white-space: nowrap !important; overflow: visible !important; text-overflow: unset !important; min-width: 0 !important; }
.log-icon { cursor: pointer; color: #8b5cf6; }
.log-badge :deep(.el-badge__content) { background: #8b5cf6; border: none; }
.expand-hint { color: #909399; font-size: 12px; text-align: center; padding: 16px; }
.product-detail { padding: 16px; background: #f9fafb; }
.detail-toolbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; flex-wrap: wrap; gap: 8px; }
.detail-title { font-weight: bold; color: #303133; }
.detail-chart { margin-bottom: 16px; overflow-x: auto; }
.chart-metrics { display: flex; gap: 24px; padding-bottom: 8px; }
.chart-metric { min-width: 150px; }
.metric-header { position: relative !important; font-size: 12px; color: #606266; margin-bottom: 8px; font-weight: bold; }
.mini-line-chart { width: 100%; height: 40px; }
.day-labels { display: flex; gap: 6px; margin-top: 4px; }
.day-labels span { font-size: 9px; color: #909399; flex: 1; text-align: center; min-width: 20px; }
.detail-table { overflow-x: auto; }
.detail-data-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.detail-data-table th, .detail-data-table td { padding: 8px 12px; text-align: right; border-bottom: 1px solid #eee; }
.detail-data-table th { background: #f5f7fa; font-weight: bold; }
.detail-data-table td:first-child, .detail-data-table th:first-child { text-align: left; }
.log-badge-small { background: #8b5cf6; color: #fff; padding: 2px 6px; border-radius: 10px; font-size: 10px; margin-left: 8px; }
.log-header { display: flex; justify-content: space-between; margin-bottom: 16px; }
.log-header h4 { margin: 0; }
.log-item { padding: 4px 0; }
.log-content { font-size: 14px; }
.log-meta { font-size: 12px; color: #909399; margin-top: 4px; }
.metric-header .el-icon { display: inline-block !important; vertical-align: middle !important; }

/* 展开详情 - 店铺汇总 */
/* 展开详情 */
.expand-detail { padding: 8px 0; }
.expand-row { display: flex; align-items: center; flex-wrap: wrap; }
.expand-cell { flex: 1; min-width: 60px; text-align: center; padding: 4px 8px; }
.expand-cell.shop-cell { min-width: 100px; text-align: left; }
.shop-name-item { font-size: 12px; color: #303133; }
.shop-sep { color: #c0c4cc; margin: 0 2px; }
.shop-metric-item { font-size: 12px; color: #606266; }
.expand-daily-row { display: flex; flex-direction: column; gap: 4px; }
.daily-item { display: flex; align-items: center; font-size: 12px; background: #f9fafb; border-radius: 4px; padding: 4px 8px; }
.daily-date { width: 80px; color: #909399; }
.daily-shop { width: 100px; font-weight: 600; color: #303133; }
.daily-metric { flex: 1; text-align: right; color: #606266; }
.expand-hint { color: #c0c4cc; font-size: 12px; }

/* Demo-aligned operations density overrides */
.dashboard { padding: 16px; background: var(--surface-page); }
.filter-bar,
.data-info-bar {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-panel);
  box-shadow: var(--shadow-sm);
}
.filter-bar { gap: 8px 10px; margin-bottom: 12px; padding: 10px; }
.data-info-bar {
  background: var(--surface-panel);
  color: var(--text-main);
  gap: 10px;
  margin-bottom: 12px;
  padding: 8px 10px;
}
.data-info-warning { color: var(--color-warning); }
.metric-matrix-section { margin-bottom: 12px; }
.metric-matrix {
  border-color: var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
}
.matrix-row { border-top-color: var(--border-subtle); }
.matrix-header-row,
.matrix-metric-label { background: var(--surface-muted); }
.matrix-metric-heading,
.matrix-section-heading,
.matrix-metric-label,
.matrix-value-cell { border-right-color: var(--border-subtle); }
.matrix-section-title,
.matrix-value { color: var(--text-strong); }
.matrix-section-subtitle,
.matrix-metric-label { color: var(--text-subtle); }
.matrix-change.positive,
.metric-change.positive { color: var(--color-success); background-color: var(--color-success-soft); }
.matrix-change.negative,
.metric-change.negative { color: var(--color-danger); background-color: var(--color-danger-soft); }
.metric-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 12px;
}
.metric-card:hover { transform: none; box-shadow: var(--shadow-md); }
.metric-label { color: var(--text-subtle); font-weight: 650; letter-spacing: 0; }
.metric-value { color: var(--text-strong); letter-spacing: 0; }
.chart-area,
.matrix-chart { border-top-color: var(--border-subtle); }
.product-detail,
.detail-data-table th,
.daily-item { background: var(--surface-muted); }
.detail-data-table th,
.detail-data-table td { border-bottom-color: var(--border-subtle); }
.log-icon { color: var(--color-brand); }
.log-badge-small { background: var(--color-brand); color: #fff; }
</style>
