"""写入 README.md"""
from pathlib import Path

CONTENT = r'''# Bidding QA Chatbot · 招投标智能问答机器人

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
- **回答反馈**：👍/👎 存入数据库，用于优化策略
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
