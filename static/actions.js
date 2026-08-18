/* 数据加载与视图编排:图谱、搜索、路径、涟漪、作者视图、深链 */

import { el, esc } from "./util.js";
import { state } from "./state.js";
import { renderView, getCameraState, applyCameraState, toggleAuthorsInView } from "./renderer.js";
import {
  showEmptyPanel,
  showPickError,
  showNoPath,
  showToast,
  renderAuthorPanel,
  renderWorkPanel,
  renderPathPanel,
} from "./panels.js";

var rippleCenter = null;   // 当前涟漪视图的中心作品
var currentActionView = "main"; // 与异步布局解耦的"动作层"视图状态
var pathFromId = null;
var pathToId = null;
var currentAuthorId = null;
var urlLock = false;       // 应用 URL 期间禁止回写,避免循环
var lastHandledHash = null;

export function loadGraph() {
  return fetch("/api/graph")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      state.fullData = data;
      buildWorkLookups();
      if (location.search.indexOf("hideislands") !== -1) {
        el("hide-islands").checked = true; // 测试/分享参数
      }
      if (location.search.indexOf("authors=0") !== -1) {
        el("show-authors").checked = false; // 测试/分享参数
      }
      renderMain();
      showEmptyPanel();
    });
}

function buildWorkLookups() {
  state.workLookup = {};
  state.workById = {};
  state.fullData.nodes.filter(function (n) { return n.type === "work"; }).forEach(function (w) {
    var key = w.label + " - " + (w.author || "");
    state.workLookup[key] = w.id;
    state.workById[w.id] = w;
  });
}

function findNode(id) {
  return state.fullData.nodes.filter(function (n) { return n.id === id; })[0];
}

function countWorks(authorId) {
  return state.fullData.nodes.filter(function (n) {
    return n.type === "work" && n.author_id === authorId;
  }).length;
}

function isIslandsHidden() {
  return !!el("hide-islands") && el("hide-islands").checked;
}

function isAuthorsHidden() {
  return !!el("show-authors") && !el("show-authors").checked;
}

function filterAuthors(data) {
  if (!isAuthorsHidden()) return data;
  var ids = {};
  data.nodes.forEach(function (n) {
    if (n.type !== "author") ids[n.id] = true;
  });
  var nodes = data.nodes.filter(function (n) { return n.type !== "author"; });
  var edges = data.edges.filter(function (e) {
    return ids[e.source] && ids[e.target];
  });
  return {
    nodes: data.nodes.filter(function (n) { return !!ids[n.id]; }),
    edges: edges,
  };
}

// 给作品子图补充作者节点与归属边(尊重"显示作家节点"开关)
function addAuthorsTo(data) {
  if (isAuthorsHidden()) return data;
  var nodes = data.nodes.slice();
  var edges = data.edges.slice();
  var out = { nodes: nodes, edges: edges };
  Object.keys(data).forEach(function (k) {
    if (k !== "nodes" && k !== "edges") out[k] = data[k];
  });
  var have = {};
  nodes.forEach(function (n) { have[n.id] = true; });
  nodes.filter(function (n) { return n.type === "work"; }).forEach(function (w) {
    var aid = w.author_id;
    if (!aid) return;
    edges.push({ source: w.id, target: aid, type: "authored" });
    if (!have[aid]) {
      var an = findNode(aid);
      if (an) {
        nodes.push(an);
        have[aid] = true;
      }
    }
  });
  return out;
}

function filterIslands(data) {
  var deg = {};
  data.edges.forEach(function (e) {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  var visibleWork = {};
  var visibleAuthor = {};
  data.nodes.forEach(function (n) {
    if (n.type === "work") visibleWork[n.id] = (deg[n.id] || 0) > 0;
  });
  data.nodes.forEach(function (a) {
    if (a.type !== "author") return;
    visibleAuthor[a.id] = data.nodes.some(function (w) {
      return w.type === "work" && w.author_id === a.id && visibleWork[w.id];
    });
  });
  var nodes = data.nodes.filter(function (n) {
    return n.type === "work" ? !!visibleWork[n.id] : !!visibleAuthor[n.id];
  });
  var ids = {};
  nodes.forEach(function (n) { ids[n.id] = true; });
  var edges = data.edges.filter(function (e) {
    return ids[e.source] && ids[e.target];
  });
  return { nodes: nodes, edges: edges };
}

function countIslands(data) {
  var deg = {};
  data.edges.forEach(function (e) {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  return data.nodes.filter(function (n) {
    return n.type === "work" && !(deg[n.id] || 0);
  }).length;
}

// 默认规则(与"隐藏孤岛星"勾选框无关):
// 隐藏"孤岛星"——没有任何 ECHO 提及关系、且名下作品不超过 1 部的作者,连同其作品与归属边;
// 有提及关系的作品(哪怕作者名下仅此一部)保留。
function filterSingleWorkAuthors(data) {
  var workCount = {};
  var deg = {};
  data.nodes.forEach(function (n) {
    if (n.type !== "work" || !n.author_id) return;
    workCount[n.author_id] = (workCount[n.author_id] || 0) + 1;
  });
  data.edges.forEach(function (e) {
    if (e.type !== "echo") return;
    deg[e.source] = (deg[e.source] || 0) + 1;
    deg[e.target] = (deg[e.target] || 0) + 1;
  });
  var hidden = {};
  data.nodes.forEach(function (n) {
    if (n.type !== "author") return;
    var total = workCount[n.id] || 0;
    var hasEcho = data.nodes.some(function (w) {
      return w.type === "work" && w.author_id === n.id && (deg[w.id] || 0) > 0;
    });
    if (!hasEcho && total <= 1) hidden[n.id] = true;
  });
  var ids = {};
  data.nodes.forEach(function (n) {
    if (n.type === "author") {
      if (!hidden[n.id]) ids[n.id] = true;
    } else if (n.type === "work") {
      if (!hidden[n.author_id]) ids[n.id] = true;
    }
  });
  var nodes = data.nodes.filter(function (n) { return !!ids[n.id]; });
  var edges = data.edges.filter(function (e) {
    return ids[e.source] && ids[e.target];
  });
  return { nodes: nodes, edges: edges };
}

function renderMain(opts) {
  currentActionView = "main";
  var data = filterSingleWorkAuthors(state.fullData);
  if (isIslandsHidden()) data = filterIslands(data);
  data = filterAuthors(data);
  renderView("main", data, opts || { preserveCamera: true });
}

export function selectNode(id) {
  var node = findNode(id);
  if (!node) return;
  if (node.type === "work") {
    fetch("/api/work/" + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderRipple(d);     // 自动进入涟漪视图
        renderWorkPanel(d);  // 侧边栏显示详情
        showToast("已展开《" + node.label + "》的涟漪");
        syncUrl(true);
      });
  } else {
    renderAuthorView(node);  // 3D:该作者 + 他的书
    renderAuthorPanel(node);
    showToast("视图:作者 · " + node.label + "(" + countWorks(node.id) + " 部作品)");
    syncUrl(true);
  }
}

// 悬停节点:只显示右侧详情页,不切换 3D 视图
export function showNodeDetail(id) {
  var node = findNode(id);
  if (!node) return;
  if (node.type === "work") {
    fetch("/api/work/" + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderWorkPanel(d);
        el("panel").classList.add("show");
      });
  } else {
    renderAuthorPanel(node);
    el("panel").classList.add("show");
  }
}

function renderAuthorView(author) {
  currentActionView = "author";
  currentAuthorId = author.id;
  var nodes = [author];
  var edges = [];
  state.fullData.nodes.filter(function (n) {
    return n.type === "work" && n.author_id === author.id;
  }).forEach(function (w) {
    nodes.push(w);
    edges.push({ source: w.id, target: author.id, type: "authored" });
  });
  renderView("author", { nodes: nodes, edges: edges });
}

function renderRipple(detail) {
  currentActionView = "ripple";
  var center = detail.work.id;
  rippleCenter = center;
  el("expand-range").value = "1";
  el("expand-value").textContent = "1 级";
  var ids = {};
  ids[center] = true;
  var nodes = [];
  var edges = [];

  detail.mentioned_by.forEach(function (e) {
    ids[e.source] = true;
    edges.push({ source: e.source, target: center, type: "echo", evidence: e.evidence, note: e.note });
  });
  detail.mentions.forEach(function (e) {
    ids[e.target] = true;
    edges.push({ source: center, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
  });
  Object.keys(ids).forEach(function (id) {
    var n = findNode(id);
    if (!n) return;
    nodes.push(n);
  });

  renderView("ripple", addAuthorsTo({ nodes: nodes, edges: edges, centerId: center }));
}

function expandRipple() {
  if (!rippleCenter) return;
  var hops = parseInt(el("expand-range").value, 10) || 1;
  fetch("/api/expansion/" + encodeURIComponent(rippleCenter) + "?hops=" + hops)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      data = addAuthorsTo(data);
      renderView("ripple", data, { preserveCamera: true }); // 拖动滑动条时保持当前视角
      var works = data.nodes.filter(function (n) { return n.type === "work"; }).length;
      el("expand-value").textContent = hops + " 级 · " + works + " 本书";
      showToast(hops + " 级扩散 · " + works + " 本书");
      syncUrl(false);
    });
}

function findPath() {
  var f = el("from").value.trim();
  var t = el("to").value.trim();
  var fromId = state.workLookup[f];
  var toId = state.workLookup[t];
  pathFromId = fromId || null;
  pathToId = toId || null;
  if (!fromId || !toId) {
    showPickError();
    showToast("请从下拉列表中选择两部作品");
    return;
  }
  fetch("/api/path?from=" + encodeURIComponent(fromId) + "&to=" + encodeURIComponent(toId))
    .then(function (r) { return r.status === 404 ? null : r.json(); })
    .then(function (result) {
      if (!result) {
        showNoPath(f, t);
        showToast("未找到「" + f + " → " + t + "」的提及链");
        return;
      }
      renderPath(result, f, t);
      showToast("提及链 · " + result.nodes.length + " 本书 / " + result.edges.length + " 次提及");
      syncUrl(true);
    });
}

function renderPath(result, f, t) {
  currentActionView = "path";
  var nodes = [];
  var edges = [];
  var ids = {};
  result.nodes.forEach(function (id) {
    var n = findNode(id);
    if (n) { nodes.push(n); ids[id] = true; }
  });
  result.edges.forEach(function (e) {
    edges.push({ source: e.source, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
    [e.source, e.target].forEach(function (id) {
      if (!ids[id]) {
        var n = findNode(id);
        if (n) { nodes.push(n); ids[id] = true; }
      }
    });
  });
  renderView("path", { nodes: nodes, edges: edges, pathOrder: result.nodes });
  renderPathPanel(result, f, t);
}

// ---- 路径输入联想 ----
function setupPathAutocomplete(inputId, resultsId) {
  var input = el(inputId);
  var ul = el(resultsId);
  input.addEventListener("input", function () {
    var q = input.value.trim();
    if (!q) { ul.style.display = "none"; return; }
    fetch("/api/search?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var works = data.hits.filter(function (h) { return h.type === "work"; }).slice(0, 8);
        ul.innerHTML = "";
        if (!works.length) { ul.style.display = "none"; return; }
        works.forEach(function (h) {
          var node = state.workById[h.id];
          var li = document.createElement("li");
          li.innerHTML = "<strong>" + esc(h.label) + "</strong> <small>" + esc(h.sub || "") + "</small>";
          li.addEventListener("mousedown", function (ev) {
            ev.preventDefault();
            input.value = node ? node.label + " - " + (node.author || "") : h.label;
            ul.style.display = "none";
          });
          ul.appendChild(li);
        });
        ul.style.display = "block";
      });
  });
  input.addEventListener("keydown", function (e) {
    if (e.key === "Enter") findPath();
  });
  input.addEventListener("blur", function () {
    setTimeout(function () { ul.style.display = "none"; }, 150);
  });
}

function swapPath() {
  var a = el("from").value;
  el("from").value = el("to").value;
  el("to").value = a;
}

export function wireEvents() {
  el("btn-path").onclick = findPath;
  el("btn-back-main").onclick = function () {
    loadGraph().then(function () { syncUrl(true); });
  };
  el("btn-swap").onclick = swapPath;
  el("btn-example").onclick = function () {
    el("from").value = "伊利亚特 - 荷马";
    el("to").value = "活着 - 余华";
    findPath();
  };
  el("expand-range").addEventListener("input", expandRipple);
  el("hide-islands").addEventListener("change", function () {
    if (isIslandsHidden()) {
      showToast("已隐藏 " + countIslands(state.fullData) + " 座孤岛星");
    } else {
      showToast("已显示全部作品");
    }
    if (state.currentView === "main") renderMain();
    syncUrl(true);
  });
  el("show-authors").addEventListener("change", function () {
    showToast(isAuthorsHidden() ? "已隐藏作家节点" : "已显示作家节点");
    toggleAuthorsInView(isAuthorsHidden()); // 即时增删,不重新布局
    syncUrl(true);
  });
  el("btn-share").onclick = shareLink;
  el("btn-export-png").onclick = exportPng;
  el("btn-export-data").onclick = exportData;
  setupPathAutocomplete("from", "from-results");
  setupPathAutocomplete("to", "to-results");

  // 搜索联想 + 键盘导航
  var qInput = el("q");
  var qActive = -1;
  function highlight(items) {
    Array.prototype.forEach.call(items, function (li, i) {
      li.classList.toggle("active", i === qActive);
    });
    if (qActive >= 0 && items[qActive]) {
      items[qActive].scrollIntoView({ block: "nearest" });
    }
  }
  qInput.addEventListener("input", function () {
    qActive = -1;
    var q = qInput.value.trim();
    if (!q) { el("q-results").style.display = "none"; return; }
    fetch("/api/search?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (data) {
        var ul = el("q-results");
        ul.innerHTML = "";
        if (!data.hits.length) { ul.style.display = "none"; return; }
        data.hits.forEach(function (h) {
          var li = document.createElement("li");
          li.innerHTML = "<strong>" + esc(h.label) + "</strong> <small>" + esc(h.sub || h.type) + "</small>";
          li.onclick = function () {
            ul.style.display = "none";
            qInput.value = h.label;
            selectNode(h.id);
          };
          ul.appendChild(li);
        });
        ul.style.display = "block";
      });
  });
  qInput.addEventListener("keydown", function (e) {
    var items = el("q-results").querySelectorAll("li");
    if (e.key === "ArrowDown" && items.length) {
      e.preventDefault();
      qActive = (qActive + 1) % items.length;
      highlight(items);
    } else if (e.key === "ArrowUp" && items.length) {
      e.preventDefault();
      qActive = (qActive - 1 + items.length) % items.length;
      highlight(items);
    } else if (e.key === "Enter") {
      if (qActive >= 0 && items[qActive]) items[qActive].click();
      else if (items.length) items[0].click();
    }
  });

  document.addEventListener("click", function (e) {
    if (e.target.id !== "q") el("q-results").style.display = "none";
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && state.currentView !== "main") {
      loadGraph().then(function () { syncUrl(true); });
    }
  });
  window.addEventListener("popstate", handleHash);
  window.addEventListener("hashchange", handleHash);
}

// ---- URL 状态化 ----

function buildUrlHash() {
  var v = "main";
  if (currentActionView === "ripple" && rippleCenter) {
    v = "ripple:" + rippleCenter + ":" + (el("expand-range").value || 1);
  } else if (currentActionView === "author" && currentAuthorId) {
    v = "author:" + currentAuthorId;
  } else if (currentActionView === "path" && pathFromId && pathToId) {
    v = "path:" + pathFromId + "," + pathToId;
  }
  var parts = ["v=" + v];
  if (isIslandsHidden()) parts.push("islands=1");
  if (isAuthorsHidden()) parts.push("authors=0");
  return parts.join("&");
}

function syncUrl(push) {
  if (urlLock) return;
  var url = "#" + buildUrlHash();
  try {
    if (push) history.pushState(null, "", url);
    else history.replaceState(null, "", url);
  } catch (e) { /* 忽略 */ }
}

function parseCam(s) {
  var n = s.split(",").map(function (x) { return parseFloat(x); });
  if (n.length < 3 || n.some(isNaN)) return null;
  return { theta: n[0], phi: n[1], radius: n[2], cx: n[3] || 0, cy: n[4] || 0, cz: n[5] || 0 };
}

// 深链(新格式 #v=...) + 兼容旧格式(#path= / #ripple= / #author=)
export function handleHash() {
  var hash = location.hash;
  if (hash === lastHandledHash) return;
  lastHandledHash = hash;
  var h = hash.replace(/^#/, "");
  if (!h) return;
  if (!state.fullData.nodes.length) return; // 数据未就绪时忽略(启动时 loadGraph 后再调用)

  var v = null, islands = false, cam = null;
  h.split("&").forEach(function (p) {
    if (p.indexOf("v=") === 0) v = p.slice(2);
    else if (p.indexOf("path=") === 0) v = "path:" + p.slice(5);
    else if (p.indexOf("ripple=") === 0) v = "ripple:" + p.slice(7) + ":1";
    else if (p.indexOf("author=") === 0) v = "author:" + p.slice(7);
    else if (p.indexOf("islands=") === 0) islands = p.slice(8) === "1";
    else if (p.indexOf("authors=") === 0) el("show-authors").checked = p.slice(8) !== "0";
    else if (p.indexOf("cam=") === 0) cam = parseCam(p.slice(4));
  });
  el("hide-islands").checked = !!islands;

  urlLock = true;
  var parts = (v || "main").split(":");
  function finish() {
    urlLock = false;
    syncUrl(false); // 规范化 URL(替换,不产生历史记录)
  }

  if (parts[0] === "ripple" && parts[1]) {
    fetch("/api/work/" + encodeURIComponent(parts[1]))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderRipple(d);
        renderWorkPanel(d);
        var hops = parseInt(parts[2], 10) || 1;
        if (hops > 1) {
          el("expand-range").value = String(hops);
          expandRipple();
        }
        if (cam) applyCameraState(cam);
        finish();
      })
      .catch(finish);
  } else if (parts[0] === "author" && parts[1]) {
    selectNode(parts[1]);
    if (cam) applyCameraState(cam);
    finish();
  } else if (parts[0] === "path" && parts[1]) {
    var ids = parts[1].split(",");
    var f = findNode(ids[0]);
    var t = findNode(ids[1]);
    if (f && t) {
      el("from").value = f.label + " - " + (f.author || "");
      el("to").value = t.label + " - " + (t.author || "");
      findPath();
      if (cam) applyCameraState(cam);
    }
    finish();
  } else {
    renderMain(cam ? { camera: cam } : {});
    finish();
  }
}

// ---- 分享与导出 ----

function copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).catch(function () { legacyCopy(text); });
  } else {
    legacyCopy(text);
  }
}

function legacyCopy(text) {
  var ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } catch (e) { /* ignore */ }
  ta.remove();
}

function shareLink() {
  var cam = getCameraState();
  var hash = buildUrlHash() + "&cam=" +
    [cam.theta, cam.phi, cam.radius, cam.cx, cam.cy, cam.cz]
      .map(function (x) { return +x.toFixed(3); }).join(",");
  var url = location.origin + location.pathname + "#" + hash;
  copyText(url);
  showToast("分享链接已复制");
}

function exportPng() {
  var canvas = document.querySelector("#graph canvas");
  if (!canvas) return;
  var a = document.createElement("a");
  a.href = canvas.toDataURL("image/png");
  a.download = "echo-graph-" + Date.now() + ".png";
  document.body.appendChild(a);
  a.click();
  a.remove();
  showToast("已导出当前视图 PNG");
}

function exportData() {
  var blob = new Blob([JSON.stringify(state.fullData, null, 2)], { type: "application/json" });
  var url = URL.createObjectURL(blob);
  var a = document.createElement("a");
  a.href = url;
  a.download = "echo-graph-data.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  showToast("已导出图谱数据 JSON");
}
