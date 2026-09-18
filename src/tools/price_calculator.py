"""报价计算 — 纯规则算术校验 + 分项汇总 + 价格分计算.

无 LLM 依赖, 结果可确定性复现, 便于自动测试.

校验项:
  1. 行内算术: 数量 × 单价 = 分项金额
  2. 分项汇总: Σ 分项金额 = 投标总价
  3. 大小写一致性: 中文大写金额解析后 = 阿拉伯数字总价
  4. 数据异常: 负数 / 零单价 / 缺失或重复分项
  5. 最高限价: 投标总价 > 招标控制价 (可选)
价格分:
  低价优先法 (常见评标办法): score = 评标基准价 / 投标价 × 满分
  评标基准价取所有有效投标最低价 (或外部传入 base_price)
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 算术容差 (元): 浮点/四舍五入误差
_AMOUNT_TOL = 0.01
# 汇总容差允许按比例放宽 (分项多时累计舍入)
_SUM_TOL_RATIO = 0.0005

_CN_DIGITS = {"零": 0, "壹": 1, "贰": 2, "叁": 3, "肆": 4,
              "伍": 5, "陆": 6, "柒": 7, "捌": 8, "玖": 9}
_CN_UNITS = {"分": 0.01, "角": 0.1, "元": 1.0, "拾": 10.0, "佰": 100.0,
             "仟": 1000.0, "万": 10000.0, "亿": 100000000.0}


def parse_cn_amount(text: str) -> float | None:
    """解析中文大写金额为元. 支持 '捌佰贰拾万元整' '叁佰贰拾壹万零伍佰元陆角' 等.

    无法解析返回 None.
    """
    if not text:
        return None
    s = str(text).strip().replace(" ", "").replace("　", "")
    s = s.replace("圓", "元").replace("塡", "填")
    s = s.replace("人民币", "").rstrip("整正")
    if not s:
        return None

    total = 0.0
    section = 0.0      # 当前万/亿节内累计
    number = 0.0       # 当前数字
    seen_any = False
    for ch in s:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
            seen_any = True
        elif ch in _CN_UNITS:
            u = _CN_UNITS[ch]
            seen_any = True
            if ch in ("万", "亿"):
                section = (section + number) * u
                if ch == "亿":
                    total += section
                    section = 0.0
                number = 0.0
            elif ch == "元":
                section += number * u
                number = 0.0
                total += section
                section = 0.0
            else:
                section += number * u if number else (u if ch in ("角", "分") else 0.0)
                number = 0.0
        else:
            return None
    # 收尾: 无"元"结尾 (如 '捌佰贰拾万') 或角分余值
    total += section + number
    return round(total, 2) if seen_any else None


def _to_float(v: Any) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace(",", "").replace("，", "").replace(" ", "")
    s = s.replace("元", "").replace("￥", "").replace("¥", "").replace("人民币", "")
    # 万元单位
    mult = 1.0
    if s.endswith("万元"):
        mult = 10000.0
        s = s[:-2]
    elif s.endswith("万"):
        mult = 10000.0
        s = s[:-1]
    try:
        return float(s) * mult
    except ValueError:
        return None


def calculate_price(
    items: list[dict[str, Any]],
    declared_total: float | str | None = None,
    declared_total_cn: str | None = None,
    control_price: float | str | None = None,
    base_price: float | str | None = None,
    score_full: float = 100.0,
    all_bid_prices: list[float] | None = None,
) -> dict[str, Any]:
    """报价计算与校验.

    Args:
        items: 分项报价行 [{"name","spec","unit","qty","unit_price","amount"}]
               amount 可省略 (自动按 qty*unit_price 计算)
        declared_total: 投标函自报总价 (阿拉伯数字, 可带单位/逗号)
        declared_total_cn: 投标函自报总价 (中文大写)
        control_price: 招标控制价/最高限价 (可选)
        base_price: 评标基准价 (可选, 默认取 all_bid_prices 最低价)
        score_full: 价格分满分
        all_bid_prices: 所有投标人总价 (多供应商同时算分时确定基准价)

    Returns:
        {table, subtotal, declared_total, total_diff, cn_amount, cn_total,
         anomalies, price_score, verdict}
    """
    anomalies: list[dict[str, Any]] = []
    table: list[dict[str, Any]] = []
    seen_names: dict[str, int] = {}

    for idx, raw in enumerate(items, start=1):
        name = str(raw.get("name") or "").strip()
        qty = _to_float(raw.get("qty"))
        unit_price = _to_float(raw.get("unit_price"))
        amount = _to_float(raw.get("amount"))
        row_anoms: list[str] = []

        if not name:
            row_anoms.append("分项名称缺失")
        elif name in seen_names:
            row_anoms.append(f"分项名称与第 {seen_names[name]} 行重复")
        else:
            seen_names[name] = idx

        if qty is None:
            row_anoms.append("数量缺失或非数字")
        elif qty < 0:
            row_anoms.append("数量为负数")
        if unit_price is None:
            row_anoms.append("单价缺失或非数字")
        elif unit_price < 0:
            row_anoms.append("单价为负数")
        elif unit_price == 0:
            row_anoms.append("单价为 0, 请确认是否漏项/赠送")

        calc_amount = None
        if qty is not None and unit_price is not None and qty >= 0 and unit_price >= 0:
            calc_amount = round(qty * unit_price, 2)

        if amount is None and calc_amount is not None:
            amount = calc_amount  # 未填金额, 以计算值代填
        elif amount is not None and calc_amount is not None:
            diff = round(amount - calc_amount, 2)
            if abs(diff) > _AMOUNT_TOL:
                row_anoms.append(
                    f"行内算术不符: {qty}×{unit_price}={calc_amount}, 填报 {amount}, 差 {diff:+.2f}")
        elif amount is not None and calc_amount is None:
            row_anoms.append("无法校验行内算术 (数量/单价不全)")

        for msg in row_anoms:
            anomalies.append({"level": "error" if "不符" in msg or "负数" in msg
                              or "缺失" in msg else "warning",
                              "code": "ROW_ARITHMETIC", "row": idx,
                              "item": name or f"第{idx}行", "message": msg})

        table.append({
            "row": idx, "name": name,
            "spec": str(raw.get("spec") or ""),
            "unit": str(raw.get("unit") or ""),
            "qty": qty, "unit_price": unit_price,
            "filled_amount": amount, "calc_amount": calc_amount,
            "row_anomalies": row_anoms,
        })

    subtotal = round(sum(r["calc_amount"] or r["filled_amount"] or 0.0 for r in table), 2)

    declared = _to_float(declared_total)
    total_diff = None
    if declared is not None and table:
        tol = max(_AMOUNT_TOL, subtotal * _SUM_TOL_RATIO)
        total_diff = round(declared - subtotal, 2)
        if abs(total_diff) > tol:
            anomalies.append({
                "level": "error", "code": "SUM_MISMATCH", "item": "投标总价",
                "message": f"分项合计 {subtotal:.2f} 与投标总价 {declared:.2f} 不一致, 差 {total_diff:+.2f}",
            })

    # 中文大写金额
    cn_amount = parse_cn_amount(declared_total_cn) if declared_total_cn else None
    if declared_total_cn and cn_amount is None:
        anomalies.append({"level": "warning", "code": "CN_UNPARSEABLE", "item": "大写金额",
                          "message": f"中文大写金额无法解析: '{declared_total_cn}'"})
    elif cn_amount is not None:
        target = declared if declared is not None else subtotal
        if abs(cn_amount - target) > _AMOUNT_TOL:
            anomalies.append({
                "level": "error", "code": "CN_MISMATCH", "item": "大写金额",
                "message": f"大写金额 {cn_amount:.2f} 与数字金额 {target:.2f} 不一致",
            })

    # 最高限价
    ctrl = _to_float(control_price)
    check_price = declared if declared is not None else subtotal
    if ctrl is not None and check_price and check_price > ctrl + _AMOUNT_TOL:
        anomalies.append({
            "level": "error", "code": "OVER_CONTROL_PRICE", "item": "投标总价",
            "message": f"投标价 {check_price:.2f} 超过最高限价 {ctrl:.2f}, 将被否决",
        })

    # 价格分 (低价优先)
    price_score = None
    base = _to_float(base_price)
    if base is None and all_bid_prices:
        nums = [_to_float(p) for p in all_bid_prices]
        nums = [p for p in nums if p is not None and p > 0]
        if nums:
            base = min(nums)
    if base is not None and check_price and check_price > 0:
        price_score = round(base / check_price * score_full, 2)

    err_cnt = sum(1 for a in anomalies if a["level"] == "error")
    warn_cnt = len(anomalies) - err_cnt
    verdict = "fail" if err_cnt else ("attention" if warn_cnt else "pass")

    return {
        "table": table,
        "subtotal": subtotal,
        "declared_total": declared,
        "total_diff": total_diff,
        "cn_input": declared_total_cn or "",
        "cn_amount": cn_amount,
        "control_price": ctrl,
        "base_price": base,
        "price_score": price_score,
        "summary": {"rows": len(table), "errors": err_cnt, "warnings": warn_cnt},
        "anomalies": anomalies,
        "verdict": verdict,
    }
