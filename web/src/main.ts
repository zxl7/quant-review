import { createApp } from 'vue';
import App from './App.vue';
import './style.css';
import './template.css';
import { initMarketData } from './composables/useMarketData';

async function bootstrap() {
  await initMarketData();
  createApp(App).mount('#app');
}

bootstrap();
