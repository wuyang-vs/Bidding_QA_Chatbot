#!/bin/bash
# 服务器侧: 上传 SFT 数据 + 训练
# 用法: 在本地执行 bash scripts/sft/upload_and_train.sh
set -e

echo "=== 1. 上传数据到服务器 ==="
ssh aliyun "mkdir -p ~/sft"
scp scripts/sft/sft_train.json scripts/sft/sft_val.json scripts/sft/dataset_info.json scripts/sft/glm4_lora.yaml aliyun:~/sft/
echo "上传完成"

echo "=== 2. 停止 vLLM 释放显存 ==="
ssh aliyun "docker stop vllm-glm4 2>/dev/null || true"
echo "vLLM 已停止"

echo "=== 3. 检查显存 ==="
ssh aliyun "nvidia-smi --query-gpu=memory.total,memory.used,memory.free --format=csv"

echo "=== 4. 启动训练 ==="
ssh aliyun "source ~/lf_venv/bin/activate && cd ~/sft && nohup llamafactory-cli train glm4_lora.yaml > train.log 2>&1 &"
echo "训练已启动, 日志: ~/sft/train.log"
echo "查看训练进度: ssh aliyun 'tail -f ~/sft/train.log'"
