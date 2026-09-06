#!/usr/bin/env node
/**
 * ダッシュボードの DATA.today から「過去の評価」用の1件を書き出す。
 *
 *   node scripts/export_run_history.js <dashboard.html> <out.json>
 *
 * 中身はすでに DATA に入っている値の丸写しなので、モデルに書き起こさせず
 * ここで機械的にコピーする。日々の生成コストを増やさないための仕組み。
 * 出来た JSON を Artifact の write_db に file_path で渡す。
 */
const fs = require("fs");

const [src, out] = process.argv.slice(2);
if (!src || !out) {
  console.error("usage: node scripts/export_run_history.js <dashboard.html> <out.json>");
  process.exit(2);
}

// ⚠ 正規表現で <script id="coach-data"> を探してはいけない。
//   ファイル冒頭の説明コメントの中にも同じ文字列が現れるので、そちらに当たる。
//   「行全体がそのタグである行」だけを目印にする。
const lines = fs.readFileSync(src, "utf8").split("\n");
const from = lines.findIndex((l) => l.trim() === '<script id="coach-data">');
const to = from < 0 ? -1 : lines.findIndex((l, i) => i > from && l.trim() === "</script>");
if (from < 0 || to < 0) {
  console.error("DATA ブロックが見つかりません: " + src);
  process.exit(1);
}
const DATA = Function(lines.slice(from + 1, to).join("\n") + "\n; return DATA;")();
const t = DATA.today || {};
if (!t.date) {
  console.error("today.date がありません");
  process.exit(1);
}

const pick = (label) => {
  const s = (t.stats || []).find((x) => x.label === label);
  return s ? s.value : null;
};

// ラップは "秒:心拍" のカンマ区切り1行。ペースは秒から復元できるので持たない。
const laps = (t.laps || [])
  .map((l) => `${l.sec}:${l.hr == null ? "" : l.hr}`)
  .join(",");

const doc = {
  d: t.date,
  dow: t.dow || "",
  type: t.type || "",
  verdict: t.verdict || "",
  verdictLabel: t.verdictLabel || "",
  km: pick("距離"),
  pace: pick("平均ペース"),
  hr: pick("平均心拍"),
  headline: t.headline || "",
  points: t.points || [],
  stats: t.stats || [],
  effect: t.effect || "",
  laps
};

fs.writeFileSync(out, JSON.stringify(doc));
console.log(`${t.date} -> ${out} (${fs.statSync(out).size} bytes, laps=${(t.laps || []).length})`);
