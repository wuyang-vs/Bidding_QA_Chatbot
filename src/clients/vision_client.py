"""智谱 glm-4.6v-flashx 图片解析"""
from zai import ZhipuAiClient
from src.config import settings

VISION_MODEL = "glm-4.6v-flashx"


class VisionClient:
    def __init__(self):
        self._client = ZhipuAiClient(api_key=settings.zhipu_api_key) if settings.zhipu_api_key else None

    @property
    def ready(self) -> bool:
        return self._client is not None

    def analyze(self, image_base64: str, prompt: str = "请详细描述这张图片的内容") -> dict:
        if not self._client:
            raise RuntimeError("视觉服务未就绪")
        resp = self._client.chat.completions.create(
            model=VISION_MODEL,
            messages=[{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}},
                {"type": "text", "text": prompt},
            ]}],
        )
        return {"analysis": resp.choices[0].message.content, "model": VISION_MODEL}


vision_client = VisionClient()
