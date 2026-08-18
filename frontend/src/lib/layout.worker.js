/* 力导向布局计算(独立线程):主图谱大数据量时避免阻塞主线程。
   算法与 renderer.js 主线程回退版保持一致,返回 {id: [x, y, z]}。 */

self.onmessage = function (e) {
  var ids = e.data.ids || [];
  var edges = e.data.edges || [];
  var positions = {};
  ids.forEach(function (id) {
    var u = Math.random() * 2 - 1;
    var th = Math.random() * Math.PI * 2;
    var s = Math.sqrt(Math.max(0, 1 - u * u));
    var r = 320 + Math.random() * 320;
    positions[id] = [r * s * Math.cos(th), r * u, r * s * Math.sin(th)];
  });

  var k = 850 / Math.sqrt(ids.length || 1);
  var temp = 0.62;
  var iters = 260;
  for (var it = 0; it < iters; it++) {
    var disp = {};
    ids.forEach(function (id) { disp[id] = [0, 0, 0]; });
    for (var i = 0; i < ids.length; i++) {
      for (var j = i + 1; j < ids.length; j++) {
        var a = ids[i], b = ids[j];
        var pa = positions[a], pb = positions[b];
        var dx = pa[0] - pb[0], dy = pa[1] - pb[1], dz = pa[2] - pb[2];
        var d = Math.max(Math.sqrt(dx * dx + dy * dy + dz * dz), 0.01);
        var force = (k * k) / d;
        var nx = dx / d, ny = dy / d, nz = dz / d;
        disp[a][0] += nx * force; disp[a][1] += ny * force; disp[a][2] += nz * force;
        disp[b][0] -= nx * force; disp[b][1] -= ny * force; disp[b][2] -= nz * force;
      }
    }
    edges.forEach(function (ed) {
      var pa = positions[ed.source], pb = positions[ed.target];
      if (!pa || !pb) return;
      var dx = pa[0] - pb[0], dy = pa[1] - pb[1], dz = pa[2] - pb[2];
      var d = Math.max(Math.sqrt(dx * dx + dy * dy + dz * dz), 0.01);
      var force = (d * d) / k;
      var nx = dx / d, ny = dy / d, nz = dz / d;
      disp[ed.source][0] -= nx * force; disp[ed.source][1] -= ny * force; disp[ed.source][2] -= nz * force;
      disp[ed.target][0] += nx * force; disp[ed.target][1] += ny * force; disp[ed.target][2] += nz * force;
    });
    ids.forEach(function (id) {
      var dl = Math.sqrt(disp[id][0] * disp[id][0] + disp[id][1] * disp[id][1] + disp[id][2] * disp[id][2]);
      if (dl < 0.0001) return;
      var step = Math.min(dl, 220) * temp / dl;
      positions[id][0] += disp[id][0] * step;
      positions[id][1] += disp[id][1] * step;
      positions[id][2] += disp[id][2] * step;
      positions[id][0] *= 1 - 0.0035;
      positions[id][1] *= 1 - 0.0035;
      positions[id][2] *= 1 - 0.0035;
    });
    temp = Math.max(0.02, temp * 0.965);
  }

  var meanR = 0;
  ids.forEach(function (id) {
    meanR += Math.sqrt(positions[id][0] * positions[id][0] + positions[id][1] * positions[id][1] + positions[id][2] * positions[id][2]);
  });
  meanR = meanR / Math.max(ids.length, 1);
  var scale = 520 / Math.max(meanR, 1);
  var out = {};
  ids.forEach(function (id) {
    out[id] = [positions[id][0] * scale, positions[id][1] * scale, positions[id][2] * scale];
  });
  self.postMessage({ positions: out });
};
