# 招投标采购 RAG-Agent MVP 验收测试报告

| 项目 | 内容 |
|---|---|
| 系统名称 | 招投标采购智能问答与辅助评标系统（Bidding_QA_Chatbot） |
| 报告版本 | V1.0 |
| 测试日期 | 2026-09-18 |
| 测试执行人 | 自动化验收套件（tests/acceptance/run_acceptance.py） |
| 基线代码 | commit `c1ec425`（MVP 24 项验收基线）＋本轮专项工具补齐（P7 报价计算 / P8 投标文件解析器 / P9 围串标线索） |
| 报告依据 | 原始执行日志、evidence.json、db_evidence.json、UI 截图（见第 7 章附件索引） |

---

## 1. 验收结论

**在本次测试范围内，32 项验收用例全部通过（PASS 32 / FAIL 0 / ERROR 0，通过率 100.0%），MVP 约定的 5 项核心能力、3 项扩展能力（P4/P5/P6）、权限控制、工作流编排，以及《招投标采购专用 Agent 工具》7 项清单全部具备验收条件。**

第三轮（2026-09-18 12:52）针对专项工具清单补齐的 8 个新用例全部一次通过，其中报价计算为纯规则可复现，围串标/投标解析经 LLM 输出结构性断言，未放宽断言口径。

需要说明的边界（详见第 6 章）：

1. 首轮测试曾暴露 6 个真实缺陷（含 1 个核心链路缺口：上传的招标文件未进入向量检索库），全部修复后经第二轮全量回归验证通过；修复过程与验证证据在第 4、5 章完整留痕。
2. 围串标工具**只输出线索不自动定性**；文件属性维度仅支持 docx/pdf 标准元数据（作者/最后保存者/生成程序/公司），IP/MAC 仅识别正文暴露地址，电子标书平台专有元数据格式暂不支持——该输入限制随接口结果 `limitations` 字段返回。

---

## 2. 测试范围

### 2.1 范围内（本次验收覆盖）

| 模块 | 验收点 | 对应用例 |
|---|---|---|
| 运行环境 | FastAPI 后端、PostgreSQL、Qdrant 向量库连通性 | ENV-01 ~ ENV-03 |
| MVP-1 招标文件库 | 文档列表查询、结构化字段与全文存储、上传→解析→入库→**自动向量化** | M1-01 ~ M1-03 |
| MVP-2 混合检索+引用 | BM25+Dense 混合检索、reranker 精排、答案带原文引用（命中文档库分片） | M2-01 |
| MVP-3 条款提取 | 评分办法、资格要求列表的结构化抽取 | M3-01 ~ M3-02 |
| MVP-4 条款检查 | 合规性扫描（排他性条款分级）、资格条件逐条比对、废标条款提取 | M4-01 ~ M4-03 |
| MVP-5 人工复核留痕 | 登录态复核记录与 user_id 自动关联、非法入参拦截 | M5-01 ~ M5-02 |
| P4 响应性检查 | 招标要求 vs 投标逐条判定（响应/正偏离/负偏离/未响应） | P4-01 |
| P5 评分辅助表 | 评分办法→结构化打分表，权重合计校验 | P5-01 |
| P6 多家投标对比 | 三家投标 9 字段并排对比矩阵 | P6-01 |
| P7 报价计算 | 行内算术/分项汇总/中文大写/最高限价校验＋低价优先价格分 | P7-01 ~ P7-03 |
| P8 投标文件解析器 | 单份投标→商务响应/技术方案/资格业绩三维度结构化 JSON | P8-01 |
| P9 围串标线索 | 文本雷同/正文 IP·MAC/文件属性/报价规律，只提示不定性；含工作流节点注册 | P9-01 ~ P9-04 |
| 权限控制 | 注册/登录/鉴权全链路、错误密码 401、无 token 401、默认管理员 | AUTH-01 ~ AUTH-04 |
| 工作流编排 | 预置清单查询、合规审查 DAG（3 节点）、评标辅助 DAG（2 节点） | WF-01 ~ WF-03 |

### 2.2 范围外说明

- 专用 Agent 7 项工具清单已全部交付，无未实现项；
- 围串标的电子标书平台专有元数据（部分省市交易平台导出的机器码/加密狗信息）暂不支持，已在接口输出 `limitations` 中声明；
- 压力/并发性能、深度安全渗透测试不在本次范围（见 2.3）。

### 2.3 未覆盖的测试类型

- 压力/并发性能测试（本轮仅记录单请求耗时，无并发基准）；
- 浏览器级逐页面深度交互回归（UI 仅对关键路径截图留证，见 7.2）；
- 安全渗透（JWT 只做了正向/反向鉴权用例，未做 token 篡改、过期边界、越权水平扫描）。

---

## 3. 测试环境

### 3.1 软件环境

| 组件 | 版本 / 配置 |
|---|---|
| 操作系统 | Windows（DESKTOP-26K8KR8） |
| Python | 3.12.10 |
| FastAPI | 0.141.1 |
| SQLAlchemy | 2.0.52 |
| 鉴权 | python-jose（JWT, HS256）＋ bcrypt 直接哈希（rounds=12） |
| PostgreSQL | 本地 localhost:5432，库名 chatbot，账号 postgres |
| Qdrant | 本地实例，集合向量点数 **338**（回归时实测） |
| 嵌入/精排模型 | BGE-M3（dense+sparse）＋ reranker-v2-m3 |
| 前端 | Next.js，localhost:3000 |
| 后端 | uvicorn，localhost:8001（回归时运行修复后代码） |

### 3.2 测试数据

- 主测试文档：db_id=6，`test_bid.txt`，项目"XX市智慧园区信息化建设项目（二期）"，全文 1736 字，预算 8,600,000.00 元，投标截止 2025-12-15 14:00，资格要求 12 条，解析状态 ok；
- 上传链路用例动态生成 `acceptance_upload_test.txt`（入库后 db_id=8）；
- 鉴权用例每次运行动态注册时间戳账号（如 acpt_user01_1789705591），不复用固定口令数据；
- P6 用固定三家模拟投标（报价 820/950/880 万元）。

---

## 4. 测试用例执行情况

### 4.1 总览（第三轮全量回归，专项工具补齐后）

- 执行时间：2026-09-18 12:52 起，端到端约 6 分 08 秒；
- **共 32 项：PASS 32，FAIL 0，ERROR 0，通过率 100.0%**；
- 原始输出：`tests/acceptance/run_log_round3.txt`；结构化结果：`tests/acceptance/evidence.json`。

| 测试组 | 通过/总数 |
|---|---|
| 环境 | 3/3 |
| MVP1 文档库 | 3/3 |
| MVP2 检索 | 1/1 |
| MVP3 条款提取 | 2/2 |
| MVP4 条款检查 | 3/3 |
| P4 响应性 | 1/1 |
| P5 评分辅助表 | 1/1 |
| P6 多家对比 | 1/1 |
| P7 报价计算 | 3/3 |
| P8 投标解析器 | 1/1 |
| P9 围串标线索 | 4/4 |
| Auth 权限 | 4/4 |
| MVP5 复核留痕 | 2/2 |
| Workflow 编排 | 3/3 |
| **合计** | **32/32** |

### 4.2 用例明细（耗时与关键观测均取自实际执行日志）

| 用例 ID | 用例名称 | 结果 | 耗时 | 关键观测 |
|---|---|---|---|---|
| ENV-01 | 后端服务存活 /api/health | PASS | 2103ms | ready/agent_ready/graph_ready/pg_ready 均 true，points=338 |
| ENV-02 | PostgreSQL 已连接 | PASS | 2074ms | pg_ready=true |
| ENV-03 | Qdrant 向量库已连接且有向量 | PASS | 2064ms | 向量点数 338，rag_ready=true |
| M1-01 | 文档列表可分页查询 | PASS | 2037ms | 库内 7 份文档 |
| M1-02 | 文档含结构化字段+全文 | PASS | 2055ms | #6 含项目名/预算/截止时间/评分办法/资格要求，全文 1736 字 |
| M1-03 | 上传→解析入库+自动向量化 | PASS | 4611ms | db_id=8，parse_status=ok，写入向量分片 1 个 |
| M2-01 | 问答带引用且命中文档库 | PASS | 4098ms | 答案 316 字，引用 2 条均为 tender_document 分片；截止时间、预算两个事实均命中原文 |
| M3-01 | 评分办法结构化提取 | PASS | 2056ms | "综合评分法总分100：价格40/技术35/商务15/业绩10" |
| M3-02 | 资格要求列表非空 | PASS | 2041ms | 12 条 |
| M4-01 | 合规性扫描 | PASS | 10860ms | 检查 15 项，风险 2（中 2/高 0/低 0），status=attention |
| M4-02 | 资格条件逐条比对 | PASS | 21020ms | 返回 summary/checks/gap_report/verdict/action_suggestions |
| M4-03 | 废标条款提取 | PASS | 12561ms | 提取 12 条废标条款（含原文表述） |
| P4-01 | 投标逐条响应判定 | PASS | 34902ms | 25 条：响应 4、正偏离 2，verdict=attention |
| P5-01 | 评分办法→打分表 | PASS | 3519ms | 价格/技术/商务/业绩 4 项，合计 100.0 分 |
| P6-01 | 三家投标并排对比 | PASS | 7151ms | 9 字段；报价列 820/950/880 万元抽取正确 |
| P7-01 | 正确报价表（算术/汇总/大写/价格分） | PASS | 2056ms | 合计 740,000；大写柒拾肆万一致；最低价基准价格分 100；verdict=pass |
| P7-02 | 行内算术不符＋超最高限价 | PASS | 2039ms | verdict=fail；命中 ROW_ARITHMETIC/SUM_MISMATCH/OVER_CONTROL_PRICE |
| P7-03 | 大小写金额不一致 | PASS | 2067ms | 大写 750,000 vs 数字 740,000 → CN_MISMATCH |
| P8-01 | 单份投标三维度结构化 | PASS | 4972ms | 商务 6/6、技术 4/4、资质 1 条；报价 820 万元/工期 100 日历天 |
| P9-01 | 雷同文本＋接近报价（不定性） | PASS | 2071ms | 2 条高风险线索（文本雷同/报价规律），含免责声明与双方原文证据 |
| P9-02 | 内容独立投标不误报 | PASS | 2040ms | Jaccard 0.08，verdict=clean，0 线索 |
| P9-03 | 少于 2 份被拒 | PASS | 2065ms | HTTP 400 |
| P9-04 | 围串标注册为工作流节点 | PASS | 2060ms | 自定义 DAG 节点 success，输出 clues_found |
| AUTH-01 | 注册→登录→/auth/me | PASS | 6588ms | 新用户全链路，role=auditor |
| AUTH-02 | 错误密码被拒 | PASS | 4471ms | HTTP 401「用户名或密码错误」 |
| AUTH-03 | 无 token 访问受保护接口 | PASS | 2058ms | HTTP 401「未登录」 |
| AUTH-04 | 默认管理员可用 | PASS | 2239ms | admin/admin123，role=admin |
| M5-01 | 复核记录 user_id 关联 | PASS | 8559ms | review id=6，reviewer=复核员甲，**user_id=11 与登录账号一致** |
| M5-02 | 非法 review_type 拦截 | PASS | 2037ms | HTTP 400 |
| WF-01 | 预置工作流清单 | PASS | 2054ms | compliance_review、eval_assist |
| WF-02 | 合规审查一条龙 DAG | PASS | 44919ms | 3 节点全部 success，verdict=ok |
| WF-03 | 评标辅助一条龙 DAG | PASS | 35026ms | 2 节点全部 success，verdict=ok |

### 4.3 首轮执行结果（修复前，留痕对照）

- 执行时间：2026-09-18 11:38:35，共 23 项：**PASS 20 / FAIL 3 / ERROR 0，通过率 87.0%**；
- FAIL 项：M1-02（文档列表缺结构化字段）、M3-01、M3-02（同一根因）；
- 首轮另有 2 项"测试通过但证据异常"的问题被人工复核拦下并深查：M2-01 首轮引用 0 条却判 PASS（问题表述不含项目名，未暴露链路缺口）、M5-01 user_id 显示 None（查询接口未返回该列，直查数据库证实写入端实际为 user_id=8）；
- 首轮记录：`tests/acceptance/run_log_round1.txt`（控制台原始日志）；首轮结构化 evidence.json 已被第二轮覆盖，其结论性数据以本报告 4.3 节与该日志留痕。

---

## 5. 缺陷发现与修复记录

首轮测试及缺陷分析阶段共记录 **6 个缺陷**，全部修复并经第二轮回归验证。未通过"放宽断言迁就实现"的方式消缺——其中 D2/D3 是在测试通过的情况下主动深查发现的。

| 编号 | 严重度 | 现象 / 根因 | 修复内容 | 验证方式 | 状态 |
|---|---|---|---|---|---|
| D1 | 中 | `/api/documents` 列表 SQL 只返回 7 个摘要列，不含 qualification_requirements/scoring_criteria，致 M1-02、M3-01、M3-02 FAIL | postgresql_client.list_documents 补齐结构化字段列 | M1-02/M3-01/M3-02 第二轮 PASS | 已关闭 |
| D2 | **高** | **核心链路缺口：上传的招标文件只写 PostgreSQL，未向量化入 Qdrant，问答无法检索用户自己上传的文档**（FAQ 库 326 点中无招标分片） | 新增 ingest_tender_document（500 字滑窗分片+dense/sparse 双向量+独立 ID 段+重传去旧）；上传端点自动调用；对存量 3 份有效文档回填（点数 326→338） | M1-03 上传后返回 vector_indexed_chunks=1；M2-01 命中 2 个招标分片 | 已关闭 |
| D3 | 高 | Agent 工具路由把"某项目的截止时间/预算"类问题导向 SQL/图谱（工具描述仅写"法规流程概念"），不走向量库 | 更新 search_bidding_knowledge 工具描述与系统提示路由指引，明确招标文件内容类问题首选该工具 | M2-01 tool_name=search_bidding_knowledge，答案准确引用原文（860 万元、2025-12-15 14:00） | 已关闭 |
| D4 | 中 | 单变体 Query 走 lru_cache 路径时只保留 question/answer/score，丢失 source_file/doc_type/db_id，引用溯源断链 | pipeline 缓存与返回改为保留完整文档 dict；vector_store 元数据白名单增补 db_id/business_line | M2-01 引用条目携带 doc_type=tender_document | 已关闭 |
| D5 | 中 | 工作流 rejection 节点误写模块名（rejection_checker.check_rejection，实际为 bid_rejection_checker.check_bid_rejection）；且惰性注册"一次失败永不重试"，合规龙恒为 2/3 | 修正 6 个工具的模块/函数名与参数签名，wrapper 支持 db_id 自动取文档，注册改为逐工具幂等补注册 | WF-02 由 partial(2/3) 转为 ok(3/3) | 已关闭 |
| D6 | 低 | list_reviews 查询未 SELECT user_id，审计列表无法看到操作人（写入端与外键关联本身正常） | 查询补 user_id 列 | M5-01 经接口查到 user_id=11，与登录账号一致 | 已关闭 |

附：验收期间另修复 2 项既有基建问题（前序会话已提交，本轮回归受益）：SQLAlchemy 2.x 无 RETURNING 的 INSERT 结果集读取（begin 事务 + returns_rows 保护）；passlib 与 bcrypt 4.0 不兼容（改直调 bcrypt）。

---

## 6. 风险评估与遗留事项

| # | 事项 | 影响 | 建议 |
|---|---|---|---|
| R1 | 围串标工具仅识别 docx/pdf 标准元数据与正文 IP/MAC；电子标书平台专有机器码无法解析；报价可从正文正则抽取也可显式传入 | 专项场景（如某省交易平台加密标书）需另做适配；关键案件建议以显式报价入参复核 | 收集各平台导出格式样本后扩展解析器；线索类输出已强制人工复核 |
| R2 | LLM 输出具非确定性：同一废标检查两轮分别抽出 17/12 条，响应性检查 18/25 条 | 条款类结果条数会波动；测试断言已采用结构性/下界口径，不锁死条数 | 生产场景建议人工复核环节兜底（M5 已具备）；后续可加 schema 校验与温度固定策略 |
| R3 | AUTH_ENABLED 默认 false，业务端点可匿名访问 | 便于兼容旧流程，但生产部署若忘记开启则鉴权形同虚设 | 部署文档显式标注；生产环境默认值改为 true |
| R4 | 验收测试数据残留：acpt_* 测试账号多组、上传文档 db_id=8/9、复核测试记录若干 | 不影响功能，但统计口径会被污染 | 验收后提供清理脚本或标记测试数据 |
| R5 | Qdrant 本地实例用 API key + http 明文；未做并发/性能基准 | 本机开发无风险，上生产需加固；大文档/多并发性能未知 | 上生产改 https + 内网隔离；补并发基准测试 |
| R6 | JWT 仅覆盖正反向鉴权用例，未做篡改/过期/水平越权扫描 | 安全保证深度有限 | 上线前补安全测试用例集 |

---

## 7. 测试证据附件索引

所有证据位于 `tests/acceptance/`，与本报告同目录：

### 7.1 机器可读证据

| 文件 | 说明 |
|---|---|
| run_acceptance.py | 32 项验收用例源码（可重复执行，零外部测试框架依赖） |
| evidence.json | 第三轮回归结构化结果（32 项逐条 status/耗时/备注/错误） |
| db_evidence.json | 数据库实物证据：5 张表清单、users 记录、bidding_documents 计数与 #6 字段、document_reviews 列结构及最近 6 条（含 user_id） |
| run_log_round2.txt | 第二轮全量执行原始控制台日志（24/24 PASS） |
| run_log_round1.txt | 首轮执行原始控制台日志（23 项：20 PASS / 3 FAIL，修复前留痕） |
| run_log_round3.txt | 第三轮全量执行原始控制台日志（32/32 PASS，P7-P9 专项工具） |
| collect_db_evidence.py / backfill_index.py | DB 证据采集脚本、存量招标文档向量回填脚本 |
| collusion_sample_a.txt / collusion_sample_b.txt | 围串标原件上传端点（/api/collusion/upload）测试样本，实测命中雷同/相同 IP/报价接近 3 条高风险线索 |

### 7.2 UI 截图证据（screenshots/）

| 文件 | 内容 |
|---|---|
| 01_documents_overview.png | 文件解析页总览（文档卡片 + 功能按钮区） |
| 02_login_dialog.png | 登录/注册弹窗 |
| 03_logged_in.png | 登录后用户名+角色标签+退出 |
| 04_workflow_dialog.png | 智能工作流弹窗（2 个预置 + 文档下拉，共 8 个可选文档） |
| 05_workflow_result.png | 合规审查一条龙执行结果面板（节点状态/耗时） |
| 06_back_to_qa.png | 文件解析页右上角"← 返回问答"入口（点击已验证跳转问答首页） |

### 7.3 复测方法

1. 启动 PostgreSQL、Qdrant 后，运行后端：`.venv\Scripts\python.exe -m uvicorn api.server:app --port 8001`；
2. 执行：`.venv\Scripts\python.exe tests\acceptance\run_acceptance.py`；
3. 退出码 0 即全部通过；结果写入 evidence.json。
   注意：单次执行约 6 分钟（含 10+ 次真实 LLM 工具调用），需可用的 LLM 服务；执行会产生 1 份测试上传文档与临时测试账号。
