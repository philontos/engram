---
number: 009
date: 2026-05-19
title: Router 取代 intent gate
---

## 上下文

当前 intent gate 是二态准入决策（accept cognitive / reject everything else），会拒绝 outcome / retrospective / 事件结果类内容，直接堵死 ADR-006 升维双标志 ①（判别力）的数据基础（判别力需要 outcome 数据才能事后回灌）。同时一段长文本本质上是多 lens 并存的（"今天跟 A 吵架，答应他下周给反馈，其实每次都用同样话术效果不好" —— 同一段话同时是 relationship_event + intent_express + method_in_use + outcome），整段单分类会丢失精细度。

## 决策

把 intent gate 重构为 router —— 多 lens × effort 强度提取器，按语句 / 片段分流，永不拒绝，下游 pipeline 自己设 effort 阈值消费。Content lens 枚举：cognitive / outcome / retrospective / method_in_use / intent_express / relationship_event（无 reject）。

## 当时的理由

(a) 准入决策权下放给下游，每个 pipeline 可独立调阈值；(b) 一段长文本本质上是多 lens 并存的，整段单分类丢失精细度；(c) 永不拒绝 = 用户感受到"系统在听"，没有隐性损失；(d) 直接解决判别力的 outcome 数据通道问题；(e) Router lens 枚举开放可扩，未来加新建模根只需要 register 一个 lens 即可。
