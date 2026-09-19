# -*- coding: utf-8 -*-
"""MinIO/S3 真实连通手动实测 (非自动套件; 需先启动真实 MinIO, 无 MinIO 时跳过).

定位: 自动套件 tests/test_new_tools.py 的 TestS3CertStorage 用 botocore Stubber
离线模拟 (CI 可重复); 本脚本用**真实 MinIO server** 做一次端到端连通实测,
关闭报告 R11 "仅 Stubber、未做真实连通" 遗留。2026-09-20 首测 13/13 PASS
(MinIO RELEASE.2025-09-07T16-13-09Z, windows-amd64)。

启动 MinIO (Windows 单文件, 无需 Docker; 开源 server 归档前最后带二进制版本之一):
  # 二进制: https://github.com/minio/minio/releases/tag/RELEASE.2025-09-07T16-13-09Z
  $env:MINIO_ROOT_USER="minioadmin"; $env:MINIO_ROOT_PASSWORD="minioadmin"
  minio.exe server <数据目录> --address ":9000" --console-address ":9001"

运行:
  .\\.venv\\Scripts\\python.exe tests\\acceptance\\manual_minio_live.py

覆盖:
 0. 生产工厂 get_cert_storage() 在 CERT_STORAGE_TYPE=s3 + MinIO 配置下构建成功并自动建桶
 1. save 中文名证书 → token/扩展/字节数
 2. S3 metadata original_name URL 编码可还原 (D18 缺陷在真实服务侧复验)
 3. presigned URL(s3v4) 匿名 GET 200 且字节一致
 4. read 回读字节一致
 5. cleanup: 第二份孤儿按 keep_tokens 批量删除
 6. delete 后 read → FileNotFoundError (404/NoSuchKey 映射)
 7. 对象 key 路径隔离 certs/{uid}/{token}
收尾: 清空并删除测试桶, 不留测试数据。
"""
import os
import sys
import time
from urllib.parse import unquote

import requests

ENDPOINT = "http://127.0.0.1:9000"
AK, SK = "minioadmin", "minioadmin"
BUCKET = "bid-certs-live-test"
UID = 999999

# 真实 MinIO 配置 (与 .env.example 同名), 必须在 import src.config 前设置
os.environ["CERT_STORAGE_TYPE"] = "s3"
os.environ["CERT_S3_ENDPOINT"] = ENDPOINT
os.environ["CERT_S3_ACCESS_KEY"] = AK
os.environ["CERT_S3_SECRET_KEY"] = SK
os.environ["CERT_S3_BUCKET"] = BUCKET
os.environ["CERT_S3_AUTO_BUCKET"] = "true"
os.environ["CERT_S3_PRESIGN_MIN"] = "5"

from src.tools.cert_ocr import S3CertStorage, get_cert_storage, reset_cert_storage  # noqa: E402

# 合法 1x1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201f4d34cf80000000049454e44ae426082"
)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def wait_live(seconds: int = 30) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            if requests.get(f"{ENDPOINT}/minio/health/live", timeout=3).status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False


def main() -> int:
    if not wait_live():
        print("MinIO 未就绪")
        return 1
    check("MinIO /minio/health/live", True, ENDPOINT)

    # 0. 生产工厂集成 (真实配置 → S3CertStorage + 自动建桶)
    reset_cert_storage()
    st = get_cert_storage()
    check("工厂构建 S3CertStorage (CERT_STORAGE_TYPE=s3)",
          isinstance(st, S3CertStorage), type(st).__name__)
    st._s3().head_bucket(Bucket=BUCKET)  # auto_bucket 已建桶则不抛异常
    check("auto_bucket 自动建桶", True, BUCKET)

    s3 = st._s3()
    key_prefix = f"certs/{UID}/"

    # 1. save 中文名
    fname = "营业执照-真连通测试.jpg"
    info = st.save(UID, fname, PNG)
    token = info["file_token"]
    check("save 中文名证书", token.endswith(".jpg") and info["size"] == len(PNG),
          f"token={token} size={info['size']}")

    # 7. key 路径隔离
    full_key = st._key(UID, token)
    check("对象 key 路径隔离 certs/{uid}/{token}", full_key == f"{key_prefix}{token}", full_key)

    # 2. metadata D18 真实服务复验
    head = s3.head_object(Bucket=BUCKET, Key=full_key)
    orig = head.get("Metadata", {}).get("original_name", "")
    check("metadata 中文名 URL 编码可还原 (D18)", unquote(orig) == fname, f"meta={orig!r}")

    # 3. presigned s3v4 匿名 GET
    url = st.presigned_url(UID, token, expires_min=5)
    check("presigned URL 含 X-Amz-Signature (s3v4)", "X-Amz-Signature=" in url, "")
    r = requests.get(url, timeout=10)
    check("预签名匿名 GET 200 且字节一致", r.status_code == 200 and r.content == PNG,
          f"http={r.status_code} bytes={len(r.content)}")

    # 4. read 回读
    check("read 回读字节一致", st.read(UID, token) == PNG)

    # 5. cleanup 孤儿批删
    info2 = st.save(UID, "资质证书-孤儿.jpg", PNG)
    removed = st.cleanup(UID, keep_tokens={token})
    check("cleanup 列举+批量删除孤儿=1", removed == 1, f"removed={removed}")
    try:
        st.read(UID, info2["file_token"])
        check("孤儿对象已不可读", False, "仍可读")
    except FileNotFoundError:
        check("孤儿对象已不可读", True)

    # 6. delete → 404 映射
    st.delete(UID, token)
    try:
        st.read(UID, token)
        check("delete 后 read → FileNotFoundError", False, "未抛异常")
    except FileNotFoundError:
        check("delete 后 read → FileNotFoundError", True)

    # 收尾: 清空桶并删桶 (测试数据零残留)
    s3 = st._s3()
    paginator = s3.get_paginator("list_objects_v2")
    objs = []
    for page in paginator.paginate(Bucket=BUCKET):
        objs.extend(page.get("Contents") or [])
    if objs:
        s3.delete_objects(Bucket=BUCKET,
                          Delete={"Objects": [{"Key": o["Key"]} for o in objs], "Quiet": True})
    s3.delete_bucket(Bucket=BUCKET)
    import botocore.exceptions as be  # noqa
    try:
        s3.head_bucket(Bucket=BUCKET)
        check("测试桶已删除(零残留)", False, "桶仍存在")
    except be.ClientError:
        check("测试桶已删除(零残留)", True)

    failed = [x for x in results if not x[1]]
    print(f"\n{'='*60}\n真实 MinIO 连通实测: {len(results)-len(failed)}/{len(results)} PASS")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
