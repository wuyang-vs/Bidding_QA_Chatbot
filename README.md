# Bidding QA Chatbot · 招投标智能问答机器人

基于 **RAG + 知识图谱 + 结构化数据库 + 联网搜索** 的招投标领域智能问答系统。使用 ReAct 多轮推理的 Agent 自动选择工具，支持流式输出、深度思考、图片解析、对话持久化。

---

## ✨ 功能特性

### 智能问答
- **RAG 混合检索**：Qdrant 向量库（Dense BGE + Sparse BM25）+ RRF 融合 + CrossEncoder 精排
- **知识图谱查询**：Neo4j 星型图谱，标的物 / 采购人 / 供应商 / 代理机构关系
- **结构化查询**：PostgreSQL 金额统计、时间范围、排名、分组聚合
- **联网搜索**：Tavily 关键词搜索 + Exa 语义搜索（未就绪时自动降级）
- **ReAct 多轮推理**：最多 4 轮工具调用，基于中间结果决定是否补查
- **工具文本防泄漏**：拦截 `<tool_call>` / JSON / DSML 格式的工具文本泄漏

### 交互体验
- **SSE 流式输出**：逐字返回，用户无需等待完整生成
- **深度思考模式**：推理模型优先，无则提示词注入回退
- **思考过程可视化**：可折叠的紫色思考块
- **图片解析**：上传图片，智谱 glm-4.6v-flashx 解析内容
- **多 LLM 切换**：DeepSeek / 智谱 AI / vLLM / Ollama
- **对话持久化**：PostgreSQL 存储会话，支持跨会话恢复、搜索、删除
- **回答反馈**：👍/👎 存入数据库
- **暗色模式**：跟随系统 + 手动切换 + localStorage 持久化
- **移动端适配**：汉堡菜单、抽屉式侧栏

### 工程化
- **FastAPI + SSE**：11 个 REST 端点 + 流式对话
- **Next.js 14**：App Router + TypeScript + Tailwind CSS
- **Pytest**：30 个单元测试
- **CI**：GitHub Actions 自动测试
- **限流**：滑动窗口 30 req / 60s / IP
- **评测脚本**：RAG 质量（LLM-as-Judge）+ Agent 端到端 + 运行看板

---

## 🏗️ 项目结构

```
Bidding_QA_Chatbot/
├── main.py                    # CLI 入口: ingest / api / dev
├── pyproject.toml             # 依赖声明（uv 管理）
├── conftest.py                # pytest 根配置
├── .env.example               # 环境变量模板
│
├── api/
│   └── server.py              # FastAPI 端点 + 限流 + lifespan 初始化
│
├── src/
│   ├── config.py              # Settings dataclass
│   ├── logging_config.py      # 统一日志
│   ├── http_client.py         # 出站 HTTP（不继承系统代理）
│   ├── rate_limiter.py        # 滑动窗口限流
│   ├── web_search.py          # Tavily 客户端
│   │
│   ├── agent/                 # Agent 核心
│   │   ├── core.py            #   BiddingAgent 主体
│   │   ├── react_loop.py      #   ReAct 多轮工具循环
│   │   ├── generation.py      #   最终生成 / 深度思考 / RAG 降级
│   │   ├── tool_defense.py    #   工具文本检测与解析
│   │   ├── skills.py          #   技能加载与匹配
│   │   ├── prompts.py         #   系统提示词
│   │   ├── constants.py       #   常量
│   │   └── utils.py           #   SSE 构造 / 分帧 / 历史截断
│   │
│   ├── rag/                   # RAG 检索
│   │   ├── pipeline.py        #   检索 + 精排 + 生成
│   │   ├── vector_store.py    #   Qdrant 混合检索 + 问题分类
│   │   ├── embedder.py        #   BGE Dense + jieba BM25 + CrossEncoder
│   │   └── ingest.py          #   Excel → Qdrant 导入
│   │
│   ├── clients/               # LLM 客户端
│   │   ├── base_client.py
│   │   ├── deepseek_client.py
│   │   ├── zhipu_client.py
│   │   ├── openai_compatible_client.py   # vLLM / Ollama
│   │   ├── vision_client.py
│   │   └── llm_factory.py
│   │
│   ├── tools/
│   │   ├── base.py            #   BaseTool + ToolRunner
│   │   └── rag_tools.py       #   4 类工具 + 格式化 + 联网重排
│   │
│   ├── database/
│   │   ├── neo4j_client.py    #   图谱查询
│   │   └── postgresql_client.py  # 结构化查询 + 会话/反馈 CRUD
│   │
│   ├── mcp/
│   │   ├── mcp_client.py      #   stdio JSON-RPC 2.0 客户端
│   │   └── web_search_exa.py  #   Exa MCP 封装
│   │
│   └── skills/                # 技能 SKILL.md
│       ├── bid-analysis/
│       └── debug-answer/
│
├── frontend/                  # Next.js 14 前端
│   ├── app/
│   │   ├── page.tsx           #   主页面 + SSE 状态机
│   │   ├── layout.tsx
│   │   └── globals.css
│   ├── components/
│   │   ├── ChatInput.tsx
│   │   ├── ChatMessage.tsx
│   │   ├── ChatContainer.tsx
│   │   ├── Sidebar.tsx
│   │   └── SourceCard.tsx
│   └── lib/api.ts
│
├── tests/                     # pytest 30 例
├── eval/                      # 评测脚本
│   ├── ragas_eval.py
│   ├── agent_eval.py
│   ├── dashboard.py
│   ├── test_questions.json
│   └── test_cases.json
│
├── batch/                     # 数据处理脚本
│   ├── 去重.py
│   ├── 提数据_编JSONL.py
│   ├── 按custom_id排序.py
│   ├── 提数据_插标的物.py
│   └── 统计数据_插交易频次.py
│
└── data/                      # 数据目录
    ├── raw/
    ├── processed/
    ├── batch/
    └── vocab.json
```

---

## 🚀 快速开始

### 环境要求
- **Python** ≥ 3.12
- **Node.js** ≥ 18
- **uv**（Python 包管理）
- **Qdrant** 实例（Cloud 或自建）
- **DeepSeek API Key**

### 1. 克隆仓库

```bash
git clone https://github.com/wuyang-vs/Bidding_QA_Chatbot.git
cd Bidding_QA_Chatbot
```

### 2. 安装后端依赖

```bash
uv sync
```

如需运行测试：

```bash
uv sync --extra dev
```

### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，至少填写：

```bash
QDRANT_URL=https://xxx.cloud.qdrant.io:6333
QDRANT_API_KEY=xxx
DEEPSEEK_API_KEY=sk-xxx
HF_ENDPOINT=https://hf-mirror.com
```

### 4. 导入知识库

把 Q&A Excel 放到 `data/` 目录（列名：`问/答` 或 `question/answer`），然后：

```bash
python main.py ingest
```

首次运行会下载 BGE 嵌入模型和 CrossEncoder 精排模型。

### 5. 启动后端

```bash
python main.py api
```

访问 http://localhost:8001/docs 查看 API 文档。

### 6. 启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:3000

---

## ⚙️ 配置项

`.env` 关键配置（完整见 `.env.example`）：

| 分组 | 键 | 默认值 | 说明 |
|---|---|---|---|
| **必需** | `QDRANT_URL` / `QDRANT_API_KEY` | — | Qdrant 连接 |
| | `DEEPSEEK_API_KEY` | — | 默认 LLM |
| LLM | `LLM_PROVIDER` | `deepseek` | `deepseek` / `zhipu` / `vllm` / `ollama` |
| | `DEEPSEEK_MODEL` | `deepseek-v4-flash` | 文本模型 |
| | `DEEPSEEK_THINKING_MODEL` | 空 | 深度思考推理模型 |
| | `ZHIPU_API_KEY` / `ZHIPU_MODEL` | — / `glm-4.7-flashx` | 智谱 |
| 本地模型 | `VLLM_BASE_URL` / `VLLM_MODEL` | `http://localhost:8001/v1` / `deepseek-r1-0528-qwen3-8b` | vLLM |
| | `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434/v1` / `deepseek-r1:8b` | Ollama |
| 图谱 | `NEO4J_URI` / `NEO4J_USERNAME` / `NEO4J_PASSWORD` | `neo4j://127.0.0.1:7687` / `neo4j` / — | 未连接时降级 |
| 数据库 | `POSTGRES_*` | `localhost:5432` / `postgres` / `chatbot` | 未连接时降级 |
| 联网 | `TAVILY_API_KEY` | — | Tavily 关键词搜索 |
| | `EXA_API_KEY` | — | Exa 语义搜索（可选） |
| API | `API_HOST` / `API_PORT` | `0.0.0.0` / `8001` | 监听地址 |
| | `CORS_ORIGINS` | 空 | 逗号分隔白名单，`*` 允许所有 |

---

## 🔌 API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/chat/stream` | SSE 流式对话（推荐） |
| POST | `/api/chat` | 非流式对话 |
| POST | `/api/ask` | 直接 RAG（不走 Agent） |
| POST | `/api/vision` | 图片解析 |
| POST | `/api/conversations` | 保存会话 |
| GET | `/api/conversations` | 列出会话（支持 `?q=` 搜索） |
| GET | `/api/conversations/{id}` | 加载会话 |
| DELETE | `/api/conversations` | 删除所有会话 |
| DELETE | `/api/conversations/{id}` | 删除单个会话 |
| POST | `/api/feedback` | 保存反馈（`up` / `down`） |
| GET | `/api/health` | 健康检查（30s 缓存） |

### SSE 事件类型

| 事件 | 字段 | 说明 |
|---|---|---|
| `status` | `content` | 阶段提示 |
| `token` | `content` | 正文增量 |
| `thinking` | `content` | 思考增量（仅深度思考） |
| `reset` | — | 检出工具文本泄漏时清空前端重试 |
| `done` | `sources` / `web_sources` / `tool_name` / `elapsed_ms` | 结束帧 |
| `error` | `content` | 错误信息 |

---

## 🧪 测试

```bash
uv run pytest -q
```

30 个用例覆盖：限流 / 问题分类 / 格式化函数 / 工具文本解析 / SSE 事件。

---

## 📊 评测

```bash
python eval/ragas_eval.py
python eval/agent_eval.py
python eval/dashboard.py
```

---

## 🔧 核心算法

### RAG 检索链路

```
用户问题
  ├─ ① 问题分类 → keyword / concept / mixed（决定 RRF k 值）
  ├─ ② 双路编码 → Dense (BGE 512维) + Sparse (BM25)
  ├─ ③ Qdrant 混合召回 → Prefetch 双路各 30 条 + RRF 融合
  ├─ ④ CrossEncoder 精排 → 召回结果重打分取 top-k
  └─ ⑤ LRU 缓存 → (question, top_k) → 结果，128 条
```

### ReAct 多轮循环

```
第 1 轮：LLM + tools → 工具调用 / 直接回答 / 文本工具兜底
第 2-4 轮：观察结果，决定补查或回答
达到 4 轮上限：强制基于已有结果生成
```

---

## 📦 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn + Pydantic |
| LLM | DeepSeek / 智谱 GLM / vLLM / Ollama |
| 嵌入模型 | BAAI/bge-small-zh-v1.5（512 维） |
| 精排模型 | BAAI/bge-reranker-base |
| 向量库 | Qdrant（Named Vectors + RRF） |
| 图数据库 | Neo4j 5.3+ |
| 关系数据库 | PostgreSQL + SQLAlchemy + psycopg |
| 联网 | Tavily + Exa MCP |
| 前端 | Next.js 14 + React 18 + TypeScript + Tailwind |
| 测试 | pytest |

---

## 🛠️ 常见问题

**Q: 启动报“缺少必需配置”？**
检查 `.env` 中 `QDRANT_URL`、`QDRANT_API_KEY`、`DEEPSEEK_API_KEY` 是否填写。

**Q: 首次问答很慢？**
首次使用会下载 BGE / CrossEncoder 模型，国内建议设置 `HF_ENDPOINT=https://hf-mirror.com`。

**Q: 知识库检索为空？**
确认已执行 `python main.py ingest`，且 `data/vocab.json` 存在。

**Q: 前端流式失效（整段一次显示）？**
生产环境 SSE 不能走会缓冲的反向代理。设置 `NEXT_PUBLIC_API_BASE` 直连后端。

**Q: `git clone` 报 SSL 错误？**
```bash
git config --global http.sslBackend openssl
```

---

## 📄 License

MIT

---

## 🙏 致谢

- [Qdrant](https://qdrant.tech/) — 向量数据库
- [Neo4j](https://neo4j.com/) — 图数据库
- [DeepSeek](https://platform.deepseek.com/) / [智谱 AI](https://open.bigmodel.cn/) — LLM
- [BAAI](https://huggingface.co/BAAI) — 嵌入与精排模型
- [Tavily](https://tavily.com/) / [Exa](https://exa.ai/) — 联网搜索