<script setup lang="ts">
import { useMarketData } from '../../composables/useMarketData';

const { marketData } = useMarketData();
</script>

<template>
  <div class="footer">
    <div class="footer-learning" v-if="marketData.learningNotes">
      <div class="footer-learning-title">📌 短线提醒:</div>
      <div style="font-size: 11px; color: var(--text-muted); font-weight: 800; margin: 0 0 8px 0" v-if="marketData.learningNotes.meta">
        调用层：{{ marketData.learningNotes.meta.cycle || '-' }}
        <span style="opacity: 0.7">｜</span>
        视图：{{ marketData.learningNotes.meta.stageType || '-' }}
        <span style="opacity: 0.7">｜</span>
        来源：{{ marketData.learningNotes.meta.source || '-' }}
      </div>
      <ul v-if="marketData.learningNotes.tips && marketData.learningNotes.tips.length">
        <li v-for="(t, i) in marketData.learningNotes.tips" :key="'tip-'+i">{{ t }}</li>
      </ul>
      <div class="footer-quotes" v-if="marketData.learningNotes.quotes && marketData.learningNotes.quotes.length">
        <div class="footer-quote" v-for="(q, i) in marketData.learningNotes.quotes" :key="'q-'+i">
          <span>语录:</span>
          {{ q }}
        </div>
      </div>
    </div>
    <p>📊 生成时间：{{ marketData.date || '-' }} 收盘</p>
    <p>公众号：风中一刀的主升浪丨</p>
    <p>K线为王 · 数据先行 · 不虚构不猜测</p>
  </div>
</template>

<style scoped src="./ShortReminderFooter.css"></style>
