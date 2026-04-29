<template>
  <div class="product-sales-table">
    <!-- 表格 -->
    <div class="table-container">
      <div class="table-scroll">
        <table class="tree-table">
          <thead>
            <tr>
              <th class="col-toggle"></th>
              <th class="col-manager">负责人</th>
              <th class="col-product">产品名称</th>
              <th class="col-log">日志</th>
              <th class="col-shop">店铺</th>
              <th class="col-num sortable" @click="toggleSort('orders')">
                订单数 <span class="sort-icon" v-if="sortField === 'orders'">{{ sortDir === 'desc' ? '↓' : '↑' }}</span>
              </th>
              <th class="col-money sortable" @click="toggleSort('sales')">
                销售额 <span class="sort-icon" v-if="sortField === 'sales'">{{ sortDir === 'desc' ? '↓' : '↑' }}</span>
              </th>
              <th class="col-money">广告费</th>
              <th class="col-rate">广告占比</th>
              <th class="col-num">访客数</th>
              <th class="col-num">加购数</th>
              <th class="col-rate">加购率</th>
              <th class="col-rate">转化率</th>
              <th class="col-id">产品ID</th>
              <th class="col-sku">产品SKU</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="row in visibleRows" :key="row.id">
              <tr :class="getRowClass(row)" @click="row._hasChildren && toggleRow(row)">
                <td class="col-toggle">
                  <span v-if="row._hasChildren" :class="['toggle-icon', expandedIds.has(row.id) ? 'expanded' : '']" @click.stop="toggleRow(row)">
                    {{ expandedIds.has(row.id) ? '▼' : '▶' }}
                  </span>
                </td>
                <td :class="{ 'empty-cell': row.type !== 'top' }">{{ row.type === 'top' ? row.manager : '-' }}</td>
                <td :class="{ 'empty-cell': row.type !== 'top' }">{{ row.type === 'top' ? row.product_name : '-' }}</td>
                <td>
                  <span v-if="row.type === 'date'" :class="['log-icon', hasLogForDate(row)]" @click.stop="openLogDialog(row)">
                    <el-icon><Document /></el-icon>
                  </span>
                </td>
                <td>{{ row.shop_name || '-' }}</td>
                <td class="num">{{ formatNumber(row.orders) }}</td>
                <td class="num">{{ formatNumber(row.sales) }}{{ row.currency === 'RUB' ? '₽' : '' }}</td>
                <td class="num">{{ formatNumber(row.ad_cost) }}</td>
                <td class="num" :class="getRateClass(row.ad_ratio, 'ad_ratio')">{{ row.ad_ratio != null ? row.ad_ratio + '%' : '-' }}</td>
                <td class="num">{{ formatNumber(row.visitors) }}</td>
                <td class="num">{{ formatNumber(row.add_to_cart) }}</td>
                <td class="num" :class="getRateClass(row.cart_rate, 'cart_rate')">{{ row.cart_rate != null ? row.cart_rate + '%' : '-' }}</td>
                <td class="num" :class="getRateClass(row.conversion_rate, 'conversion_rate')">{{ row.conversion_rate != null ? row.conversion_rate + '%' : '-' }}</td>
                <td>
                  <a v-if="row.nm_id" :href="'https://www.wildberries.ru/catalog/' + row.nm_id + '/detail.aspx'" target="_blank" class="product-link">{{ row.nm_id }}</a>
                  <span v-else class="empty-cell">-</span>
                </td>
                <td>{{ row.sku || '-' }}</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="loading" class="loading-mask">
      <span>加载中...</span>
    </div>

    <!-- 日志弹窗 -->
    <el-dialog v-model="logDialogVisible" title="每日日志" width="700px" :append-to-body="true" style="max-width:95vw">
      <div v-if="currentLogRow" class="log-header" style="margin-bottom:12px">
        <p><strong>店铺：</strong>{{ getShopName(currentLogRow.shop_id, null) }}</p>
        <p><strong>产品：</strong>{{ currentLogRow.product_name || currentLogRow.product_id }}</p>
        <p><strong>日期：</strong>{{ currentLogRow.shop_name }}</p>
      </div>
      <div v-if="logList.length > 0" class="log-vertical-table">
        <table>
          <tbody>
            <tr>
              <th>日期</th>
              <td v-for="(log, idx) in logList" :key="log.id || idx">{{ log.date }}</td>
            </tr>
            <tr>
              <th>标题</th>
              <td v-for="(log, idx) in logList" :key="log.id || idx">{{ log.title || '-' }}</td>
            </tr>
            <tr>
              <th>操作类型</th>
              <td v-for="(log, idx) in logList" :key="log.id || idx">{{ getActionTypeText(log.action_type) }}</td>
            </tr>
            <tr>
              <th>内容</th>
              <td v-for="(log, idx) in logList" :key="log.id || idx">
                <div class="content-cell">{{ log.detail || '-' }}</div>
              </td>
            </tr>
            <tr>
              <th>效果</th>
              <td v-for="(log, idx) in logList" :key="log.id || idx">
                <el-tag v-if="log.effect" :type="getEffectType(log.effect)" size="small">{{ getEffectText(log.effect) }}</el-tag>
                <span v-else>-</span>
              </td>
            </tr>
            <tr>
              <th>效果分析</th>
              <td v-for="(log, idx) in logList" :key="log.id || idx">
                <div :class="log.effect_analysis ? 'effect-analysis-cell' : ''">{{ log.effect_analysis || '-' }}</div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="logList.length === 0" style="text-align:center;color:#909399;padding:32px">暂无日志记录</div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import axios from 'axios'
import { Document } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  startDate: { type: String, default: '' },
  endDate: { type: String, default: '' },
  selectedShop: { type: [String, Number], default: '' },
  selectedOwner: { type: String, default: '' },
  selectedProduct: { type: [String, Number], default: '' },
  quickType: { type: String, default: '' }
})

const emit = defineEmits(['update:startDate', 'update:endDate', 'update:selectedShop', 'update:selectedOwner', 'update:quickType'])

const loading = ref(false)
const shops = ref([])
const allData = ref([])
const expandedIds = ref(new Set())
const shopDailyData = ref({})  // 存储店铺每日数据
const sortField = ref('orders')
const dateLogsMap = ref({})  // 存储 {productId_shopId_date: true} 是否有日志
const sortDir = ref('desc')
const logDialogVisible = ref(false)
const currentLogRow = ref(null)
const logList = ref([])
const newLogContent = ref('')
const thresholds = ref({})  // 存储预警阈值

async function fetchThresholds() {
  try {
    const resp = await axios.get('/api/metric-thresholds/')
    const data = resp.data || []
    thresholds.value = {}
    data.forEach(t => {
      thresholds.value[t.metric_name] = t
    })
  } catch (e) {
  }
}

function getActionTypeText(type) {
  const map = { adjust_ad: "调整广告", update_price: "优化价格", optimize_page: "优化页面", ignore: "忽略", other: "其他" }
  return map[type] || type || "其他"
}

function getEffectType(effect) {
  const map = { positive: "success", neutral: "info", negative: "danger", pending: "warning" }
  return map[effect] || "info"
}

function getEffectText(effect) {
  const map = { positive: "正向", neutral: "中性", negative: "负向", pending: "待追踪" }
  return map[effect] || effect || "待追踪"
}

function getShopName(shopId, shopName) {
  if (shopName && shopName !== currentLogRow.value?.date) return shopName
  if (!shopId) return "未知"
  const shop = shops.value.find(s => s.id === shopId)
  return shop ? shop.name : "未知"
}

function getRateClass(rate, metric) {
  const t = thresholds.value[metric]
  if (!t || !rate || !t.is_active) return ''
  const val = parseFloat(rate)
  // 广告占比：低值=好（花费少），高值=差（花费多）
  if (metric === 'ad_ratio') {
    if (t.danger_threshold && val >= t.danger_threshold) return 'rate-danger'
    if (t.warning_threshold && val >= t.warning_threshold) return 'rate-warning'
    return 'rate-success'
  }
  // 加购率/转化率：高值=好，低值=差
  if (t.danger_threshold && val <= t.danger_threshold) return 'rate-danger'
  if (t.warning_threshold && val <= t.warning_threshold) return 'rate-warning'
  return 'rate-success'
}

async function openLogDialog(row) {
  if (shops.value.length === 0) await fetchShops()
  currentLogRow.value = row
  logDialogVisible.value = true
  await fetchLogs()
}

async function fetchLogs() {
  if (!currentLogRow.value) return
  try {
    // 日期存在 shop_name 字段（日期行的数据结构）
    const logDate = currentLogRow.value.shop_name || currentLogRow.value.date
    const params = {
      product_id: currentLogRow.value.product_id,
      shop_id: currentLogRow.value.shop_id,
      start_date: logDate,
      end_date: logDate
    }
    const resp = await axios.get('/api/operation-logs/', { params })
    logList.value = resp.data || []
    // 记录该 product+shop+date 组合有日志
    if (logList.value.length > 0) {
      const key = `${currentLogRow.value.product_id}_${logDate}`
      dateLogsMap.value[key] = true
    }
  } catch (e) {
    logList.value = []
  }
}

function hasLogForDate(row) {
  if (row.type !== 'date') return ''
  const map = dateLogsMap.value
  // 日期存储在 shop_name 字段，shop_id 可能不匹配，用 product_id + date
  const key = `${row.product_id}_${row.shop_name}`
  return map[key] ? 'has-log' : 'no-log'
}

async function addLog(content) {
  if (!currentLogRow.value || !content) return
  try {
    await axios.post('/api/operation-logs/', {
      product_id: currentLogRow.value.product_id,
      shop_id: currentLogRow.value.shop_id,
      date: currentLogRow.value.date,
      action: content
    })
    ElMessage.success('日志添加成功')
    newLogContent.value = ''
    await fetchLogs()
  } catch (e) {
    ElMessage.error('添加日志失败')
  }
}

function handleAddLog() {
  if (!newLogContent.value.trim()) {
    ElMessage.warning('请输入日志内容')
    return
  }
  addLog(newLogContent.value)
}

function getLogClass(content) {
  if (!content) return ''
  const c = content.toLowerCase()
  if (c.includes('问题') || c.includes('异常') || c.includes('失败')) return 'log-danger'
  if (c.includes('优化') || c.includes('调整') || c.includes('改进')) return 'log-success'
  if (c.includes('备注') || c.includes('观察')) return 'log-warning'
  return ''
}

function toggleSort(field) {
  if (sortField.value === field) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortField.value = field
    sortDir.value = 'desc'
  }
}

const isDateRange = computed(() => {
  if (!props.startDate || !props.endDate) return false
  const days = Math.ceil((new Date(props.endDate) - new Date(props.startDate)) / 86400000) + 1
  return days > 1
})

// 构建树形数据
function buildTreeData(apiData, isRange) {
  // 按 product_name 分组（同一产品名称在不同店铺的数据合并）
  const productGroups = {}
  apiData.forEach(item => {
    const key = item.product_name  // 按产品名称分组
    if (!productGroups[key]) {
      productGroups[key] = {
        product_id: item.product_id,
        nm_id: item.nm_id,
        sku: item.sku,
        product_name: item.product_name,
        owner: item.owner,
        shops: []
      }
    }
    // 添加店铺数据
    productGroups[key].shops.push({
      shop_id: item.shop_id,
      shop_name: item.shop_name,
      nm_id: item.nm_id,
      product_id: item.product_id,
      sku: item.sku,
      currency: item.currency,
      orders: item.orders || 0,
      sales: item.sales || 0,
      ad_cost: item.ad_cost || 0,
      visitors: item.visitors || 0,
      add_to_cart: item.add_to_cart || 0
    })
  })
  
  const nodes = []
  let idSeq = 0
  
  Object.values(productGroups).forEach(group => {
    // 计算产品汇总
    const totalStats = {
      orders: 0, sales: 0, ad_cost: 0, visitors: 0, add_to_cart: 0
    }
    group.shops.forEach(s => {
      totalStats.orders += s.orders
      totalStats.sales += s.sales
      totalStats.ad_cost += s.ad_cost
      totalStats.visitors += s.visitors
      totalStats.add_to_cart += s.add_to_cart
    })
    
    // 顶级：负责人+产品
    const topNode = {
      id: `top_${idSeq++}`,
      type: 'top',
      manager: group.owner,
      product_name: group.product_name,
      shop_name: '合计',
      orders: totalStats.orders,
      sales: totalStats.sales,
      ad_cost: totalStats.ad_cost,
      visitors: totalStats.visitors,
      add_to_cart: totalStats.add_to_cart,
      ad_ratio: totalStats.sales > 0 ? ((totalStats.ad_cost / totalStats.sales) * 100).toFixed(2) : '0.00',
      cart_rate: totalStats.visitors > 0 ? ((totalStats.add_to_cart / totalStats.visitors) * 100).toFixed(2) : '0.00',
      conversion_rate: totalStats.visitors > 0 ? ((totalStats.orders / totalStats.visitors) * 100).toFixed(2) : '0.00',
      nm_id: null,
      sku: null,
      currency: null,
      _children: [],
      _hasChildren: group.shops.length > 0
    }
    
    // 添加子节点：各店铺
    group.shops.forEach((shop, shopIdx) => {
      const shopNodeId = `shop_${idSeq}`
      shop._nodeId = shopNodeId
      const shopNode = {
        id: shopNodeId,
        type: 'shop',
        manager: null,
        product_name: null,
        shop_name: shop.shop_name,
        shop_id: shop.shop_id,
        currency: shop.currency,
        orders: shop.orders,
        sales: shop.sales,
        ad_cost: shop.ad_cost,
        visitors: shop.visitors,
        add_to_cart: shop.add_to_cart,
        ad_ratio: shop.sales > 0 ? ((shop.ad_cost / shop.sales) * 100).toFixed(2) : '0.00',
        cart_rate: shop.visitors > 0 ? ((shop.add_to_cart / shop.visitors) * 100).toFixed(2) : '0.00',
        conversion_rate: shop.visitors > 0 ? ((shop.orders / shop.visitors) * 100).toFixed(2) : '0.00',
        nm_id: shop.nm_id,
        product_id: shop.product_id,
        sku: shop.sku,
        _children: [],
        _hasChildren: isRange
      }
      
      // 如果已有每日数据，添加到子节点
      if (shopDailyData.value[shopNodeId]) {
        shopNode._children = shopDailyData.value[shopNodeId].map(d => ({
          id: `date_${idSeq++}_${d.date}`,
          type: 'date',
          manager: null,
          product_name: group.product_name,
          shop_name: d.date,
          shop_id: shop.shop_id,
          product_id: shop.product_id,
          currency: shop.currency,
          orders: d.orders,
          sales: d.sales,
          ad_cost: d.ad_cost,
          visitors: d.visitors,
          add_to_cart: d.add_to_cart,
          ad_ratio: d.ad_ratio,
          cart_rate: d.cart_rate,
          conversion_rate: d.conversion_rate,
          nm_id: null,
          sku: null,
          _children: [],
          _hasChildren: false
        }))
      }
      
      topNode._children.push(shopNode)
      idSeq++
    })
    
    nodes.push(topNode)
  })
  
  return nodes
}

function flattenVisible(nodes, expanded) {
  const result = []
  nodes.forEach(node => {
    result.push(node)
    if (expanded.has(node.id) && node._children && node._children.length > 0) {
      result.push(...flattenVisible(node._children, expanded))
    }
  })
  return result
}

const visibleRows = computed(() => {
  const tree = buildTreeData(allData.value, isDateRange.value)
  // 对顶级节点排序
  tree.sort((a, b) => {
    const aVal = a[sortField.value] || 0
    const bVal = b[sortField.value] || 0
    return sortDir.value === 'desc' ? bVal - aVal : aVal - bVal
  })
  return flattenVisible(tree, expandedIds.value)
})

function getRowClass(row) {
  const classes = [`level-${row.type}`]
  if (row._hasChildren) {
    classes.push('parent-row')
  }
  return classes.join(' ')
}

async function toggleRow(row) {
  if (!row._hasChildren) return
  const newSet = new Set(expandedIds.value)
  if (newSet.has(row.id)) {
    newSet.delete(row.id)
  } else {
    newSet.add(row.id)
    // 如果是店铺节点且需要获取每日数据
    if (row.type === 'shop' && isDateRange.value && !shopDailyData.value[row.id]) {
      await fetchShopDailyData(row)
    }
  }
  expandedIds.value = newSet
}

async function fetchShopDailyData(shopNode) {
  try {
    const resp = await axios.post('/api/dashboard/trend/', {
      start_date: props.startDate,
      end_date: props.endDate,
      shop_ids: [shopNode.shop_id],
      product_ids: [shopNode.product_id]
    })
    const data = resp.data || []
    shopDailyData.value[shopNode.id] = data.map(d => ({
      date: d.date,
      orders: d.orders || 0,
      sales: d.sales || 0,
      ad_cost: d.ad_cost || 0,
      visitors: d.visitors || 0,
      add_to_cart: d.cart || 0,
      cart_rate: d.visitors > 0 ? ((d.cart || 0) / d.visitors * 100).toFixed(2) : '0.00',
      conversion_rate: d.visitors > 0 ? ((d.orders || 0) / d.visitors * 100).toFixed(2) : '0.00',
      ad_ratio: d.sales > 0 ? ((d.ad_cost || 0) / d.sales * 100).toFixed(2) : '0.00'
    }))
  } catch (e) {
  }
}

function formatNumber(n) {
  if (n == null || n === '-') return '-'
  const rounded = Math.round(Number(n) * 100) / 100
  return rounded.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
}

async function fetchShops() {
  try {
    shops.value = (await axios.get('/api/shops/')).data
  } catch (e) {
  }
}

async function fetchData() {
  loading.value = true
  try {
    const resp = await axios.post('/api/dashboard/products/', {
      start_date: props.startDate,
      end_date: props.endDate,
      shop_ids: props.selectedShop ? [props.selectedShop] : undefined,
      owners: props.selectedOwner ? [props.selectedOwner] : undefined,
      product_name: props.selectedProduct || undefined
    })
    allData.value = resp.data.items || []
  } catch (e) {
  } finally {
    loading.value = false
  }
}

watch([() => props.startDate, () => props.endDate, () => props.selectedShop, () => props.selectedOwner, () => props.selectedProduct], () => {
  fetchData()
  prefetchLogsForDateRange()
})

onMounted(() => {
  fetchShops()
  fetchThresholds()
  fetchData()
})

async function prefetchLogsForDateRange() {
  // 预获取日期范围内的所有日志，用于显示颜色标记
  if (!props.startDate || !props.endDate) {
    return
  }
  try {
    const resp = await axios.get('/api/operation-logs/', {
      params: {
        start_date: props.startDate,
        end_date: props.endDate,
        limit: 500
      }
    })
    // 按 product_id + shop_id + date 建立索引
    const logs = resp.data || []
    logs.forEach(log => {
      // shop_id 可能为 null，只用 product_id + date 作为 key
      const key = `${log.product_id}_${log.date}`
      dateLogsMap.value[key] = true
    })
  } catch (e) {
  }
}
</script>

<style scoped>
.product-sales-table {
  position: relative;
}

.table-container {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  overflow: hidden;
}

.table-scroll {
  max-width: 100%;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
}

@media (max-width: 768px) {
  .table-scroll {
    max-height: 60vh;
    overflow: auto;
  }
  .tree-table th, .tree-table td {
    padding: 6px 8px;
    font-size: 12px;
  }
  .tree-table th {
    font-size: 11px;
  }
}

.tree-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}

.tree-table th,
.tree-table td {
  padding: 8px 10px;
  border-bottom: 1px solid #ebeef5;
  white-space: nowrap;
}

.tree-table th {
  background: #fafafa;
  color: #909399;
  font-weight: 600;
  font-size: 12px;
  position: sticky;
  top: 0;
  z-index: 10;
}

.tree-table th.sortable {
  cursor: pointer;
  user-select: none;
}

.tree-table th.sortable:hover {
  color: #409eff;
}

.sort-icon {
  margin-left: 4px;
  color: #409eff;
}

.tree-table td {
  font-size: 13px;
}

.col-toggle {
  width: 30px;
  text-align: center;
}

.col-manager {
  width: 60px;
}

.col-product {
  width: 140px;
}

.col-shop {
  width: 140px;
}

.col-num {
  width: 70px;
  text-align: right;
}

.col-money {
  width: 90px;
  text-align: right;
}

.col-rate {
  width: 60px;
  text-align: right;
}

.col-id {
  width: 90px;
}

.col-sku {
  width: 100px;
}

.col-log {
  width: 50px;
  text-align: center;
}

.log-icon {
  cursor: pointer;
  font-size: 16px;
}
.log-icon.has-log {
  color: #f56c6c;  /* 红色 - 有日志 */
}
.log-icon.no-log {
  color: #c0c4cc;  /* 灰色 - 无日志 */
}
.log-icon:hover {
  opacity: 0.7;
}

/* 日志弹窗效果分析单元格 */
.effect-analysis-cell {
  background-color: #f0f9ff;
  padding: 6px 8px;
  border-radius: 4px;
  color: #606266;
  line-height: 1.5;
}
.content-cell {
  background-color: #f3e8ff;
  padding: 6px 8px;
  border-radius: 4px;
  color: #606266;
  line-height: 1.5;
}

/* 日志竖向表格 */
.log-vertical-table {
  overflow-x: auto;
}
.log-vertical-table table {
  width: 100%;
  border-collapse: collapse;
  table-layout: fixed;
}
.log-vertical-table th,
.log-vertical-table td {
  padding: 8px 12px;
  border: 1px solid #ebeef5;
  text-align: left;
  vertical-align: top;
}
.log-vertical-table th {
  background-color: #f5f7fa;
  color: #909399;
  font-weight: normal;
  width: 90px;
  white-space: nowrap;
}
.log-vertical-table td {
  background-color: #fff;
  color: #606266;
  word-break: break-word;
}
.log-vertical-table td .effect-analysis-cell {
  display: block;
}

.tree-table td.num {
  text-align: right;
}

.toggle-icon {
  display: inline-block;
  width: 16px;
  height: 16px;
  cursor: pointer;
  color: #409eff;
  font-size: 12px;
  line-height: 16px;
  text-align: center;
}

.toggle-icon.expanded {
  color: #67c23a;
}

.parent-row {
  background: #f5f7fa;
  cursor: pointer;
}

.parent-row:hover {
  background: #ebeef5;
}

.level-top {
  background: #fff;
  font-weight: 600;
}

.level-shop {
  background: #f5f0ff;
}

.level-date {
  background: #fff;
}

.empty-cell {
  color: #c0c4cc;
}

.product-link {
  color: #409eff;
  text-decoration: none;
}

.product-link:hover {
  text-decoration: underline;
}

.loading-mask {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(255,255,255,0.8);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  color: #606266;
}

/* 预警阈值颜色 */
.rate-danger {
  color: #ef4444 !important;
  font-weight: 600;
}

.rate-warning {
  color: #f59e0b !important;
  font-weight: 600;
}

.rate-success {
  color: #10b981 !important;
}

/* 日志弹窗样式 */
.log-header {
  margin-bottom: 12px;
}

.log-header p {
  margin: 4px 0;
  font-size: 13px;
  color: #606266;
}

.log-input-area {
  margin-bottom: 12px;
}

.log-list {
  max-height: 300px;
  overflow-y: auto;
}

.log-item {
  padding: 8px;
  border-bottom: 1px solid #ebeef5;
  font-size: 13px;
}

.log-item:last-child {
  border-bottom: none;
}

.log-time {
  color: #909399;
  margin-right: 8px;
  font-size: 12px;
}

.log-content {
  color: #303133;
}

.log-danger {
  background: #fef0f0;
}

.log-danger .log-content {
  color: #f56c6c;
}

.log-success {
  background: #f0f9ff;
}

.log-success .log-content {
  color: #10b981;
}

.log-warning {
  background: #fdf6ec;
}

.log-warning .log-content {
  color: #e6a23c;
}

.log-empty {
  text-align: center;
  color: #909399;
  padding: 20px;
}
</style>
