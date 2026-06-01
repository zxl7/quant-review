import { onBeforeUnmount, onMounted, watch, type ComputedRef, type Ref } from 'vue';
import { echarts } from '../echarts-setup';

export function useECharts(elRef: Ref<HTMLElement | null>, optionRef: ComputedRef<any>) {
  let chart: echarts.ECharts | null = null;

  const render = () => {
    const el = elRef.value;
    const option = optionRef.value;
    if (!el || !option) return;
    if (!chart) chart = echarts.init(el);
    chart.setOption(option, true);
  };

  onMounted(() => {
    render();
    window.addEventListener('resize', render);
  });

  watch(optionRef, () => {
    render();
  });

  onBeforeUnmount(() => {
    window.removeEventListener('resize', render);
    if (chart) {
      chart.dispose();
      chart = null;
    }
  });
}
