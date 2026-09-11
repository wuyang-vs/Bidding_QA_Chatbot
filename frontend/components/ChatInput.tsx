"use client";
import { useRef, useState } from "react";
import { Paperclip, Globe, Brain, X, Send, Loader2 } from "lucide-react";

const MAX_IMAGE_FILE_MB = 10;

async function compressImage(file: File): Promise<string> {
  const img = await new Promise<HTMLImageElement>((resolve, reject) => {
    const i = new Image();
    i.onload = () => resolve(i);
    i.onerror = reject;
    i.src = URL.createObjectURL(file);
  });
  const scale = Math.min(1, 1024 / Math.max(img.width, img.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(img.width * scale);
  canvas.height = Math.round(img.height * scale);
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL("image/jpeg", 0.85).split(",")[1];
}

interface Props {
  onSend: (content: string, image?: { base64: string; name: string }) => void;
  webSearch: boolean;
  setWebSearch: (v: boolean) => void;
  deepThinking: boolean;
  setDeepThinking: (v: boolean) => void;
  loading?: boolean;
}

export function ChatInput({
  onSend, webSearch, setWebSearch, deepThinking, setDeepThinking, loading,
}: Props) {
  const [value, setValue] = useState("");
  const [image, setImage] = useState<{ base64: string; name: string } | null>(null);
  const [imageError, setImageError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.nativeEvent.isComposing) return;
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const submit = () => {
    if (loading) return;
    if (!value.trim() && !image) return;
    onSend(value.trim(), image || undefined);
    setValue("");
    setImage(null);
    setImageError("");
  };

  const onFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    if (f.size > MAX_IMAGE_FILE_MB * 1024 * 1024) {
      setImageError(`图片不能超过 ${MAX_IMAGE_FILE_MB}MB`);
      return;
    }
    try {
      const base64 = await compressImage(f);
      setImage({ base64, name: f.name });
      setImageError("");
    } catch {
      setImageError("图片解析失败");
    }
  };

  return (
    <div className="border border-gray-300 dark:border-gray-700 rounded-2xl p-3 bg-white dark:bg-gray-800 shadow-sm">
      {image && (
        <div className="flex items-center gap-2 mb-2 text-xs text-gray-600 dark:text-gray-300">
          <img src={`data:image/jpeg;base64,${image.base64}`} alt="" className="w-12 h-12 object-cover rounded" />
          <span className="truncate flex-1">{image.name}</span>
          <button onClick={() => setImage(null)} className="text-gray-400 hover:text-red-500">
            <X size={14} />
          </button>
        </div>
      )}
      {imageError && <div className="text-xs text-red-500 mb-1">{imageError}</div>}

      <textarea
        className="w-full resize-none outline-none bg-transparent text-sm"
        rows={2}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="输入招投标问题，Enter 发送，Shift+Enter 换行..."
      />

      <div className="flex items-center gap-3 mt-1">
        <button onClick={() => fileRef.current?.click()}
                className="text-gray-400 hover:text-gray-600 transition" title="插入图像">
          <Paperclip size={16} />
        </button>
        <input ref={fileRef} type="file" accept="image/*" className="hidden" onChange={onFile} />

        <button onClick={() => setWebSearch(!webSearch)}
                className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full transition ${
                  webSearch ? "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300"
                            : "text-gray-400 hover:text-gray-600"}`}
                title="联网搜索">
          <Globe size={14} /> 联网搜索
        </button>

        <button onClick={() => setDeepThinking(!deepThinking)}
                className={`flex items-center gap-1 text-xs px-2 py-1 rounded-full transition ${
                  deepThinking ? "bg-purple-100 text-purple-700 dark:bg-purple-900 dark:text-purple-300"
                               : "text-gray-400 hover:text-gray-600"}`}
                title="深度思考">
          <Brain size={14} /> 深度思考
        </button>

        <button onClick={submit} disabled={loading || (!value.trim() && !image)}
                className="ml-auto flex items-center gap-1 px-3 py-1.5 bg-blue-600 text-white rounded-lg text-sm
                           hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed transition">
          {loading ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
          发送
        </button>
      </div>
    </div>
  );
}
