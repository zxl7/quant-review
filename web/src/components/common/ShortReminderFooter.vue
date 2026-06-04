<script setup lang="ts">
import { useMarketData } from '../../composables/useMarketData';

const { marketData } = useMarketData();
</script>

<template>
  <div class="footer">
    <div class="footer-learning" v-if="marketData.learningNotes">
      <div class="footer-learning-title">📌 短线提醒</div>
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
