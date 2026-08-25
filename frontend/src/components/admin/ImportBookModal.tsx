/* 书籍导入弹窗:上传电子书 → 后端 AI 提取 → 推送到 AI 草稿(system_llm 空间)。
   提交后轮询任务状态,展示阶段进度、日志与最终结果。 */

import { useEffect, useRef, useState } from "react";
import type { BookImportTask } from "../../lib/adminTypes";

const ACCEPT = ".epub,.txt,.mobi,.azw,.azw3,.fb2,.html,.htm";
const POLL_MS = 1500;

const fmtSize = (n: number): string =>
  n >= 1024 * 1024 ? (n / (1024 * 1024)).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";

interface Props {
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onClose: () => void;
  onStatus: (msg: string) => void;
}

export default function ImportBookModal({ authFetch, onClose, onStatus }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [authors, setAuthors] = useState("");
  const [noRipples, setNoRipples] = useState(false);
  const [basicOnly, setBasicOnly] = useState(false);
  const [phase, setPhase] = useState<"form" | "running" | "done" | "error">("form");
  const [task, setTask] = useState<BookImportTask | null>(null);
  const [message, setMessage] = useState("");
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    };
  }, []);

  const poll = (taskId: string) => {
    authFetch("/api/admin/import-book/" + encodeURIComponent(taskId))
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || "查询任务失败(HTTP " + r.status + ")");
        return d as BookImportTask;
      })
      .then((t) => {
        setTask(t);
        if (t.status === "queued" || t.status === "running") {
          timerRef.current = window.setTimeout(() => poll(taskId), POLL_MS);
        } else if (t.status === "done") {
          setPhase("done");
          onStatus("书籍导入完成,已推送 AI 草稿(批次 " + (t.result?.batch_id || "") + ")");
        } else {
          setPhase("error");
          setMessage(t.error || "导入失败");
          onStatus("书籍导入失败");
        }
      })
      .catch((e: Error) => {
        setPhase("error");
        setMessage(e.message);
        onStatus("书籍导入失败");
      });
  };

  const submit = () => {
    if (!file) return;
    const q = new URLSearchParams();
    if (title.trim()) q.set("title", title.trim());
    if (authors.trim()) q.set("authors", authors.trim());
    if (noRipples) q.set("no_ripples", "true");
    if (basicOnly) q.set("basic_only", "true");
    const query = q.toString();
    setPhase("running");
    setMessage("");
    authFetch("/api/admin/import-book" + (query ? "?" + query : ""), {
      method: "POST",
      headers: { "X-Filename": encodeURIComponent(file.name) },
      body: file,
    })
      .then(async (r) => {
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(d.detail || "提交失败(HTTP " + r.status + ")");
        return d as { task_id: string };
      })
      .then((d) => poll(d.task_id))
      .catch((e: Error) => {
        setPhase("error");
        setMessage(e.message);
        onStatus("书籍导入提交失败");
      });
  };

  const resetToForm = () => {
    setPhase("form");
    setTask(null);
    setMessage("");
  };

  return (
    <div id="auth-modal">
      <div className="auth-modal-card import-card">
        <h3>导入书籍 → AI 草稿</h3>

        {phase === "form" && (
          <>
            <label>
              电子书文件(epub / txt 最佳;mobi 等需服务器 calibre)
              <input
                type="file"
                accept={ACCEPT}
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </label>
            {file && <p className="import-file">已选择:{file.name}({fmtSize(file.size)})</p>}
            <label>
              书名(可选,覆盖元数据)
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="留空则读取书籍元数据"
              />
            </label>
            <label>
              作者(可选,多个用逗号分隔)
              <input
                value={authors}
                onChange={(e) => setAuthors(e.target.value)}
                placeholder="留空则读取书籍元数据"
              />
            </label>
            <label className="import-check">
              <span>
                <input
                  type="checkbox"
                  checked={noRipples}
                  onChange={(e) => setNoRipples(e.target.checked)}
                />
                只提取作者/作品(跳过涟漪,更快)
              </span>
            </label>
            <label className="import-check">
              <span>
                <input
                  type="checkbox"
                  checked={basicOnly}
                  onChange={(e) => setBasicOnly(e.target.checked)}
                />
                去重只做基础匹配(不调用语义 embedding,更省时)
              </span>
            </label>
            <p className="import-tip">
              AI 解析后推送到「AI 草稿」(system_llm 空间),由管理员在 AI 草稿页按
              作者 → 作品 → 涟漪 顺序审核/批准发布。解析可能需要数分钟。
            </p>
            <div className="admin-modal-actions">
              <button onClick={onClose}>取消</button>
              <button disabled={!file} onClick={submit}>开始导入</button>
            </div>
          </>
        )}

        {phase === "running" && (
          <>
            <p className="import-progress">{task?.stage || "任务排队中…"}</p>
            <pre className="import-log">{(task?.log || []).join("\n")}</pre>
            <div className="admin-modal-actions">
              <button onClick={onClose}>后台执行,先关闭窗口</button>
            </div>
          </>
        )}

        {phase === "done" && task?.result && (
          <>
            <p className="import-done">导入完成,已推送到 AI 草稿:</p>
            <ul className="import-summary">
              <li>
                AI 提取:作者 {task.result.extracted.authors} · 作品{" "}
                {task.result.extracted.works} · 涟漪 {task.result.extracted.edges}
              </li>
              <li>
                草稿入库:{task.result.counts.staged} 条新增 · {task.result.counts.already} 条已处理
                · {task.result.counts.failed} 条失败
              </li>
            </ul>
            <pre className="import-log">{(task.log || []).join("\n")}</pre>
            <div className="admin-modal-actions">
              <button onClick={onClose}>关闭</button>
            </div>
          </>
        )}

        {phase === "error" && (
          <>
            <p className="import-error">导入失败:{message}</p>
            <pre className="import-log">{(task?.log || []).join("\n")}</pre>
            <div className="admin-modal-actions">
              <button onClick={resetToForm}>重试</button>
              <button onClick={onClose}>关闭</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
