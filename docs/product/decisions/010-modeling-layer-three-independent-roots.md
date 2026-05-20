---
number: 010
date: 2026-05-19
title: 建模层引入三根独立根 + backbone 双角色显式分工 + activation 四态
---

## 上下文

当前建模层在 dimension / backbone 上承担过多职责。Profile dimensions 是 trait-shaped（连续标量贝叶斯累积），装不下方法论（case-based、情境绑定、有 outcome）；backbone 同时承担"用户认知图谱"和"外部知识空间"两个角色，导致投射类输出的 differential 做不出来；backbone person 节点 by design 装的是思想家（看各 domain 的 node_extract.spt：psychology domain 是 "psychologists, psychoanalysts, cognitive scientists"），不是用户的熟人，关系维护场景无 anchor；伏笔 / 承诺账完全没有。

## 决策

建模层引入三根独立根（contacts / forebodes / method_cases），保留 dimensions（trait 层，不扩方法论）；backbone 通过 origin 字段（internal / external）显式分工用户认知层和外部知识层，external 半需要主动维护机制（标杆种子 / 用户喂入 / LLM 远邻扩展三选一或组合）；backbone_activations 表加 activation_kind 字段扩展为四态（hit / brush / avoid / absent）。Backbone person 节点保留只装思想家 / 学派人物 / 公众人物，用户熟人由 contacts 独立承载，两边同名条目允许并存。

## 当时的理由

(a) 状态机（伏笔 active → fulfilled 等）+ outcome 回灌的语义不能强塞进强度累积型的 backbone；(b) 熟人和思想家承担的角色完全不同（互动对象 vs 参照系），混用会损失关系维护能力，且 backbone person by design 就是思想家；(c) Backbone 双角色显式分离让投射类差集（B − A）计算可成立；(d) Activation 四态让"擦边 / 回避 / 未接触"成为可消费信号，支撑反射类"看见你看不见的"和投射类"递入口"；(e) Profile dimension 强行扩"方法论维度"会把 case-based 数据压成标量，丢"情境 + 结果"维度。
