<template>
  <article class="glass-panel missing-panel">
    <h2 class="section-title">页面组件未注册</h2>
    <div class="section-subtitle">
      数据库里已经存在该路由权限，但前端还没有找到对应的 Vue 组件。
      请确认 `componentPath` 是否和实际文件一致。
    </div>
    <el-descriptions border :column="1" style="margin-top: 18px">
      <el-descriptions-item label="当前路由">{{ route.path }}</el-descriptions-item>
      <el-descriptions-item label="组件路径">{{ route.meta.componentPath || '-' }}</el-descriptions-item>
      <el-descriptions-item label="页面标题">{{ route.meta.title || '-' }}</el-descriptions-item>
    </el-descriptions>
  </article>
</template>

<script setup>
import { useRoute } from 'vue-router'

const route = useRoute()
</script>

<style scoped>
.missing-panel {
  padding: 24px;
  border-radius: 28px;
}
</style>
