#!/usr/bin/env node
/**
 * その日の DATA ブロックを、リポジトリの描画レイヤー（dashboard/index.html）に差し込む。
 *
 *   node scripts/splice_dashboard.js <data_block.js> [out.html] [--published <公開済みソース.html>]
 *
 *   旧形式（2026-09-26 まで）も受け付ける:
 *   node scripts/splice_dashboard.js <公開済みソース.html> <data_block.js> [out.html]
 *
 * やること（daily_coach_routine.md の STEP 6 を機械化したもの）:
 *   1. 土台はリポジトリの dashboard/index.html（描画レイヤーの唯一の正）。
 *      publish ラッパーや重複した </body></html> が残っていれば外す
 *   2. 行全体が <script id="coach-data"> の行から、次の </script> の行までの中身を
 *      data_block.js の中身（const DATA = {...}; まで）で置き換える
 *   3. docs/athlete_profile.md からシーズンの骨格（フェーズ・レース・Mペース量の目標）を読み、
 *      `DATA.season = {...};` として DATA ブロックの末尾に足す（profile_season.js）。
 *      読めなければ警告だけ出して season なしで続ける
 *   4. check_dashboard.js で骨格と DATA を検証し、NG なら書き出さずに終了コード 1
 *
 * --published を渡すと、公開版の描画レイヤーがリポジトリと違うかどうかを報告する（置き換えはリポジトリ側）。
 *
 * ⚠ 以前は公開版を土台にしていた。そのため PR で直した描画レイヤーが公開ページに一度も届かず、
 *   2026-09-26 に PR #10 のラップ一覧が公開版に入っていないことが分かった。描画の改修は PR で
 *   main に入れ、ここで毎日そのまま公開される、という一方向の流れにしてある。
 *
 * ⚠ 置換の目印に DATA の代入文を使わない。ファイル冒頭の説明コメントにも同じ文字列が
 *   現れるので、そちらに当たるとコメントの閉じタグごと消えてページが真っ白になる。
 */
const fs = require("fs");
const path = require("path");
const { check, report } = require("./check_dashboard.js");
const { loadSeason } = require("./profile_season.js");

const ROOT = path.join(__dirname, "..");
const TEMPLATE = path.join(ROOT, "dashboard", "index.html");
const PROFILE = path.join(ROOT, "docs", "athlete_profile.md");

const args = process.argv.slice(2);
const opt = (name) => { const i = args.indexOf(name); return i >= 0 ? args.splice(i, 2)[1] : null; };
let published = opt("--published");
const template = opt("--template") || TEMPLATE;
let [dataFile, out] = args;
// 旧形式: <published.html> <data_block.js> [out]
if (dataFile && /\.html?$/i.test(dataFile) && args[1] && !/\.html?$/i.test(args[1])) {
  published = published || dataFile;
  [dataFile, out] = [args[1], args[2]];
}
out = out || TEMPLATE;
if (!dataFile) {
  console.error("usage: node scripts/splice_dashboard.js <data_block.js> [out.html] [--published <published.html>]");
  process.exit(2);
}

// publish ラッパー（1行目）と末尾の重複した </body></html> を外して、行の配列で返す
function normalize(file) {
  let lines = fs.readFileSync(file, "utf8").split("\n");
  if (lines[0].startsWith("<!doctype html><html><head>")) lines = lines.slice(1);
  while (lines.length) {
    const last = lines[lines.length - 1].trim();
    if (last === "" || last === "</body></html>") { lines.pop(); continue; }
    break;
  }
  return lines;
}
const blockRange = (lines) => {
  const from = lines.findIndex((l) => l.trim() === '<script id="coach-data">');
  const to = from < 0 ? -1 : lines.findIndex((l, i) => i > from && l.trim() === "</script>");
  return [from, to];
};

// 1) 土台
const lines = normalize(template);
const [from, to] = blockRange(lines);
if (from < 0 || to < 0) { console.error("DATA ブロックの目印が見つからない: " + template); process.exit(1); }

// 公開版との比較（報告だけ）
if (published) {
  try {
    const pub = normalize(published);
    const [, pto] = blockRange(pub);
    const a = lines.slice(to).join("\n"), b = pub.slice(pto).join("\n");
    if (pto < 0) console.log("  · 公開版に DATA ブロックが見つからないので描画レイヤーの比較は省略");
    else if (a === b) console.log("  · 公開版の描画レイヤーはリポジトリと同じ");
    else console.log(`  · 公開版の描画レイヤーはリポジトリと異なる（公開版 ${pub.length - pto} 行 / リポジトリ ${lines.length - to} 行）。リポジトリ版で置き換える`);
  } catch (e) {
    console.log(`  ⚠ 公開版を読めなかった（比較は省略）: ${e.message}`);
  }
}

// 2) DATA
let data = fs.readFileSync(dataFile, "utf8").replace(/\s+$/, "");
if (!/^const DATA = \{/m.test(data)) { console.error("data_block.js に `const DATA = {` がない"); process.exit(1); }
data = data.replace(/^DATA\.season = .*;\s*$/gm, "").replace(/\s+$/, "");

// 3) シーズン
try {
  const season = loadSeason(PROFILE);
  data += "\n// docs/athlete_profile.md から splice_dashboard.js が機械的に差し込む。手で書かない。\n"
    + `DATA.season = ${JSON.stringify(season)};`;
  console.log(`  · season: フェーズ ${season.phases.length} / レース ${season.races.length} / Mペース目標 ${season.mTargets.length}`);
} catch (e) {
  console.log(`  ⚠ プロファイルからシーズンを読めなかった（season なしで続ける）: ${e.message}`);
}

const html = [...lines.slice(0, from + 1), ...data.split("\n"), ...lines.slice(to), "", "</body></html>"].join("\n");

// 4) 検証してから書く
const res = check(html, {});
const code = report(res);
if (code) { console.error("NG のため書き出していない: " + out); process.exit(code); }
fs.writeFileSync(out, html);
console.log(`wrote ${out} (${html.split("\n").length} lines)`);
