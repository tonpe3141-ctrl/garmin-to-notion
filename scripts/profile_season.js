#!/usr/bin/env node
/**
 * docs/athlete_profile.md からシーズンの骨格を機械的に読み出す。
 *
 *   node scripts/profile_season.js [docs/athlete_profile.md]   … 読み取り結果を JSON で表示（確認用）
 *
 * 読むのはプロファイルに既にある3つの表だけ（ここに値を書き写さない。写すと前提が分裂する）:
 *   - 「レースまでのロードマップ」の表（| フェーズ | 期間 | 方針 | 週間距離 | 質練習 | 休養日 |）
 *   - 「シーズン設計」のレース表（| レース | 日付 | 狙い | … |）
 *   - 「1回あたりのMペース量の到達目標」の表（| 時期 | 1回あたりのMペース量 |）
 *
 * splice_dashboard.js がこれを DATA.season として差し込み、ダッシュボードの「進捗」タブが
 * シーズンの現在地・次のレース・Mペース量の目標を描く。Routine が DATA に書く必要はない。
 *
 * 表の形が変わって読めなくなったら例外を投げる。splice 側はそれを警告に落とし、
 * season なしで publish を続ける（ダッシュボードの更新そのものは止めない）。
 */
const fs = require("fs");
const path = require("path");

const clean = (s) => String(s || "").replace(/\*\*/g, "").replace(/\s+/g, " ").trim();
const pad = (n) => String(n).padStart(2, "0");
const lastDay = (y, m) => new Date(Date.UTC(y, m, 0)).getUTCDate();

// 表の本体行を取り出す。header に一致する行の次の区切り行から、表が途切れるまで。
// 引用（> | … |）の中の表も読む。
function tableRows(lines, headerRe) {
  const i = lines.findIndex((l) => headerRe.test(l));
  if (i < 0) return null;
  const rows = [];
  for (let k = i + 1; k < lines.length; k++) {
    const l = lines[k].replace(/^>\s?/, "").trim();
    if (!l.startsWith("|")) break;
    if (/^\|[\s:|-]+\|$/.test(l)) continue; // 区切り行
    rows.push(l.slice(1, l.endsWith("|") ? -1 : undefined).split("|").map(clean));
  }
  return rows;
}

function parseSeason(md) {
  const lines = md.split("\n");

  // --- レース ---
  const raceRows = tableRows(lines, /^\|\s*レース\s*\|\s*日付\s*\|/);
  if (!raceRows || !raceRows.length) throw new Error("レース表（| レース | 日付 | …）が見つからない");
  const races = raceRows
    .filter((r) => /^\d{4}-\d{2}-\d{2}$/.test(r[1]))
    .map((r) => ({ name: r[0], date: r[1], aim: r[2] || "" }))
    .sort((a, b) => (a.date < b.date ? -1 : 1));
  if (!races.length) throw new Error("レース表に YYYY-MM-DD の日付を持つ行がない");

  // 本命（最後のレース）の年月を基準に、「9/1」のような月日に年を付ける。
  // 本命の月より後の月は前年（9〜12月は本命の前年、1〜3月は本命の年）。
  const main = races[races.length - 1];
  const [ry, rm] = main.date.split("-").map(Number);
  const yearOf = (m) => (m > rm ? ry - 1 : ry);
  const iso = (m, d) => `${yearOf(m)}-${pad(m)}-${pad(d)}`;
  const md2iso = (s) => {
    const m = String(s).match(/(\d{1,2})\/(\d{1,2})/);
    return m ? iso(+m[1], +m[2]) : null;
  };

  // --- フェーズ ---
  const phaseRows = tableRows(lines, /^\|\s*フェーズ\s*\|\s*期間\s*\|/);
  if (!phaseRows || !phaseRows.length) throw new Error("ロードマップ表（| フェーズ | 期間 | …）が見つからない");
  const phases = phaseRows.map((r) => {
    const w = String(r[1]).match(/(\d{1,2}\/\d{1,2})\s*〜\s*(\d{1,2}\/\d{1,2})/);
    if (!w) throw new Error(`フェーズ「${r[0]}」の期間「${r[1]}」が M/D〜M/D でない`);
    return {
      name: r[0], from: md2iso(w[1]), to: md2iso(w[2]),
      policy: r[2] || "", km: String(r[3] || "").replace(/\s*km$/, ""), quality: r[4] || "", rest: r[5] || ""
    };
  });
  for (let i = 1; i < phases.length; i++) {
    if (phases[i].from <= phases[i - 1].to) throw new Error(`フェーズの期間が重なっている: ${phases[i - 1].name} / ${phases[i].name}`);
  }

  // --- Mペース量の到達目標（任意） ---
  const mRows = tableRows(lines, /\|\s*時期\s*\|\s*1回あたりのMペース量\s*\|/) || [];
  const mTargets = mRows.map((r) => {
    const km = String(r[1]).match(/(\d+(?:\.\d+)?)\s*(?:〜\s*\d+(?:\.\d+)?\s*)?km/);
    let until = md2iso(r[0]);
    if (!until) {
      const mo = String(r[0]).match(/(\d{1,2})月/);
      if (mo) until = iso(+mo[1], lastDay(yearOf(+mo[1]), +mo[1]));
    }
    return km && until ? { label: r[0].replace(/（[^）]*）/g, "").trim(), until, km: Number(km[1]), text: r[1] } : null;
  }).filter(Boolean).sort((a, b) => (a.until < b.until ? -1 : 1));

  return { phases, races, mTargets };
}

function loadSeason(file) {
  return parseSeason(fs.readFileSync(file || path.join(__dirname, "..", "docs", "athlete_profile.md"), "utf8"));
}

module.exports = { parseSeason, loadSeason };

if (require.main === module) {
  console.log(JSON.stringify(loadSeason(process.argv[2]), null, 2));
}
