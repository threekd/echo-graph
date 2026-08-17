/* 数据加载与视图编排:图谱、搜索、路径、涟漪、作者视图、深链 */

import { el, esc } from "./util.js";
import { state } from "./state.js";
import { renderView } from "./renderer.js";
import {
  showEmptyPanel,
  showPickError,
  showNoPath,
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
      renderView("main", data);
      fillWorkDatalist();
      showEmptyPanel();
    });
}

function fillWorkDatalist() {
  var dl = el("works");
  dl.innerHTML = "";
  state.workLookup = {};
  state.fullData.nodes.filter(function (n) { return n.type === "work"; }).forEach(function (w) {
    var key = w.label + " - " + (w.author || "");
    state.workLookup[key] = w.id;
    var opt = document.createElement("option");
    opt.value = key;
    dl.appendChild(opt);
  });
}

export function selectNode(id) {
  var node = state.fullData.nodes.filter(function (n) { return n.id === id; })[0];
  if (!node) return;
  if (node.type === "work") {
    fetch("/api/work/" + encodeURIComponent(id))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        renderRipple(d);     // 自动进入涟漪视图
        renderWorkPanel(d);  // 侧边栏显示详情
      });
  } else {
    renderAuthorView(node);  // 3D:该作者 + 他的书
    renderAuthorPanel(node);
  }
}

// 悬停节点:只显示右侧详情页,不切换 3D 视图
export function showNodeDetail(id) {
  var node = state.fullData.nodes.filter(function (n) { return n.id === id; })[0];
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
    var n = state.fullData.nodes.filter(function (x) { return x.id === id; })[0];
    if (!n) return;
    nodes.push(n);
  });

  renderView("ripple", { nodes: nodes, edges: edges, centerId: center });
}

function expandRipple() {
  if (!rippleCenter) return;
  var hops = parseInt(el("expand-range").value, 10) || 1;
  el("expand-value").textContent = hops + " 级";
  fetch("/api/expansion/" + encodeURIComponent(rippleCenter) + "?hops=" + hops)
    .then(function (r) { return r.json(); })
    .then(function (data) {
      renderView("ripple", data);
    });
}

function findPath() {
  var f = el("from").value.trim();
  var t = el("to").value.trim();
  var fromId = state.workLookup[f];
  var toId = state.workLookup[t];
  if (!fromId || !toId) {
    showPickError();
    return;
  }
  fetch("/api/path?from=" + encodeURIComponent(fromId) + "&to=" + encodeURIComponent(toId))
    .then(function (r) { return r.status === 404 ? null : r.json(); })
    .then(function (result) {
      if (!result) {
        showNoPath(f, t);
        return;
      }
      renderPath(result, f, t);
    });
}

function renderPath(result, f, t) {
  var nodes = [];
  var edges = [];
  var ids = {};
  result.nodes.forEach(function (id) {
    var n = state.fullData.nodes.filter(function (x) { return x.id === id; })[0];
    if (n) { nodes.push(n); ids[id] = true; }
  });
  result.edges.forEach(function (e) {
    edges.push({ source: e.source, target: e.target, type: "echo", evidence: e.evidence, note: e.note });
    [e.source, e.target].forEach(function (id) {
      if (!ids[id]) {
        var n = state.fullData.nodes.filter(function (x) { return x.id === id; })[0];
        if (n) { nodes.push(n); ids[id] = true; }
      }
    });
  });
  renderView("path", { nodes: nodes, edges: edges, pathOrder: result.nodes });
  renderPathPanel(result, f, t);
}

export function wireEvents() {
  el("btn-path").onclick = findPath;
  el("btn-back-main").onclick = function () { loadGraph(); };
  el("btn-example").onclick = function () {
    el("from").value = "伊利亚特 - 荷马";
    el("to").value = "活着 - 余华";
    findPath();
  };
  el("expand-range").addEventListener("input", expandRipple);

  var qInput = el("q");
  qInput.addEventListener("input", function () {
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
  document.addEventListener("click", function (e) {
    if (e.target.id !== "q") el("q-results").style.display = "none";
  });
}

// 深链:#path=workA,workB / #ripple=workId / #author=authorId
export function handleHash() {
  var h = location.hash.replace(/^#/, "");
  if (!h) return;
  if (h.indexOf("path=") === 0) {
    var parts = h.slice(5).split(",");
    if (parts.length === 2) {
      var f = state.fullData.nodes.filter(function (n) { return n.id === parts[0]; })[0];
      var t = state.fullData.nodes.filter(function (n) { return n.id === parts[1]; })[0];
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
