from __future__ import annotations
"""常量 + 基础工具集"""
MAX_HISTORY_ROUNDS = 5
MAX_TOOL_ROUNDS = 4
MAX_TOKENS_DEEP = 8192
STREAM_FLUSH_CHARS = 80
STREAM_CHUNK_CHARS = 40
STREAM_CHUNK_DELAY = 0.02

BASE_TOOL_NAMES = ["search_bidding_knowledge", "search_knowledge_graph",
                   "search_postgresql", "list_bid_documents", "generate_bid_draft"]
WEB_TOOL_NAMES = ["search_web", "search_exa"]
