/* 力导向 3D 布局(纯计算,主线程与 Web Worker 共用,单一算法来源)。
   支持分帧执行:tick(maxMs) 每帧只算一小段,避免大数据量时卡顿。 */

export interface ForceEdge {
  source: string;
  target: string;
}

export interface ForceLayout {
  tick(maxMs: number): boolean;
  result(): Record<string, number[]>;
}

export function createForceLayout(
  ids: string[],
  edges: ForceEdge[],
  initial?: Record<string, number[]>,
): ForceLayout {
  const positions: Record<string, number[]> = {};
  ids.forEach(function (id) {
    // 同视图刷新时用上一次布局位置作初始种子,避免每次扩散节点整体跳位
    const prev = initial && initial[id];
    if (prev && prev.length === 3 && prev.every(Number.isFinite)) {
      positions[id] = [prev[0], prev[1], prev[2]];
      return;
    }
    const u = Math.random() * 2 - 1;
    const th = Math.random() * Math.PI * 2;
    const s = Math.sqrt(Math.max(0, 1 - u * u));
    const r = 320 + Math.random() * 320;
    positions[id] = [r * s * Math.cos(th), r * u, r * s * Math.sin(th)];
  });

  const k = 850 / Math.sqrt(ids.length || 1);
  let temp = 0.62;
  const iters = 260;
  let it = 0;

  function runIteration() {
    const disp: Record<string, number[]> = {};
    ids.forEach(function (id) { disp[id] = [0, 0, 0]; });
    for (let i = 0; i < ids.length; i++) {
      for (let j = i + 1; j < ids.length; j++) {
        const a = ids[i], b = ids[j];
        const pa = positions[a], pb = positions[b];
        const dx = pa[0] - pb[0], dy = pa[1] - pb[1], dz = pa[2] - pb[2];
        const d = Math.max(Math.sqrt(dx * dx + dy * dy + dz * dz), 0.01);
        const force = (k * k) / d;
        const nx = dx / d, ny = dy / d, nz = dz / d;
        disp[a][0] += nx * force; disp[a][1] += ny * force; disp[a][2] += nz * force;
        disp[b][0] -= nx * force; disp[b][1] -= ny * force; disp[b][2] -= nz * force;
      }
    }
    edges.forEach(function (ed) {
      const pa = positions[ed.source], pb = positions[ed.target];
      if (!pa || !pb) return;
      const dx = pa[0] - pb[0], dy = pa[1] - pb[1], dz = pa[2] - pb[2];
      const d = Math.max(Math.sqrt(dx * dx + dy * dy + dz * dz), 0.01);
      const force = (d * d) / k;
      const nx = dx / d, ny = dy / d, nz = dz / d;
      disp[ed.source][0] -= nx * force; disp[ed.source][1] -= ny * force; disp[ed.source][2] -= nz * force;
      disp[ed.target][0] += nx * force; disp[ed.target][1] += ny * force; disp[ed.target][2] += nz * force;
    });
    ids.forEach(function (id) {
      const dl = Math.sqrt(disp[id][0] * disp[id][0] + disp[id][1] * disp[id][1] + disp[id][2] * disp[id][2]);
      if (dl < 0.0001) return;
      const step = Math.min(dl, 220) * temp / dl;
      positions[id][0] += disp[id][0] * step;
      positions[id][1] += disp[id][1] * step;
      positions[id][2] += disp[id][2] * step;
      positions[id][0] *= 1 - 0.0035;
      positions[id][1] *= 1 - 0.0035;
      positions[id][2] *= 1 - 0.0035;
    });
    temp = Math.max(0.02, temp * 0.965);
  }

  return {
    tick: function (maxMs) {
      const start = Date.now();
      while (it < iters && Date.now() - start < maxMs) {
        runIteration();
        it++;
      }
      return it >= iters;
    },
    result: function () {
      let meanR = 0;
      ids.forEach(function (id) {
        meanR += Math.sqrt(
          positions[id][0] * positions[id][0] +
          positions[id][1] * positions[id][1] +
          positions[id][2] * positions[id][2]
        );
      });
      meanR = meanR / Math.max(ids.length, 1);
      const scale = 520 / Math.max(meanR, 1);
      const out: Record<string, number[]> = {};
      ids.forEach(function (id) {
        out[id] = [
          positions[id][0] * scale,
          positions[id][1] * scale,
          positions[id][2] * scale,
        ];
      });
      return out;
    },
  };
}
