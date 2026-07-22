<template>
  <div class="product-knowledge">
    <section class="toolbar">
      <el-input
        v-model="filters.search"
        placeholder="搜索产品名称 / SKU / nmId"
        clearable
        class="search-input"
        @keyup.enter="fetchKnowledge"
      >
        <template #append>
          <el-button :icon="Search" @click="fetchKnowledge" />
        </template>
      </el-input>
      <el-select v-model="filters.status" class="status-select" @change="fetchKnowledge">
        <el-option label="启用" value="active" />
        <el-option label="全部" value="all" />
        <el-option label="停用" value="archived" />
      </el-select>
      <el-button :loading="refreshing" @click="refreshFromProducts">同步产品档案</el-button>
    </section>

    <section class="summary-row">
      <div class="metric">
        <span>产品知识库</span>
        <strong>{{ total }}</strong>
      </div>
      <div class="metric">
        <span>AI可用</span>
        <strong>{{ aiReadyCount }}</strong>
      </div>
      <div class="metric">
        <span>平均完整度</span>
        <strong>{{ avgCompleteness }}%</strong>
      </div>
    </section>

    <section class="content-grid">
      <div class="list-panel">
        <el-table
          class="knowledge-table"
          :data="items"
          v-loading="loading"
          height="calc(100vh - 250px)"
          highlight-current-row
          @row-click="openItem"
        >
          <el-table-column prop="product_name" label="产品名称" min-width="180" fixed="left" />
          <el-table-column label="负责人" min-width="110">
            <template #default="{ row }">{{ row.owners.join(' / ') || '-' }}</template>
          </el-table-column>
          <el-table-column label="关联店铺" min-width="150">
            <template #default="{ row }">{{ row.shop_names.join(' / ') || '-' }}</template>
          </el-table-column>
          <el-table-column label="SKU" width="80">
            <template #default="{ row }">{{ row.linked_skus.length }}</template>
          </el-table-column>
          <el-table-column label="完整度" width="120">
            <template #default="{ row }">
              <el-progress :percentage="row.completeness" :stroke-width="8" />
            </template>
          </el-table-column>
          <el-table-column label="AI" width="90">
            <template #default="{ row }">
              <el-tag :type="row.ai_enabled ? 'success' : 'info'" size="small">
                {{ row.ai_enabled ? '可用' : '关闭' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>
        <div class="mobile-knowledge-list" v-loading="loading">
          <button
            v-for="item in items"
            :key="item.id"
            class="mobile-knowledge-card"
            :class="{ active: active?.id === item.id }"
            type="button"
            @click="openItem(item)"
          >
            <div class="mobile-card-head">
              <strong>{{ item.product_name }}</strong>
              <el-tag :type="item.ai_enabled ? 'success' : 'info'" size="small">
                {{ item.ai_enabled ? '可用' : '关闭' }}
              </el-tag>
            </div>
            <div class="mobile-card-meta">
              <span>{{ item.owners.join(' / ') || '-' }}</span>
              <span>{{ item.shop_names.join(' / ') || '-' }}</span>
            </div>
            <div class="mobile-card-foot">
              <span>SKU {{ item.linked_skus.length }}</span>
              <el-progress :percentage="item.completeness" :stroke-width="7" />
            </div>
          </button>
        </div>
      </div>

      <div class="detail-panel">
        <template v-if="active">
          <div class="detail-head">
            <div>
              <h2>{{ form.product_name }}</h2>
              <p>{{ form.shop_names.join(' / ') || '未关联店铺' }}</p>
            </div>
            <div class="head-actions">
              <el-switch v-model="form.ai_enabled" active-text="AI可用" inactive-text="AI关闭" />
              <el-button type="primary" :loading="saving" @click="saveActive">保存</el-button>
            </div>
          </div>

          <el-tabs v-model="activeTab" class="knowledge-tabs">
            <el-tab-pane label="基础" name="basic">
              <el-form label-position="top">
                <el-form-item label="基础信息（WB产品卡字段，只读）">
                  <el-input
                    v-model="form.basic_info"
                    type="textarea"
                    :rows="8"
                    readonly
                    placeholder="系统从 WB Content API 自动同步标题、品牌、类目、描述、参数/属性；该区域不可手工编辑。"
                  />
                </el-form-item>
                <el-form-item label="中文基础信息整理（由系统基于 WB 基础信息翻译，只读）">
                  <el-input
                    v-model="form.basic_info_zh"
                    type="textarea"
                    :rows="8"
                    readonly
                    placeholder="系统会基于上方 WB 俄语基础信息自动翻译整理成中文，供负责人阅读。该内容不作为客服 AI 草稿的产品事实来源。"
                  />
                </el-form-item>
                <el-form-item label="功能卖点">
                  <el-input
                    v-model="form.features"
                    type="textarea"
                    :rows="6"
                    placeholder="由产品负责人补充 WB 商品卡没有覆盖的功能卖点、能力边界、适用场景差异和买家关注点。"
                  />
                </el-form-item>
              </el-form>
            </el-tab-pane>
            <el-tab-pane label="使用方法" name="usage">
              <el-form label-position="top">
                <el-form-item label="使用方法 / 清洗保养 / 注意事项">
                  <el-input v-model="form.usage_guide" type="textarea" :rows="10" />
                </el-form-item>
              </el-form>
            </el-tab-pane>
            <el-tab-pane label="故障售后" name="support">
              <el-form label-position="top">
                <el-form-item label="故障解决办法">
                  <el-input v-model="form.troubleshooting" type="textarea" :rows="7" />
                </el-form-item>
                <el-form-item label="售后边界">
                  <el-input v-model="form.after_sales_policy" type="textarea" :rows="5" />
                </el-form-item>
              </el-form>
            </el-tab-pane>
            <el-tab-pane label="FAQ" name="faq">
              <div class="faq-toolbar">
                <el-button size="small" @click="addFaq">新增问题</el-button>
              </div>
              <div v-for="(faq, index) in form.faq" :key="index" class="faq-item">
                <el-input v-model="faq.question" placeholder="买家可能怎么问" />
                <el-input v-model="faq.answer_zh" type="textarea" :rows="3" placeholder="中文标准答案/处理说明，AI 会自动生成俄语草稿" />
                <el-button text type="danger" @click="removeFaq(index)">删除</el-button>
              </div>
            </el-tab-pane>
            <el-tab-pane label="内部备注" name="notes">
              <el-form label-position="top">
                <el-form-item label="中文内部备注">
                  <el-input
                    v-model="form.internal_notes_zh"
                    type="textarea"
                    :rows="8"
                    placeholder="只填写内部补充信息，不进入 AI 草稿生成；不要填写统一 AI 回复风格或提示词规则。"
                  />
                </el-form-item>
              </el-form>
            </el-tab-pane>
            <el-tab-pane label="关联信息" name="links">
              <div class="link-block">
                <b>SKU</b>
                <p>{{ form.linked_skus.join(' / ') || '-' }}</p>
              </div>
              <div class="link-block">
                <b>nmId</b>
                <p>{{ form.linked_nm_ids.join(' / ') || '-' }}</p>
              </div>
              <div class="link-block">
                <b>别名</b>
                <p>{{ form.aliases.join(' / ') || '-' }}</p>
              </div>
            </el-tab-pane>
          </el-tabs>
        </template>
        <el-empty v-else description="选择一个产品维护知识库" />
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import axios from 'axios'

const items = ref([])
const active = ref(null)
const loading = ref(false)
const saving = ref(false)
const refreshing = ref(false)
const activeTab = ref('basic')
const filters = reactive({ search: '', status: 'active' })

const form = reactive({
  id: null,
  product_name: '',
  aliases: [],
  linked_nm_ids: [],
  linked_skus: [],
  owners: [],
  shop_names: [],
  basic_info: '',
  basic_info_zh: '',
  features: '',
  usage_guide: '',
  troubleshooting: '',
  faq: [],
  after_sales_policy: '',
  internal_notes_zh: '',
  ai_enabled: true,
  status: 'active'
})

const total = computed(() => items.value.length)
const aiReadyCount = computed(() => items.value.filter(item => item.ai_enabled && item.completeness > 0).length)
const avgCompleteness = computed(() => {
  if (!items.value.length) return 0
  const sum = items.value.reduce((acc, item) => acc + (item.completeness || 0), 0)
  return Math.round(sum / items.value.length)
})

function fillForm(item) {
  Object.assign(form, {
    ...item,
    aliases: item.aliases || [],
    linked_nm_ids: item.linked_nm_ids || [],
    linked_skus: item.linked_skus || [],
    owners: item.owners || [],
    shop_names: item.shop_names || [],
    faq: Array.isArray(item.faq) ? item.faq : []
  })
}

async function fetchKnowledge() {
  loading.value = true
  try {
    const res = await axios.get('/api/product-knowledge/', { params: filters })
    items.value = res.data.items || []
    if (active.value) {
      const latest = items.value.find(item => item.id === active.value.id)
      if (latest) {
        active.value = latest
        fillForm(latest)
      }
    }
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '获取产品知识库失败')
  } finally {
    loading.value = false
  }
}

async function refreshFromProducts() {
  refreshing.value = true
  try {
    await axios.post('/api/product-knowledge/refresh-from-products')
    ElMessage.success('产品档案已同步')
    await fetchKnowledge()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '同步失败')
  } finally {
    refreshing.value = false
  }
}

async function openItem(row) {
  const res = await axios.get(`/api/product-knowledge/${row.id}`)
  active.value = res.data
  fillForm(res.data)
  activeTab.value = 'basic'
}

function addFaq() {
  form.faq.push({ question: '', answer_zh: '', ai_enabled: true })
}

function removeFaq(index) {
  form.faq.splice(index, 1)
}

async function saveActive() {
  if (!form.id) return
  saving.value = true
  try {
    const payload = {
      features: form.features,
      usage_guide: form.usage_guide,
      troubleshooting: form.troubleshooting,
      faq: form.faq,
      after_sales_policy: form.after_sales_policy,
      internal_notes_zh: form.internal_notes_zh,
      ai_enabled: form.ai_enabled,
      status: form.status
    }
    const res = await axios.put(`/api/product-knowledge/${form.id}`, payload)
    active.value = res.data.item
    fillForm(res.data.item)
    ElMessage.success('保存成功')
    await fetchKnowledge()
  } catch (error) {
    ElMessage.error(error?.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

onMounted(fetchKnowledge)
</script>

<style scoped>
.product-knowledge {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.toolbar {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.search-input {
  width: min(420px, 100%);
}

.status-select {
  width: 120px;
}

.summary-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(120px, 1fr));
  gap: 10px;
}

.metric {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 12px 14px;
  background: #fff;
}

.metric span {
  display: block;
  color: #6b7280;
  font-size: 13px;
}

.metric strong {
  display: block;
  margin-top: 6px;
  font-size: 22px;
  color: #111827;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(520px, 0.92fr) minmax(460px, 1.08fr);
  gap: 12px;
  min-height: 0;
}

.list-panel,
.detail-panel {
  min-width: 0;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.mobile-knowledge-list {
  display: none;
}

.detail-panel {
  padding: 16px;
  min-height: calc(100vh - 250px);
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #eef2f7;
  padding-bottom: 12px;
}

.detail-head h2 {
  margin: 0;
  font-size: 20px;
}

.detail-head p {
  margin: 6px 0 0;
  color: #6b7280;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.knowledge-tabs {
  margin-top: 12px;
}

.faq-toolbar {
  margin-bottom: 10px;
}

.faq-item {
  display: grid;
  gap: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  padding: 10px;
  margin-bottom: 10px;
}

.link-block {
  border-bottom: 1px solid #eef2f7;
  padding: 10px 0;
}

.link-block p {
  margin: 6px 0 0;
  color: #374151;
  word-break: break-word;
}

@media (max-width: 1100px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 430px) {
  .product-knowledge {
    gap: 10px;
    padding-bottom: 12px;
  }

  .toolbar {
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) 108px !important;
    flex-direction: initial !important;
    gap: 8px;
    align-items: stretch;
  }

  .search-input {
    grid-column: 1 / -1;
  }

  .search-input,
  .status-select,
  .toolbar :deep(.el-button) {
    width: 100%;
  }

  .toolbar :deep(.el-input__wrapper),
  .toolbar :deep(.el-select__wrapper),
  .toolbar :deep(.el-button) {
    min-height: 36px;
  }

  .toolbar > :deep(.el-button) {
    min-width: 0;
    padding: 0 8px;
  }

  .summary-row {
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 8px;
  }

  .metric {
    padding: 10px;
  }

  .metric span {
    font-size: 12px;
    line-height: 1.25;
  }

  .metric strong {
    font-size: 18px;
  }

  .content-grid {
    gap: 10px;
  }

  .list-panel {
    border: 0;
    background: transparent;
    overflow: visible !important;
  }

  .knowledge-table {
    display: none !important;
  }

  .mobile-knowledge-list {
    display: grid;
    gap: 8px;
    max-height: 46dvh;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
  }

  .mobile-knowledge-card {
    width: 100%;
    min-width: 0;
    display: grid;
    gap: 8px;
    padding: 10px;
    border: 1px solid #e5e7eb;
    border-radius: 6px;
    background: #fff;
    color: inherit;
    text-align: left;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
  }

  .mobile-knowledge-card.active {
    border-color: #409eff;
    box-shadow: 0 0 0 1px rgba(64, 158, 255, 0.12);
  }

  .mobile-card-head {
    display: grid;
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
    align-items: start;
  }

  .mobile-card-head strong {
    min-width: 0;
    color: #111827;
    font-size: 14px;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }

  .mobile-card-meta {
    display: grid;
    gap: 4px;
    color: #6b7280;
    font-size: 12px;
    line-height: 1.35;
  }

  .mobile-card-meta span {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .mobile-card-foot {
    display: grid;
    grid-template-columns: 54px minmax(0, 1fr);
    gap: 8px;
    align-items: center;
    color: #374151;
    font-size: 12px;
    font-weight: 700;
  }

  .detail-panel {
    padding: 12px;
    min-height: auto;
  }

  .detail-head {
    flex-direction: column;
    gap: 10px;
  }

  .detail-head h2 {
    font-size: 17px;
    line-height: 1.35;
    overflow-wrap: anywhere;
  }

  .detail-head p {
    font-size: 12px;
    line-height: 1.4;
    overflow-wrap: anywhere;
  }

  .head-actions {
    width: 100%;
    display: grid !important;
    grid-template-columns: minmax(0, 1fr) 96px !important;
    flex-wrap: initial !important;
    gap: 8px;
    justify-content: stretch;
  }

  .head-actions :deep(.el-button) {
    width: 100%;
  }

  .knowledge-tabs :deep(.el-tabs__content) {
    padding-top: 10px;
  }

  .knowledge-tabs :deep(.el-tabs__nav-wrap) {
    overflow: hidden;
  }

  .knowledge-tabs :deep(.el-tabs__nav-scroll) {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .knowledge-tabs :deep(.el-tabs__item) {
    padding: 0 10px;
    font-size: 13px;
  }

  .product-knowledge :deep(.el-textarea__inner) {
    min-height: 132px !important;
    font-size: 13px;
    line-height: 1.45;
  }

  .faq-item {
    padding: 10px;
  }
}
</style>
