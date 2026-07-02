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
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'feedback_low_bad_unanswered', 'has-count': stats.feedback_low_bad_unanswered }" @click="setQuickKey('feedback_low_bad_unanswered')">
            <span class="channel-item-label">差评待回复</span>
            <span class="channel-item-num danger">{{ stats.feedback_low_bad_unanswered || 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'feedback_low_bad_replied' }" @click="setQuickKey('feedback_low_bad_replied')">
            <span class="channel-item-label">差评已回复</span>
            <span class="channel-item-num">{{ stats.feedback_low_bad_replied || 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'feedback_high_bad_unanswered' }" @click="setQuickKey('feedback_high_bad_unanswered')">
            <span class="channel-item-label">好评待回复</span>
            <span class="channel-item-num">{{ stats.feedback_high_bad_unanswered || 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'feedback_high_bad_replied' }" @click="setQuickKey('feedback_high_bad_replied')">
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
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'question_unanswered', 'has-count': stats.question_unanswered }" @click="setQuickKey('question_unanswered')">
            <span class="channel-item-label">待回复</span>
            <span class="channel-item-num danger">{{ stats.question_unanswered || 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'question_answered' }" @click="setQuickKey('question_answered')">
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
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'return_pending', 'has-count': stats.return_pending }" @click="setQuickKey('return_pending')">
            <span class="channel-item-label">待处理</span>
            <span class="channel-item-num danger">{{ stats.return_pending || 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'return_closed' }" @click="setQuickKey('return_closed')">
            <span class="channel-item-label">已处理</span>
            <span class="channel-item-num">{{ stats.return_closed || 0 }}</span>
          </div>
        </div>
      </div>

      <!-- 聊天卡片 -->
      <div class="channel-card">
        <div class="channel-card-title">
          <span>买家聊天</span>
        </div>
        <div class="channel-card-items">
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'chat_unanswered', 'has-count': stats.chat_unanswered }" @click="setQuickKey('chat_unanswered')">
            <span class="channel-item-label">待回复</span>
            <span class="channel-item-num danger">{{ stats.chat_unanswered || 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'chat_answered' }" @click="setQuickKey('chat_answered')">
            <span class="channel-item-label">已回复</span>
            <span class="channel-item-num">{{ stats.chat_answered || 0 }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 快速筛选标签 -->
    <div v-if="filters.quick_key" class="quick-filter-tag">
      <span>当前筛选：{{ quickKeyLabel }}</span>
      <el-button size="small" circle @click="clearQuickKey" class="clear-quick-btn">✕</el-button>
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
      <el-select v-model="filters.channel" placeholder="类型" @change="handleChannelStatusChange">
        <el-option label="全部类型" value="all" />
        <el-option label="问答" value="question" />
        <el-option label="评价" value="feedback" />
        <el-option label="买家聊天" value="chat" />
        <el-option label="退货申请" value="return_claim" />
      </el-select>
      <el-select v-model="filters.status" placeholder="状态" @change="handleChannelStatusChange">
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
        <div class="queue-items-wrapper">
          <button
            v-for="item in items"
            :key="item.id"
            :class="['queue-item', { active: activeItem?.id === item.id }]"
            @click="selectItem(item)"
          >
            <div class="queue-head">
              <el-tag size="small" :type="channelTag(item.channel)">{{ channelLabel(item.channel) }}</el-tag>
              <el-tag
                v-if="getDisplayStatus(item)"
                size="small"
                :type="getDisplayStatus(item).type"
                effect="dark"
                class="status-tag"
              >{{ getDisplayStatus(item).label }}</el-tag>
              <el-tag v-if="item.risk_level === 'urgent'" size="small" type="danger">紧急</el-tag>
              <el-tag v-else-if="item.risk_level === 'high'" size="small" type="warning">高风险</el-tag>
              <span class="time">{{ item.external_created_at || '-' }}</span>
            </div>
            <div class="product-line">
              <span class="product-name" :class="{ 'product-name-empty': !item.product_name && !item.product_name_ru }">
                {{ item.product_name || item.product_name_ru || '(无产品名)' }}
              </span>
              <el-tag type="info" size="small" class="nmid-tag">nmId {{ item.nm_id || '-' }}</el-tag>
              <el-tag type="warning" size="small" class="sku-tag">SKU {{ item.sku || '-' }}</el-tag>
              <span v-if="item.channel === 'feedback' && item.rating" class="rating-stars">{{ item.rating_display || '' }}</span>
            </div>
            <div class="content-line">{{ item.content_zh || item.content || '无文本内容' }}</div>
            <div v-if="item.content_zh" class="original-hint">已翻译，详情可查看俄语原文</div>
            <div class="meta-line">
              <span>{{ item.shop_name }}</span>
              <span>{{ item.owner || item.assigned_owner || '未分配' }}</span>

            </div>
            <div v-if="item.channel === 'return_claim'" class="countdown" :class="countdownClass(item)">
              退货处理剩余 {{ formatHours(item.sla_hours_left) }}
            </div>
          </button>

          <el-empty v-if="!loading && !items.length" description="暂无客服事项" />
        </div>
      </section>

      <section class="detail" v-if="activeItem" :class="{ 'hide-on-mobile': !activeItem }">
        <div class="mobile-back">
          <el-button size="small" @click="activeItem = null" class="back-btn">← 返回列表</el-button>
        </div>

        <!-- ── 三层结构详情头部 ─────────────────── -->
        <div class="detail-header">
          <div class="detail-main">
            <!-- 第一层：类型 · 状态 · 风险 · WB ID · 时间 -->
            <div class="detail-meta-row">
              <el-tag size="small" :type="channelTag(activeItem.channel)">{{ channelLabel(activeItem.channel) }}</el-tag>
              <el-tag
                v-if="getDisplayStatus(activeItem)"
                size="small"
                :type="getDisplayStatus(activeItem).type"
                effect="dark"
                class="status-tag"
              >{{ getDisplayStatus(activeItem).label }}</el-tag>
              <el-tag v-if="activeItem.risk_level === 'urgent'" size="small" type="danger">紧急</el-tag>
              <el-tag v-else-if="activeItem.risk_level === 'high'" size="small" type="warning">高风险</el-tag>
              <span class="detail-id">WB #{{ activeItem.external_id?.slice(0, 8) || '-' }}</span>
              <span class="detail-time">{{ activeItem.external_created_at || '-' }}</span>
            </div>

            <!-- 第二层：产品名称 -->
            <div class="detail-title-row">
              <h3 :class="{ 'product-name-empty': !activeItem.product_name && !activeItem.product_name_ru }">
                {{ activeItem.product_name || activeItem.product_name_ru || '(无产品名)' }}
              </h3>
            </div>

            <!-- 第三层：店铺 · 负责人 · nmId · SKU -->
            <div class="detail-sub-row">
              <span>店铺：{{ activeItem.shop_name || '-' }}</span>
              <span>负责人：{{ activeItem.owner || activeItem.assigned_owner || '未分配' }}</span>
              <el-tag size="small" type="info" class="nmid-tag">nmId {{ activeItem.nm_id || '-' }}</el-tag>
              <el-tag size="small" type="warning" class="sku-tag">SKU {{ activeItem.sku || '-' }}</el-tag>
            </div>

            <!-- 退货倒计时 ────────────────────────── -->
            <div v-if="activeItem.channel === 'return_claim'" class="detail-sla" :class="countdownClass(activeItem)">
              退货处理剩余 {{ formatHours(activeItem.sla_hours_left) }}
            </div>
          </div>

          <!-- 右侧操作按钮 ────────────────────────── -->
          <div class="detail-actions">
            <el-button size="small" plain :loading="translatingItem" @click="translateItem">翻译事项</el-button>
            <el-dropdown @command="handleStatusCommand" size="small">
              <el-button plain size="small">处理状态</el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="pending_internal">转内部处理</el-dropdown-item>
                  <el-dropdown-item command="closed">关闭</el-dropdown-item>
                  <el-dropdown-item command="open">重新打开</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <!-- item 翻译结果 -->
        <div v-if="activeItem.content_zh" class="translation-box">
          <div class="translation-title">中文翻译</div>
          <div>{{ activeItem.content_zh }}</div>
          <details>
            <summary class="original-hint">查看俄语原文</summary>
            <div class="message-text">{{ activeItem.content }}</div>
          </details>
        </div>
        <div v-else-if="activeItem.content" class="message-text" style="margin: 12px 0">{{ activeItem.content }}</div>

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
              <el-button
                v-if="message.direction !== 'seller'"
                size="small"
                text
                type="primary"
                :loading="translatingMessageId === message.id"
                @click="translateMessage(message)"
              >翻译</el-button>
            </div>
            <div v-if="message.message_text_zh" class="message-translation">{{ message.message_text_zh }}</div>
            <details v-if="message.message_text_zh" class="original-hint">
              <summary>俄语原文</summary>
              <div class="message-text">{{ message.message_text }}</div>
            </details>
            <div v-else class="message-text">{{ message.message_text || '无文本内容' }}</div>
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

        <!-- 拒绝原因二级弹窗（置于条件链之外） -->
        <el-dialog v-model="rejectDialogVisible" title="选择拒绝原因" width="420px" :close-on-click-modal="false">
          <div class="reject-choice-list">
            <div class="reject-choice-item" @click="answerReturnConfirm('reject1')">
              <strong>商品无缺陷，拒绝退款请求</strong>
              <p>将通知买家：商品检查无问题，无法满足退款要求</p>
            </div>
            <div class="reject-choice-item" @click="answerReturnConfirm('reject2')">
              <strong>申请填写错误或信息不足</strong>
              <p>将通知买家：申请信息不完整，请重新填写</p>
            </div>
            <div class="reject-choice-item" @click="answerReturnConfirm('reject3')">
              <strong>建议联系售后/服务中心</strong>
              <p>将通知买家：请前往售后或服务中心处理</p>
            </div>
            <div class="reject-choice-item reject-choice-custom" @click="openRejectCustom">
              <strong>💬 自定义回复内容</strong>
              <p>手动输入要发送给买家的俄语拒绝理由</p>
            </div>
          </div>
        </el-dialog>

        <!-- 自定义拒绝内容弹窗 -->
        <el-dialog v-model="rejectCustomDialogVisible" title="自定义拒绝回复" width="500px" :close-on-click-modal="false">
          <p style="margin-bottom:12px;color:#b45309;font-size:13px">请输入要发送给买家的俄语拒绝理由，将直接发送至买家。</p>
          <el-input
            v-model="rejectCustomText"
            type="textarea"
            :rows="5"
            placeholder="在此输入俄语拒绝理由..."
          />
          <template #footer>
            <el-button @click="rejectCustomDialogVisible = false">取消</el-button>
            <el-button type="primary" :loading="answeringReturn" @click="confirmRejectCustom">确认发送</el-button>
          </template>
        </el-dialog>

        <div v-if="activeItem.channel === 'return_claim'" class="return-actions">
          <div class="return-note">
            买家退货申请需在发起后 120 小时内处理，超时将自动批准。
          </div>
          <template v-if="returnActions.length">
            <el-button
              v-for="btn in returnActions"
              :key="btn.action"
              :type="btn.action === '_reject' ? 'danger' : 'success'"
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
const rejectDialogVisible = ref(false)
const rejectCustomDialogVisible = ref(false)
const rejectCustomText = ref('')
const shops = ref([])
const items = ref([])
const activeItem = ref(null)
const stats = ref({})
const replyText = ref('')
const returnActions = ref([])
const translatingItem = ref(false)
const translatingMessageId = ref(null)

const filters = reactive({
  search: '',
  shop_id: null,
  owner: '',
  channel: 'all',
  status: 'open',
  quick_key: null
})

const canManage = computed(() => ['admin', 'manager'].includes(authStore.user?.role))

const QUICK_KEY_MAP = {
  feedback_low_bad_unanswered: '差评待回复',
  feedback_low_bad_replied: '差评已回复',
  feedback_high_bad_unanswered: '好评待回复',
  feedback_high_bad_replied: '好评已回复',
  question_unanswered: '问答待回复',
  question_answered: '问答已回复',
  return_pending: '退货待处理',
  return_closed: '退货已处理',
  chat_unanswered: '聊天待回复',
  chat_answered: '聊天已回复',
}

const QUICK_FILTER_STATE = {
  feedback_low_bad_unanswered: { channel: 'feedback', status: 'unanswered' },
  feedback_low_bad_replied: { channel: 'feedback', status: 'all' },
  feedback_high_bad_unanswered: { channel: 'feedback', status: 'unanswered' },
  feedback_high_bad_replied: { channel: 'feedback', status: 'all' },
  question_unanswered: { channel: 'question', status: 'unanswered' },
  question_answered: { channel: 'question', status: 'all' },
  return_pending: { channel: 'return_claim', status: 'unanswered' },
  return_closed: { channel: 'return_claim', status: 'closed' },
  chat_unanswered: { channel: 'chat', status: 'unanswered' },
  chat_answered: { channel: 'chat', status: 'all' },
}

const quickKeyLabel = computed(() => QUICK_KEY_MAP[filters.quick_key] || null)

/**
 * 客服事项业务状态兜底计算。
 * 优先用后端返回的 display_status；后端未返回时根据 channel/status/reply_status 推断。
 */
function getDisplayStatus(item) {
  if (!item) return null
  if (item.display_status && item.display_status.label) {
    return item.display_status
  }

  if (item.status === 'archived') {
    return { key: 'archived', label: '已归档', type: 'info' }
  }
  if (item.status === 'closed') {
    if (item.channel === 'return_claim') {
      return { key: 'return_closed', label: '退货已处理', type: 'info' }
    }
    return { key: 'closed', label: '已关闭', type: 'info' }
  }
  if (item.status === 'pending_internal') {
    return { key: 'pending_internal', label: '内部处理中', type: 'warning' }
  }

  if (item.channel === 'chat') {
    if (item.reply_status === 'unanswered') {
      return { key: 'waiting_seller', label: '待卖家回复', type: 'danger' }
    }
    if (item.status === 'replied' || item.reply_status === 'answered') {
      return { key: 'waiting_buyer', label: '待买家回复', type: 'success' }
    }
    return { key: 'chat_open', label: '聊天处理中', type: 'warning' }
  }

  if (item.channel === 'return_claim') {
    if (item.status === 'open' && item.reply_status === 'unanswered') {
      return { key: 'return_pending', label: '退货待处理', type: 'danger' }
    }
    return { key: 'return_open', label: '退货处理中', type: 'warning' }
  }

  if (item.reply_status === 'unanswered') {
    return { key: 'unanswered', label: '待回复', type: 'danger' }
  }
  if (item.reply_status === 'answered') {
    return { key: 'answered', label: '已回复', type: 'success' }
  }

  return {
    key: item.status || 'open',
    label: statusLabel(item.status || 'open'),
    type: statusTag(item.status || 'open') || 'danger',
  }
}

function setQuickKey(key) {
  if (filters.quick_key === key) {
    clearQuickKey()
  } else {
    filters.quick_key = key
    const next = QUICK_FILTER_STATE[key]
    if (next) {
      filters.channel = next.channel
      filters.status = next.status
    }
    activeItem.value = null
    reload()
  }
}

function clearQuickKey() {
  filters.quick_key = null
  filters.channel = 'all'
  filters.status = 'open'
  activeItem.value = null
  reload()
}

async function handleChannelStatusChange() {
  // 手动切换类型/状态时清除 quick_key，避免与顶部快捷筛选冲突
  filters.quick_key = null
  activeItem.value = null
  await Promise.all([loadStats(), loadItems()])
}
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
      quick_key: filters.quick_key || undefined,
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
    replyText.value = draft
    await selectItem(activeItem.value)
    replyText.value = draft
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '生成草稿失败')
  } finally {
    drafting.value = false
  }
}

async function translateItem() {
  if (!activeItem.value) return
  translatingItem.value = true
  try {
    const res = await axios.post(`/api/customer-service/items/${activeItem.value.id}/translate`)
    if (res.data.success) {
      ElMessage.success(res.data.cached ? '已有翻译' : '翻译完成')
    } else {
      ElMessage.error(res.data.error || '翻译失败')
    }
    await selectItem(activeItem.value)
  } finally {
    translatingItem.value = false
  }
}

async function translateMessage(message) {
  translatingMessageId.value = message.id
  try {
    const res = await axios.post(`/api/customer-service/messages/${message.id}/translate`)
    if (res.data.success) {
      ElMessage.success(res.data.cached ? '已有翻译' : '翻译完成')
    } else {
      ElMessage.error(res.data.error || '翻译失败')
    }
    await selectItem(activeItem.value)
  } finally {
    translatingMessageId.value = null
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

  // 拒绝退货：弹出二级选择弹窗
  if (action === '_reject') {
    rejectDialogVisible.value = true
    return
  }

  // 批准类直接确认
  const labelMap = {
    autorefund1: '批准无需退货',
    approve2: '批准并回收商品',
  }
  await ElMessageBox.confirm(`确认执行「${labelMap[action] || action}」？`, '退货处理确认', { type: 'warning' })
  await doAnswerReturn(action, '')
}

async function answerReturnConfirm(rejectAction) {
  rejectDialogVisible.value = false
  await doAnswerReturn(rejectAction, '')
}

function openRejectCustom() {
  rejectCustomText.value = ''
  rejectDialogVisible.value = false
  rejectCustomDialogVisible.value = true
}

async function confirmRejectCustom() {
  if (!rejectCustomText.value.trim()) {
    ElMessage.warning('请输入拒绝理由')
    return
  }
  rejectCustomDialogVisible.value = false
  await doAnswerReturn('rejectcustom', rejectCustomText.value.trim())
}

async function doAnswerReturn(action, comment) {
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
/* ── 整体：自然文档流，不固定高度 ─────────────── */
.customer-service-page {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-height: 100%;
}

.toolbar {
  flex-shrink: 0;
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

/* ── 统计卡片自适应 ──────────────────────────── */
.channel-cards {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
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

.channel-item.clickable {
  cursor: pointer;
  transition: background 0.12s, border-color 0.12s;
}

.channel-item.clickable:hover {
  background: #f0f7ff;
  border-color: #bfdbfe;
}

.channel-item.clickable.active {
  background: #dbeafe;
  border-color: #93c5fd;
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

/* ── 筛选栏自适应 ───────────────────────────── */
.filters {
  flex-shrink: 0;
  display: grid;
  grid-template-columns: minmax(220px, 1.6fr) repeat(auto-fit, minmax(140px, 1fr));
  gap: 10px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px;
}

/* 快速筛选标签 */
.quick-filter-tag {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  font-size: 13px;
  color: #1d4ed8;
  font-weight: 500;
}

.clear-quick-btn {
  font-size: 11px;
  padding: 2px 5px;
  min-height: auto;
  line-height: 1;
  color: #60a5fa;
  border-color: #bfdbfe;
}

.filters .el-button {
  min-width: 88px;
}

/* ── Workspace：双栏 grid，左侧顶部对齐 ─────── */
.workspace {
  display: grid;
  grid-template-columns: minmax(360px, 460px) minmax(0, 1fr);
  align-items: start;
  gap: 14px;
  min-height: 720px;
  height: auto;
}

/* ── 左侧列表：有最大高度，内部滚动 ─────────── */
.queue,
.detail {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  overflow: hidden;
}

.queue {
  display: flex;
  flex-direction: column;
  min-height: 720px;
  max-height: calc(100vh - 120px);
  overflow: hidden;
  padding: 8px;
}

.queue-items-wrapper {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.queue-item {
  width: 100%;
  display: block;
  text-align: left;
  padding: 12px;
  border: 1px solid transparent;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  min-height: 104px;
}

.queue-item + .queue-item {
  margin-top: 8px;
}

.queue-items-wrapper::-webkit-scrollbar {
  width: 4px;
}

.queue-items-wrapper::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 2px;
}

.queue-item:hover,
.queue-item.active {
  background: #f0f7ff;
  border-color: #bfdbfe;
}

.queue-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 5px;
  font-size: 12px;
  color: #64748b;
  min-height: 24px;
}

.queue-head .time {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 11px;
}

.product-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin: 8px 0 4px;
  font-size: 13px;
  line-height: 1.5;
}

/* 状态 tag */
.status-tag {
  font-weight: 600;
  font-size: 11px;
}

.product-line .product-name {
  font-weight: 700;
  color: #0f172a;
  margin-right: 4px;
}

.product-line .product-name-empty {
  color: #94a3b8;
  font-style: italic;
}

.product-line .nmid-tag,
.product-badges .nmid-tag {
  background: #ede9fe;
  border-color: #c4b5fd;
  color: #5b21b6;
  font-weight: 600;
}

.product-line .sku-tag,
.product-badges .sku-tag {
  background: #fef3c7;
  border-color: #fcd34d;
  color: #92400e;
  font-weight: 600;
}

.content-line {
  font-size: 13px;
  color: #475569;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
  word-break: break-word;
  margin-top: 6px;
}

.original-hint {
  font-size: 11px;
  color: #94a3b8;
  cursor: pointer;
  margin-top: 2px;
}

.meta-line {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #94a3b8;
  margin-top: 8px;
  line-height: 1.5;
}

.countdown {
  margin-top: 8px;
  font-size: 12px;
  font-weight: 600;
  color: #64748b;
  line-height: 1.5;
}

.countdown.danger {
  color: #dc2626;
  font-weight: 700;
  font-size: 14px;
  animation: pulse-red 1.5s ease-in-out infinite;
}

@keyframes pulse-red {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

/* ── 右侧详情区：自然高度 ───────────────────── */
.detail {
  min-height: 720px;
  height: auto;
  overflow: visible;
  display: flex;
  flex-direction: column;
  padding: 16px;
  box-sizing: border-box;
}

.detail.empty {
  display: flex;
  align-items: center;
  justify-content: center;
}

/* ── 三层结构详情头部 ─────────────────────── */
.detail-header {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid #e2e8f0;
}

.detail-main {
  min-width: 0;
}

.detail-meta-row {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.detail-id,
.detail-time {
  font-size: 12px;
  color: #94a3b8;
}

.detail-title-row h3 {
  margin: 0;
  font-size: 18px;
  line-height: 1.35;
  font-weight: 700;
  color: #0f172a;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.detail-title-row h3.product-name-empty {
  color: #94a3b8;
  font-style: italic;
  font-weight: 400;
}

.detail-sub-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  margin-top: 8px;
  font-size: 13px;
  color: #64748b;
}

/* 退货倒计时醒目样式 */
.detail-sla {
  display: inline-flex;
  align-items: center;
  margin-top: 10px;
  padding: 5px 10px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  background: #f0fdf4;
  color: #166534;
}

.detail-sla.warning {
  background: #fffbeb;
  color: #b45309;
}

.detail-sla.danger {
  background: #fef2f2;
  color: #dc2626;
  animation: pulse-red 1.5s ease-in-out infinite;
}

/* 右侧操作按钮区 */
.detail-actions {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  flex-shrink: 0;
}

/* ── 长文本防溢出 ───────────────────────────── */
.message,
.message-text,
.message-translation,
.translation-box,
.product-line,
.product-badges {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message-text,
.message-translation {
  white-space: pre-wrap;
}

.translation-box {
  margin: 12px 0;
  padding: 12px;
  border-radius: 8px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  font-size: 13px;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.translation-title {
  font-size: 11px;
  color: #16a34a;
  font-weight: 600;
  margin-bottom: 6px;
}

.handler-box {
  flex-shrink: 0;
  margin: 14px 0;
  padding: 10px;
  border-radius: 8px;
  background: #f8fafc;
  color: #475569;
  font-size: 13px;
}

/* ── 消息列表：可滚动，回复框始终可见 ───────── */
.message-list {
  flex: 1;
  min-height: 260px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 14px 0 16px;
  padding-right: 4px;
}

.message {
  max-width: 86%;
  padding: 13px 14px;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  background: #f8fafc;
  line-height: 1.55;
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
  line-height: 1.65;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.message-translation {
  margin-top: 6px;
  color: #15803d;
  font-size: 13px;
  line-height: 1.65;
  border-top: 1px dashed #bbf7d0;
  padding-top: 6px;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.attachments {
  margin-top: 10px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* ── 回复区 ─────────────────────────────────── */
.return-actions,
.reply-box {
  flex-shrink: 0;
  background: #fff;
  border-top: 1px solid #e2e8f0;
  padding-top: 14px;
}

.return-note {
  margin-bottom: 12px;
  color: #b45309;
  font-weight: 600;
}

.return-no-action {
  font-size: 13px;
  color: #94a3b8;
}

.reject-choice-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reject-choice-item {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
  cursor: pointer;
  transition: all 0.15s;
}

.reject-choice-item:hover {
  border-color: #409eff;
  background: #f0f7ff;
}

.reject-choice-item strong {
  display: block;
  margin-bottom: 4px;
  color: #303133;
}

.reject-choice-custom {
  border-color: #f56c6c;
  background: #fef0f0;
}

.reject-choice-custom:hover {
  border-color: #f56c6c;
  background: #fde2e2;
}

.reject-choice-item p {
  margin: 0;
  font-size: 13px;
  color: #909399;
}

.reply-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 32px;
  margin-bottom: 10px;
}

.reply-actions {
  justify-content: flex-end;
  margin-top: 12px;
}

.reply-box :deep(.el-textarea__inner),
.return-actions :deep(.el-textarea__inner) {
  min-height: 150px;
  line-height: 1.6;
  resize: vertical;
}

/* ── 移动端 ─────────────────────────────────── */
@media (max-width: 980px) {
  .quick-filter-tag {
    font-size: 12px;
  }

  .workspace {
    grid-template-columns: 1fr;
    min-height: auto;
    height: auto;
  }

  .queue,
  .detail {
    display: block;
    height: auto;
    overflow: visible;
    min-height: auto;
    max-height: none;
  }

  .queue {
    min-height: auto;
    max-height: none;
  }

  .queue-item {
    min-height: 104px;
  }

  .queue-items-wrapper,
  .message-list {
    flex: none;
    overflow: visible;
    max-height: none;
    min-height: auto;
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

  .reply-box :deep(.el-textarea__inner) {
    min-height: 130px;
  }

  .detail-header {
    grid-template-columns: 1fr;
  }

  .detail-actions {
    flex-direction: row;
    flex-wrap: wrap;
    align-items: flex-start;
    justify-content: flex-start;
  }

  .detail-title-row h3 {
    font-size: 16px;
  }
}

@media (min-width: 981px) {
  .mobile-back {
    display: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .countdown.danger {
    animation: none;
  }
}
</style>
