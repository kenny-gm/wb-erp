<template>
  <div class="customer-service-page">
    <div class="toolbar">
      <div class="toolbar-title">
        <h2>客服工作台</h2>
        <span>问答、评价、聊天、退货申请</span>
      </div>
      <div class="toolbar-actions" v-if="canManage">
        <el-button v-if="hasCSperm('customer_service:sync')" :loading="syncing" @click="syncCustomerService">同步客服数据</el-button>
      </div>
    </div>

    <!-- 4个模块统计卡片 -->
    <div class="channel-cards">
      <!-- 评论卡片 -->
      <div class="channel-card channel-card-feedback">
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
      <div class="channel-card channel-card-question">
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
      <div class="channel-card channel-card-return_claim">
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
      <div class="channel-card channel-card-chat">
        <div class="channel-card-title">
          <span>买家聊天</span>
        </div>
        <div class="channel-card-items channel-card-items-3">
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'chat_waiting_seller', 'has-count': stats.chat_waiting_seller || stats.chat_unanswered }" @click="setQuickKey('chat_waiting_seller')">
            <span class="channel-item-label">待卖家回复</span>
            <span class="channel-item-num danger">{{ stats.chat_waiting_seller ?? stats.chat_unanswered ?? 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'chat_waiting_buyer' }" @click="setQuickKey('chat_waiting_buyer')">
            <span class="channel-item-label">待买家回复</span>
            <span class="channel-item-num">{{ stats.chat_waiting_buyer ?? stats.chat_answered ?? 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'chat_finished' }" @click="setQuickKey('chat_finished')">
            <span class="channel-item-label">已完结</span>
            <span class="channel-item-num">{{ stats.chat_finished || 0 }}</span>
          </div>
          <div class="channel-item clickable" :class="{ active: filters.quick_key === 'chat_pending_internal' }" @click="setQuickKey('chat_pending_internal')">
            <span class="channel-item-label">内部处理中</span>
            <span class="channel-item-num">{{ stats.chat_pending_internal || 0 }}</span>
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
            :class="['queue-item', `queue-item-${item.channel}`, { active: activeItem?.id === item.id }]"
            @click="selectItem(item)"
          >
            <!-- 第一行：渠道 + 业务状态 + 时间 -->
            <div class="queue-card-top">
              <div class="queue-card-state">
                <span class="queue-card-channel" :class="`channel-${item.channel}`">{{ channelLabel(item.channel) }}</span>
                <span
                  v-if="getDisplayStatus(item)"
                  class="queue-card-status"
                  :class="'status-' + getDisplayStatus(item).key"
                >
                  {{ getDisplayStatus(item).label }}
                </span>
                <span
                  v-if="item.channel === 'return_claim'"
                  class="queue-card-wait-time"
                  :class="getReturnSlaClass(item)"
                >
                  {{ getReturnSlaText(item) }}
                </span>
                <span v-if="item.risk_level === 'urgent'" class="queue-card-risk risk-urgent">紧急</span>
                <span v-else-if="item.risk_level === 'high'" class="queue-card-risk risk-high">高风险</span>
              </div>
              <span class="queue-card-time">{{ item.external_created_at || '-' }}</span>
            </div>

            <!-- 第二行：产品名称 -->
            <div class="queue-card-product-name" :class="{ empty: !item.product_name && !item.product_name_ru }">
              {{ item.product_name || item.product_name_ru || '(无产品名)' }}
            </div>

            <!-- 第三行：产品id + SKU + 评分星级 -->
            <div class="queue-card-product-meta">
              <span>产品id：{{ item.nm_id || '-' }}</span>
              <span>SKU：{{ item.sku || '-' }}</span>
              <span v-if="item.channel === 'feedback' && item.rating" class="queue-card-rating">
                {{ item.rating_display || '' }}
              </span>
              <span v-else></span>
            </div>

            <!-- 第四行：内容 -->
            <div class="queue-card-content">
              {{ item.content_zh || item.content || '无文本内容' }}
            </div>

            <!-- 底部：店铺 + 负责人 -->
            <div class="queue-card-footer">
              <span>{{ item.shop_name || '-' }}</span>
              <span>{{ item.owner || item.assigned_owner || '未分配' }}</span>
            </div>

            <!-- 备注摘要 -->
            <div v-if="canUseInternalNote(item) && item.internal_note" class="note-line">
              <span class="note-label">备注</span>
              <span class="note-text">{{ item.internal_note }}</span>
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
            <div v-if="activeItem.channel === 'return_claim'" class="detail-sla" :class="getReturnSlaClass(activeItem)">
              {{ getReturnSlaText(activeItem) }}
            </div>
          </div>

          <!-- 右侧操作按钮 ────────────────────────── -->
          <div class="detail-actions">
            <el-button v-if="hasCSperm('customer_service:translate')" size="small" plain :loading="translatingItem" @click="translateItem">翻译内容</el-button>
            <el-dropdown v-if="hasCSperm('customer_service:status')" @command="handleStatusCommand" size="small">
              <el-button plain size="small">处理状态</el-button>
              <template #dropdown>
                <el-dropdown-menu v-if="activeItem.channel === 'chat'">
                  <el-dropdown-item command="chat_waiting_seller">待卖家回复</el-dropdown-item>
                  <el-dropdown-item command="chat_waiting_buyer">待买家回复</el-dropdown-item>
                  <el-dropdown-item command="chat_finished">已完结</el-dropdown-item>
                  <el-dropdown-item command="pending_internal">内部处理中</el-dropdown-item>
                </el-dropdown-menu>
                <el-dropdown-menu v-else>
                  <el-dropdown-item command="pending_internal">转内部处理</el-dropdown-item>
                  <el-dropdown-item command="closed">关闭</el-dropdown-item>
                  <el-dropdown-item command="open">重新打开</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
          </div>
        </div>

        <!-- 退货申请内容（独立区块，不复用聊天 message-list） -->
        <div v-if="activeItem.channel === 'return_claim'" class="return-claim-content">
          <div class="return-claim-header">退货申请内容</div>
          <div v-if="activeItem.content_zh" class="translation-box">
            <div class="translation-title">中文翻译</div>
            <div>{{ activeItem.content_zh }}</div>
            <details>
              <summary class="original-hint">查看俄语原文</summary>
              <div class="message-text">{{ activeItem.content }}</div>
            </details>
          </div>
          <div v-else-if="activeItem.content" class="message-text">{{ activeItem.content }}</div>
          <div v-else class="message-text" style="color: #999">（无申请内容）</div>
        </div>

        <!-- item 翻译结果（非退货） -->
        <div v-else-if="activeItem.content_zh" class="translation-box">
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

        <!-- 客服备注编辑区 -->
        <div v-if="canUseInternalNote(activeItem)" class="internal-note-box">
          <div class="internal-note-head">
            <div>
              <strong>客服备注</strong>
              <span>仅系统内可见，不会发送给 WB 买家</span>
            </div>
            <span v-if="activeItem.internal_note_updated_by" class="internal-note-meta">
              {{ activeItem.internal_note_updated_by }} · {{ activeItem.internal_note_updated_at || '-' }}
            </span>
          </div>
          <el-input v-model="noteText" type="textarea" :rows="3" maxlength="5000" show-word-limit placeholder="记录客户要求、协商状态、后续跟进事项。" />
          <div class="internal-note-actions">
            <el-button v-if="hasCSperm('customer_service:note')" size="small" :loading="savingNote" @click="saveInternalNote">保存备注</el-button>
          </div>
        </div>

        <!-- 聊天消息列表（退货申请不展示，用独立区块） -->
        <div v-if="activeItem.channel !== 'return_claim'" class="message-list">
          <div
            v-for="message in activeItem.messages || []"
            :key="message.id"
            :class="['message', message.direction]"
          >
            <div class="message-meta">
              <strong>{{ message.direction === 'seller' ? '客服' : '买家' }}</strong>
              <span>{{ message.created_at_external || message.created_at }}</span>
              <el-button
                v-if="message.direction !== 'seller' && hasCSperm('customer_service:translate')"
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
        <!-- /聊天消息列表 -->

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

        <div v-if="activeItem.channel === 'return_claim' && hasCSperm('customer_service:handle_return')" class="return-actions">
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
            <el-button v-if="activeItem.channel === 'question' && activeItem.reply_status !== 'answered' && hasCSperm('customer_service:reject_question')" 
              type="warning" :loading="rejectingQuestion" @click="rejectQuestion">拒绝问题</el-button>
            <el-button v-if="hasCSperm('customer_service:ai_draft')" :loading="drafting" @click="generateDraft">生成俄语草稿</el-button>
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
            <el-button
              v-if="(activeItem.channel === 'feedback' && hasCSperm('customer_service:reply_feedback')) || (activeItem.channel === 'question' && hasCSperm('customer_service:answer_question')) || (activeItem.channel === 'chat' && hasCSperm('customer_service:send_chat'))"
              type="primary" :loading="sending" @click="sendReply">
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
const noteText = ref('')
const savingNote = ref(false)
const detailRequestSeq = ref(0)  // 请求序列号，防串详情
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

// 客服细粒度权限 helpers
// 后端 get_user_permissions 规则：
// - admin → *
// - customer_service → 全部 customer_service:* + user.permissions
// - product_owner（permissions 为空）→ 全部 customer_service:*
// - viewer → customer_service:read
// - staff（permissions 为空）→ customer_service:read
// - manager/custom → user.permissions（可为空）
const CS_ALL_PERMS = new Set([
  'customer_service:read',
  'customer_service:sync',
  'customer_service:translate',
  'customer_service:ai_draft',
  'customer_service:note',
  'customer_service:status',
  'customer_service:reply_feedback',
  'customer_service:answer_question',
  'customer_service:reject_question',
  'customer_service:send_chat',
  'customer_service:handle_return',
])

const csPermissions = computed(() => {
  const user = authStore.user
  const role = user?.role
  const perms = user?.permissions || []

  if (role === 'admin') return new Set(['*'])

  if (role === 'customer_service') {
    return new Set([...CS_ALL_PERMS, ...perms])
  }

  if (role === 'product_owner') {
    // permissions 为空时默认全客服权限
    return perms.length > 0 ? new Set(perms) : new Set([...CS_ALL_PERMS, ...perms])
  }

  if (role === 'viewer') {
    return new Set(['customer_service:read'])
  }

  if (role === 'staff') {
    // permissions 为空时默认只有 read
    return perms.length > 0 ? new Set(perms) : new Set(['customer_service:read'])
  }

  // manager / custom：完全按 permissions
  return new Set(perms)
})

function hasCSperm(perm) {
  if (csPermissions.value.has('*')) return true
  if (csPermissions.value.has(perm)) return true
  // 通配支持
  const [prefix] = perm.split(':')
  return [...csPermissions.value].some(p => p.startsWith(prefix + ':') && p.endsWith('*'))
}

function hasCSChannelPerm(channel, basePerm) {
  // 某些权限不需要 channel 判断
  return hasCSperm(basePerm)
}

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
  chat_waiting_seller: '聊天待卖家回复',
  chat_waiting_buyer: '聊天待买家回复',
  chat_finished: '聊天已完结',
  chat_pending_internal: '聊天内部处理中',
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
  chat_waiting_seller: { channel: 'chat', status: 'unanswered' },
  chat_waiting_buyer: { channel: 'chat', status: 'replied' },
  chat_finished: { channel: 'chat', status: 'closed' },
  chat_pending_internal: { channel: 'chat', status: 'pending_internal' },
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

  if (item.channel === 'chat') {
    if (item.status === 'closed') {
      return { key: 'chat_finished', label: '已完结', type: 'info' }
    }
    if (item.status === 'pending_internal') {
      return { key: 'pending_internal', label: '内部处理中', type: 'warning' }
    }
    if (item.reply_status === 'unanswered') {
      return { key: 'waiting_seller', label: '待卖家回复', type: 'danger' }
    }
    if (item.status === 'replied' || item.reply_status === 'answered') {
      return { key: 'waiting_buyer', label: '待买家回复', type: 'success' }
    }
    return { key: 'waiting_seller', label: '待卖家回复', type: 'danger' }
  }

  if (item.status === 'closed') {
    if (item.channel === 'return_claim') {
      // 已处理：label 追加用时
      const created = item.external_created_at ? new Date(item.external_created_at) : null
      const closed = item.closed_at ? new Date(item.closed_at) : null
      let label = '退货已处理'
      if (created && closed && !isNaN(created) && !isNaN(closed)) {
        const diffH = (closed - created) / (1000 * 60 * 60)
        if (diffH < 1) label += `（${Math.round((closed - created) / 1000 / 60)}分钟）`
        else label += `（${Math.round(diffH * 10) / 10}小时）`
      }
      return { key: 'return_closed', label, type: 'info' }
    }
    return { key: 'closed', label: '已关闭', type: 'info' }
  }
  if (item.status === 'pending_internal') {
    return { key: 'pending_internal', label: '内部处理中', type: 'warning' }
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
    // 清除可能干扰的固定筛选，只保留 quick_key 精确过滤
    filters.shop_id = null
    filters.owner = ''
    filters.search = ''
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
  filters.shop_id = null
  filters.owner = ''
  filters.search = ''
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
  await authStore.fetchUser()
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
  // 立即清空旧数据，防止串详情
  activeItem.value = null
  returnActions.value = []
  replyText.value = ''
  noteText.value = ''

  const seq = ++detailRequestSeq.value
  const res = await axios.get(`/api/customer-service/items/${item.id}`)

  // 校验序列号：过期请求不得覆盖 activeItem
  if (seq !== detailRequestSeq.value) {
    console.warn(`[CustomerService] 请求序列号过期，丢弃响应 (seq=${seq}, current=${detailRequestSeq.value})`)
    return
  }

  activeItem.value = res.data
  replyText.value = ''
  noteText.value = res.data.internal_note || ''
  returnActions.value = []
  if (res.data.channel === 'return_claim') {
    try {
      const ar = await axios.get(`/api/customer-service/returns/${item.id}/actions`)
      // 再次校验序列号
      if (seq !== detailRequestSeq.value) return
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

function buildStatusPayload(command) {
  if (activeItem.value?.channel === 'chat') {
    if (command === 'chat_waiting_seller') {
      return { status: 'open', reply_status: 'unanswered' }
    }
    if (command === 'chat_waiting_buyer') {
      return { status: 'replied', reply_status: 'answered' }
    }
    if (command === 'chat_finished') {
      return { status: 'closed', reply_status: 'answered' }
    }
    if (command === 'pending_internal') {
      return { status: 'pending_internal' }
    }
  }
  return { status: command }
}

async function handleStatusCommand(command) {
  if (!activeItem.value) return
  const payload = buildStatusPayload(command)
  await axios.patch(`/api/customer-service/items/${activeItem.value.id}/status`, payload)
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

function canUseInternalNote(item) {
  return item && ['chat', 'return_claim'].includes(item.channel)
}

async function saveInternalNote() {
  if (!activeItem.value || !canUseInternalNote(activeItem.value)) return
  savingNote.value = true
  try {
    const res = await axios.patch(`/api/customer-service/items/${activeItem.value.id}/note`, {
      internal_note: noteText.value || ''
    })
    // 更新详情项（完整替换，保持所有字段同步）
    activeItem.value = res.data.item
    noteText.value = activeItem.value.internal_note || ''
    // 更新列表中对应卡片（完整替换，保持所有元信息同步）
    const idx = items.value.findIndex(item => item.id === activeItem.value.id)
    if (idx >= 0) {
      items.value[idx] = { ...items.value[idx], ...res.data.item }
    }
    ElMessage.success('备注已保存')
  } catch (err) {
    ElMessage.error(err?.response?.data?.detail || '备注保存失败')
  } finally {
    savingNote.value = false
  }
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

/**
 * 退货 SLA 显示：
 * - 已处理（closed）：用时 = closed_at - external_created_at
 * - 未处理（open）：剩余时间 = sla_hours_left
 */
function formatHours(hours) {
  if (hours === null || hours === undefined) return '-'
  if (hours <= 0) return '已超时'
  if (hours < 1) return `${Math.round(hours * 60)} 分钟`
  const h = Math.round(hours * 10) / 10
  if (h === Math.round(h)) return `${h} 小时`
  return `${h.toFixed(1)} 小时`
}

/**
 * 退货时间显示：统一用 elapsed = now - created（不用 deadline）
 * - closed: 用时 = closed_at - created_at
 * - open:   已等待 = now - created_at
 */
function getReturnSlaText(item) {
  if (!item) return '-'
  const created = item.external_created_at ? new Date(item.external_created_at) : null
  if (!created || isNaN(created)) return '-'

  if (item.status === 'closed') {
    const closed = item.closed_at ? new Date(item.closed_at) : null
    if (closed && !isNaN(closed)) {
      const diffMs = closed - created
      const diffH = diffMs / (1000 * 60 * 60)
      if (diffH < 1) return `已处理，用时 ${Math.round(diffMs / 1000 / 60)} 分钟`
      const h = Math.round(diffH * 10) / 10
      if (h === Math.round(h)) return `已处理，用时 ${h} 小时`
      return `已处理，用时 ${h.toFixed(1)} 小时`
    }
    return '已处理'
  }

  // 未处理：显示已等待时间
  const now = Date.now()
  const elapsedMs = now - created
  const elapsedH = elapsedMs / (1000 * 60 * 60)
  if (elapsedH < 1) return `已等待 ${Math.round(elapsedMs / 1000 / 60)} 分钟`
  const h = Math.round(elapsedH * 10) / 10
  if (h === Math.round(h)) return `已等待 ${h} 小时`
  return `已等待 ${h.toFixed(1)} 小时`
}

function getReturnSlaClass(item) {
  if (!item) return ''
  if (item.status === 'closed') return 'success'

  // 未处理：按已等待时间判断颜色
  const created = item.external_created_at ? new Date(item.external_created_at) : null
  if (!created || isNaN(created)) return ''
  const elapsedH = (Date.now() - created) / (1000 * 60 * 60)
  if (elapsedH >= 120) return 'danger'   // 超过 WB 120h 警戒线
  if (elapsedH >= 72) return 'warning'   // 超过 72 小时预警
  return ''
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

/* ── 顶部统计卡片渠道颜色 ─────────────────── */
.channel-card {
  position: relative;
  overflow: hidden;
}

.channel-card::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  bottom: 0;
  width: 4px;
}

.channel-card-feedback {
  background: linear-gradient(90deg, #f0fdf4 0, #ffffff 34%);
  border-color: #bbf7d0;
}

.channel-card-feedback::before {
  background: #22c55e;
}

.channel-card-question {
  background: linear-gradient(90deg, #f5f3ff 0, #ffffff 34%);
  border-color: #ddd6fe;
}

.channel-card-question::before {
  background: #8b5cf6;
}

.channel-card-return_claim {
  background: linear-gradient(90deg, #fef2f2 0, #ffffff 34%);
  border-color: #fecaca;
}

.channel-card-return_claim::before {
  background: #ef4444;
}

.channel-card-chat {
  background: linear-gradient(90deg, #fff7ed 0, #ffffff 34%);
  border-color: #fed7aa;
}

.channel-card-chat::before {
  background: #f97316;
}

/* ── 顶部卡片标题颜色 ─────────────────── */
.channel-card-feedback .channel-card-title {
  color: #166534;
}

.channel-card-question .channel-card-title {
  color: #5b21b6;
}

.channel-card-return_claim .channel-card-title {
  color: #991b1b;
}

.channel-card-chat .channel-card-title {
  color: #9a3412;
}


.channel-card-items {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.channel-card-items-3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.channel-card-items-3 .channel-item-label {
  white-space: normal;
  line-height: 1.25;
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
  box-shadow: inset 0 0 0 1px rgba(59, 130, 246, 0.25);
}

.channel-item.clickable.active {
  background: rgba(59, 130, 246, 0.08);
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.35);
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

/* ── 左侧卡片列表 ─────────────────────────────── */
.queue-items-wrapper {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
}

.queue-items-wrapper::-webkit-scrollbar {
  width: 4px;
}

.queue-items-wrapper::-webkit-scrollbar-thumb {
  background: #cbd5e1;
  border-radius: 2px;
}

/* ── 卡片主体 ──────────────────────────────── */
.queue-item {
  width: 100%;
  display: block;
  text-align: left;
  padding: 14px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  background: #fff;
  cursor: pointer;
  min-height: 190px;
}

.queue-item + .queue-item {
  margin-top: 10px;
}

.queue-item:hover,
.queue-item.active {
  border-color: #93c5fd;
  box-shadow: 0 0 0 1px rgba(147, 197, 253, 0.35);
}

/* ── 渠道底色（左边框 + 渐变背景） ───────── */
.queue-item-feedback {
  border-left: 4px solid #22c55e;
  background: linear-gradient(90deg, #f0fdf4 0, #ffffff 28%);
}

.queue-item-question {
  border-left: 4px solid #8b5cf6;
  background: linear-gradient(90deg, #f5f3ff 0, #ffffff 28%);
}

.queue-item-return_claim {
  border-left: 4px solid #ef4444;
  background: linear-gradient(90deg, #fef2f2 0, #ffffff 28%);
}

.queue-item-chat {
  border-left: 4px solid #f97316;
  background: linear-gradient(90deg, #fff7ed 0, #ffffff 28%);
}

/* ── 渠道标签颜色 ─────────────────────────── */
.queue-card-channel {
  display: inline-flex;
  align-items: center;
  min-height: 24px;
  padding: 2px 9px;
  border-radius: 999px;
  font-size: 13px;
  font-weight: 700;
}

.channel-feedback {
  background: #dcfce7;
  color: #166534;
}

.channel-question {
  background: #ede9fe;
  color: #5b21b6;
}

.channel-return_claim {
  background: #fee2e2;
  color: #991b1b;
}

.channel-chat {
  background: #ffedd5;
  color: #9a3412;
}


/* ── 第一行：渠道 + 状态 + 时间 ───────────── */
.queue-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.queue-card-state {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  min-width: 0;
}

.queue-card-channel {
  font-size: 14px;
  font-weight: 700;
  color: #0f172a;
}

.queue-card-status,
.queue-card-risk {
  display: inline-flex;
  align-items: center;
  min-height: 22px;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 700;
  line-height: 1.4;
}

.queue-card-wait-time {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 700;
  line-height: 1;
  color: #64748b;
  background: #f1f5f9;
  white-space: nowrap;
}

.queue-card-wait-time.warning {
  color: #b45309;
  background: #fef3c7;
}

.queue-card-wait-time.danger {
  color: #b91c1c;
  background: #fee2e2;
}

.queue-card-wait-time.success {
  color: #15803d;
  background: #dcfce7;
}

.queue-card-time {
  flex-shrink: 0;
  font-size: 12px;
  color: #94a3b8;
  line-height: 22px;
}

/* ── 第二行：产品名称 ──────────────────────── */
.queue-card-product-name {
  margin-top: 10px;
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.45;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.queue-card-product-name.empty {
  color: #94a3b8;
  font-style: italic;
  font-weight: 500;
}

/* ── 第三行：产品id + SKU + 评分 ─────────── */
.queue-card-product-meta {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto;
  gap: 10px;
  margin-top: 8px;
  font-size: 12px;
  color: #64748b;
  line-height: 1.5;
}

.queue-card-product-meta span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.queue-card-rating {
  color: #f59e0b;
  font-weight: 700;
  letter-spacing: 1px;
}

/* ── 第四行：内容 ──────────────────────────── */
.queue-card-content {
  margin-top: 16px;
  min-height: 58px;
  color: #334155;
  font-size: 14px;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
  word-break: break-word;
}

/* ── 底部：店铺 + 负责人 ─────────────────── */
.queue-card-footer {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 18px;
  color: #64748b;
  font-size: 13px;
  line-height: 1.4;
}

.queue-card-footer span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* ── 状态颜色（pill 样式） ────────────────── */
.queue-card-status.status-waiting_seller,
.queue-card-status.status-return_pending,
.queue-card-status.status-unanswered,
.queue-card-status.status-return_open {
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.queue-card-status.status-waiting_buyer,
.queue-card-status.status-answered {
  background: #f0fdf4;
  color: #15803d;
  border: 1px solid #bbf7d0;
}

.queue-card-status.status-return_closed,
.queue-card-status.status-closed,
.queue-card-status.status-archived {
  background: #f1f5f9;
  color: #475569;
  border: 1px solid #cbd5e1;
}

.queue-card-status.status-pending_internal,
.queue-card-status.status-return_open,
.queue-card-status.status-chat_open {
  background: #fffbeb;
  color: #a16207;
  border: 1px solid #fde68a;
}

.queue-card-risk.risk-urgent {
  background: #fee2e2;
  color: #b91c1c;
  border: 1px solid #fecaca;
}

.queue-card-risk.risk-high {
  background: #fffbeb;
  color: #a16207;
  border: 1px solid #fde68a;
}

/* ── 移动端适配 ──────────────────────────── */
@media (max-width: 980px) {
  .queue-card-product-meta {
    grid-template-columns: 1fr;
    gap: 4px;
  }

  .queue-card-footer {
    flex-direction: column;
    gap: 4px;
  }
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

.countdown.success {
  color: #16a34a;
  font-weight: 600;
  font-size: 13px;
  background: #f0fdf4;
  border: 1px solid #86efac;
  border-radius: 6px;
  padding: 4px 10px;
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

.detail-sla.success {
  background: #f0fdf4;
  color: #16a34a;
  font-size: 13px;
  font-weight: 600;
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

.return-claim-content {
  margin: 12px 0;
  padding: 12px;
  border-radius: 8px;
  background: #fff7f0;
  border: 1px solid #fed7aa;
}

.return-claim-header {
  font-size: 11px;
  color: #c2410c;
  font-weight: 600;
  margin-bottom: 8px;
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

/* ── 客服备注样式 ─────────────────────────── */
.note-line {
  margin-top: 7px;
  display: flex;
  gap: 6px;
  align-items: flex-start;
  padding: 6px 8px;
  border-radius: 6px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 12px;
  line-height: 1.45;
}

.note-label {
  flex-shrink: 0;
  font-weight: 700;
}

.note-text {
  min-width: 0;
  display: -webkit-box;
  -webkit-line-clamp: 1;
  -webkit-box-orient: vertical;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.internal-note-box {
  margin: 12px 0;
  padding: 12px;
  border: 1px solid #fde68a;
  border-radius: 8px;
  background: #fffbeb;
}

.internal-note-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: flex-start;
  margin-bottom: 8px;
  color: #92400e;
}

.internal-note-head strong {
  display: block;
  font-size: 13px;
}

.internal-note-head span {
  font-size: 12px;
  color: #a16207;
}

.internal-note-meta {
  flex-shrink: 0;
  font-size: 12px;
  color: #a16207;
}

.internal-note-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
