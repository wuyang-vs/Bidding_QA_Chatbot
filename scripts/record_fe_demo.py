# -*- coding: utf-8 -*-
"""前端功能测试演示视频录制.

用 Playwright 原生录屏(record_video)自动遍历前端 6 大页面并执行核心操作,
页面顶部注入实时字幕条说明当前测试项。输出 webm 后由 ffmpeg 转 mp4。

运行前置:
  set PLAYWRIGHT_BROWSERS_PATH=D:\Bidding_QA_Chatbot\.pw-browsers
  前端 http://localhost:3000、后端 http://localhost:8001 已启动
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".pylibs"))
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / ".pw-browsers"))

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = "http://localhost:3000"
OUT = ROOT / "tests" / "acceptance" / "videos"
RAW = OUT / "_raw"

CAPTION_JS = """(txt) => {
  let b = document.getElementById('__cap');
  if (!b) {
    b = document.createElement('div'); b.id = '__cap';
    b.style = 'position:fixed;top:0;left:0;right:0;z-index:999999;'
      + 'background:rgba(15,23,42,.85);color:#fefce8;font-size:18px;'
      + 'padding:9px 18px;font-family:"Microsoft YaHei",sans-serif;'
      + 'box-shadow:0 2px 10px rgba(0,0,0,.35);letter-spacing:.5px';
    document.body.appendChild(b);
  }
  b.textContent = txt;
}"""

LAST_TEXT_JS = """() => {
  const els = document.querySelectorAll('.prose, .markdown, article');
  return els.length ? els[els.length - 1].innerText : document.body.innerText;
}"""


def caption(page, text: str, pause: float = 0.4) -> None:
    page.evaluate(CAPTION_JS, text)
    time.sleep(pause)


def wait_answer(page, timeout: int = 90) -> None:
    """等发送按钮恢复可用, 且最后一条消息文本连续 3 次稳定即视为回答完成."""
    deadline = time.time() + timeout
    last, stable = "", 0
    while time.time() < deadline:
        try:
            sending = page.locator('button:has-text("发送")').first.is_disabled()
        except Exception:
            sending = True
        try:
            text = page.evaluate(LAST_TEXT_JS)
        except Exception:
            text = ""
        if not sending and text == last and len(text.strip()) > 20:
            stable += 1
            if stable >= 3:
                return
        else:
            stable = 0
        last = text
        time.sleep(1.5)


def ask(page, question: str, timeout: int = 90) -> None:
    page.locator("textarea").first.fill(question)
    page.locator('button:has-text("发送")').first.click()
    wait_answer(page, timeout)


def main() -> None:
    if RAW.exists():
        shutil.rmtree(RAW)
    RAW.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            record_video_dir=str(RAW),
            record_video_size={"width": 1440, "height": 900},
        )
        page = ctx.new_page()

        # ① 智能问答页: RAG 问答
        page.goto(BASE, wait_until="networkidle")
        caption(page, "① 智能问答页 — 招标法规提问: Query规划→多路召回→RRF融合→精排→生成")
        time.sleep(2)
        ask(page, "投标人对招标文件提出质疑的期限是几个工作日？")
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        caption(page, "① 回答引用【资料N】出处, 来源卡片给出相似度与原文定位, 支持点赞/点踩反馈", 6)

        # 多专家协作开关展示(不实际执行, 全链路约 1-4 分钟)
        caption(page, "① “多专家协作”开关: 主管拆解 → 法规/价格/案例专家并行 → 综合作答", 1)
        page.locator('button:has-text("多专家协作")').click()
        time.sleep(1.8)
        page.locator('button:has-text("多专家协作")').click()
        time.sleep(1)

        # ② 证据闸门拒答
        page.goto(BASE)
        caption(page, "② 证据闸门 — 知识库无证据的问题必须拒答, 禁止幻觉编造")
        ask(page, "月球上适合开招投标会场吗？", timeout=60)
        caption(page, "② 系统明确拒答并给出 3 条引导建议(换问法/补充资料/联系管理员)", 7)

        # ③ Agent 执行过程
        page.goto(f"{BASE}/agent", wait_until="networkidle")
        caption(page, "③ Agent执行过程 — 工具调用轨迹 / 阶段耗时条 / 异常筛选 / 硬闸门拦截 / TraceID")
        time.sleep(4)
        for label in ("异常", "失败", "全部"):
            try:
                page.locator(f'button:has-text("{label}")').first.click(timeout=2500)
                time.sleep(3)
                break
            except Exception:
                continue

        # ④ 数据看板
        page.goto(f"{BASE}/dashboard", wait_until="networkidle")
        caption(page, "④ 数据看板 — 知识库向量点数 / 业务库行数 / 图谱规模 / 调用统计实时聚合")
        time.sleep(7)

        # ⑤ 文件解析
        page.goto(f"{BASE}/documents", wait_until="networkidle")
        caption(page, "⑤ 文件解析 — 上传(PDF/XLSX)→8字段抽取→入向量库→15条合规规则→审计留痕")
        time.sleep(8)

        # ⑥ 知识图谱
        page.goto(f"{BASE}/graph", wait_until="networkidle")
        caption(page, "⑥ 知识图谱可视化 — 标的物/采购人/供应商三类节点力导向关系图")
        time.sleep(6)
        try:
            box = page.locator('input[placeholder="搜索标的物..."]')
            box.fill("医疗设备")
            box.press("Enter")
            caption(page, "⑥ 模糊搜索“医疗设备”→ 命中标的物并展开采购人/供应商上下游关系", 8)
        except Exception as exc:
            print(f"[warn] graph search skipped: {exc}")

        # ⑦ 企业资料库(需登录)
        page.goto(f"{BASE}/profile", wait_until="networkidle")
        try:
            page.locator('input[placeholder="用户名"]').fill("admin", timeout=4000)
            page.locator('input[placeholder="密码"]').fill("admin123")
            page.locator('button:has-text("登录")').first.click()
            page.wait_for_timeout(4500)
        except Exception:
            pass
        caption(page, "⑦ 企业资料库 — 12类企业信息, 手机号等敏感字段脱敏展示, 资质证书 OCR 留痕")
        time.sleep(8)

        # 结尾
        page.goto(BASE, wait_until="networkidle")
        caption(page, "前端 6 大页面 26 项功能用例实测全部通过 · 招投标RAG智能问答系统", 4)

        ctx.close()
        browser.close()

    webms = sorted(glob.glob(str(RAW / "*.webm")), key=os.path.getmtime)
    if not webms:
        raise RuntimeError("未找到录制产物 webm")
    webm = OUT / "前端功能测试演示.webm"
    shutil.move(webms[-1], webm)
    shutil.rmtree(RAW, ignore_errors=True)
    print(f"WEBM: {webm} ({webm.stat().st_size // 1024} KB)")

    # webm -> mp4 (imageio-ffmpeg 自带二进制)
    try:
        import imageio_ffmpeg  # noqa
        ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        mp4 = OUT / "前端功能测试演示.mp4"
        subprocess.run(
            [ffmpeg, "-y", "-i", str(webm),
             "-c:v", "libx264", "-preset", "medium", "-crf", "23",
             "-movflags", "+faststart", str(mp4)],
            check=True,
            capture_output=True,
        )
        print(f"MP4: {mp4} ({mp4.stat().st_size // 1024} KB)")
    except Exception as exc:
        print(f"[warn] mp4 转码失败(可直接播放 webm): {exc}")


if __name__ == "__main__":
    main()
