# 字段、候选与来源校验

公开示例 mapping.demo.json 完全是 DEMO，不是平台字段。自助适配器只使用此前在普通账号正常响应中观察到的主机、端点及结构；新团须由新响应证明身份和结构，不能拼接分享短码发起查询。

## 当前观察到的结构

- 业务成功条件：HTTP 200 且 `code` 为整数0。
- 商品数组：`data.list`，商品 ID=`goods_uuid`，名称=`title`。
- 目标关联：每个商品的 `groupon_uuid` 与经详情/用户核对确定的目标相同。
- SKU 数组：`sku_list`，真实 SKU ID=`sku_uuid`，名称=`title`。
- 原始候选：SKU 下的 `stock`、`sale`。这些路径的存在不证明其数量口径。

自助观察同时需要匹配团名的详情及本次 visitor 角色佐证：管理标识为空、所检查修改权限为0，并有用户普通账号/入口声明。角色校验是对观察版本的保守判定，不是平台全部权限模型审计。字段不符或权限不符时不作为普通账号成功入库。

## 显式映射

路径均为 JSON 数组，不执行 eval、表达式或动态代码。商品字段相对商品，SKU 字段相对 SKU；group_scope 支持 response 和 item。任一商品属于错误团单时整个事件拒绝，不写半条记录。

规范字段为 stock_remaining、stock_total、sold_quantity、purchase_limit、availability、visibility_flag、raw_display_text。数量项必须有明确语义证据及 confirmed 才提取，不能凭名称启用；自助默认 metrics 为空。

candidates 独立指定候选别名/路径，独立进入 candidate_evidence，带来源路径、类型、时间和 unconfirmed 标记。只保留数字、布尔、null或短数字字符串；任意字符串隐藏。候选不会自动填入规范库存。

0是有效规范数量，bool不作为整数；缺失、null、错误类型、负数/特殊标记和未确认分开处理。负数只有明确语义后才能转换。总量减销量不默认等于可售数量。原始显示文案不自动拆为剩余/总量。

## 状态与历史

exact_stock 只表示有已确认的规范剩余数量；availability_only 只表示有已确认状态；语义未确认、正文不透明或流程不足为 inconclusive。access_denied 不等于无库存；未返回字段也不证明平台所有接口都没有该字段。

稳定身份使用团单+商品 ID+SKU ID，不按商品名合并。事件幂等，失败保留历史并标记过期；本次成功但缺数量时不把旧值展示为本次数量。局部刷新中缺项不自动判下架。

插件使用有界 gzip/deflate/Brotli 解码；Brotli 需要锁定环境中支持 output_buffer_limit 的版本。其他编码或无法解析的结构明确诊断，不尝试猜测性解密。
