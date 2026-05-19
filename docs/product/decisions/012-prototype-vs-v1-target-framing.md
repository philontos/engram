---
number: 012
date: 2026-05-19
title: 原型 vs v1.0 目标态 framing + 6 步实施依赖顺序
---

## 上下文

之前的实现思考缺乏明确的"目标态"概念，每个 minor 决定容易被实现细节牵着走（dimension schema 怎么改、backbone domain 加什么 —— 这些都是手段层的讨论，但被当成产品讨论）。讨论中作者明确这次 compass 产出的整个框架（ADR 006-011）= v1.0 目标态，不是分多个版本渐进。

## 决策

把当前实现明确标记为"原型"；本 compass 周期产出的完整框架（含 ADR 006-011）= v1.0 目标态。原型 → v1.0 的实施依赖顺序：(1) contacts → (2) router → (3) forebodes → (4) method_cases → (5) activation 四态 → (6) external backbone 主动维护。完成 6 步 = v1.0。

## 当时的理由

(a) 明确目标态可避免实施过程中被实现细节绑架；(b) 依赖顺序约束了实施次序（contacts 是 forebodes 的 anchor / router 是后续所有根的输入前提）；(c) 把 push / 多人设 / 行为通道 / suggestion 闭环明确推到 post-1.0，避免范围蔓延，同时显式声明它们不是 anti-feature，只是 v1.0 不做。
