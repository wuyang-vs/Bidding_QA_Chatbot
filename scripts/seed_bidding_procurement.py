"""历史中标数据脱敏种子脚本 (小范围可用性验证前置).

用途:
- 建立 bidding_procurement 表 (postgresql_client 仅查询不建表, 需本表存在);
- 写入 30 条脱敏历史中标记录, 覆盖多领域/多采购人/多代理机构,
  使 PRICE 专家与 search_postgresql 价格分析能力可用.

幂等: 表已存在则跳过建表; 数据以 project_code 为唯一键, 已存在则 UPDATE.
不存任何真实单位/金额/时间, 全部为合成脱敏数据.

用法:
  .venv\\Scripts\\python.exe scripts/seed_bidding_procurement.py
  .venv\\Scripts\\python.exe scripts/seed_bidding_procurement.py --reset   # 先清空再灌
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_DDL = """
CREATE TABLE IF NOT EXISTS bidding_procurement (
    id              BIGSERIAL PRIMARY KEY,
    title           TEXT,
    project_name    TEXT,
    project_code    TEXT UNIQUE,
    subject_matter  TEXT,
    purchaser       TEXT,
    agency          TEXT,
    winning_bidder  TEXT,
    winning_amount  NUMERIC(18,2),
    publish_time    DATE,
    winning_time    DATE,
    location        TEXT,
    created_at      TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_bp_purchaser ON bidding_procurement (purchaser);
CREATE INDEX IF NOT EXISTS idx_bp_subject  ON bidding_procurement (subject_matter);
CREATE INDEX IF NOT EXISTS idx_bp_amount   ON bidding_procurement (winning_amount);
"""

# 30 条脱敏合成数据: 字段全部虚构, 仅用于打通价格分析链路
_RECORDS = [
    # 货物类
    ("办公设备批量采购项目", "XX2025-001", "货物-办公设备", "某市第一中学", "某市公共资源交易中心", "迅捷科技有限公司", 86.5, "2025-01-10", "2025-02-05", "华东"),
    ("智慧校园设备采购项目", "XX2025-002", "货物-信息化设备", "北京交通大学", "中央国家机关政府采购中心", "云图智能科技股份有限公司", 850.0, "2025-03-15", "2025-04-20", "华北"),
    ("医疗设备采购项目(一批)", "XX2025-003", "货物-医疗设备", "某市人民医院", "某市卫生健康委员会采购中心", "康健医疗器械有限公司", 320.0, "2025-02-20", "2025-03-25", "华南"),
    ("空调设备采购项目", "XX2025-004", "货物-空调设备", "某市行政中心", "某市机关事务管理局", "冷暖设备工程有限公司", 128.6, "2025-01-25", "2025-02-28", "华中"),
    ("教学实验仪器采购", "XX2025-005", "货物-教学仪器", "某理工大学", "某省教育厅采购中心", "科教仪器设备有限公司", 76.3, "2025-04-05", "2025-05-10", "西南"),
    ("消防器材集中采购", "XX2025-006", "货物-消防器材", "某市消防救援支队", "某市应急管理局", "安盾消防设备有限公司", 45.2, "2025-03-01", "2025-03-30", "华东"),
    ("图书馆电子资源采购", "XX2025-007", "货物-电子资源", "某师范大学", "某省高校采购联盟", "知源数字科技有限公司", 58.8, "2025-05-12", "2025-06-15", "华北"),
    ("食堂食材配送服务采购", "XX2025-008", "货物-食材配送", "某职业技术学院", "某市公共资源交易中心", "绿源农副产品配送有限公司", 210.0, "2025-06-01", "2025-07-05", "华南"),
    # 工程类
    ("基础设施配套改造项目", "XX2025-009", "工程-装修改造", "国家广播电视总局282台", "国正聚源工程咨询有限公司", "建工集团第七工程局", 240.43, "2025-02-08", "2025-03-15", "华北"),
    ("教学楼抗震加固工程", "XX2025-010", "工程-加固工程", "某市实验小学", "某市住房和城乡建设局", "固基建设工程有限公司", 560.0, "2025-03-20", "2025-05-18", "华东"),
    ("市政道路修缮工程", "XX2025-011", "工程-市政工程", "某市市政管理处", "某市公共资源交易中心", "城建道桥建设集团有限公司", 1280.0, "2025-04-10", "2025-06-25", "华中"),
    ("污水处理厂扩建工程", "XX2025-012", "工程-环保工程", "某市水务集团", "某市生态环境局", "净水环保工程股份有限公司", 3450.0, "2025-05-01", "2025-08-30", "西南"),
    ("校园绿化景观工程", "XX2025-013", "工程-园林绿化", "某农业大学", "某省教育厅采购中心", "绿野园林工程有限公司", 185.0, "2025-06-15", "2025-08-10", "华南"),
    ("体育馆屋面维修工程", "XX2025-014", "工程-维修工程", "某市体育局", "某市公共资源交易中心", "宏达建设工程有限公司", 92.5, "2025-07-01", "2025-08-05", "华北"),
    # 服务类
    ("物业管理服务采购", "XX2025-015", "服务-物业管理", "某市行政中心", "某市机关事务管理局", "金牌物业管理有限公司", 360.0, "2025-01-05", "2025-02-10", "华东"),
    ("信息系统运维服务", "XX2025-016", "服务-IT运维", "某税务局", "某省税务局采购中心", "网信科技服务有限公司", 145.0, "2025-02-15", "2025-03-20", "华北"),
    ("车辆维修保养服务", "XX2025-017", "服务-车辆维修", "某市公安局", "某市公共资源交易中心", "安行汽车服务有限公司", 38.6, "2025-03-05", "2025-04-08", "华南"),
    ("会计审计服务采购", "XX2025-018", "服务-审计服务", "某财政局", "某省财政厅采购中心", "正信会计师事务所", 25.0, "2025-04-01", "2025-04-30", "华中"),
    ("网络安全等级保护测评", "XX2025-019", "服务-安全测评", "某大数据局", "某市公共资源交易中心", "网安测评技术有限公司", 18.5, "2025-05-10", "2025-06-12", "西南"),
    ("法律顾问服务采购", "XX2025-020", "服务-法律服务", "某司法局", "某省司法厅采购中心", "明法律师事务所", 15.0, "2025-06-01", "2025-06-30", "华东"),
    # 跨地域对比数据 (支撑多跳价格分析)
    ("办公设备批量采购项目", "XX2025-021", "货物-办公设备", "某市第二中学", "某市公共资源交易中心", "恒达办公设备有限公司", 92.0, "2025-02-15", "2025-03-20", "华北"),
    ("办公设备批量采购项目", "XX2025-022", "货物-办公设备", "某市第三中学", "某市公共资源交易中心", "迅捷科技有限公司", 78.4, "2025-03-10", "2025-04-12", "华南"),
    ("智慧校园设备采购项目", "XX2025-023", "货物-信息化设备", "某工业大学", "某省教育厅采购中心", "云图智能科技股份有限公司", 920.0, "2025-04-20", "2025-05-25", "华东"),
    ("医疗设备采购项目(一批)", "XX2025-024", "货物-医疗设备", "某市中医院", "某市卫生健康委员会采购中心", "康健医疗器械有限公司", 298.0, "2025-05-05", "2025-06-08", "华中"),
    ("教学楼抗震加固工程", "XX2025-025", "工程-加固工程", "某市第一中学", "某市住房和城乡建设局", "固基建设工程有限公司", 610.0, "2025-06-10", "2025-08-15", "西南"),
    ("物业管理服务采购", "XX2025-026", "服务-物业管理", "某理工大学", "某省教育厅采购中心", "金牌物业管理有限公司", 410.0, "2025-07-01", "2025-08-01", "华北"),
    ("信息系统运维服务", "XX2025-027", "服务-IT运维", "某教育局", "某市公共资源交易中心", "网信科技服务有限公司", 168.0, "2025-08-01", "2025-09-05", "华南"),
    ("空调设备采购项目", "XX2025-028", "货物-空调设备", "某市图书馆", "某市机关事务管理局", "冷暖设备工程有限公司", 95.2, "2025-08-15", "2025-09-18", "华中"),
    ("消防器材集中采购", "XX2025-029", "货物-消防器材", "某化工园区管委会", "某市应急管理局", "安盾消防设备有限公司", 62.8, "2025-09-01", "2025-10-08", "华东"),
    ("基础设施配套改造项目", "XX2025-030", "工程-装修改造", "某市档案馆", "国正聚源工程咨询有限公司", "建工集团第七工程局", 310.0, "2025-09-15", "2025-11-01", "西南"),
]

_UPSERT = """
INSERT INTO bidding_procurement
    (title, project_name, project_code, subject_matter, purchaser, agency,
     winning_bidder, winning_amount, publish_time, winning_time, location)
VALUES
    (:title, :project_name, :project_code, :subject_matter, :purchaser, :agency,
     :winning_bidder, :winning_amount, :publish_time, :winning_time, :location)
ON CONFLICT (project_code) DO UPDATE SET
    title = EXCLUDED.title,
    project_name = EXCLUDED.project_name,
    subject_matter = EXCLUDED.subject_matter,
    purchaser = EXCLUDED.purchaser,
    agency = EXCLUDED.agency,
    winning_bidder = EXCLUDED.winning_bidder,
    winning_amount = EXCLUDED.winning_amount,
    publish_time = EXCLUDED.publish_time,
    winning_time = EXCLUDED.winning_time,
    location = EXCLUDED.location
"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true", help="先清空 bidding_procurement 再灌数据")
    args = ap.parse_args()

    from src.database.postgresql_client import postgresql_client
    postgresql_client.initialize()
    if not postgresql_client.ready:
        print("[FAIL] PostgreSQL 未就绪, 请检查 .env 中 POSTGRES_* 配置")
        return 2

    # 建表
    for stmt in _DDL.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                postgresql_client._run(stmt)
            except Exception as e:
                print(f"[WARN] DDL 执行失败: {e}")

    if args.reset:
        try:
            postgresql_client._run("TRUNCATE TABLE bidding_procurement")
            print("[INFO] 已清空 bidding_procurement")
        except Exception as e:
            print(f"[FAIL] 清空失败: {e}")
            return 2

    inserted = 0
    for (title, code, subject, purchaser, agency, bidder, amount,
         pub, win, loc) in _RECORDS:
        params = {
            "title": title, "project_name": title, "project_code": code,
            "subject_matter": subject, "purchaser": purchaser, "agency": agency,
            "winning_bidder": bidder, "winning_amount": amount,
            "publish_time": pub, "winning_time": win, "location": loc,
        }
        try:
            postgresql_client._run(_UPSERT, params)
            inserted += 1
        except Exception as e:
            print(f"[WARN] 写入 {code} 失败: {e}")

    rows = postgresql_client._run("SELECT COUNT(*) AS cnt FROM bidding_procurement")
    total = int(rows[0]["cnt"]) if rows else 0
    print(f"[OK] 写入/更新 {inserted} 条, 当前表共 {total} 条脱敏历史中标记录")
    print(f"[INFO] 字段: {json.dumps(['title','project_name','subject_matter','purchaser', 'winning_bidder','project_code','winning_amount','agency','location'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
