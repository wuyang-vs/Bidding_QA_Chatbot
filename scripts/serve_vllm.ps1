# -*- coding: utf-8 -*-
<#
.SYNOPSIS
    本地 vLLM (OpenAI 兼容) 服务一键启停 — 架构优化建议 #11 本地模型部署.
.DESCRIPTION
    通过 Docker (GPU 直通 WSL2 后端) 运行 vllm/vllm-openai, 模型使用本地目录
    (ModelScope 拉取, 离线挂载), 服务监听 http://localhost:8001/v1.
    项目侧 .env: LLM_PROVIDER=vllm, VLLM_MODEL 与 -ServedName 一致.
    模型拉取(二选一):
      git clone https://www.modelscope.cn/Qwen/Qwen2.5-3B-Instruct-AWQ.git
    注: 本机全局 git 代理失效导致 git-lfs 权重拉取挂起时, 改用 ModelScope 文件
    直链 (repo?FilePath=model.safetensors) 分片下载, 校验 2686704624 字节即可.
.EXAMPLE
    powershell -File scripts\serve_vllm.ps1 start
    powershell -File scripts\serve_vllm.ps1 start -MaxModelLen 16384 -GpuMemFraction 0.92
    powershell -File scripts\serve_vllm.ps1 status / logs / stop
#>
param(
    [Parameter(Position = 0)]
    [ValidateSet("start", "stop", "status", "logs")]
    [string]$Action = "start",

    # 宿主机模型目录 (挂载到容器 /model, vLLM 以本地路径加载, 不联网)
    [string]$ModelDir = "D:\ai_models\modelscope\Qwen2.5-3B-Instruct-AWQ",
    [string]$ServedName = "qwen2.5-3b-awq",
    [string]$ImageTag = "latest",
    [int]$Port = 8001,
    [double]$GpuMemFraction = 0.90,
    [int]$MaxModelLen = 8192,
    [string]$ContainerName = "vllm-local"
)

$ErrorActionPreference = "Stop"

function Get-Container {
    docker ps -a --filter "name=^/$ContainerName$" --format "{{.ID}} {{.Status}}" 2>$null
}

switch ($Action) {
    "status" {
        $line = Get-Container
        if (-not $line) { Write-Output "vLLM 容器不存在"; exit 0 }
        Write-Output "容器: $line"
        try {
            $r = Invoke-RestMethod -Uri "http://localhost:$Port/v1/models" -TimeoutSec 3 -Proxy $null
            Write-Output "服务就绪, served models:"
            $r.data | ForEach-Object { Write-Output "  - $($_.id)" }
        } catch {
            Write-Output "API 未就绪 (容器可能仍在加载模型, 用 logs 查看进度)"
        }
        exit 0
    }
    "logs" {
        docker logs -f --tail 100 $ContainerName
        exit 0
    }
    "stop" {
        if (Get-Container) {
            docker rm -f $ContainerName | Out-Null
            Write-Output "已停止并移除容器 $ContainerName"
        } else {
            Write-Output "容器不存在, 无需停止"
        }
        exit 0
    }
    "start" {
        if (Get-Container) {
            Write-Error "容器 $ContainerName 已存在, 请先执行: scripts\serve_vllm.ps1 stop"
            exit 1
        }
        if (-not (Test-Path (Join-Path $ModelDir "config.json"))) {
            Write-Error "模型目录无效(缺 config.json): $ModelDir`n" `
                "拉取: git clone https://www.modelscope.cn/Qwen/Qwen2.5-3B-Instruct-AWQ.git $ModelDir"
            exit 1
        }

        Write-Output "启动 vLLM: model_dir=$ModelDir served=$ServedName port=$Port " `
            "gpu_mem=$GpuMemFraction max_len=$MaxModelLen"
        docker run -d --name $ContainerName --gpus all --ipc host `
            -p "${Port}:8000" `
            -v "${ModelDir}:/model:ro" `
            -e HF_HUB_OFFLINE=1 `
            -e VLLM_NO_USAGE_STATS=1 `
            --restart unless-stopped `
            "vllm/vllm-openai:$ImageTag" `
            --model /model `
            --served-model-name $ServedName `
            --gpu-memory-utilization $GpuMemFraction `
            --max-model-len $MaxModelLen `
            --dtype float16 `
            --trust-remote-code | Out-Null

        Write-Output "容器已创建, 等待 API 就绪 (首次加载模型约 1-3 分钟)..."
        $deadline = (Get-Date).AddMinutes(5)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Seconds 5
            try {
                $r = Invoke-RestMethod -Uri "http://localhost:$Port/v1/models" -TimeoutSec 3 -Proxy $null
                Write-Output "vLLM 服务就绪: http://localhost:$Port/v1 (model=$($r.data[0].id))"
                Write-Output "项目接入: .env 设 LLM_PROVIDER=vllm, VLLM_MODEL=$ServedName"
                exit 0
            } catch {
                $line = Get-Container
                if ($line -notmatch "Up") {
                    Write-Error "容器已退出, 最近日志:"
                    docker logs --tail 40 $ContainerName
                    exit 1
                }
            }
        }
        Write-Error "5 分钟内 API 未就绪, 请查日志: scripts\serve_vllm.ps1 logs"
        exit 1
    }
}
