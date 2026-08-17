/* 数据加载与视图编排:图谱、搜索、路径、涟漪、作者视图、深链 */

import { el, esc } from "./util.js";
import { state } from "./state.js";
import { renderView } from "./renderer.js";
import {
  showEmptyPanel,
  showPickError,
  showNoPath,
  showToast,
  renderAuthorPanel,
  renderWorkPanel,
  renderPathPanel,
} from "./panels.js";

var rippleCenter = null; // 当前涟漪视图的中心作品

export function loadGraph() {
  return fetch("/api/graph")
    .then(function (r) { return r.json(); })
    .then(function (data) {
      state.fullData = data;
      buildWorkLookups();
      if (location.search.indexOf("hideislands") !== -1) {
        el("hide-islands").checked = true; // 测试/分享参数
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

function renderMain() {
  var data = isIslandsHidden() ? filterIslands(state.fullData) : state.fullData;
  renderView("main", data, { preserveCamera: true });
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
      });
  } else {
    renderAuthorView(node);  // 3D:该作者 + 他的书
    renderAuthorPanel(node);
    showToast("视图:作者 · " + node.label + "(" + countWorks(node.id) + " 部作品)");
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

  renderView("ripple", { nodes: nodes, edges: edges, centerId: center });
}

function expandRipple() {
  if (!rippleCenter) return;
  var hops = parseInt(el("expand-range").value, 10) || 1;
  fetch("/api/expansion/" + encodeURIComponent(rippleCenter) + "?hops=" + hops)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      renderView("ripple", data, { preserveCamera: true }); // 拖动滑动条时保持当前视角
      el("expand-value").textContent = hops + " 级 · " + data.nodes.length + " 本书";
      showToast(hops + " 级扩散 · " + data.nodes.length + " 本书");
    });
}

function findPath() {
  var f = el("from").value.trim();
  var t = el("to").value.trim();
  var fromId = state.workLookup[f];
  var toId = state.workLookup[t];
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
    });
}

function renderPath(result, f, t) {
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
  el("btn-back-main").onclick = function () { loadGraph(); };
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
  });
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
      loadGraph();
    }
  });
}

// 深链:#path=workA,workB / #ripple=workId / #author=authorId
export function handleHash() {
  var h = location.hash.replace(/^#/, "");
  if (!h) return;
  if (h.indexOf("path=") === 0) {
    var parts = h.slice(5).split(",");
    if (parts.length === 2) {
      var f = findNode(parts[0]);
      var t = findNode(parts[1]);
      if (f && t) {
        el("from").value = f.label + " - " + (f.author || "");
        el("to").value = t.label + " - " + (t.author || "");
        findPath();
      }
    }
  } else if (h.indexOf("ripple=") === 0) {
    fetch("/api/work/" + encodeURIComponent(h.slice(7)))
      .then(function (r) { return r.json(); })
      .then(renderRipple);
  } else if (h.indexOf("author=") === 0) {
    selectNode(h.slice(7));
  }
}
