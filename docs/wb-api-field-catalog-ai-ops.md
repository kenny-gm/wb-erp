# WB API 字段目录、业务作用与 AI 运营判断设计

更新时间：2026-07-16

目标：把 WB API 12 类数据域拆到字段级，说明字段在 ERP 中的作用、各数据域如何协作，以及 AI 大模型如何帮助运营快速判断经营情况。

说明：本文件是设计文档，不包含代码或数据库变更。字段以官方 API 可获取的信息、现有系统已接入字段、运营分析需要为基础整理。实际开发前仍需按 token 权限逐个接口做返回样本校验。

## 1. 总体数据链路

```text
WB API
  -> 原始层 raw：保存接口原始响应、同步批次、来源端点
  -> 维表 dimensions：店铺、商品、产品组、广告活动、仓库、币种、负责人
  -> 事实层 facts：每日销售、漏斗、广告、库存、财务、客服
  -> 展示层 views：Dashboard、产品销售明细、广告分析、客服工作台、财务对账
  -> AI 辅助层：异常解释、原因归因、行动建议、日报周报、客服/广告/商品优化建议
```

所有数据域建议统一保留以下字段：

| 字段 | 作用 |
| --- | --- |
| shop_id | 店铺维度，跨店铺隔离与汇总 |
| platform | 平台维度，WB / Yandex 后续统一扩展 |
| source_api | API 类目，例如 content / analytics / promotion |
| source_endpoint | 具体接口路径，便于追溯 |
| external_id | WB 外部 ID，例如 nmId / advertId / srid / feedbackId |
| sync_batch_id | 同步批次，排查漏同步和重复同步 |
| external_created_at | WB 侧创建时间 |
| external_updated_at | WB 侧更新时间 |
| raw_json | 原始响应，保证后续字段补录不丢数据 |
| created_at / updated_at | ERP 入库与更新时间 |

## 2. 12 类数据域字段目录

### 2.1 店铺/账号域

来源：API information / Users / seller-info

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| seller_id / supplier_id | 店铺在 WB 侧的主体 ID | 多店铺归属、接口权限校验 |
| seller_name | 卖家主体名称 | 店铺档案展示 |
| tin / inn | 公司税号 | 财务对账、主体识别 |
| trademark / brand | 商标/品牌信息 | 商品品牌维度关联 |
| rating | 卖家评分 | 店铺健康度、异常预警 |
| feedback_count | 评价数量 | 口碑趋势 |
| token_category | token 权限类目 | 判断哪些同步任务可运行 |
| token_readonly | 是否只读 | 防止误调用写接口 |
| token_expired_at | token 过期时间 | 同步失败预警 |
| user_id / role / permissions | WB 用户和权限 | 店铺内部权限映射 |

当前系统对应：`shops`、`users`。

建议新增/调整：

- `shops.api_permissions_json`：保存 token 权限类目检查结果。
- `shops.seller_external_id`：保存 WB 卖家主体 ID。
- `shops.token_checked_at`：最近一次权限检查时间。

AI 可帮助：

- 发现 token 权限缺失导致的数据空洞。
- 解释“为什么某店铺某模块没有数据”。
- 按权限自动生成同步任务建议。

### 2.2 商品内容域

来源：Content 商品卡、字典、标签、媒体

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| nmID / nmId | WB 商品 ID，商品核心主键 | 商品维度分析、广告/订单/客服关联 |
| imtID | 商品组/合并卡 ID | 同款多规格聚合 |
| vendorCode / supplierArticle | 商家 SKU | 运营识别、采购/仓库关联 |
| barcode / sku | 条码/规格 SKU | 规格级库存、订单匹配 |
| chrtID | WB 规格 ID | 尺码/颜色维度库存分析 |
| subjectID / subjectName | 类目 ID/名称 | 类目分析、类目指标对比 |
| brand | 品牌 | 品牌维度分析 |
| title / name | 商品标题 | 搜索与转化优化 |
| description | 商品描述 | 内容质量诊断 |
| characteristics | 特征属性 | 筛选、内容完整度 |
| photos / mediaFiles | 图片/视频 | 内容完整度、转化诊断 |
| dimensions.length/width/height/weight | 尺寸重量 | 物流费、仓储费、利润计算 |
| tags | 商品标签 | 产品组、运营分组 |
| createdAt / updatedAt | 商品卡更新时间 | 内容变更追踪 |
| card_status / error_text | 卡片状态/错误 | 商品上架问题预警 |

当前系统对应：`products`。

当前缺口：

- `products.nm_id` 当前全局唯一，应改为 `shop_id + nm_id`。
- 缺少 `imtID`、`barcode`、`chrtID`、`subjectID`、`brand`、`raw_json`。
- `custom_name` 是运营聚合名称，但不是 WB 原始主键。

建议核心表：

- `dim_product`
- `dim_product_variant`
- `dim_product_group`
- `wb_raw_content_cards`

AI 可帮助：

- 判断商品卡内容是否缺图片、标题过短、属性不完整。
- 结合转化率识别“曝光高但点击低”的标题/主图问题。
- 给商品标题、卖点、属性补全建议。

### 2.3 价格与折扣域

来源：Prices / Discounts / Promotion calendar

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| nmID | 商品关联 | 商品价格历史 |
| chrtID / sizeID | 规格价格 | 尺码差异定价 |
| price | 原价 | 毛利和促销判断 |
| discounted_price | 折后价 | 实际成交预估 |
| discount | 折扣百分比 | 折扣强度监控 |
| club_discount | WB Club 折扣 | 会员价格影响 |
| currency | 币种 | CNY/RUB 统一换算 |
| editable_size_price | 是否可编辑规格价 | 定价策略 |
| upload_task_id | 价格上传任务 | 操作追踪 |
| upload_status | 上传状态 | 价格失败预警 |
| error_text | 上传错误 | 自动诊断 |
| promo_id / action_id | 促销活动 ID | 促销参与分析 |
| promo_start / promo_end | 促销周期 | 促销前后对比 |
| promo_status | 活动状态 | 是否已报名/进行中 |

当前系统对应：基本未形成生产链路。

建议核心表：

- `wb_product_prices_daily`
- `wb_product_discounts_daily`
- `wb_promotion_calendar`

AI 可帮助：

- 识别“降价后订单没涨”的无效促销。
- 识别“广告费上升但价格竞争力下降”。
- 推荐是否进入促销、是否调价、是否恢复原价。

### 2.4 库存/仓库域

来源：Marketplace stocks、Statistics stocks、Analytics stocks report

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| nmId | 商品关联 | 商品库存 |
| barcode / chrtID | 规格关联 | 规格库存 |
| warehouseId / officeId | 仓库 ID | 仓库维度库存 |
| warehouseName / officeName | 仓库名称 | 库存位置展示 |
| warehouseType | WB / seller warehouse | FBW/FBS 区分 |
| regionName | 区域 | 区域库存与销售匹配 |
| quantity | 可售库存 | 缺货预警 |
| quantityFull | 总库存 | 完整库存口径 |
| inWayToClient | 去客户途中 | 履约中库存 |
| inWayFromClient | 退货途中 | 退货库存 |
| reserved_quantity | 已预留库存 | 可售风险 |
| subject / brand / techSize | 类目/品牌/规格 | 库存分组分析 |
| lastChangeDate | 更新时间 | 库存新鲜度 |

当前系统对应：`inventory_snapshots`、`inventory_records`，但生产数据基本为空。

建议核心表：

- `wb_inventory_daily`
- `dim_warehouse`
- `fact_inventory_daily`

AI 可帮助：

- 结合销量预测断货日期。
- 判断广告是否应该暂停：库存低但广告还在烧。
- 发现某仓库缺货导致转化率下降。

### 2.5 订单/销售 Statistics 域

来源：Statistics `/api/v1/supplier/orders`、`/api/v1/supplier/sales`

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| srid | 官方建议订单识别字段 | 订单去重、订单/销售/退货串联 |
| gNumber | 订单组号 | 订单组关联 |
| date | 下单/销售时间 | 日维度趋势 |
| lastChangeDate | 数据更新时间 | 增量同步游标 |
| warehouseName / warehouseType | 仓库 | 仓库表现 |
| countryName / oblastOkrugName / regionName | 区域 | 区域销售分析 |
| supplierArticle | 商家 SKU | 商品关联 |
| nmId | 商品 ID | 商品维度 |
| barcode | 条码 | 规格维度 |
| category / subject / brand / techSize | 商品分类 | 类目分析 |
| totalPrice | 原始价格 | 折扣前金额 |
| discountPercent | 折扣 | 折扣分析 |
| spp | WB 折扣 | 平台补贴影响 |
| finishedPrice | 订单完成价 | 运营销售金额参考 |
| priceWithDisc | 折后价 | 运营口径金额 |
| forPay | 预计应付卖家 | 预估收入 |
| saleID | 销售/退货 ID | 销售去重 |
| isCancel / cancelDate | 是否取消 | 取消率分析 |
| isSupply / isRealization | 供货/实现标记 | 结算状态参考 |
| sticker | 贴纸码 | 履约排查 |

当前系统对应：`orders`、`order_items`，但当前 `orders` 里有 Analytics 合成数据。

关键口径：

- Statistics 是运营监控口径，适合看趋势。
- 财务精确对账必须用 Finance realization report。

AI 可帮助：

- 分析订单下降是流量下降、转化下降、库存问题还是价格问题。
- 识别取消率上升、退货率上升、区域异常。
- 生成每日异常产品清单。

### 2.6 Analytics 商品漏斗域

来源：Analytics sales funnel、search report、stocks report

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| nmId | 商品关联 | 漏斗主键 |
| vendorCode | SKU | 商品识别 |
| brandName | 品牌 | 品牌维度 |
| subjectId / subjectName | 类目 | 类目对比 |
| tagId / tagName | 商品标签 | 运营分组 |
| date / period | 日期/周期 | 趋势分析 |
| openCount | 商品卡访问/打开 | 流量入口 |
| cartCount | 加购数 | 兴趣强度 |
| orderCount | 订单数 | 转化结果 |
| orderSum | 订单金额 | 运营销售额 |
| buyoutCount / buyoutSum | 买断/成交 | 真实成交质量 |
| cancelCount / cancelSum | 取消 | 取消风险 |
| avgPrice | 平均价格 | 定价分析 |
| cartConversion | 访问到加购转化 | 主图/价格/详情质量 |
| orderConversion | 访问到下单转化 | 商品页综合转化 |
| buyoutPercent | 买断率 | 订单质量 |
| searchText | 搜索词 | SEO/广告关键词 |
| avgPosition | 搜索平均位置 | 搜索排名 |
| frequency | 搜索频率 | 需求热度 |
| stock metrics | 库存指标 | 缺货/周转 |

当前系统对应：`ad_records` 中 `ad_type='product_analytics'`。

当前缺口：

- 商品漏斗不应存在 `ad_records`。
- 应拆到 `fact_product_daily`。

AI 可帮助：

- 生成“漏斗断点”：曝光/访问高但加购低，说明商品页/价格问题；加购高但订单低，说明价格/配送/库存/信任问题。
- 结合搜索词和广告词，给自然搜索优化建议。
- 输出“今天最该处理的 10 个产品”。

### 2.7 广告 Promotion 域

来源：Promotion adverts、fullstats、normquery/stats、budget、balance

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| advertId | 广告活动 ID | 广告主键 |
| type | 广告类型 | 搜索/推荐等类型分析 |
| status | 活动状态 | 是否运行中 |
| payment_type | CPC / CPM | 计费方式 |
| placements | search / recommendations | 投放位置 |
| nmId | 投放商品 | 广告归因到商品 |
| subjectId | 投放类目 | 类目投放 |
| bid / cpm / cpc | 出价/成本 | 投放成本控制 |
| budget | 预算 | 预算消耗 |
| balance | 广告账户余额 | 余额预警 |
| date | 日期 | 日趋势 |
| appType / platform | web / ios / android | 端口表现 |
| views | 展示 | 曝光 |
| clicks | 点击 | 流量 |
| ctr | 点击率 | 素材/位置吸引力 |
| sum / spend | 花费 | 广告成本 |
| orders | 广告订单 | 广告转化 |
| sum_price | 广告销售额 | 广告收入 |
| atbs | 广告加购 | 广告兴趣 |
| shks | 已购/购买数 | 广告成交 |
| normQuery / keyword | 搜索词 | 关键词优化 |
| avgPos | 平均排名 | 搜索位置 |
| excludedWords | 否定词 | 浪费流量控制 |

当前系统对应：`ad_records`、`ad_keyword_stats`。

当前缺口：

- 缺 `wb_ad_campaigns` 活动维表。
- 缺 `wb_ad_campaign_products` 投放商品快照。
- 广告统计和商品漏斗混表。

AI 可帮助：

- 找出“花费上升但订单下降”的广告。
- 判断是 CTR 低、CPC 高、加购低、转化低还是排名差。
- 自动给否定词、加价/降价、暂停广告建议。
- 生成关键词分组：高意图词、低转化词、浪费词、潜力词。

### 2.8 FBS Marketplace 域

来源：Marketplace orders、stickers、supplies、metadata

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| orderId / id | FBS 订单 ID | 履约主键 |
| rid / srid | 订单关联 | 订单追踪 |
| createdAt | 创建时间 | 履约时效 |
| skus | SKU/条码 | 商品匹配 |
| nmId | 商品 ID | 商品维度 |
| article / supplierArticle | 商家货号 | 仓库拣货 |
| chrtId | 规格 ID | 规格履约 |
| price / convertedPrice | 价格 | 金额核对 |
| currencyCode | 币种 | 币种核算 |
| warehouseId | 发货仓 | 仓库维度 |
| offices | 办公室/仓库 | 履约配置 |
| status | 订单状态 | 发货监控 |
| sticker / barcode | 贴纸 | 发货操作 |
| sgtin / uin / imei / gtin | 标识码 | 强制标识品类 |
| expirationDate | 有效期 | 食品/消耗品管理 |
| supplyId | 发货单 ID | 批次发货 |

当前系统对应：基本未系统化接入。

AI 可帮助：

- 预警 FBS 未及时处理订单。
- 识别高频履约失败商品。
- 按仓库和 SKU 给拣货优先级。

### 2.9 FBW Supplies 域

来源：FBW supplies

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| supplyId | 供货单 ID | 供货批次 |
| supplyName | 供货名称 | 运营识别 |
| status | 供货状态 | 入仓进度 |
| warehouseId / warehouseName | 入仓仓库 | 仓库规划 |
| transitWarehouse | 中转仓 | 物流链路 |
| boxType | 包装类型 | 箱规管理 |
| barcode | 商品条码 | 商品匹配 |
| nmId | 商品 ID | 商品维度 |
| quantity | 计划数量 | 补货计划 |
| acceptedQuantity | 已接收数量 | 入仓差异 |
| createdAt / updatedAt | 时间 | 供货时效 |

当前系统对应：未系统化接入。

AI 可帮助：

- 对比计划入仓和实际入仓差异。
- 预测补货是否能赶上销售节奏。
- 结合库存和销量生成补货建议。

### 2.10 客服问答/评价域

来源：Questions / Feedbacks

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| id | 问答/评价 ID | 去重主键 |
| nmId / imtId | 商品关联 | 商品问题归因 |
| supplierArticle | SKU | 商品识别 |
| productName | 商品名称 | 客服卡片展示 |
| userName | 买家名称 | 展示 |
| text / questionText / feedbackText | 内容 | 问题识别 |
| pros / cons | 优缺点 | 评价分析 |
| rating | 星级 | 口碑监控 |
| createdDate | 创建时间 | SLA |
| updatedDate | 更新时间 | 增量同步 |
| state / status | 状态 | 待回复/已回复 |
| wasViewed | 是否查看 | 待处理 |
| answer.text | 回复内容 | 客服质量 |
| answer.createDate | 回复时间 | 响应时效 |
| answer.editable | 是否可编辑 | 后续处理 |
| photoLinks / video | 图片视频 | 质量问题证据 |

当前系统对应：`customer_service_items/messages/actions`。

当前状态：

- 这个域已经是系统里设计最接近目标架构的一块。
- 已统一 questions / feedbacks / chat / return_claim。

AI 可帮助：

- 自动识别问题类型：质量、物流、尺寸、使用方法、售后。
- 生成俄语回复草稿。
- 汇总产品维度的高频差评原因。
- 把客服问题反向喂给产品优化和详情页优化。

### 2.11 买家聊天/退货域

来源：Buyers Chat / Buyers Returns

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| chatID | 聊天 ID | 聊天线程 |
| eventID | 消息事件 ID | 消息去重 |
| replySign | 回复凭证 | 发消息必需 |
| message | 消息内容 | 客服沟通 |
| sender / direction | 买家/卖家方向 | 对话流 |
| attachments | 附件 | 图片证据 |
| goodCard.nmId | 商品关联 | 商品问题归因 |
| goodCard.vendorCode | SKU | 商品识别 |
| createdAt | 消息时间 | SLA |
| claimId | 退货申请 ID | 退货处理 |
| claimStatus | 退货状态 | 售后进度 |
| reason | 退货原因 | 商品质量分析 |
| orderUid / srid | 订单关联 | 退货与订单串联 |
| deadline | 处理截止时间 | 超时预警 |
| action | 同意/拒绝/处理动作 | 售后动作审计 |

当前系统对应：`customer_service_items/messages/actions`。

AI 可帮助：

- 判断退货是否应优先处理。
- 识别退货原因与商品质量问题。
- 输出“超过 SLA 风险”的任务列表。
- 给客服生成下一步动作建议。

### 2.12 财务/对账域

来源：Finance realization report、balance、documents、acquiring

| 字段 | 系统作用 | 运营价值 |
| --- | --- | --- |
| realizationreport_id | 报告 ID | 财务批次 |
| date_from / date_to | 报告周期 | 周/月对账 |
| create_dt | 报告生成时间 | 数据新鲜度 |
| rrd_id | 明细行 ID | 去重主键 |
| gi_id | 供货单 ID | 供货关联 |
| subject_name | 类目 | 类目利润 |
| nm_id | 商品 ID | 商品利润 |
| brand_name | 品牌 | 品牌利润 |
| sa_name / supplierArticle | SKU | 商品识别 |
| ts_name / techSize | 规格 | 规格利润 |
| barcode | 条码 | 规格匹配 |
| doc_type_name | 销售/退货/补偿类型 | 财务分类 |
| quantity | 数量 | 销售/退货数量 |
| retail_price | 零售价 | 原价 |
| retail_amount | 零售金额 | 销售额 |
| sale_percent | 折扣 | 折扣影响 |
| commission_percent | 佣金比例 | 平台成本 |
| office_name | 仓库/办公室 | 仓库费用 |
| supplier_oper_name | 操作类型 | 费用分类 |
| order_dt / sale_dt / rr_dt | 下单/销售/报告日期 | 时间口径 |
| retail_price_withdisc_rub | 折后卢布价 | 财务销售额 |
| ppvz_for_pay | 应付卖家 | 结算收入 |
| acquiring_fee | 收单费用 | 支付成本 |
| delivery_rub | 物流费用 | 履约成本 |
| penalty | 罚款 | 异常成本 |
| additional_payment | 补款 | 调整项 |
| storage_fee | 仓储费 | 仓储成本 |
| deduction | 扣款 | 成本项 |
| acceptance | 验收费/接收费 | 入仓成本 |
| currency | 币种 | 统一换算 |

当前系统对应：未系统化接入。当前利润计算不应作为最终财务口径。

AI 可帮助：

- 解释利润下降来自佣金、物流、广告、折扣、罚款还是退货。
- 生成财务对账异常清单。
- 识别某类商品“运营看着卖得好但财务利润差”。

## 3. 各数据域如何协作

### 3.1 商品是所有域的中心

```text
Content 商品卡
  -> dim_product / dim_product_variant / dim_product_group
  -> 连接 Analytics、Statistics、Promotion、Inventory、Finance、客服
```

关键关联字段：

- `shop_id`
- `nmId`
- `barcode`
- `supplierArticle`
- `chrtID`
- `custom_name / product_group_id`

用途：

- 让一个运营看到“同一个产品在多个店铺”的统一表现。
- 让系统支持从产品下钻到店铺、规格、日期、广告、客服、财务。

### 3.2 销售判断需要 Analytics + Statistics + Finance 三层

```text
Analytics：看漏斗和趋势
Statistics：看订单/销售运营明细
Finance：看最终结算与利润
```

协作方式：

| 问题 | 主要数据源 | 辅助数据源 |
| --- | --- | --- |
| 今天销售为什么掉了 | Analytics | 广告、库存、价格 |
| 订单多但利润低 | Finance | 广告、价格、退货 |
| 加购高但订单低 | Analytics | 价格、库存、客服 |
| 订单高但结算低 | Finance | Statistics |
| 退货变多 | Statistics / Finance | 客服评价、退货申请 |

### 3.3 广告必须和商品漏斗联动

```text
Promotion 广告
  -> 点击 / 花费 / 搜索词 / 订单
Analytics 商品漏斗
  -> 访问 / 加购 / 订单 / 销售
```

协作判断：

| 现象 | 判断 |
| --- | --- |
| 广告点击高，商品访问高，加购低 | 商品卡、价格、主图、评价可能有问题 |
| 广告花费高，点击低 | 关键词、出价、展示位置、素材问题 |
| 加购高，订单低 | 价格、库存、配送、差评、竞品问题 |
| 广告订单高，Finance 利润低 | 广告占比、折扣、佣金、物流成本过高 |

### 3.4 库存和价格是运营动作的前置约束

```text
库存低：不能盲目加广告
价格异常：不能只看转化率
促销中：需要单独评估折扣后利润
```

协作判断：

- 库存不足 + 广告花费高：提示暂停或降预算。
- 价格上升 + 转化下降：提示价格敏感。
- 促销期间销售上升 + 利润下降：提示促销质量差。

### 3.5 客服数据是产品问题的早期信号

```text
Questions / Feedbacks / Chat / Returns
  -> 产品维度问题标签
  -> 影响商品详情、广告词、FAQ、质量改进
```

协作判断：

- 同一商品客服问题上升 + 转化率下降：商品页可能没有解释清楚。
- 评价星级下降 + 退货上升：质量或预期不符。
- 高频问题集中在尺寸/配件/使用方法：需要改详情页或客服话术。

## 4. AI 大模型在系统中的角色

AI 不应替代数据计算，AI 应基于结构化数据做解释、归因、建议和文本生成。

### 4.1 AI 运营判断输入

AI 每次分析应拿到结构化上下文：

```json
{
  "date_range": "2026-07-10 ~ 2026-07-16",
  "shop": "all / 157WB / 炊恒WB",
  "product": "产品组 / nmId",
  "metrics": {
    "sales": {},
    "orders": {},
    "visitors": {},
    "cart_rate": {},
    "conversion_rate": {},
    "ad_cost": {},
    "ad_ratio": {},
    "stock": {},
    "price": {},
    "returns": {},
    "feedback_rating": {},
    "finance_profit": {}
  },
  "changes": {
    "vs_yesterday": {},
    "vs_last_7_days": {},
    "vs_last_period": {}
  }
}
```

### 4.2 AI 输出类型

| AI 输出 | 用途 | 示例 |
| --- | --- | --- |
| 异常摘要 | 快速知道哪里出问题 | “803洗地机 CNY 店铺销售额下降 28%，主要由访客下降和广告点击下降导致。” |
| 原因归因 | 把多个数据域串起来 | “广告曝光没降，但 CTR 从 2.1% 降到 0.9%，说明搜索词或位置质量变差。” |
| 行动建议 | 给运营下一步 | “先暂停 2 个高花费低订单关键词，检查库存和价格，再观察 24 小时。” |
| 风险预警 | 提醒处理优先级 | “库存预计 3 天断货，但广告仍在高预算投放。” |
| 日报/周报 | 管理者快速了解经营情况 | “本周销售增长来自 157WB，CNY 店铺广告占比升高，需要关注。” |
| 客服归因 | 把客户反馈转运营动作 | “最近退货集中在尺寸不符，建议修改详情页尺寸说明。” |
| 广告关键词建议 | 提高广告效率 | “保留高转化词，降低低点击高花费词，新增自然搜索高频词。” |
| 商品卡优化 | 提升转化 | “主图点击率低，建议突出套装/尺寸/使用场景。” |

### 4.3 AI 不应该直接做的事

| 不建议 AI 直接做 | 原因 |
| --- | --- |
| 自动改价格 | 影响收入和利润，需要人工确认 |
| 自动调广告预算/出价 | 费用相关，需要确认 |
| 自动删除/归档数据 | 数据安全风险 |
| 自动回复争议客服 | 外部平台写操作，需人工确认 |
| 自动清空或迁移表 | 高风险数据库操作 |

## 5. 运营判断场景设计

### 5.1 每日经营总览

输入数据：

- Analytics：访客、加购、订单、销售
- Promotion：广告费、点击、广告订单
- Statistics：销售/退货运营明细
- Finance：结算收入和费用，若已生成
- 客服：新增评价、差评、退货、问答

输出：

```text
今日经营结论：
1. 销售额上涨/下降来自哪几个产品和店铺。
2. 流量、加购、转化哪个环节变化最大。
3. 广告费是否合理。
4. 是否有库存/价格/评价/退货导致的风险。
5. 今天最该处理的 5 个动作。
```

### 5.2 产品诊断

输入数据：

- Content 商品卡
- Analytics 漏斗
- Promotion 广告
- Prices 价格
- Inventory 库存
- Feedbacks / Returns 客服售后
- Finance 利润

输出：

```text
产品状态：
- 流量：正常/下降/异常上升
- 加购：正常/偏低
- 转化：正常/偏低
- 广告效率：健康/烧钱/潜力
- 库存：充足/紧张/断货风险
- 客服反馈：质量/尺寸/物流/使用问题
- 利润：健康/低利润/亏损
```

### 5.3 广告诊断

输入数据：

- Promotion 活动、关键词、花费、点击、订单
- Analytics 商品漏斗
- Finance 利润
- Inventory 库存

输出：

```text
广告动作建议：
- 加预算：高 ROAS、高转化、库存充足
- 降预算：花费高、订单低、利润差
- 暂停：库存不足或连续多日无订单
- 优化词：点击高无订单、位置差、低频无效词
- 商品页优化：点击正常但加购/转化低
```

### 5.4 客服到运营闭环

输入数据：

- Questions / Feedbacks / Chat / Returns
- Product / Sales / Ads

输出：

```text
客服信号：
- 高频问题
- 差评原因
- 退货原因
- 涉及产品
- 对销售转化的影响
- 需要修改的商品卡/FAQ/图片/说明
```

## 6. 前后端设计建议

### 6.1 后端 API

建议新增稳定聚合接口：

| 接口 | 作用 |
| --- | --- |
| `/api/ops/overview` | 经营总览，给 Dashboard 和 AI 日报 |
| `/api/ops/products/{product_group_id}/diagnosis` | 单品诊断 |
| `/api/ops/ads/diagnosis` | 广告诊断 |
| `/api/ops/customer-signals` | 客服信号聚合 |
| `/api/ops/finance/reconciliation` | 财务对账 |
| `/api/ai/ops-summary` | AI 经营摘要 |
| `/api/ai/product-action-plan` | AI 单品行动计划 |

### 6.2 前端页面

| 页面 | 应显示什么 |
| --- | --- |
| 销售看板 | 总体趋势、统一卢布/RUB/CNY、异常原因入口 |
| 产品销售明细 | 产品组、店铺、日期、广告、库存、客服信号 |
| 广告分析 | 活动、关键词、花费效率、AI 优化建议 |
| 客服工作台 | 处理工单，同时回传产品问题标签 |
| 财务看板 | 结算收入、费用、利润、异常扣费 |
| AI 运营助手 | 今日重点、风险、原因、建议动作 |

## 7. 最小可落地版本

不建议一次性重构全部模块。最小可落地版本建议：

1. 新增 `product_group` 和 `shop_id + nm_id` 商品维度。
2. 把商品漏斗从 `ad_records` 拆到 `fact_product_daily`。
3. 把广告统计拆到 `fact_ad_daily`，广告活动拆到 `dim_ad_campaign`。
4. 建一个 `view_ops_product_daily`，同时给 Dashboard、产品明细、AI 使用。
5. 新增 AI 日报接口，只读分析，不做自动外部操作。

这样可以先解决运营判断最痛的三个问题：

- 数据口径混乱。
- 产品跨店铺无法干净聚合。
- 广告和销售无法快速归因。
