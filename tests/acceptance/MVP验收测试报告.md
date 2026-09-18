# 招投标采购 RAG-Agent MVP 验收测试报告

| 项目 | 内容 |
|---|---|
| 系统名称 | 招投标采购智能问答与辅助评标系统（Bidding_QA_Chatbot） |
| 报告版本 | V1.3（在 V1.2 41 项基线上新增⑨"无引用不生成"硬闸门、⑩标书生成闭环：Agent 工具＋单章流式＋前端一键生成） |
| 测试日期 | 2026-09-18（V1.3 回归） |
| 测试执行人 | 自动化验收套件（tests/acceptance/run_acceptance.py）＋离线确定性测试＋浏览器 UI 实测 |
| 基线代码 | V1.2 commit `7faee05`/`cf4bef6`/`d40bbc6` 等；V1.3 改动见第 5 章（尚未提交） |
| 报告依据 | 全量执行日志 run_log_bid3.txt、evidence.json、离线测试输出、UI 截图（见第 7 章） |

---

## 1. 验收结论

**V1.3 验收套件共 45 项，全量回归 45 PASS / 0 FAIL / 0 ERROR（通过率 100%）。V1.2 唯一波动项 M2-01 本轮由"无引用不生成"硬闸门从机制上根治（35.4s 稳定通过，命中 2 条招标分片与截止/预算双事实）；新增 GATE-01 证明跨领域虚构问题在 LLM 多轮改写检索后仍被硬拒。**

本轮（⑨⑩）交付的关键结论：

1. **⑨"无引用不生成"硬闸门形成确定性防线**：纯函数判定（寒暄放行 / 强制补检索一次 / 固定话术硬拒三态）；RAG 低分噪声（均分 <0.3）不算证据；**问题特征词覆盖判据**防止通用法规 FAQ 为虚构具体项目"背书"；未取证即作答会被丢弃答案强制补检索。离线 44 断言 + GATE-01 全过。
2. **⑩标书生成闭环贯通**：对话内 Agent 工具（list_bid_documents / generate_bid_draft，强制走工具严禁代写、行级权限继承）→ 单章同步/SSE 流式端点（5 章：技术/商务/资格/项目管理/售后）→ 前端文档页"一键生成标书"入口（流式 Markdown、章节切换、复制、导出 Word、占位符提示、同类案例计数）→ docx 导出支持给定 Markdown 直出。BID-01/02/03 + 浏览器实测全过。
3. **⑦权限隔离形成三层闭环**：JWT 角色（管理员/审计专家/招标人/投标人）→ 业务 API 行级检查（owner_id/visibility，匿名同样强制检查）→ **RAG 向量召回层 Qdrant 预过滤**（修复了"业务 API 挡住了、对话问答仍能召回内部文档分片"的真实越权漏洞）。RBAC 相关 8 个验收用例 + 1 个离线隔离专项测试全部通过。
4. **⑧检索质量可量化**：17 条真实用例的纯离线评测，基线 HitRate@5=100%、MRR=1.0000、漏检 0%、引用准确率 32.94%、证据覆盖 100%。
5. **①扫描件/Excel 可用**：无文本层中文扫描 PDF 自动 OCR 正确；xlsx 多 Sheet 提取正确。
6. **③引用可定位到页**：PDF 按页切分不跨页，引用卡片显示"文件名＋第 N 页"，包件/投标人元数据全链路持久化。
7. **⑥评审状态机合法可控**：初评→质疑→复审→结案，服务端强制流转合法性（非法 400）、全程操作人留痕；浏览器实测面板流转与历史时间线正常。
8. 存量向量分片权限已幂等回填：326 条 FAQ→public、28 条招标分片按 PG 权限对齐、0 条错误兜底。

历史边界（V1.x 已声明，仍然有效）：围串标只输出线索不定性；电子标书平台专有元数据暂不支持；LLM 输出具非确定性。

---

## 2. 测试范围

### 2.1 范围内（V1.2 覆盖矩阵）

| 模块 | 验收点 | 对应用例 |
|---|---|---|
| 运行环境 | FastAPI/PostgreSQL/Qdrant 连通 | ENV-01 ~ ENV-03 |
| MVP-1 招标文件库 | 列表/结构化字段/上传→解析→入库→自动向量化 | M1-01 ~ M1-03 |
| MVP-2 混合检索+引用 | 混合检索、rerank、答案带原文引用（命中文档库分片） | M2-01 |
| MVP-3 条款提取 | 评分办法、资格要求结构化 | M3-01 ~ M3-02 |
| MVP-4 条款检查 | 合规扫描/资格比对/废标提取 | M4-01 ~ M4-03 |
| MVP-5 人工复核 | **管理员建专家号**→登录复核→user_id 关联、非法入参 400 | M5-01 ~ M5-02 |
| P4-P6 | 响应性判定/评分辅助表/三家对比 | P4-01、P5-01、P6-01 |
| P7 报价计算 | 算术/汇总/大写/限价/价格分 | P7-01 ~ P7-03 |
| P8 投标解析 | 商务/技术/资格三维度结构化 | P8-01 |
| P9 围串标 | 雷同/IP/文件属性/报价规律，只提示不定性＋工作流节点 | P9-01 ~ P9-04 |
| Auth | 注册/登录/me、错误密码 401、无 token 401、默认管理员 | AUTH-01 ~ AUTH-04 |
| **⑦ RBAC** | 自助注册角色与冒充降级、投标人 403 矩阵、管理员建号端点鉴权、internal 文档行级可见性（A 可见/B 不可见/投标人不可见/管理员可见）、匿名与投标人对内部检查端点 403、投标人强制 internal | RBAC-01/02/02B/03/04/05 |
| **③ 页码/包件** | PDF 按页解析回传 page_count=2、包件持久化、按页向量化 | META-01 |
| **⑥ 评审状态机** | 初评→质疑→复审→结案全链路＋历史留痕＋非法流转 400；匿名 401/投标人 403/跨租户 403/不存在 404 | STAGE-01 ~ STAGE-02 |
| **⑨ 无引用不生成硬闸门** | 无证据问题 gated=True 返回固定话术、sources=0；RAG 低分噪声与通用法规 FAQ 不得放行 | GATE-01 + 离线 44 断言 |
| **⑩ 标书生成闭环** | 对话触发 generate_bid_draft（exec_log 工具轨迹）、/api/bid/section 同步（5 章/非法章节 400）、单章流式、行级权限（投标人/匿名对 internal 403，owner 200）、docx 导出 | BID-01 ~ BID-03 |
| Workflow | 预置清单、合规 DAG、评标辅助 DAG | WF-01 ~ WF-03 |
| **离线专项** | 检索质量评测（17 例 5 指标）、页码切分、RAG 召回行级隔离、**硬闸门纯函数 44 断言** | tests/eval/ 四个脚本 |
| **① OCR/Excel** | 扫描件 OCR、xlsx 提取（离线手工实测，见 4.4） | 离线实测 |
| **浏览器 UI** | 注册角色选择、投标人入口隐藏、上传元数据表、状态机面板、引用文件名/页码、**标书生成器弹窗（流式渲染/章节切换/复制/导出 Word/占位符/案例计数）** | 9 张截图（7.2） |

### 2.2 范围外说明（截至 V1.3 仍未覆盖）

- 压力/并发性能、安全渗透（token 篡改/过期/水平越权穷举扫描）；
- 移动端 H5/公众号、CA/USBKey 认证、敏感词过滤、平台对接（属后续二期，已在需求符合性评估中记录）；
- OCR/Excel 未纳入 HTTP 自动验收（以离线实测＋META-01 上传链路间接覆盖 PDF 侧）。

---

## 3. 测试环境

### 3.1 软件环境

| 组件 | 版本 / 配置 |
|---|---|
| 操作系统 | Windows（DESKTOP-26K8KR8） |
| Python | 3.12.10；FastAPI 0.141.1；SQLAlchemy 2.0.52 |
| 鉴权 | python-jose（JWT, HS256）＋ bcrypt rounds=12；4 角色 RBAC |
| PostgreSQL | 本地 localhost:5432，库名 chatbot |
| Qdrant | 本地实例，集合 bid_qa_v2，回归时 **374 点**（含权限回填） |
| 嵌入/精排 | BGE-M3（dense+sparse）＋ reranker-v2-m3 |
| OCR/文档 | rapidocr-onnxruntime 1.4.4（懒加载）、pymupdf、openpyxl |
| 前后端 | Next.js localhost:3000；uvicorn localhost:8001（运行最新代码） |

### 3.2 测试数据

- 主测试文档 db_id=6 `test_bid.txt`（智慧园区项目，预算 860 万，截止 2025-12-15 14:00，public）；
- 每轮动态生成时间戳账号（acpt_*）与上传文档（V1.2 轮 db_id 18~22；V1.3 轮至 db_id 47），internal 隔离用文档自带 PKG-A 等标记；
- 离线测试使用隔离 ID 段（db_id 999001/999002/999003，虚构 uid 880001/880002），结束即清理。

---

## 4. 测试用例执行情况

### 4.1 总览（V1.3 全量回归，2026-09-18 晚）

- **共 45 项：PASS 45，FAIL 0，ERROR 0，通过率 100.0%**；
- 原始输出：`run_log_bid3.txt`（仓库未纳管，留存本地）；结构化结果：`tests/acceptance/evidence.json`。

| 测试组 | 通过/总数 |
|---|---|
| 环境 | 3/3 |
| MVP1 文档库 | 3/3 |
| MVP2 检索 | 1/1（硬闸门上线后稳定，35.4s） |
| MVP3 条款提取 | 2/2 |
| MVP4 条款检查 | 3/3 |
| P4/P5/P6 | 3/3 |
| P7 报价计算 | 3/3 |
| P8 投标解析器 | 1/1 |
| P9 围串标线索 | 4/4 |
| Auth 权限 | 4/4 |
| MVP5 复核留痕 | 2/2 |
| **⑦ RBAC 权限隔离** | **6/6** |
| **③ 页码/包件** | **1/1** |
| **⑥ 评审状态机** | **2/2** |
| Workflow 编排 | 3/3 |
| **⑨ 无引用不生成硬闸门** | **1/1** |
| **⑩ 标书生成闭环** | **3/3** |
| **合计** | **45/45** |

### 4.2 新增用例明细（本轮，关键观测均取自实际日志）

| 用例 ID | 用例名称 | 结果 | 耗时 | 关键观测 |
|---|---|---|---|---|
| RBAC-01 | 投标人自助注册；冒充 admin 注册强制降级 | PASS | 6.7s | bidder 注册 role=bidder；提交 role=admin 被服务端静默降级 |
| RBAC-02 | 投标人被禁：复核写/查、围串标检测 | PASS | 10.6s | 三端点均 403 |
| RBAC-02B | 管理员建号端点鉴权 | PASS | 8.5s | 匿名 401、投标人 403（admin 建号 200 另由 M5-01 覆盖） |
| RBAC-03 | internal 文档行级可见性 | PASS | 27.4s | doc=19（PKG-A）：owner A 可见、另一招标人不可见、投标人不可见、管理员可见 |
| RBAC-04 | 内部文档检查端点 | PASS | 8.6s | 投标人 403、匿名 403（匿名由原先误放行 200 修复为快速 403） |
| RBAC-05 | 投标人不得公开上传 | PASS | 19.0s | 显式 public→403；auto→internal（doc=20），本人可见他人不可见 |
| META-01 | PDF 页数回传＋包件持久化 | PASS | 12.1s | sample_multipage.pdf：page_count=2、package=PKG-PDF、4 个按页分片 |
| STAGE-01 | 状态机全链路＋非法拦截 | PASS | 24.8s | doc=22：start/challenge/start_recheck/close 四步成功，history 动作序列一致，操作人留痕；结案后再流转与未知动作均 400 |
| STAGE-02 | 状态机端点权限矩阵 | PASS | 32.1s | 匿名 POST/GET=401/401，投标人=403，跨租户 internal=403，不存在文档=404，owner=200 |
| M5-01 | 管理员建专家号→复核关联（重写） | PASS | 10.8s | admin 建 auditor→登录→review id=9，user_id 自动关联 |
| WF-02/WF-03 | 两条 DAG | PASS | 24.4s/42.6s | 3/3、2/2 节点全 success（WF-03 上轮 180s 超时，本轮通过） |
| GATE-01 | 硬闸门：知识库无证据的问题禁止 LLM 自由生成 | PASS | 71.1s | 跨领域虚构问题触发 4 次检索（含 LLM 自行改写 query 命中共性法规 FAQ，均分 0.5+ 但不含问题特征词）；gated=True、sources=0、返回 155 字固定受控话术 |
| BID-01 | 对话内触发 generate_bid_draft 生成标书章节 | PASS | 38.3s | 工具轨迹=['generate_bid_draft']（严禁代写生效）、gated=False、答案 1458 字、exec_log 完整回传 |
| BID-02 | /api/bid/section 单章同步生成（公开招标文件） | PASS | 18.6s | title=技术方案、正文 1216 字、已参考同类案例 3 条；非法 section 名返回 400 |
| BID-03 | 单章生成行级权限 | PASS | 54.1s | doc=47（internal）：投标人 403、匿名 403、owner 200 且生成 794 字 |

其余 30 个存量用例（ENV/M1/M3/M4/P4-P9/AUTH/M5-02/WF-01）V1.3 轮全部 PASS，观测与 V1.1 报告一致（耗时随 LLM 负载波动）；M2-01 见 4.5 更新。

### 4.3 离线确定性测试（不依赖 HTTP/LLM，可重复执行）

| 脚本 | 结果 | 关键断言 |
|---|---|---|
| tests/eval/run_retrieval_eval.py | **PASS** | 17 例：HitRate@5=100%、漏检 0%、MRR=1.0000、CitationPrecision@5=32.94%、EvidenceCoverage=100%；报告 retrieval_eval_report.json/.md |
| tests/eval/test_page_chunking.py | **PASS** | 3 页注入→6 分片，page_no={1,2,3}、chunk_id 含 pN、package/bidder_name 写入、语义检索命中第 3 页且透传页码 |
| tests/eval/test_retrieval_access.py | **PASS** | 公开 2 片/内部 2 片：匿名仅召回 public、owner 可见本人 internal、其他投标人/招标人不可见、admin/auditor 全见；pipeline 缓存按身份分桶（≥2 桶） |
| tests/eval/test_evidence_gate.py | **PASS** | **硬闸门纯函数 44 断言**：寒暄识别 16 例；工具证据判定（RAG 高/低分阈值 0.3、PG/图谱空结果、标书工具越权文本、执行失败、未知工具）；gate_decision 三态状态机；问题特征词覆盖（通用法规 FAQ 不为虚构项目背书、纯通用问题不约束）；固定话术不含业务事实 |

### 4.4 OCR / Excel 离线实测（①）

- 自制无文本层中文扫描 PDF：RapidOCR 正确识别"招投标测试扫描件/项目编号"等内容，逐页 page_no 正确；单页异常隔离不拖垮整体；
- xlsx：openpyxl 多 Sheet 提取，Sheet 名以 `## Sheet:` 保留、单元格以 ` | ` 连接；
- 上传端点 accept 已含 .xlsx/.xls，前端上传提示同步更新。

### 4.5 M2-01 历史波动项的根治说明（V1.3 更新）

- V1.2 现象：匿名 POST /api/chat 偶发 sources 为空（ReAct 当轮未调用检索工具），当时定性为 LLM 非确定性，仅 prompt 软约束；
- V1.3 机制修复（不再依赖 LLM 自觉）：
  1. **未取证即作答 → 服务端丢弃答案并强制补检索 1 次**；仍无证据 → 返回固定受控话术（done 事件 `gated=True`、sources=0），不进入 LLM 自由生成；
  2. RAG 并行工具执行 Context 独立复制（修"Context is already entered"崩溃，见 D12），检索超时放宽到 90s 并在**服务启动时后台预热 RAG**（冷启首查实测 >120s，预热后 30-40s）；
  3. 低相关噪声（均分 <0.3）不算证据；
- V1.3 结果：M2-01 35.4s PASS，答案 432 字、引用 2 条 tender_document、截止/预算双事实命中；GATE-01（虚构项目）历经 4 轮检索（含改写 query 命中高分通用法规 FAQ）仍被特征词覆盖判据硬拒，71.1s PASS。

### 4.5b 标书闭环补充实测（自动化套件外的手工冒烟，均通过）

- `POST /api/bid/section/stream`：SSE 事件序列 meta → token* → done，5 个章节均可流式生成；
- `POST /api/export/docx`：给定已生成 Markdown 直接导出（不再重复调 LLM），文件约 38KB、ZIP(PK) 头合法；中文文件名通过 `filename*=UTF-8''` 编码下发（修 D15）；
- 对话实测"请根据 6 号招标文件帮我生成投标技术方案章节草稿"：工具轨迹 `['generate_bid_draft']`、答案 1697 字、gated=False。

### 4.6 浏览器 UI 实测（2026-09-18，admin/admin123 与新注册投标人 uibid_1789735700）

| 验证点 | 结果 | 证据 |
|---|---|---|
| 注册态含"投标人/招标人"身份选择，默认投标人 | PASS | 01_register_role.png |
| 投标人登录后无"智能工作流""围串标线索"入口；上传区有包件号/投标人名称/内部文件勾选（默认选中且禁用） | PASS | 02_bidder_view.png |
| 管理员可见两入口，徽标"管理员" | PASS | 03_admin_view.png |
| 文档详情评审面板：未开始→提交评审→初评（历史含操作人"系统管理员"）→初评结案→结案（按钮消失，两条历史） | PASS | 04_stage_none/05_stage_initial/05b_stage_closed.png |
| 对话引用卡片显示来源文件名 test_bid.txt；/api/chat/stream 200、sources 非空 | PASS | 06_chat_sources.png |
| **标书生成器入口（3 处）：列表行绿色钢笔按钮、详情弹窗"一键生成标书"、上传解析结果区** | PASS | bid_ui_1.png |
| **生成器弹窗：技术方案 SSE 流式 Markdown 渲染、[公司全称] 等占位符提示、"已参考 3 条同类案例"** | PASS | bid_ui_2.png |
| **章节切换/复制 Markdown/导出 Word 按钮齐备，正文 1200-1900 字** | PASS | bid_ui_3.png |

全程浏览器控制台无报错（存量 9 个 tsc 类型告警与本次改动无关，改动前后一致）。

---

## 5. 本轮缺陷发现与修复记录（接 V1.1 D1-D6）

| 编号 | 严重度 | 现象 / 根因 | 修复内容 | 验证方式 | 状态 |
|---|---|---|---|---|---|
| D7 | 高 | **RAG 检索越权：向量库无 visibility/owner 概念，投标人/匿名在对话问答中可召回他人 internal 招标文件分片**（业务 API 的行级检查被检索链路绕过） | 新增 src/auth/access_scope.py（ContextVar 按请求注入身份范围）；hybrid_search 在 Qdrant 召回前根级 query_filter 预过滤；chat/chat-stream/ask/标书生成导出全覆盖；pipeline lru_cache 键含身份分桶；ingest 写权限字段；启动幂等回填 | test_retrieval_access PASS；匿名/管理员召回集合对比实测内部 11/15/19 仅管理员可见；RBAC-03/04 PASS | 已关闭 |
| D8 | 高 | 匿名访问 internal 文档检查端点曾被短路放行（200，耗时数十秒） | _assert_doc_readable 对匿名同样执行 can_read_document 行级检查 | RBAC-04 PASS（403 秒回） | 已关闭 |
| D9 | 中 | 专家账号可被自助注册（M5-01 旧流程自注册 auditor），违背最小权限 | 自助注册仅允许 bidder/purchaser，其余静默降级 bidder；新增 POST /auth/admin/users 由管理员建号 | RBAC-01/02B、M5-01 重写后 PASS | 已关闭 |
| D10 | 中 | PG 多条 ALTER 在同一事务，一条失败导致 owner_id/visibility/page_count 等列整体回滚 | 迁移 DDL 拆独立事务逐条执行；page_count/package/bidder_name 独立成组 | META-01、RBAC-03 PASS | 已关闭 |
| D11 | 低 | qdrant-client 当前版本 Prefetch 不支持 query_filter（pydantic extra_forbidden） | 过滤条件置于 query_points 根级（Qdrant 下推至各 prefetch 召回阶段，非后置截断） | 离线隔离测试 PASS | 已关闭 |
| D12 | 高 | 并行工具执行共用同一个 Context 副本，ThreadPoolExecutor 第二次进入即抛 "Context is already entered"（LLM 一轮并行调多个工具时必崩） | 每次 pool.submit 使用 `copy_context().run(...)` 独立上下文副本 | M2-01/多工具并行场景回归 PASS | 已关闭 |
| D13 | 高 | M2-01 波动根因：无引用时仅靠 prompt 软约束，LLM 可直接自由作答 | evidence_gate 三态闸门（强制补检索 1 次/固定话术硬拒），gated 标记透传至 done 事件；新增 GATE-01 与 44 条离线断言 | GATE-01、44 离线断言、45/45 全量 PASS | 已关闭 |
| D14 | 高 | 闸门两处证据误判：①跨领域低相关噪声（0.003-0.006 分）被算作证据；②LLM 改写 query 命中高分通用法规 FAQ（"投标保证金比例上限"）为虚构具体项目"背书" | ①RAG 均分 <0.3 不计证据；②问题剔除招投标通用词后提取特征 2-gram，证据文本须覆盖至少 1 个特征词，纯通用问题回退分数判据 | GATE-01 4 轮改写后仍 gated=True；通用 FAQ 类问题（"保证金怎么退"）正常放行 | 已关闭 |
| D15 | 中 | docx 导出中文文件名经 latin-1 编码头崩溃；且导出时重新调用 LLM 生成（与界面所见不一致、慢） | Content-Disposition 改 `filename=bid_draft.docx; filename*=UTF-8''...`；导出端点接受已生成 Markdown 直出 | 手工冒烟：38KB docx 合法下载、中文文件名正常 | 已关闭 |
| D16 | 中 | access_scope 上下文清理 finally 中两个 reset 误写同一变量（首个还错传 user token），每请求结束必抛 ValueError，/api/chat 500 | 分别 `_current_user.reset(tok_user)` / `_current_scope.reset(tok_scope)` | 全量 45 例 PASS（含全部 chat 用例） | 已关闭 |

V1.1 的 D1-D6 修复在本轮回归中持续有效。

---

## 6. 风险评估与遗留事项

| # | 事项 | 影响 | 建议 |
|---|---|---|---|
| R1 | 围串标仅识别标准元数据/正文 IP·MAC，平台专有机器码不支持 | 特定省市平台加密标书需适配 | 收集样本扩展；线索强制人工复核 |
| R2 | ~~LLM 非确定性：条款条数波动、M2-01 当轮未调工具~~（V1.3 已对"问答事实性"上硬闸门：无证据不放行、低相关/通用 FAQ 不背书） | 偶发拒答/条数变化仍可能存在 | 硬闸门＋强制补检索已上线；温度固定；M5 人工复核兜底；条款条数类波动可后续加结构化校验 |
| R3 | 默认 LLM 走云端 API（deepseek），非全本地闭环；日志明文；无敏感词过滤/CA 认证 | 政务场景合规差距 | 切 vLLM/Ollama 本地模型配置、加联网 kill-switch、日志加密、敏感词中间件（需求评估已列） |
| R4 | 业务端点保持匿名兼容（通过 public 文档实现，非跳过检查） | 匿名只能触达公开数据，符合设计；但部署方需正确标注 internal | 上传默认策略已按角色强制；部署文档说明 |
| R5 | 检索评测引用准确率 32.94%（top5 中平均仅约 1/3 分片与期望证据直接相关） | 不影响命中（HitRate 100%），但上下文有噪声、耗 token | 调 diversity/rerank 阈值；扩充评测集至 50+ 例后持续观测 |
| R6 | 测试数据残留（acpt_*、uibid_* 账号，db_id 18-22 等） | 统计口径污染 | 提供清理脚本或测试数据标记 |
| R7 | 未做并发/性能与渗透测试 | 生产保障未知 | 上线前补并发基准与 JWT 篡改/过期/水平越权扫描集 |
| R8 | 标书生成当前为**单章流式**（5 章独立生成），企业资料库未接入，[公司全称]/[资质证书号] 等占位符需人工补；尚无整本合稿、逐条招标要求响应对照表与不合格项自动标红 | 距离"全自动成册"仍有最后一段人工工序 | 后续接入企业资料库做占位符自动回填、整本合稿编排、响应对照表与偏离项标红 |

---

## 7. 测试证据附件索引

### 7.1 机器可读证据（tests/）

| 文件 | 说明 |
|---|---|
| acceptance/run_acceptance.py | **45 项**验收用例源码（含 RBAC/META/STAGE/GATE/BID 与 multipart 上传 helper） |
| acceptance/evidence.json | V1.3 结构化结果（逐条 status/耗时/备注） |
| acceptance/sample_multipage.pdf | META-01 用 2 页中文 PDF 夹具 |
| eval/retrieval_cases.json | 17 条检索评测用例（招标事实 7/企业 3/法规 7） |
| eval/run_retrieval_eval.py | 纯检索评测脚本（HitRate/漏检/MRR/引用准确率/证据覆盖，--min-hitrate 门禁） |
| eval/retrieval_eval_report.json/.md | 基线报告（HitRate@5=100%） |
| eval/test_page_chunking.py | 按页切分与元数据透传离线测试 |
| eval/test_retrieval_access.py | RAG 召回行级隔离离线测试 |
| eval/test_evidence_gate.py | **硬闸门纯函数离线测试（44 断言，无需 HTTP/LLM）** |

### 7.2 UI 截图证据（acceptance/screenshots/）

| 文件 | 内容 |
|---|---|
| 01_register_role.png | 注册弹窗的投标人/招标人身份选择 |
| 02_bidder_view.png | 投标人视图：无内部入口＋上传元数据表单（内部文件勾选锁定） |
| 03_admin_view.png | 管理员视图：工作流/围串标入口可见 |
| 04_stage_none.png | 文档详情评审面板（未开始＋提交评审） |
| 05_stage_initial.png | 提交评审后：初评徽标＋历史首条（含操作人） |
| 05b_stage_closed.png | 初评结案：结案徽标、按钮消失、两条历史 |
| 06_chat_sources.png | 问答答案＋引用来源卡片（test_bid.txt） |
| bid_ui_1.png | 文档列表行"一键生成标书"绿色钢笔入口 |
| bid_ui_2.png | 标书生成器弹窗：技术方案流式 Markdown＋占位符提示＋"已参考 3 条同类案例" |
| bid_ui_3.png | 章节切换、复制 Markdown、导出 Word 操作区 |

### 7.3 复测方法

1. 启动 PostgreSQL、Qdrant，运行后端（首次启动自动回填分片权限，见日志"分片访问权限回填完成"）：
   `.venv\Scripts\python.exe -m uvicorn api.server:app --port 8001`
2. 全量验收：`.venv\Scripts\python.exe tests\acceptance\run_acceptance.py`（约 10-15 分钟，需可用 LLM；产生临时账号/文档）；
3. 离线专项（无需 LLM/HTTP）：
   - `.venv\Scripts\python.exe tests\eval\run_retrieval_eval.py`
   - `.venv\Scripts\python.exe tests\eval\test_retrieval_access.py`
   - `.venv\Scripts\python.exe tests\eval\test_page_chunking.py`
   - `.venv\Scripts\python.exe tests\eval\test_evidence_gate.py`（硬闸门 44 断言）
4. 标书闭环：浏览器 http://localhost:3000/documents → 文档行钢笔按钮 → 选章节流式生成 → 复制/导出 Word；接口侧见 BID-01/02/03 与 4.5b。
5. 浏览器：frontend 目录 `npm run dev` 后访问 http://localhost:3000/documents，按 4.6 节路径复测。
