#!/usr/bin/env node
/**
 * 公開済み Artifact のソースに、その日の DATA ブロックを差し込んで dashboard/index.html を作る。
 *
 *   node scripts/splice_dashboard.js <公開済みソース.html> <data_block.js> [dashboard/index.html]
 *
 * やること（daily_coach_routine.md の STEP 6 をそのまま機械化したもの）:
 *   1. 1行目の publish ラッパー（<!doctype html><html><head>…<body>）を外す
 *   2. 末尾に重複した </body></html> を1つにする
 *   3. 行全体が <script id="coach-data"> の行から、次の </script> の行までの中身を
 *      data_block.js の中身（const DATA = {...}; まで）で置き換える
 *   4. check_dashboard.js で骨格と DATA を検証し、NG なら書き出さずに終了コード 1
 *
 * ⚠ 置換の目印に DATA の代入文を使わない。ファイル冒頭の説明コメントにも同じ文字列が
 *   現れるので、そちらに当たるとコメントの閉じタグごと消えてページが真っ白になる。
 */
const fs = require("fs");
const { check, report } = require("./check_dashboard.js");

const [src, dataFile, outArg] = process.argv.slice(2);
const out = outArg || "dashboard/index.html";
if (!src || !dataFile) {
  console.error("usage: node scripts/splice_dashboard.js <published.html> <data_block.js> [out.html]");
  process.exit(2);
}

let lines = fs.readFileSync(src, "utf8").split("\n");

// 1) publish ラッパー
if (lines[0].startsWith("<!doctype html><html><head>")) lines = lines.slice(1);

// 2) 末尾の重複
// （公開版は「</body></html>」「空行」「</body></html>」の並びで終わる。全部剥がして1つだけ付け直す）
let closers = 0;
while (lines.length) {
  const last = lines[lines.length - 1].trim();
  if (last === "") { lines.pop(); continue; }
  if (last === "</body></html>") { lines.pop(); closers++; continue; }
  break;
}
if (!closers) { console.error("末尾に </body></html> がない: " + src); process.exit(1); }
lines.push("", "</body></html>");

// 3) DATA ブロックの差し替え
const from = lines.findIndex((l) => l.trim() === '<script id="coach-data">');
const to = from < 0 ? -1 : lines.findIndex((l, i) => i > from && l.trim() === "</script>");
if (from < 0 || to < 0) { console.error("DATA ブロックの目印が見つからない: " + src); process.exit(1); }

const data = fs.readFileSync(dataFile, "utf8").replace(/\s+$/, "");
if (!/^const DATA = \{/m.test(data)) { console.error("data_block.js に `const DATA = {` がない"); process.exit(1); }
const html = [...lines.slice(0, from + 1), ...data.split("\n"), ...lines.slice(to)].join("\n");

// 4) 検証してから書く
const res = check(html, {});
const code = report(res);
if (code) { console.error("NG のため書き出していない: " + out); process.exit(code); }
fs.writeFileSync(out, html);
console.log(`wrote ${out} (${html.split("\n").length} lines)`);
