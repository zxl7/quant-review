# Cache 上传检查报告

- 日期：`2026-04-30`
- 模式：`minimal`
- 结论：`可上传`

## 检查结果

- ✅ `market_data-20260430.json`：必需，包含天梯质量分与板块轮动明细
- ✅ `pools_cache.json`：必需，当日涨停池存在；缓存交易日 7 个
- ✅ `theme_cache.json`：必需，题材映射 732 只
- ✅ `plate_rotate_cache.json`：必需，当日 TOP10 存在；首项领涨 日联科技，量能 17881

## 远端建议

- 远端只做 `./qr.sh render YYYY-MM-DD` 或 `./qr.sh deploy` 时，至少上传必需文件。
- 若远端也需要更完整的离线能力，可一并上传可选文件。
- 若远端无法联网抓板块轮动，`plate_rotate_cache.json` 必须保留。
