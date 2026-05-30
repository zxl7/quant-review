<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

defineProps<{
  tabs: readonly { id: string; name: string }[]
  currentTab: string
}>()

const emit = defineEmits<{
  (e: 'select', id: string): void
}>()

const wrapRef = ref<HTMLElement | null>(null)
const tabbarRef = ref<HTMLElement | null>(null)
const isFloating = ref(false)
const tabbarHeight = ref(0)
const tabbarLeft = ref(0)
const tabbarWidth = ref(0)

let triggerY = 0
let rafToken = 0

const FLOATING_TOP_PX = 8

function measureLayout() {
  const wrap = wrapRef.value
  const bar = tabbarRef.value
  if (!wrap || !bar) return
  const rect = wrap.getBoundingClientRect()
  triggerY = rect.top + window.scrollY - FLOATING_TOP_PX
  tabbarHeight.value = bar.offsetHeight
  tabbarLeft.value = Math.round(rect.left)
  tabbarWidth.value = Math.round(rect.width)
}

function syncFloating() {
  rafToken = 0
  const wrap = wrapRef.value
  if (!wrap) return
  if (!triggerY) measureLayout()
  const nextFloating = window.scrollY > triggerY
  if (nextFloating !== isFloating.value) {
    if (nextFloating) measureLayout()
    isFloating.value = nextFloating
  }
}

function onScroll() {
  if (rafToken) return
  rafToken = requestAnimationFrame(syncFloating)
}

function onResize() {
  triggerY = 0
  measureLayout()
  syncFloating()
}

onMounted(() => {
  nextTick(() => {
    measureLayout()
    syncFloating()
  })
  window.addEventListener('scroll', onScroll, { passive: true })
  window.addEventListener('resize', onResize)
  window.addEventListener('orientationchange', onResize)
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  window.removeEventListener('resize', onResize)
  window.removeEventListener('orientationchange', onResize)
  if (rafToken) cancelAnimationFrame(rafToken)
})

const wrapStyle = computed(() => (isFloating.value ? { height: tabbarHeight.value + 'px' } : {}))
const tabbarStyle = computed(() =>
  isFloating.value
    ? {
        position: 'fixed' as const,
        top: FLOATING_TOP_PX + 'px',
        left: tabbarLeft.value + 'px',
        width: tabbarWidth.value + 'px',
      }
    : {},
)
</script>

<template>
  <div class="tabbar-wrap" ref="wrapRef" :style="wrapStyle">
    <div class="tabbar" ref="tabbarRef" :class="{ 'is-floating': isFloating }" :style="tabbarStyle">
      <button v-for="tab in tabs" :key="tab.id" class="tab-btn" :class="{ active: currentTab === tab.id }" type="button" @click="emit('select', tab.id)">
        {{ tab.name }}
      </button>
    </div>
  </div>
</template>

<style scoped src="./TabBar.css"></style>
