import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "招投标智能问答",
  description: "基于知识库、知识图谱、结构化数据库与联网搜索的招投标问答机器人",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <head>
        <script
          dangerouslySetInnerHTML={{
            __html: `try{
              var s=localStorage.getItem('chat_dark_mode');
              if(s==='1'||(s===null&&matchMedia('(prefers-color-scheme: dark)').matches)){
                document.documentElement.classList.add('dark');
              }
            }catch(e){}`,
          }}
        />
      </head>
      <body>{children}</body>
    </html>
  );
}
