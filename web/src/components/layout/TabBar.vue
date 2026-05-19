<script setup lang="ts">
defineProps<{
  tabs: Array<{ id: string; name: string }>
  currentTab: string
}>()

const emit = defineEmits<{
  (e: 'select', id: string): void
}>()
</script>

<template>
  <div class="tabbar">
    <button v-for="tab in tabs" :key="tab.id" class="tab-btn" :class="{ active: currentTab === tab.id }" type="button" @click="emit('select', tab.id)">
      {{ tab.name }}
    </button>
  </div>
</template>
