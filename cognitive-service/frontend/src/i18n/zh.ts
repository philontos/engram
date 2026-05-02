/**
 * 中文文案字典。Key 命名约定：<scope>.<key>，例如 common.cancel / nav.graph。
 * 简单插值用 {var}，由 i18n.t 替换。
 *
 * 不在此处的：
 * - 用户产生的内容（entry raw、query 输出、节点 label）
 * - 后端 LLM 输出
 * - 中文领域名（domain/relation/value 的 enum 值，作为数据存在）
 */
const dict = {
  common: {
    cancel:        '取消',
    confirm:       '确认',
    delete:        '删除',
    save:          '保存',
    edit:          '编辑',
    close:         '关闭',
    loading:       '加载中…',
    refresh:       '刷新',
    retry:         '重试',
    yes:           '是',
    no:            '否',
    or:            '或',
    success:       '成功',
    failed:        '失败',
    error:         '错误',
    none:          '无',
    just_now:      '刚刚',
    minutes_ago:   '{n}分钟前',
    hours_ago:     '{n}小时前',
    empty_dash:    '—',
    formatted:     '已格式化',
    invalid_json:  'JSON 格式错误',
  },

  nav: {
    graph:         '图谱',
    entries:       '记忆',
    profile:       '画像',
    query:         '洞察',
    admin:         '管理',
  },

  stats: {
    entries:       '记忆',
    memos:         '备忘',
    nodes:         '节点',
    edges:         '关系',
  },

  admin: {
    title:                  '管理操作',
    export_entries:         '导出 Entries',
    import_entries:         '导入 Entries',
    process_pending:        '批量处理 Pending',
    reset_derived:          '重置派生数据',
    reset_all:              '重置全部数据',
    reset_derived_title:    '重置派生数据',
    reset_all_title:        '重置全部数据',
    reset_derived_label:    '派生数据（保留 entries）',
    reset_all_label:        '所有数据（含 entries）',
    reset_message:          '将清除{label}，此操作不可恢复。',
    reset_confirm:          '确认重置',
    reset_success:          '重置成功',
    processed:              '处理了 {count} 条',
    export_failed:          '导出失败',
  },

  import: {
    title:           '导入记忆',
    formats_hint:    '支持单条对象、数组 [ ]、或 {entries: []} 格式',
    paste_json:      '粘贴 JSON',
    valid:           '✓ 合法',
    invalid:         '✗ 格式错误',
    format_button:   '格式化',
    file_select:     '选择文件',
    importing:       '导入中…',
    import:          '导入',
    confirm_title:   '导入 {count} 条记忆',
    confirm_message: '将追加到现有数据，不会覆盖已有内容。',
    confirm_button:  '确认导入',
    parse_error:     '无法识别的格式，需要单条对象、数组或 {entries:[...]}',
    nothing_to_import: '没有可导入的记录',
  },

  language: {
    label:    '语言',
    chinese:  '中文',
    english:  'English',
  },

  graph: {
    all:               '全部',
    nodes_hint:        '{count} 节点 · 单击节点展开/折叠',
    reset:             '重置',
    fit_window:        '适应窗口',
    empty:             '暂无图谱数据，请先写入记忆并处理',
    expanding:         '正在展开邻居…',
    open_detail:       '查看详情',
    close_detail:      '关闭详情',
    external_tag:      '[外部]',
    unexpanded_hint:   '◐ 还有 {n} 个未展开邻居',
    relation_prefix:   '关系',
    legend_shapes:     '● 人物 ■ 概念 ◆ 规律 ⬡ 方法',
    legend_pending:    '琥珀双线 = 待探索',
    legend_expanded:   '青色光圈 = 已展开',
    weight:            '权重',
    activation_count:  '激活次数',
    last_activation:   '最近激活',
    expand_n:          '◐ 展开 {n} 个邻居',
    expanding_label:   '◐ 展开中…',
    collapse_branch:   '⊖ 折叠分支',
    click_to_collapse: '提示：单击当前节点可折叠分支',
    user_relevance:    '与用户的关联',
    summary:           '内容摘要',
    neighbors_n:       '相邻节点 · {n}',
    no_neighbors:      '暂无关系',
    edge_props:        '关系属性',
    relation_type:     '关系类型',
    strength:          '强度',
    confidence:        '置信度',
    source_entry:      '来源 Entry',
    strength_short:    'strength',
    activated_n_times: '激活 {n} 次',
  },

  profile: {
    loading:               '加载中…',
    empty:                 '暂无画像数据，请先处理一些记忆',
    current:               '当前画像',
    timeline:              '演化时间线',
    sources_n:             '{n} 条来源',
    score_label:           '分',
    confidence_label:      '置信',
    based_on_n:            '基于 {n} 条记忆',
    no_data:               '暂无数据',
    no_evolution:          '暂无演化数据',
    chart_ocean:           'OCEAN 人格演化',
    chart_schwartz:        'Schwartz 价值观演化',
  },

  entries: {
    write_placeholder:     '写点什么… (Ctrl+Enter 提交)',
    storing:               '存储中…',
    store:                 '存储',
    tab_entries:           '记忆',
    tab_memos:             '备忘',
    loading:               '加载中…',
    has_node_marker:       '节点',
    failed:                '失败',
    processing:            '处理中…',
    process:               '处理',
    cascade_revert_title:  '级联撤销（含之后 {n} 条）',
    revert_one_title:      '撤销此条记忆',
    reverting:             '撤销中…',
    cascade_revert:        '撤销+{n}',
    revert:                '撤销',
    no_memos:              '暂无备忘',
    select_one:            '选择一条记忆查看详情',
    write_failed:          '写入失败: {error}',
    delete_title:          '删除 Entry #{id}',
    delete_message:        '将同时删除关联的切片和激活记录，无法恢复。',
    revert_title:          '撤销 Entry #{id}',
    revert_message:        '将回滚该条记忆对图谱和画像的影响，entry 状态变为 reverted。{cascade}',
    revert_cascade_note:   '\n\n将同时级联撤销之后的 {n} 条记忆。',
    revert_failed:         '撤销失败: {error}',
    nodes_edges:           '{nodes}节点 {edges}边',
    memo_label:            '备忘',
    memo_id:               '备忘 #{id}',
    keywords:              '关键词',
    metadata:              '元信息',
    captured_at:           '记录时间',
    date:                  '日期',
    weekday:               '星期',
    time_of_day:           '时段',
    channel:               '来源',
    source_type:           '类型',
    timezone:              '时区',
    status_captured:       '待处理',
    status_processed:      '已处理',
    status_slice_failed:   '处理失败',
    status_reverted:       '已撤销',
    view_trace:            '查看 Trace',
    slice_analysis:        '切片分析',
    activation_nodes:      '激活节点 · {n}',
    not_processed:         '尚未处理',
    frame_present:         '当下',
    frame_retrospective:   '回顾',
    frame_hypothetical:    '假设',
    stance_present:        '当下反思',
    stance_recount:        '复述过去',
    stance_mixed:          '混合',
    sit_temporal:          '时间视角',
    sit_stance:            '叙述立场',
    sit_phase:             '人生阶段',
    sit_emotion:           '情绪',
    sit_pressure:          '压力',
    sit_energy:            '能量',
    trace_run_at:          '运行于 {time}',
    export_one:            '导出本条',
    export_one_title:      '导出本条 entry 的完整 trace 为 JSON 文件',
    export_all:            '导出全部',
    export_all_title:      '导出全部 entries 的 trace 打包文件，便于离线评测',
    export_failed:         '导出失败: {error}',
    no_trace:              '暂无 Trace 数据，请先执行处理',
    stage_slice:           'Slice 切片',
    stage_activation:      'Activation 激活',
    stage_rough_recall:    '粗召回 Top-K',
    stage_node_extract:    'Node Extract 各域提取',
    stage_subgraph:        '精召回 子图',
    stage_edge_extract:    'Edge Extract LLM输出',
    stage_db_diff:         'DB Diff 实际变更',
    badge_empty:           '空',
    badge_n_items:         '{n}项',
    badge_has_data:        '有数据',
    empty_text:            '空',
    no_slice:              '无切片数据',
    no_change:             '无变化',
    no_activation:         '无激活域',
    no_extract:            '无提取结果',
    no_subgraph:            '无子图',
    no_confirmed:          '无确认节点',
    no_edge_extract:       '无边提取结果',
    no_diff:               '无 diff 数据',
    no_db_change:          '无 DB 变更',
    th_field:              '字段',
    th_score:              '分数',
    th_label:              '标签',
    th_domain:             '域',
    th_type:               '类型',
    th_status:             '状态',
    th_description:        '描述',
    th_relation:           '关系',
    th_direction:          '方向',
    th_evidence:           '证据',
    th_id:                 'id',
    th_domain_act:         '域',
    badge_new:             '新建',
    badge_hit:             '命中',
    nodes_edges_label:     '{nodes} 节点 · {edges} 边',
    new_nodes_n:           '新建节点 ({n})',
    update_nodes_n:        '更新节点 ({n})',
    new_edges_n:           '新建边 ({n})',
    update_edges_n:        '更新边 ({n})',
    domain_n_nodes:        '{domain} ({n}个节点)',
  },

  fieldHint: {
    conf_title:            'Confidence (conf)',
    conf_body:             `LLM 对该次提取结果的置信度，范围 0–1，由模型直接输出。

用途：
• profile merge 中作为新信号权重
• 决定是否进入 slice_features
• 低于 0.15 的信号会被直接丢弃，不进入画像
• node 写入时影响 strength 增量：
    delta = clamp(0.02–0.15, conf × 0.15)

含义：0.9 = 模型非常确定；0.3 = 弱信号；<0.15 = 噪声过滤`,
    strength_title:        'Strength',
    strength_body:         `节点的累计激活强度，范围理论上无上界，实际常见 0–3。

更新公式（每次 entry 命中该节点）：
    new_strength = (1 - α) × old × time_decay + α × conf
其中 α 由 confidence 决定。

含义：
• 高 strength (>1.5)：用户反复提及的认知锚点
• 中 strength (0.5–1.5)：有一定历史积累
• 低 strength (<0.5)：刚建立或很久未被强化

在查询链路中，strength 决定节点被激活和召回的优先级。`,
    weight_title:          'Edge weight',
    weight_body:           `边的累计强化强度，从 0 开始累加，理论上限由配置决定。

LLM 边更新公式（每次被 entry 关联）：
    weight += clamp(min_delta, max_delta, base × conf)
    weight = min(weight, weight_cap)

强度等级（查询时动态标注）：
• weak    < 0.25：1–2 次观测，关系刚建立
• moderate 0.25–0.5：多次强化，有意义的模式
• strong  ≥ 0.5：深度建立，高置信结构性连接

注意：weak 不等于不可信，只代表观测次数少。算法边（相似/关联）有独立上限（0.3 / 0.5）。`,
    sim_title:             'Similarity (sim)',
    sim_body:              `语义向量余弦相似度，范围 0–1，由 embedding 模型计算。

用途：
• 粗召回阶段：从向量库检索与当前 entry 最相关的存量节点
• 算法边触发：sim ≥ 0.78 时自动建立"相似"边
• 关联边触发：sim ≥ 0.20 时建立"关联"边（共现兜底）

含义：0.9+ = 几乎相同语义；0.7–0.9 = 强相关；0.5–0.7 = 有关联；<0.5 = 弱相关`,
  },

  query: {
    stage_intent:        '意图识别',
    stage_baseline:      '通用解答',
    stage_raw_recall:    'Raw 召回',
    stage_persona:       '人格穿刺',
    stage_explore:       '图谱探索',
    stage_synthesis:     '综合分析',
    tool_graph_search:   '语义搜索',
    tool_expand_node:    '展开子图',
    tool_get_opposites:  '寻找对立',
    tool_web_search:     'Web 搜索',
    err_unknown:         '未知错误',
    confirm_clear_title: '清除查询历史',
    confirm_clear_msg:   '所有历史记录将被永久删除。',
    confirm_clear_btn:   '清除',
    placeholder_initial: '输入问题，对你的认知图谱发起查询…',
    placeholder_followup:'继续追问…',
    empty_hint:          '输入问题开始探索你的认知图谱',
    generating:          '生成中…',
    queue_n:             '已排队 {n} 个问题',
    turn_n_followup:     '第 {n} 轮 · 可继续追问，上下文已自动携带',
    continue_session:    '继续此对话 · 发送后延续历史上下文',
    mode_full:           '完整',
    mode_fast:           '快速',
    new_chat:            '新建对话',
    history_label:       '历史对话',
    streaming_back:      '正在生成 · 点击返回',
    no_history:          '暂无历史记录',
    turns_n:             '{n} 轮',
    confirm_del_title:   '删除记录',
    confirm_del_msg:     '此条查询记录将被永久删除。',
    badge_n_nodes:       '{n} 节点',
    nodes:               '节点',
    edges:               '边',
    origin_internal:     '内源',
    origin_external:     '外源',
    raw_records_n:       '{n} 条原始记录',
    raw_total_chars:     '· {n} 字',
    raw_candidates_n:    ' · 候选 {n}',
    raw_records_click:   '{n} 条原始记录（点击展开）',
    inject_history:      '注入的历史上下文',
    copy_md:             '复制为 Markdown',
    copied:              '✓ 已复制',
    download_md:         '↓ 下载 .md',
    section_baseline:    '通用解答',
    section_persona:     '人格穿刺',
    section_synthesis:   '图谱洞察',
    md_q:                '**问题**: {q}',
    md_history:          '### 历史上下文',
    md_q1:               '### Q1 通用解答',
    md_q2:               '### Q2 人格穿刺',
    md_agent:            '### Agent 调用链路',
    md_raw:              '### Raw 原文召回（用于 synthesis 的真实证据）',
    md_q3:               '### Q3 图谱洞察（synthesis）',
    md_q4:               '## Q4 主题深析（合并文本）',
    tool_label_search:   '图谱搜索',
    tool_label_expand:   '展开子图',
    tool_label_opposite: '对立挖掘',
    tool_label_web:      'Web 搜索',
    agent_log:           'Agent 调用链路 · {n} 次',
    expand_payload:      '展开返回内容',
    raw_recall_n:        'Raw 原文召回 · {n} 主题 / {entries} 条',
  },
}

/** Dict shape is derived from `dict` but widens leaf strings so en.ts can
 *  provide different (still string) values at the same keys. */
type Widen<T> = T extends string ? string : { [K in keyof T]: Widen<T[K]> }
export type Dict = Widen<typeof dict>

const typed: Dict = dict
export default typed
