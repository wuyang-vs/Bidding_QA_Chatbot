# -*- coding: utf-8 -*-
"""前端功能全量测试报告 PPT 生成 (基于 2026-09-20 浏览器自动化实测).

运行: .venv\\Scripts\\python.exe scripts\\gen_fe_test_ppt.py
输出: 前端功能测试报告.pptx
"""
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "tests" / "acceptance" / "screenshots"
OUT = ROOT / "前端功能测试报告.pptx"

PRIMARY = RGBColor(0x1F, 0x4E, 0x79)
GREEN = RGBColor(0x2E, 0x8B, 0x6E)
RED = RGBColor(0xC0, 0x39, 0x2B)
GOLD = RGBColor(0xB9, 0x8A, 0x2F)
LIGHT = RGBColor(0xEF, 0xF4, 0xF8)
GRAY = RGBColor(0x60, 0x60, 0x60)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)


def _set_text(tf, lines, valign=None):
    tf.word_wrap = True
    if valign:
        tf.vertical_anchor = valign
    for i, (txt, kw) in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = txt
        p.alignment = kw.get("align", PP_ALIGN.LEFT)
        p.space_after = Pt(kw.get("space_after", 4))
        for r in p.runs:
            r.font.size = Pt(kw.get("size", 14))
            r.font.bold = kw.get("bold", False)
            r.font.color.rgb = kw.get("color", RGBColor(0x22, 0x22, 0x22))
            r.font.name = "Microsoft YaHei"


def add_text(slide, x, y, w, h, lines, valign=None):
    tb = slide.shapes.add_textbox(x, y, w, h)
    _set_text(tb.text_frame, lines, valign)
    return tb


def add_box(slide, x, y, w, h, fill=LIGHT, line=None, round_=True):
    shp = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE, x, y, w, h)
    shp.fill.solid()
    shp.fill.fore_color.rgb = fill
    if line:
        shp.line.color.rgb = line
        shp.line.width = Pt(1)
    else:
        shp.line.fill.background()
    shp.shadow.inherit = False
    return shp


def slide_base(prs, title):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_box(slide, 0, 0, Inches(13.333), Inches(0.72), fill=PRIMARY, round_=False)
    add_text(slide, Inches(0.4), Inches(0.08), Inches(12.5), Inches(0.56),
             [(title, {"size": 20, "bold": True, "color": WHITE})])
    return slide


def add_image_fit(slide, path, x, y, max_w, max_h):
    from PIL import Image
    with Image.open(path) as im:
        iw, ih = im.size
    scale = min(max_w / iw, max_h / ih)
    w, h = int(iw * scale), int(ih * scale)
    px, py = int(x + (max_w - w) / 2), int(y + (max_h - h) / 2)
    pic = slide.shapes.add_picture(str(path), px, py, w, h)
    pic.line.color.rgb = RGBColor(0xBD, 0xBD, 0xBD)
    pic.line.width = Pt(0.75)
    return pic, px, py, w, h


def table_rows(slide, x, y, w, rows, col_ratio, header_fill=PRIMARY, size=11):
    n = len(rows)
    tbl_shape = slide.shapes.add_table(n, len(col_ratio), x, y, w, Inches(0.32 * n))
    tbl = tbl_shape.table
    total = sum(col_ratio)
    for j, r_ in enumerate(col_ratio):
        tbl.columns[j].width = int(w * r_ / total)
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            c = tbl.cell(i, j)
            c.margin_left, c.margin_right = Pt(4), Pt(4)
            c.margin_top, c.margin_bottom = Pt(1), Pt(1)
            _set_text(c.text_frame, [(str(cell), {
                "size": size, "bold": i == 0,
                "color": WHITE if i == 0 else RGBColor(0x22, 0x22, 0x22)})])
            if i == 0:
                c.fill.solid()
                c.fill.fore_color.rgb = header_fill
            elif i % 2 == 0:
                c.fill.solid()
                c.fill.fore_color.rgb = LIGHT
    return tbl


def s_cover(prs):
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    add_box(slide, 0, 0, Inches(13.333), Inches(7.5), fill=PRIMARY, round_=False)
    add_text(slide, Inches(1), Inches(2.1), Inches(11.3), Inches(1.2),
             [("前端功能全量测试报告", {"size": 40, "bold": True, "color": WHITE})])
    add_text(slide, Inches(1), Inches(3.3), Inches(11.3), Inches(0.6),
             [("招投标智能问答系统 · 6 大页面 38 项功能 · 浏览器自动化实测",
               {"size": 18, "color": RGBColor(0xCF, 0xE2, 0xF3)})])
    add_box(slide, Inches(1), Inches(4.3), Inches(11.3), Inches(1.7),
            fill=RGBColor(0x16, 0x3A, 0x5C))
    add_text(slide, Inches(1.3), Inches(4.5), Inches(10.8), Inches(1.4), [
        ("测试日期: 2026-09-20    方式: 真实浏览器端到端操作 (非 Mock)", {"size": 14, "color": WHITE}),
        ("结果: 26 项核心功能通过 · 12 项入口验证 · 发现并修复 4 个缺陷",
         {"size": 14, "color": WHITE, "space_after": 8}),
    ])


def s_summary(prs):
    slide = slide_base(prs, "一、测试结论总览")
    rows = [
        ("页面", "测试项", "结果", "关键验证点"),
        ("对话页", "提问/SSE 流式/引用标注/来源卡片/多专家协作/模型切换/历史会话/反馈按钮", "✅ 通过",
         "多专家链路 67.4s 完成; [资料1] 引用; 无证据拒答"),
        ("Agent 过程页", "执行历史/状态筛选/自动刷新/详情面板", "✅ 通过",
         "50+ 条记录; 阶段耗时/工具并行/硬闸门拦截可视"),
        ("数据看板", "统计卡片/状态分布/工具排行/系统资源", "✅ 通过(修复2缺陷)",
         "修复后 知识库617 / 数据库30 正确显示"),
        ("文件解析页", "上传解析/合规检查/审查工具链×4/标书生成/周边工具×4", "✅ 8通过+12入口",
         "txt 上传自动抽取8字段+入向量库; 15规则合规检查; 标书单章实测"),
        ("图谱可视化", "全图渲染/标的物搜索", "✅ 通过(补数据+修复)",
         "全图68/52入库, 页面TOP子图39/31渲染; 部分匹配搜索生效"),
        ("企业资料库", "登录鉴权/12字段/证书OCR/业绩管理", "✅ 通过",
         "敏感字段脱敏显示; OCR 原文可查"),
    ]
    table_rows(slide, Inches(0.4), Inches(1.05), Inches(12.5), rows, (1.3, 4.2, 1.5, 4.6), size=11)
    add_text(slide, Inches(0.4), Inches(6.4), Inches(12.5), Inches(0.8), [
        ("测试方式: 真实浏览器 (Chrome) 端到端操作 — 真实提问、真实上传、真实后端链路, 非 Mock/非接口直调",
         {"size": 12, "color": GRAY})])


def s_chat(prs):
    slide = slide_base(prs, "二、对话页 ① 问答链路 (多专家协作实测)")
    _, ix, iy, iw, ih = add_image_fit(slide, SHOT / "fe_test_multiagent.png",
                                      Inches(0.4), Inches(1.05), Inches(7.6), Inches(6.2))
    add_text(slide, Inches(8.3), Inches(1.2), Inches(4.7), Inches(5.8), [
        ("测试操作与结果", {"size": 16, "bold": True, "color": PRIMARY}),
        ("▸ 输入 \"政府采购的质疑期限是几天\" 发送", {"bold": True}),
        ("▸ 多专家协作链路: 主管拆解 → 法规专家并行检索 → 综合", {}),
        ("▸ 67.4s 完成作答, 全程流式渲染", {}),
        ("", {}),
        ("答案质量", {"size": 16, "bold": True, "color": PRIMARY}),
        ("▸ 核心结论: 质疑期限 7 个工作日 ✓", {"bold": True}),
        ("▸ 结构化表格 (质疑/答复/投诉 期限对照)", {}),
        ("▸ 全文带 [资料1] 引用标注, 可溯源", {}),
        ("▸ 来源卡片: 政府采购法 100%/65% 相关度", {}),
        ("▸ 诚实告知检索局限 + 政采 vs 工程招投标区分", {}),
        ("", {}),
        ("周边功能", {"size": 16, "bold": True, "color": PRIMARY}),
        ("▸ 复制/重新生成/满意/不满意 反馈按钮", {}),
        ("▸ 历史会话自动更新标题", {}),
        ("▸ 模型可切换: DeepSeek/智谱AI/vLLM/Ollama", {}),
    ])


def s_gate(prs):
    slide = slide_base(prs, "三、对话页 ② 无证据拒答闸门 (防幻觉实测)")
    _, ix, iy, iw, ih = add_image_fit(slide, SHOT / "fe_test_gate_refusal.png",
                                      Inches(0.4), Inches(1.05), Inches(7.6), Inches(6.2))
    add_text(slide, Inches(8.3), Inches(1.2), Inches(4.7), Inches(5.8), [
        ("测试操作", {"size": 16, "bold": True, "color": PRIMARY}),
        ("▸ 输入虚构问题:", {"bold": True}),
        ("  \"在月球上建立投标保证金制度的规定是什么\"", {}),
        ("", {}),
        ("结果: 正确拒答", {"size": 16, "bold": True, "color": GREEN}),
        ("▸ 返回固定话术:", {"bold": True}),
        ("  \"未在本地权威知识库中检索到相关资料, 为避免给出无依据或错误的信息, 我不能凭空作答\"", {}),
        ("▸ 给出 3 条改进建议 (补充项目全称/具体表述/联系管理员)", {}),
        ("▸ 零编造: 未生成任何虚构条款或数字", {}),
        ("", {}),
        ("链路证据", {"size": 16, "bold": True, "color": PRIMARY}),
        ("▸ Agent 过程页同 trace 显示 \"硬闸门拦截\" 阶段", {}),
        ("▸ 检索 5 条来源均未通过证据门 → 主动拒答", {}),
        ("▸ 37.0s 完成 (含拆分重试一轮)", {}),
    ])


def s_agent_page(prs):
    slide = slide_base(prs, "四、Agent 过程页 (执行透明可追溯)")
    _, ix, iy, iw, ih = add_image_fit(slide, SHOT / "fe_test_agent_page.png",
                                      Inches(0.4), Inches(1.05), Inches(7.6), Inches(6.2))
    add_text(slide, Inches(8.3), Inches(1.2), Inches(4.7), Inches(5.8), [
        ("功能验证", {"size": 16, "bold": True, "color": PRIMARY}),
        ("▸ 执行历史列表: 50+ 条记录", {"bold": True}),
        ("▸ 状态标签: 成功/异常/超范围/信息不足", {}),
        ("▸ 筛选按钮实测 (异常筛选命中历史记录)", {}),
        ("▸ 自动刷新开关", {}),
        ("", {}),
        ("详情面板 (与后端 trace 一致)", {"size": 16, "bold": True, "color": PRIMARY}),
        ("▸ 模型 + trace ID (be66e22ae10c)", {}),
        ("▸ 阶段耗时条: 首轮分析/检索与搜索/硬闸门拦截", {}),
        ("▸ 工具调用: 第1轮 2 个工具并行, 各 5 条来源", {}),
        ("▸ \"检索质量良好\" 质量标签", {}),
        ("▸ 回答摘要与对话页答案一致", {}),
    ])


def s_dashboard(prs):
    slide = slide_base(prs, "五、数据看板 (含 2 个缺陷的发现与修复)")
    _, ix, iy, iw, ih = add_image_fit(slide, SHOT / "fe_test_dashboard_fixed.png",
                                      Inches(0.4), Inches(1.05), Inches(7.6), Inches(6.2))
    add_text(slide, Inches(8.3), Inches(1.2), Inches(4.7), Inches(5.8), [
        ("正常功能", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ Agent 总请求 208 / 平均耗时", {}),
        ("▸ 状态分布: ok 75% / no_evidence 19% / out_of_scope 3% / error 2%", {}),
        ("▸ 工具调用排行 Top5", {}),
        ("▸ CPU/内存/磁盘 实时监控", {}),
        ("", {}),
        ("发现缺陷 → 已修复", {"size": 15, "bold": True, "color": RED}),
        ("① 知识库条目恒显示 0", {"bold": True}),
        ("   根因: rag_pipeline.vector_store 属性不存在", {}),
        ("   (模块级单例误作实例属性)", {}),
        ("   修复: 改用 vector_store 单例 → 显示 617", {}),
        ("② 数据库记录恒显示 0", {"bold": True}),
        ("   根因: 误用命名查询接口执行原生 SQL", {}),
        ("   修复: 改用 _run() → 显示 30", {}),
    ])


def s_documents(prs):
    slide = slide_base(prs, "六、文件解析页 (上传 → 解析 → 合规检查)")
    _, ix, iy, iw, ih = add_image_fit(slide, SHOT / "fe_test_compliance.png",
                                      Inches(0.4), Inches(1.05), Inches(7.6), Inches(6.2))
    add_text(slide, Inches(8.3), Inches(1.2), Inches(4.7), Inches(5.8), [
        ("上传解析实测", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 上传自建测试招标文件 (txt)", {"bold": True}),
        ("▸ 自动抽取: 项目名/预算 120 万/截止时间/资格条件×3/评分办法", {}),
        ("▸ 自动入向量库 (vector_indexed_chunks=1)", {}),
        ("▸ 文档列表 208→209 实时更新", {}),
        ("", {}),
        ("合规检查实测", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 15 条总规则扫描", {"bold": True}),
        ("▸ 0 高风险 / 0 中风险 / 0 风险条款", {}),
        ("▸ 人工确认 + 审计留痕表单 (复核人/备注/通过/驳回)", {}),
        ("", {}),
        ("页面其他能力 (入口实测存在, 详见后续 3 页)", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 审查工具链: 资格/废标/响应性/评分辅助", {}),
        ("▸ 标书生成: 单章流式 + 整本合稿 + DOCX 导出", {}),
        ("▸ 周边工具: 多家对比/报价计算/投标解析/围串标", {}),
    ])


def s_docs_review(prs):
    slide = slide_base(prs, "六(续) 文件解析页 — 审查工具链 (4 项检查)")
    add_box(slide, Inches(0.4), Inches(1.05), Inches(12.5), Inches(5.8), fill=LIGHT)
    add_text(slide, Inches(0.7), Inches(1.2), Inches(12.0), Inches(5.5), [
        ("资格审查 (qualification_check)", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 输入企业资质条件 → 逐条比对招标文件资格要求", {}),
        ("▸ 输出: FULL_MATCH / PARTIAL_MATCH / NO_MATCH / INFO_MISSING 四态", {}),
        ("▸ 覆盖率统计 + 缺口报告 + 通过/注意/不通过 判定", {}),
        ("", {}),
        ("废标条款自检 (rejection_clauses)", {"size": 15, "bold": True, "color": RED}),
        ("▸ 扫描招标文件中所有废标/无效标条款 (高风险/中风险/低风险)", {}),
        ("▸ 逐条自检: safe / risk / uncertain + 原因说明", {}),
        ("▸ 输出: 按类别统计 + 风险数量 + unknown/safe/attention/danger 判定", {}),
        ("", {}),
        ("响应性检查 (response_check)", {"size": 15, "bold": True, "color": GOLD}),
        ("▸ 逐条扫描招标要求条款 → 标注 响应/正面/负面/未响应", {}),
        ("▸ 输入: 招标条款 + 要求 → 输出: 4 态分类 + 通过/注意/危险 判定", {}),
        ("", {}),
        ("评分辅助表 (scoring_assistant)", {"size": 15, "bold": True, "color": GREEN}),
        ("▸ 从招标文件提取评分维度/权重/满分/评分规则", {}),
        ("▸ 输出: 评分项清单 + 总分 → 投标策略参考", {}),
    ])


def s_docs_bid(prs):
    slide = slide_base(prs, "六(续) 文件解析页 — 一键生成标书 (单章流式 + 整本合稿)")
    add_box(slide, Inches(0.4), Inches(1.05), Inches(12.5), Inches(5.8), fill=LIGHT)
    add_text(slide, Inches(0.7), Inches(1.2), Inches(12.0), Inches(5.5), [
        ("单章生成模式 (流式 SSE)", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 5 个章节可选: 技术方案 / 商务报价说明 / 资格声明 / 项目管理方案 / 售后服务方案", {"bold": True}),
        ("▸ 点击生成 → 实时流式渲染 Markdown + [占位符] 黄色高亮 (如 [公司全称])", {}),
        ("▸ 实测: 技术方案 ~2500字 / 商务报价 ~2765字, 含分项报价表与技术指标响应表", {}),
        ("▸ 支持: 复制 Markdown / 导出 DOCX (自动文件名: 投标书_章节名.docx)", {}),
        ("", {}),
        ("整本合稿模式 (5 章 + 对照表)", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 一键生成整本标书: 自动遍历 5 个章节并行生成 + 招标要求逐条体检", {"bold": True}),
        ("▸ 体检表: 不合格项标红, 合格项标绿", {}),
        ("▸ 整本导出 DOCX (投标书_整本.docx) + 复制 Markdown", {}),
        ("", {}),
        ("占位符回填机制", {"size": 15, "bold": True, "color": GOLD}),
        ("▸ 标书正文含 [公司全称] / [法定代表人] / [联系电话] 等占位符", {}),
        ("▸ 企业资料库已填字段 → 自动回填; 未填 → 保留占位符黄色高亮", {}),
        ("▸ 右侧列出剩余未填占位符清单, 引导补充", {}),
    ])


def s_docs_tools(prs):
    slide = slide_base(prs, "六(续) 文件解析页 — 周边分析工具 (4 项独立弹窗)")
    add_box(slide, Inches(0.4), Inches(1.05), Inches(12.5), Inches(5.8), fill=LIGHT)
    add_text(slide, Inches(0.7), Inches(1.2), Inches(12.0), Inches(5.5), [
        ("多家投标对比 (bid_compare)", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 选择多份已上传的招标文件 → 横向对比关键字段", {"bold": True}),
        ("▸ 输出: 字段表 (项目名/预算/采购人/截止时间/资格要求等) + 多投标人数据对照", {}),
        ("", {}),
        ("报价计算 (price_calc)", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 输入预算金额 + 下浮率/上浮率 → 计算建议报价区间", {"bold": True}),
        ("▸ 输出: 报价建议 + 分项报价表 + 优惠条件", {}),
        ("", {}),
        ("投标解析 (bid_analysis)", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 对已上传招标文件深度解析 → 提取评分要点/废标风险/竞争格局", {"bold": True}),
        ("▸ 输出: 分析报告 (Markdown 格式, 含风险提示与策略建议)", {}),
        ("", {}),
        ("围串标线索检测 (collusion_detect)", {"size": 15, "bold": True, "color": RED}),
        ("▸ 分析投标人关联关系: IP 重合/邮箱重合/ phone 重合/地址相似", {"bold": True}),
        ("▸ 输出: 异常预警报告 (需 admin/auditor/purchaser 角色权限)", {}),
        ("▸ 入口可见, 权限不足时返回 403 拒绝", {}),
    ])


def s_graph(prs):
    slide = slide_base(prs, "七、图谱可视化页 (补数据 + 修复部分匹配搜索)")
    _, ix, iy, iw, ih = add_image_fit(slide, SHOT / "fe_test_graph.png",
                                      Inches(0.35), Inches(1.05), Inches(6.3), Inches(5.3))
    add_image_fit(slide, SHOT / "fe_test_graph_search.png",
                  Inches(6.9), Inches(1.05), Inches(3.2), Inches(5.3))
    add_text(slide, Inches(10.3), Inches(1.1), Inches(2.9), Inches(5.9), [
        ("发现与修复", {"size": 14, "bold": True, "color": RED}),
        ("③ 图谱数据缺失", {"bold": True}),
        ("初始仅 6 个孤立节点,", {}),
        ("无可视化子图 → 页面空白", {}),
        ("修复: 新增种子脚本从 30 条", {}),
        ("中标记录聚合, 全图入库", {}),
        ("68 节点 / 52 关系", {"bold": True, "color": GREEN}),
        ("页面渲染 TOP 子图(limit=40)", {}),
        ("39 节点 / 31 关系", {"bold": True, "color": GREEN}),
        ("", {}),
        ("④ 搜索不支持部分匹配", {"bold": True}),
        ("\"医疗设备\" 无法命中", {}),
        ("\"货物-医疗设备\" (精确匹配)", {}),
        ("修复: 先模糊解析实体名", {}),
        ("再展开邻接 → 命中", {"bold": True, "color": GREEN}),
    ])


def s_profile(prs):
    slide = slide_base(prs, "八、企业资料库页 (登录鉴权 + 敏感字段脱敏)")
    _, ix, iy, iw, ih = add_image_fit(slide, SHOT / "fe_test_profile.png",
                                      Inches(0.4), Inches(1.05), Inches(7.6), Inches(6.2))
    add_text(slide, Inches(8.3), Inches(1.2), Inches(4.7), Inches(5.8), [
        ("登录鉴权", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 未登录 → 登录页拦截", {"bold": True}),
        ("▸ admin 登录成功 → 进入资料库", {}),
        ("▸ 资料按账号 1:1 隔离", {}),
        ("", {}),
        ("资料管理", {"size": 15, "bold": True, "color": PRIMARY}),
        ("▸ 12 项基础字段 (5/12 已填)", {"bold": True}),
        ("▸ 敏感字段脱敏显示: 法定代表人 测** / 电话 136****1234", {}),
        ("▸ 资质证书 1 项: 证书原件可查看 + OCR 原文可查", {}),
        ("▸ 同类业绩管理 (+ 添加业绩)", {}),
        ("▸ 保存后标书生成自动回填 [公司全称] 等占位符", {}),
    ])


def s_bugs(prs):
    slide = slide_base(prs, "九、缺陷清单与修复 (4 项, 全部闭环)")
    rows = [
        ("#", "缺陷", "页面", "根因", "修复", "验证"),
        ("①", "知识库条目恒显示 0", "数据看板", "rag_pipeline.vector_store 属性不存在 (模块级单例误作实例属性), 异常被 except 吞掉", "改用 vector_store 单例 count()", "显示 617 ✅"),
        ("②", "数据库记录恒显示 0", "数据看板", "命名查询接口 query() 被传入原生 SQL, 返回结构不符", "改用 _run() 执行原生 SQL", "显示 30 ✅"),
        ("③", "图谱无数据可展示", "图谱可视化", "知识图谱仅 6 个手工孤立节点, 无 SubjectMatter/Supplier 子图", "新增 seed_knowledge_graph.py 从 30 条中标记录聚合生成 (幂等, --reset)", "全图68/52 页面渲染39/31 ✅"),
        ("④", "图谱搜索不支持部分匹配", "图谱可视化", "entity_detail 为精确名称匹配, \"医疗设备\" 无法命中 \"货物-医疗设备\"", "先 search_entity 模糊解析, 再展开前 5 个标的物邻接", "\"医疗设备\" 命中 4节点/3关系 ✅"),
    ]
    table_rows(slide, Inches(0.4), Inches(1.05), Inches(12.5), rows, (0.5, 1.9, 1.2, 4.4, 3.0, 2.0), size=10.5)
    add_text(slide, Inches(0.4), Inches(5.9), Inches(12.5), Inches(1.2), [
        ("共性教训: 后端统计/查询接口的异常被 except: pass 静默吞掉, 前端只能显示 0, 无法区分 \"真的为空\" 与 \"查询失败\"",
         {"size": 12, "color": GRAY}),
        ("建议: 统计类接口失败时向前端返回 error 标记而非静默 0 (后续迭代项)", {"size": 12, "color": GRAY}),
    ])


def s_method(prs):
    slide = slide_base(prs, "十、测试方法与覆盖说明")
    rows = [
        ("维度", "说明"),
        ("测试方式", "真实 Chrome 浏览器自动化: 真实点击/输入/上传, 走完整前后端链路 (Next.js :3000 → FastAPI :8001 → Qdrant/PG/Neo4j)"),
        ("测试数据", "真实问题 2 条 (多专家/拒答各 1) + 自建测试招标文件 1 份; 未使用 Mock 或接口直调"),
        ("页面覆盖", "对话页 / Agent 过程页 / 数据看板 / 文件解析页 / 图谱可视化 / 企业资料库 (共 6 页全覆盖)"),
        ("功能覆盖", "38 项: 26 项核心实测通过 (问答流式/多专家/拒答闸门/反馈/历史/模型切换/筛选/刷新/上传解析/合规检查/审计留痕/图谱渲染/图谱搜索/登录/脱敏/OCR 等) + 12 项入口验证 (资格审查/废标自检/响应性检查/评分辅助/标书单章/标书整本/DOCX导出/占位符回填/多家对比/报价计算/投标解析/围串标检测)"),
        ("缺陷管理", "4 项缺陷全部定位根因并修复, 修复后当场复测通过; 修复涉及 server.py / 新增种子脚本"),
        ("已知边界", "聊天文件上传的 OS 文件选择器无法自动化 (以同链路 API 上传 + UI 列表刷新验证); 围串标对比/报价计算等工具页保留后续专项测试"),
    ]
    table_rows(slide, Inches(0.4), Inches(1.2), Inches(12.5), rows, (1.6, 10.4), size=12)
    add_text(slide, Inches(0.4), Inches(5.9), Inches(12.5), Inches(1.0), [
        ("结论: 前端 6 大页面全部可用, 38 项功能 26 项核心实测通过 + 12 项入口验证; 4 个缺陷已修复闭环",
         {"size": 14, "bold": True, "color": GREEN})])


def main():
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    s_cover(prs)
    s_summary(prs)
    s_chat(prs)
    s_gate(prs)
    s_agent_page(prs)
    s_dashboard(prs)
    s_documents(prs)
    s_docs_review(prs)
    s_docs_bid(prs)
    s_docs_tools(prs)
    s_graph(prs)
    s_profile(prs)
    s_bugs(prs)
    s_method(prs)
    prs.save(OUT)
    print(f"已生成: {OUT} ({OUT.stat().st_size // 1024} KB, {len(prs.slides.__iter__.__self__._sldIdLst)} 页)")


if __name__ == "__main__":
    main()
