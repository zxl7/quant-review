// 按需引入 ECharts：只注册当前项目实际用到的 chart / component / renderer。
// 新增图表类型时需要在这里 use() 对应模块，否则运行时静默不渲染。
import * as echarts from 'echarts/core';
import { BarChart, LineChart } from 'echarts/charts';
import {
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  AxisPointerComponent,
} from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';

echarts.use([
  BarChart,
  LineChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  MarkLineComponent,
  AxisPointerComponent,
  CanvasRenderer,
]);

export { echarts };
export default echarts;
