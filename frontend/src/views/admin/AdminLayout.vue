<template>
  <div class="admin-layout">
    <el-tabs v-model="activeTab" @tab-click="handleTabClick" type="border-card">
      <el-tab-pane label="👥 用户管理" name="users">
        <router-view v-if="activeTab === 'users'" />
      </el-tab-pane>
      <el-tab-pane label="📦 产品管理" name="products">
        <router-view v-if="activeTab === 'products'" />
      </el-tab-pane>
      <el-tab-pane label="🏪 店铺管理" name="shops">
        <router-view v-if="activeTab === 'shops'" />
      </el-tab-pane>
      <el-tab-pane label="⏱ 同步设置" name="sync-schedules">
        <router-view v-if="activeTab === 'sync-schedules'" />
      </el-tab-pane>
      <el-tab-pane label="🔔 预警阈值" name="thresholds">
        <router-view v-if="activeTab === 'thresholds'" />
      </el-tab-pane>
      <el-tab-pane label="🎨 界面管理" name="ui">
        <router-view v-if="activeTab === 'ui'" />
      </el-tab-pane>
      <el-tab-pane label="⚙️ 系统设置" name="settings">
        <router-view v-if="activeTab === 'settings'" />
      </el-tab-pane>
      <el-tab-pane label="🤖 AI 设置" name="ai-settings">
        <router-view v-if="activeTab === 'ai-settings'" />
      </el-tab-pane>
      <el-tab-pane label="💬 Prompt 模板" name="ai-prompts">
        <router-view v-if="activeTab === 'ai-prompts'" />
      </el-tab-pane>
    </el-tabs>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useRouter, useRoute } from 'vue-router'

const router = useRouter()
const route = useRoute()
const activeTab = ref('users')

function handleTabClick({ props }) {
  router.push(`/admin/${props.name}`)
}

// 根据路由设置当前 tab
watch(() => route.path, (path) => {
  if (path.includes('/admin/users')) activeTab.value = 'users'
  else if (path.includes('/admin/products')) activeTab.value = 'products'
  else if (path.includes('/admin/shops')) activeTab.value = 'shops'
  else if (path.includes('/admin/sync-schedules')) activeTab.value = 'sync-schedules'
  else if (path.includes('/admin/thresholds')) activeTab.value = 'thresholds'
  else if (path.includes('/admin/ui')) activeTab.value = 'ui'
  else if (path.includes('/admin/settings')) activeTab.value = 'settings'
  else if (path.includes('/admin/ai-settings')) activeTab.value = 'ai-settings'
  else if (path.includes('/admin/ai-prompts')) activeTab.value = 'ai-prompts'
}, { immediate: true })
</script>

<style scoped>
.admin-layout {
  background: #fff;
  padding: 0;
  border-radius: 4px;
  min-height: calc(100vh - 180px);
}

:deep(.el-tabs__header) {
  margin-bottom: 0;
  overflow-x: auto;
  overflow-y: hidden;
  -webkit-overflow-scrolling: touch;
}

:deep(.el-tabs__nav) {
  display: flex;
  flex-wrap: nowrap;
}

:deep(.el-tabs__item) {
  height: 50px;
  line-height: 50px;
  font-size: 15px;
  padding: 0 20px;
  flex-shrink: 0;
}

:deep(.el-tabs__content) {
  padding: 16px;
}

/* 移动端适配 */
@media (max-width: 767px) {
  .admin-layout {
    min-height: auto;
  }
  
  :deep(.el-tabs__header) {
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;
  }
  
  :deep(.el-tabs__nav) {
    flex-wrap: nowrap;
  }
  
  :deep(.el-tabs__item) {
    height: 44px;
    line-height: 44px;
    font-size: 13px;
    padding: 0 12px;
    white-space: nowrap;
  }
  
  :deep(.el-tabs__content) {
    padding: 12px;
  }
  
  :deep(.el-tabs--border-card) {
    border: none;
    box-shadow: none;
  }
  
  :deep(.el-tabs--border-card > .el-tabs__header) {
    background: #f5f7fa;
    border-bottom: 1px solid #e4e7ed;
  }
  
  :deep(.el-tabs--border-card > .el-tabs__header .el-tabs__item) {
    height: 44px;
    line-height: 44px;
  }
}

/* 平板适配 */
@media (min-width: 768px) and (max-width: 1023px) {
  :deep(.el-tabs__item) {
    font-size: 14px;
    padding: 0 16px;
  }
  
  :deep(.el-tabs__content) {
    padding: 16px;
  }
}
</style>
