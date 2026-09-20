# 招投标采购 RAG-Agent MVP 验收测试报告

| 项目 | 内容 |
|---|---|
| 系统名称 | 招投标采购智能问答与辅助评标系统（Bidding_QA_Chatbot） |
| 报告版本 | V2.3（多专家协作接入＋Agent 端到端评测基准＋小范围可用性验证前置：V2.2 59 项基线之上，①将孤立原型 multi_agent 工作流接入主问答（前端琥珀色"多专家协作"开关＋可折叠专家过程面板，后端端点补齐鉴权/限频/行级隔离/伪工具调用防御），新增 MULTI-01 验收；②建立 Agent 端到端评测基准集 12 题（单跳/多跳/跨域，工具选择＋答案事实双指标），新增纯函数打分器与 HTTP 评测器；③可用性验证前置三项：问答交互审计落库（chat.answer/out_of_scope/vague，仅存统计量与工具名）、复杂多跳问题 gated 后 query 改写重试一次、历史中标 bidding_procurement 脱敏种子数据 30 条（scripts/seed_bidding_procurement.py）；④意图识别升级为显式三业务线分类路由（intent.py 招投标/企业/法规/通用 评分分类器，显著单域裁剪 active_tools，跨域/弱信号保守回退全集，INTENT_ROUTING_ENABLED 可关），并修复分类路由冒烟暴露的 D25（本地权威目录工具未计入证据门致法规目录题被误拒）） |
| 测试日期 | 2026-09-20（V2.3 全量回归 60/60、Agent 评测 12 题两跑、浏览器实测，均为 PROFILE_ENC_KEYS 双密钥链环境；V2.1/V2.2 同日早些时候执行） |
| 测试执行人 | 自动化验收套件（tests/acceptance/run_acceptance.py）＋离线确定性测试＋Agent 端到端评测器（tests/eval/run_agent_eval.py）＋浏览器 UI 实测＋真实 MinIO 手动实测（V2.2） |
| 基线代码 | V2.2 commit `4dd4b50`（MinIO 实测版）；V2.3 在其上新增多专家接入与评测体系代码 |
| 报告依据 | V2.3 全量执行日志（60/60；意图路由版复跑 run_log_route.txt，GATE-01 36.6s 仍 gated/sources=0）、evidence.json（2026-09-20 12:54 复跑）、Agent 评测报告 agent_eval_report.json/.md（11/12，工具选择 100%）、UI 截图 v23_multi_agent.png、离线 pytest 160 项（含意图路由 14 项，见 4.5l）、硬闸门 54 断言（见 4.5l/D25） |

---

## 1. 验收结论

**V2.3 验收套件共 60 项，全量回归 60 PASS / 0 FAIL / 0 ERROR（通过率 100%，PROFILE_ENC_KEYS 双密钥链环境，验收脚本与后端以同一密钥链启动）。本期完成两件事：①多专家协作（multi_agent）从"仅有孤立端点的原型"正式接入主问答——前端新增琥珀色"多专家协作"开关与可折叠专家过程面板，后端端点补齐鉴权、限频、行级隔离上下文传播与伪工具调用防御，新增 MULTI-01 端到端验收（真实 207.3s）；②建立 Agent 端到端评测基准集——12 道多跳/跨域题＋"工具选择正确率＋答案事实组覆盖率"双指标纯函数打分体系，HTTP 评测器产出可复现报告。**

本轮（⑳ 多专家接入＋Agent 评测基准）交付的关键结论：

1. **multi_agent 工作流正式接入主问答**：[src/agent/multi_agent.py] 主管 CoordinatorAgent 以 LLM 输出 JSON 调度计划（非法专家名过滤、异常回退三专家全开），LAW/CASE/PRICE 三类 SpecialistAgent 各自带角色工具子集（法规=知识库/联网；案例=知识库/图谱/PG/联网；价格=PG/图谱/联网）跑最多 3 轮 ReAct，WRITER 综合终稿。端点 POST /api/multi-agent/run 为非流式：等待态由前端文案承载，过程（计划专家、各专家答案/轮数/耗时）在回复的可折叠面板中展示。
2. **接入过程修复 3 个真实缺陷**（详见第 5 章 D19-D21）：①端点调用了 RateLimiter 并不存在的 `acquire` 方法（端点此前从未被前端调用，属潜伏缺陷，一触即 500）；②多专家线程池让多个线程并发进入同一个 contextvars.Context（Python 禁止重入，72s 后必 500），改为逐任务 `base_ctx.copy().run(...)`，RAG 行级隔离 ContextVar 正确传播到工作线程（离线 Barrier 并发测试锁死该回归点）；③专家循环缺少主 ReAct 循环的伪工具调用防御，DeepSeek 风格全角 `｜｜DSML｜｜` 标记直接泄漏进终稿——tool_defense 增加全角变体归一化解析，专家循环支持文本工具调用解析执行（限本专家工具白名单）、非法标记纠偏提示、轮次耗尽后强制一次无工具纯文本生成，写作终稿为空时拼接专家结论兜底。
3. **前端入口与过程可观测**：ChatInput 琥珀色"多专家协作"开关（localStorage 持久化，位于"深度思考"之后）；助手回复带"多专家协作"徽标与琥珀色可折叠面板——标题栏展示主管计划调度的专家 chips，展开后每个专家卡片显示角色、轮数、耗时、答案（max-h 滚动）；多专家消息与会话一并持久化与刷新回显。`npx tsc --noEmit` 0 报错。
4. **MULTI-01 端到端实证（207.3s）**：跨域题（截止时间＋预算＋保证金法规）主管调度 CASE+LAW 两专家，均真实调用 search_bidding_knowledge，终稿 2000 字、去重来源 11 条；独立真实冒烟 185s 的终稿准确给出"2025年12月15日 14:00 / 860万元 / 保证金不得超过估算价 2%"并带 [资料N] 标注，无 DSML 标记泄漏。验收断言含终稿洁净负向断言（不得含 DSML/全角竖线）。
5. **Agent 端到端评测基准建立**：[tests/eval/agent_eval_cases.json] 12 题（单跳/多跳/跨域各 4，ID E2E-01~12），事实全部锚定已入库真实数据（主测试文档 2025-12-15/860万/保证金2%/17.2万计算/公示期3日/逾期拒收、KG 两个真实 Project 节点、大陆-香港对比材料）；[src/agent/eval_scoring.py] 为零依赖纯函数打分器——事实组支持字符串/list(all)/{any}/{all} 嵌套、大小写不敏感，组间等权；工具指标含 tools_required 全命中召回与 tools_any 命中；通过线＝工具对＋事实覆盖≥0.6＋答案非空。[tests/eval/run_agent_eval.py] 逐题打真实 /api/chat（从 exec_log.tool_calls 提取工具），产出 agent_eval_report.json/.md（总体/分类别/逐用例，含 gated 拒答标注）。
6. **评测结果如实记录（两跑）**：题集首跑 10/12——E2E-04（资格预审异议渠道）当轮证据门拒答、E2E-05 经查证为**坏题**（锚定的"空调采购"数据在本环境 PG bidding_procurement 表未部署、KG 亦无供应商节点，直连两库实证），E2E-05 替换为锚定 KG 真实节点（北京交通大学雄安校区项目→采购人/代理机构两跳）后复跑：**11/12 通过，工具选择正确率 100%，事实组覆盖 0.909**；单跳 4/4、跨域 4/4、多跳 3/4。复跑中 E2E-07（大陆/香港跨法域对比）证据门拒答（该题首跑曾 PASS）——工具选择正确但复杂多跳检索稳定性存在波动，作为**已观测缺陷**记录（见第 5/6 章），未改动任何事实标准去凑分。
7. **零回退**：V2.2 及以前 59 项存量防线本轮全量 60/60 中持续有效（CERT-01、PROFILE-03 双密钥链、GATE-01、BID-06 整本、ALERT-01 等全过）；硬闸门纯函数 54 断言全过（意图路由新增目录工具证据 10 条）；本轮相关 pytest 160 项全绿（含 test_intent_routing 14、test_new_tools 102、test_multi_agent 5、test_agent_eval_scoring 15、test_tool_text_parsing 14 及 react_loop/sse）；tsc 0；浏览器实测开关/徽标/面板/事实终稿/来源五项全过且 console 无错误（截图 v23_multi_agent.png）。

---

**V2.2 为验证补测版（无产品代码变更）：在 V2.1 全量 59/59 基线上，完成 R11 自 V1.7 起遗留的"真实 MinIO/S3 连通实测"。以真实 MinIO server（RELEASE.2025-09-07，Windows 单文件、非 Docker）对 S3CertStorage 做端到端实测，13/13 PASS。至此证书对象存储从"Stubber 离线模拟"升级为"真实服务全链路实证"。**

本轮（⑲ MinIO 真连通补测）关键结论：

1. **环境获取绕开受限路径**：本机 Docker Hub 加速器免费节点繁忙、DaoCloud denied、1ms/dockerpull 不可达，且 dl.min.io 官方 Windows 开源二进制已 410 Gone（开源 server 归档）；改从 **GitHub Releases 归档前最后带二进制版本 RELEASE.2025-09-07T16-13-09Z** 直链下载 windows-amd64 单文件（107.9MB），`minio.exe server` 直接启动，/minio/health/live 200、9000 API/9001 控制台监听正常。
2. **S3CertStorage 真实全链路 13/13 PASS**（脚本 tests/acceptance/manual_minio_live.py）：生产工厂 `get_cert_storage()` 在 CERT_STORAGE_TYPE=s3+MinIO 配置下构建为 S3CertStorage 并 auto_bucket 自动建桶；中文名证书 save；对象 key 路径隔离 `certs/{uid}/{token}`；**D18 中文原名 metadata URL 编码在真实服务侧复验可还原**；s3v4 预签名 URL 匿名 GET 200 且字节一致；read 回读一致；cleanup 列举+批量删除孤儿=1；delete 后 404/NoSuchKey→FileNotFoundError 映射正确；收尾清空并删除测试桶（测试数据零残留）。
3. **与自动套件的分工**：tests/test_new_tools.py 的 TestS3CertStorage（7 项 botocore Stubber）继续承担 CI 可重复的离线断言；manual_minio_live.py 为需真实 MinIO 的手动实测（脚本头部含二进制下载地址、启动命令、运行命令），默认不属于自动套件，无 MinIO 环境不阻塞日常验收。
4. **V2.1 质量底座不变**：R17 检测主动弹窗预警 59/59 全绿、tsc 0、硬闸门 44 断言均仍有效；本期未触碰任何产品代码。

---

**V2.1 验收套件共 59 项，全量回归 59 PASS / 0 FAIL / 0 ERROR（通过率 100%，PROFILE_ENC_KEYS 双密钥链环境，验收脚本与后端以同一密钥链启动）。本期落地增强项 R17「检测结果前端主动弹窗预警」：五类检测（合规/资格/废标/响应性/报价）完成后发现不合格或风险项时主动弹窗，无需用户翻阅结果面板。新增 ALERT-01 验收用例。**

本轮（⑱ R17）交付的关键结论：

1. **通用预警弹窗组件**：[frontend/components/AlertModal.tsx] 单一受控组件，双级配色——红色顶条 `level=high`（不合格项/废标风险，"发现不合格项，请及时处理"）、琥珀顶条 `level=medium`（待确认/警告，"检测发现风险项"）；列出不合格条目（最多 5 条，超出折叠为"共 N 项"）、条目截断 90 字防溢出；"查看详情"平滑滚动至对应结果面板锚点（check-results/price-result），"知道了"仅关闭。z-[60] 高于业务弹窗（z-50），遮罩点击与 X 均可关闭。
2. **五类检测全部接入主动预警**（[frontend/app/documents/page.tsx]）：①合规检测——高风险排他条款弹红、中风险弹黄（取 risk_level=高/中，条目含规则号+类别+证据）；②资格检查——NO_MATCH/INFO_MISSING 不满足项弹红（可能被否决）、PARTIAL_MATCH 弹黄；③废标自查——verdict=danger 或 self_check 含 risk 弹红、attention/uncertain 弹黄（关联条款原文）；④响应性检查——负偏离弹红、未响应弹黄；⑤报价计算——anomalies 中 error 级（SUM_MISMATCH/CN_MISMATCH/ROW_ARITHMETIC/OVER_CONTROL_PRICE）弹红、warning 级弹黄。
3. **无异常不打扰**：检测 verdict=pass/safe 或无风险条目时不弹窗，仅渲染原结果面板，避免告警疲劳。
4. **ALERT-01 端到端实证（6.1s）**：报价 error 场景（分项合计 200 vs 投标总价 300）verdict=fail 且 anomalies 含 SUM_MISMATCH（level=error、带 message），构成前端红窗数据契约；大写金额"柒拾肆万元整"与数字 100 不符触发 CN_MISMATCH error；总价一致且无大写时 verdict=pass、无 error 级异常（不弹窗契约）。
5. **浏览器 UI 实测三场景全过**：报价 SUM_MISMATCH+CN_MISMATCH 双错误红色弹窗实际渲染（标题/条目/双按钮齐全，截图 v21_alert_modal.png）、"查看详情"关闭弹窗并滚动至报价计算表面板、总价一致时不弹窗且面板显示"✅ 校验通过"（截图 v21_no_alert_pass.png），console 无错误。
6. **零回退**：V2.0 及以前 58 项存量防线在 V2.1 全量回归中持续有效（PROFILE-03 双密钥链、BID-01~06 标书闭环、CERT-01、硬闸门、RBAC 等全过）；tsc 0 报错；本期仅改前端与验收脚本，后端无改动。
7. **MinIO 真连通实测的环境受限说明**：本期尝试 Docker 拉取 minio/minio（经默认加速器/轩辕/DaoCloud/1ms/dockerpull 多源）均失败（免费节点繁忙/denied/镜像 not found/网络不可达），dl.min.io 官方 Windows 二进制已 410 Gone（开源版归档）；真实 MinIO 连通实测顺延，S3 链路仍由 V1.7 的 7 项 botocore Stubber 离线单测保障，R11 风险条更新见第 6 章。**【V2.2 已闭环：经 GitHub Releases 归档版本 Windows 单文件完成真实 MinIO 端到端实测 13/13，详见 4.5j】**

---

**V2.0 验收套件共 58 项，全量回归 58 PASS / 0 FAIL / 0 ERROR（通过率 100%，PROFILE_ENC_KEYS 双密钥链环境）。本期关闭"智慧问答四类功能"中的后两项：R15 异议投诉咨询、R16 操作智能引导。新增 APPEAL-01、GUIDE-01 两个验收用例。至此四类智慧问答功能全部关闭。**

本轮（⑰ R15/R16）交付的关键结论：

1. **R15 异议投诉咨询**：[src/tools/appeal_catalog.py] 结构化专项知识库覆盖 **11 个主题**——通用（渠道总览/时限速查）、工程招投标异议（资格文件+招标文件/开标/评标结果）、投诉（流程/材料/不予受理 6 情形/处理时限/恶意投诉后果）、政府采购（质疑→投诉财政渠道）。每条含 channel/deadline/materials/steps/legal_basis/notes；检索采用与范本推荐相同的中文分词打分算法，问答侧通过 `consult_appeal` Agent 工具调用。
2. **异议投诉 HTTP 端点**：POST `/api/appeal/consult`（自然语言检索）、GET `/api/appeal/topics`（按 4 类：异议/投诉/通用/政府采购分类）、GET `/api/appeal/topics/{code}`（详情，不存在 404）。
3. **两套法定渠道明确区分**：工程招投标用"异议→投诉"（自然日、行政监督部门），政府采购用"质疑→投诉"（工作日、财政部门），避免用户把 7 个工作日与 10 自然日混淆。法规精确到条款：招标投标法实施条例第 22/44/54/60/61 条、七部委 11 号令第七/十二/二十六条、政府采购法第 52/53/55/56 条、财政部 94 号令第三十七条。
4. **R16 操作智能引导**：[src/tools/guide_catalog.py] **7 个操作流程、27 个阶段**，覆盖投标人（注册认证 3/CA 2/标书制作上传 4/开标解密 3/评标澄清 2）、招标人（项目登记至定标 4）、评标专家（抽取回避至签署报告 5）。每阶段含 purpose/prerequisites/actions/common_errors/tips；识别器按自然语言命中**流程+阶段专属关键词**定位，自动返回上一阶段/下一阶段衔接；仅命中流程级关键词时 stage_locked=False，引导补充描述避免误判。
5. **操作引导 HTTP 端点**：POST `/api/guide/recognize`（识别流程+当前阶段，未识别 404）、GET `/api/guide/workflows`（三类角色流程清单）、GET `/api/guide/workflows/{wid}`（含全部阶段详情）。
6. **APPEAL-01 端到端实证（12.3s）**：评标结果异议首推 APPEAL_RESULT 且 deadline 含"公示期/3 日"；投诉材料命中 COMPLAINT_MATERIALS 且材料≥5 项；投诉流程详情 channel 含"行政监督部门"、deadline 含"10 日"、legal_basis 含"第六十条"、steps 含"异议前置"；政采质疑首推 GOV_CHALLENGE 且 channel="财政"、deadline 含"7+15 个工作日"；列表 4 类 11 主题。
7. **GUIDE-01 端到端实证（16.4s）**：投标文件上传失败定位 GW-BID-UPLOAD/up-3（加密上传阶段）且 stage_locked=True、前后阶段均存在；开标解密定位 dec-2 且内容含"同一把 CA"关键提示；仅说"评标专家"命中 GW-EXPERT 但 stage_locked=False（不锁定阶段）；招标人"发布招标公告"定位 tdr-3；无法识别 404；流程列表三角色 7 流程、专家流程 5 阶段。
8. **离线测试 17 项新增全过**（test_new_tools.py 102 项）：R15 8 项（catalog 要素/大小写/评标结果/材料+政采/招标文件+无匹配/文本渲染/工具 executor/端点）+ R16 9 项（流程完整性/上传/解密注册/招标专家/CA无匹配/列表/文本/工具/端点）。全量 pytest 269 passed（test_intent 3 项为 V1.7 起基线实证的既有失败）；硬闸门 44 断言全过；本期未改前端，tsc 0 报错。
9. V1.9 及以前各版本防线（58 项全量零回退，PROFILE-03 双密钥链 10.8s、AUDIT-01、ANOMALY-01、TEMPLATE-01、CERT-01、硬闸门、RBAC）在 V2.0 全量回归中持续有效。
10. **四类智慧问答功能全部关闭**：①操作智能引导（**R16**）②范本智能推荐（**R14**）③异常预警问答（**R13**，检测 P4-P9 已具备）④异议投诉咨询（**R15**）。

**V1.9 验收套件共 56 项，全量回归 56 PASS / 0 FAIL / 0 ERROR（通过率 100%，PROFILE_ENC_KEYS 双密钥链环境）。本期关闭"智慧问答四类功能"中的前两项：R13 异常预警问答解释层、R14 范本智能推荐。新增 ANOMALY-01、TEMPLATE-01 两个验收用例。**

本轮（⑯ R13/R14）交付的关键结论：

1. **R13 异常预警问答解释层**：[src/tools/anomaly_catalog.py] 结构化异常知识库覆盖 **12 个异常 code**——P7 报价计算 5 项（ROW_ARITHMETIC/SUM_MISMATCH/CN_UNPARSEABLE/CN_MISMATCH/OVER_CONTROL_PRICE）、P9 围串标 3 项（jaccard_text/identical_line_items/metadata_author）、M4 资格/废标/偏离 4 项（QUALIFICATION_FAIL/REJECTION_CLAUSE/DEVIATION_MAJOR）。每条含 level/item/summary/causes(多条)/impact/actions(可执行步骤)/legal_basis(具体法规条款)。问答侧通过新增 `explain_anomaly` Agent 工具（已加入 BASE_TOOL_NAMES 默认工具集）按 code 查表，避免 LLM 自由发挥误导。
2. **异常解释 HTTP 端点**：POST `/api/anomaly/explain`（单条，未知 code 404）、POST `/api/anomaly/explain_batch`（批量，已知 found=true/未知 found=false+entry=null 混合返回），供前端检测结果页"为什么不合格/如何修改"按钮直接消费。
3. **R14 范本智能推荐**：[src/tools/templates_catalog.py] 内置 **11 份范本**（招标文件 4、合同范本 3、业务表单 4），每条含 category/name/project_types/keywords/summary/sections/source_url；自研中文分词（标点拆分 + 词典最大逆向匹配 6→1 字贪心）+ 词命中打分（haystack 命中 1 分，name 命中 0.25 分加权，类别核心词"招标/合同/表单"纳入 keywords 避免名称淹没类别意图）。问答侧通过 `recommend_template` Agent 工具调用。
4. **范本 HTTP 端点**：POST `/api/templates/recommend`（query+category 过滤+top_k）、GET `/api/templates/{tid}`（详情含完整章节，不存在 404）、GET `/api/templates`（三类全量列表）。
5. **ANOMALY-01 端到端实证（8.2s）**：OVER_CONTROL_PRICE 返回 level=error、4 条 actions、含法规依据且 impact 含"废标/否决"；未知 code 404；批量混合 [已知×3+未知×1] 正确标记；jaccard_text 围串标线索 level=high 可解释。
6. **TEMPLATE-01 端到端实证（10.2s）**："工程施工项目招标"首推 TPL-BID-001（score>0）；category="合同范本"过滤后全部为合同类；详情 sections 含"招标公告/投标人须知"；不存在范本 404；列表 3 类 ≥10 份。
7. **离线测试 10 项新增全过**（test_new_tools.py 85 项）：catalog 完整性（≥10 code 且每条四要素齐全）、大小写不敏感查表、文本渲染含【问题说明】【处置建议】【法规依据】、Agent 工具 executor（正常/空 code/未知 code）、推荐匹配排序（工程→招标文件优先）、类别过滤、无匹配空列表、详情/三类枚举、TestClient 端点全链路。全量 pytest 203 passed（仅 test_intent 3 项为 V1.7 起基线实证的既有失败，非本期回归）；硬闸门 44 断言全过；本期未改前端。
8. V1.8 及以前各版本防线（56 项全量零回退，PROFILE-03 双密钥链 10.8s、AUDIT-01、CERT-01、硬闸门、RBAC）在 V1.9 全量回归中持续有效。
9. **四类功能整体进度**：①操作智能引导（未实现）②范本智能推荐（**R14 已关闭**）③异常预警问答（**R13 解释层已关闭**，检测能力 P4-P9 早已具备）④异议投诉咨询（未实现，待 R15）。

**V1.8 验收套件共 54 项，全量回归 54 PASS / 0 FAIL / 0 ERROR（通过率 100%）。本期关闭 V1.7 报告遗留的 R12「操作审计落库表」：敏感操作审计从仅 logger 升级为 audit_logs 表持久化，admin/auditor 可按账号/动作/目标类型分页查询，记录只含字段名与动作，不含任何敏感字段值；新增 AUDIT-01 端到端验收用例（含明文泄露负向断言与 RBAC 断言）。**

本轮（⑮ R12 审计落库）交付的关键结论：

1. **audit_logs 表幂等建表**：BIGSERIAL 主键、user_id→users 外键 ON DELETE SET NULL、action/target_type/target_id、changed_fields JSONB、ip/user_agent/detail、created_at；按 (user_id, created_at DESC) 与 (action, created_at DESC) 建索引，由 postgresql_client 启动时 CREATE TABLE IF NOT EXISTS 创建。
2. **src/tools/audit_log.py 模块**：`record_audit(...)` 写库（参数化绑定，changed_fields 只存字段名清单，action 去空白，所有文本字段限长防超大写入）；PG 未就绪或写库异常时**降级 logger 不抛异常**（审计永不阻断主业务）；`list_audit_logs(...)` 分页查询（user_id/username/action/target_type 过滤、limit≤200 钳制、order 白名单仅 desc/asc 防注入、JSONB 字符串兜底解析、datetime 序列化为 ISO）。
3. **敏感操作接入**：企业资料 upsert 仅在字段真变化时写一条 profile.update 审计（只透传 audit_meta 身份/来源，字段名由 tool 层 diff 后落库；掩码回传保护与加密逻辑不变）；证书 OCR 上传写 cert.ocr 审计（只记 token/格式/识别来源/字节数，不记 OCR 文本内容）；密钥轮换 CLI 实际执行后写一条 system 的 key.rotate 审计（仅统计数字）。
4. **GET /api/audit/logs 端点 RBAC**：`require_roles(admin, auditor, allow_anonymous=False)`，匿名 401、投标人 403；返回 {items, total, limit, offset}。
5. **AUDIT-01 端到端实证**：投标人两次 PUT（含银行账号/电话/法人变更）→ admin 按 user_id+action 查到 ≥2 条审计，changed_fields 含 contact_phone/bank_account/legal_person；**整条 items JSON 不含 "13700008888"/"6222000088889999"/"赵六" 明文**；bidder 403、匿名 401；PG 直连实证落库；不存在的 action 过滤为空。
6. **离线测试 8 项新增全过**（test_new_tools.py 75 项）：INSERT 参数严格断言且不含值、PG 未就绪/异常降级、字段名清洗去重限长与文本截断、查询过滤/分页/排序白名单与 JSONB 解析、PG 不可用返回空、upsert 有变更写审计、无变更不写审计。全量 pytest 258 passed（仅 test_intent 3 项为与 V1.7 基线实证一致的既有失败，非本期回归）；硬闸门 44 断言全过；前端 tsc 0 报错（本期未改前端）。
7. V1.7 及以前各版本防线（54 项全量零回退，CERT-01 仍 33.4s 全过、PROFILE-03 双密钥链、硬闸门、RBAC）在 V1.8 全量回归中持续有效。

**V1.7 验收套件共 53 项，全量回归 53 PASS / 0 FAIL / 0 ERROR（通过率 100%）。

本轮（⑭ R11 S3 接入 + R10 密钥轮换）交付的关键结论：

1. **S3CertStorage 完整实现（boto3 懒加载）**：key=`{prefix}{user_id}/{uuidhex+ext}` 保持用户目录隔离；save=put_object（ContentType 按扩展名、original_name 元数据）、read=get_object（404/NoSuchKey→FileNotFoundError）、delete=delete_object、cleanup=list_objects_v2 分页器列举＋delete_objects 批量 1000/批、presigned_url 生成 s3v4 限时直链。MinIO/自建网关通过 `endpoint_url`＋path-style addressing＋s3v4 签名适配；`auto_bucket=true` 时 head_bucket 404 自动 create_bucket。仅 `CERT_STORAGE_TYPE=s3` 时 import boto3，默认 local 零影响。
2. **中文原名元数据缺陷修复（D18）**：S3 用户自定义元数据只接受 ASCII，中文文件名直传会被 botocore ParamValidationError 拒绝（真实生产缺陷，本期单测先暴露）。改为 `urllib.parse.quote` URL 编码后存入 `x-amz-meta-original_name`，Stubber 严格断言。
3. **端点存储后端无关化**：OCR 上传端点保存后直接对**上传字节** `ocr_cert_bytes`（图片内存解码、PDF 写系统临时文件提取后即删），不再依赖本地路径；证书预览端点改为"预签名 URL 307 重定向优先，失败/本地存储时由应用鉴权代理读取字节内联返回（Content-Disposition: inline）"，两种存储后端访问语义一致。
4. **多版本密钥链（MultiFernet）**：`PROFILE_ENC_KEYS` 逗号分隔多个 Fernet key，**第一个为当前加密密钥**，其余历史密钥仅用于解密旧密文；未配置时回退 AUTH_SECRET 经 PBKDF2HMAC（salt=bid-profile-v1，100k iter）派生的单一密钥，V1.6 存量密文零迁移。新增 `key_index/needs_rotation/rotate_value` 与 `rotate_all_profiles(dry_run)`（全表扫描逐字段重加密，返回 scanned/rotated_users/rotated_fields/skipped 统计）；CLI：`gen-key` 生成新密钥、`rotate [--dry-run]` 批量重加密、`status` 查看密钥链长度。
5. **PROFILE-03 端到端实证（双密钥链环境）**：新写入档案确认由当前密钥 K1 加密（历史密钥 K2 解不开）；用 K2 加密的"轮换前历史密文"直写 PG 后，服务端 GET 仍能经密钥链解密并正确掩码（HTTP 实证，掩码 `************7777`）；dry-run 扫描 34 行不写库；rotate_value 重加密后 key_index=0、GET 掩码不变。轮换流程：gen-key → PROFILE_ENC_KEYS 新key置首重启（旧密文可读不中断业务）→ rotate 批量收尾（用户下次 PUT 亦惰性重加密）。
6. **离线测试 12 项新增全过**：TestFieldCryptoRotation 5 项（历史密文可解/needs_rotation+rotate_value/加密用当前密钥/明文 passthrough/非法密钥回退派生）＋TestS3CertStorage 7 项（botocore Stubber：put_object 参数严格断言含编码元数据、get 字节一致与 404、delete、cleanup 列举+批量删、非法 token/越权扩展名不触发 API 调用、预签名 URL 含 X-Amz-Signature、按 settings 工厂构建 s3 存储）。test_new_tools.py 达 67 项；全量 pytest 250 passed（仅 test_intent 3 项失败，经 git stash 在基线 `58a4399` 上复跑确认为**与本期无关的既有失败**）；硬闸门 44 断言全过；前端 tsc 0 报错（本期未改前端）。
7. V1.6 及以前各版本防线（53 项全量零回退，含 CERT-01 证书链路在双密钥链环境下仍全过、硬闸门 44 断言、RBAC 隔离、整本合稿）在 V1.7 全量回归中持续有效。

**V1.6 验收套件共 52 项，全量回归 52 PASS / 0 FAIL / 0 ERROR（通过率 100%）。本期针对 V1.5 报告中 R9/R10/R11 三项风险做收尾：对照表对 LLM 返回做行结构校验（丢弃空要求、修正非法 status/category、material 启发式校正）并加 1 小时内存 TTL 缓存（相同招标+投标稿复用结果，整本反复生成跳过 LLM）；企业资料库 bank_account/contact_phone/contact_email/legal_person 四个敏感字段应用层 Fernet 加密入库（密钥由 auth_secret 派生），GET 端点掩码展示（银行账号保留后 4 位、电话前 3 后 4、邮箱首字母+***、法人姓+**），PUT 时掩码回传自动保留旧明文，upsert 记录字段级审计日志（不含值）；证书原件存储抽象为 `CertStorage` 基类 + `LocalCertStorage`（默认）+ `S3CertStorage`（接口占位，待接 boto3），OCR 前加灰度化+小图放大预处理提升小字识别率。**

本轮（⑬ R9/R10/R11 收尾）交付的关键结论：

1. **R9 对照表结构化校验**：`_validate_row` 丢弃 requirement 为空的行、status 非法回退 NO_RESPONSE、category 不在白名单（资格/商务/技术/交付/售后/其他）归"其他"、material=true 但要求文本不含实质性关键词（★/必须/废标/否决/不得/应当等）时强制降为 false，避免 LLM 乱标导致硬失败误报。MATRIX-02 之外 BID-05/BID-06 仍全过（18~20 条要求、verdict 判定正确）。
2. **R9 内存 TTL 缓存**：`_cache_key(db_id + tender_blob[:9000] + bid_blob[:14000])` SHA256 截断 32 位，缓存 64 条上限 LRU 淘汰、1 小时 TTL；`build_requirement_matrix` 默认 `use_cache=True`，命中时返回 `cached=True` 跳过 LLM。MATRIX-02 实测：首次 cached=False、相同输入第二次 cached=True、summary.total 与 verdict 一致；整本反复生成时对照表阶段从 ~5s 降到 <100ms。
3. **R10 敏感字段应用层加密**：`field_crypto.py` 用 PBKDF2HMAC(auth_secret, salt=bid-profile-v1, 100k iter) 派生 Fernet 密钥；`encrypt_sensitive` 在 upsert 入库前加密 bank_account/contact_phone/contact_email/legal_person，`decrypt_sensitive` 在 get_profile 出库后解密为明文（业务侧标书生成/资格比对用明文不受影响）。PROFILE-02 直连 PG 确认 bank_account 以 `gAAAAA` 开头、不含明文片段 `6222`。
4. **R10 掩码展示 + 掩码回传保护**：GET /api/profile 调用 `mask_profile` 返回掩码（银行 `************7890`、电话 `138****5678`、邮箱 `z***@example.com`、法人 `张**`），非敏感字段（公司名等）明文不变；用户在 /profile 页未改银行账号直接保存时，前端提交掩码值，upsert 检测到含 `*` 且旧值非空则保留旧明文，杜绝覆盖。PROFILE-02 验证：掩码 PUT 后 PG 解密明文仍为 `6222021234567890`。
5. **R10 操作审计**：upsert_profile 比对新旧明文，记录 `logger.info("企业资料更新审计 user_id=%s changed_fields=%s")`，只记字段名不含值，满足审计留痕要求且不泄漏敏感信息。
6. **R11 存储可插拔抽象**：`CertStorage(ABC)` 定义 save/path/delete/cleanup 契约；`LocalCertStorage` 搬入原 uploads/certs 逻辑；`S3CertStorage` 接口占位（save/path/delete/cleanup 均 NotImplementedError，待接 boto3 后实现）；`get_cert_storage()` 按 `settings.cert_storage_type`（默认 local，可选 s3）工厂返回。模块级 save_cert_file/cert_file_path/delete_cert_file/cleanup_orphan_certs 委托给默认实例，server.py 调用零改动，CERT-01 全过（本地存储行为不变）。
7. **R11 OCR 图像预处理**：`_preprocess_image` 对宽度 <1200px 的小图放大 1.5 倍（INTER_CUBIC）、BGR→灰度→转回 3 通道，提升证书扫描件小字识别率；不做强二值化以保留彩色印章/水印信息。冒烟实测建筑业企业资质证书/一级/2029-12-31 仍正确识别。
8. V1.5 各项防线（52 项全量零回退，含硬闸门 44 断言、RBAC 隔离、整本合稿、证书 OCR、49→50→52 用例仅新增 PROFILE-02/MATRIX-02）在 V1.6 全量回归中持续有效；PROFILE-01 断言同步适配掩码（legal_person 由"李四"改为"李*"）。

**V1.5 验收套件共 50 项，全量回归 50 PASS / 0 FAIL / 0 ERROR（通过率 100%）。本期在 V1.4 自动成册基础上补齐企业资料库最后一块：资质证书附件的上传、OCR 结构化与私有原件预览。**

本轮（⑫）交付的关键结论：

1. **零新依赖复用 OCR**：直接复用 `document_parser` 的 RapidOCR 单例（onnxruntime 懒加载），图片走 `cv2.imdecode`＋RapidOCR，PDF 走 `extract_pages_pdf`（文本层/扫描页自动处理，限前 2 页）；不引入 pytesseract/paddleocr 等重依赖，规避环境/版本冲突风险。
2. **LLM 抽取 + 正则回退双保险**：`extract_cert_fields` 优先调 LLM（temperature=0）输出 JSON 四字段；LLM 异常或返回空时走 `fallback_cert_fields` 正则（等级/编号/有效期/证照名四类模式，名称中的等级词自动剥离）。CERT-01 实测 LLM 路径一次性抽对"建筑业企业资质证书/一级/BZ-2025-777888/2029-12-31"，source=llm、warnings=[]。
3. **账号私有原件 + 越权隔离**：`save_cert_file` 生成 uuidhex 文件名（不暴露真实名称）；`cert_file_path` 以正则白名单（32 位 hex＋白名单扩展名）+ `resolve` 后父目录强校验双保险，跨用户目录访问、`../` 穿越、非证书扩展名一律 FileNotFoundError→端点 404；原件仅本人可下载（CERT-01：本人 200、跨用户 404、穿越 404）。
4. **整表保存 + 孤儿清理闭环**：OCR 不直接写库，返回的 cert 对象由前端展示/校正后随 `PUT /api/profile` 整表提交；PUT 端点比对新旧档案中的 file_token，调 `cleanup_orphan_certs` 删除被移除证书的原件（CERT-01：去掉证书再保存后原件立即 404）。
5. **前端交互闭环**：证书卡片新增"上传证书自动识别"按钮（jpg/png/webp/bmp/pdf），OCR 中按钮 loading、完成后四字段自动填充、左下显示 48×56 原件缩略图（图片直接预览、PDF 显示红图标可点击打开）、"原件已上传"提示与可折叠 OCR 原文；刷新页面证书与缩略图正常回显。浏览器实测：建筑业企业资质证书/特级/JZ-2026-666999/2030-08-08 四字段全对。
6. **数据模型平滑扩展**：`CertItem` 新增 `file_token/file_name/ocr_text`；`company_profile._norm_items` 对白名单键过滤，历史无附件的证书项兼容不变；标书占位符回填/资格比对/对照矩阵均复用证书四字段，附件元数据不参与生成逻辑。
7. V1.4 各项防线（50 项全量零回退，含硬闸门 44 断言、RBAC 隔离、整本合稿、49→50 用例仅新增 CERT-01）在 V1.5 全量回归中持续有效。

**V1.4 验收套件共 49 项，全量回归 49 PASS / 0 FAIL / 0 ERROR（通过率 100%）。本期在 V1.3 单章生成基础上打通"Cursor 式自动成册"最后一公里：企业资料库按账号 1:1 持久化，标书生成时 22 类占位符自动回填（或由 prompt 直接引导 LLM 使用真实信息），整本一键流式合稿（封面/目录/5 章/对照表附录/待补清单），并自动产出逐条招标要求响应对照表（🟢满足/🔵正偏离/🟡负偏离/🔴不满足/🔴未响应，★实质性红项构成废标级硬失败清单）。**

V1.4 轮（⑪ 自动成册）交付的关键结论（持续有效）：

1. **企业资料库 1:1 闭环**：company_profiles 表随启动幂等建表（user_id 主键外键级联删除），12 个文本字段＋资质证书/同类业绩两组动态 JSONB；GET/PUT /api/profile 强制登录（匿名 401）；PROFILE-01 全过。资料同时注入 Agent 工具链（对话中可查/可用）。
2. **占位符双路径回填**：①prompt 资料块引导 LLM 直接写真实信息（BID-04 实测：正文直接出现公司全称/法人/注册资本/证书编号 UI-2025-888，无 [公司全称] 残留）；②流式后处理 `fill_placeholders_stream` 对 LLM 仍输出的 [占位符] 做跨 chunk 精确替换（22 别名映射，[资质证书编号] 自动展开全部证书），未填项分"企业资料缺失"（引导补档案）与"业务测算类"（黄色提示手工确认）两类清单随文末下发。
3. **逐条响应对照表确定性可用**：空投标稿对照 18 条要求全部判红、verdict=fail、附录含 🔴（BID-05）；无原文/资质要求的手填空白招标 400；LLM 不可用时回退关键词包含匹配。浏览器实测 doc#7：18 条要求中识别出 **4 项实质性条款不合格**（业绩个数/交付工期/保证金/最高限价），红框逐条列出并在顶部提示"导出前须整改"。
4. **整本一键合稿 SSE**：meta → section_start/token/section_done×N → matrix_done → done 事件序列严格（BID-06 计数全对），done 一次性下发整本 Markdown（封面"投 标 文 件"、目录、各章、对照表附录、待补清单）＋fill_info＋matrix_summary＋hard_failures＋verdict；前端章节级进度条、结构化表格（红/黄行配色、★实质性列）、整本 Markdown 折叠预览、复制与整本 Word 导出齐备。
5. **docx 标红落地**：导出 Word 中 🔴 行整行红色加粗、🟡 行琥珀色，确保纸质/离线审阅同样能看到不合格项。
6. V1.3 各项防线（硬闸门 44 断言本轮再跑全过、RBAC 三层隔离、状态机、引用页码）在 49 项全量回归中零回退。

**V1.3 验收套件共 45 项，全量回归 45 PASS / 0 FAIL / 0 ERROR（通过率 100%）。V1.2 唯一波动项 M2-01 已由"无引用不生成"硬闸门从机制上根治（35.4s 稳定通过）。**

V1.3 轮（⑨⑩）交付的关键结论（持续有效）：

1. **⑨"无引用不生成"硬闸门形成确定性防线**：纯函数三态判定；RAG 低分噪声不算证据；问题特征词覆盖判据防止通用法规 FAQ 为虚构项目"背书"。离线 44 断言 + GATE-01 全过。
2. **⑩标书生成闭环贯通**：对话内 Agent 工具 → 单章同步/SSE 流式（5 章）→ 前端"一键生成标书"入口 → docx 直出。BID-01/02/03 全过。
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
| **⑪ Cursor 式自动成册** | 企业资料库 1:1（12 文本字段＋证书/业绩 JSONB，匿名 401）、单章生成按资料回填（fill_info/profile_used）、空稿对照表全红 verdict=fail＋无原文 400、整本 SSE（meta/章节/matrix_done/done 序列＋封面目录＋fill_info） | PROFILE-01、BID-04 ~ BID-06 |
| **⑫ 证书附件 OCR** | 图片/PDF 上传→RapidOCR→LLM 四字段抽取（正则回退）、私有原件存储（uuidhex+目录隔离）、鉴权预览（跨用户/穿越/非法扩展名 404）、随整表保存、孤儿清理 | CERT-01 |
| **⑬ R9/R10/R11 收尾** | 对照表行结构校验（丢弃空要求/修正非法状态类别/material 启发式）＋内存 TTL 缓存（db_id+bid_hash→matrix，cached=True）；敏感字段 Fernet 加密入库＋GET 掩码展示＋掩码回传保护＋操作审计；证书存储抽象（Local/S3 可插拔）＋OCR 灰度化小图放大预处理 | MATRIX-02、PROFILE-02 |
| **⑭ V1.7 S3 接入+密钥轮换** | 证书原件 S3/MinIO 实际接入（boto3 put/get/delete/list 批量清理/s3v4 预签名/自动建桶/中文原名 URL 编码）、OCR 字节流与预览端点存储后端无关；敏感字段 MultiFernet 多版本密钥链（第一把=当前密钥）＋历史密钥解密＋dry-run/批量重加密＋gen-key CLI | PROFILE-03（S3 链路由 7 项 Stubber 离线单测覆盖） |
| **⑮ V1.8 审计落库** | audit_logs 表持久化（字段名清单 JSONB、user_id 外键、双索引）、record_audit/list_audit_logs（降级不阻断/参数化/限长/排序白名单）、企业资料/证书 OCR/密钥轮换三类敏感操作接入、GET /api/audit/logs 端点（admin/auditor 403/401） | AUDIT-01 |
| **⑯ V1.9 异常解释+范本推荐** | 12 code 结构化异常知识库（原因/影响/处置/法规）+ explain_anomaly Agent 工具 + /api/anomaly/explain(_batch)；11 份范本库+中文分词推荐 + recommend_template 工具 + /api/templates 三件套 | ANOMALY-01、TEMPLATE-01 |
| **⑰ V2.0 异议投诉+操作引导** | 11 主题异议投诉专项库（渠道/时限/材料/流程/法规，工程招投标与政采两套区分）+ consult_appeal 工具 + /api/appeal 三件套；7 流程 27 阶段操作引导（投标人/招标人/评标专家，含阶段识别+前后衔接）+ guide_operation 工具 + /api/guide 三件套 | APPEAL-01、GUIDE-01 |
| **⑱ V2.1 检测主动预警** | 五类检测（合规高/中风险、资格不满足/部分满足、废标 risk/uncertain、响应性负偏离/未响应、报价 error/warning 异常码）完成后前端主动弹红/黄预警，AlertModal 通用组件+锚点定位详情，无异常不弹窗 | ALERT-01 |
| **⑳ V2.3 多专家协作接入＋Agent 评测基准** | multi_agent（主管 LLM 拆解→LAW/CASE/PRICE 专家并行 ReAct→WRITER 综合）接入主问答：琥珀色开关+专家过程可折叠面板，端点鉴权/限频/行级隔离 ContextVar 传播/伪 DSML 工具调用防御；Agent 端到端基准 12 题（单跳/多跳/跨域），工具选择+事实组双指标纯函数打分器+HTTP 评测器 | MULTI-01（评测见 4.5k） |
| **㉑ V2.3 三业务线显式意图路由** | 招投标/企业/法规/通用 规则评分分类器（强弱信号词＋分差阈值＋零信号历史继承），显著单域才裁剪 active_tools（法规 3/企业 7），跨域弱信号保守回退全集；RAG 底座恒保留；INTENT_ROUTING_ENABLED 开关；并修复 D25（R13-R16 权威目录工具纳入证据门证据集合） | test_intent_routing 14 项＋硬闸门 54 断言（见 4.5l） |
| Workflow | 预置清单、合规 DAG、评标辅助 DAG | WF-01 ~ WF-03 |
| **离线专项** | 检索质量评测（17 例 5 指标）、页码切分、RAG 召回行级隔离、**硬闸门纯函数 44 断言**、**占位符回填/跨 chunk 流式/prompt 注入离线自测、pytest（test_new_tools.py 67 项：含证书 OCR 正则/LLM/存储隔离、对照表校验+缓存、字段加密+掩码、存储抽象、多密钥轮换、S3 Stubber 全链路；全量 250 passed，test_intent 3 项为基线既有失败）** | tests/eval/ 四个脚本＋tests/test_new_tools.py |
| **① OCR/Excel** | 扫描件 OCR、xlsx 提取（离线手工实测，见 4.4） | 离线实测 |
| **浏览器 UI** | 注册角色选择、投标人入口隐藏、上传元数据表、状态机面板、引用文件名/页码、标书生成器弹窗、**企业资料库页（表单/证书增删/完整度）、整本合稿 Tab（章节进度/对照表红行/硬失败红框/整本预览）、单章回填后无占位符** | 15 张截图（7.2） |

### 2.2 范围外说明（截至 V2.3 仍未覆盖）

- **智慧问答四类功能已全部实现**（①R16 操作引导 ②R14 范本推荐 ③R13 异常解释 ④R15 异议投诉），均为内置静态结构化知识库 + Agent 工具查表模式，规避 LLM 编造；**V2.1 落地 R17 检测结果前端主动弹窗预警**（五类检测完成即弹窗，见 4.5i）；**V2.3 将原孤立的 multi_agent 多专家协作原型正式接入主问答**（前端开关+专家过程面板+MULTI-01，见 4.5k），并建立 Agent 端到端评测基准（12 题双指标）；后续增强项：范本库与操作流程库接入运营后台动态维护、异常 code 与操作 stage 随业务扩展持续补录；**多专家调度计划目前为一次性 LLM 拆解（不支持中途追加专家/人机协同修正计划），且 PRICE 专家依赖的 PG bidding_procurement 历史中标表在本环境未部署（价格专家会如实报告数据缺口而非编造，见 4.5k 截图）**；
- **Agent 评测基准当前为 12 题小规模基准、事实判定为关键词组字符串匹配（非 LLM 评审）**：能稳定区分"工具选错"与"答非所问"，但对同义改写（如"850 万元/8,500,000 元"）需在题面显式列举候选锚点；后续扩充至 50+ 题、增加多次运行的稳定性（flaky）统计与语义级事实判定；
- 压力/并发性能、安全渗透（token 篡改/过期/水平越权穷举扫描）；
- 移动端 H5/公众号、CA/USBKey 认证、敏感词过滤、平台对接（属后续二期，已在需求符合性评估中记录）；
- OCR/Excel 未纳入 HTTP 自动验收（以离线实测＋META-01 上传链路间接覆盖 PDF 侧，证书 OCR 由 CERT-01 覆盖）；
- 证书原件已支持 Local/S3 双后端（**V1.7 已接入 boto3 实际 S3/MinIO**，配置见 .env.example：CERT_STORAGE_TYPE/CERT_S3_*），S3 链路有双重保障——CI 侧 7 项 botocore Stubber 离线单测＋**V2.2 已补真实 MinIO server 端到端连通实测 13/13 PASS**（自动建桶/中文名 metadata D18/s3v4 预签名匿名 GET/read/cleanup 批删/404 映射/测试桶零残留，脚本 manual_minio_live.py，复现步骤见 4.5j/7.3；环境获取经 GitHub Releases 归档版本单文件，绕开 Docker 加速器与 dl.min.io 410 限制）；商用 AWS S3 尚未实测（MinIO 同为 S3v4+path-style 协议，风险低）；OCR 已加灰度+小图放大预处理，复杂版式/手写/印章遮挡场景仍需用户手工核对（系统提供可折叠 OCR 原文对照）；
- 对照表已加行结构校验+缓存，仍为 LLM 抽取判定（带关键词回退），非确定性场景需人工复核；投标报价测算类参数仍需业务人员手工确认（系统显式黄色提示而非杜撰）；
- 企业资料敏感字段已应用层加密+掩码，**V1.7 已支持多密钥链无停机轮换与批量重加密（PROFILE-03 全过）**；**V1.8 已支持敏感操作审计落库表（AUDIT-01 全过，admin/auditor 可按字段名查询且不含明文）**；数据库透明加密（TDE）仍待下一期。

---

## 3. 测试环境

### 3.1 软件环境

| 组件 | 版本 / 配置 |
|---|---|
| 操作系统 | Windows（DESKTOP-26K8KR8） |
| Python | 3.12.10；FastAPI 0.141.1；SQLAlchemy 2.0.52 |
| 鉴权 | python-jose（JWT, HS256）＋ bcrypt rounds=12；4 角色 RBAC |
| PostgreSQL | 本地 localhost:5432，库名 chatbot |
| Qdrant | 本地实例，集合 bid_qa_v2，V2.3 回归开始时 **551 点**（验收上传后 562 点，含权限回填；V2.1 轮为 374 点） |
| 嵌入/精排 | BGE-M3（dense+sparse）＋ reranker-v2-m3 |
| OCR/文档 | rapidocr-onnxruntime 1.4.4（懒加载）、pymupdf、openpyxl |
| 对象存储 | boto3 1.43（仅 CERT_STORAGE_TYPE=s3 时懒加载，兼容 AWS S3 / MinIO，path-style+s3v4） |
| 前后端 | Next.js localhost:3000；uvicorn localhost:8001（V1.7 起验收以 PROFILE_ENC_KEYS=K1,K2 双密钥链启动；V2.1 起验收脚本与后端必须同密钥链，否则直连 PG 密文断言 PROFILE-02/03 失败） |

### 3.2 测试数据

- 主测试文档 db_id=6 `test_bid.txt`（智慧园区项目，预算 860 万，截止 2025-12-15 14:00，public）；
- 每轮动态生成时间戳账号（acpt_*）与上传文档（V1.2 轮 db_id 18~22；V1.3 轮至 db_id 47），internal 隔离用文档自带 PKG-A 等标记；
- 离线测试使用隔离 ID 段（db_id 999001/999002/999003，虚构 uid 880001/880002），结束即清理。

---

## 4. 测试用例执行情况

### 4.1 总览（V2.3 全量回归，2026-09-20 03:43 起，PROFILE_ENC_KEYS 双密钥链环境，脚本与后端同密钥链）

- **共 60 项：PASS 60，FAIL 0，ERROR 0，通过率 100.0%**；
- 原始输出：全量执行日志 run_log_v23.txt（仓库未纳管，留存本地）；结构化结果：`tests/acceptance/evidence.json`。

| 测试组 | 通过/总数 |
|---|---|
| 环境 | 3/3 |
| MVP1 文档库 | 3/3 |
| MVP2 检索（含⑨硬闸门 GATE-01） | 2/2 |
| MVP3 条款提取 | 2/2 |
| MVP4 条款检查 | 3/3 |
| P4/P5/P6 | 3/3 |
| P7 报价计算 | 3/3 |
| P8 投标解析器 | 1/1 |
| P9 围串标线索 | 4/4 |
| Auth 权限 | 4/4 |
| MVP5 复核留痕 | 2/2 |
| **⑦ RBAC 权限隔离** | **7/7** |
| **⑥ 评审状态机** | **2/2** |
| Workflow 编排 | 3/3 |
| **⑩ 标书生成闭环** | **3/3** |
| **⑪ V1.4 企业资料库/回填/对照表/整本** | **4/4**（PROFILE-01、BID-04/05/06） |
| **⑫ V1.5 证书附件 OCR** | **1/1**（CERT-01） |
| **⑬ V1.6 加密脱敏＋对照表缓存** | **2/2**（PROFILE-02、MATRIX-02） |
| **⑭ V1.7 密钥轮换** | **1/1**（PROFILE-03） |
| **⑮ V1.8 审计落库** | **1/1**（AUDIT-01） |
| **⑯ V1.9 异常解释+范本推荐** | **2/2**（ANOMALY-01、TEMPLATE-01） |
| **⑰ V2.0 异议投诉+操作引导** | **2/2**（APPEAL-01、GUIDE-01） |
| **⑱ V2.1 检测主动预警** | **1/1**（ALERT-01） |
| **⑳ V2.3 多专家协作接入** | **1/1**（MULTI-01，207.3s 真实主管拆解+双专家并行+写作综合） |
| **合计** | **60/60** |

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
| BID-03 | 单章生成行级权限 | PASS | 54.1s | doc=47（internal）：投标人 403、匿名 403、owner 200 且生成 794 字（V1.3 观测，V1.4 回归仍 PASS） |
| PROFILE-01 | 企业资料库 1:1：空档案→PUT→GET 回显；匿名 401 | PASS | 12.6s | 华信闭环测试有限公司72753；certs=1/projects=1、完整度 5/12；证书编号 HX-2025-001 原样回显；匿名 GET=401 |
| BID-04 | 单章生成按企业资料自动回填（fill_info） | PASS | 52.7s | 技术方案 1226 字直接引用公司全称/资料（profile_used=true，无 [公司全称] 残留）；占位符后处理路径另由 pytest 离线断言覆盖 |
| BID-05 | 空投标稿对照表 verdict=fail/red>0/含🔴；无原文 400 | PASS | 9.9s | 18 条要求全红（18/18）、verdict=fail、附录含 🔴、rows 与 summary.total 一致；手填空白 tender（无原文无资质要求）=400 |
| BID-06 | 整本 SSE：封面目录＋fill_info＋对照表 | PASS | 88.8s | 事件计数 meta1/start2/done2/matrix_done1/done1/error0；整本 4374 字含"投 标 文 件""目 录"与回填公司名；对照 18 条、verdict=fail |
| CERT-01 | 证书图片上传→OCR 结构化→私有预览鉴权→保存→孤儿清理 | PASS | 31.0s | pymupdf 生成中文证书 PNG（simhei 字体）；匿名上传 401；登录上传 OCR 成功（source=llm、warnings=[]），识别：名称=建筑业企业资质证书、等级=一级、编号=BZ-2025-777888、有效期=2029-12-31；本人预览 200 image/png 字节一致、跨用户 404、`../etc/passwd` 穿越 404、.exe 上传 400；PUT 整表保存后 GET 回显含 file_token/ocr_text；去掉证书再 PUT 后原件 404（孤儿清理生效） |
| PROFILE-02 | 敏感字段 Fernet 加密入库＋GET 掩码＋掩码回传保护 | PASS | ~2s | PUT bank_account=6222021234567890/phone=13812345678/email=zhangsan@example.com/legal=张三丰；GET 掩码：银行 `************7890`、电话 `138****5678`、邮箱 `z***@example.com`、法人 `张**`，公司名明文不变；直连 PG 确认 bank_account 以 `gAAAAA` 开头、不含明文 `6222`；提交掩码值 PUT 后 PG 解密明文仍为 `6222021234567890`（掩码回传保护生效） |
| MATRIX-02 | 对照表缓存：相同输入二次命中 cached=True | PASS | 30s(首)+<1s(次) | 首次 `cached=False`、17 条要求 verdict=fail；相同 db_id+markdown 第二次 `cached=True`、summary.total 与 verdict 与首次一致、不调 LLM |
| **PROFILE-03** | **多密钥链：历史密钥密文服务端可解＋新写入当前密钥＋重加密闭环** | **PASS** | **10.7s** | 后端以 `PROFILE_ENC_KEYS=K1,K2` 双密钥链启动；新 PUT 档案密文经 K1 解出 `6222000011112222`、K2 解不开（InvalidToken）；用 K2 直写 PG 模拟轮换前历史密文后 key_index=1/needs_rotation=True，GET 掩码仍正确 `************7777`（HTTP 实证历史密钥解密）；dry-run 扫描 34 行不写库；rotate_value 重加密后 key_index=0、K1 解出原文、GET 掩码不变 |
| **AUDIT-01** | **敏感操作审计落库：资料变更→admin 按字段名可查（不含值）→RBAC 401/403** | **PASS** | **19.1s** | 投标人两次 PUT（含 bank_account/contact_phone/legal_person 变更）→ admin 按 user_id+action 查到 ≥2 条审计，changed_fields 含 contact_phone/bank_account/legal_person；**整条 items JSON 不含 "13700008888"/"6222000088889999"/"赵六" 明文**；bidder 403、匿名 401；PG 直连 changed_fields 含 contact_phone；不存在的 action 过滤为空 |

| **ANOMALY-01** | **异常预警解释层：按 code 返回原因/影响/处置/法规依据＋批量解释** | **PASS** | **8.2s** | OVER_CONTROL_PRICE 返回 level=error、actions 4 条、legal_basis 非空且 impact 含"废标/否决"；未知 code NOPE_XYZ 返回 404；批量 [SUM_MISMATCH/CN_MISMATCH/QUALIFICATION_FAIL/ZZZ] 前 3 found=true 且含 causes/actions、末项 found=false/entry=null；jaccard_text 围串标线索 level=high 可解释 |
| **TEMPLATE-01** | **范本推荐：按项目类型匹配招标/合同/表单范本＋详情/列表** | **PASS** | **10.2s** | "工程施工项目招标"首推 TPL-BID-001（score>0）；category="合同范本"过滤后全部合同类；详情 sections 含"招标公告/投标人须知"；不存在范本 404；列表 categories 三类、items ≥10 份 |
| **APPEAL-01** | **异议投诉咨询：渠道/时限/材料/流程/法规检索＋政采区分** | **PASS** | **12.3s** | 评标结果异议首推 APPEAL_RESULT（公示期+3 日）；投诉材料命中 COMPLAINT_MATERIALS 且材料≥5；投诉流程详情含"行政监督部门""10 日""第六十条""异议前置"；政采质疑首推 GOV_CHALLENGE 走财政渠道+7/15 工作日；列表 4 类 11 主题 |
| **GUIDE-01** | **操作引导：识别当前操作阶段并给出针对性步骤＋三类角色流程** | **PASS** | **16.4s** | 上传失败定位 GW-BID-UPLOAD/up-3（stage_locked=True，前后阶段均存在）；开标解密 dec-2 含"同一把 CA"；仅说"评标专家"命中流程但不锁定阶段；招标人发布公告 tdr-3；无法识别 404；列表三角色 7 流程、专家流程 5 阶段 |
| **ALERT-01** | **检测预警弹窗数据契约：error 级 anomalies 驱动前端红弹窗，无异常不弹** | **PASS** | **6.1s** | 分项合计 200 vs 投标总价 300 → verdict=fail、anomalies 含 SUM_MISMATCH（level=error+message，前端红窗依据）；大写"柒拾肆万元整"与数字 100 → CN_MISMATCH error；总价一致且无大写 → verdict=pass 且无 error（不弹窗依据） |
| **MULTI-01** | **多 Agent 工作流接入主问答：主管拆解→专家并行 ReAct→写作综合，返回计划/专家结果/终稿** | **PASS** | **207.3s** | 跨域题主管调度 ['CASE','LAW']（⊆合法专家集）；expert_results 数==specialists_count==2，各专家 role 合法、elapsed_ms 为 int，两专家均真实调用 search_bidding_knowledge；终稿 2000 字（>20 且不含 DSML/全角竖线标记）；跨专家去重来源 11 条；total_elapsed_ms=207324ms |

其余存量用例（ENV/M1/M3/M4/P4-P9/AUTH/M5/WF/RBAC/META/STAGE/GATE/BID-01~06/PROFILE-01/02/03/CERT-01/MATRIX-02/AUDIT-01/ANOMALY-01/TEMPLATE-01/APPEAL-01/GUIDE-01/ALERT-01）V2.3 轮全部 PASS（共 59/59 无回退，PROFILE-03 双密钥链、CERT-01、BID-06 整本 88.8s、GATE-01 32.3s 均正常），观测与 V2.1/V2.2 报告一致（耗时随 LLM 负载波动）。

### 4.3 离线确定性测试（不依赖 HTTP/LLM，可重复执行）

| 脚本 | 结果 | 关键断言 |
|---|---|---|
| tests/eval/run_retrieval_eval.py | **PASS** | 17 例：HitRate@5=100%、漏检 0%、MRR=1.0000、CitationPrecision@5=32.94%、EvidenceCoverage=100%；报告 retrieval_eval_report.json/.md。**2026-09-20 增补 nDCG@K 后 top-K=20 复跑：HitRate@20=100%（即 Recall@20）、MRR=1.0、nDCG@20=0.9846、EvidenceCoverage=100%** |
| tests/eval/run_retrieval_ablation.py | **PASS** | **四档消融（同 17 例固定题集、同候选预算、同行级隔离）**：A0 纯 dense 单路 Top-1=100%/HitRate@20=100%/nDCG=0.9756；A1 +BM25 混合 Top-1=29%/nDCG=0.6862；A2 +受控变体（无精排）Top-1=24%/nDCG=0.6520；A3 完整流水线（精排+多样性）Top-1=100%/MRR=1.0/nDCG=**0.9953**。结论：①多通道召回保覆盖，但无精排时 RRF 融合稀释前排质量，**CrossEncoder 精排是前排质量的决定性环节**（A2→A3 nDCG +34.3pp）；②完整流水线较纯 dense 基线 nDCG +2.0pp；③本语料下 Recall@20 全档 100%（覆盖到顶），架构价值在排序质量与语料增长后的多通道鲁棒性 |
| tests/eval/test_page_chunking.py | **PASS** | 3 页注入→6 分片，page_no={1,2,3}、chunk_id 含 pN、package/bidder_name 写入、语义检索命中第 3 页且透传页码 |
| tests/eval/test_retrieval_access.py | **PASS** | 公开 2 片/内部 2 片：匿名仅召回 public、owner 可见本人 internal、其他投标人/招标人不可见、admin/auditor 全见；pipeline 缓存按身份分桶（≥2 桶） |
| tests/eval/test_evidence_gate.py | **PASS** | **硬闸门纯函数 54 断言**（D25 后）：寒暄识别 16 例；工具证据判定（RAG 高/低分阈值 0.3、PG/图谱空结果、标书工具越权文本、执行失败、未知工具、**R13-R16 权威目录工具实质内容/空匹配**）；gate_decision 三态状态机；问题特征词覆盖（通用法规 FAQ 不为虚构项目背书、纯通用问题不约束）；固定话术不含业务事实 |

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

### 4.5c V1.4 自动成册补充实测（pytest 离线 + 接口冒烟 + 浏览器，均通过）

- `pytest tests/test_new_tools.py` **34 passed**：含 `test_profile_placeholder_fill`（22 别名替换、[资质证书编号] 展开、跨 chunk 未闭合 `[` 缓存流式）与 tuple 返回值适配；
- 后端接口冒烟（临时脚本，测后已删）：注册→登录→GET 空档案→PUT（1 证书）→GET 回显→匿名 401；/api/bid/section 回填断言；/api/bid/matrix 空稿 fail＋非法 400；/api/bid/full/stream 两节 SSE 全事件序列；
- 浏览器实测（2026-09-19，admin/admin123，doc#7 test_bid.txt）：企业资料库 5/12＋1 证书保存成功；整本合稿（5 章全量）生成对照表 18 行，其中**红色"4 项实质性条款不合格（投标前必须整改）"**：第 5 条资格（近 3 年 3 个 500 万类似业绩）、第 9 条交付（120 日历天）、第 10 条商务（10 万保证金基本户转出）、第 11 条商务（不得超 860 万限价）；顶部红色提示"存在实质性不合格项，导出前须整改"；业务测算类占位 5 项在灰色提示区列出（参考值/项目经理/服务承诺类，未杜撰）；
- 单章"资格响应"：正文直接写出"华信浏览器实测有限公司…法定代表人测试人…注册资本人民币3000万元…软件企业证书（二级，编号UI-2025-888，有效期至2028-08-08）"，无 [公司全称] 残留，已参考 3 条同类案例；
- 前端类型检查 `npx tsc --noEmit` **0 报错**（V1.3 遗留的 9 个告警本期已全部修复：ComplianceResult/QualificationResult 补 docId、ReviewBox 的 review_type 联合补齐 response/scoring、资格检查请求体未定义变量 companyCerts 改回参数 certs——后者同时修复了"执行资格检查必抛 ReferenceError"的潜在运行时缺陷）。

### 4.5d V1.5 证书附件 OCR 补充实测（pytest 离线 + 接口冒烟 + 浏览器，均通过）

- `pytest tests/test_new_tools.py` **43 passed**（V1.4 34 项＋本期 9 项 TestCertOcr）：`test_fallback_qualification_cert/business_license/level_stripped_from_name/empty` 覆盖资质证/营业执照/名称剥离等级词/空文本；`test_extract_llm_success/failure_fallback/empty_text` 覆盖 LLM 成功/异常回退/空文本；`test_cert_storage_lifecycle_and_isolation` 覆盖 uuidhex token、跨用户 404、`../../etc/passwd` 穿越 404、`.exe` 上传 ValueError、孤儿清理删除数；`test_ocr_image_uses_rapidocr` 覆盖图片字节→cv2 解码→RapidOCR 结果按行拼接（引擎 mock，不拉模型）；
- 后端接口冒烟（临时脚本，测后已删）：注册→登录→匿名上传 401→登录上传证书 PNG（pymupdf 排版＋simhei 字体，200dpi 渲染）→RapidOCR 中文识别＋LLM 四字段全对（建筑业企业资质证书/一级/BZ-2025-777888/2029-12-31，source=llm warnings=[]）→本人预览 200 image/png 字节一致、跨用户 404→PUT 保存→GET 回显含 file_token/ocr_text→清空证书 PUT→孤儿清理 404；
- 浏览器实测（2026-09-19，admin/admin123）：证书卡片"上传证书自动识别"→按钮 loading→20 秒后四字段自动填充（建筑业企业资质证书/特级/JZ-2026-666999/2030-08-08），左下出现证书缩略图与"原件已上传：资质证书.png"，展开"OCR 原文"显示完整识别文本；保存后绿色提示；刷新页面证书与缩略图正常回显。三张截图见 7.2。

### 4.5e V1.7 S3 接入 + 密钥轮换补充实测（pytest 离线 + CLI，均通过）

- `pytest tests/test_new_tools.py` **67 passed**（V1.6 55 项＋本期 12 项新增）：
  - **TestFieldCryptoRotation 5 项**（monkeypatch 双密钥链 + reload_keys，测试后恢复派生密钥隔离）：历史 K2 密文经 MultiFernet 仍可解（is_encrypted/decrypt_field）；key_index=1→needs_rotation=True→rotate_value 后 key_index=0 且明文一致、已是当前密钥不重复加密；新 encrypt_field 用第一个（当前）密钥；明文/空串 passthrough 不参与轮换；PROFILE_ENC_KEYS 配成非法值时跳过并回退 AUTH_SECRET 派生密钥（存量零迁移兜底）；
  - **TestS3CertStorage 7 项**（botocore Stubber，无需真实 MinIO）：put_object 严格断言 Bucket/Key=`certs/{uid}/{uuidhex}.png`/Body/ContentType=image/png/Metadata.original_name 已 URL 编码（**先暴露中文文件名 ASCII 校验缺陷 D18，再修生产代码**）；get_object 字节一致＋NoSuchKey→FileNotFoundError；delete_object；cleanup 列举前缀＋delete_objects 批量删（保留集内不删，返回删除数 1）；`../` 穿越/`.exe` 扩展名/预签名越权 token 均在发 API 前被拒（Stubber 零调用）；预签名 URL 为 s3v4（含 X-Amz-Signature、bucket 与 token）；按 settings（cert_storage_type=s3）工厂构建出 S3CertStorage；
  - TestCertStorage 既有 2 项补 read() 断言与 reset_cert_storage 单例隔离；
- 全量 pytest：**250 passed**；仅 tests/test_intent.py 3 项失败（is_out_of_scope 合同违约判定、诚实约束注入），已 `git stash` 在基线 commit `58a4399` 上复跑复现，确认为**与本期改动无关的既有失败**（意图分类模块，非本期触及文件）；
- CLI 实测：`python -m src.tools.field_crypto status`（默认环境输出"密钥链长度: 1"）、`gen-key`（输出 urlsafe Fernet key 与轮换操作提示）正常；
- 硬闸门 `tests/eval/test_evidence_gate.py` **44 断言全过**；前端 `npx tsc --noEmit` **0 报错**（本期未改前端）。

### 4.5f V1.8 R12 审计落库补充实测（pytest 离线 + HTTP 冒烟，均通过）

- `pytest tests/test_new_tools.py` **75 passed**（V1.7 67 项＋本期 8 项新增 TestAuditLog）：
  - record_audit INSERT 参数严格断言（action/profile.update、target_type=company_profile、user_id、username），changed_fields 为字段名 JSON 数组，**所有绑定参数序列化后不含任何敏感值**（"13812345678"/"6222" 负向断言）；
  - PG 未就绪（ready=False）时 record_audit 返回 False 且不触达 DB；写库抛异常时降级返回 False 不抛出（审计永不阻断主业务）；
  - 字段名清洗：去重、剔除非字符串、去空白、限长 64、限量 50；action 去空白后为空直接拒绝落库；detail/ip/user_agent/username 长度钳制（2000/500/500/500）；
  - list_audit_logs：WHERE 条件按 user_id/action 参数化拼接、`ORDER BY id DESC LIMIT :limit OFFSET :offset`、limit 超 200 钳制为 200、非法 order（如 `; DROP TABLE`）回落 DESC、非法 limit/offset 回落默认值；JSONB changed_fields 字符串形态兜底 json.loads 解析、datetime 序列化为 `2026-09-19 10:11:12`；PG 未就绪返回 `{items:[],total:0,limit:50,offset:0}`；
  - upsert_profile 有字段变更写一条 profile.update 审计且传透 username/ip/user_agent；旧档与新档完全一致时**不写审计**（避免噪音）。
- 全量 pytest：**258 passed**（较 V1.7 +8）；仅 tests/test_intent.py 3 项失败，与 V1.7 基线实证的既有失败同名同因，非本期回归；
- HTTP 冒烟：`audit_logs` 表幂等建成（to_regclass=audit_logs）；PUT 资料变更后 admin 查到 changed_fields=`['company_name','contact_phone','bank_account']`，items JSON 无明文；bidder 403、匿名 401；
- 硬闸门 **44 断言全过**；前端 `npx tsc --noEmit` **0 报错**（本期未改前端）。

### 4.5g V1.9 R13/R14 异常解释层与范本推荐（pytest 离线，均通过）

- `pytest tests/test_new_tools.py` **85 passed**（V1.8 75 项＋本期 10 项：TestAnomalyCatalog 4 项 + TestTemplatesCatalog 6 项）：
  - 异常 catalog 完整性：≥10 个 code 且每条必须含 summary/causes/impact/actions 四要素；`get_anomaly_guidance` 精确命中 + 大小写不敏感兜底 + 未知/空 code 返回 None；`format_guidance_text` 渲染含【问题说明】【处置建议】【法规依据】；Agent executor 对正常/空 code/未知 code 三种输入的文案断言；
  - 范本推荐：`recommend_templates("工程施工项目招标")` 首条=TPL-BID-001；category 过滤后类别一致（工程施工+合同范本→TPL-CON-001）；无关 query（量子加密通信卫星）返回空；详情查询与三类枚举（招标文件/合同范本/业务表单）；Agent executor 正常/空 query；TestClient 全链路（explain 200/404、batch 混合、recommend 排序、detail 200/404、list 三类）；
  - 开发阶段修正的一处算法问题（先红后绿）：初始 name 命中加权 0.5 分导致"建设工程**施工**合同"在纯"工程施工"query 下挤掉招标文件范本，调整为 name 权重 0.25 + 给招标类范本补充类别核心词"招标"，并在测试中明确"工程施工项目招标"含类别意图词的断言；
- 全量 pytest：**203 passed**（指定测试文件集，test_new_tools 85 + 其余模块；test_intent 3 项为 V1.7 起基线实证的既有失败，非本期回归）；
- HTTP 冒烟：OVER_CONTROL_PRICE 端点返回 error/4 actions/法规依据；范本推荐 top1=TPL-BID-001、列表 11 份三类；
- 硬闸门 **44 断言全过**；前端 `npx tsc --noEmit` **0 报错**（本期未改前端）。

### 4.5h V2.0 R15/R16 异议投诉与操作引导（pytest 离线，均通过）

- `pytest tests/test_new_tools.py` **102 passed**（V1.9 85 项＋本期 17 项：TestAppealCatalog 8 项 + TestGuideCatalog 9 项）：
  - R15：11 主题六要素完整性（channel/deadline/materials/steps/legal_basis/notes）、大小写不敏感取主题、评标结果异议首推 APPEAL_RESULT（deadline 含公示期与 3 日）、投诉材料命中 COMPLAINT_MATERIALS、政采质疑走财政渠道+7/15 工作日、文件条款异议命中+无匹配空、文本渲染六段、工具 executor 正常/空/无匹配、TestClient 三件套（consult 排序、topics 4 类、detail 200/404）；
  - R16：7 流程三角色（投标人/招标人/评标专家）且每阶段含 purpose/prerequisites/actions/common_errors；上传失败定位 up-3 且前后阶段齐全；开标解密 dec-2、注册首阶段 prev=None；招标人公告 tdr-3、仅"评标专家"不锁定阶段（stage_locked=False）；CA 办理 ca-1、无匹配 None；流程详情与列表（每流程≥2 阶段）；文本渲染含【识别结果】【操作步骤】【常见错误/坑】；工具 executor 三态；TestClient 三件套（recognize 锁定+404、workflows 三角色、detail 专家 5 阶段+404）；
  - 开发期先红后绿修正两处真实问题：①识别器流程级关键词误致阶段锁定（已改为必须命中至少 1 个阶段专属词才锁定，否则 stage_locked=False）；②COMPLAINT_MATERIALS 材料清单漏"投诉书正文"（已补六段式说明）；引导文本补 flow id 便于可追溯。
- 全量 pytest：**269 passed**（指定测试文件集；test_intent 3 项为 V1.7 起基线实证的既有失败，非本期回归）；
- HTTP 冒烟：upload/decrypt/role-only/tenderer/404 五场景全过；APPEAL 渠道、时限、政采区分正确；
- 硬闸门 **44 断言全过**；前端 `npx tsc --noEmit` **0 报错**（本期未改前端）。

### 4.5i V2.1 R17 检测结果主动弹窗预警（前端 tsc + HTTP 契约 + 浏览器，均通过）

- 本期为纯前端增强（+验收用例），**后端零改动**；弹窗触发判定直接消费既有检测端点返回的 risks/checks/self_check/clauses/anomalies 字段，无需新增 API；
- 前端 `npx tsc --noEmit` **0 报错**；新增 [frontend/components/AlertModal.tsx]（level 双级/条目折叠/锚点详情）并在 [frontend/app/documents/page.tsx] 五类检测完成回调接入（合规/资格/废标/响应性/报价）；
- HTTP 数据契约由 **ALERT-01** 覆盖（6.1s，fail+error 异常/CN_MISMATCH/pass 无 error 三断言）；
- 浏览器实测三场景：①报价总价 300 vs 分项合计 200（叠加大写 740000 残留）→ 红色弹窗含 SUM_MISMATCH+CN_MISMATCH 两条、标题"发现不合格项，请及时处理"、双按钮齐全（v21_alert_modal.png）；②"查看详情"关闭弹窗并平滑滚动至报价计算表面板；③总价 200 一致、清空大写 → **不弹窗**、面板"✅ 校验通过"（v21_no_alert_pass.png）；console 全程无错误。

### 4.5j V2.2 真实 MinIO/S3 连通实测（手动，13/13 PASS）

- **环境**：MinIO RELEASE.2025-09-07T16-13-09Z windows-amd64 单文件（GitHub Releases 归档前最后带二进制版本之一，107.9MB），`minio.exe server <数据目录> --address :9000 --console-address :9001`，MINIO_ROOT_USER/PASSWORD=minioadmin；/minio/health/live 200。
- **脚本**：[tests/acceptance/manual_minio_live.py]（非自动套件，需真实 MinIO；脚本内自带环境变量与收尾清桶）。
- **13 项断言全过**：

| # | 断言 | 实测结果 |
|---|---|---|
| 0 | MinIO 存活 | /minio/health/live 200 |
| 1 | 生产工厂 CERT_STORAGE_TYPE=s3 构建 | 返回 S3CertStorage 实例 |
| 2 | auto_bucket 自动建桶 | head_bucket 成功（bid-certs-live-test） |
| 3 | save 中文名证书 | token 含 .jpg、size=69 |
| 4 | key 路径隔离 | certs/999999/{token} |
| 5 | D18 metadata 中文名 URL 编码 | x-amz-meta-original-name 百分号编码，unquote 还原"营业执照-真连通测试.jpg" |
| 6 | 预签名 s3v4 | URL 含 X-Amz-Signature |
| 7 | 预签名匿名 GET | 200 且 69 字节与原文一致 |
| 8 | read 回读 | 字节一致 |
| 9 | cleanup 孤儿批删 | removed=1 |
| 10 | 孤儿对象不可读 | FileNotFoundError |
| 11 | delete 后 404 映射 | FileNotFoundError（NoSuchKey） |
| 12 | 收尾清桶零残留 | delete_bucket 后 head_bucket ClientError |
| 合计 | **13/13 PASS** | 无测试数据残留 |

- **意义**：V1.7 的 7 项 Stubber 验证的是"请求构造/响应解析正确性"（无真实网络与签名服务）；本次验证了真实服务侧的 TCP 连通、AWS SigV4 签名握手、path-style addressing、MinIO 对 metadata ASCII 约束的实际执行（D18 修复在真实服务再次确认）、预签名直链的跨进程匿名可达性与生命周期、list/delete 批处理分页语义——这些是 Stubber 无法覆盖的部署期风险点。

### 4.5k V2.3 多专家协作接入＋Agent 端到端评测基准（pytest 离线＋HTTP 评测＋浏览器，均通过）

**A. 多专家工作流接入（离线 19 项 + MULTI-01 + 浏览器）**

- 工作流：[src/agent/multi_agent.py] `CoordinatorAgent.plan`（LLM JSON 计划、专家名白名单过滤、异常/脏数据回退三专家全开）→ LAW/CASE/PRICE 三专家线程池并行（contextvars 逐任务 copy 传播行级隔离，各带角色工具子集，最多 3 轮 ReAct）→ WRITER 综合；端点 [api/server.py] `POST /api/multi-agent/run` 补 `get_current_user_optional` 鉴权、`bidding_agent.ready` 503 守卫、真实 client IP 限频、`use_access_scope(user)` 包裹。
- 专家循环防御与主 ReAct 循环对齐：[src/agent/tool_defense.py] 新增全角 `｜｜DSML｜｜` 变体检测与归一化解析（2 项新单测）；专家循环支持文本伪工具调用解析后真实执行（限本专家工具白名单，越权工具不执行）、不可解析标记→纯文本纠偏提示、轮次耗尽→强制一次无工具纯文本生成、终稿仍为标记则丢弃，写作终稿为空时拼接各专家有效结论兜底。
- 离线 pytest **19 项全绿**：[tests/test_multi_agent.py] 5 项（计划 JSON 解析+非法专家过滤、脏数据回退、plan LLM 异常回退、**workflow 结构+Barrier 强制三线程并发进入上下文+行级隔离 scope 传播断言（bidder→("owner",7)）**、跨专家来源去重）；[tests/test_tool_text_parsing.py] 14 项（含全角 DSML 检测/解析 2 项新增）。
- 真实冒烟（独立于 MULTI-01）：HTTP 200/185s，主管调度 CASE+LAW，终稿准确含"2025年12月15日 14:00""860万元""保证金≤估算价 2%"，[资料N] 标注齐全、无标记泄漏；PRICE 专家在 PG 历史表未部署时如实报告"数据缺口"而非编造（浏览器截图可见）。

**B. Agent 端到端评测基准（12 题双指标，两跑如实记录）**

- 题集 [tests/eval/agent_eval_cases.json]：单跳/多跳/跨域各 4（E2E-01~12），事实锚点全部取自可直查的在库数据；打分器 [src/agent/eval_scoring.py] 纯函数零依赖（事实组 any/all 嵌套、组间等权，通过线：工具对＋事实≥0.6＋答案非空），离线单测 [tests/test_agent_eval_scoring.py] **15 项全绿**；评测器 [tests/eval/run_agent_eval.py] 逐题打真实 POST /api/chat（最长 280s/题），从 exec_log.tool_calls 提取实际工具，输出 agent_eval_report.json/.md。
- 最终（第二跑，题集修正后）：**12 题 11 PASS，通过率 0.917；工具选择正确率 1.00；事实组覆盖率 0.909**；分类别：单跳 4/4、跨域 4/4、多跳 3/4。

| 类别 | 用例 | 通过 | 工具选择正确 | 事实覆盖 |
|---|---|---|---|---|
| 单跳 | 4 | 4 | 1.00 | 1.00 |
| 多跳 | 4 | 3 | 1.00 | 0.67 |
| 跨域 | 4 | 4 | 1.00 | 1.00 |
| 合计 | 12 | 11（0.917） | 1.00 | 0.909 |

- 两跑差异如实记录：首跑 10/12——E2E-04 当轮证据门拒答（复跑 PASS，改写措辞即能命中，定性检索措辞敏感）、E2E-05 经 PG/KG **直连查证为坏题**（PG bidding_procurement 表未部署、KG 仅 2 Project/2 Buyer/2 Agency 无供应商节点，"空调"数据不存在），替换为 KG 真实节点两跳题（北京交通大学雄安校区项目→采购人/代理机构，复跑 PASS）；第二跑唯一失败 E2E-07（大陆/香港跨法域对比）gated 拒答（首跑曾 PASS），工具选择正确、事实 0 分，定性为**复杂多跳问题的检索/证据门稳定性波动**（D22，第 5 章）。全过程未改任何事实判定标准凑分。
- 说明：E2E-08（采购量最多标的物下钻）因依赖未部署的 PG 表，设计上 facts 为空只评工具选择（gated 拒答仍 PASS）；评测器 CLI：--base-url/--timeout/--fact-threshold/--min-pass，health 不 ready 退出码 2。

### 4.5l V2.3 三业务线显式意图分类路由（pytest 离线＋直连/HTTP 冒烟，均通过）

- 背景：V2.3 前工具选择完全依赖 LLM 在 9 工具全集内自选。本期把意图识别升级为**显式三业务线分类路由**：[src/agent/intent.py] 新增 `classify_domain(question, history)`（规则评分：强信号词权重 2、弱信号词 1，显著单域需强信号命中＋总分≥2＋与次高域分差≥2；零信号时继承上一轮用户消息的域）与 `select_tools_for_domain(domain, base)`（保序去重裁剪），返回 `{domain, scores, confident, inherited}`。
- 裁剪策略（保守：宁可多给工具不可误裁）：**search_bidding_knowledge 为跨域底座恒保留**；法规域＝底座＋consult_appeal/recommend_template（3 工具）；企业域＝底座＋KG/PG/标书列表/标书生成/范本/操作引导（7 工具）；招投标域/通用/低置信/跨域一律保留全集（9 工具）。接入点 [src/agent/core.py] `_build_context`，开关 [src/config.py] `INTENT_ROUTING_ENABLED`（默认 true，关闭即回退全集自选），每次问答输出"意图路由"观测日志（domain/confident/scores/工具数 9→N）。
- 离线 pytest：新建 [tests/test_intent_routing.py] **14 项全绿**（纯法规→regulation/3 工具、纯企业查询→enterprise/7 工具、标书生成→tender/全集、GATE-01 月球题与采购人/价格/CA/保证金等弱信号→general/全集、历史继承、开关无关的保序去重）；本轮相关 pytest 合计 **160 passed**（react_loop/sse/multi_agent/eval_scoring/tool_text_parsing/new_tools/intent_routing）。
- 真实冒烟：直连 `_build_context` 法规题 9→3、标书题 9→9、预算题 9→9；HTTP 法规题"政府采购的质疑期限是几天？"路由日志 domain=regulation tools 9->3，gated=False、consult_appeal 作答"7 个工作日"；GATE-01 月球无证据题在路由改动后直连复测仍 gated=True/sources=0/无编造数字。
- 路由暴露并修复既有缺口 **D25**（见第 5 章）：四个 R13-R16 本地权威目录工具此前不在证据门证据工具集合内，裁剪后单走目录即被误判无证据；修复后硬闸门离线断言由 44 增至 **54 项全过**（新增目录实质内容=证据、空匹配/未识别=无证据、法条正文"无权质疑投诉"不误杀共 10 条）。

### 4.6 浏览器 UI 实测（V1.3：2026-09-18；V1.4 补测：2026-09-19，admin/admin123）

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
| **V1.4 企业资料库页：12 字段表单＋证书动态行，保存成功，完整度"基础字段 5/12 · 资质证书 1 项 · 同类业绩 0 条"** | PASS | v14_profile_saved.png |
| **V1.4 标书弹窗双 Tab＋"企业资料库（自动回填）"入口；整本生成中按钮 loading/禁用** | PASS | v14_bid_tabs.png |
| **V1.4 整本合稿：对照表 18 行、4 项实质性不合格红框、verdict 红色整改提示、业务测算占位提示** | PASS | v14_full_matrix.png、v14_matrix_red.png |
| **V1.4 整本 Markdown 预览（封面/目录/章节/附录/待补清单，约 4.6k 字）** | PASS | v14_full_md.png |
| **V1.4 单章资格响应：公司名/法人/注册资本/证书编号(UI-2025-888) 已写入，无 [公司全称] 残留** | PASS | v14_section_filled.png |
| **V1.5 证书 OCR：上传后四字段自动填充（建筑业企业资质证书/特级/JZ-2026-666999/2030-08-08）、原件缩略图、OCR 原文折叠展开** | PASS | v15_cert_ocr.png |
| **V1.5 保存企业资料：绿色"已保存"提示** | PASS | v15_cert_saved.png |
| **V1.5 刷新页面：证书卡片与缩略图正常回显** | PASS | v15_cert_reload.png |
| **V2.3 多专家协作：琥珀色开关开启→发问→"多专家协作"徽标＋可折叠专家过程面板（案例/价格专家 chips＋各专家轮数/耗时/答案）→终稿含 2025年12月15日/860万事实＋来源卡片** | PASS | v23_multi_agent.png |

全程浏览器控制台无报错；`npx tsc --noEmit` 已清零（V1.3 遗留 9 告警本期修复，见 4.5c；V2.3 新增多专家前端代码 tsc 仍 0 报错）。

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
| D17 | 中（V1.4 修） | 前端资格检查 runQualificationCheck 请求体引用不存在的变量 `companyCerts`（重构遗留，tsc TS2304），**UI 上执行资格比对必在前端抛 ReferenceError 并走失败分支**；另 ComplianceResult/QualificationResult 缺 docId 类型声明（4 处 TS2339/2353）、ReviewBox 的 review_type 联合缺 response/scoring（2 处 TS2322），共 9 个存量 tsc 告警 | 变量改回函数入参 `certs`（弹窗文本框录入的资质清单，与后端 company_qualifications 字段对齐）；两个接口补 `docId?: number`；ReviewBox type 联合补齐后端五类 review_type | `npx tsc --noEmit` 0 报错；/documents 页面热更新编译 200 | 已关闭 |
| D18 | 中（V1.7 修） | **S3 put_object 中文文件名经 Metadata 直传会触发 botocore ParamValidationError**（"Non ascii characters found in S3 metadata"）——S3 用户自定义元数据仅允许 ASCII，而证书原名实际场景几乎都是中文（营业执照.png），S3 模式下上传必失败。由 TestS3CertStorage 的 Stubber 严格参数断言先暴露 | original_name 改为 `urllib.parse.quote(filename, safe="")` URL 编码后存入 Metadata；OCR 端点同步改为对上传字节 `ocr_cert_bytes` 识别（S3 无本地路径，原 `cert_file_path` 路径在 s3 模式会 NotImplementedError）；预览端点改预签名 307/应用代理双通道 | Stubber put_object 断言编码后元数据通过；CERT-01 全过（默认 local 行为不变）；S3 7 项 Stubber 单测全过 | 已关闭 |
| D19 | 高（V2.3 修） | **multi-agent 端点一触即 500（2.0s 内）：`RateLimiter.acquire` 方法不存在**。端点自原型创建后从未被前端/验收调用，潜伏至今；真实冒烟首次调用即在限频行抛 AttributeError | 改用 RateLimiter 真实接口 `is_allowed(client_ip)`（全局 30 次/60s 策略），超限返回 429；client IP 由原恒为 unknown 的 `getattr(req,"_client_ip")` 改为 `request.client.host` | MULTI-01 PASS（207.3s）；端点真实冒烟 HTTP 200 | 已关闭 |
| D20 | 高（V2.3 修） | **多专家线程池并发进入同一个 contextvars.Context 必崩**：`pool.submit(ctx.run, ...)` 让多个专家线程共享同一 Context 对象，Python 规定 Context 不可重入，专家并行阶段（72s 处）抛 "cannot enter context: ... is already entered" 后 500。同时 ThreadPoolExecutor 默认不继承主线程 ContextVar，直接写还会让 RAG 行级隔离退回匿名 public（与 D12 同类、新代码重犯） | 主线程 `base_ctx = copy_context()`，每个专家任务独立 `pool.submit(base_ctx.copy().run, agent.run, task)`；离线测试以 `threading.Barrier(3)` 强制三专家并发在场，断言各工作线程 scope 均为 ("owner",7) | 强化后的 test_workflow_structure_and_scope_propagation PASS（Barrier 下旧代码必崩、新代码通过）；MULTI-01 中多专家真实检索成功 | 已关闭 |
| D21 | 中（V2.3 修） | **专家循环无伪工具调用防御，DeepSeek 全角 `｜｜DSML｜｜` 标记直接泄漏到用户终稿**：首次 200 冒烟终稿开头即为 `<｜｜DSML｜｜ calls>...`，且法规专家空答案（0 字）。主 ReAct 循环早有 tool_defense，专家循环是复制时遗漏 | ①tool_defense 增加全角竖线 DSML 变体检測与归一化（open/close 令牌正则→半角 XML→既有 invoke/parameter 解析）；②专家循环解析文本工具调用后真实执行（仅限本专家工具白名单，越权不执行），不可解析标记则追加纯文本纠偏提示继续；③轮次耗尽仍无干净文本则强制一次 tools=[] 纯文本生成；④终稿仍含标记则丢弃，写作终稿为空时拼接各专家有效结论兜底 | 新增 2 条全角 DSML 解析单测；修复后两次真实冒烟终稿均为干净 Markdown（含事实与 [资料N] 标注），MULTI-01 增加终稿洁净负向断言 | 已关闭 |
| D22 | 中（V2.3 观测，已缓解） | **复杂多跳问题检索/证据门存在轮次波动**：Agent 评测 E2E-04（资格预审异议渠道）首跑 gated 拒答、复跑 PASS（改写问法即可命中在库 FAQ 254）；E2E-07（大陆/香港对比）首跑 PASS、复跑 gated 拒答（66.1s，工具选择正确但证据文本未覆盖问题特征）。工具选择 100%，失败均发生在检索命中/证据门环节 | **V2.3 可用性前置阶段缓解**：react_loop 最终 gated 前增加复杂多跳问题（对比/分别/和/与/哪些等特征词＋长度阈值）的 query 改写重试一次——注入拆分子问题提示后再调一轮检索，命中证据则放行作答，仍无证据才拒答；未改证据门阈值与事实标准。E2E-07 复跑直接 PASS（gated=False，6 来源） | 复杂多跳题直连冒烟 gated=False/6 来源；react_loop 离线单测＋硬闸门 44 断言全过 | 已缓解（重试仅一次，极端波动仍可能拒答） |
| D23 | 中（V2.3 可用性前置，已关闭） | **问答交互无审计留痕**：原 audit_logs 仅覆盖企业资料/证书 OCR/密钥轮换三类敏感操作，用户每次问答（/api/chat、/api/chat/stream）不落库，小范围试用无法收集 badcase 与用量统计 | 在 core.py `_chat_events` 的 done 分支调用 `record_audit`，action 为 `chat.answer`/`chat.gated`/`chat.out_of_scope`/`chat.vague`；detail 仅存 q_len/ans_len/sources/web/gated/elapsed_ms，changed_fields 存实际调用工具名列表，**不存问题原文与回答原文**；失败降级不阻断主流程；server.py 透传 user 与 request.client.host | 直查 audit_logs 表：chat.answer 记录含 q_len=28 sources=6 gated=False elapsed_ms=39711 等字段，问答均落库 | 已关闭 |
| D24 | 中（V2.3 可用性前置，已关闭） | **PRICE 专家与价格分析依赖的 bidding_procurement 表未部署**：postgresql_client 仅查询不建表，price_analyzer/search_postgresql 报"数据缺口"，价格类问题直接拒答 | 新增 scripts/seed_bidding_procurement.py：建表（11 字段，含 project_code 唯一键＋purchaser/subject/amount 索引）＋写入 30 条脱敏合成数据（覆盖货物/工程/服务三类、多采购人多地域、含同名项目跨地域对比行）；幂等 UPSERT，--reset 可重灌 | 直连 PG：avg winning_amount=374.33、top_by_amount 返回 3450/1280/920、keyword "办公设备"命中 3 条；price_analyzer 链路可用 | 已关闭 |
| D25 | 中（V2.3 意图路由，已关闭） | **四个本地权威目录工具未计入证据门，返回实质内容仍被判"无证据"拒答**：consult_appeal/recommend_template/guide_operation/explain_anomaly 是 R13-R16 人工编排的受控目录，但不在 evidence_gate 的 `_EVIDENCE_TOOLS` 内。此前 LLM 多并行调用 search_bidding_knowledge 而未暴露；意图路由把纯法规题裁剪为 3 工具后，LLM 先调 consult_appeal（返回"质疑 7 个工作日"实质指引），证据门仍 gated 拒答。另裸"无权"空标记会误命中合法法条正文"供应商无权质疑投诉" | ①新增 `_CURATED_CATALOG_TOOLS` 四目录工具并入 `_EVIDENCE_TOOLS`，实质文本（不含空匹配措辞）即证据；②空标记补 未匹配/暂无/暂未识别，裸"无权"收紧为 无权访问/无权查看（真实越权文案均含"无权访问"，已全仓 grep 核实）；③特征词覆盖校验保持不变，GATE-01 虚构项目即使误中目录仍 gated | 新增 10 条目录证据硬闸门断言（共 54 断言全过）；法规题 HTTP 冒烟 gated=False、consult_appeal 作答"7 个工作日"；GATE-01 直连复测仍 gated=True/sources=0/无编造数字 | 已关闭 |

V1.1 的 D1-D6 修复在本轮回归中持续有效。

**V1.4（⑪ 自动成册）本期改动未引入新缺陷**：后端 pytest 34 项、接口冒烟、49 项全量、浏览器实测一次通过。顺带修复 1 个 V1.3 遗留的前端运行时缺陷 D17（资格比对必失败）并清零全部存量 tsc 告警。测试脚本侧两处自测断言修正（非产品问题）：①注册端点不返回 token，冒烟脚本改为注册后再登录；②BID-04 回填断言放宽为"占位符已替换"或"prompt 引导 LLM 直接引用真实资料"双路径，均以 profile_used=true 且无 [公司全称] 残留为准。

**V1.5（⑫ 证书附件 OCR）本期改动未引入新缺陷**：后端 pytest 43 项、接口冒烟、50 项全量、浏览器实测一次通过。设计上采取保守策略规避风险：①OCR 不直接写库，识别结果经用户核对后随整表 PUT 一并保存；②原件文件路径用 uuidhex 白名单正则＋resolve 父目录强校验双重防穿越，跨用户目录访问 404；③PUT 后比对新旧 file_token 清理孤儿，避免磁盘堆积；④非证书扩展名上传 400、OCR 失败 422 并回删原件（不残留半文件）。CERT-01 的匿名 401、跨用户 404、穿越 404、非法格式 400、孤儿 404 五项鉴权断言全过。

**V1.7（⑭ S3 接入＋密钥轮换）发现并修复 1 个真实生产缺陷 D18**：S3 元数据不接受非 ASCII，中文名证书在 s3 模式上传必失败，由新增 Stubber 严格参数断言在编码阶段拦截（先红后绿）。另测试方法侧一处适配（非产品问题）：Stubber 包装的注入 client 需显式带 `Config(signature_version="s3v4")` 才能断言预签名 v4 特征，与生产 `_s3()` 构建配置对齐。

**V1.8（⑮ R12 审计落库）未发现产品缺陷**：8 项离线单测一次通过，HTTP 冒烟与 AUDIT-01 一次通过。开发阶段修复的一处测试桩 bug（`sql.upper()` 后 `startswith("SELECT * FROM company_profiles")` 表名大小不匹配导致 fake PG 返回空档，与生产无关）和一处产品鲁棒性补强（`record_audit` 的 action 入参增加 `str().strip()` 空白清理，避免纯空白 action 落库），后者属防御性加固，非线上缺陷。

**V1.9（⑯ R13/R14 异常解释层＋范本推荐）未发现产品缺陷**：核心单测首轮暴露并修复 1 处推荐排序算法问题——name 命中加权 0.5 过高导致纯"工程施工"query 下"建设工程施工合同范本"（TPL-CON-001）挤掉"工程施工招标文件范本"（TPL-BID-001），改为 name 权重 0.25 并为招标类范本补充类别核心词后测试转绿（先红后绿，属新功能内部调优，非已上线缺陷）。全量 HTTP 验收首轮因**测试环境漏配 `PROFILE_ENC_KEYS` 双密钥链**致 PROFILE-03 失败 1 例（非代码问题），补齐环境变量重跑后 56/56 全绿。

**V2.0（⑰ R15/R16 异议投诉＋操作引导）未发现产品缺陷**：R15 单测首轮发现 COMPLAINT_MATERIALS 主题的材料清单遗漏"投诉书正文"本身（已补六段式撰写说明）；R16 识别器首轮存在流程级关键词误致阶段锁定的逻辑缺陷（仅说"评标专家"被错误锁定到第 1 阶段而非保持不锁定），已修正为必须命中至少 1 个阶段专属关键词才锁定阶段，否则 stage_locked=False。两处均属新功能内部先红后绿修复，非已上线缺陷。全量 HTTP 验收 58/58 一次通过。

**V2.1（⑱ R17 检测主动预警）未发现产品缺陷**：前端 tsc、ALERT-01 契约、浏览器三场景（红窗/详情定位/无异常不弹）全部一次通过。验收过程两度受**测试环境**（非代码）干扰并已澄清：①接手时运行中的后端进程未带 `PROFILE_ENC_KEYS` 双密钥链（PROFILE-02/03 失败），且验收脚本进程同样需要该变量直连 PG 解密（脚本与后端必须同密钥链），两端补齐后恢复；②连续两轮全量间隔 <1 小时时 MATRIX-02 因 V1.6 内存 TTL 缓存（SHA256 键、1 小时 TTL、进程内存）首请命中旧缓存而失败，重启后端清空缓存后全绿——该现象符合缓存设计，非功能缺陷。另：BID-01/02/03/04、P8-01 在首轮曾失败（500/超时/LLM 未调工具/解析空），未改任何代码、后端重启后复跑全部 PASS，定性为 LLM 云端 API 当轮响应波动。

**V2.2（⑲ MinIO 真连通补测）无代码改动、无产品缺陷**：V2.1 阶段 Docker/官方直链两路获取 MinIO 均受阻；本轮改用 GitHub Releases 归档版本 Windows 单文件一次启动成功，manual_minio_live.py 首轮 13/13 全过（未做任何代码修改即通过，反向印证 V1.7 S3 接入与 D18 修复的生产可用性）。实测后已停止 MinIO 进程释放 9000/9001 端口，脚本自动清空并删除测试桶，本地零数据残留；minio.exe 留存 C:\\Users\\DELL\\.local\\bin 供日后复测。

**V2.3（⑳ 多专家接入＋Agent 评测基准）发现并修复 3 个真实产品缺陷 D19-D21、观测 1 个稳定性问题 D22（未关闭）**：D19/D20/D21 均在"原型端点首次被真实调用"时暴露——500 限流方法名错误（2s 即崩）、contextvars Context 并发重入（72s 崩，离线 Barrier 测试已锁死回归）、全角 DSML 标记泄漏终稿，三处均先红后绿：MULTI-01 与两次独立冒烟从 500/脏终稿变为 200/干净事实终稿。评测侧发现的题集质量问题（E2E-05 锚定未部署数据）经 PG/KG 直连查证后换题，属基准维护而非放松标准；E2E-04/E2E-07 的轮次差异定性为检索波动（D22），未改证据门任何阈值。

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
| R8 | ~~标书生成当前为**单章流式**（5 章独立生成），企业资料库未接入，[公司全称]/[资质证书号] 等占位符需人工补；尚无整本合稿、逐条招标要求响应对照表与不合格项自动标红~~ **V1.4 已关闭**：企业资料库 1:1＋占位符双路径回填＋整本一键合稿 SSE＋响应对照表（🔴/🟡 标红，硬失败清单）＋docx 同色导出；**V1.5 进一步关闭"证书附件"**：图片/PDF 上传→OCR 四字段→私有原件→鉴权预览→整表保存→孤儿清理（CERT-01 全过） | 已实现"自动成册＋证书 OCR"，PROFILE-01/BID-04/05/06/CERT-01 与浏览器实测通过 | 剩余：业务测算类参数仍显式提示人工确认；证书原件未接入对象存储（见 R11） |
| R9（新增） | ~~对照表要求抽取与响应判定依赖 LLM（带关键词回退），条款条数/分类可能随模型波动~~ **V1.6 已关闭**：`_validate_row` 行结构校验（空要求丢弃、非法 status→NO_RESPONSE、category 白名单、material 启发式校正防乱标）＋1 小时内存 TTL 缓存（相同 db_id+bid_hash 复用，cached=True 跳过 LLM） | 可能漏标/错标个别偏离项 | 已用校验+缓存+硬失败清单+红黄分级+导出前整改提示；剩余：非确定性 LLM 判定仍需人工最终复核（业务测算类参数显式黄色提示） |
| R10（新增） | ~~企业资料按账号 1:1 明文存 PG（含银行账号等敏感字段），暂无字段级加密/脱敏~~ **V1.6 已关闭**：bank_account/contact_phone/contact_email/legal_person 应用层 Fernet 加密（PBKDF2 派生密钥）入库，GET 掩码展示（银行后 4/电话前 3 后 4/邮箱首字母+***/法人姓+**），PUT 掩码回传自动保留旧明文，upsert 字段级审计日志（不含值）。**V1.7 已支持多密钥链无停机轮换与批量重加密**。**V1.8 已支持审计落库表（audit_logs，admin/auditor 按字段名/动作/账号分页查询，AUDIT-01 全过无明文泄露）** | 多租户合规差距 | 已实现加密+掩码+密钥轮换+审计落库；剩余：TDE（数据库透明加密）待下一期 |
| R11（新增 V1.5） | ~~证书原件存本地 `uploads/certs/{uid}/`，未接入对象存储/CDN；OCR 识别准确度依赖图片清晰度~~ **V1.6 部分关闭**：存储抽象为 `CertStorage` 基类＋`LocalCertStorage`（默认）＋`S3CertStorage`（接口占位）；OCR 前加灰度化+小图放大预处理。**V1.7 完全关闭对象存储**：boto3 实际接入 S3CertStorage（put/get/delete/list 批量清理、s3v4 预签名 307、MinIO endpoint+path-style 适配、auto_bucket 自动建桶、中文原名 URL 编码 D18），OCR 改字节流、预览双通道，7 项 Stubber 单测全过。**V2.2 真实连通实测关闭**：真实 MinIO server 端到端 13/13 PASS（含 D18 metadata 真实服务复验、s3v4 预签名匿名 GET、批删/404 映射，manual_minio_live.py） | 多实例部署/生产可靠性、识别准确度 | Local/S3 双后端均已可用且经真实服务实证（CERT_STORAGE_TYPE 切换，.env.example 已补全部配置，复测步骤见 7.3）；剩余：商用 AWS S3 未实测（同 S3v4+path-style 协议，风险低）；复杂版式/手写/印章遮挡仍需人工核对 |
| R12（新增 V1.9） | ~~智慧问答四类功能覆盖不完整~~ **V2.0 四类已全部关闭**：②范本智能推荐（R14，11 份静态范本库+中文分词匹配）、③异常预警问答（R13，12 code 原因/处置/法规解释层，检测能力 P4-P9 早已具备）、④异议投诉咨询（R15，11 主题专项库，工程招投标与政采两套渠道区分）、①操作智能引导（R16，7 流程 27 阶段，三角色阶段识别+前后衔接）。**V2.1 另关闭"检测结果前端主动弹窗预警"（R17）**：合规/资格/废标/响应性/报价五类检测完成即红/黄弹窗（ALERT-01+浏览器实测全过） | 面向交易平台用户的服务完整性 | 后续增强：范本/流程/异常知识库接运营后台动态维护、异常 code 与操作 stage 随业务扩展持续补录；弹窗阈值可随业务反馈分级调优 |
| R13（新增 V2.3） | ①~~multi_agent 多专家工作流为孤立原型（仅 /api/multi-agent/run，前端无入口、验收无覆盖）~~ **V2.3 已接入主问答**（开关/面板/MULTI-01/浏览器全过，D19-D21 已修）；遗留：调度计划为一次性 LLM 拆解，不支持中途追加专家/人工修正；非流式整链路 185-242s，仅适合复杂问题，不宜默认开启（前端默认关闭）；PRICE 专家依赖 PG bidding_procurement 历史中标表，**本环境未部署该表**（浏览器实测中价格专家如实报告数据缺口，不编造；price_analyzer 早有"请先部署 PG 并导入数据"降级提示）。②Agent 端到端基准仅 12 题、事实判定为关键词组匹配，复杂多跳存在 D22 轮次波动（E2E-07 两跑一过一拒） | 多专家的速度/可干预性、价格分析在无历史库环境不可用；评测基准覆盖与稳定性统计尚浅 | 部署方导入 bidding_procurement 后复跑评测（题集锚点需随库扩充）；评测扩至 50+ 题、多跑取 flaky 率、引入语义级事实判定；多专家改流式/子问题级进度推送、支持计划人工修订（后续版本） |

---

## 7. 测试证据附件索引

### 7.1 机器可读证据（tests/）

| 文件 | 说明 |
|---|---|
| acceptance/run_acceptance.py | **60 项**验收用例源码（含 RBAC/META/STAGE/GATE/BID/PROFILE/CERT/MATRIX/AUDIT/ANOMALY/TEMPLATE/APPEAL/GUIDE/ALERT/**MULTI** 与 multipart 上传/SSE 流式消费/证书 OCR 夹具/PG 直连密文断言/多密钥链轮换/审计落库明文负向断言/异常批量解释/范本匹配/异议政采区分/操作阶段识别/弹窗数据契约/**多专家计划-专家数-终稿洁净断言** helper） |
| tests/acceptance/evidence.json | **V2.3 结构化结果（60 条逐条 status/耗时/备注）** |
| tests/test_new_tools.py | 后端 pytest **102 项**（含企业资料占位符回填/跨 chunk 流式、证书 OCR 正则/LLM/存储隔离、对照表校验+缓存、字段加密+掩码、存储抽象、多密钥轮换、S3 Stubber 全链路、R12 审计落库 8 项、R13 异常 catalog 4 项、R14 范本推荐 6 项、R15 异议投诉 8 项、R16 操作引导 9 项） |
| **tests/test_multi_agent.py** | **V2.3 多专家工作流离线 5 项：计划 JSON 解析+非法专家过滤、脏数据/LLM 异常回退、workflow 结构＋Barrier 强制并发上下文＋行级隔离 scope 传播断言、跨专家来源去重** |
| **tests/test_agent_eval_scoring.py** | **V2.3 Agent 评测打分器离线 15 项：事实组 any/all 嵌套、组间等权、工具召回/any 命中、通过线、分类聚合** |
| **tests/test_tool_text_parsing.py** | 伪工具调用文本检测/解析 14 项（V2.3 新增全角 `｜｜DSML｜｜` 变体检测与 invoke/parameter 解析 2 项） |
| acceptance/sample_multipage.pdf | META-01 用 2 页中文 PDF 夹具 |
| eval/retrieval_cases.json | 17 条检索评测用例（招标事实 7/企业 3/法规 7） |
| eval/run_retrieval_eval.py | 纯检索评测脚本（HitRate/漏检/MRR/nDCG/引用准确率/证据覆盖，--topk 可调、--min-hitrate 门禁） |
| **eval/run_retrieval_ablation.py** | **四档检索消融（纯 dense→+BM25→+变体→完整流水线），产出优化前后量化对比 retrieval_ablation_report.json/.md** |
| eval/retrieval_eval_report.json/.md | 检索评测报告（最新 top-K=20 复跑：HitRate=100%/MRR=1.0/nDCG=0.9846） |
| **eval/agent_eval_cases.json** | **V2.3 Agent 端到端基准 12 题（single_hop/multi_hop/cross_domain 各 4，含 tools_any/tools_required/facts 锚点/note）** |
| **eval/run_agent_eval.py** | **V2.3 Agent 端到端 HTTP 评测器（逐题 POST /api/chat，exec_log.tool_calls 提取工具→双指标打分→json/md 报告；--base-url/--timeout/--fact-threshold/--min-pass）** |
| **eval/agent_eval_report.json/.md** | **V2.3 评测报告：11/12 通过、工具选择 1.00、事实覆盖 0.909（单跳4/4、跨域4/4、多跳3/4，E2E-07 gated 波动）** |
| eval/test_page_chunking.py | 按页切分与元数据透传离线测试 |
| eval/test_retrieval_access.py | RAG 召回行级隔离离线测试 |
| eval/test_evidence_gate.py | **硬闸门纯函数离线测试（44 断言，无需 HTTP/LLM）** |
| acceptance/manual_minio_live.py | **V2.2 真实 MinIO 端到端连通手动实测脚本（13 断言，需真实 MinIO server；非自动套件，脚本头部含下载/启动/运行步骤，自动收尾清桶）** |
| **scripts/seed_bidding_procurement.py** | **V2.3 可用性前置：bidding_procurement 建表＋30 条脱敏历史中标种子数据（货物/工程/服务三类，含跨地域对比行），幂等 UPSERT，--reset 重灌；使 PRICE 专家与价格分析可用** |

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
| v14_profile_saved.png | V1.4 企业资料库页（保存成功、5/12 字段、1 项资质证书） |
| v14_bid_tabs.png | V1.4 标书弹窗双 Tab 与"企业资料库（自动回填）"入口 |
| v14_full_matrix.png | V1.4 整本合稿：逐条响应对照表（🟢满足行/★实质性列） |
| v14_matrix_red.png | V1.4 红色"4 项实质性条款不合格（投标前必须整改）"警告框 |
| v14_full_md.png | V1.4 整本 Markdown 预览（封面/目录/章节/附录/待补清单） |
| v14_section_filled.png | V1.4 单章资格响应：公司名/法人/证书编号已写入、无占位符残留 |
| v15_cert_ocr.png | V1.5 证书 OCR：四字段自动填充＋原件缩略图＋OCR 原文展开 |
| v15_cert_saved.png | V1.5 保存企业资料绿色提示 |
| v15_cert_reload.png | V1.5 刷新后证书与缩略图回显 |
| v21_alert_modal.png | V2.1 报价检测 SUM_MISMATCH+CN_MISMATCH 红色主动预警弹窗（条目+查看详情/知道了） |
| v21_no_alert_pass.png | V2.1 总价一致无异常时不弹窗，报价计算表面板"✅ 校验通过" |
| **v23_multi_agent.png** | **V2.3 多专家协作实测：琥珀开关开启态、"多专家协作"徽标、展开的专家过程面板（案例/价格专家 chips＋轮数/耗时/答案，价格专家如实报告历史库数据缺口）** |

### 7.3 复测方法

1. 启动 PostgreSQL、Qdrant，运行后端（首次启动自动回填分片权限，见日志"分片访问权限回填完成"）：
   `.venv\Scripts\python.exe -m uvicorn api.server:app --port 8001`
   - PROFILE-03 需双密钥链环境：PowerShell 下先 `$env:PROFILE_ENC_KEYS="<K1当前>,<K2历史>"`（key 由 `python -m src.tools.field_crypto gen-key` 生成），后端与验收脚本均需带同一环境变量；
   - 证书 S3/MinIO 模式：设置 `CERT_STORAGE_TYPE=s3` 及 `CERT_S3_ENDPOINT/BUCKET/ACCESS_KEY/SECRET_KEY`（配置项见 .env.example，auto_bucket=true 自动建桶）；
2. 全量验收：`.venv\Scripts\python.exe tests/acceptance\run_acceptance.py`（V2.3 起 **60 例约 18-25 分钟**，末位 MULTI-01 单例约 3 分钟；需可用 LLM；产生临时账号/文档）；
3. 离线专项（无需 LLM/HTTP）：
   - `.venv\Scripts\python.exe tests/eval/run_retrieval_eval.py`
   - `.venv\Scripts\python.exe tests/eval/test_retrieval_access.py`
   - `.venv\Scripts\python.exe tests/eval/test_page_chunking.py`
   - `.venv\Scripts\python.exe tests/eval/test_evidence_gate.py`（硬闸门 44 断言）
   - V2.3 新增：`.venv\Scripts\python.exe -m pytest tests/test_multi_agent.py tests/test_agent_eval_scoring.py tests/test_tool_text_parsing.py -q`（34 项，秒级）
4. 标书闭环：浏览器 http://localhost:3000/documents → 文档行钢笔按钮 → 选章节流式生成 → 复制/导出 Word；V1.4 另可访问 http://localhost:3000/profile 维护企业资料库，弹窗内"整本合稿＋响应对照"一键成册；接口侧见 BID-01~06、PROFILE-01 与 4.5b/4.5c。后端单测：`.venv\Scripts\python.exe -m pytest tests/test_new_tools.py -q`（**102 项**）；审计查询：admin/auditor 登录后 `GET /api/audit/logs?user_id=<uid>&action=profile.update`；异常解释：`POST /api/anomaly/explain {"code":"OVER_CONTROL_PRICE"}`；范本推荐：`POST /api/templates/recommend {"query":"工程施工"}`（V1.9 新增，均无需登录）。
5. 浏览器：frontend 目录 `npm run dev` 后访问 http://localhost:3000/documents，按 4.6 节路径复测。
6. **V2.2 真实 MinIO 连通复测（手动，约 3 分钟，无需 LLM/后端/PG）**：
   - 获取二进制（开源 server 已从 dl.min.io 归档，用 GitHub Releases 归档版本）：https://github.com/minio/minio/releases/tag/RELEASE.2025-09-07T16-13-09Z 下载 `minio.windows-amd64.*.exe`；
   - 启动：`$env:MINIO_ROOT_USER="minioadmin"; $env:MINIO_ROOT_PASSWORD="minioadmin"; minio.exe server <数据目录> --address ":9000" --console-address ":9001"`（health: http://127.0.0.1:9000/minio/health/live）；
   - 执行：`.venv\Scripts\python.exe tests/acceptance/manual_minio_live.py`，预期末行 `13/13 PASS`；脚本自行设置 CERT_S3_* 环境变量并在结束时清空删除测试桶，无需改 .env。
7. **V2.3 Agent 端到端评测复跑（需后端＋LLM，约 5-7 分钟）**：确认 /api/health ready 后执行 `.venv\Scripts\python.exe tests/eval/run_agent_eval.py`（12 题逐题打 /api/chat，默认超时 280s/题；可用 `--base-url/--timeout/--fact-threshold/--min-pass`），末行打印通过率并生成 tests/eval/agent_eval_report.json/.md；注意 LLM/检索波动会使个别题（当前观测为 E2E-07）在 gated 拒答与通过间波动，**不得修改题集事实锚点凑分**，扩库后需同步更新锚点。
8. **V2.3 多专家协作复测**：接口侧 POST /api/multi-agent/run `{"question": "...跨域问题...", "deep_thinking": false}`（非流式，约 1-4 分钟，返回 plan/expert_results/final_answer/sources）；UI 侧首页打开"多专家协作"琥珀开关后发问，验证徽标＋可折叠专家过程面板＋终稿＋来源（参考 4.6 v23_multi_agent.png）。
