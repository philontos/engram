/**
 * English translations. Mirrors the structure of zh.ts exactly.
 * Type-checked against zh.ts via the Dict type.
 */
import type { Dict } from './zh'

const dict: Dict = {
  common: {
    cancel:        'Cancel',
    confirm:       'Confirm',
    ok:            'OK',
    delete:        'Delete',
    save:          'Save',
    edit:          'Edit',
    close:         'Close',
    loading:       'Loading…',
    refresh:       'Refresh',
    retry:         'Retry',
    yes:           'Yes',
    no:            'No',
    or:            'or',
    success:       'Success',
    failed:        'Failed',
    error:         'Error',
    none:          'None',
    just_now:      'just now',
    minutes_ago:   '{n}m ago',
    hours_ago:     '{n}h ago',
    empty_dash:    '—',
    formatted:     'Formatted',
    invalid_json:  'Invalid JSON',
  },

  nav: {
    graph:         'Graph',
    entries:       'Memory',
    profile:       'Profile',
    query:         'Insight',
    admin:         'Admin',
  },

  stats: {
    entries:       'Entries',
    nodes:         'Nodes',
    edges:         'Edges',
  },

  admin: {
    title:                  'Admin actions',
    export_entries:         'Export entries',
    import_entries:         'Import entries',
    process_pending:        'Process pending',
    reset_derived:          'Reset derived data',
    reset_all:              'Reset all data',
    reset_derived_title:    'Reset derived data',
    reset_all_title:        'Reset all data',
    reset_derived_label:    'derived data (entries kept)',
    reset_all_label:        'all data (including entries)',
    reset_message:          'This will clear {label} and cannot be undone.',
    reset_confirm:          'Confirm reset',
    reset_success:          'Reset succeeded',
    processed:              'Processed {count} entries',
    export_failed:          'Export failed',
  },

  import: {
    title:           'Import memories',
    formats_hint:    'Accepts a single object, an array [ ], or {entries: []}',
    paste_json:      'Paste JSON',
    valid:           '✓ valid',
    invalid:         '✗ invalid',
    format_button:   'Format',
    file_select:     'Select file',
    importing:       'Importing…',
    import:          'Import',
    confirm_title:   'Import {count} memories',
    confirm_message: 'Will be appended to existing data; nothing will be overwritten.',
    confirm_button:  'Confirm import',
    parse_error:     'Unrecognized format. Expected a single object, an array, or {entries:[...]}',
    nothing_to_import: 'No entries to import',
  },

  language: {
    label:    'Language',
    chinese:  '中文',
    english:  'English',
  },

  graph: {
    all:               'All',
    nodes_hint:        '{count} nodes · click a node to expand/collapse',
    reset:             'Reset',
    fit_window:        'Fit',
    empty:             'No graph data yet — capture some entries and process them first',
    expanding:         'expanding neighbors…',
    open_detail:       'Show detail',
    close_detail:      'Close detail',
    external_tag:      '[external]',
    unexpanded_hint:   '◐ {n} more unexpanded neighbors',
    relation_prefix:   'relation',
    legend_shapes:     '● person ■ concept ◆ pattern ⬡ method',
    legend_pending:    'amber double-line = pending exploration',
    legend_expanded:   'cyan halo = expanded',
    weight:            'Weight',
    activation_count:  'Activations',
    last_activation:   'Last activated',
    expand_n:          '◐ Expand {n} neighbors',
    expanding_label:   '◐ Expanding…',
    collapse_branch:   '⊖ Collapse branch',
    click_to_collapse: 'Tip: click the current node to collapse its branch',
    user_relevance:    'User relevance',
    summary:           'Summary',
    neighbors_n:       'Neighbors · {n}',
    no_neighbors:      'No relations',
    edge_props:        'Edge properties',
    relation_type:     'Relation type',
    strength:          'Strength',
    confidence:        'Confidence',
    source_entry:      'Source entry',
    strength_short:    'strength',
    activated_n_times: 'activated {n} times',
  },

  profile: {
    loading:               'Loading…',
    empty:                 'No profile data yet — process some entries first',
    current:               'Current profile',
    timeline:              'Evolution timeline',
    sources_n:             '{n} sources',
    score_label:           'score',
    confidence_label:      'conf',
    based_on_n:            'based on {n} entries',
    no_data:               'No data',
    no_evolution:          'No evolution data yet',
  },

  entries: {
    write_placeholder:     'Write something… (Ctrl+Enter to submit)',
    storing:               'Saving…',
    store:                 'Save',
    tab_entries:           'Entries',
    loading:               'Loading…',
    has_node_marker:       'nodes',
    failed:                'failed',
    processing:            'Processing…',
    process:               'Process',
    cascade_revert_title:  'Cascade revert (also reverts {n} later)',
    revert_one_title:      'Revert this entry',
    reverting:             'Reverting…',
    cascade_revert:        'Revert+{n}',
    revert:                'Revert',
    select_one:            'Select an entry to see details',
    write_failed:          'Save failed: {error}',
    delete_title:          'Delete Entry #{id}',
    delete_message:        'Will also remove the linked slice and activation records. Cannot be undone.',
    revert_title:          'Revert Entry #{id}',
    revert_message:        'Will roll back this entry\'s effect on the graph and profile; the entry status becomes reverted.{cascade}',
    revert_blocked_title:  'Revert in order',
    revert_blocked_msg:    'There are {n} newer processed entries on top of this one. Revert them first (newest first) before reverting this one.',
    revert_failed:         'Revert failed: {error}',
    nodes_edges:           '{nodes} nodes, {edges} edges',
    status_captured:       'pending',
    status_processed:      'processed',
    status_slice_failed:   'failed',
    status_reverted:       'reverted',
    view_trace:            'View trace',
    slice_analysis:        'Slice analysis',
    activation_nodes:      'Activated nodes · {n}',
    not_processed:         'Not processed yet',
    frame_present:         'present',
    frame_retrospective:   'retrospective',
    frame_hypothetical:    'hypothetical',
    stance_present:        'present reflection',
    stance_recount:        'recounting past',
    stance_mixed:          'mixed',
    sit_temporal:          'Temporal frame',
    sit_stance:            'Narrator stance',
    sit_phase:             'Life phase',
    sit_emotion:           'Emotion',
    sit_pressure:          'Pressure',
    sit_energy:            'Energy',
    trace_run_at:          'ran at {time}',
    export_one:            'Export one',
    export_one_title:      'Download this entry\'s full trace as a JSON file',
    export_all:            'Export all',
    export_all_title:      'Download a bundled trace archive of all entries (for offline analysis)',
    export_failed:         'Export failed: {error}',
    no_trace:              'No trace yet — run processing first',
    stage_slice:           'Slice',
    stage_activation:      'Activation',
    stage_rough_recall:    'Rough recall (top-K)',
    stage_node_extract:    'Node Extract (per domain)',
    stage_subgraph:        'Fine recall — subgraph',
    stage_edge_extract:    'Edge Extract (LLM output)',
    stage_db_diff:         'DB diff (actual changes)',
    badge_empty:           'empty',
    badge_n_items:         '{n} items',
    badge_has_data:        'has data',
    empty_text:            'empty',
    no_slice:              'no slice data',
    no_change:             'no changes',
    no_activation:         'no activated domains',
    no_extract:            'no extraction results',
    no_subgraph:            'no subgraph',
    no_confirmed:          'no confirmed nodes',
    no_edge_extract:       'no edge-extract output',
    no_diff:               'no diff data',
    no_db_change:          'no DB changes',
    th_field:              'Field',
    th_score:              'Score',
    th_label:              'Label',
    th_domain:             'Domain',
    th_type:               'Type',
    th_status:             'Status',
    th_description:        'Description',
    th_relation:           'Relation',
    th_direction:          'Direction',
    th_evidence:           'Evidence',
    th_id:                 'id',
    th_domain_act:         'Domain',
    badge_new:             'new',
    badge_hit:             'hit',
    nodes_edges_label:     '{nodes} nodes · {edges} edges',
    new_nodes_n:           'New nodes ({n})',
    update_nodes_n:        'Updated nodes ({n})',
    new_edges_n:           'New edges ({n})',
    update_edges_n:        'Updated edges ({n})',
    domain_n_nodes:        '{domain} ({n} nodes)',
  },

  fieldHint: {
    conf_title:            'Confidence (conf)',
    conf_body:             `LLM confidence in this extraction, range 0–1, output directly by the model.

Used for:
• Weighting the new signal during profile merge
• Deciding whether the row enters slice_features
• Signals below 0.15 are dropped and never enter the profile
• Affects strength delta when writing a node:
    delta = clamp(0.02–0.15, conf × 0.15)

Meaning: 0.9 = highly confident; 0.3 = weak signal; <0.15 = filtered as noise`,
    strength_title:        'Strength',
    strength_body:         `Cumulative activation strength of a node. Theoretically unbounded; in practice usually 0–3.

Update formula (each time an entry hits the node):
    new_strength = (1 - α) × old × time_decay + α × conf
where α is determined by confidence.

Meaning:
• High strength (>1.5): a recurring cognitive anchor for the user
• Mid strength (0.5–1.5): some historical accumulation
• Low strength (<0.5): newly created or long unreinforced

At query time, strength drives node activation and recall priority.`,
    weight_title:          'Edge weight',
    weight_body:           `Cumulative reinforcement strength of an edge, accumulated from 0; the upper bound is configurable.

LLM-edge update formula (each time the edge is reinforced by an entry):
    weight += clamp(min_delta, max_delta, base × conf)
    weight = min(weight, weight_cap)

Strength tier (annotated dynamically at query time):
• weak    < 0.25: 1–2 observations, just established
• moderate 0.25–0.5: repeatedly reinforced, meaningful pattern
• strong  ≥ 0.5: deeply established, high-confidence structural link

Note: weak does not mean unreliable — it just means few observations. Algorithmic edges (similar/related) have independent caps (0.3 / 0.5).`,
    sim_title:             'Similarity (sim)',
    sim_body:              `Semantic embedding cosine similarity, range 0–1, computed by the embedding model.

Used for:
• Rough recall: vector search for the most relevant existing nodes for the current entry
• Algorithmic similar edge: triggers when sim ≥ 0.78
• Related (co-occurrence) edge: triggers when sim ≥ 0.20

Meaning: 0.9+ ≈ near-identical semantics; 0.7–0.9 = strongly related; 0.5–0.7 = related; <0.5 = weakly related`,
  },

  query: {
    tool_expand_node:    'Expand subgraph',
    tool_get_opposites:  'Find opposites',
    tool_web_search:     'Web search',
    err_unknown:         'unknown error',
    confirm_clear_title: 'Clear query history',
    confirm_clear_msg:   'All history will be permanently deleted.',
    confirm_clear_btn:   'Clear',
    placeholder_initial: 'Ask your cognitive graph a question…',
    placeholder_followup:'Follow up…',
    empty_hint:          'Ask a question to start exploring your cognitive graph',
    generating:          'generating…',
    queue_n:             '{n} questions queued',
    turn_n_followup:     'Turn {n} · keep asking — context is preserved automatically',
    continue_session:    'Continue this conversation · history will be carried forward',
    new_chat:            'New chat',
    history_label:       'History',
    streaming_back:      'streaming · click to return',
    no_history:          'No history yet',
    turns_n:             '{n} turns',
    confirm_del_title:   'Delete record',
    confirm_del_msg:     'This query record will be permanently deleted.',
    badge_n_nodes:       '{n} nodes',
    nodes:               'Nodes',
    edges:               'Edges',
    origin_internal:     'internal',
    origin_external:     'external',
    raw_records_n:       '{n} raw records',
    raw_total_chars:     '· {n} chars',
    raw_candidates_n:    ' · candidates {n}',
    raw_records_click:   '{n} raw records (click to expand)',
    inject_history:      'Injected conversation history',
    copy_md:             'Copy as Markdown',
    copied:              '✓ Copied',
    download_md:         '↓ Download .md',
    section_baseline:    'Baseline',
    section_persona:     'Persona lens',
    section_synthesis:   'Graph insight',
    tool_label_search:   'Graph search',
    tool_label_expand:   'Expand subgraph',
    tool_label_opposite: 'Opposites mining',
    tool_label_web:      'Web search',
    agent_log:           'Agent tool calls · {n}',
    expand_payload:      'expand returned content',
    raw_recall_n:        'Raw recall · {n} themes / {entries} records',
    // Agent-mode UI
    thinking:               'Thinking',
    thinking_meta:          '· {rounds} rounds · {calls} tool calls',
    round_n:                'Round {n}',
    tool_running:           'running…',
    tool_recall_raw:        'recall_raw',
    tool_recall_raw_by_node:'recall_raw_by_node',
    tool_search_graph:      'search_graph',
    tool_get_neighborhood:  'get_node_neighborhood',
    tool_compare_nodes:     'compare_nodes',
    tool_list_blindspots:   'list_blindspots',
    tool_list_bridges:      'list_bridges',
    tool_find_paths:        'find_evolution_paths',
    tool_persona_lens:      'get_persona_lens',
    tool_history_answer:        'recall_history_answer',
    tool_history_tools:         'recall_history_tools',
    tool_history_tool_detail:   'recall_history_tool_detail',
    bridges:                'Bridges',
    paths:                  'Paths',
    web_results:            'Web results',
  },
}

export default dict
