/* 侧边栏内容渲染 */

import { el, esc } from "./util.js";
import { state } from "./state.js";

var selectHandler = null;
var toastTimer = null;

export function setOnSelect(fn) {
  selectHandler = fn;
}

export function showToast(msg) {
  var t = el("toast");
  if (!t) return;
  t.textContent = msg;
  t.classList.add("show");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(function () {
    t.classList.remove("show");
  }, 2200);
}

export function showEmptyPanel() {
  el("panel-content").innerHTML =
    "<div id='panel-empty'><p>点击任意星星,自动展开它的涟漪;</p><p>右键拖拽旋转 · 左键拖拽平移 · 滚轮缩放。</p><p>顶部可搜索作品、查找提及链。</p></div>";
}

export function showPickError() {
  el("panel-content").innerHTML = "<p class='no-path'>请从下拉列表中选择两部作品。</p>";
}

export function showNoPath(f, t) {
  el("panel-content").innerHTML = "<p class='no-path'>未找到「" + esc(f) + " → " + esc(t) + "」的提及链。</p>";
}

export function renderAuthorPanel(author) {
  var works = state.fullData.nodes.filter(function (n) {
    return n.type === "work" && n.author_id === author.id;
  });
  var years = String(author.birthYear != null ? author.birthYear : "?") + " – " + String(author.deathYear != null ? author.deathYear : "?");
  var meta = [author.originalName || author.label_en, author.nationality, years, author.primaryLanguage ? "语言 " + author.primaryLanguage : ""]
    .filter(Boolean).join(" · ");
  var html =
    "<h2>" + esc(author.label) + "</h2>" +
    "<div class='meta'>" + esc(meta) + "</div>" +
    (author.bio ? "<p style='font-size:12px;color:#93a4c8;line-height:1.7'>" + esc(author.bio) + "</p>" : "") +
    "<h3>作品(" + works.length + ")</h3><ul>" +
    works.map(function (w) {
      return "<li class='work-item' data-id='" + esc(w.id) + "'><strong>" + esc(w.label) + "</strong> <small>(" + (w.year || "?") + " · " + esc(w.language || "") + ")</small></li>";
    }).join("") +
    "</ul><p style='font-size:12px;color:#93a4c8'>点击书籍可查看它的涟漪。</p>";
  el("panel-content").innerHTML = html;
  Array.prototype.forEach.call(el("panel-content").querySelectorAll(".work-item"), function (li) {
    li.addEventListener("click", function () {
      if (selectHandler) selectHandler(li.getAttribute("data-id"));
    });
  });
}

export function renderWorkPanel(d) {
  var w = d.work, a = d.author;
  var html =
    "<h2>" + esc(w.title) + "</h2>" +
    "<div class='meta'>" + esc(w.originalTitle || w.title_en) + " · " + esc(a.name) + " · " + (w.year || "?") + " · " + esc(w.language) + "</div>";
  if (w.summary) {
    html += "<p style='font-size:12px;color:#93a4c8;line-height:1.7'>" + esc(w.summary) + "</p>";
  }

  if (d.mentioned_by.length) {
    html += "<h3>谁提及了这本书(回声来源)</h3><ul>";
    d.mentioned_by.forEach(function (e) {
      html += "<li><span class='tag-mention'>提及</span>" +
        "<strong>" + esc(e.source_title) + "</strong> <small>(" + esc(e.source_author) + ")</small>" +
        "<div class='quote'>" + esc(e.evidence) + "</div>" +
        "<div class='quote' style='opacity:0.75'>" + esc(e.note || "") + "</div></li>";
    });
    html += "</ul>";
  }
  if (d.mentions.length) {
    html += "<h3>这本书提及了(涟漪扩散)</h3><ul>";
    d.mentions.forEach(function (e) {
      html += "<li><span class='tag-mention'>提及</span>" +
        "<strong>" + esc(e.target_title) + "</strong> <small>(" + esc(e.target_author) + ")</small>" +
        "<div class='quote'>" + esc(e.evidence) + "</div>" +
        "<div class='quote' style='opacity:0.75'>" + esc(e.note || "") + "</div></li>";
    });
    html += "</ul>";
  }
  if (!d.mentioned_by.length && !d.mentions.length) {
    html += "<p class='no-path'>这本书没有被其他书提及,也未提及别的书(孤岛星)。</p>";
  }
  el("panel-content").innerHTML = html;
}

export function renderPathPanel(result, f, t) {
  var html =
    "<h2>提及链(3D)</h2><div class='meta'>" + esc(f) + " → " + esc(t) + " · " + result.nodes.length + " 本书 / " + result.edges.length + " 次提及</div>";
  for (var i = 0; i < result.edges.length; i++) {
    var e = result.edges[i];
    var sn = state.fullData.nodes.filter(function (x) { return x.id === e.source; })[0];
    var tn = state.fullData.nodes.filter(function (x) { return x.id === e.target; })[0];
    html += "<div class='path-step'><strong>" + esc(sn ? sn.label : e.source) + "</strong> → " +
      "<strong>" + esc(tn ? tn.label : e.target) + "</strong>" +
      "<div class='edge'>提及 · " + esc(e.note || "") + "</div>" +
      "<div class='quote'>" + esc(e.evidence || "") + "</div></div>";
  }
  el("panel-content").innerHTML = html;
}
