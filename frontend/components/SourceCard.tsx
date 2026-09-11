import { ExternalLink } from "lucide-react";

interface Source {
  question: string;
  answer: string;
  score: number;
  url?: string;
}

export function SourceCard({ source }: { source: Source }) {
  const isWeb = Boolean(source.url);
  const pct = Math.round((source.score || 0) * 100);

  return (
    <div className="border border-gray-200 dark:border-gray-700 rounded-lg p-2 text-xs bg-gray-50 dark:bg-gray-800">
      <div className="flex items-start justify-between gap-2">
        <div className="font-medium text-gray-700 dark:text-gray-200 truncate flex-1">
          {source.question || (isWeb ? "网页来源" : "知识库来源")}
        </div>
        <span className={`shrink-0 px-1.5 py-0.5 rounded text-[10px] ${
          pct >= 70 ? "bg-green-100 text-green-700" :
          pct >= 40 ? "bg-yellow-100 text-yellow-700" :
          "bg-gray-100 text-gray-600"}`}>
          {pct}%
        </span>
      </div>
      <div className="text-gray-500 dark:text-gray-400 mt-1 line-clamp-3 whitespace-pre-wrap">
        {source.answer}
      </div>
      {isWeb && (
        <a href={source.url} target="_blank" rel="noopener noreferrer"
           className="inline-flex items-center gap-1 text-blue-500 hover:underline mt-1">
          <ExternalLink size={10} /> 打开链接
        </a>
      )}
    </div>
  );
}
