/* 书籍导入弹窗:上传电子书 → 后端 AI 提取 → 推送到上传者的 AI 草稿。
   提交后轮询任务状态,展示阶段进度、日志与最终结果。 */

import { useEffect, useRef, useState } from "react";
import type { BookImportTask } from "../../lib/adminTypes";

const ACCEPT = ".epub,.txt,.mobi,.azw,.azw3,.fb2,.html,.htm";
const MAX_BOOK_BYTES = 20 * 1024 * 1024; // 与后端 app/book_import.MAX_BOOK_BYTES 一致(20MB)
const POLL_MS = 1500;

const fmtSize = (n: number): string =>
  n >= 1024 * 1024 ? (n / (1024 * 1024)).toFixed(1) + " MB" : Math.max(1, Math.round(n / 1024)) + " KB";

interface Props {
  authFetch: (url: string, options?: RequestInit) => Promise<Response>;
  onClose: () => void;
  onStatus: (msg: string) => void;
  onImported?: () => void;
}

export default function ImportBookModal({ authFetch, onClose, onStatus, onImported }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [authors, setAuthors] = useState("");
  const [phase, setPhase] = useState<"form" | "running" | "done" | "error">("form");
  const [task, setTask] = useState<BookImportTask | null>(null);
  const [message, setMessage] = useState("");
  const [fileError, setFileError] = useState("");
  const timerRef = useRef<number | null>(null);
  const logRef = useRef<HTMLPreElement | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current != null) window.clearTimeout(timerRef.current);
    };
  }, []);

  // 日志更新时自动滚动到底部,保证展示的是最新输出
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [task?.log]);

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
          onImported?.();
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
    const query = q.toString();
    setPhase("running");
    setMessage("");
    authFetch("/api/admin/import-book" + (query ? "?" + query : ""), {
      method: "POST",
      headers: { "X-Filename": encodeURIComponent(file.name) },
      body: file,
    })
      .then(async (r) => {
        const d = await r.json().catch(() => null);
        if (!r.ok) {
          const detail = d && typeof d.detail === "string" && d.detail ? d.detail : null;
          throw new Error(
            detail ||
              (r.status === 413
                ? "上传被网关拒绝(文件过大)。请确认 nginx 已配置 client_max_body_size 20m 并 reload"
                : "提交失败(HTTP " + r.status + ")")
          );
        }
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
    setFileError("");
  };

  return (
    <div id="auth-modal">
      <div className="auth-modal-card import-card">
        <h3>导入书籍 → AI 草稿</h3>

        {phase === "form" && (
          <>
            <label>
              电子书文件(epub最佳; 支持mobi、azw、azw3等格式; ≤ 20MB)
              <input
                type="file"
                accept={ACCEPT}
                onChange={(e) => {
                  const f = e.target.files?.[0] || null;
                  if (f && f.size > MAX_BOOK_BYTES) {
                    setFile(null);
                    setFileError("文件过大(上限 20MB),请压缩或拆分后重试");
                    return;
                  }
                  setFile(f);
                  setFileError("");
                }}
              />
            </label>
            {fileError && <p className="import-error">{fileError}</p>}
            {file && <p className="import-file">已选择:{file.name}({fmtSize(file.size)})</p>}
            <label>
              书名(可选)
              <input
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="留空则读取书籍元数据"
              />
            </label>
            <label>
              作者(可选)
              <input
                value={authors}
                onChange={(e) => setAuthors(e.target.value)}
                placeholder="留空则读取书籍元数据"
              />
            </label>
            <div className="admin-modal-actions">
              <button onClick={onClose}>取消</button>
              <button disabled={!file} onClick={submit}>开始导入</button>
            </div>
          </>
        )}

        {phase === "running" && (
          <>
            <p className="import-progress">{task?.stage || "任务排队中…"}</p>
            <pre ref={logRef} className="import-log">{(task?.log || []).join("\n")}</pre>
            <div className="admin-modal-actions">
              <button onClick={onClose}>后台执行</button>
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
            <pre ref={logRef} className="import-log">{(task.log || []).join("\n")}</pre>
            <div className="admin-modal-actions">
              <button onClick={onClose}>关闭</button>
            </div>
          </>
        )}

        {phase === "error" && (
          <>
            <p className="import-error">导入失败:{message}</p>
            <pre ref={logRef} className="import-log">{(task?.log || []).join("\n")}</pre>
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
