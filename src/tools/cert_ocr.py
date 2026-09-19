"""资质证书附件 OCR 与结构化抽取。

链路: 上传图片/PDF → RapidOCR 文本 → LLM JSON 抽取四字段
      (name/level/cert_no/valid_until); LLM 不可用时正则确定性回退。

OCR 引擎复用 document_parser 的 RapidOCR 单例 (onnxruntime 懒加载),
不引入任何新依赖。纯文本字段抽取与 OCR 执行分离, 便于离线单测。
"""
from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# 支持的证书附件格式
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
CERT_EXTS = IMAGE_EXTS | {".pdf"}
# 单文件大小上限 (10MB, 与常见网关默认一致)
MAX_CERT_BYTES = 10 * 1024 * 1024
# 证书 PDF 最多识别前 2 页 (证书一般 1 页, 防止长文档拖慢)
_MAX_PDF_PAGES = 2

_CERT_SYSTEM = (
    "你是证照信息录入助手。用户提供一张资质证书/营业执照/许可证的 OCR 文本, "
    "请提取四项信息并只输出 JSON (无代码块、无额外文字):\n"
    '{"name": "证书/证照名称(如:建筑业企业资质证书、安全生产许可证, 不含等级)", '
    '"level": "等级(如:一级/甲级/特级/AAA; 没有则空字符串)", '
    '"cert_no": "证书编号(原文照录, 去掉空格; 没有则空字符串)", '
    '"valid_until": "有效期至(统一YYYY-MM-DD; 长期有效填长期; 没有则空字符串)"}\n'
    "OCR 文本可能有错字或断行, 请结合常见证照版式推断; 无法确定的字段留空, 严禁编造。"
)

# ---- 正则回退 ----
# 等级: 特/一/二/三/四级、甲/乙/丙级、高/中/初级、信用 AAA 等
_LEVEL_RE = re.compile(
    r"(特级|一级|二级|三级|四级|甲级|乙级|丙级|丁级|高级|中级|初级|AAA级|AA级|A级)")
# 证照名称: 2-30 个中英文 + 证书/执照/许可证/登记证/资质 结尾
_NAME_RE = re.compile(
    r"([\u4e00-\u9fa5（）()A-Za-z0-9·]{0,30}?(?:企业资质证书|资质证书|资格证书|"
    r"安全生产许可证|许可证|营业执照|登记证|认证证书|证书))")
# 编号: 关键词引导, 取其后的字母数字组合; 或直接识别常见编号形态 (字母前缀+数字)
_NO_AFTER_RE = re.compile(
    r"(?:证书编号|证书号|注册号|统一社会信用代码|编\s*号|证\s*号|No\.?|NO\.?)[\s:：]*"
    r"([0-9A-Za-z][0-9A-Za-z\-_/（）()]{3,40}[0-9A-Za-z）)])")
_NO_SHAPE_RE = re.compile(r"\b([A-Z]{2,}-?\d{5,}(?:-[0-9A-Z]+)*)\b")
# 有效期
_DATE_RE = re.compile(
    r"(?:有效期(?:限)?至|有效期到|有效日期至|有效期限|截止日期|营业期限至|至)\s*[:：]?\s*"
    r"(\d{4})\s*[年\.\-/]\s*(\d{1,2})\s*[月\.\-/]\s*(\d{1,2})\s*日?")
_LONG_VALID_RE = re.compile(r"(长期有效|长期|永久有效)")

EMPTY_CERT_FIELDS = {
    "name": "", "level": "", "cert_no": "", "valid_until": "",
}


def _clean(s: object) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def fallback_cert_fields(text: str) -> dict:
    """OCR 文本 → 四字段的确定性正则抽取 (LLM 不可用时的降级, 也用于单测)。"""
    t = (text or "").replace("（", "(").replace("）", ")")
    out = dict(EMPTY_CERT_FIELDS)

    m = _LEVEL_RE.search(t)
    if m:
        out["level"] = m.group(1)

    m = _NO_AFTER_RE.search(t)
    if m:
        out["cert_no"] = m.group(1)
    else:
        m = _NO_SHAPE_RE.search(t)
        if m:
            out["cert_no"] = m.group(1)

    m = _DATE_RE.search(t)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            out["valid_until"] = f"{y:04d}-{mo:02d}-{d:02d}"
    elif _LONG_VALID_RE.search(t):
        out["valid_until"] = "长期"

    m = _NAME_RE.search(t)
    if m:
        name = m.group(1)
        # 去掉被误带进名称的等级词 (如"建筑工程施工总承包一级资质证书"→剥离"一级")
        name = _LEVEL_RE.sub("", name)
        out["name"] = _clean(name)

    return out


def extract_cert_fields(ocr_text: str, llm_client=None) -> dict:
    """OCR 文本 → {name,level,cert_no,valid_until,source,warnings}。

    LLM 成功且至少抽到一个字段 → source=llm; 否则正则回退 → source=fallback。
    """
    text = (ocr_text or "").strip()
    warnings: list[str] = []
    if not text:
        warnings.append("OCR 未识别到文字, 请确认图片清晰或手工填写")
        return {**EMPTY_CERT_FIELDS, "source": "none", "warnings": warnings}

    if llm_client is None:
        try:
            from src.clients.llm_factory import get_llm_client
            llm_client = get_llm_client()
        except Exception as e:  # 连客户端都构造不出
            logger.warning("LLM 客户端不可用, 证书字段走正则回退: %s", e)
            llm_client = None

    if llm_client is not None:
        try:
            raw = llm_client.chat([
                {"role": "system", "content": _CERT_SYSTEM},
                {"role": "user", "content": text[:3000]},
            ], temperature=0.0)
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
            cleaned = re.sub(r"\s*```$", "", cleaned)
            data = json.loads(cleaned)
            fields = {
                "name": _clean(data.get("name"))[:60],
                "level": _clean(data.get("level"))[:20],
                "cert_no": _clean(data.get("cert_no"))[:50],
                "valid_until": _clean(data.get("valid_until"))[:20],
            }
            if any(fields.values()):
                if not fields["cert_no"] or not fields["name"]:
                    warnings.append("部分字段未识别, 请核对后手工补充")
                return {**fields, "source": "llm", "warnings": warnings}
            warnings.append("LLM 未识别出有效字段, 已改用规则提取")
        except Exception as e:
            logger.warning("证书 LLM 抽取失败, 降级正则: %s", e)
            warnings.append("智能识别不可用, 已改用规则提取, 请核对")

    fields = fallback_cert_fields(text)
    if not any(fields.values()):
        warnings.append("未能从图片中识别证书信息, 请手工填写")
    return {**fields, "source": "fallback", "warnings": warnings}


# ---- OCR 执行 ----

def _preprocess_image(img):
    """R11: OCR 前图像预处理: 灰度化 + 小图放大, 提升小字/低清晰度识别率。

    不做强二值化 (避免破坏彩色印章/水印), 仅做灰度与尺度增强。
    """
    import cv2
    h, w = img.shape[:2]
    # 小图放大 1.5 倍 (证书扫描件字号通常偏小)
    if w < 1200:
        img = cv2.resize(img, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
    # 灰度化 (RapidOCR 内部也会处理, 显式灰度减少通道干扰)
    if len(img.shape) == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        img = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return img


def _ocr_image_bytes(data: bytes) -> str:
    """图片字节流 → (预处理) → RapidOCR 文本。"""
    import cv2
    import numpy as np
    from src.tools.document_parser import _get_ocr_engine

    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("图片解码失败 (文件损坏或格式不受支持)")
    img = _preprocess_image(img)
    result, _ = _get_ocr_engine()(img)
    if not result:
        return ""
    return "\n".join(item[1] for item in result if item and len(item) > 1 and item[1])


def ocr_cert_file(path: str, ext: str) -> str:
    """对磁盘上的证书文件执行 OCR, 返回拼接文本 (本地存储用)。

    - 图片: 直接解码识别
    - PDF: 复用 document_parser 按页提取 (文本层/扫描页自动处理), 仅前 2 页
    """
    ext = (ext or "").lower()
    if ext in IMAGE_EXTS:
        with open(path, "rb") as f:
            return _ocr_image_bytes(f.read())
    if ext == ".pdf":
        from src.tools.document_parser import extract_pages_pdf
        pages, _ocr_pages, _meta = extract_pages_pdf(path)
        return "\n".join(p["text"] for p in pages[:_MAX_PDF_PAGES])
    raise ValueError(f"不支持的证书格式: {ext}")


def ocr_cert_bytes(data: bytes, ext: str) -> str:
    """直接对上传字节执行 OCR (存储后端无关, S3 场景不落临时盘)。

    - 图片: 内存解码识别
    - PDF: 写系统临时文件供 pymupdf 提取, 完成后立即删除
    """
    ext = (ext or "").lower()
    if ext in IMAGE_EXTS:
        return _ocr_image_bytes(data)
    if ext == ".pdf":
        import tempfile
        from src.tools.document_parser import extract_pages_pdf
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        try:
            tmp.write(data)
            tmp.flush()
            tmp.close()
            pages, _ocr_pages, _meta = extract_pages_pdf(tmp.name)
            return "\n".join(p["text"] for p in pages[:_MAX_PDF_PAGES])
        finally:
            try:
                Path(tmp.name).unlink(missing_ok=True)
            except OSError:
                pass
    raise ValueError(f"不支持的证书格式: {ext}")


# ---- 附件私有存储 (uploads/certs/{user_id}/{uuid}{ext}) ----

# 仓库根/uploads (与 data/ 同级), 已在 .gitignore 忽略
CERT_UPLOAD_DIR = Path(__file__).resolve().parents[2] / "uploads" / "certs"


def _user_dir(user_id: int) -> Path:
    d = CERT_UPLOAD_DIR / str(int(user_id))
    d.mkdir(parents=True, exist_ok=True)
    return d


def _validate_token(file_token: str) -> str:
    """token 白名单校验 (uuidhex+扩展名); 非法抛 FileNotFoundError。"""
    if not re.fullmatch(r"[0-9a-f]{32}(?:\.[a-z0-9]+)?", file_token or ""):
        raise FileNotFoundError(file_token)
    ext = os.path.splitext(file_token)[1].lower()
    if ext and ext not in CERT_EXTS:
        raise FileNotFoundError(file_token)
    return file_token


def save_cert_file(user_id: int, filename: str, data: bytes) -> dict:
    """存储证书原件, 返回 {file_token, file_name, ext, size}。委托给默认 CertStorage。"""
    return get_cert_storage().save(user_id, filename, data)


def cert_file_path(user_id: int, file_token: str) -> Path:
    """解析本地证书文件的绝对路径; 非本地存储/非法 token/越权 → FileNotFoundError。"""
    return get_cert_storage().path(user_id, file_token)


def read_cert_file(user_id: int, file_token: str) -> bytes:
    """读取证书原件字节 (本地/S3 统一接口, 已做用户目录隔离校验)。"""
    return get_cert_storage().read(user_id, file_token)


def delete_cert_file(user_id: int, file_token: str) -> None:
    get_cert_storage().delete(user_id, file_token)


def cleanup_orphan_certs(user_id: int, keep_tokens: set[str]) -> int:
    """整表 PUT 后清理"旧档案有、新档案无"的孤儿证书文件, 返回删除数。"""
    return get_cert_storage().cleanup(user_id, keep_tokens)


# ============ R11: 证书存储抽象层 (可插拔: 本地/S3) ============
from abc import ABC, abstractmethod

_CERT_CONTENT_TYPES = {
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".bmp": "image/bmp", ".webp": "image/webp", ".pdf": "application/pdf",
}


class CertStorage(ABC):
    """证书原件存储抽象基类。实现需保证:
    - file_token = uuidhex+扩展名, 不暴露真实文件名;
    - read()/path() 校验 token 合法性与用户目录隔离 (防穿越/越权);
    - cleanup() 整表保存后清理孤儿文件。
    """

    @abstractmethod
    def save(self, user_id: int, filename: str, data: bytes) -> dict:
        ...

    @abstractmethod
    def read(self, user_id: int, file_token: str) -> bytes:
        ...

    def path(self, user_id: int, file_token: str) -> Path:
        """仅本地存储支持; 对象存储无本地路径, 抛 NotImplementedError。"""
        raise NotImplementedError(f"{type(self).__name__} 无本地路径, 请用 read()")

    @abstractmethod
    def delete(self, user_id: int, file_token: str) -> None:
        ...

    @abstractmethod
    def cleanup(self, user_id: int, keep_tokens: set[str]) -> int:
        ...

    def presigned_url(self, user_id: int, file_token: str,
                      expires_min: int = 10) -> str | None:
        """对象存储可返回限时预签名 URL; 本地存储返回 None (走应用鉴权代理)。"""
        return None


class LocalCertStorage(CertStorage):
    """本地磁盘存储: uploads/certs/{user_id}/{uuidhex+ext}。"""

    def save(self, user_id: int, filename: str, data: bytes) -> dict:
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in CERT_EXTS:
            raise ValueError(f"不支持的证书格式 {ext}")
        if len(data) > MAX_CERT_BYTES:
            raise ValueError(f"证书文件超过 {MAX_CERT_BYTES // 1024 // 1024}MB 上限")
        token = f"{uuid.uuid4().hex}{ext}"
        _user_dir(user_id).joinpath(token).write_bytes(data)
        return {"file_token": token, "file_name": filename, "ext": ext, "size": len(data)}

    def path(self, user_id: int, file_token: str) -> Path:
        _validate_token(file_token)
        base = _user_dir(user_id).resolve()
        p = (base / file_token).resolve()
        if p.parent != base or not p.is_file():
            raise FileNotFoundError(file_token)
        return p

    def read(self, user_id: int, file_token: str) -> bytes:
        return self.path(user_id, file_token).read_bytes()

    def delete(self, user_id: int, file_token: str) -> None:
        try:
            self.path(user_id, file_token).unlink()
        except FileNotFoundError:
            pass

    def cleanup(self, user_id: int, keep_tokens: set[str]) -> int:
        removed = 0
        try:
            for p in _user_dir(user_id).iterdir():
                if p.is_file() and p.name not in keep_tokens:
                    try:
                        p.unlink()
                        removed += 1
                    except OSError:
                        pass
        except FileNotFoundError:
            pass
        return removed


class S3CertStorage(CertStorage):
    """S3 兼容对象存储 (AWS S3 / MinIO): key = {prefix}{user_id}/{uuidhex+ext}。

    - boto3 懒加载 (仅 storage_type=s3 时需要);
    - MinIO/自建网关通过 endpoint_url + path-style addressing 适配;
    - auto_bucket=true 时启动自动建桶 (需有 ListAllMyBuckets/CreateBucket 权限);
    - read 走 get_object 由应用鉴权代理内联返回; 也可用 presigned_url 重定向直传。
    """

    def __init__(self, bucket: str, prefix: str = "certs/", endpoint_url: str = "",
                 region: str = "", access_key: str = "", secret_key: str = "",
                 auto_bucket: bool = True, presign_min: int = 10,
                 client=None):
        self.bucket = bucket
        self.prefix = prefix if prefix.endswith("/") else prefix + "/"
        self.endpoint_url = endpoint_url
        self.region = region
        self.access_key = access_key
        self.secret_key = secret_key
        self.auto_bucket = auto_bucket
        self.presign_min = presign_min
        self._client = client  # 测试可注入 Stubber 包装的 client

    def _s3(self):
        if self._client is not None:
            return self._client
        import boto3
        from botocore.config import Config
        cfg = Config(s3={"addressing_style": "path"}, signature_version="s3v4")
        kw = {"config": cfg}
        if self.endpoint_url:
            kw["endpoint_url"] = self.endpoint_url
        if self.region:
            kw["region_name"] = self.region
        if self.access_key:
            kw["aws_access_key_id"] = self.access_key
            kw["aws_secret_access_key"] = self.secret_key
        self._client = boto3.client("s3", **kw)
        if self.auto_bucket:
            self._ensure_bucket(self._client)
        return self._client

    def _ensure_bucket(self, client) -> None:
        from botocore.exceptions import ClientError
        try:
            client.head_bucket(Bucket=self.bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchBucket"):
                create_kw = {"Bucket": self.bucket}
                if self.region and not self.endpoint_url:
                    create_kw["CreateBucketConfiguration"] = {
                        "LocationConstraint": self.region}
                client.create_bucket(**create_kw)
                logger.info("已自动创建证书存储桶 %s", self.bucket)
            else:
                raise

    def _key(self, user_id: int, file_token: str) -> str:
        _validate_token(file_token)
        return f"{self.prefix}{int(user_id)}/{file_token}"

    def save(self, user_id: int, filename: str, data: bytes) -> dict:
        ext = os.path.splitext(filename or "")[1].lower()
        if ext not in CERT_EXTS:
            raise ValueError(f"不支持的证书格式 {ext}")
        if len(data) > MAX_CERT_BYTES:
            raise ValueError(f"证书文件超过 {MAX_CERT_BYTES // 1024 // 1024}MB 上限")
        token = f"{uuid.uuid4().hex}{ext}"
        # S3 用户元数据只接受 ASCII: 中文原名 URL 编码后存放 (读取方 unquote 还原)
        from urllib.parse import quote
        self._s3().put_object(
            Bucket=self.bucket, Key=self._key(user_id, token), Body=data,
            ContentType=_CERT_CONTENT_TYPES.get(ext, "application/octet-stream"),
            Metadata={"original_name": quote(filename[:128], safe="")})
        return {"file_token": token, "file_name": filename, "ext": ext, "size": len(data)}

    def read(self, user_id: int, file_token: str) -> bytes:
        from botocore.exceptions import ClientError
        try:
            resp = self._s3().get_object(
                Bucket=self.bucket, Key=self._key(user_id, file_token))
            return resp["Body"].read()
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code", "")
            if code in ("404", "NoSuchKey"):
                raise FileNotFoundError(file_token)
            raise

    def delete(self, user_id: int, file_token: str) -> None:
        from botocore.exceptions import ClientError
        try:
            self._s3().delete_object(
                Bucket=self.bucket, Key=self._key(user_id, file_token))
        except (FileNotFoundError, ClientError):
            pass

    def cleanup(self, user_id: int, keep_tokens: set[str]) -> int:
        """列举该用户前缀下的对象, 删除不在保留集合中的, 批量 1000/批。"""
        from botocore.exceptions import ClientError
        prefix = f"{self.prefix}{int(user_id)}/"
        removed = 0
        token_to_key: dict[str, str] = {}
        try:
            paginator = self._s3().get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents") or []:
                    name = item["Key"].rsplit("/", 1)[-1]
                    if name and name not in keep_tokens:
                        token_to_key[name] = item["Key"]
        except ClientError as e:
            logger.warning("S3 列举孤儿证书失败 user=%s: %s", user_id, e)
            return 0
        keys = list(token_to_key.values())
        for i in range(0, len(keys), 1000):
            batch = keys[i:i + 1000]
            try:
                self._s3().delete_objects(Bucket=self.bucket, Delete={
                    "Objects": [{"Key": k} for k in batch], "Quiet": True})
                removed += len(batch)
            except ClientError as e:
                logger.warning("S3 批量删除失败: %s", e)
        return removed

    def presigned_url(self, user_id: int, file_token: str,
                      expires_min: int | None = None) -> str | None:
        _validate_token(file_token)
        return self._s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": self._key(user_id, file_token)},
            ExpiresIn=(expires_min or self.presign_min) * 60)


_default_storage: CertStorage | None = None


def _build_default_storage() -> CertStorage:
    from src.config import settings
    if settings.cert_storage_type == "s3":
        return S3CertStorage(
            bucket=settings.cert_s3_bucket, prefix=settings.cert_s3_prefix,
            endpoint_url=settings.cert_s3_endpoint, region=settings.cert_s3_region,
            access_key=settings.cert_s3_access_key, secret_key=settings.cert_s3_secret_key,
            auto_bucket=settings.cert_s3_auto_bucket,
            presign_min=settings.cert_s3_presign_min)
    return LocalCertStorage()


def get_cert_storage() -> CertStorage:
    """获取默认证书存储实现 (CERT_STORAGE_TYPE=local|s3, 默认 local)。"""
    global _default_storage
    if _default_storage is None:
        _default_storage = _build_default_storage()
    return _default_storage


def reset_cert_storage() -> None:
    """重置缓存的默认存储 (配置变更/测试用)。"""
    global _default_storage
    _default_storage = None

