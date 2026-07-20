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
          :data="items"
          v-loading="loading"
          height="calc(100vh - 250px)"
          highlight-current-row
          @row-click="openItem"
        >
          <el-table-column prop="product_name" label="产品名称" min-width="180" />
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
                <el-form-item label="基础信息">
                  <el-input v-model="form.basic_info" type="textarea" :rows="6" />
                </el-form-item>
                <el-form-item label="功能卖点">
                  <el-input v-model="form.features" type="textarea" :rows="6" />
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
                <el-form-item label="AI回复禁区">
                  <el-input v-model="form.reply_rules" type="textarea" :rows="5" />
                </el-form-item>
              </el-form>
            </el-tab-pane>
            <el-tab-pane label="FAQ" name="faq">
              <div class="faq-toolbar">
                <el-button size="small" @click="addFaq">新增问题</el-button>
              </div>
              <div v-for="(faq, index) in form.faq" :key="index" class="faq-item">
                <el-input v-model="faq.question" placeholder="买家可能怎么问" />
                <el-input v-model="faq.answer_ru" type="textarea" :rows="3" placeholder="俄语标准回答" />
                <el-input v-model="faq.answer_zh" type="textarea" :rows="2" placeholder="中文内部说明" />
                <el-button text type="danger" @click="removeFaq(index)">删除</el-button>
              </div>
            </el-tab-pane>
            <el-tab-pane label="俄语示例" name="examples">
              <el-form label-position="top">
                <el-form-item label="俄语回复示例">
                  <el-input v-model="form.answer_examples_ru" type="textarea" :rows="8" />
                </el-form-item>
                <el-form-item label="中文内部备注">
                  <el-input v-model="form.internal_notes_zh" type="textarea" :rows="6" />
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
  features: '',
  usage_guide: '',
  troubleshooting: '',
  faq: [],
  after_sales_policy: '',
  reply_rules: '',
  answer_examples_ru: '',
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
  form.faq.push({ question: '', answer_ru: '', answer_zh: '', ai_enabled: true })
}

function removeFaq(index) {
  form.faq.splice(index, 1)
}

async function saveActive() {
  if (!form.id) return
  saving.value = true
  try {
    const payload = {
      basic_info: form.basic_info,
      features: form.features,
      usage_guide: form.usage_guide,
      troubleshooting: form.troubleshooting,
      faq: form.faq,
      after_sales_policy: form.after_sales_policy,
      reply_rules: form.reply_rules,
      answer_examples_ru: form.answer_examples_ru,
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
</style>
