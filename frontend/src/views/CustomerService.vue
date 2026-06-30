<template>
  <div class="customer-service-page">
    <div class="toolbar">
      <div class="toolbar-title">
        <h2>客服工作台</h2>
        <span>问答、评价、聊天、退货申请</span>
      </div>
      <div class="toolbar-actions" v-if="canManage">
        <el-button :loading="syncing" @click="syncCustomerService">同步客服数据</el-button>
      </div>
    </div>

    <!-- 4个模块统计卡片 -->
    <div class="channel-cards">
      <!-- 评论卡片 -->
      <div class="channel-card">
        <div class="channel-card-title">
          <span>买家评论</span>
          <el-tag size="small" type="danger" effect="plain">差评紧急</el-tag>
        </div>
        <div class="channel-card-items">
          <div class="channel-item" :class="{ 'has-count': stats.feedback_low_bad_unanswered }">
            <span class="channel-item-label">差评待回复</span>
            <span class="channel-item-num danger">{{ stats.feedback_low_bad_unanswered || 0 }}</span>
          </div>
          <div class="channel-item">
            <span class="channel-item-label">差评已回复</span>
            <span class="channel-item-num">{{ stats.feedback_low_bad_replied || 0 }}</span>
          </div>
          <div class="channel-item">
            <span class="channel-item-label">好评待回复</span>
            <span class="channel-item-num">{{ stats.feedback_high_bad_unanswered || 0 }}</span>
          </div>
          <div class="channel-item">
            <span class="channel-item-label">好评已回复</span>
            <span class="channel-item-num">{{ stats.feedback_high_bad_replied || 0 }}</span>
          </div>
        </div>
      </div>

      <!-- 问答卡片 -->
      <div class="channel-card">
        <div class="channel-card-title">
          <span>买家问答</span>
        </div>
        <div class="channel-card-items">
          <div class="channel-item" :class="{ 'has-count': stats.question_unanswered }">
            <span class="channel-item-label">待回复</span>
            <span class="channel-item-num danger">{{ stats.question_unanswered || 0 }}</span>
          </div>
          <div class="channel-item">
            <span class="channel-item-label">已回复</span>
            <span class="channel-item-num">{{ stats.question_answered || 0 }}</span>
          </div>
        </div>
      </div>

      <!-- 退货卡片 -->
      <div class="channel-card">
        <div class="channel-card-title">
          <span>买家退货</span>
          <el-tag size="small" type="danger" effect="plain">紧急</el-tag>
        </div>
        <div class="channel-card-items">
          <div class="channel-item" :class="{ 'has-count': stats.return_pending }">
            <span class="channel-item-label">待处理</span>
            <span class="channel-item-num danger">{{ stats.return_pending || 0 }}</span>
          </div>
          <div class="channel-item">
            <span class="channel-item-label">已拒绝</span>
            <span class="channel-item-num">-</span>
          </div>
          <div class="channel-item">
            <span class="channel-item-label">已同意</span>
            <span class="channel-item-num">-</span>
          </div>
        </div>
      </div>

      <!-- 聊天卡片 -->
      <div class="channel-card">
        <div class="channel-card-title">
          <span>买家聊天</span>
        </div>
        <div class="channel-card-items">
          <div class="channel-item" :class="{ 'has-count': stats.chat_unanswered }">
            <span class="channel-item-label">待回复</span>
            <span class="channel-item-num danger">{{ stats.chat_unanswered || 0 }}</span>
          </div>
          <div class="channel-item">
            <span class="channel-item-label">已回复</span>
            <span class="channel-item-num">{{ stats.chat_answered || 0 }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="filters">
      <el-input
        v-model="filters.search"
        placeholder="搜索 SKU / nmId / 买家 / 内容"
        clearable
        @keyup.enter="reload"
        @clear="reload"
      />
      <el-select v-model="filters.shop_id" placeholder="店铺" clearable @change="reload">
        <el-option v-for="shop in shops" :key="shop.id" :label="shop.name" :value="shop.id" />
      </el-select>
      <el-select v-model="filters.owner" placeholder="负责人" clearable @change="reload">
        <el-option v-for="owner in ownerOptions" :key="owner" :label="owner" :value="owner" />
      </el-select>
      <el-select v-model="filters.channel" placeholder="类型" @change="reload">
        <el-option label="全部类型" value="all" />
        <el-option label="问答" value="question" />
        <el-option label="评价" value="feedback" />
        <el-option label="买家聊天" value="chat" />
        <el-option label="退货申请" value="return_claim" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" @change="reload">
        <el-option label="待回复" value="unanswered" />
        <el-option label="全部状态" value="all" />
        <el-option label="已回复待买家" value="replied" />
        <el-option label="内部处理中" value="pending_internal" />
        <el-option label="已关闭" value="closed" />
      </el-select>
      <el-button type="primary" @click="reload">刷新</el-button>
    </div>

    <div class="workspace">
      <section class="queue" v-loading="loading" :class="{ 'hide-on-mobile': !!activeItem }">
        <button
          v-for="item in items"
          :key="item.id"
          :class="['queue-item', { active: activeItem?.id === item.id }]"
          @click="selectItem(item)"
        >
          <div class="queue-head">
            <el-tag size="small" :type="channelTag(item.channel)">{{ channelLabel(item.channel) }}</el-tag>
            <el-tag v-if="item.risk_level === 'urgent'" size="small" type="danger">紧急</el-tag>
            <el-tag v-else-if="item.risk_level === 'high'" size="small" type="warning">高风险</el-tag>
            <span class="time">{{ item.external_created_at || '-' }}</span>
          </div>
          <div class="product-line">
            <strong>{{ item.product_name || item.product_name_ru || item.sku || item.nm_id || '未匹配产品' }}</strong>
            <span v-if="item.channel === 'feedback' && item.rating" class="rating-stars">{{ item.rating_display || '' }}</span>
          </div>
          <div class="content-line">{{ item.content || '无文本内容' }}</div>
          <div class="meta-line">
            <span>{{ item.shop_name }}</span>
            <span>{{ item.owner || item.assigned_owner || '未分配' }}</span>

          </div>
          <div v-if="item.channel === 'return_claim'" class="countdown" :class="countdownClass(item)">
            退货处理剩余 {{ formatHours(item.sla_hours_left) }}
          </div>
        </button>

        <el-empty v-if="!loading && !items.length" description="暂无客服事项" />
      </section>

      <section class="detail" v-if="activeItem" :class="{ 'hide-on-mobile': !activeItem }">
        <div class="detail-head mobile-back">
          <el-button size="small" @click="activeItem = null" class="back-btn">← 返回列表</el-button>
        </div>
        <div class="detail-head">
          <div>
            <div class="detail-tags">
              <el-tag :type="channelTag(activeItem.channel)">{{ channelLabel(activeItem.channel) }}</el-tag>
              <el-tag :type="statusTag(activeItem.status)">{{ statusLabel(activeItem.status) }}</el-tag>
              <el-tag v-if="activeItem.channel === 'return_claim'" :type="countdownTag(activeItem)">
                剩余 {{ formatHours(activeItem.sla_hours_left) }}
              </el-tag>
            </div>
            <h3>{{ activeItem.product_name || activeItem.product_name_ru || activeItem.sku || activeItem.nm_id }}</h3>
            <p>{{ activeItem.shop_name }} / {{ activeItem.owner || activeItem.assigned_owner || '未分配负责人' }}</p>
          </div>
          <el-dropdown @command="handleStatusCommand">
            <el-button>处理状态</el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="pending_internal">转内部处理</el-dropdown-item>
                <el-dropdown-item command="closed">关闭</el-dropdown-item>
                <el-dropdown-item command="open">重新打开</el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>

        <div class="handler-box">
          <span>最后处理人：{{ activeItem.last_handled_by || '-' }}</span>
          <span>最后处理时间：{{ activeItem.last_handled_at || '-' }}</span>
          <span>首响人：{{ activeItem.first_replied_by || '-' }}</span>
          <span>首响时间：{{ activeItem.first_replied_at || '-' }}</span>
        </div>

        <div class="message-list">
          <div
            v-for="message in activeItem.messages || []"
            :key="message.id"
            :class="['message', message.direction]"
          >
            <div class="message-meta">
              <strong>{{ message.direction === 'seller' ? '客服' : '买家' }}</strong>
              <span>{{ message.created_at_external || message.created_at }}</span>
            </div>
            <div class="message-text">{{ message.message_text || '无文本内容' }}</div>
            <div v-if="message.attachments?.length" class="attachments">
              <el-button
                v-for="(attachment, index) in message.attachments"
                :key="index"
                size="small"
                @click="openAttachment(attachment)"
              >
                查看附件 {{ index + 1 }}
              </el-button>
            </div>
          </div>
        </div>

        <div v-if="activeItem.channel === 'return_claim'" class="return-actions">
          <div class="return-note">
            买家退货申请需在发起后 120 小时内处理，超时将自动批准。
          </div>
          <template v-if="returnActions.length">
            <el-button
              v-for="btn in returnActions"
              :key="btn.action"
              :type="btn.action.includes('reject') ? 'danger' : 'success'"
              :loading="answeringReturn"
              @click="answerReturn(btn.action)"
            >{{ btn.label }}</el-button>
          </template>
          <span v-else class="return-no-action">无可用操作（WB 后台已处理）</span>
        </div>

        <div v-else class="reply-box">
          <div class="reply-toolbar">
            <el-button v-if="activeItem.channel === 'question' && activeItem.reply_status !== 'answered'" 
              type="warning" :loading="rejectingQuestion" @click="rejectQuestion">拒绝问题</el-button>
            <el-button :loading="drafting" @click="generateDraft">生成俄语草稿</el-button>
            <span>AI 只生成草稿，发送前必须人工确认。</span>
          </div>
          <el-input
            v-model="replyText"
            type="textarea"
            :rows="6"
            :placeholder="activeItem.reply_status === 'answered' ? '请输入俄语修改回复内容' : '请输入俄语回复内容'"
          />
          <div class="reply-actions">
            <el-button @click="replyText = ''">清空</el-button>
            <el-button type="primary" :loading="sending" @click="sendReply">
              {{ activeItem.reply_status === 'answered' ? '修改回复' : '发送回复' }}
            </el-button>
          </div>
        </div>

      </section>

      <section class="detail empty hide-on-mobile" v-if="!activeItem">
        <el-empty description="请选择一条客服事项" />
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { useAuthStore } from '../stores/auth'

const authStore = useAuthStore()
const loading = ref(false)
const syncing = ref(false)
const drafting = ref(false)
const sending = ref(false)
const answeringReturn = ref(false)
const rejectingQuestion = ref(false)
const shops = ref([])
const items = ref([])
const activeItem = ref(null)
const stats = ref({})
const replyText = ref('')
const returnActions = ref([])

const filters = reactive({
  search: '',
  shop_id: null,
  owner: '',
  channel: 'all',
  status: 'open'
})

const canManage = computed(() => ['admin', 'manager'].includes(authStore.user?.role))
const ownerOptions = computed(() => {
  const set = new Set()
  const allowed = authStore.user?.allowed_owners
  if (Array.isArray(allowed)) {
    allowed.forEach(owner => owner && set.add(owner))
  }
  items.value.forEach(item => {
    if (item.owner) set.add(item.owner)
    if (item.assigned_owner) set.add(item.assigned_owner)
  })
  return Array.from(set)
})

onMounted(async () => {
  await Promise.all([loadShops(), loadStats(), loadItems()])
})

async function loadShops() {
  try {
    const res = await axios.get('/api/shops/')
    shops.value = res.data || []
  } catch (error) {
    shops.value = []
  }
}

async function loadStats() {
  const params = {}
  if (filters.shop_id) params.shop_id = filters.shop_id
  if (filters.owner) params.owner = filters.owner
  const res = await axios.get('/api/customer-service/stats', { params })
  stats.value = res.data || {}
}

async function loadItems() {
  loading.value = true
  try {
    const params = {
      search: filters.search,
      shop_id: filters.shop_id,
      owner: filters.owner,
      channel: filters.channel,
      status: filters.status,
      page: 1,
      page_size: 50
    }
    const res = await axios.get('/api/customer-service/inbox', { params })
    items.value = res.data.items || []
    if (activeItem.value) {
      const stillExists = items.value.find(item => item.id === activeItem.value.id)
      if (!stillExists) activeItem.value = null
    }
  } finally {
    loading.value = false
  }
}

async function reload() {
  await Promise.all([loadStats(), loadItems()])
}

async function selectItem(item) {
  const res = await axios.get(`/api/customer-service/items/${item.id}`)
  activeItem.value = res.data
  replyText.value = ''
  returnActions.value = []
  if (res.data.channel === 'return_claim') {
    try {
      const ar = await axios.get(`/api/customer-service/returns/${item.id}/actions`)
      returnActions.value = ar.data.actions || []
    } catch { returnActions.value = [] }
  }
}

async function syncCustomerService() {
  syncing.value = true
  try {
    const syncRes = await axios.post('/api/customer-service/sync', {
      shop_id: filters.shop_id || null,
      channel: filters.channel === 'all' ? 'all' : `${filters.channel}s`,
      days: 30
    })
    const logIds = syncRes.data.log_ids || []
    if (logIds.length === 0) {
      ElMessage.warning('没有可同步的店铺')
      return
    }
    // 轮询每个店铺的同步状态
    const promises = logIds.map((logId) => pollSyncStatus(logId))
    await Promise.all(promises)
    ElMessage.success('同步完成，刷新收件箱查看结果')
    await reload()
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '同步失败')
  } finally {
    syncing.value = false
  }
}

async function pollSyncStatus(logId, interval = 2000) {
  return new Promise((resolve) => {
    const timer = setInterval(async () => {
      try {
        const res = await axios.get(`/api/customer-service/sync-status/${logId}`)
        const status = res.data.status
        if (status === 'completed') {
          clearInterval(timer)
          resolve(res.data)
        } else if (status === 'rate_limited') {
          clearInterval(timer)
          ElMessage.warning(`店铺 ${res.data.shop_id} 同步被限流: ${res.data.message}`)
          resolve(res.data)
        } else if (status === 'failed') {
          clearInterval(timer)
          ElMessage.error(`店铺 ${res.data.shop_id} 同步失败: ${res.data.message}`)
          resolve(res.data)
        }
        // running: 继续等待
      } catch {
        clearInterval(timer)
        resolve(null)
      }
    }, interval)
    // 超时 5 分钟
    setTimeout(() => {
      clearInterval(timer)
      resolve(null)
    }, 300000)
  })
}

async function generateDraft() {
  if (!activeItem.value) return
  drafting.value = true
  try {
    const res = await axios.post(`/api/customer-service/items/${activeItem.value.id}/ai-draft`)
    const draft = res.data.draft || ''
    // 先保存草稿，再刷新详情（selectItem 会清空 replyText）
    replyText.value = draft
    await selectItem(activeItem.value)
    replyText.value = draft
  } finally {
    drafting.value = false
  }
}

async function sendReply() {
  if (!activeItem.value || !replyText.value.trim()) {
    ElMessage.warning('请填写回复内容')
    return
  }
  if (/[\u4e00-\u9fff]/.test(replyText.value)) {
    ElMessage.error('回复内容含中文，请改为俄语后再发送')
    return
  }
  sending.value = true
  try {
    await axios.post(`/api/customer-service/items/${activeItem.value.id}/reply`, {
      message: replyText.value.trim()
    })
    ElMessage.success('回复已发送')
    await Promise.all([selectItem(activeItem.value), reload()])
  } finally {
    sending.value = false
  }
}

async function answerReturn(action) {
  if (!activeItem.value) return
  let comment = ''
  if (action === 'rejectcustom') {
    // 拒绝并自定义回复：弹出文本框
    const { value } = await ElMessageBox.prompt(
      '请输入要发送给买家的拒绝原因（俄语）',
      '自定义拒绝回复',
      { confirmButtonText: '确认发送', cancelButtonText: '取消', inputType: 'textarea' }
    )
    if (!value || !value.trim()) {
      ElMessage.warning('请填写拒绝原因')
      return
    }
    comment = value.trim()
  } else {
    const labelMap = {
      autorefund1: '批准无需退货',
      approve2: '批准并回收商品',
      reject1: '拒绝退货：商品无缺陷',
      reject2: '拒绝退货：申请填写错误',
      reject3: '拒绝退货：请买家联系售后',
    }
    await ElMessageBox.confirm(`确认执行「${labelMap[action] || action}」？`, '退货处理确认', { type: 'warning' })
  }
  answeringReturn.value = true
  try {
    await axios.post(`/api/customer-service/returns/${activeItem.value.id}/answer`, {
      action,
      comment,
    })
    ElMessage.success('退货申请已处理')
    await Promise.all([selectItem(activeItem.value), reload()])
  } finally {
    answeringReturn.value = false
  }
}

async function rejectQuestion() {
  if (!activeItem.value) return
  await ElMessageBox.confirm('确认拒绝该问题？', '拒绝确认', { type: 'warning' })
  rejectingQuestion.value = true
  try {
    await axios.post(`/api/customer-service/questions/${activeItem.value.id}/reject`)
    ElMessage.success('问题已拒绝')
    await Promise.all([selectItem(activeItem.value), reload()])
  } finally {
    rejectingQuestion.value = false
  }
}

async function handleStatusCommand(status) {
  if (!activeItem.value) return
  await axios.patch(`/api/customer-service/items/${activeItem.value.id}/status`, { status })
  ElMessage.success('状态已更新')
  await Promise.all([selectItem(activeItem.value), reload()])
}

function openAttachment(attachment) {
  if (attachment.url) {
    window.open(attachment.url, '_blank')
    return
  }
  if (attachment.download_id) {
    window.open(`/api/customer-service/attachments/${attachment.download_id}`, '_blank')
  }
}

function channelLabel(channel) {
  return {
    question: '问答',
    feedback: '评价',
    chat: '聊天',
    return_claim: '退货'
  }[channel] || channel
}

function channelTag(channel) {
  return {
    question: '',
    feedback: 'success',
    chat: 'info',
    return_claim: 'warning'
  }[channel] || ''
}

function statusLabel(status) {
  return {
    open: '待处理',
    pending_internal: '内部处理中',
    replied: '已回复',
    closed: '已关闭',
    archived: '已归档'
  }[status] || status
}

function statusTag(status) {
  return {
    open: 'danger',
    pending_internal: 'warning',
    replied: 'success',
    closed: 'info'
  }[status] || ''
}

function countdownClass(item) {
  if (item.sla_hours_left === null || item.sla_hours_left === undefined) return ''
  if (item.sla_hours_left <= 6) return 'danger'
  if (item.sla_hours_left <= 24) return 'warning'
  return ''
}

function countdownTag(item) {
  const cls = countdownClass(item)
  return cls === 'danger' ? 'danger' : cls === 'warning' ? 'warning' : 'success'
}

function formatHours(hours) {
  if (hours === null || hours === undefined) return '-'
  if (hours <= 0) return '已超时'
  if (hours < 1) return `${Math.round(hours * 60)} 分钟`
  const h = Math.round(hours * 10) / 10
  if (h === Math.round(h)) return `${h} 小时`
  return `${h.toFixed(1)} 小时`
}
</script>

<style scoped>
.customer-service-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
}

.toolbar-title h2 {
  margin: 0;
  font-size: 22px;
  color: #0f172a;
}

.toolbar-title span,
.reply-toolbar span {
  color: #64748b;
  font-size: 13px;
}

.channel-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
}

.channel-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
}

.channel-card-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: #1e293b;
  margin-bottom: 12px;
  padding-bottom: 10px;
  border-bottom: 1px solid #f1f5f9;
}

.channel-card-items {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.channel-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #f8fafc;
}

.channel-item.has-count {
  background: #fef2f2;
}

.channel-item-label {
  font-size: 11px;
  color: #64748b;
}

.channel-item-num {
  font-size: 20px;
  font-weight: 700;
  color: #1e293b;
  line-height: 1.2;
}

.channel-item-num.danger {
  color: #dc2626;
}

.filters {
  display: grid;
  grid-template-columns: minmax(240px, 1.6fr) repeat(4, minmax(130px, 1fr)) auto;
  gap: 10px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(320px, 420px) minmax(0, 1fr);
  gap: 14px;
  min-height: calc(100vh - 260px);
}

.queue,
.detail {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
}

.queue {
  overflow: auto;
  padding: 8px;
}

.queue-item {
  width: 100%;
  display: block;
  text-align: left;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
}

.queue-item + .queue-item {
  margin-top: 8px;
}

.queue-item:hover,
.queue-item.active {
  border-color: #7b2d8e;
  background: #faf7fc;
}

.queue-head,
.meta-line,
.detail-tags,
.handler-box,
.reply-toolbar,
.reply-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.queue-head .time {
  margin-left: auto;
  color: #94a3b8;
  font-size: 12px;
}

.product-line {
  margin-top: 8px;
  color: #0f172a;
  font-size: 14px;
}

.content-line {
  margin-top: 6px;
  color: #334155;
  font-size: 13px;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.meta-line {
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
  justify-content: space-between;
}

.rating-stars {
  margin-left: 6px;
  color: #f59e0b;
  font-size: 12px;
  letter-spacing: 1px;
}


.countdown {
  margin-top: 8px;
  color: #166534;
  font-size: 13px;
  font-weight: 600;
}

.countdown.warning {
  color: #b45309;
}

.countdown.danger {
  color: #dc2626;
}

.detail {
  padding: 16px;
  overflow: auto;
}

.detail.empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  border-bottom: 1px solid #e2e8f0;
  padding-bottom: 14px;
}

.detail-head h3 {
  margin: 10px 0 4px;
  color: #0f172a;
  font-size: 20px;
}

.detail-head p {
  margin: 0;
  color: #64748b;
}

.handler-box {
  margin: 14px 0;
  padding: 10px;
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 13px;
}

.message-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 16px;
}

.message {
  max-width: 82%;
  padding: 12px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
}

.message.seller {
  margin-left: auto;
  background: #f6eff8;
  border-color: #e8d5ee;
}

.message-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: #64748b;
  font-size: 12px;
}

.message-text {
  margin-top: 8px;
  color: #0f172a;
  line-height: 1.6;
  white-space: pre-wrap;
}

.attachments {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.return-actions,
.reply-box {
  border-top: 1px solid #e2e8f0;
  padding-top: 14px;
}

.return-note {
  margin-bottom: 12px;
  color: #b45309;
  font-weight: 600;
}

.reply-toolbar {
  justify-content: space-between;
  margin-bottom: 10px;
}

.reply-actions {
  justify-content: flex-end;
  margin-top: 10px;
}

@media (max-width: 980px) {
  .channel-cards,
  .filters {
    grid-template-columns: 1fr;
  }
  .workspace {
    grid-template-columns: 1fr;
  }
  .queue {
    display: block;
  }
  .detail {
    display: block;
  }
  .queue.hide-on-mobile,
  .detail.hide-on-mobile {
    display: none;
  }
  .queue.show-on-mobile,
  .detail.show-on-mobile {
    display: block;
  }
  .mobile-back {
    display: flex;
  }
  .back-btn {
    margin-bottom: 8px;
  }
}

@media (min-width: 981px) {
  .mobile-back {
    display: none;
  }
}
</style>
