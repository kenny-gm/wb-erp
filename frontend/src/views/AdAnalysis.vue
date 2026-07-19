<template>
  <div class="ad-analysis">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <div class="filter-item">
        <el-button-group>
          <el-button :type="quickType === 'yesterday' ? 'primary' : ''" @click="setQuickDate('yesterday')">昨日</el-button>
          <el-button :type="quickType === '7days' ? 'primary' : ''" @click="setQuickDate('7days')">7天</el-button>
          <el-button :type="quickType === '30days' ? 'primary' : ''" @click="setQuickDate('30days')">30天</el-button>
        </el-button-group>
      </div>
      <div class="filter-item">
        <el-date-picker
          v-model="filters.dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          @change="handleDateChange"
          style="width: 240px"
        />
      </div>
      <div class="filter-item">
        <el-select v-model="selectedShop" placeholder="选择店铺" clearable style="width: 150px">
          <el-option v-for="shop in shops" :key="shop.id" :label="shop.name" :value="shop.id" />
        </el-select>
      </div>
      <div class="filter-item">
        <el-select v-model="selectedProduct" placeholder="搜索产品(名称/SKU/nm_id)" clearable filterable style="width: 250px">
          <el-option v-for="product in products" :key="product.id" :label="getProductLabel(product)" :value="product.id" />
        </el-select>
      </div>
      <el-button type="primary" @click="fetchAdData" :loading="loading">查询</el-button>
      <el-button @click="downloadAllAdData" :disabled="!hasAdData">下载报表</el-button>
    </div>

    <!-- 数据时间与口径说明 -->
    <div v-if="dataInfo.data_updated_at || dataInfo.data_staleness" class="data-info-bar">
      <span v-if="dataInfo.data_updated_at" class="data-info-item">
        <el-icon><Clock /></el-icon> 数据更新时间：{{ dataInfo.data_updated_at }}
      </span>
      <span v-if="dataInfo.data_staleness" class="data-info-item data-info-warning">
        <el-icon><Warning /></el-icon> {{ dataInfo.data_staleness }}
      </span>
    </div>

    <!-- 产品信息横向展示 -->
    <div class="product-info-bar" v-if="currentProduct">
      <div class="product-icon-wrap">📦</div>
      <div class="product-main">
        <div class="product-name-row">
          <span class="product-name">{{ currentProduct.name || currentProduct.sku }}</span>
          <el-tag size="small" type="info" effect="plain">ID: {{ currentProduct.nm_id || currentProduct.id }}</el-tag>
        </div>
        <div class="product-sub-row">
          <span class="product-meta-item">🏪 {{ currentShop?.name || '-' }}</span>
          <span class="product-meta-item">📋 SKU: {{ currentProduct.sku || '-' }}</span>
          <span class="product-meta-item" v-if="currentProduct.weight">⚖️ {{ currentProduct.weight }}g</span>
          <span class="product-meta-item" v-if="currentProduct.length && currentProduct.width && currentProduct.height">📐 {{ currentProduct.length }}×{{ currentProduct.width }}×{{ currentProduct.height }}cm</span>
        </div>
      </div>
    </div>
    <div class="product-info-bar loading-bar" v-else-if="loading">
      <div class="loading-tip">加载产品信息...</div>
    </div>

    <!-- 核心指标卡片 - 4列2行布局 -->
    <div class="metrics-grid">
      <!-- 第一行: 4个指标卡片 -->
      <!-- 访客 -->
      <div class="metric-card">
        <div class="metric-header">
          <div class="metric-label"><el-icon><User /></el-icon> 访客</div>
          <div class="metric-change" :class="coreMetrics.visitors_change >= 0 ? 'positive' : 'negative'">{{ formatChange(coreMetrics.visitors_change) }}</div>
        </div>
        <div class="metric-value">{{ formatNumber(coreMetrics.total_visitors) }}</div>
        <div class="chart-area" v-if="dailyData.length">
          <svg class="line-chart" viewBox="0 0 100 50" preserveAspectRatio="none">
            <path :d="getAreaPath(metricTrends.total_visitors, maxTrend.total_visitors)" fill="#3b82f6" fill-opacity="0.2" />
            <polyline :points="getLinePoints(metricTrends.total_visitors, maxTrend.total_visitors)" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
      <!-- 加购 -->
      <div class="metric-card">
        <div class="metric-header">
          <div class="metric-label"><el-icon><ShoppingCart /></el-icon> 加购</div>
          <div class="metric-change" :class="coreMetrics.cart_change >= 0 ? 'positive' : 'negative'">{{ formatChange(coreMetrics.cart_change) }}</div>
        </div>
        <div class="metric-value">{{ formatNumber(coreMetrics.total_cart) }}</div>
        <div class="chart-area" v-if="dailyData.length">
          <svg class="line-chart" viewBox="0 0 100 50" preserveAspectRatio="none">
            <path :d="getAreaPath(metricTrends.total_cart, maxTrend.total_cart)" fill="#ec4899" fill-opacity="0.2" />
            <polyline :points="getLinePoints(metricTrends.total_cart, maxTrend.total_cart)" fill="none" stroke="#ec4899" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
      <!-- 订单 -->
      <div class="metric-card">
        <div class="metric-header">
          <div class="metric-label"><el-icon><Document /></el-icon> 订单</div>
          <div class="metric-change" :class="coreMetrics.orders_change >= 0 ? 'positive' : 'negative'">{{ formatChange(coreMetrics.orders_change) }}</div>
        </div>
        <div class="metric-value">{{ formatNumber(coreMetrics.orders) }}</div>
        <div class="chart-area" v-if="dailyData.length">
          <svg class="line-chart" viewBox="0 0 100 50" preserveAspectRatio="none">
            <path :d="getAreaPath(metricTrends.orders, maxTrend.orders)" fill="#f97316" fill-opacity="0.2" />
            <polyline :points="getLinePoints(metricTrends.orders, maxTrend.orders)" fill="none" stroke="#f97316" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
      <!-- 广告花费 -->
      <div class="metric-card">
        <div class="metric-header">
          <div class="metric-label"><el-icon><Notification /></el-icon> 广告花费</div>
          <div class="metric-change" :class="coreMetrics.ad_spend_change >= 0 ? 'negative' : 'positive'">{{ formatChange(coreMetrics.ad_spend_change) }}</div>
        </div>
        <div class="metric-value">{{ formatNumber(coreMetrics.ad_spend) }} ₽</div>
        <div class="chart-area" v-if="dailyData.length">
          <svg class="line-chart" viewBox="0 0 100 50" preserveAspectRatio="none">
            <path :d="getAreaPath(metricTrends.ad_spend, maxTrend.ad_spend)" fill="#ef4444" fill-opacity="0.2" />
            <polyline :points="getLinePoints(metricTrends.ad_spend, maxTrend.ad_spend)" fill="none" stroke="#ef4444" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
        </div>
      </div>
      <!-- 第二行: 4个多段饼图 -->
            <!-- 访客结构 -->
      <div class="metric-card pie-card">
        <div class="pie-top-row">
          <div class="pie-label">访客结构</div>
          <div class="pie-total-pct">{{ visitorAdPercent.toFixed(1) }}%</div>
        </div>
        <div class="donut-section">
          <svg viewBox="0 0 120 120" class="donut-svg-full">
            <!-- Background circle -->
            <circle cx="60" cy="60" r="50" fill="none" stroke="#f0f0f0" stroke-width="14"/>
            <!-- Natural (light gray arc) -->
            <path :d="donutArcPath(naturalPct('visitors'), 0)" fill="none" stroke="#d1d5db" stroke-width="14" stroke-linecap="round"/>
            <!-- CPM推荐 (purple arc) -->
            <path :d="donutArcPath(cpmPct('visitors'), naturalPct('visitors'))" fill="none" stroke="#8b5cf6" stroke-width="14" stroke-linecap="round"/>
            <!-- CPC搜索 (green arc) -->
            <path :d="donutArcPath(cpcPct('visitors'), naturalPct('visitors') + cpmPct('visitors'))" fill="none" stroke="#10b981" stroke-width="14" stroke-linecap="round"/>
            <!-- CPM搜索 (orange arc) -->
            <path :d="donutArcPath(cmsPct('visitors'), naturalPct('visitors') + cpmPct('visitors') + cpcPct('visitors'))" fill="none" stroke="#f97316" stroke-width="14" stroke-linecap="round"/>
            <text x="60" y="56" text-anchor="middle" class="donut-text-main">{{ visitorAdPercent.toFixed(1) }}%</text>
            <text x="60" y="70" text-anchor="middle" class="donut-text-sub">广告</text>
          </svg>
          <div class="donut-legend-list">
            <div class="dl-row">
              <span class="dl-dot" style="background:#8b5cf6"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_recommend || {}).visitors || 0) }}</span>
              <span class="dl-pct">{{ cpmPct('visitors').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#10b981"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpc_search || {}).visitors || 0) }}</span>
              <span class="dl-pct">{{ cpcPct('visitors').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#f97316"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_search || {}).visitors || 0) }}</span>
              <span class="dl-pct">{{ cmsPct('visitors').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#d1d5db"></span>
              <span class="dl-val">{{ formatNumber(naturalVal('visitors')) }}</span>
              <span class="dl-pct">{{ naturalPct('visitors').toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>
      <!-- 加购结构 -->
      <div class="metric-card pie-card">
        <div class="pie-top-row">
          <div class="pie-label">加购结构</div>
          <div class="pie-total-pct">{{ cartAdPercent.toFixed(1) }}%</div>
        </div>
        <div class="donut-section">
          <svg viewBox="0 0 120 120" class="donut-svg-full">
            <circle cx="60" cy="60" r="50" fill="none" stroke="#f0f0f0" stroke-width="14"/>
            <path :d="donutArcPath(naturalPct('cart'), 0)" fill="none" stroke="#d1d5db" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cpmPct('cart'), naturalPct('cart'))" fill="none" stroke="#8b5cf6" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cpcPct('cart'), naturalPct('cart') + cpmPct('cart'))" fill="none" stroke="#10b981" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cmsPct('cart'), naturalPct('cart') + cpmPct('cart') + cpcPct('cart'))" fill="none" stroke="#f97316" stroke-width="14" stroke-linecap="round"/>
            <text x="60" y="56" text-anchor="middle" class="donut-text-main">{{ cartAdPercent.toFixed(1) }}%</text>
            <text x="60" y="70" text-anchor="middle" class="donut-text-sub">广告</text>
          </svg>
          <div class="donut-legend-list">
            <div class="dl-row">
              <span class="dl-dot" style="background:#8b5cf6"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_recommend || {}).cart || 0) }}</span>
              <span class="dl-pct">{{ cpmPct('cart').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#10b981"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpc_search || {}).cart || 0) }}</span>
              <span class="dl-pct">{{ cpcPct('cart').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#f97316"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_search || {}).cart || 0) }}</span>
              <span class="dl-pct">{{ cmsPct('cart').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#d1d5db"></span>
              <span class="dl-val">{{ formatNumber(naturalVal('cart')) }}</span>
              <span class="dl-pct">{{ naturalPct('cart').toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>
      <!-- 订单结构 -->
      <div class="metric-card pie-card">
        <div class="pie-top-row">
          <div class="pie-label">订单结构</div>
          <div class="pie-total-pct">{{ orderAdPercent.toFixed(1) }}%</div>
        </div>
        <div class="donut-section">
          <svg viewBox="0 0 120 120" class="donut-svg-full">
            <circle cx="60" cy="60" r="50" fill="none" stroke="#f0f0f0" stroke-width="14"/>
            <path :d="donutArcPath(naturalPct('orders'), 0)" fill="none" stroke="#d1d5db" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cpmPct('orders'), naturalPct('orders'))" fill="none" stroke="#8b5cf6" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cpcPct('orders'), naturalPct('orders') + cpmPct('orders'))" fill="none" stroke="#10b981" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cmsPct('orders'), naturalPct('orders') + cpmPct('orders') + cpcPct('orders'))" fill="none" stroke="#f97316" stroke-width="14" stroke-linecap="round"/>
            <text x="60" y="56" text-anchor="middle" class="donut-text-main">{{ orderAdPercent.toFixed(1) }}%</text>
            <text x="60" y="70" text-anchor="middle" class="donut-text-sub">广告</text>
          </svg>
          <div class="donut-legend-list">
            <div class="dl-row">
              <span class="dl-dot" style="background:#8b5cf6"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_recommend || {}).orders || 0) }}</span>
              <span class="dl-pct">{{ cpmPct('orders').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#10b981"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpc_search || {}).orders || 0) }}</span>
              <span class="dl-pct">{{ cpcPct('orders').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#f97316"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_search || {}).orders || 0) }}</span>
              <span class="dl-pct">{{ cmsPct('orders').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#d1d5db"></span>
              <span class="dl-val">{{ formatNumber(naturalVal('orders')) }}</span>
              <span class="dl-pct">{{ naturalPct('orders').toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>
      <!-- 花费结构 -->
      <div class="metric-card pie-card">
        <div class="pie-top-row">
          <div class="pie-label">花费结构</div>
          <div class="pie-total-pct">{{ spendAdPercent.toFixed(1) }}%</div>
        </div>
        <div class="donut-section">
          <svg viewBox="0 0 120 120" class="donut-svg-full">
            <circle cx="60" cy="60" r="50" fill="none" stroke="#f0f0f0" stroke-width="14"/>
            <path :d="donutArcPath(naturalPct('spend'), 0)" fill="none" stroke="#d1d5db" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cpmPct('spend'), naturalPct('spend'))" fill="none" stroke="#8b5cf6" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cpcPct('spend'), naturalPct('spend') + cpmPct('spend'))" fill="none" stroke="#10b981" stroke-width="14" stroke-linecap="round"/>
            <path :d="donutArcPath(cmsPct('spend'), naturalPct('spend') + cpmPct('spend') + cpcPct('spend'))" fill="none" stroke="#f97316" stroke-width="14" stroke-linecap="round"/>
            <text x="60" y="56" text-anchor="middle" class="donut-text-main">{{ spendAdPercent.toFixed(1) }}%</text>
            <text x="60" y="70" text-anchor="middle" class="donut-text-sub">广告</text>
          </svg>
          <div class="donut-legend-list">
            <div class="dl-row">
              <span class="dl-dot" style="background:#8b5cf6"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_recommend || {}).spend || 0) }}</span>
              <span class="dl-pct">{{ cpmPct('spend').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#10b981"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpc_search || {}).spend || 0) }}</span>
              <span class="dl-pct">{{ cpcPct('spend').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#f97316"></span>
              <span class="dl-val">{{ formatNumber((coreMetrics.ad_by_type?.cpm_search || {}).spend || 0) }}</span>
              <span class="dl-pct">{{ cmsPct('spend').toFixed(1) }}%</span>
            </div>
            <div class="dl-row">
              <span class="dl-dot" style="background:#d1d5db"></span>
              <span class="dl-val">{{ formatNumber(naturalVal('spend')) }}</span>
              <span class="dl-pct">{{ naturalPct('spend').toFixed(1) }}%</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    <!-- CPM推荐广告（紫色半透明背景） -->
    <el-card class="box-card cpm-recommend-card" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; align-items: center;">
          <span style="font-weight: 600; color: #8b5cf6;">CPM推荐广告</span>
        </div>
      </template>
      <CpmRecommendationsTable :data="cpmRecommendationsData" />
    </el-card>

    <!-- CPC搜索广告（绿色半透明背景） -->
    <el-card class="box-card cpc-combined-card" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; gap: 16px;">
          <span style="font-weight: 600; color: #10b981;">CPC搜索广告</span>
          <span 
            style="font-weight: 600; color: #909399; cursor: pointer;"
            @click="cpcKeywordsExpanded = !cpcKeywordsExpanded"
          >CPC搜索关键词</span>
        </div>
      </template>
      <CpcSearchDailyTable :data="cpcDailyData" />
      <CpcKeywordsTable 
        v-show="cpcKeywordsExpanded"
        :keywords="cpcKeywordsData"
        :dateFrom="filters.start_date"
        :dateTo="filters.end_date"
        :productId="selectedProduct"
      />
    </el-card>

    <!-- CPM搜索广告（橙色半透明背景） -->
    <el-card class="box-card cpm-combined-card" style="margin-bottom: 16px">
      <template #header>
        <div style="display: flex; gap: 16px;">
          <span style="font-weight: 600; color: #E6A23C;">CPM搜索广告</span>
          <span 
            style="font-weight: 600; color: #909399; cursor: pointer;"
            @click="cpmKeywordsExpanded = !cpmKeywordsExpanded"
          >CPM搜索关键词</span>
        </div>
      </template>
      <CpmSearchTable :data="cpmSearchData" />
      <CpmKeywordsTable 
        v-show="cpmKeywordsExpanded"
        :keywords="cpmKeywordsData"
        :dateFrom="filters.start_date"
        :dateTo="filters.end_date"
        :productId="selectedProduct"
      />
    </el-card>

  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Download, DataAnalysis, Setting, Money, User, Document, ShoppingCart, Notification, Clock, Warning } from '@element-plus/icons-vue'
import { useAuthStore } from '../stores/auth'
import axios from 'axios'
import * as XLSX from 'xlsx'

// 导入组件
import CpmRecommendationsTable from '../components/ad/CpmRecommendationsTable.vue'
import CpmSearchTable from '../components/ad/CpmSearchTable.vue'
import CpcSearchDailyTable from '../components/ad/CpcSearchDailyTable.vue'
import CpcKeywordsTable from '../components/ad/CpcKeywordsTable.vue'
import CpmKeywordsTable from '../components/ad/CpmKeywordsTable.vue'

// 真实数据，无 mock

// Auth store
const authStore = useAuthStore()

// 是否为管理员
const isAdmin = computed(() => authStore.user?.role === 'admin')

// 预警设置状态
const alertSettingsVisible = ref(false)
const thresholds = ref([])
const loadingThresholds = ref(false)
const saving = ref(false)
const changedThresholds = ref(new Set())

// 筛选状态
const selectedShop = ref(null)
const selectedProduct = ref(null)
const activeAdType = ref('all')
const quickType = ref('7days')
const filters = reactive({ dateRange: null, start_date: '', end_date: '' })

// 数据状态 - 使用空数组而不是mock数据
const shops = ref([])
const products = ref([])
const coreMetrics = ref({})
const dailyData = ref([])  // 原始日数据,用于趋势计算
const cpmRecommendationsData = ref([])  // CPM推荐广告数据
const cpmRecommendExpanded = ref(true)  // CPM推荐广告折叠状态（默认展开）
const cpmSearchData = ref([])  // CPM搜索广告数据
const cpcDailyData = ref([])  // CPC搜索每日数据
const cpcDailyExpanded = ref(true)  // CPC搜索广告折叠状态（默认展开）
const cpcKeywordsData = ref([])  // CPC搜索关键词数据
const cpcKeywordsExpanded = ref(false)  // CPC搜索关键词折叠状态
const cpmSearchExpanded = ref(true)   // CPM搜索广告折叠状态（默认展开）
const cpmKeywordsExpanded = ref(false)  // CPM搜索关键词折叠状态
const cpmKeywordsData = ref([])  // CPM搜索关键词数据
const hasAdData = computed(() => cpmRecommendationsData.value.length > 0 || cpmSearchData.value.length > 0 || cpcDailyData.value.length > 0)


// 占比计算
const adRatioPercent = computed(() => {
  const sales = coreMetrics.value.sales || 0
  const adSpend = coreMetrics.value.ad_spend || 0
  if (!sales) return 0
  return Math.min(100, Math.round((adSpend / sales) * 1000) / 10)
})

const adOrderRatioPercent = computed(() => {
  const orders = coreMetrics.value.orders || 0
  const adOrders = coreMetrics.value.ad_orders || 0
  if (!orders) return 0
  return Math.min(100, Math.round((adOrders / orders) * 1000) / 10)
})

const adTrafficRatioPercent = computed(() => {
  const visitors = coreMetrics.value.total_visitors || 0
  const adVisitors = coreMetrics.value.ad_visitors || 0
  if (!visitors) return 0
  return Math.min(100, Math.round((adVisitors / visitors) * 1000) / 10)
})

// 各广告维度占比（用于饼图）
const visitorAdPercent = computed(() => {
  const total = coreMetrics.value.total_visitors || 0
  const ad = coreMetrics.value.ad_visitors || 0
  if (!total) return 0
  return Math.min(100, (ad / total) * 100)
})

const cartAdPercent = computed(() => {
  const total = coreMetrics.value.total_cart || 0
  const ad = coreMetrics.value.ad_cart || 0
  if (!total) return 0
  return Math.min(100, (ad / total) * 100)
})

const orderAdPercent = computed(() => {
  const total = coreMetrics.value.orders || 0
  const ad = coreMetrics.value.ad_orders || 0
  if (!total) return 0
  return Math.min(100, (ad / total) * 100)
})

const spendAdPercent = computed(() => {
  const total = coreMetrics.value.sales || 0
  const ad = coreMetrics.value.ad_spend || 0
  if (!total) return 0
  return Math.min(100, (ad / total) * 100)
})

// 饼图分段百分比 (CPM推荐/CPC搜索/CPM搜索)
// 各维度占总量比例
function visitorPctOfTotal(type) {
  const byType = coreMetrics.value.ad_by_type || {}
  const total = coreMetrics.value.total_visitors || 0
  if (!total) return 0
  if (type === 'cpm_recommend') return (byType.cpm_recommend || {}).visitors || 0
  if (type === 'cpc_search') return (byType.cpc_search || {}).visitors || 0
  if (type === 'cpm_search') return (byType.cpm_search || {}).visitors || 0
  if (type === 'natural') return Math.max(0, total - ((byType.cpm_recommend || {}).visitors || 0) - ((byType.cpc_search || {}).visitors || 0) - ((byType.cpm_search || {}).visitors || 0))
  return 0
}
function visitorNatural() { return visitorPctOfTotal('natural') }

function cartPctOfTotal(type) {
  const byType = coreMetrics.value.ad_by_type || {}
  const total = coreMetrics.value.total_cart || 0
  if (!total) return 0
  if (type === 'cpm_recommend') return (byType.cpm_recommend || {}).cart || 0
  if (type === 'cpc_search') return (byType.cpc_search || {}).cart || 0
  if (type === 'cpm_search') return (byType.cpm_search || {}).cart || 0
  if (type === 'natural') return Math.max(0, total - ((byType.cpm_recommend || {}).cart || 0) - ((byType.cpc_search || {}).cart || 0) - ((byType.cpm_search || {}).cart || 0))
  return 0
}
function cartNatural() { return cartPctOfTotal('natural') }

function orderPctOfTotal(type) {
  const byType = coreMetrics.value.ad_by_type || {}
  const total = coreMetrics.value.orders || 0
  if (!total) return 0
  if (type === 'cpm_recommend') return (byType.cpm_recommend || {}).orders || 0
  if (type === 'cpc_search') return (byType.cpc_search || {}).orders || 0
  if (type === 'cpm_search') return (byType.cpm_search || {}).orders || 0
  if (type === 'natural') return Math.max(0, total - ((byType.cpm_recommend || {}).orders || 0) - ((byType.cpc_search || {}).orders || 0) - ((byType.cpm_search || {}).orders || 0))
  return 0
}
function orderNatural() { return orderPctOfTotal('natural') }

function spendPctOfTotal(type) {
  const byType = coreMetrics.value.ad_by_type || {}
  const total = coreMetrics.value.sales || 0
  if (!total) return 0
  if (type === 'cpm_recommend') return (byType.cpm_recommend || {}).spend || 0
  if (type === 'cpc_search') return (byType.cpc_search || {}).spend || 0
  if (type === 'cpm_search') return (byType.cpm_search || {}).spend || 0
  if (type === 'natural') return Math.max(0, total - ((byType.cpm_recommend || {}).spend || 0) - ((byType.cpc_search || {}).spend || 0) - ((byType.cpm_search || {}).spend || 0))
  return 0
}
function spendNatural() { return spendPctOfTotal('natural') }

// Donut arc path: pct = percentage of this segment, startPct = cumulative before this segment
function donutArcPath(pct, startPct) {
  if (pct <= 0) return ''
  const R = 50
  const C = 2 * Math.PI * R
  const gap = 3 / 360 * C // 3deg gap between segments
  const segLen = pct / 100 * C - gap
  if (segLen <= 0) return ''
  const startAngle = startPct / 100 * 360 - 90 // -90 = top
  const endAngle = (startPct + pct) / 100 * 360 - 90 - (gap / C * 360)
  const sx = 60 + R * Math.cos(startAngle * Math.PI / 180)
  const sy = 60 + R * Math.sin(startAngle * Math.PI / 180)
  const ex = 60 + R * Math.cos(endAngle * Math.PI / 180)
  const ey = 60 + R * Math.sin(endAngle * Math.PI / 180)
  const large = pct > 50 ? 1 : 0
  return `M ${sx} ${sy} A ${R} ${R} 0 ${large} 1 ${ex} ${ey}`
}

// Dimension pct helpers (each returns % of total for a given type)
function cpmPct(dim) {
  const byType = coreMetrics.value.ad_by_type || {}
  const total = dimTotal(dim)
  if (!total) return 0
  return ((byType.cpm_recommend || {})[dim] || 0) / total * 100
}
function cpcPct(dim) {
  const byType = coreMetrics.value.ad_by_type || {}
  const total = dimTotal(dim)
  if (!total) return 0
  return ((byType.cpc_search || {})[dim] || 0) / total * 100
}
function cmsPct(dim) {
  const byType = coreMetrics.value.ad_by_type || {}
  const total = dimTotal(dim)
  if (!total) return 0
  return ((byType.cpm_search || {})[dim] || 0) / total * 100
}
function naturalPct(dim) {
  const total = dimTotal(dim)
  if (!total) return 0
  return Math.max(0, 100 - cpmPct(dim) - cpcPct(dim) - cmsPct(dim))
}
function naturalVal(dim) {
  const total = dimTotal(dim)
  if (!total) return 0
  const byType = coreMetrics.value.ad_by_type || {}
  const adTotal = ((byType.cpm_recommend || {})[dim] || 0) + ((byType.cpc_search || {})[dim] || 0) + ((byType.cpm_search || {})[dim] || 0)
  return Math.max(0, total - adTotal)
}
function dimTotal(dim) {
  if (dim === 'visitors') return coreMetrics.value.total_visitors || 0
  if (dim === 'cart') return coreMetrics.value.total_cart || 0
  if (dim === 'orders') return coreMetrics.value.orders || 0
  if (dim === 'spend') return coreMetrics.value.sales || 0
  return 0
}

function dashArray(percent) {
  const circumference = 2 * Math.PI * 40 // r=40
  const filled = (percent / 100) * circumference
  return `${filled} ${circumference - filled}`
}

// 核心指标趋势数据(用于卡片折线图)
const metricTrends = computed(() => {
  if (!dailyData.value || !dailyData.value.length) return {}
  const sorted = [...dailyData.value].sort((a, b) => new Date(a.date) - new Date(b.date))
  return {
    sales: sorted.map(d => d.sales || 0),
    orders: sorted.map(d => d.orders || 0),
    total_visitors: sorted.map(d => d.total_visitors || 0),
    total_cart: sorted.map(d => d.add_to_cart || 0),
    ad_visitors: sorted.map(d => d.ad_visitors || 0),
    ad_orders: sorted.map(d => d.ad_orders || 0),
    ad_spend: sorted.map(d => d.spend || 0),
    ad_ctr: sorted.map(d => {
      const imp = d.ad_impressions || 0
      const clk = d.ad_visitors || 0
      return imp > 0 ? (clk / imp * 100) : 0
    }),
    ad_cart_rate: sorted.map(d => d.cart_rate || 0),
    cpc: sorted.map(d => {
      const spend = d.spend || 0
      const clicks = d.ad_visitors || 0
      return clicks > 0 ? (spend / clicks) : 0
    })
  }
})

// 计算趋势最大值
const maxTrend = computed(() => {
  if (!metricTrends.value || Object.keys(metricTrends.value).length === 0) return {}
  return {
    sales: Math.max(...metricTrends.value.sales) || 1,
    orders: Math.max(...metricTrends.value.orders) || 1,
    total_visitors: Math.max(...metricTrends.value.total_visitors) || 1,
    total_cart: Math.max(...(metricTrends.value.total_cart || [0])) || 1,
    ad_visitors: Math.max(...metricTrends.value.ad_visitors) || 1,
    ad_orders: Math.max(...metricTrends.value.ad_orders) || 1,
    ad_spend: Math.max(...metricTrends.value.ad_spend) || 1,
  }
})
const salesTrend = ref([])
const trafficSource = ref({
  natural_ratio: 0,
  ad_ratio: 0,
  other_ratio: 0,
  natural_visitors: 0,
  ad_visitors: 0,
  other_visitors: 0,
  total_visitors: 0
})
const trafficTrend = ref([])
const adCampaigns = ref([])
const keywordsData = ref([])
const optimizationAdvice = ref([])
const loading = ref(false)
const dataInfo = reactive({ data_updated_at: '', data_staleness: '' })

// 计算当前选中的产品和店铺
const currentProduct = computed(() => {
  if (!selectedProduct.value || products.value.length === 0) return null
  return products.value.find(p => p.id === selectedProduct.value) || null
})

const currentShop = computed(() => {
  if (!selectedShop.value || shops.value.length === 0) return null
  return shops.value.find(s => s.id === selectedShop.value) || null
})

// 计算日期范围
const dateRange = computed(() => {
  if (filters.start_date && filters.end_date) {
    return { start: filters.start_date, end: filters.end_date }
  }
  // 默认7天
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 6)
  const fmt = (d) => d.toISOString().split('T')[0]
  return { start: fmt(start), end: fmt(end) }
})

// 设置快捷日期
function setQuickDate(type) {
  quickType.value = type
  const today = new Date()
  const y = today.getFullYear(), m = String(today.getMonth() + 1).padStart(2, '0'), d = String(today.getDate()).padStart(2, '0')
  const todayStr = y + '-' + m + '-' + d

  if (type === 'yesterday') {
    const yd = new Date(today); yd.setDate(yd.getDate() - 1)
    const yesterdayStr = yd.getFullYear() + '-' + String(yd.getMonth() + 1).padStart(2, '0') + '-' + String(yd.getDate()).padStart(2, '0')
    filters.dateRange = [yesterdayStr, yesterdayStr]
    filters.start_date = yesterdayStr
    filters.end_date = yesterdayStr
  } else if (type === '7days') {
    const yd = new Date(today); yd.setDate(yd.getDate() - 1)
    const sd = new Date(yd); sd.setDate(sd.getDate() - 6)
    const startStr = sd.getFullYear() + '-' + String(sd.getMonth() + 1).padStart(2, '0') + '-' + String(sd.getDate()).padStart(2, '0')
    const endStr = yd.getFullYear() + '-' + String(yd.getMonth() + 1).padStart(2, '0') + '-' + String(yd.getDate()).padStart(2, '0')
    filters.dateRange = [startStr, endStr]
    filters.start_date = startStr
    filters.end_date = endStr
  } else if (type === '30days') {
    const yd = new Date(today); yd.setDate(yd.getDate() - 1)
    const sd = new Date(yd); sd.setDate(sd.getDate() - 29)
    const startStr = sd.getFullYear() + '-' + String(sd.getMonth() + 1).padStart(2, '0') + '-' + String(sd.getDate()).padStart(2, '0')
    const endStr = yd.getFullYear() + '-' + String(yd.getMonth() + 1).padStart(2, '0') + '-' + String(yd.getDate()).padStart(2, '0')
    filters.dateRange = [startStr, endStr]
    filters.start_date = startStr
    filters.end_date = endStr
  }
}

// 日期变化处理
function handleDateChange(val) {
  if (val && val.length === 2) {
    filters.start_date = val[0]
    filters.end_date = val[1]
    quickType.value = ''
  }
}

// 格式化数字
function formatNumber(n) {
  if (!n && n !== 0) return '0'
  const value = Number.parseFloat(String(n).replace(/,/g, ''))
  if (!Number.isFinite(value)) return '0'
  const rounded = Math.round((value + Number.EPSILON) * 100) / 100
  const [integerPart, decimalPart] = String(rounded).split('.')
  const integer = integerPart.replace(/\B(?=(\d{3})+(?!\d))/g, ' ')
  return decimalPart ? `${integer}.${decimalPart}` : integer
}

// 产品选项标签(显示 nm_id + SKU + 名称)
function getProductLabel(product) {
  const nmId = product.nm_id ? `(${product.nm_id})` : ''
  return `${nmId} ${product.sku} - ${product.name}`
}

function formatChange(c) {
  return c || c === 0 ? (c >= 0 ? '+' : '') + c.toFixed(1) + '%' : '0%'
}

// 折线图辅助函数
function getX(i, len) { return (i / (len - 1)) * 100 }
function getY(v, max) { return max > 0 ? 50 - (v / max) * 45 : 25 }

function getLinePoints(data, max) {
  if (!data || data.length < 2) return ''
  return data.map((d, i) => getX(i, data.length) + ',' + getY(d, max)).join(' ')
}

function getAreaPath(data, max) {
  if (!data || data.length < 2) return ''
  const pts = data.map((d, i) => getX(i, data.length) + ',' + getY(d, max))
  return 'M' + pts.join('L') + 'V50H' + getX(0, data.length) + 'Z'
}

// 加载店铺列表
async function fetchShops() {
  try {
    const response = await axios.get('/api/shops/')
    shops.value = response.data
    if (shops.value.length > 0 && !selectedShop.value) {
      selectedShop.value = shops.value[0].id
    }
  } catch (error) {
    console.error('获取店铺列表失败', error)
  }
}

// 加载店铺产品列表
async function fetchProducts(shopId) {
  if (!shopId) {
    products.value = []
    return
  }
  try {
    const response = await axios.get(`/api/shops/${shopId}/products/`)
    products.value = response.data
    if (products.value.length > 0 && !selectedProduct.value) {
      selectedProduct.value = products.value[0].id
    }
  } catch (error) {
    console.error('获取产品列表失败', error)
  }
}

// 加载产品广告数据
async function fetchAdData() {
  if (!selectedProduct.value) return

  loading.value = true
  try {
    const dateFrom = filters.start_date || dateRange.value.start
    const dateTo = filters.end_date || dateRange.value.end

    const response = await axios.get(`/api/products/${selectedProduct.value}/ads/`, {
      params: {
        date_from: dateFrom,
        date_to: dateTo
      }
    })

    const data = response.data

    const summary = data.summary || {}

    coreMetrics.value = {
      sales: summary.sales || 0,
      orders: summary.orders || 0,
      total_visitors: summary.total_visitors || 0,
      total_cart: summary.total_cart || 0,
      ad_visitors: summary.ad_visitors || 0,
      ad_orders: summary.ad_orders || 0,
      ad_cart: summary.ad_cart || 0,
      ad_spend: summary.ad_spend || 0,
      ad_ctr: summary.ad_ctr || 0,
      ad_cart_rate: summary.ad_cart_rate || 0,
      cpc: summary.cpc || 0,
      ad_by_type: summary.ad_by_type || { cpm_recommend: {}, cpm_search: {}, cpc_search: {} },
      // 环比变化
      sales_change: summary.sales_change || 0,
      orders_change: summary.orders_change || 0,
      visitors_change: summary.visitors_change || 0,
      cart_change: summary.cart_change || 0,
      ad_spend_change: summary.ad_spend_change || 0,
      ad_orders_change: summary.ad_orders_change || 0,
      ad_visitors_change: summary.ad_visitors_change || 0,
    }

    // 数据时间信息
    dataInfo.data_updated_at = summary.data_updated_at || ''
    dataInfo.data_staleness = summary.data_staleness || ''

    // 计算访客数据 - 使用API返回的新字段
    const productVisitors = summary.impressions || 0  // 产品访客 (product_analytics)
    const adVisitors = summary.ad_visitors || 0  // 广告点击=广告访客
    const adImpressions = summary.ad_impressions || 0  // 广告曝光
    const naturalVisitors = Math.max(0, productVisitors - adVisitors)  // 自然访客 = 产品访客 - 广告访客

    // 流量来源分析
    trafficSource.value = {
      ad_ratio: productVisitors > 0 ? parseFloat((adVisitors / productVisitors * 100).toFixed(1)) : 0,
      natural_ratio: productVisitors > 0 ? parseFloat((naturalVisitors / productVisitors * 100).toFixed(1)) : 0,
      other_ratio: 0,
      ad_visitors: adVisitors,
      natural_visitors: naturalVisitors,
      other_visitors: 0,
      total_visitors: productVisitors,
      ad_impressions: adImpressions
    }

    adCampaigns.value = data.ad_details || data.adverts || []

    // 销售趋势 - 销售额和广告费
    if (data.daily_data && data.daily_data.length > 0) {
      dailyData.value = data.daily_data
      // 按日期排序
      const sortedData = [...data.daily_data].sort((a, b) => new Date(a.date) - new Date(b.date))
      salesTrend.value = sortedData.map(d => ({
        date: d.date,
        sales: d.sales || 0,
        ad_cost: d.spend || 0
      }))

      // 流量趋势 - 从daily_data计算
      trafficTrend.value = sortedData.map(d => {
        const dayTotalVisitors = d.impressions || 0
        const dayAdSpend = d.spend || 0
        // 估算广告访客(如果有广告花费就有广告访客)
        const dayAdVisitors = dayAdSpend > 0 ? Math.round(dayTotalVisitors * 0.3) : 0
        const dayNaturalVisitors = dayTotalVisitors - dayAdVisitors
        return {
          date: d.date,
          total_visitors: dayTotalVisitors,
          ad_visitors: dayAdVisitors,
          natural_visitors: dayNaturalVisitors
        }
      })
    }

    // 获取CPM推荐广告数据
    try {
      const cpmResponse = await axios.get(`/api/products/${selectedProduct.value}/cpm-recommendations`, {
        params: { date_from: dateFrom, date_to: dateTo }
      })
      cpmRecommendationsData.value = cpmResponse.data.data || []
    } catch (e) {
      console.error(`[CPM推荐] /cpm-recommendations 接口失败 (CPM推荐):`, e)
      cpmRecommendationsData.value = []
    }

    // 获取CPM搜索广告数据
    try {
      const cpmSearchResponse = await axios.get(`/api/products/${selectedProduct.value}/cpm-search`, {
        params: { date_from: dateFrom, date_to: dateTo }
      })
      cpmSearchData.value = cpmSearchResponse.data.data || []
    } catch (e) {
      console.error(`[CPM搜索] /cpm-search 接口失败:`, e)
      cpmSearchData.value = []
    }

    // 获取CPC搜索每日数据
    try {
      const cpcDailyResponse = await axios.get(`/api/products/${selectedProduct.value}/cpc-search`, {
        params: { date_from: dateFrom, date_to: dateTo }
      })
      cpcDailyData.value = cpcDailyResponse.data.data || []
    } catch (e) {
      console.error(`[CPC每日] /cpc-search 接口失败:`, e)
      cpcDailyData.value = []
    }
    
    // 获取CPC搜索关键词数据
    try {
      const cpcKwResponse = await axios.get(`/api/products/${selectedProduct.value}/keyword-stats`, {
        params: { date_from: dateFrom, date_to: dateTo, payment_type: 'cpc' }
      })
      cpcKeywordsData.value = cpcKwResponse.data.keywords || []
    } catch (e) {
      console.error(`[CPC关键词] /keyword-stats?payment_type=cpc 接口失败:`, e)
      cpcKeywordsData.value = []
    }
    
    // 获取CPM搜索关键词数据
    try {
      const cpmKwResponse = await axios.get(`/api/products/${selectedProduct.value}/keyword-stats`, {
        params: { date_from: dateFrom, date_to: dateTo, payment_type: 'cpm' }
      })
      cpmKeywordsData.value = cpmKwResponse.data.keywords || []
    } catch (e) {
      console.error(`[CPM关键词] /keyword-stats?payment_type=cpm 接口失败:`, e)
      cpmKeywordsData.value = []
    }

  } catch (error) {
    console.error('获取广告数据失败', error)
    // 接口失败时显示错误状态，不生成假数据
    dailyData.value = []
    salesTrend.value = []
    trafficTrend.value = []
    trafficSource.value = { ad_visitors: 0, natural_visitors: 0, other_visitors: 0, total_visitors: 0 }
    adCampaigns.value = []
    keywordsData.value = []
    optimizationAdvice.value = []
  } finally {
    loading.value = false
  }
}

// 下载整合的广告报表
async function downloadAllAdData() {
  const dateFrom = filters.start_date || dateRange.value.start
  const dateTo = filters.end_date || dateRange.value.end
  const shopName = currentShop.value?.name || '全店铺'
  const productName = currentProduct.value?.name || currentProduct.value?.sku || '产品'

  // 获取当前产品的 nm_id
  const productNmId = currentProduct.value?.nm_id || ''

  // 构建 nm_id + date → 日志内容 的映射
  const logMap = {}
  try {
    const logResp = await axios.get('/api/operation-logs/', {
      params: { start_date: dateFrom, end_date: dateTo, limit: 500 }
    })
    const logs = logResp.data || []
    logs.forEach(log => {
      if (log.nm_id) {
        const key = `${log.nm_id}_${log.date}`
        if (!logMap[key]) {
          logMap[key] = log.title ? `${log.title}: ${log.detail || ''}` : (log.detail || '')
        } else {
          // 多条日志用换行合并
          const existing = logMap[key]
          const newEntry = log.title ? `${log.title}: ${log.detail || ''}` : (log.detail || '')
          logMap[key] = existing + '\n' + newEntry
        }
      }
    })
  } catch (e) {
    console.warn('获取日志失败:', e)
  }

  const rows = []

  // 表头（加一列日志内容）
  rows.push(['产品ID', '广告类型', '时间', '曝光', '访客', '花费', '订单', '购物车', '加购率', 'CTR', '转化', 'CPM', 'CPC', '日志内容'])

  // CPM推荐
  for (const r of cpmRecommendationsData.value) {
    const impressions = r.impressions || 0
    const visitors = r.visitors || 0
    const cost = r.cost || 0
    const orders = r.order_count || 0
    const cart = r.cart_count || 0
    const ctr = visitors > 0 ? (visitors / impressions * 100) : 0
    const cartRate = visitors > 0 ? (cart / visitors * 100).toFixed(2) : '0.00'
    const conversion = visitors > 0 ? (orders / visitors * 100).toFixed(2) : '0.00'
    const cpm = impressions > 0 ? (cost / impressions * 1000).toFixed(2) : '0.00'
    const cpc = visitors > 0 ? (cost / visitors).toFixed(2) : '0.00'
    const logKey = `${productNmId}_${r.record_date}`
    const logContent = logMap[logKey] || ''
    rows.push([currentProduct.value?.nm_id || currentProduct.value?.id || '', 'CPM推荐', r.record_date, impressions, visitors, cost, orders, cart, cartRate + '%', ctr.toFixed(2) + '%', conversion + '%', cpm, cpc, logContent])
  }

  // CPM搜索
  for (const r of cpmSearchData.value) {
    const impressions = r.impressions || 0
    const visitors = r.visitors || 0
    const cost = r.cost || 0
    const orders = r.order_count || 0
    const cart = r.cart_count || 0
    const ctr = visitors > 0 ? (visitors / impressions * 100) : 0
    const cartRate = visitors > 0 ? (cart / visitors * 100).toFixed(2) : '0.00'
    const conversion = visitors > 0 ? (orders / visitors * 100).toFixed(2) : '0.00'
    const cpm = impressions > 0 ? (cost / impressions * 1000).toFixed(2) : '0.00'
    const cpc = visitors > 0 ? (cost / visitors).toFixed(2) : '0.00'
    const logKey2 = `${productNmId}_${r.record_date}`
    const logContent2 = logMap[logKey2] || ''
    rows.push([currentProduct.value?.nm_id || currentProduct.value?.id || '', 'CPM搜索', r.record_date, impressions, visitors, cost, orders, cart, cartRate + '%', ctr.toFixed(2) + '%', conversion + '%', cpm, cpc, logContent2])
  }

  // CPC搜索
  for (const r of cpcDailyData.value) {
    const impressions = r.impressions || 0
    const visitors = r.visitors || 0
    const cost = r.cost || 0
    const orders = r.order_count || 0
    const cart = r.cart_count || 0
    const ctr = visitors > 0 ? (visitors / impressions * 100) : 0
    const cartRate = visitors > 0 ? (cart / visitors * 100).toFixed(2) : '0.00'
    const conversion = visitors > 0 ? (orders / visitors * 100).toFixed(2) : '0.00'
    const cpm = impressions > 0 ? (cost / impressions * 1000).toFixed(2) : '0.00'
    const cpc = visitors > 0 ? (cost / visitors).toFixed(2) : '0.00'
    const logKey3 = `${productNmId}_${r.record_date}`
    const logContent3 = logMap[logKey3] || ''
    rows.push([currentProduct.value?.nm_id || currentProduct.value?.id || '', 'CPC搜索', r.record_date, impressions, visitors, cost, orders, cart, cartRate + '%', ctr.toFixed(2) + '%', conversion + '%', cpm, cpc, logContent3])
  }

  // 生成Excel并下载
  const wb = XLSX.utils.book_new()
  const ws = XLSX.utils.aoa_to_sheet(rows)
  XLSX.utils.book_append_sheet(wb, ws, '广告数据')

  // 关键词数据 sheet（仅当存在关键词时）
  const hasCpcKw = cpcKeywordsData.value && cpcKeywordsData.value.length > 0
  const hasCpmKw = cpmKeywordsData.value && cpmKeywordsData.value.length > 0
  if (hasCpcKw || hasCpmKw) {
    const kwRows = []
    kwRows.push(['产品ID', '类型', '关键词', '曝光', '点击', '花费', '订单', '加购', 'CTR', 'CPC', 'CPM', '平均排名', '加购率', '转化率'])
    if (hasCpcKw) {
      for (const k of cpcKeywordsData.value) {
        kwRows.push([
          currentProduct.value?.nm_id || currentProduct.value?.id || '', 'CPC搜索', k.keyword || '', k.views || 0, k.clicks || 0, k.spend || 0,
          k.orders || 0, k.atbs || 0,
          (k.ctr || 0).toFixed(2) + '%',
          (k.cpc || 0).toFixed(2),
          (k.cpm || 0).toFixed(2),
          (k.avg_position || 0).toFixed(1),
          (k.cart_rate || 0).toFixed(2) + '%',
          (k.conv_rate || 0).toFixed(2) + '%'
        ])
      }
    }
    if (hasCpmKw) {
      for (const k of cpmKeywordsData.value) {
        kwRows.push([
          currentProduct.value?.nm_id || currentProduct.value?.id || '', 'CPM搜索', k.keyword || '', k.views || 0, k.clicks || 0, k.spend || 0,
          k.orders || 0, k.atbs || 0,
          (k.ctr || 0).toFixed(2) + '%',
          (k.cpc || 0).toFixed(2),
          (k.cpm || 0).toFixed(2),
          (k.avg_position || 0).toFixed(1),
          (k.cart_rate || 0).toFixed(2) + '%',
          (k.conv_rate || 0).toFixed(2) + '%'
        ])
      }
    }
    const wsKw = XLSX.utils.aoa_to_sheet(kwRows)
    XLSX.utils.book_append_sheet(wb, wsKw, '关键词数据')
  }

  // 每日销售数据 sheet
  if (dailyData.value && dailyData.value.length > 0) {
    const salesRows = []
    salesRows.push(['日期', '销售额', '访客数', '订单数', '加购数', '广告花费', '加购率', '转化率', '广告占比', '日志内容'])
    const sortedDaily = [...dailyData.value].sort((a, b) => new Date(a.date) - new Date(b.date))
    for (const d of sortedDaily) {
      const visitors = d.total_visitors || 0
      const orders = d.orders || 0
      const cart = d.add_to_cart || 0
      const spend = d.ad_cost || d.spend || 0
      const sales = d.sales || 0
      const cartRate = visitors > 0 ? (cart / visitors * 100).toFixed(2) : '0.00'
      const convRate = visitors > 0 ? (orders / visitors * 100).toFixed(2) : '0.00'
      const adRatio = sales > 0 ? ((spend / sales) * 100).toFixed(2) : '0.00'
      const salesLogKey = `${productNmId}_${d.date}`
      const salesLogContent = logMap[salesLogKey] || ''
      salesRows.push([
        d.date || '',
        d.sales || 0,
        visitors,
        orders,
        cart,
        spend,
        cartRate + '%',
        convRate + '%',
        adRatio + '%',
        salesLogContent
      ])
    }
    const wsSales = XLSX.utils.aoa_to_sheet(salesRows)
    XLSX.utils.book_append_sheet(wb, wsSales, '每日销售数据')
  }

  const fileName = `${shopName}_${productName}_${dateFrom}_${dateTo}.xlsx`
  XLSX.writeFile(wb, fileName)
}

// 根据时间范围获取开始日期
function getDateFrom(timeRange) {
  const now = new Date()
  let days = 7
  if (timeRange === 'yesterday') days = 1
  else if (timeRange === '30days') days = 30
  else if (timeRange === '90days') days = 90
  else if (timeRange === '7days') days = 7

  const date = new Date(now.getTime() - days * 24 * 60 * 60 * 1000)
  return date.toISOString().split('T')[0]
}

// 生成模拟每日数据
// 筛选变化处理
const handleFilterChange = () => {
  console.log('筛选条件变化:', {
    selectedShop: selectedShop.value,
    selectedProduct: selectedProduct.value,
    quickType: quickType.value
  })

  // 当店铺变化时,重新加载产品列表
  if (selectedShop.value) {
    fetchProducts(selectedShop.value)
  }

  // 加载广告数据(只调用API获取真实数据,不使用mock覆盖)
  fetchAdData()
}

// 刷新数据（调用真实 API）
const refreshData = () => {
  ElMessage.success('数据刷新中...')
  fetchAdData()
}

// 导出报表
const exportReport = () => {
  ElMessage.info('导出报表功能开发中...')
}

// 查看详细报告
const viewDetailReport = () => {
  ElMessage.info('详细报告功能开发中...')
}

// 打开预警设置
const openAlertSettings = async () => {
  alertSettingsVisible.value = true
  await loadThresholds()
}

// 加载阈值配置
const loadThresholds = async () => {
  loadingThresholds.value = true
  try {
    const response = await axios.get('/api/metric-thresholds/')
    thresholds.value = response.data
    changedThresholds.value = new Set()
  } catch (error) {
    ElMessage.error('加载阈值配置失败')
  } finally {
    loadingThresholds.value = false
  }
}

// 标记阈值已修改
const handleThresholdChange = (row) => {
  changedThresholds.value.add(row.metric_name)
}

// 获取阈值显示值
const getThresholdDisplay = (metricName, type) => {
  const threshold = thresholds.value.find(t => t.metric_name === metricName)
  if (!threshold) return '-'

  const value = type === 'warning' ? threshold.warning_threshold : threshold.danger_threshold

  // 根据指标类型格式化显示
  if (metricName === 'acos') {
    return value != null ? (value * 100).toFixed(0) : '-'
  } else if (metricName === 'ctr' || metricName === 'natural_orders_ratio') {
    return value != null ? (value * 100).toFixed(0) : '-'
  } else {
    return value != null ? value.toFixed(1) : '-'
  }
}

// 保存所有阈值
const saveAllThresholds = async () => {
  saving.value = true
  try {
    // 保存所有修改过的阈值
    for (const metricName of changedThresholds.value) {
      const threshold = thresholds.value.find(t => t.metric_name === metricName)
      if (threshold) {
        await axios.put(`/api/metric-thresholds/${metricName}`, {
          display_name: threshold.display_name,
          warning_threshold: threshold.warning_threshold,
          danger_threshold: threshold.danger_threshold,
          good_color: threshold.good_color,
          warning_color: threshold.warning_color,
          danger_color: threshold.danger_color
        })
      }
    }

    ElMessage.success('预警设置已保存')
    alertSettingsVisible.value = false

    // 刷新页面数据以应用新颜色
    window.location.reload()
  } catch (error) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  setQuickDate('7days')
  // 加载店铺列表
  fetchShops().then(() => {
    // 如果有选中的店铺,加载产品列表
    if (selectedShop.value) {
      fetchProducts(selectedShop.value)
    }
    // 加载广告数据
    fetchAdData()
  })
})

// 监听产品变化,自动加载广告数据
watch(selectedProduct, (newProductId) => {
  if (newProductId) {
    fetchAdData()
  }
})

// 监听店铺变化
watch(selectedShop, (newShopId) => {
  if (newShopId) {
    fetchProducts(newShopId)
  } else {
    products.value = []
    selectedProduct.value = null
  }
})

// 初始化快捷日期(已在上面的 onMounted 中合并)
</script>

<style scoped>
.ad-analysis {
  padding: 20px;
  background: #f5f7fa;
  min-height: 100vh;
}

.filter-bar { display: flex; align-items: center; flex-wrap: wrap; gap: 16px; margin-bottom: 16px; padding: 12px 16px; background: #fff; border-radius: 8px; }
.data-info-bar { display: flex; flex-wrap: wrap; gap: 16px; margin-bottom: 12px; padding: 8px 16px; background: #f0f9eb; border: 1px solid #e1f3d8; border-radius: 6px; font-size: 13px; align-items: center; }
.data-info-item { display: flex; align-items: center; gap: 4px; color: #606266; }
.data-info-warning { color: #e6a23c; font-weight: 500; }
.filter-item { display: flex; align-items: center; gap: 8px; }
.filter-item.flex-1 { flex: 1; min-width: 150px; }

/* 产品信息横向展示 */
.product-info-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 20px;
  background: linear-gradient(135deg, #667eea08 0%, #764ba208 100%);
  border: 1px solid #e8eaf0;
  border-radius: 12px;
  margin-bottom: 16px;
}

.product-icon-wrap {
  font-size: 36px;
  line-height: 1;
}

.product-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.product-name-row {
  display: flex;
  align-items: center;
  gap: 10px;
}

.product-name {
  font-size: 16px;
  font-weight: 600;
  color: #1a1a2e;
}

.product-sub-row {
  display: flex;
  flex-wrap: wrap;
  gap: 16px;
}

.product-meta-item {
  font-size: 12px;
  color: #6b7280;
}

.loading-tip {
  color: #909399;
  font-size: 14px;
}

@media (max-width: 768px) {
  .filter-bar { flex-direction: column; align-items: stretch; gap: 8px; padding: 12px; }
  .filter-bar .filter-item { width: 100%; }
  .filter-bar .filter-item .el-button-group { width: 100%; display: flex; }
  .filter-bar .filter-item .el-button-group .el-button { flex: 1; padding: 8px 4px; font-size: 12px; }
  .filter-bar .filter-item .el-date-picker { width: 100% !important; }
  .filter-bar .filter-item .el-select { width: 100% !important; }
  .filter-bar .flex-1 { width: 100%; }
  .filter-bar > .el-button { width: 100%; margin-top: 8px; }
  .metrics-grid { display: flex; overflow-x: auto; gap: 10px; -webkit-overflow-scrolling: touch; scroll-snap-type: x mandatory; scrollbar-width: none; -ms-overflow-style: none; touch-action: pan-x; overscroll-behavior: none; }
  .metrics-grid::-webkit-scrollbar { display: none; }
  .metrics-grid .metric-card { min-width: 160px; flex-shrink: 0; scroll-snap-align: start; touch-action: pan-x; overscroll-behavior: none; }
  .metrics-grid .pie-card { min-width: 280px; }
}

.charts-row {
  margin-bottom: 20px;
}

.quick-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  padding: 16px;
  background: white;
  border-radius: 12px;
  flex-wrap: wrap;
}

.color-pickers {
  display: flex;
  gap: 4px;
  justify-content: center;
}

.threshold-help {
  margin-top: 16px;
}

.help-list {
  margin: 8px 0 0 0;
  padding-left: 20px;
  line-height: 1.8;
  font-size: 13px;
}

.help-list li {
  margin-bottom: 4px;
}

@media (max-width: 768px) {
  .ad-analysis {
    padding: 12px;
  }

  .charts-row .el-col {
    margin-bottom: 16px;
  }

  .quick-actions {
    justify-content: center;
  }
}

/* 核心指标卡片 */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
  margin-bottom: 16px;
}
.metric-card { background: #fff; border-radius: 16px; padding: 14px 14px 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.03); transition: transform 0.2s ease, box-shadow 0.2s ease; display: flex; flex-direction: column; }
.pie-card { padding: 14px 16px 12px; }
.pie-top-row { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.pie-label { font-size: 12px; font-weight: 500; color: #5b6e8c; }
.pie-total-pct { font-size: 14px; font-weight: 700; color: #1a1a2e; }
.donut-section { display: flex; align-items: center; gap: 14px; }
.donut-svg-full { width: 110px; height: 110px; flex-shrink: 0; }
.donut-text-main { font-size: 15px; font-weight: 700; fill: #1f2937; }
.donut-text-sub { font-size: 10px; fill: #9ca3af; }
.donut-legend-list { flex: 1; display: flex; flex-direction: column; gap: 7px; }
.dl-row { display: flex; align-items: center; gap: 6px; }
.dl-dot { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
.dl-val { font-size: 12px; font-weight: 600; color: #1f2937; min-width: 44px; text-align: right; }
.dl-pct { font-size: 12px; font-weight: 600; color: #9ca3af; min-width: 42px; text-align: right; }
.metric-header { position: relative; display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px; gap: 8px; flex-wrap: nowrap; overflow: visible; min-height: 20px; height: auto; flex-shrink: 0; width: 100%; box-sizing: border-box; }
.metric-label { display: inline-flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: #5b6e8c; flex-shrink: 0; white-space: nowrap; min-width: 0; }
.metric-value { display: flex; align-items: center; justify-content: flex-start; width: 100%; font-size: 16px; font-weight: 700; color: #0f172a; line-height: 1.1; letter-spacing: -0.02em; word-break: keep-all; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-height: 22px; flex-shrink: 0; }
.metric-change { position: absolute; right: 0; top: 50%; transform: translateY(-50%); font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 20px; white-space: nowrap; background-color: #f8fafc; flex-shrink: 0; }
.metric-change.positive { color: #10b981; background-color: rgba(16, 185, 129, 0.1); }
.metric-change.negative { color: #ef4444; background-color: rgba(239, 68, 68, 0.08); }
.metric-sub { position: absolute; right: 0; top: 50%; transform: translateY(-50%); font-size: 11px; font-weight: 600; padding: 3px 8px; border-radius: 20px; white-space: nowrap; flex-shrink: 0; }
.metric-sub.positive { color: #8b5cf6; background-color: rgba(139, 92, 246, 0.1); }
.metric-sub.negative { color: #f97316; background-color: rgba(249, 115, 22, 0.1); }
.pie-chart-container { }
.pie-label { }
.chart-area { width: 100%; margin-top: 4px; padding-top: 8px; border-top: 1px solid #eef2ff; }
.line-chart { width: 100%; height: 36px; display: block; }
.cpm-combined-card { background: rgba(230, 162, 60, 0.08) !important; border-color: rgba(230, 162, 60, 0.3) !important; }
.cpm-combined-card :deep(.el-card__header) { background: rgba(230, 162, 60, 0.05); border-bottom: 1px solid rgba(230, 162, 60, 0.2); }
.cpc-combined-card { background: rgba(16, 185, 129, 0.08) !important; border-color: rgba(16, 185, 129, 0.3) !important; }
.cpc-combined-card :deep(.el-card__header) { background: rgba(16, 185, 129, 0.05); border-bottom: 1px solid rgba(16, 185, 129, 0.2); }
.cpm-recommend-card { background: rgba(139, 92, 246, 0.08) !important; border-color: rgba(139, 92, 246, 0.3) !important; }
.cpm-recommend-card :deep(.el-card__header) { background: rgba(139, 92, 246, 0.05); border-bottom: 1px solid rgba(139, 92, 246, 0.2); }

/* Demo-aligned operations density overrides */
.ad-analysis { padding: 16px; background: var(--surface-page); }
.filter-bar,
.data-info-bar,
.product-info-bar {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface-panel);
  box-shadow: var(--shadow-sm);
}
.filter-bar { gap: 8px 10px; margin-bottom: 12px; padding: 10px; }
.data-info-bar { gap: 10px; margin-bottom: 12px; padding: 8px 10px; }
.data-info-warning { color: var(--color-warning); }
.product-info-bar {
  gap: 12px;
  margin-bottom: 12px;
  padding: 10px 12px;
  background: linear-gradient(90deg, var(--color-brand-soft), var(--surface-panel) 36%);
}
.product-icon-wrap {
  width: 34px;
  height: 34px;
  border-radius: var(--radius-lg);
  display: grid;
  place-items: center;
  background: var(--color-brand);
  color: #fff;
  font-size: 18px;
}
.product-name { color: var(--text-strong); font-size: 15px; font-weight: 750; }
.product-meta-item,
.pie-label,
.metric-label { color: var(--text-subtle); }
.metrics-grid { gap: 12px; margin-bottom: 12px; }
.metric-card {
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  box-shadow: var(--shadow-sm);
  padding: 12px;
}
.metric-card:hover { box-shadow: var(--shadow-md); }
.metric-value,
.pie-total-pct,
.dl-val { color: var(--text-strong); }
.donut-text-main { fill: var(--text-strong); }
.metric-value { letter-spacing: 0; }
.metric-change.positive { color: var(--color-success); background-color: var(--color-success-soft); }
.metric-change.negative { color: var(--color-danger); background-color: var(--color-danger-soft); }
.chart-area { border-top-color: var(--border-subtle); }
.cpm-combined-card,
.cpc-combined-card,
.cpm-recommend-card {
  border-radius: var(--radius-lg) !important;
  box-shadow: var(--shadow-sm) !important;
}
</style>
