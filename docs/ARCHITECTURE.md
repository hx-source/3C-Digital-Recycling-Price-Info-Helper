# PriceRadar 架构与扩展边界

## 设计原则

第一版采用“确定性数据管道 + 可替换识别器 + 人工复核”，而不是把所有逻辑塞进一个大模型 Agent。报价入库和涨跌计算必须可追溯、可复核、可重复运行；模型主要负责图片转录，业务规则仍由代码控制。

## 核心状态

`ImportBatch` 记录一次来源文件及处理状态：

`uploaded → parsing → review → committed`

图片未配置 OCR 时进入 `needs_ocr`，解析失败进入 `failed`。`committed` 批次禁止重新解析。

`QuoteCandidate` 是可编辑草稿，保存原文、工作表、单元格、解析器版本和置信度。复核状态为 `pending / approved / rejected`。

`PriceQuote` 是不可由导入解析直接修改的正式历史。只有通过复核并发布的候选才能生成正式报价。

## 解析策略

- Excel：`openpyxl` 读取；排除业务说明和酒水页；每个工作表独立提取报价日期。
- 图片：`OcrProvider` 抽象。当前有 OpenAI Vision 和人工文本两个实现，后续可增加 PaddleOCR、云 OCR 或其他视觉模型。
- 规范化：品牌、型号、容量、颜色、版本拆分；移除重复品牌前缀；一个型号的多个颜色拆成独立记录。
- 价格状态：明确数字为 `quoted`，完全缺失为 `no_quote`，星号遮挡为 `masked`。
- 型号主键：`brand + normalized model + storage + color + variant`，用于跨日期匹配。

## 涨跌计算

对每个型号主键：

1. 只取 `quoted` 且价格非空的记录。
2. 每个报价日保留当天最后发布的一条。
3. 当前价与此前最近的不同日期报价比较。
4. 返回涨跌额和百分比；没有上一期时只返回当前价。

因此无报价和遮挡价格会保留在历史库中，但不会把趋势错误地拉到 0。

## 扩展方式

- 新输入来源：新增 importer/provider，然后复用 `_persist_candidates`。
- 新品类：扩展工作表元数据与品牌规则，不影响数据库流程。
- 新统计：基于 `PriceQuote` 增加 service 和 API，不修改导入过程。
- 新前端功能：增加独立 view 和 API client 方法，Pinia 只保存跨页面市场状态。
- 异步化：未来将 `create_import` 的解析步骤投递到队列，批次状态协议无需改变。
- 多商家比较：在 `source_name` 基础上增加供应商实体和来源维度索引即可。

## 安全与数据完整性

- 数据库密码与 API Key 只放在 `.env`。
- 上传文件按日期和 UUID 存储，不使用用户文件名覆盖已有文件。
- 文件大小和扩展名受限。
- 草稿可以修正；正式历史通过发布动作生成。
- Excel 重解析只允许未发布且全部仍为 `pending` 的批次，避免覆盖人工工作。
- E2E 固定使用 `price_radar_test_e2e`，不操作生产表。

