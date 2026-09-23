"""混合 SFT 数据集 + 通用样本 + 去重 + 切分 train/val。

用法:
    python scripts/sft/merge_dataset.py

输入: sft_domain.json + sft_toolcall.json
输出: sft_train.json + sft_val.json (95:5 切分)
"""
import json
import random
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
random.seed(42)

# 50 条通用对话样本 (保泛化)
GENERAL_QA = [
    {"conversations": [
        {"from": "human", "value": "你好"},
        {"from": "gpt", "value": "您好！我是招投标智能问答助手，可以为您解答招投标、政府采购相关的问题。请问有什么可以帮您的？"},
    ]},
    {"conversations": [
        {"from": "human", "value": "你是谁？"},
        {"from": "gpt", "value": "我是招投标智能问答助手，专门回答招投标和政府采购领域的问题。您可以向我咨询招投标流程、法规条文、招标文件内容等问题。"},
    ]},
    {"conversations": [
        {"from": "human", "value": "你能做什么？"},
        {"from": "gpt", "value": "我可以帮您：\n1. 查询招投标法规条文和流程\n2. 检索已入库的招标文件内容\n3. 查询知识图谱中的采购关系\n4. 统计采购数据\n5. 生成投标书章节草稿\n请问您需要什么帮助？"},
    ]},
    {"conversations": [
        {"from": "human", "value": "谢谢"},
        {"from": "gpt", "value": "不客气！如果您还有其他招投标相关问题，随时可以问我。"},
    ]},
    {"conversations": [
        {"from": "human", "value": "再见"},
        {"from": "gpt", "value": "再见！祝您工作顺利。如果以后有招投标问题，随时欢迎咨询。"},
    ]},
]


def main():
    all_items = []

    # 加载知识 Q&A
    domain_path = OUT_DIR / "sft_domain.json"
    if domain_path.exists():
        with open(domain_path, "r", encoding="utf-8") as f:
            domain = json.load(f)
        print(f"加载 sft_domain.json: {len(domain)} 条")
        all_items.extend(domain)
    else:
        print("sft_domain.json 不存在 (跳过)")

    # 加载工具调用轨迹
    toolcall_path = OUT_DIR / "sft_toolcall.json"
    if toolcall_path.exists():
        with open(toolcall_path, "r", encoding="utf-8") as f:
            toolcall = json.load(f)
        print(f"加载 sft_toolcall.json: {len(toolcall)} 条")
        all_items.extend(toolcall)
    else:
        print("sft_toolcall.json 不存在 (跳过)")

    # 追加通用样本
    all_items.extend(GENERAL_QA * 10)  # 复制 10 份 = 50 条
    print(f"追加通用样本: {len(GENERAL_QA) * 10} 条")

    # 去重 (按 human 的第一轮 question)
    seen = set()
    deduped = []
    for item in all_items:
        convs = item.get("conversations", [])
        if not convs:
            continue
        # 找到第一条 human 消息作为去重 key
        key = None
        for c in convs:
            if c["from"] == "human":
                key = c["value"][:100]
                break
        if key and key not in seen:
            seen.add(key)
            deduped.append(item)

    print(f"去重后: {len(deduped)} 条")

    # 打乱 + 切分
    random.shuffle(deduped)
    split = int(len(deduped) * 0.95)
    train = deduped[:split]
    val = deduped[split:]

    # 写出
    train_path = OUT_DIR / "sft_train.json"
    val_path = OUT_DIR / "sft_val.json"
    with open(train_path, "w", encoding="utf-8") as f:
        json.dump(train, f, ensure_ascii=False, indent=2)
    with open(val_path, "w", encoding="utf-8") as f:
        json.dump(val, f, ensure_ascii=False, indent=2)

    print(f"\n输出:")
    print(f"  sft_train.json: {len(train)} 条")
    print(f"  sft_val.json:   {len(val)} 条")


if __name__ == "__main__":
    main()
