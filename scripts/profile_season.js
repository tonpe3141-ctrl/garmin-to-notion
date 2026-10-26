#!/usr/bin/env node
/**
 * docs/athlete_profile.md からシーズンの骨格を機械的に読み出す。
 *
 *   node scripts/profile_season.js [docs/athlete_profile.md]   … 読み取り結果を JSON で表示（確認用）
 *
 * 読むのはプロファイルに既にある4つの表だけ（ここに値を書き写さない。写すと前提が分裂する）:
 *   - 「レースまでのロードマップ」の表（| フェーズ | 期間 | 方針 | 週間距離 | 質練習 | 休養日 |）
 *   - 「シーズン設計」のレース表（| レース | 日付 | 狙い | … |）
 *   - 「1回あたりのMペース量の到達目標」の表（| 時期 | 1回あたりのMペース量 |）
 *   - 「ペースゾーン定義」の表（| ゾーン | ペース | 心拍目安 |）と「現在は段階X。」の1文（任意。2026-10-19 追加）
 *     → ダッシュボードのラップの色分け・心拍上限の線・Mペースの持続力の上限・E帯の心拍が、段階を変えると自動で追従する
 *     ステディ（ロング専用）の行も読む（任意。2026-10-26 追加）
 *   以下はすべて任意（読めなければ null / 空配列で、ダッシュボードはその部分を出さないだけ。2026-10-26 追加）:
 *   - 「月間距離について」の表（| 月 | 見込み | 内訳 |）→ 月ごとの距離の計画（ホームの月間目標・月間走行距離の基準線）
 *   - 「段階的なペースの引き上げ」の表（| 段階 | 走力（VDOT） | M | T | I | … |）→ 走力の階段
 *   - 「キロ4分の位置を動かす」の表（| 段階 | 4:00 の位置 | VDOT | 5km の目安 | 確かめる練習 | 時期 |）→ 次の判定
 *   - 「確度を上げる条件」の表（| 積み上げの目標 | 目安 | 数え始め | 期限 |）→ 積み上げの目標の進み具合
 *
 * splice_dashboard.js がこれを DATA.season として差し込み、ダッシュボードの「予定」タブとホームが
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

  // 「11月中旬」のような日付は旬の真ん中（5・15・25日）で近似し、label に元の書き方を残す
  const whenOf = (s) => {
    const iso2 = md2iso(s);
    if (iso2) return { date: iso2, approx: false };
    const m = String(s).match(/(\d{1,2})月(上旬|中旬|下旬)?/);
    if (!m) return null;
    const day = { 上旬: 5, 中旬: 15, 下旬: 25 }[m[2]] || lastDay(yearOf(+m[1]), +m[1]);
    return { date: iso(+m[1], day), approx: true };
  };

  return {
    phases, races, mTargets, zones: parseZones(lines, md),
    months: parseMonths(lines, iso, yearOf),
    stages: parseStages(lines),
    milestones: parseMilestones(lines, whenOf),
    goals: parseGoals(lines, md2iso),
  };
}

const secOf = (s) => { const m = String(s).match(/^(\d{1,2}):(\d{2})(?::(\d{2}))?$/); return m ? (m[3] != null ? +m[1] * 3600 + +m[2] * 60 + +m[3] : +m[1] * 60 + +m[2]) : null; };
const timesIn = (s) => (String(s).match(/\d{1,2}:\d{2}(?::\d{2})?/g) || []).map(secOf).filter((x) => x != null);
const numsIn = (s) => (String(s).match(/\d+(?:\.\d+)?/g) || []).map(Number);

/* 月ごとの距離の計画。[{ ym: "2026-11", km: 355, text }] */
function parseMonths(lines, iso, yearOf) {
  const rows = tableRows(lines, /\|\s*月\s*\|\s*見込み\s*\|/) || [];
  return rows.map((r) => {
    const mo = String(r[0]).match(/^(\d{1,2})月/);
    const km = String(r[1]).match(/(\d+)\s*km/);
    return mo && km ? { ym: iso(+mo[1], 1).slice(0, 7), km: +km[1], text: r[2] || "" } : null;
  }).filter(Boolean);
}

/* 段階の表。[{ name: "A+", vdot: [53, 54], m: [252, 258], t: [...], i: [...], k5: 1137, current, cond }]
   k5 はその段階に入れる 5km の遅い側（例: A は 18:58〜19:30 → 19:30）。「以上」の段階（いちばん下）は null。 */
function parseStages(lines) {
  const rows = tableRows(lines, /^\|\s*段階\s*\|\s*走力（VDOT）\s*\|/) || [];
  return rows.map((r) => {
    const name = String(r[0]).split(/[（(\s]/)[0];
    if (!name) return null;
    const cond = r[5] || "";
    const k5txt = (String(cond).match(/5km\s*([\d:〜\s]+(?:以内|以上)?)/) || [])[1] || "";
    const k5s = timesIn(k5txt);
    return {
      name, vdot: numsIn(r[1]).slice(0, 2),
      m: paceRange(r[2]), t: paceRange(r[3]), i: paceRange(r[4]),
      k5: /以上/.test(k5txt) || !k5s.length ? null : Math.max(...k5s),
      current: /現在/.test(r[0]), cond,
    };
  }).filter(Boolean);
}

/* キロ4分の位置の表（判定の機会）。[{ step: "②", label: "4:00 が閾値", vdot: [54], k5: [1120], check, when: "11/21 の 5km TT", date, approx }] */
function parseMilestones(lines, whenOf) {
  const rows = tableRows(lines, /^\|\s*段階\s*\|\s*4:00 の位置\s*\|/) || [];
  return rows.map((r) => {
    const w = whenOf(r[5]);
    const step = (String(r[0]).match(/^[①-⑳]/) || [""])[0];
    return {
      step, label: String(r[0]).replace(/^[①-⑳]\s*/, "").replace(/（[^）]*）/g, "").trim(),
      vdot: numsIn(r[2]).slice(0, 2), k5: timesIn(r[3]), check: r[4] || "", when: r[5] || "",
      date: w ? w.date : null, approx: w ? w.approx : false, done: /確定/.test(r[5] || ""),
    };
  });
}

/* 積み上げの目標。[{ label, target: "8〜10本", n: 8, from, to }]。n は目安の最初の数（無ければ null） */
function parseGoals(lines, md2iso) {
  const rows = tableRows(lines, /^\|\s*積み上げの目標\s*\|/) || [];
  return rows.map((r) => ({
    label: r[0], target: r[1], n: numsIn(r[1]).length ? numsIn(r[1])[0] : null,
    from: md2iso(r[2]), to: md2iso(r[3]),
  })).filter((g) => g.label);
}

// 「4:15〜4:25 /km」→ [255, 265]（速い側, 遅い側）。読めなければ null
const paceRange = (s) => {
  const m = String(s).match(/(\d{1,2}):(\d{2})\s*〜\s*(\d{1,2}):(\d{2})/);
  if (!m) return null;
  const a = +m[1] * 60 + +m[2], b = +m[3] * 60 + +m[4];
  return [Math.min(a, b), Math.max(a, b)];
};
// 心拍の上限。「上限167」があればそれ、なければ「≤ 140」、なければ帯の上の値。「管理なし」は null
const hrCap = (s) => {
  const t = String(s);
  const m = t.match(/上限\s*(\d{3})/) || t.match(/≤\s*(\d{3})/);
  if (m) return +m[1];
  const all = t.match(/\d{3}/g);
  return all ? +all[all.length - 1] : null;
};

/* ペースゾーン（任意）。E / M / T / R の4つが読めたときだけ返す。読めなければ null（描画側は既定値で描く）。
   { stage: "A", E: { pace: [330, 360], hr: 140 }, M: {…}, T: {…}, R: {…}, I: {…} } */
function parseZones(lines, md) {
  const rows = tableRows(lines, /^\|\s*ゾーン\s*\|\s*ペース\s*\|/);
  if (!rows || !rows.length) return null;
  const out = {};
  for (const r of rows) {
    const key = /^E/.test(r[0]) ? "E" : /^M/.test(r[0]) ? "M" : /^T/.test(r[0]) ? "T" : /^R/.test(r[0]) ? "R"
      : /インターバル/.test(r[0]) ? "I" : /^ステディ/.test(r[0]) ? "S" : null;
    const pace = paceRange(r[1]);
    if (key && pace) out[key] = { pace, hr: /管理なし/.test(r[2] || "") ? null : hrCap(r[2] || "") };
  }
  if (!["E", "M", "T", "R"].every((k) => out[k])) return null;
  // 帯が速い順に並んでいること（R < T < M < E）。崩れていたら色分けの境界が引けないので使わない
  if (!(out.R.pace[1] <= out.T.pace[0] && out.T.pace[1] <= out.M.pace[0] && out.M.pace[1] <= out.E.pace[0])) return null;
  // ステディは M と E の間にあるときだけ使う（任意）
  if (out.S && !(out.M.pace[1] <= out.S.pace[0] && out.S.pace[1] <= out.E.pace[0])) delete out.S;
  const st = String(md).match(/現在は段階\s*([^\s。*（(]+)/);
  out.stage = st ? st[1] : null;
  return out;
}

function loadSeason(file) {
  return parseSeason(fs.readFileSync(file || path.join(__dirname, "..", "docs", "athlete_profile.md"), "utf8"));
}

module.exports = { parseSeason, loadSeason };

if (require.main === module) {
  console.log(JSON.stringify(loadSeason(process.argv[2]), null, 2));
}
