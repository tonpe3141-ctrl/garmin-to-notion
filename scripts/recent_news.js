#!/usr/bin/env node
/**
 * 直近に紹介した「今日の読みもの」を一覧する。同じ記事・同じ話題を続けて選ばないための照合用。
 *
 *   node scripts/recent_news.js <db の一覧を保存したディレクトリ> [--days 45]
 *
 * 入力は STEP 3.5 で ArtifactData list の out_dir に保存した runs の JSON（export_widget_data.js と同じ）。
 * 各記録の news（export_run_history.js が DATA.news から写したもの）を新しい順に出す。
 * 最後にテーマごとの件数を出すので、偏りも見られる。
 *
 * 中身は db の丸写しなので、モデルに思い出させずにここで機械的に出す。
 */
const fs = require("fs");
const path = require("path");

const args = process.argv.slice(2);
const di = args.indexOf("--days");
const days = di >= 0 ? Number(args[di + 1]) : 45;
const dir = args.find((a, i) => !a.startsWith("--") && (di < 0 || i !== di + 1));
if (!dir) {
  console.error("usage: node scripts/recent_news.js <db_dir> [--days 45]");
  process.exit(2);
}
if (!fs.existsSync(dir)) {
  console.log(`（${dir} がない。履歴の一覧を取れていないので照合なしで選ぶ）`);
  process.exit(0);
}

// 一覧の保存形式に依存しないよう、ディレクトリ内の JSON を全部読んで「d と news を持つオブジェクト」を拾う
const found = [];
const walk = (v) => {
  if (Array.isArray(v)) return v.forEach(walk);
  if (!v || typeof v !== "object") return;
  if (typeof v.d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v.d) && v.news && (v.news.t || v.news.title)) found.push(v);
  Object.values(v).forEach(walk);
};
const files = [];
const list = (d) => fs.readdirSync(d).forEach((f) => {
  const p = path.join(d, f);
  if (fs.statSync(p).isDirectory()) list(p);
  else if (/\.json$/i.test(f)) files.push(p);
});
list(dir);
for (const f of files) {
  try { walk(JSON.parse(fs.readFileSync(f, "utf8"))); } catch (e) { /* 読めないファイルは飛ばす */ }
}

const today = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10);
const since = new Date(Date.parse(today) - days * 86400000).toISOString().slice(0, 10);
const seen = new Set();
const rows = found
  .filter((r) => r.d >= since)
  .sort((a, b) => (a.d < b.d ? 1 : -1))
  .map((r) => ({ d: r.d, t: r.news.t || r.news.title, u: r.news.u || r.news.url || "", s: r.news.s || r.news.source || "", th: r.news.th || r.news.theme || "" }))
  .filter((r) => (r.u && seen.has(r.u) ? false : (seen.add(r.u), true)));

if (!rows.length) {
  console.log(`直近${days}日に紹介した読みものはない。`);
  process.exit(0);
}
console.log(`直近${days}日に紹介した読みもの（${rows.length}件・新しい順）。同じ URL・同じ話題は選ばないこと:`);
for (const r of rows) console.log(`- ${r.d} [${r.th}] ${r.t} — ${r.s}\n    ${r.u}`);
const byTheme = rows.reduce((m, r) => m.set(r.th, (m.get(r.th) || 0) + 1), new Map());
console.log("テーマ別: " + [...byTheme].map(([k, v]) => `${k || "（なし）"} ${v}`).join(" ／ "));
