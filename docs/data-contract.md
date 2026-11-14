# 业务资料契约

visits.duration 是已记录的分钟数，不是精确潜在时长。method=sensor 按 devices 规则取整并封顶，interview 由受访者报数，gate 使用整数分钟且 90 分钟封顶；rule 记录当时计时协议。paired_timing.reference 是高精度复计，inclusion_probability 为进入复计资料的条件选择概率；sampling.reference_coverage 限制复计覆盖时段。group 是同游团体，不能当完全独立个体。

## 资料表

| 表名 | 原始记录数 | 字段 |
| --- | ---: | --- |
| visits | 300 | center, device, duration, group, guide, id, method, released_at, revision, rule |
| paired_timing | 60 | id, inclusion_probability, reference, released_at, revision, visit |
| devices | 2 | cap, effective_from, id, released_at, revision, step |
| sampling | 4 | center, id, reference_coverage, released_at, revision, selection_stratum |

记录均为本地合成资料，只表达业务结构，不是公开报道所述人群或机构的实测资料。日期是本地资料日历；所有版本以资料服务的 as_of 为准。字段值和自然缺失保留原义。金额、评分、频率和权重不可跨表不加判断地直接合计。
