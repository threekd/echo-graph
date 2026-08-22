/* 力导向布局计算(独立线程):复用 layout.ts 的纯函数,避免与主线程算法漂移。 */
import { createForceLayout } from "./layout";

interface WorkerGlobalLike {
  onmessage: ((e: MessageEvent) => void) | null;
  postMessage: (message: unknown) => void;
}

const workerSelf = self as unknown as WorkerGlobalLike;

workerSelf.onmessage = function (e: MessageEvent) {
  const data = (e.data || {}) as {
    ids?: string[];
    edges?: { source: string; target: string }[];
    positions?: Record<string, number[]>;
  };
  const layout = createForceLayout(data.ids || [], data.edges || [], data.positions || {});
  while (!layout.tick(100)) { /* 在 Worker 内连续计算 */ }
  workerSelf.postMessage({ positions: layout.result() });
};
