export async function loadGraphData() {
  const r = await fetch("/api/graph");
  return r.json();
}

export async function search(q) {
  const r = await fetch("/api/search?q=" + encodeURIComponent(q));
  return r.json();
}

export async function workDetail(id) {
  const r = await fetch("/api/work/" + encodeURIComponent(id));
  return r.json();
}

export async function expansion(id, hops) {
  const r = await fetch("/api/expansion/" + encodeURIComponent(id) + "?hops=" + hops);
  return r.json();
}

export async function findPath(from, to) {
  const r = await fetch("/api/path?from=" + encodeURIComponent(from) + "&to=" + encodeURIComponent(to));
  return r.json();
}
