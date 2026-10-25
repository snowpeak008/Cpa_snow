export const fmt = (n) => Number(n || 0).toLocaleString("zh-CN");
export const compact = (n) =>
  new Intl.NumberFormat("en", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(n || 0);
export const dateKey = (d) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export function summarize(events) {
  return events.reduce(
    (s, e) => ({
      n: s.n + 1,
      input: s.input + e.input,
      output: s.output + e.output,
      cache: s.cache + e.cache,
      reasoning: s.reasoning + e.reasoning,
      fail: s.fail + Number(e.failed),
    }),
    { n: 0, input: 0, output: 0, cache: 0, reasoning: 0, fail: 0 },
  );
}
export function groups(events, key) {
  const m = new Map();
  for (const e of events) {
    if (!m.has(e[key])) m.set(e[key], []);
    m.get(e[key]).push(e);
  }
  return [...m]
    .map(([name, evs]) => ({ name, ...summarize(evs) }))
    .sort((a, b) => b.input + b.output - (a.input + a.output));
}
export function trend(events, bucket) {
  const map = new Map();
  for (const e of events) {
    const d = new Date(e.ts * 1000),
      label =
        bucket === "month"
          ? dateKey(d).slice(0, 7)
          : bucket === "hour"
            ? `${dateKey(d)} ${String(d.getHours()).padStart(2, "0")}:00`
            : dateKey(d);
    if (!map.has(label))
      map.set(label, { label, cache: 0, net: 0, output: 0, requests: 0 });
    const b = map.get(label);
    b.cache += e.cache;
    b.net += Math.max(0, e.input - e.cache);
    b.output += e.output;
    b.requests++;
  }
  return [...map.values()].sort((a, b) => a.label.localeCompare(b.label));
}
