"""全局图结构规则 — 所有主干共用，不可按域覆盖。"""

NODE_TYPES = ["person", "concept", "pattern", "method"]

RELATION_TYPES = ["supports", "opposes", "derives", "similar", "related"]

# 关联：仅算法产出，用于保证图谱连通（同 entry 共现兜底）
#   - 语义弱于"相似"（不要求 embedding 高相似）
#   - 权重上限低，不压制 LLM 边

# 节点来源：internal = 用户原始语料直接提取；external = 基于内源向外发散
NODE_ORIGINS = ["internal", "external"]

# 边来源：llm = LLM 关系提取；algo = 算法自动建连（相似度等）
EDGE_SOURCES = ["llm", "algo"]

# 节点 strength 累加算法参数
NODE_STRENGTH = {
    "lambda": 0.01,  # 时间衰减系数，半衰期约 69 天
}

# 边权重增量算法参数（LLM 只输出 confidence，weight 由算法计算）
EDGE_WEIGHT = {
    "base_delta": 0.15,  # 单次最大增量（confidence=1.0 时）
    "min_delta":  0.02,  # 单次最小增量（confidence=0.0 时）
    # increment = min_delta + (base_delta - min_delta) * confidence
}

# 边消费时的时间衰减（不影响存储值，仅在读取时计算）
EDGE_DECAY = {
    "lambda": 0.002,  # 500 天后衰减至约 37%
    "floor":  0.3,    # 衰减下限，边永不完全消失
}

# 算法边参数：相似边 + 关联兜底/共现加权
ALGO_EDGE = {
    "intra_domain_sim_threshold": 0.78,  # 同域"相似"算法边触发阈值
    "weight_cap":                 0.30,  # "相似"算法边 weight 上限
    # 共现/关联：每次 entry 激活的两两节点对 → '关联' 边，重复共现累加
    "association_min_sim":        0.20,  # 低于此相似度不建关联边（避免荒谬配对）
    "association_initial_cap":    0.20,  # 首次建立时 weight 上限
    "association_weight_cap_max": 0.50,  # 多次共现累加 weight 硬上限（不压制 LLM 边）
    "association_co_increment":   0.05,  # 每次再次共现时的增量
    "association_pairs_per_entry": 30,   # 每条 entry 最多产出多少条 '关联' 边
}

# 对立传染：A⟷B 对立 且 A→C 支撑 ⇒ B⟷C 倾向对立
#   通过图论规则自动发现用户未直接表达但结构上蕴含的认知矛盾
OPPOSITION_PROPAGATION = {
    "min_source_weight":  0.30,  # 参与传染的支撑/对立边最低 weight
    "weight_cap":         0.20,  # 传染推出的对立边 weight 上限
    "max_per_entry":      10,    # 单条 entry 推出的对立边上限
}

PROFILE_MERGE = {
    "lambda": 0.01,
}

RETRIEVAL = {
    "rough_top_k":       10,   # Stage 2 全域粗召回节点数
    "max_edges_per_node": 10,  # Stage 5 精召回单节点边上限
}

DEDUP_THRESHOLD = 0.92              # 同域节点 embedding 余弦相似度阈值，高于此视为同一节点
CROSS_DOMAIN_SIM_THRESHOLD = 0.85   # 跨域相似边触发阈值，不合并只建边

# 节点溯源 source_entry_ids 保留最近 N 条，避免列表无限增长
SOURCE_ENTRIES_MAX = 20
