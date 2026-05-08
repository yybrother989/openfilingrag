# 新成员 Onboarding — OpenFilingRAG

欢迎加入。这份文档帮你在 1–2 天内对 repo 形成大概念地图，然后明确你接下来的核心方向：**继续探索更优的 filing parsing 方案 (不局限于 Docling)**。

---

## 1. 项目是什么

**OpenFilingRAG** 是一个 *filing-aware* 的 RAG 原型，专门处理上市公司披露文件 (SEC 10-K / 10-Q / 8-K / annual report / earnings transcript / investor presentation)。它和"普通 PDF chatbot"的核心区别是：

- **Structure-first retrieval**：检索决策依赖 *canonical filing sections* (Item 1, Item 1A Risk Factors, Item 7 MD&A 等约 15 个标准段落)，而不是纯 cosine 相似度。
- **Intent routing**：把用户问题分成 10 类研究意图 (revenue_drivers / margin_analysis / risk_analysis / liquidity_analysis / management_outlook / cross_year_comparison / segment_analysis …)，每类有独立的 `RetrievalPolicy`。
- **Hybrid scoring**：`0.45·vector + 0.30·keyword + 0.10·section_match + 0.10·source_priority + 0.05·recency`，每条 chunk 都带 `score_breakdown` 给 UI 解释为什么被召回。
- **Evidence-grounded 生成 + grounding-strict self-correction**：每个 finding 必须 cite `evidence_id`，没有引用的会被 reject 回去重写。
- **Compliance**：禁止给出投资建议；pre-query guard + post-gen 正则双重过滤。

技术栈：FastAPI + LangGraph + Postgres/pgvector (Supabase) + Next.js/assistant-ui，SSE 流式。

> 强烈建议先跑通：`make install && make edgar-pull TICKER=AAPL TYPES=10-K LIMIT=1 && make api && make demo`，然后在 [http://localhost:3000](http://localhost:3000) 提一个问题，看完整的 event timeline。这比读 10 页文档收益大得多。

参考：[README.md](README.md)、[CONTRIBUTING.md](CONTRIBUTING.md)。

---

## 2. 仓库地图 (要先记住的几条)

```
app/
  ingestion/       ← 你的主战场。parsing / chunking / table 抽取 / section 检测
    docling_adapter.py     ← 当前 Docling 实现 + 纯文本 fallback
    pipeline.py            ← parse → enrich → embed → 写库 的整条流水线
    sec_sections.py        ← canonical section taxonomy + 标题正则匹配器
    metadata_enricher.py   ← content_type / metric_tags / risk_tags
    source_id.py           ← 决定性 chunk_id (idempotent ingest)
    types.py               ← Chunk / DetectedSection / ExtractedTable

  retrieval/      ← hybrid retriever、metadata filter、PGVector、FTS、cross-encoder reranker
  graph/          ← LangGraph nodes (classify → plan → retrieve → verify → generate → validate → format)
  schemas/        ← Pydantic 合约 (CanonicalSection 枚举在这里)
  db/             ← ORM + 001_init.sql (companies / documents / sections / chunks / tables / reports / evidence)

scripts/
  edgar_pull.py            ← 从 SEC EDGAR 拉真实 filing
  ingest_sample.py         ← 走 ingest pipeline
  create_sample_report.py  ← 离线/mock 用合成 filing

frontend/        ← Next.js + assistant-ui 三栏终端 UI
tests/           ← pytest，全部 mock 模式可跑 (无需 Postgres / API key)
```

**第一周阅读顺序建议**：
1. [app/ingestion/types.py](app/ingestion/types.py) — 看清楚下游期待什么数据结构
2. [app/ingestion/sec_sections.py](app/ingestion/sec_sections.py) — section taxonomy 是 retrieval 的灵魂
3. [app/ingestion/docling_adapter.py](app/ingestion/docling_adapter.py) — 当前 parsing 实现
4. [app/ingestion/pipeline.py](app/ingestion/pipeline.py) — parsing 怎么接到 embed/写库
5. [app/graph/policies.py](app/graph/policies.py) — 看 retrieval 怎么用 section metadata，理解为什么 section 检测必须准
6. [app/retrieval/hybrid_retriever.py](app/retrieval/hybrid_retriever.py) — 看 metadata 怎么影响打分

---

## 3. ⚠️ 我们处理的文件有什么特殊性 (重点读)

这一节是你之后所有判断的基础。**SEC filing 不是普通的 PDF**，下面这些特性决定了"哪个 parser 在通用 benchmark 上排第一"基本不能直接外推到我们的场景。

### 3.1 Canonical 结构是检索的生命线
- 10-K / 10-Q 有一组**法定章节**：Item 1 Business、Item 1A Risk Factors、Item 7 MD&A、Item 7A Quantitative & Qualitative Disclosures、Item 8 Financial Statements & Notes、Item 9A Controls 等。
- 我们整套 retrieval 都基于这套 taxonomy (见 `CanonicalSection` 枚举)。**section 错分 = retrieval 直接失效**。"What are the key risks?" 必须命中 *Item 1A*，不能漂到任何提到 "risk" 的段落。
- 真实 filing 里标题写法极不统一："Item 1A. RISK FACTORS"、"ITEM 1A — Risk Factors"、"1A. Risk Factors."、纯居中无 "Item" 前缀、跨页断开、带脚注上标的标题…… 任何 parser 都必须能把这些**异写**统一到 canonical 名。

### 3.2 文件来源是 EDGAR 的 **iXBRL / HTML**，不是 PDF
- `make edgar-pull` 拿到的 primary document 绝大多数是 **inline XBRL (iXBRL)** —— 一个塞满 `<ix:nonNumeric>` / `<ix:nonFraction>` 标签的 HTML。每个数字、日期、entity 都带语义标签 (us-gaap:Revenues、dei:DocumentPeriodEndDate 等)。
- **这是巨大的金矿，但当前 pipeline 完全没有消费 XBRL 语义** (README "Limitations" 里列着)。把 iXBRL 当成普通 HTML 解析，等于扔掉了上市公司亲手贴好的事实标签。
- 历史 filing 也存在纯 PDF / 扫描 PDF 的情况 (尤其 board deck、非美股、早期 filing)，所以 parser 要兼顾两条路径。

### 3.3 Tables 是 first-class evidence
- Income statement / balance sheet / cash flow / segment breakdown / non-GAAP reconciliation 都是结构化表格，**margin_analysis / liquidity_analysis / segment_analysis 这几个 intent 严重依赖 table 的正确性**。
- 真实表格的麻烦：跨页延续 (Continued)、合并单元格、嵌套标题行、负数用括号、单位脚注 (`$ in millions`)、千分位空格、$/% 混排、横向 12 列窄字体。
- 当前用 Docling 的 **TableFormer** 抽，效果还行但远谈不上 production 级。**复杂多页表 + 合并 cell 经常崩。**

### 3.4 Footnote / cross-reference 网状结构
- 数字往往挂着上标 `(1)`、`(a)`、`*` 指向脚注；脚注和表格分别在不同页。
- "Note 12 — Segment Information" 这种跨段引用极常见。
- 引用关系如果断了，retrieval 召回的 evidence 拼出来就会缺关键限定语 (例如 "excluding restructuring charges")，下游的 grounding-strict 自我校正会直接把这条 finding 拒掉。

### 3.5 长度与 layout 噪声
- 一份大公司 10-K 经常 **150–300 页**，几十万 token。chunker 必须 layout-aware，否则会把 risk factor 切到一半或把表格切成纯文字流。
- Cover page、forward-looking statement boilerplate、signatures、certifications、exhibits index、auditor letter 这些大量出现但**对研究价值低**，应当被识别并降权 (现在没有专门处理)。
- 多列排版、页眉页脚、水印、内嵌图表 caption — 通用 PDF parser 经常会把这些和正文混进同一段。

### 3.6 我们输出 schema 已经稳定
不管换什么 parser，下游期待的还是 `(sections, chunks, tables, page_count)`：
- `DetectedSection.canonical_name` ∈ `CanonicalSection` 枚举
- `Chunk` 必带 `section_canonical` + `page_start/page_end` + `chunk_index`
- `ExtractedTable` 至少有结构化 cell 内容、所属 section、page span
- `chunk_source_id` 必须**确定性**，重跑 ingest 不能换 ID (PGVector upsert 依赖它)

任何替代方案都要能稳定填这些字段。`source_id` 决定性这一点尤其关键，是 idempotent ingest 的基石。

---

## 4. 你的任务：探索更好的 parsing 方案

**目标**：在保持 (或拓展) 当前下游 schema 的前提下，找到对 SEC filing **明显更优**的 parsing/chunking 流水线，并给出有数据支撑的推荐。

不要默认"换掉 Docling"也不要默认"留住 Docling"。先做证据驱动的对比，再下结论。**很可能最终是混合方案** (例如：iXBRL 走专用解析器、扫描 PDF 走 vision model、纯文本 fallback 留着) 而不是单一引擎。

### 4.1 评估维度 (按重要性排序)

1. **Section 检测准确率** — 给一组真实 10-K，人工打标 canonical section 起止位置，算 P/R/F1。
2. **Table 还原保真度** — 选 ≥10 张代表性表 (income statement、segment、cash flow、跨页、合并 cell)，对比 cell-level 准确率 + 结构 (header / units / footnote 链接) 是否保留。
3. **iXBRL 语义利用** — 是否能产出 `(metric_tag, value, period, unit, scale)` 的结构化 fact 流，用来给 retrieval 加 metric filter，并给生成阶段做事实校验。
4. **Footnote / cross-ref 保留** — 抽样若干带 `(1)` 上标的 cell，看脚注文本是否能挂回原 cell。
5. **长文档稳健性** — 200+ 页 10-K 不能 OOM；分钟级延迟可接受，小时级不行。
6. **扫描/OCR 路径** — 老 PDF 或非 SEC 文件 (board deck、非美股年报) 走得通吗？
7. **维护成本** — 依赖、license、更新频率、API 还是本地模型、GPU 需求。
8. **下游契合** — 能否稳定填出 `DetectedSection` / `Chunk` / `ExtractedTable` 而不需要重写整个 pipeline 接口。

### 4.2 候选方向 (起点，不是限制)

- **iXBRL 专用解析**：[Arelle](https://arelle.org/)、[python-edgar](https://github.com/dgunning/edgartools)、`sec-api.io`、`ix-edgar` —— 直接吃 XBRL fact graph，而不是把 HTML 当字符串。
- **layout-aware 通用方案**：Unstructured.io、LlamaParse、Reducto、Azure Document Intelligence (Form Recognizer)、AWS Textract、Google Document AI。
- **学术 / 开源 vision parser**：Marker、Nougat、MinerU、Dolphin、PaddleOCR-VL、GOT-OCR2.0。
- **专门的 SEC pipeline**：[sec-edgar-downloader](https://github.com/jadchaar/sec-edgar-downloader)、[sec-parsers](https://github.com/john-friedman/sec-parsers)、[edgartools](https://github.com/dgunning/edgartools) 的 chunked text。
- **混合策略**：iXBRL → fact stream；HTML 正文 → DOM-aware splitter；表格 → TableFormer 或 Reducto；扫描 PDF → vision model fallback。

### 4.3 建议的工作路径

1. **W1 跑通现状 + 建 ground truth**
   - 跑 `make edgar-pull` 至少各拉一份 AAPL / INTC / NVDA 的 10-K 和 10-Q (3.1–3.5 想覆盖完整需要这个混合面)。
   - 对其中 1–2 份 filing 人工标 section 边界 + 选 5–10 张表做 cell-level ground truth。这是后面所有对比的基线。
   - 把当前 Docling pipeline 在这份 ground truth 上的指标记录下来 (baseline)。

2. **W2 候选 spike**
   - 每个候选方案做最小可跑 demo (单文件输入 → `(sections, chunks, tables)`)，**不要先适配整套接口**，先看天花板。
   - 重点测 3.1 / 3.2 / 3.3，其他维度先粗估。

3. **W3 写报告 + 推荐**
   - 在 [`docs/`](docs/) 下新建 `parsing_evaluation.md`：维度 × 候选方案的矩阵 + 关键失败 case 截图/样例 + 最终推荐 + 迁移成本估计。
   - 推荐如果是"混合方案"，画出 routing 决策图 (按 file 类型 / 来源走哪条分支)。
   - 如果选定一个方向要落地，开 PR 写 adapter (复用现有的 `IngestionArtifacts` 出口)，新加 feature flag，让现存 Docling 路径仍可回退。

### 4.4 提交物清单

- [ ] `docs/parsing_ground_truth/` — 人工标的 section 边界 + 表格 ground truth (JSON/CSV)
- [ ] `docs/parsing_evaluation.md` — 候选对比报告 + 推荐 + 推荐理由
- [ ] (如果决定推进) `app/ingestion/<new>_adapter.py` — 与 `DoclingIngestor` 同形的实现 + 单测 + feature flag
- [ ] 一段 5–10 分钟的 walkthrough 视频 / 文档，让 reviewer 不需要重跑就能理解你的判断

---

## 5. 协作准则

- **小步提交**：评估阶段也建议每个候选一个分支 + 简短 PR，方便回看。
- **不要默默换核心路径**：parsing 改动牵动 retrieval 评测和 grounding 校验，每次大改前先在 issue / 文档同步思路。
- **测试**：`make lint && make test` 在 mock 模式跑通才能开 PR。新加的 adapter 至少要有 fixture-driven 单测覆盖 section 检测和 chunk 形状。
- **离线优先**：repo 设计目标之一是"无 API key 也能跑"。新依赖如果是云服务，要有本地/mock fallback 或显式 feature flag。
- **不要打破 idempotent ingest**：`chunk_source_id` 的稳定性是硬约束。

---

## 6. 第一天 checklist

- [ ] 读完 README "Why this is different" + "Architecture" 两节
- [ ] 跑通 `make install` → `make test` (全 mock 模式跑过)
- [ ] 跑通 `make edgar-pull TICKER=AAPL TYPES=10-K LIMIT=1`，肉眼看一份真实 10-K (HTML/iXBRL 源文件) 至少 30 分钟，对照本文档第 3 节自己对一遍特殊性
- [ ] 跑通 `make api && make demo`，从前端提一个 risk_analysis 问题，跟到 retrieval / verify / generate 每一步
- [ ] 在 [app/ingestion/docling_adapter.py](app/ingestion/docling_adapter.py) 打断点 / 加 log，看一份真实 filing 被切成什么样的 `Chunk` 和 `ExtractedTable`
- [ ] 找 [@yuegao](mailto:yybrother1@gmail.com) 聊 30 分钟，确认 ground truth 范围和评估指标

有任何卡点直接问，不要憋。

