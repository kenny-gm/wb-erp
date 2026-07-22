<template>
  <div class="cpm-table-card">
    <div class="card-header">
      <h3>CPM推荐广告</h3>
      <div class="header-info">
        <span class="total-cost">总花费: {{ formatNumber(totalCost) }} {{ currencySymbol }}</span>
      </div>
    </div>
    
    <el-table 
      :data="tableData" 
      stripe
      style="width: 100%; min-width: 900px;"
      :fit="true"
    >
      <el-table-column prop="date" label="日期" min-width="110" fixed="left" />
      <el-table-column label="曝光" align="right" min-width="90">
        <template #default="props">
          {{ formatNumber(props.row.impressions) }}
        </template>
      </el-table-column>
      <el-table-column label="访客" align="right" min-width="80">
        <template #default="props">
          {{ formatNumber(props.row.visitors) }}
        </template>
      </el-table-column>
      <el-table-column label="花费" align="right" min-width="120">
        <template #default="props">
          {{ formatNumber(props.row.cost) }} {{ currencySymbol }}
        </template>
      </el-table-column>
      <el-table-column label="订单" align="right" min-width="70">
        <template #default="props">
          {{ formatNumber(props.row.orders) }}
        </template>
      </el-table-column>
      <el-table-column label="购物车" align="right" min-width="80">
        <template #default="props">
          {{ formatNumber(props.row.cart_count) }}
        </template>
      </el-table-column>
      <el-table-column label="加购率" align="right" min-width="80">
        <template #default="props">
          {{ props.row.visitors > 0 ? (props.row.cart_count / props.row.visitors * 100).toFixed(1) : '0.0' }}%
        </template>
      </el-table-column>
      <el-table-column label="CTR" align="right" min-width="70">
        <template #default="props">
          {{ props.row.ctr.toFixed(2) }}%
        </template>
      </el-table-column>
      <el-table-column label="转化" align="right" min-width="70">
        <template #default="props">
          {{ props.row.conversion_rate.toFixed(2) }}%
        </template>
      </el-table-column>
      <el-table-column label="CPM" align="right" min-width="90">
        <template #default="props">
          {{ calcCpm(props.row) }} {{ currencySymbol }}
        </template>
      </el-table-column>
      <el-table-column label="CPC" align="right" min-width="90">
        <template #default="props">
          {{ calcCpc(props.row) }} {{ currencySymbol }}
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: { type: Array, default: () => [] },
  currencySymbol: { type: String, default: '₽' }
})

const tableData = computed(() => {
  const dailyMap = {}
  
  for (const item of props.data) {
    const date = item.record_date ? item.record_date.split(' ')[0] : item.date
    
    if (!dailyMap[date]) {
      dailyMap[date] = {
        date,
        impressions: 0,
        visitors: 0,
        cost: 0,
        orders: 0,
        sales: 0,
        cart_count: 0
      }
    }
    
    dailyMap[date].impressions += item.impressions || 0
    dailyMap[date].visitors += item.visitors || 0
    dailyMap[date].cost += item.cost || 0
    dailyMap[date].orders += item.order_count || 0
    dailyMap[date].sales += item.sales || 0
    dailyMap[date].cart_count += item.cart_count || 0
  }
  
  return Object.values(dailyMap).map(day => ({
    ...day,
    ctr: day.impressions > 0 ? (day.visitors / day.impressions * 100) : 0,
    conversion_rate: day.visitors > 0 ? (day.orders / day.visitors * 100) : 0
  })).sort((a, b) => new Date(b.date) - new Date(a.date))
})

const totalCost = computed(() => {
  return tableData.value.reduce((sum, row) => sum + row.cost, 0)
})

function calcCpm(row) {
  if (!row.impressions) return '0.00'
  return (row.cost / row.impressions * 1000).toFixed(2)
}

function calcCpc(row) {
  if (!row.visitors) return '0.00'
  return (row.cost / row.visitors).toFixed(2)
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
</script>

<style scoped>
.cpm-table-card {
  background: #fff;
  border-radius: 12px;
  padding: 16px;
  margin-bottom: 16px;
  overflow-x: auto;
  -webkit-overflow-scrolling: touch;
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

.total-cost {
  font-size: 14px;
  color: #f97316;
  font-weight: 500;
}

:deep(.el-table) { font-size: 12px; }
:deep(.el-table th) { background-color: #f5f7fa; color: #606266; font-weight: 600; }
:deep(.el-table td) { padding: 6px 4px; }
</style>
