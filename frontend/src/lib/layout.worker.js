/* 力导向布局计算(独立线程):复用 layout.js 的纯函数,避免与主线程算法漂移。 */
import { createForceLayout } from "./layout.js";

self.onmessage = function (e) {
  var layout = createForceLayout(e.data.ids || [], e.data.edges || []);
  while (!layout.tick(100)) { /* 在 Worker 内连续计算 */ }
  self.postMessage({
    positions: layout.result(),
  });
};
