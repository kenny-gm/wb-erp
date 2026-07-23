<template>
  <div class="ai-prompts">
    <el-card>
      <template #header>
        <span>💬 AI 提示词模板</span>
      </template>

      <div v-loading="loading" class="prompt-layout">
        <!-- 左侧模板列表 -->
        <div class="template-list">
          <el-menu :default-active="activeKey" @select="selectTemplate">
            <el-menu-item v-for="tpl in templateList" :key="tpl.template_key" :index="tpl.template_key">
              <span>{{ tpl.name }}</span>
              <el-tag size="small" type="success" style="margin-left: 6px">v{{ tpl.version }}</el-tag>
            </el-menu-item>
          </el-menu>
        </div>

        <!-- 右侧编辑区 -->
        <div class="prompt-editor" v-if="activeKey">
          <el-form :model="form" label-width="160px" class="editor-form">

            <el-form-item label="模板名称">
              <el-input v-model="form.name" :disabled="true" />
            </el-form-item>

            <el-form-item label="描述">
              <el-input v-model="form.description" type="textarea" :rows="2" :disabled="true" />
            </el-form-item>

            <el-divider content-position="left">Prompt 内容</el-divider>

            <el-form-item label="System Prompt">
              <el-input v-model="form.system_prompt" type="textarea" :rows="5" />
            </el-form-item>

            <el-form-item label="User Prompt 模板">
              <el-input v-model="form.user_prompt_template" type="textarea" :rows="5" />
              <span class="field-hint">使用 {"{{变量名}}"} 占位</span>
            </el-form-item>

            <el-form-item label="输出格式（JSON）">
              <el-input v-model="form.output_schema_json" type="textarea" :rows="3" placeholder='{"type": "object", ...}' />
            </el-form-item>

            <el-form-item label="Temperature">
              <el-slider v-model="form.temperature" :min="0" :max="1" :step="0.05" show-stops style="width: 200px" />
              <span style="margin-left: 12px">{{ form.temperature }}</span>
            </el-form-item>

            <el-form-item label="Max Tokens">
              <el-input-number v-model="form.max_tokens" :min="100" :max="8000" :step="100" controls-position="right" />
            </el-form-item>

            <el-form-item>
              <el-button type="primary" @click="saveVersion" :loading="saving">保存新版本</el-button>
              <span class="field-hint">保存将创建新版本，不覆盖旧版本</span>
            </el-form-item>

            <!-- 版本历史 -->
            <el-divider content-position="left">版本历史</el-divider>
            <div class="version-list">
              <div
                v-for="v in versions"
                :key="v.id"
                class="version-item"
                :class="{ 'version-active': v.is_active }"
              >
                <span class="version-label">v{{ v.version }}</span>
                <el-tag v-if="v.is_active" type="success" size="small">当前</el-tag>
                <span class="version-date">{{ v.updated_at ? formatDate(v.updated_at) : '-' }}</span>
                <el-button
                  v-if="!v.is_active"
                  size="small"
                  text
                  type="primary"
                  @click="activateVersion(v.version)"
                  :loading="activating"
                >激活</el-button>
                <el-button
                  v-if="!v.is_active"
                  size="small"
                  text
                  type="danger"
                  @click="deleteVersion(v.version)"
                  :loading="deletingVersion === v.version"
                >删除</el-button>
              </div>
            </div>

            <!-- 测试区 -->
            <el-divider content-position="left">Prompt 测试</el-divider>

            <el-form-item label="变量（JSON）">
              <el-input
                v-model="testVariables"
                type="textarea"
                :rows="4"
                placeholder='{"text": "пример", "channel": "question"}'
                style="font-family: monospace"
              />
              <span v-if="variablesError" class="field-error">{{ variablesError }}</span>
            </el-form-item>

            <el-form-item>
              <el-button @click="renderPrompt" :loading="rendering">渲染 Prompt</el-button>
              <el-button type="success" @click="testAI" :loading="testingAI">调用 AI 测试</el-button>
            </el-form-item>

            <template v-if="renderResult">
              <el-divider content-position="left">渲染结果</el-divider>
              <div class="render-result">
                <p><strong>System Prompt:</strong></p>
                <el-input type="textarea" :model-value="renderResult.rendered_system_prompt" :rows="4" readonly />
                <p style="margin-top: 12px"><strong>User Prompt:</strong></p>
                <el-input type="textarea" :model-value="renderResult.rendered_user_prompt" :rows="4" readonly />
                <template v-if="renderResult.ai_output !== null">
                  <p style="margin-top: 12px"><strong>AI 输出:</strong></p>
                  <el-input type="textarea" :model-value="typeof renderResult.ai_output === 'object' ? JSON.stringify(renderResult.ai_output, null, 2) : renderResult.ai_output" :rows="6" readonly />
                </template>
                <template v-if="renderResult.error">
                  <el-alert type="error" :title="renderResult.error" :closable="false" style="margin-top: 12px" />
                </template>
              </div>
            </template>

          </el-form>
        </div>

        <div v-else class="empty-hint">
          请从左侧选择一个模板
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

const loading = ref(false)
const saving = ref(false)
const activating = ref(false)
const deletingVersion = ref(null)
const rendering = ref(false)
const testingAI = ref(false)
const templateList = ref([])
const activeKey = ref('')
const versions = ref([])
const renderResult = ref(null)
const variablesError = ref(null)

const form = reactive({
  name: '',
  description: '',
  system_prompt: '',
  user_prompt_template: '',
  output_schema_json: '{}',
  temperature: 0.2,
  max_tokens: 1200,
})

const testVariables = ref('')
const lastAutoFilledKey = ref('')

const DEFAULT_VARIABLES = {
  customer_reply: {
    channel: 'feedback',
    product_name: 'Air fryer 5L',
    content: 'Товар пришел с повреждением, очень расстроена.',
    content_zh: '商品到货有破损，买家很不满意。',
  },
  translate_to_zh: {
    text: 'Товар пришел с повреждением, очень расстроена.',
  },
  product_analysis: {
    product: '{"sku":"TEST-001","name":"Air fryer 5L"}',
    facts: '{"bad_feedback_count":2,"return_claim_count":1}',
    evidence: '["买家反馈包装破损", "退货原因：商品损坏"]',
  },
  task_suggestion: {
    signals: '加购率下降 20%，广告花费超标',
    evidence: '昨日加购率 1.2%，今日 0.9%；广告 ROAS 0.8',
  },
}

function getDefaultVariables(key) {
  const vars = DEFAULT_VARIABLES[key]
  if (!vars) return ''
  return JSON.stringify(vars, null, 2)
}

function formatDate(iso) {
  if (!iso) return '-'
  return new Date(iso).toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai' })
}

async function fetchAll() {
  loading.value = true
  try {
    const res = await axios.get('/api/ai-prompts')
    templateList.value = res.data
    if (res.data.length > 0) {
      selectTemplate(res.data[0].template_key)
    }
  } catch (e) {
    ElMessage.error('获取模板列表失败')
  } finally {
    loading.value = false
  }
}

async function selectTemplate(key) {
  activeKey.value = key
  renderResult.value = null
  variablesError.value = null
  // 自动填入测试变量（如果为空或是旧模板的默认值）
  const currentVars = testVariables.value.trim()
  const isEmpty = currentVars === ''
  const isStale = lastAutoFilledKey.value !== key && currentVars !== ''
  if (isEmpty || isStale) {
    testVariables.value = getDefaultVariables(key)
    lastAutoFilledKey.value = key
  }
  try {
    const res = await axios.get(`/api/ai-prompts/${key}`)
    versions.value = res.data
    const active = res.data.find(v => v.is_active)
    if (active) {
      form.name = active.name
      form.description = active.description || ''
      form.system_prompt = active.system_prompt
      form.user_prompt_template = active.user_prompt_template
      form.output_schema_json = active.output_schema_json || '{}'
      form.temperature = active.temperature
      form.max_tokens = active.max_tokens
    }
  } catch (e) {
    ElMessage.error('获取模板详情失败')
  }
}

async function saveVersion() {
  saving.value = true
  try {
    await axios.patch(`/api/ai-prompts/${activeKey.value}`, {
      name: form.name,
      description: form.description,
      system_prompt: form.system_prompt,
      user_prompt_template: form.user_prompt_template,
      output_schema_json: form.output_schema_json,
      temperature: form.temperature,
      max_tokens: form.max_tokens,
    })
    ElMessage.success('新版本已保存')
    await selectTemplate(activeKey.value)
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function activateVersion(version) {
  activating.value = true
  try {
    await axios.post(`/api/ai-prompts/${activeKey.value}/activate-version`, { version })
    ElMessage.success(`v${version} 已激活`)
    await selectTemplate(activeKey.value)
  } catch (e) {
    ElMessage.error('激活失败：' + (e.response?.data?.detail || e.message))
  } finally {
    activating.value = false
  }
}

async function deleteVersion(version) {
  try {
    await ElMessageBox.confirm(
      `确认删除 ${activeKey.value} 的 v${version} 旧版本？删除后不可从页面恢复。`,
      '删除旧版本',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }

  deletingVersion.value = version
  try {
    await axios.delete(`/api/ai-prompts/${activeKey.value}/versions/${version}`)
    ElMessage.success(`v${version} 已删除`)
    await selectTemplate(activeKey.value)
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.detail || e.message))
  } finally {
    deletingVersion.value = null
  }
}

function renderPrompt() {
  variablesError.value = null
  renderResult.value = null
  let vars = {}
  try {
    vars = JSON.parse(testVariables.value)
  } catch (e) {
    variablesError.value = '变量 JSON 格式错误：' + e.message
    return
  }
  rendering.value = true
  axios.post(`/api/ai-prompts/${activeKey.value}/test`, { variables: vars, run_ai: false })
    .then(res => { renderResult.value = res.data })
    .catch(e => { ElMessage.error('渲染失败：' + (e.response?.data?.detail || e.message)) })
    .finally(() => { rendering.value = false })
}

function testAI() {
  variablesError.value = null
  renderResult.value = null
  let vars = {}
  try {
    vars = JSON.parse(testVariables.value)
  } catch (e) {
    variablesError.value = '变量 JSON 格式错误：' + e.message
    return
  }
  testingAI.value = true
  axios.post(`/api/ai-prompts/${activeKey.value}/test`, { variables: vars, run_ai: true })
    .then(res => { renderResult.value = res.data })
    .catch(e => { ElMessage.error('AI 调用失败：' + (e.response?.data?.detail || e.message)) })
    .finally(() => { testingAI.value = false })
}

onMounted(() => {
  fetchAll()
})
</script>

<style scoped>
.ai-prompts {
  padding: 20px;
}

.prompt-layout {
  display: flex;
  gap: 20px;
  min-height: 500px;
}

.template-list {
  width: 260px;
  flex-shrink: 0;
}

.template-list .el-menu {
  border: none;
}

.prompt-editor {
  flex: 1;
  min-width: 0;
}

.editor-form {
  min-width: 600px;
}

.field-hint {
  margin-left: 12px;
  color: #909399;
  font-size: 12px;
}

.field-error {
  margin-left: 12px;
  color: #f56c6c;
  font-size: 12px;
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: 16px;
}

.version-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  background: #f5f7fa;
  font-size: 13px;
}

.version-item.version-active {
  background: #e8f7e8;
}

.version-label {
  font-weight: 600;
  min-width: 30px;
}

.version-date {
  color: #909399;
  font-size: 12px;
  margin-left: auto;
}

.render-result {
  background: #f5f7fa;
  padding: 12px;
  border-radius: 6px;
}

.empty-hint {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #909399;
  font-size: 14px;
  width: 100%;
}

@media (max-width: 430px) {
  .ai-prompts {
    padding: 8px;
  }

  .prompt-layout {
    flex-direction: column;
    gap: 12px;
    min-height: auto;
  }

  .template-list {
    width: 100%;
  }

  .template-list .el-menu {
    display: flex;
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
  }

  .template-list :deep(.el-menu-item) {
    min-width: 160px;
    height: 44px;
    line-height: 44px;
    flex-shrink: 0;
  }

  .prompt-editor {
    width: 100%;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
  }

  .editor-form {
    min-width: 560px;
  }

  .version-item {
    flex-wrap: wrap;
    align-items: flex-start;
  }

  .version-date {
    width: 100%;
    margin-left: 0;
  }

  .field-hint,
  .field-error {
    display: block;
    margin: 6px 0 0;
  }
}
</style>
