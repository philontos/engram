-- 001_chinese_to_english_enums.sql
-- Migrates legacy Chinese canonical enum values to English across backbone tables.
-- Idempotent: rows already in English are unaffected. Run once after upgrading code.
--
-- Mapping (canonical English in code/prompts/configs):
--   backbone_nodes.domain        : 心理学/哲学/历史/商业/科技/科学  →  psychology/philosophy/history/business/technology/science
--   backbone_nodes.node_type     : 人物/概念/规律/方法/学派         →  person/concept/pattern/method/concept (学派 is folded into concept)
--   backbone_edges.relation_type : 支撑/对立/推导/相似/关联          →  supports/opposes/derives/similar/related
--
-- Run:  sqlite3 ./data/cognitive/cognitive.db < migrations/001_chinese_to_english_enums.sql

BEGIN;

-- domain
UPDATE backbone_nodes SET domain = 'psychology' WHERE domain = '心理学';
UPDATE backbone_nodes SET domain = 'philosophy' WHERE domain = '哲学';
UPDATE backbone_nodes SET domain = 'history'    WHERE domain = '历史';
UPDATE backbone_nodes SET domain = 'business'   WHERE domain = '商业';
UPDATE backbone_nodes SET domain = 'technology' WHERE domain = '科技';
UPDATE backbone_nodes SET domain = 'science'    WHERE domain = '科学';

-- node_type
UPDATE backbone_nodes SET node_type = 'person'  WHERE node_type = '人物';
UPDATE backbone_nodes SET node_type = 'concept' WHERE node_type = '概念';
UPDATE backbone_nodes SET node_type = 'pattern' WHERE node_type = '规律';
UPDATE backbone_nodes SET node_type = 'method'  WHERE node_type = '方法';
UPDATE backbone_nodes SET node_type = 'concept' WHERE node_type = '学派';  -- legacy bucket, fold into concept

-- relation_type
UPDATE backbone_edges SET relation_type = 'supports' WHERE relation_type = '支撑';
UPDATE backbone_edges SET relation_type = 'opposes'  WHERE relation_type = '对立';
UPDATE backbone_edges SET relation_type = 'derives'  WHERE relation_type = '推导';
UPDATE backbone_edges SET relation_type = 'similar'  WHERE relation_type = '相似';
UPDATE backbone_edges SET relation_type = 'related'  WHERE relation_type = '关联';

-- query_logs.seeds_json contains embedded domain strings (e.g. {"domain": "心理学"}).
-- Rewrite the embedded values with text-level REPLACE on the well-anchored pattern.
UPDATE query_logs SET seeds_json = REPLACE(seeds_json, '"domain": "心理学"', '"domain": "psychology"') WHERE seeds_json LIKE '%心理学%';
UPDATE query_logs SET seeds_json = REPLACE(seeds_json, '"domain": "哲学"',   '"domain": "philosophy"') WHERE seeds_json LIKE '%哲学%';
UPDATE query_logs SET seeds_json = REPLACE(seeds_json, '"domain": "历史"',   '"domain": "history"')    WHERE seeds_json LIKE '%历史%';
UPDATE query_logs SET seeds_json = REPLACE(seeds_json, '"domain": "商业"',   '"domain": "business"')   WHERE seeds_json LIKE '%商业%';
UPDATE query_logs SET seeds_json = REPLACE(seeds_json, '"domain": "科技"',   '"domain": "technology"') WHERE seeds_json LIKE '%科技%';
UPDATE query_logs SET seeds_json = REPLACE(seeds_json, '"domain": "科学"',   '"domain": "science"')    WHERE seeds_json LIKE '%科学%';

COMMIT;

-- Verification queries (run manually; commented out for non-interactive execution):
-- SELECT DISTINCT domain        FROM backbone_nodes;
-- SELECT DISTINCT node_type     FROM backbone_nodes;
-- SELECT DISTINCT relation_type FROM backbone_edges;
