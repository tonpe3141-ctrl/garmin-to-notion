#!/usr/bin/env node
/**
 * iPhone ウィジェット用のデータを書き出す。
 *
 *   node scripts/export_widget_data.js <dashboard.html> <out.md> [--history <dir>]
 *
 * DATA から「直近のラン」「次のラン」「この先7日」「今週の距離」「レース」だけを抜き出し、
 * Notion の「📱 ウィジェット用データ」ページにそのまま入れられる本文（説明1行 + JSON コードブロック）を
 * <out.md> に書く。Routine はこの中身を notion-update-page の new_str に渡すだけでよい（STEP 6.8）。
 *
 * 中身はすでに DATA に書いてある値の丸写しなので、モデルに書き起こさせずここで機械的に作る。
 * export_run_history.js と同じ考え方。
 *
 * --history には STEP 6.7 で ArtifactData list の out_dir に保存した db の一覧を渡す。
 * 今日が休養日のとき、直近のランをそこから拾う（渡さなければ休養日を直近として出す）。
 *
 * ウィジェット本体は widget/running_widget.js。JSON のキーを変えたらそちらも直すこと。
 */
const fs = require("fs");
const path = require("path");

const PAGE_INTRO =
  "iPhone ウィジェット（Scriptable）が読むデータです。毎日 12:00 に Claude Routine が下の JSON ブロックを丸ごと書き換えます。" +
  "手で編集しないでください。仕様は `docs/daily_coach_routine.md` の STEP 6.8。";
// Notion のテキスト1要素は 2,000 文字で分割される。ウィジェット側は連結して読むが、短いほど安全。
const MAX_JSON = 1800;

const args = process.argv.slice(2);
const hi = args.indexOf("--history");
const historyDir = hi >= 0 ? args[hi + 1] : null;
const [src, out] = args.filter((_, i) => hi < 0 || (i !== hi && i !== hi + 1));
if (!src || !out) {
  console.error("usage: node scripts/export_widget_data.js <dashboard.html> <out.md> [--history <dir>]");
  process.exit(2);
}

function loadData(file) {
  const text = fs.readFileSync(file, "utf8");
  // ⚠ 正規表現で <script id="coach-data"> を探してはいけない（冒頭コメントにも同じ文字列がある）。
  //   export_run_history.js と同じく「行全体がそのタグである行」だけを目印にする。
  const lines = text.split("\n");
  const from = lines.findIndex((l) => l.trim() === '<script id="coach-data">');
  const to = from < 0 ? -1 : lines.findIndex((l, i) => i > from && l.trim() === "</script>");
  if (from < 0 || to < 0) { console.error("DATA ブロックが見つかりません: " + file); process.exit(1); }
  return Function(lines.slice(from + 1, to).join("\n") + "\n; return DATA;")();
}

const statOf = (run, label) => {
  const s = (run.stats || []).find((x) => x.label === label);
  return s ? s.value : null;
};
// 要点の見出し（6〜12字の名詞句）を2つ並べて一行コメントにする
const noteOf = (points) => (points || []).slice(0, 2).map((p) => p.label).filter(Boolean).join(" / ");
const num = (v) => (v == null || v === "" || isNaN(+v) ? null : +v);
const isRest = (r) => !r || r.type === "休養日" || r.verdict === "—";

// db の一覧から、休養日でない最新の記録を探す。一覧の保存形式に依存しないよう、
// ディレクトリ内の JSON を全部読んで「d と verdict を持つオブジェクト」を拾う。
function latestFromHistory(dir, before) {
  if (!dir || !fs.existsSync(dir)) return null;
  const found = [];
  const walk = (v) => {
    if (Array.isArray(v)) return v.forEach(walk);
    if (!v || typeof v !== "object") return;
    if (typeof v.d === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v.d) && "verdict" in v) found.push(v);
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
  const runs = found.filter((r) => !isRest(r) && r.d < before)
    .sort((a, b) => (a.d === b.d ? (b.seq || 1) - (a.seq || 1) : a.d < b.d ? 1 : -1));
  return runs[0] || null;
}

const D = loadData(src);
const today = D.today || {};
if (!today.date) { console.error("today.date がありません"); process.exit(1); }

// ---------- 直近のラン ----------
let last;
if (!isRest(today)) {
  last = {
    date: today.date, dow: today.dow || "", type: today.type || "",
    km: statOf(today, "距離"), pace: statOf(today, "平均ペース"), hr: num(statOf(today, "平均心拍")),
    verdict: today.verdict || "", label: today.verdictLabel || "", note: noteOf(today.points),
  };
} else {
  const h = latestFromHistory(historyDir, today.date);
  last = h
    ? { date: h.d, dow: h.dow || "", type: h.type || "", km: h.km, pace: h.pace, hr: num(h.hr),
        verdict: h.verdict || "", label: h.verdictLabel || "", note: noteOf(h.points) }
    : { date: today.date, dow: today.dow || "", type: "休養日", km: null, pace: null, hr: null,
        verdict: "—", label: "休養", note: "" };
}

// ---------- 次のラン ----------
const t = D.tomorrow || {};
const wp = (D.weekPlan && D.weekPlan.days) || [];
const ZONE_RANK = { R: 4, T: 3, M: 2, E: 1 };
const segs = t.segments || [];
// ウィジェットに出すペース・心拍は、その日いちばん強度の高い区間（同じ強度なら長いほう）
const main = segs.slice().sort((a, b) =>
  (ZONE_RANK[b.zone] || 0) - (ZONE_RANK[a.zone] || 0) || (b.km || 0) - (a.km || 0))[0] || {};
const kmSum = segs.reduce((s, x) => s + (+x.km || 0), 0);
const firstSentence = (s) => { const m = String(s || "").match(/^[\s\S]*?。/); return m ? m[0] : String(s || ""); };

// weekPlan の "9/26" に年を付ける。明日より前になる日付は年をまたいでいる
const year = +String(t.date || today.date).slice(0, 4);
const withYear = (d) => {
  const [m, dd] = String(d).split("/").map(Number);
  const iso = (y) => `${y}-${String(m).padStart(2, "0")}-${String(dd).padStart(2, "0")}`;
  return t.date && iso(year) < t.date ? iso(year + 1) : iso(year);
};
const plan = wp.map((p) => ({
  date: withYear(p.d), dow: p.dow || "", type: p.type || "E", title: p.title || "", km: String(p.km ?? ""), note: p.note || "",
}));
const next = t.date ? {
  date: t.date, dow: t.dow || "",
  type: (plan[0] && plan[0].date === t.date && plan[0].type) || main.zone || "E",
  title: t.title || "",
  km: kmSum ? String(Math.round(kmSum * 10) / 10) : (plan[0] ? plan[0].km : ""),
  pace: main.pace || "", hr: main.hr || "",
  headline: firstSentence(t.headline),
} : null;

// ---------- レース ----------
// ウィジェットでは「◯◯まで N日」と出すので短くする（例: 水戸黄門漫遊マラソン → 水戸黄門）
const shortName = (n) => {
  let s = String(n || "").replace(/[（(][^）)]*[）)]/g, "").replace(/マラソン$/, "").trim();
  if (s.length > 5) s = s.slice(0, 4);
  return s;
};
const races = [D.tuneup, D.race].filter((r) => r && r.date)
  .map((r) => ({ name: shortName(r.name), date: r.date }))
  .sort((a, b) => (a.date < b.date ? -1 : 1));

const widget = {
  v: 1,
  generatedAt: String((D.meta && D.meta.generatedAt) || "").replace(/\s*JST$/, ""),
  last, next, plan,
  week: D.week ? { km: D.week.totalKm, target: D.week.targetKm } : null,
  races,
};

let json = JSON.stringify(widget);
// 長すぎるときは、ウィジェットで一番後ろに出る plan の note から削る
if (json.length > MAX_JSON) { widget.plan.forEach((p) => { p.note = ""; }); json = JSON.stringify(widget); }
if (json.length > MAX_JSON) { console.error(`JSON が ${json.length} 文字あり、上限 ${MAX_JSON} を超えています`); process.exit(1); }

fs.writeFileSync(out, `${PAGE_INTRO}\n\n\`\`\`json\n${json}\n\`\`\`\n`);
console.log(`${out} (${json.length} chars) last=${last.date} ${last.verdict} ${last.type} / next=${next ? next.date + " " + next.title : "なし"} / plan=${plan.length}日`);
