<script setup lang="ts">
import ShortReminderFooter from '../common/ShortReminderFooter.vue';
import SentimentPanoramaSection from './SentimentPanoramaSection.vue';
import SentimentStructureSection from './SentimentStructureSection.vue';
import SentimentSummarySection from './SentimentSummarySection.vue';
</script>

<template>
  <div class="sentiment-page">
    <SentimentSummarySection />
    <SentimentPanoramaSection />
    <SentimentStructureSection />
    <ShortReminderFooter />
  </div>
</template>

<style src="./SentimentPage.css"></style>
