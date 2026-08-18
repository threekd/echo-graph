/* 数据管理页:三张表的增删改查、一键导入 Neo4j、导出 */

import { el, esc } from "./util.js";
import { showToast } from "./panels.js";
import { loadGraph } from "./actions.js";

var state = {
  data: { authors: [], works: [], edges: [] },
  kind: "authors",
  search: "",
};

var GENRES = ["Fiction", "Non-fiction", "Poetry", "Drama"];
var REVIEWS = ["draft", "reviewed", "rejected"];
var LANGS = ["ar", "de", "el", "en", "es", "fr", "it", "ja", "la", "no", "pt", "ru", "zh", "bn"];

function kindRows() {
  return state.data[state.kind];
}

function filterRows(rows) {
  var q = state.search.toLowerCase();
  if (!q) return rows;
  return rows.filter(function (r) {
    return Object.keys(r).some(function (k) {
      var v = r[k];
      return v != null && String(v).toLowerCase().indexOf(q) !== -1;
    });
  });
}

function load() {
  return fetch("/api/admin/data")
    .then(function (r) { return r.json(); })
    .then(function (d) {
      state.data = d;
      render();
      if (location.search.indexOf("admintest=1") !== -1) {
        state.kind = "edges";
        render();
        openForm(null, false);
        var si = el("admin-form").querySelector("[data-picker='source_work_id']");
        if (si) {
          si.value = "百年";
          si.dispatchEvent(new Event("input", { bubbles: true }));
        }
        var ti = el("admin-form").querySelector("[data-picker='target_work_id']");
        if (ti) {
          ti.value = "不存在的书";
          ti.dispatchEvent(new Event("input", { bubbles: true }));
        }
      }
    });
}

function open() {
  el("admin-overlay").style.display = "flex";
  load().catch(function (e) { showToast("加载管理数据失败:" + e.message); });
}

function close() {
  el("admin-overlay").style.display = "none";
}

// ---------- 渲染 ----------

function render() {
  renderTabs();
  renderTable();
}

function renderTabs() {
  Array.prototype.forEach.call(el("admin-overlay").querySelectorAll(".admin-tab"), function (btn) {
    var k = btn.getAttribute("data-kind");
    btn.classList.toggle("active", k === state.kind);
    var cnt = btn.querySelector(".cnt");
    var rows = state.data[k];
    var deleted = rows.filter(function (r) { return r.deletedAt; }).length;
    cnt.textContent = rows.length + (deleted ? "(-" + deleted + ")" : "");
  });
}

function tableCols() {
  if (state.kind === "authors") {
    return [
      { key: "Name_CN", label: "中文名" },
      { key: "originalName", label: "原文名" },
      { key: "nationality", label: "国籍" },
      { key: "years", label: "生卒" },
    ];
  }
  if (state.kind === "works") {
    return [
      { key: "Title_CN", label: "中文名" },
      { key: "Author", label: "作者" },
      { key: "language", label: "语言" },
      { key: "year", label: "年份" },
      { key: "genre", label: "体裁" },
    ];
  }
  return [
    { key: "source_title", label: "源作品" },
    { key: "target_title", label: "目标作品" },
    { key: "evidence", label: "摘抄(节选)" },
    { key: "evidenceSource", label: "出处" },
    { key: "reviewStatus", label: "审核" },
  ];
}

function cellValue(row, col) {
  if (state.kind === "authors" && col.key === "years") {
    return (row.birthYear || "?") + "–" + (row.deathYear || "?");
  }
  if (state.kind === "works" && col.key === "year") {
    return row.publicationYear || row.creationYear || "";
  }
  if (state.kind === "edges") {
    if (col.key === "source_title") return workLabel(row.source_work_id);
    if (col.key === "target_title") return workLabel(row.target_work_id);
    if (col.key === "evidence") {
      var t = row.evidence || "";
      return t.length > 60 ? t.slice(0, 60) + "…" : t;
    }
    if (col.key === "reviewStatus") {
      return "<span class='badge-" + (row.reviewStatus || "draft") + "'>" + esc(row.reviewStatus || "draft") + "</span>";
    }
  }
  return row[col.key] || "";
}

function workTitle(id) {
  var w = state.data.works.filter(function (x) { return x.id === id; })[0];
  return w ? w.Title_CN : id;
}

function workLabel(id) {
  var w = state.data.works.filter(function (x) { return x.id === id; })[0];
  if (!w) return id;
  return [w.originalTitle, w.Title_CN].filter(Boolean).join(" - ") || id;
}

function workLabelToId(text) {
  if (!text) return null;
  if (state.data.works.some(function (w) { return w.id === text; })) return text;
  var hit = state.data.works.filter(function (w) { return workLabel(w.id) === text; })[0];
  return hit ? hit.id : null;
}

function workInputField(name, labelText, value) {
  var display = value ? (workLabelToId(value) ? workLabel(value) : value) : "";
  return "<label><span>" + esc(labelText) + "</span>" +
    "<div class='work-picker'><input name='" + name + "' data-picker='" + name +
    "' value='" + esc(display) + "' autocomplete='off' placeholder='输入筛选…' />" +
    "<ul class='work-picker-results' data-for='" + name + "'></ul>" +
    "<div class='work-picker-warn' data-warn='" + name + "' style='display:none'>⚠ 该作品不在数据库中,请先新增作品数据</div>" +
    "</div></label>";
}

function renderTable() {
  var cols = tableCols();
  var rows = filterRows(kindRows());
  var html = "<thead><tr><th>#</th>";
  cols.forEach(function (c) { html += "<th>" + esc(c.label) + "</th>"; });
  html += "<th>操作</th></tr></thead><tbody>";
  rows.forEach(function (r, i) {
    var deleted = !!r.deletedAt;
    html += "<tr class='" + (deleted ? "deleted" : "") + "'>";
    html += "<td>" + (i + 1) + "</td>";
    cols.forEach(function (c) { html += "<td>" + cellValue(r, c) + "</td>"; });
    html += "<td class='row-actions'>" +
      "<button data-act='edit' data-id='" + esc(r.id) + "'>编辑</button>" +
      (deleted
        ? "<button data-act='restore' data-id='" + esc(r.id) + "'>恢复</button>"
        : "<button class='del' data-act='del' data-id='" + esc(r.id) + "'>删除</button>") +
      "</td></tr>";
  });
  html += "</tbody>";
  el("admin-table").innerHTML = html;
  el("admin-status").textContent =
    state.kind + ":" + filterRows(kindRows()).length + " / " + kindRows().length + " 条";
}

// ---------- 表单 ----------

function field(label, name, value, opts) {
  opts = opts || {};
  var input;
  if (opts.kind === "select") {
    var options = opts.options || [];
    input = "<select name='" + name + "'>";
    input += "<option value=''></option>";
    options.forEach(function (o) {
      var v = typeof o === "object" ? o.value : o;
      var label = typeof o === "object" ? (o.label || o.value) : o;
      input += "<option value='" + esc(v) + "'" + (String(value) === String(v) ? " selected" : "") + ">" + esc(label) + "</option>";
    });
    input += "</select>";
  } else if (opts.kind === "textarea") {
    input = "<textarea name='" + name + "'>" + esc(value || "") + "</textarea>";
  } else {
    input = "<input name='" + name + "' value='" + esc(value || "") + "'" + (opts.placeholder ? " placeholder='" + esc(opts.placeholder) + "'" : "") + " />";
  }
  return "<label class='" + (opts.full ? "full" : "") + "'>" + esc(label) + input + "</label>";
}

function authorOptions(selected) {
  return state.data.authors.map(function (a) { return a.originalName || a.Name_CN; }).filter(function (n) { return n; })
    .map(function (n) {
      return "<option value='" + esc(n) + "'" + (n === selected ? " selected" : "") + ">" + esc(n) + "</option>";
    }).join("");
}

function buildForm(row, isEdit) {
  row = row || {};
  var html = "";
  function idField() {
    return "<input type='hidden' name='id' value='" + esc(isEdit ? (row.id || "") : "") + "' />";
  }
  if (state.kind === "authors") {
    html += idField() +
      field("originalName(原文名,必填)", "originalName", row.originalName) +
      field("Name_CN(中文名)", "Name_CN", row.Name_CN) +
      field("Name_EN", "Name_EN", row.Name_EN) +
      field("nationality", "nationality", row.nationality) +
      field("birthYear", "birthYear", row.birthYear, { placeholder: "如 1913" }) +
      field("deathYear", "deathYear", row.deathYear, { placeholder: "如 1960" });
  } else if (state.kind === "works") {
    html += idField() +
      field("language(ISO 639-1)", "language", row.language, { kind: "select", options: LANGS }) +
      field("originalTitle(原著标题)", "originalTitle", row.originalTitle) +
      field("Title_CN(中文名)", "Title_CN", row.Title_CN) +
      field("Title_EN", "Title_EN", row.Title_EN) +
      field("Title_Other", "Title_Other", row.Title_Other) +
      field("Author(多人用逗号隔开)", "Author", row.Author, { kind: "select", options: [] }) +
      field("publicationYear", "publicationYear", row.publicationYear) +
      field("creationYear", "creationYear", row.creationYear) +
      field("genre", "genre", row.genre, { kind: "select", options: GENRES });
  } else {
    html += workInputField("source_work_id", "源作品(输入中文筛选)", row.source_work_id) +
      workInputField("target_work_id", "目标作品(输入中文筛选)", row.target_work_id) +
      field("evidence(摘抄,必填)", "evidence", row.evidence, { kind: "textarea", full: true }) +
      field("evidenceSource(出处)", "evidenceSource", row.evidenceSource) +
      field("evidenceLang", "evidenceLang", row.evidenceLang) +
      field("note(备注)", "note", row.note) +
      field("reviewStatus", "reviewStatus", row.reviewStatus, { kind: "select", options: REVIEWS });
  }
  // work Author: 用 datalist 支持既有作者名 + 自由输入
  if (state.kind === "works") {
    html += "<datalist id='admin-authors-list'>" + authorOptions(row.Author) + "</datalist>";
  }
  return html;
}

function initWorkPickers() {
  Array.prototype.forEach.call(el("admin-form").querySelectorAll("[data-picker]"), function (input) {
    var list = el("admin-form").querySelector("[data-for='" + input.name + "']");
    var warnEl = el("admin-form").querySelector("[data-warn='" + input.name + "']");
    if (!list) return;
    input.addEventListener("input", function () {
      input.dataset.pickedId = "";
      var q = input.value.trim().toLowerCase();
      if (!q) {
        list.style.display = "none";
        if (warnEl) warnEl.style.display = "none";
        return;
      }
      var hits = state.data.works.filter(function (w) {
        if (w.deletedAt) return false;
        return workLabel(w.id).toLowerCase().indexOf(q) !== -1 ||
          (w.Title_CN || "").toLowerCase().indexOf(q) !== -1 ||
          (w.originalTitle || "").toLowerCase().indexOf(q) !== -1;
      }).slice(0, 8);
      list.innerHTML = "";
      if (!hits.length) {
        list.style.display = "none";
        if (warnEl) warnEl.style.display = "block"; // 库中不存在 → 提示先新增
        return;
      }
      if (warnEl) warnEl.style.display = "none";
      hits.forEach(function (w) {
        var li = document.createElement("li");
        li.textContent = workLabel(w.id);
        li.addEventListener("mousedown", function (ev) {
          ev.preventDefault();
          input.value = workLabel(w.id);
          input.dataset.pickedId = w.id;
          list.style.display = "none";
          if (warnEl) warnEl.style.display = "none";
        });
        list.appendChild(li);
      });
      list.style.display = "block";
    });
    input.addEventListener("keydown", function (e) {
      if (e.key === "Enter") {
        var first = list.querySelector("li");
        if (first) {
          first.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
          e.preventDefault();
        }
      }
    });
    input.addEventListener("blur", function () {
      setTimeout(function () { list.style.display = "none"; }, 150);
    });
  });
}

function openForm(row, isEdit) {
  el("admin-modal").style.display = "flex";
  el("admin-modal-title").textContent =
    (isEdit ? "编辑" : "新增") + " " + { authors: "作者", works: "作品", edges: "提及" }[state.kind];
  el("admin-form").innerHTML = buildForm(row, isEdit);
  var authorInput = el("admin-form").querySelector("[name='Author']");
  if (authorInput) {
    authorInput.setAttribute("list", "admin-authors-list");
    authorInput.type = "text";
  }
  el("admin-form-errors").textContent = "";
  initWorkPickers();
  el("admin-form-save").dataset.isEdit = isEdit ? "1" : "0";
  el("admin-form-save").dataset.id = row && row.id ? row.id : "";
}

function collectForm() {
  var out = {};
  Array.prototype.forEach.call(el("admin-form").querySelectorAll("input, select, textarea"), function (el_) {
    if (el_.name) out[el_.name] = el_.value.trim();
  });
  // 作品输入框显示的是 "originalTitle - Title_CN",提交时解析回 UUID
  ["source_work_id", "target_work_id"].forEach(function (k) {
    if (out[k]) {
      var inputEl = el("admin-form").querySelector("[data-picker='" + k + "']");
      if (inputEl && inputEl.dataset.pickedId) {
        out[k] = inputEl.dataset.pickedId;
      } else {
        var resolved = workLabelToId(out[k]);
        if (resolved) out[k] = resolved;
      }
    }
  });
  Object.keys(out).forEach(function (k) {
    if (out[k] === "") out[k] = null;
  });
  return out;
}

function saveForm() {
  var row = collectForm();
  var invalid = [];
  ["source_work_id", "target_work_id"].forEach(function (k) {
    if (row[k] && !workLabelToId(row[k])) {
      invalid.push(k === "source_work_id" ? "源作品" : "目标作品");
      var warnEl = el("admin-form").querySelector("[data-warn='" + k + "']");
      if (warnEl) warnEl.style.display = "block";
    }
  });
  if (invalid.length) {
    el("admin-form-errors").textContent =
      "请选择数据库中已存在的作品:" + invalid.join("、") + "(不在数据库中,请先新增作品数据)";
    return;
  }
  var isEdit = el("admin-form-save").dataset.isEdit === "1";
  var id = el("admin-form-save").dataset.id;
  var url = "/api/admin/" + state.kind + (isEdit ? "/" + encodeURIComponent(id) : "");
  var method = isEdit ? "PUT" : "POST";
  fetch(url, {
    method: method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(row),
  })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (res) {
      if (!res.ok) {
        el("admin-form-errors").textContent = res.data.detail || "保存失败";
        return;
      }
      el("admin-modal").style.display = "none";
      showToast(isEdit ? "已更新" : "已新增");
      load();
    })
    .catch(function (e) {
      el("admin-form-errors").textContent = "请求失败:" + e.message;
    });
}

function removeRow(id) {
  if (!confirm("确认删除「" + id + "」?(软删除,可在 CSV 中恢复)")) return;
  fetch("/api/admin/" + state.kind + "/" + encodeURIComponent(id), { method: "DELETE" })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      if (d && d.ok) {
        showToast("已软删除");
        load();
      } else {
        showToast((d && d.detail) || "删除失败");
      }
    });
}

function restoreRow(id) {
  var row = kindRows().filter(function (r) { return r.id === id; })[0];
  if (!row) return;
  row.deletedAt = null;
  fetch("/api/admin/" + state.kind + "/" + encodeURIComponent(id), {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(row),
  })
    .then(function (r) { return r.json(); })
    .then(function (d) {
      showToast(d.ok ? "已恢复" : (d.detail || "恢复失败"));
      if (d.ok) load();
    });
}

function doImport() {
  if (!confirm("将 data/real/*.csv 写入 Neo4j(增量合并),继续?")) return;
  fetch("/api/admin/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ wipe: false, version: "1.1" }),
  })
    .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
    .then(function (res) {
      if (!res.ok) {
        showToast("导入失败:" + (res.data.detail || ""));
        return;
      }
      showToast("已导入 Neo4j:" + res.data.authors + " 作者 / " + res.data.works + " 作品 / " + res.data.echoes + " 提及");
      loadGraph(); // 刷新星云
    })
    .catch(function (e) { showToast("导入失败:" + e.message); });
}

function exportJson() {
  var a = document.createElement("a");
  a.href = "/api/admin/export/json";
  a.download = "echo-graph-data.json";
  a.click();
}

function exportCsv() {
  var a = document.createElement("a");
  a.href = "/api/admin/export/csv/" + state.kind;
  a.download = state.kind + ".csv";
  a.click();
}

function wire() {
  el("btn-admin").addEventListener("click", open);
  el("admin-close").addEventListener("click", close);
  el("admin-add").addEventListener("click", function () { openForm(null, false); });
  el("admin-form-save").addEventListener("click", saveForm);
  el("admin-form-cancel").addEventListener("click", function () { el("admin-modal").style.display = "none"; });
  el("admin-import").addEventListener("click", doImport);
  el("admin-export-json").addEventListener("click", exportJson);
  el("admin-export-csv").addEventListener("click", exportCsv);
  el("admin-search").addEventListener("input", function () {
    state.search = el("admin-search").value.trim();
    renderTable();
  });
  Array.prototype.forEach.call(el("admin-overlay").querySelectorAll(".admin-tab"), function (btn) {
    btn.addEventListener("click", function () {
      state.kind = btn.getAttribute("data-kind");
      render();
    });
  });
  el("admin-table").addEventListener("click", function (e) {
    var btn = e.target.closest("button");
    if (!btn || !btn.dataset.act) return;
    var id = btn.dataset.id;
    if (btn.dataset.act === "edit") {
      var row = kindRows().filter(function (r) { return r.id === id; })[0];
      openForm(row, true);
    } else if (btn.dataset.act === "del") {
      removeRow(id);
    } else if (btn.dataset.act === "restore") {
      restoreRow(id);
    }
  });
}

wire();

export { open, close };
