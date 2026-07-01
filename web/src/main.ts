import { createApp } from 'vue';
import App from './App.vue';
import Antd from 'ant-design-vue';
import 'ant-design-vue/dist/reset.css';
import './style.css';
import './template.css';
import { initMarketData } from './composables/useMarketData';

async function bootstrap() {
  await initMarketData();
  createApp(App).use(Antd).mount('#app');
}

bootstrap();
