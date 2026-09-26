#!/usr/bin/env node
/**
 * ダッシュボードを publish する前に、DATA と HTML の骨格を機械的に検証する。
 *
 *   node scripts/check_dashboard.js dashboard/index.html [--render] [--shot out.png]
 *
 * 見るもの:
 *   - HTML の骨格（publish ラッパーの残り、DATA 代入文の重複、コメント閉じタグ、#app）
 *     → ここが壊れるとページが真っ白になる（2026-08-24 に実際に発生）
 *   - DATA のキーの抜け・廃止キー・列挙値・日付の整合・件数
 *   - 週プラン／週間ロードの合計と日付の連続
 *   - --render: Chromium があれば実際に描画し、#app に今日の日付が出るかを見る
 *   - --shot:   描画結果を PNG に保存する（目視確認用。--render を含む）
 *
 * 終了コード: 0 = OK（警告だけ）, 1 = エラーあり, 2 = 使い方の誤り
 * splice_dashboard.js からも呼ばれる（module.exports.check）。
 */
const fs = require("fs");
const path = require("path");
const { spawnSync } = require("child_process");

const DOW = ["日", "月", "火", "水", "木", "金", "土"];
const ZONES = ["E", "M", "T", "R", "rest"];
const TONES = ["good", "bad", "note"];
const STAT_STATES = ["ok", "warn", "crit"];
const AXIS_STATES = ["good", "warn", "crit"];
const VERDICTS = ["◎", "○", "△", "✕", "—"];

// ---------- helpers ----------
const isoDate = (s) => typeof s === "string" && /^\d{4}-\d{2}-\d{2}$/.test(s) && !isNaN(Date.parse(s));
const md = (iso) => { const [, m, d] = iso.split("-"); return `${Number(m)}/${Number(d)}`; };
const dowOf = (iso) => DOW[new Date(iso + "T00:00:00").getDay()];
const addDays = (iso, n) => {
  const d = new Date(iso + "T00:00:00");
  d.setDate(d.getDate() + n);
  return d.toISOString().slice(0, 10);
};
const daysBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
const numOf = (v) => { const m = String(v == null ? "" : v).match(/\d+(\.\d+)?/); return m ? Number(m[0]) : null; };
const isNum = (v) => typeof v === "number" && isFinite(v);
const isStr = (v) => typeof v === "string" && v.trim() !== "";
const arr = (v) => Array.isArray(v) ? v : null;

function extractData(html) {
  const lines = html.split("\n");
  const from = lines.findIndex((l) => l.trim() === '<script id="coach-data">');
  const to = from < 0 ? -1 : lines.findIndex((l, i) => i > from && l.trim() === "</script>");
  if (from < 0 || to < 0) return null;
  return Function(lines.slice(from + 1, to).join("\n") + "\n; return DATA;")();
}

// ---------- checks ----------
function check(html, opts = {}) {
  const errors = [], warns = [], infos = [];
  const err = (m) => errors.push(m);
  const warn = (m) => warns.push(m);
  const info = (m) => infos.push(m);

  // --- 骨格 ---
  if (html.startsWith("<!doctype html><html><head>")) err("1行目に publish 時のラッパーが残っている。取り除くこと");
  const bodyEnds = (html.match(/<\/body><\/html>/g) || []).length;
  if (bodyEnds !== 1) err(`</body></html> が ${bodyEnds} 個ある（1個であること）`);
  if (!html.trimEnd().endsWith("</body></html>")) err("ファイル末尾が </body></html> で終わっていない");
  const assigns = (html.match(/^const DATA = \{/gm) || []).length;
  if (assigns !== 1) err(`DATA の代入文が ${assigns} 個ある（1個であること）`);
  for (const marker of ["-->", '<script id="coach-data">', '<div class="wrap" id="app">']) {
    if (!html.includes(marker)) err(`目印 ${marker} が消えている。置換範囲が広すぎる`);
  }
  // 目印は「行全体がそのタグの行」で探す（説明コメントの中にも同じ文字列が出てくるため）
  const hl = html.split("\n");
  const cLine = hl.findIndex((l) => l.trim() === "-->");
  const sLine = hl.findIndex((l) => l.trim() === '<script id="coach-data">');
  if (sLine < 0) err('行全体が <script id="coach-data"> の行がない');
  if (cLine >= 0 && sLine >= 0 && cLine > sLine) err("説明コメントの閉じタグ --> が DATA より後ろにある。コメントに飲み込まれている");

  let D;
  try { D = extractData(html); } catch (e) { err(`DATA が JavaScript として評価できない: ${e.message}`); }
  if (!D) { if (!errors.length) err("DATA ブロックが見つからない"); return { errors, warns, infos, data: null }; }

  // --- 廃止キー ---
  if ("alerts" in D) err("廃止キー DATA.alerts がある（2026-09-06 廃止）");
  if (D.today && "verdictReason" in D.today) err("廃止キー today.verdictReason がある");
  if (D.weekPlan && "policy" in D.weekPlan) err("廃止キー weekPlan.policy がある（aim を使う）");
  (arr(D.axes) || []).forEach((a, i) => { if (a && "text" in a) err(`廃止キー axes[${i}].text がある（summary を使う）`); });

  // --- meta ---
  const m = D.meta || {};
  if (!isStr(m.generatedAt)) err("meta.generatedAt がない");
  if (!isStr(m.sourceUpdatedAt)) err("meta.sourceUpdatedAt がない");
  if (typeof m.sourceFresh !== "boolean") err("meta.sourceFresh は true/false");
  if (!isStr(m.note)) warn("meta.note が空");

  // --- today ---
  const t = D.today || {};
  const today = t.date;
  if (!isoDate(today)) err("today.date が YYYY-MM-DD でない");
  else if (t.dow !== dowOf(today)) err(`today.dow "${t.dow}" が ${today} の曜日 ${dowOf(today)} と違う`);
  if (!isStr(t.type)) err("today.type がない");
  if (!VERDICTS.includes(t.verdict)) err(`today.verdict "${t.verdict}" は ${VERDICTS.join(" ")} のいずれか`);
  if (!isStr(t.verdictLabel)) err("today.verdictLabel がない");
  if (!isStr(t.headline)) err("today.headline がない");
  const rest = t.type === "休養日" || t.verdict === "—";
  if (rest) {
    if (t.verdict !== "—" || t.type !== "休養日") err('休養日は type "休養日" と verdict "—" を両方そろえる');
    if ((arr(t.stats) || []).length) err("休養日の stats は空配列");
    if ((arr(t.laps) || []).length) err("休養日の laps は空配列");
  }
  const pts = arr(t.points);
  if (!pts) err("today.points が配列でない");
  else {
    if (pts.length < 4) warn(`today.points が ${pts.length} 個（4〜7個が規定）`);
    if (pts.length > 7) err(`today.points が ${pts.length} 個（最大7個）`);
    pts.forEach((p, i) => {
      if (!TONES.includes(p.tone)) err(`points[${i}].tone "${p.tone}" は good/bad/note`);
      if (!isStr(p.label)) err(`points[${i}].label がない`);
      else if (p.label.length > 14) warn(`points[${i}].label が ${p.label.length} 字（6〜12字の名詞句）`);
      if (!isStr(p.text)) err(`points[${i}].text がない`);
      else if (!/\d/.test(p.text)) warn(`points[${i}].text に数字がない（規約2）`);
    });
  }
  const stats = arr(t.stats) || [];
  stats.forEach((s, i) => {
    if (!isStr(s.label)) err(`stats[${i}].label がない`);
    if (s.value == null || s.value === "") err(`stats[${i}].value がない`);
    if (!STAT_STATES.includes(s.state)) err(`stats[${i}].state "${s.state}" は ok/warn/crit`);
  });
  if (!rest) {
    for (const need of ["距離", "平均ペース", "平均心拍"]) {
      if (!stats.some((s) => s.label === need)) err(`stats に「${need}」がない（履歴の一覧行が空になる）`);
    }
    if (!isStr(t.effect)) err("today.effect がない");
  }
  const laps = arr(t.laps) || [];
  laps.forEach((l, i) => {
    if (!Number.isInteger(l.sec) || l.sec <= 0) err(`laps[${i}].sec は正の整数（秒）`);
    if (!isStr(l.pace)) err(`laps[${i}].pace がない`);
    else if (Number.isInteger(l.sec)) {
      const p = `${Math.floor(l.sec / 60)}:${String(l.sec % 60).padStart(2, "0")}`;
      if (p !== l.pace) err(`laps[${i}] pace "${l.pace}" と sec ${l.sec}（=${p}）が食い違う`);
    }
    if (!(l.hr === null || isNum(l.hr))) err(`laps[${i}].hr は数値か null`);
  });
  // 同じ日の2本目以降（任意）。1本目と同じ形で、履歴には <日付>-2 … として書かれる
  if (t.extra != null) {
    const ex = arr(t.extra);
    if (!ex) err("today.extra は配列");
    else ex.forEach((r, i) => {
      if (!isStr(r.type)) err(`extra[${i}].type がない`);
      if (!VERDICTS.includes(r.verdict)) err(`extra[${i}].verdict "${r.verdict}" は ${VERDICTS.join(" ")} のいずれか`);
      if (!isStr(r.headline)) err(`extra[${i}].headline がない`);
      if (!(arr(r.stats) || []).some((s) => s.label === "距離")) err(`extra[${i}].stats に「距離」がない`);
      (arr(r.laps) || []).forEach((l, j) => {
        if (!Number.isInteger(l.sec) || l.sec <= 0) err(`extra[${i}].laps[${j}].sec は正の整数`);
      });
    });
  }
  if (t.plan != null) {
    if (!isStr(t.plan.title)) err("today.plan.title がない");
    if (!isNum(t.plan.km)) err("today.plan.km は数値");
  } else if (!rest) {
    warn("today.plan がない（昨日の処方と実走の対比が出ない。tomorrow から写す）");
  }

  // --- race / tuneup / phase ---
  const r = D.race || {};
  for (const k of ["name", "date", "goal", "pace"]) if (!isStr(r[k])) err(`race.${k} がない`);
  if (!Number.isInteger(r.daysLeft)) err("race.daysLeft は整数");
  else if (isoDate(r.date) && isoDate(today) && daysBetween(today, r.date) !== r.daysLeft) {
    err(`race.daysLeft ${r.daysLeft} が ${today}→${r.date} の日数 ${daysBetween(today, r.date)} と違う`);
  }
  if (D.tuneup != null) {
    if (!isStr(D.tuneup.name) || !isoDate(D.tuneup.date)) err("tuneup は null か {name,date,daysLeft}");
    else if (isoDate(today) && daysBetween(today, D.tuneup.date) !== D.tuneup.daysLeft) err("tuneup.daysLeft が日付と合わない");
  }
  const ph = D.phase || {};
  for (const k of ["name", "window", "policy", "weeklyTarget"]) if (!isStr(ph[k])) err(`phase.${k} がない`);

  // --- axes / good / issues ---
  const axes = arr(D.axes);
  if (!axes || axes.length !== 4) err("axes は4軸");
  (axes || []).forEach((a, i) => {
    if (!isStr(a.name)) err(`axes[${i}].name がない`);
    if (!AXIS_STATES.includes(a.state)) err(`axes[${i}].state "${a.state}" は good/warn/crit`);
    if (!isStr(a.summary)) err(`axes[${i}].summary がない`);
  });
  for (const k of ["good", "issues"]) {
    const v = arr(D[k]);
    if (!v || !v.length) err(`${k} が空`);
    else v.forEach((s, i) => { if (!isStr(s)) err(`${k}[${i}] が空文字`); });
  }
  if (m.sourceFresh === false && !(arr(D.issues) || []).some((s) => /最新|日前|同期/.test(s))) {
    warn("sourceFresh=false なのに issues にデータ鮮度の指摘がない");
  }

  // --- tomorrow ---
  const tm = D.tomorrow || {};
  if (!isoDate(tm.date)) err("tomorrow.date が YYYY-MM-DD でない");
  else {
    if (isoDate(today) && tm.date !== addDays(today, 1)) err(`tomorrow.date ${tm.date} は today+1（${addDays(today, 1)}）であること`);
    if (tm.dow !== dowOf(tm.date)) err(`tomorrow.dow "${tm.dow}" が曜日 ${dowOf(tm.date)} と違う`);
  }
  for (const k of ["title", "headline", "why", "next"]) if (!isStr(tm[k])) err(`tomorrow.${k} がない`);
  const segs = arr(tm.segments);
  if (!segs || !segs.length) err("tomorrow.segments が空");
  else segs.forEach((s, i) => {
    if (!ZONES.includes(s.zone)) err(`segments[${i}].zone "${s.zone}" は E/M/T/R/rest`);
    if (!isNum(s.km)) err(`segments[${i}].km は数値`);
    if (!isStr(s.label)) err(`segments[${i}].label がない`);
    for (const k of ["pace", "hr", "note"]) if (!isStr(s[k])) err(`segments[${i}].${k} がない（無い区間は "—"）`);
  });
  const rx = arr(tm.prescription);
  if (!rx) err("tomorrow.prescription が配列でない");
  else rx.forEach((p, i) => { if (!isStr(p.k) || !isStr(p.v)) err(`prescription[${i}] は {k, v}`); });
  const alt = arr(tm.alt);
  if (!alt || !alt.length) err("tomorrow.alt は配列（1条件1要素）");
  else alt.forEach((s, i) => { if (/^[①②③④⑤]/.test(String(s))) warn(`alt[${i}] に丸数字がある（描画側が番号を振る）`); });

  // --- weekPlan ---
  const wp = D.weekPlan || {};
  if (!isStr(wp.label)) err("weekPlan.label がない");
  if (!isStr(wp.aim)) err("weekPlan.aim がない");
  if (!isStr(wp.totalKm)) err("weekPlan.totalKm は文字列");
  const pd = arr(wp.days);
  if (!pd || pd.length !== 7) err("weekPlan.days は7日");
  else {
    let sum = 0, quality = 0, restDays = 0;
    pd.forEach((d, i) => {
      if (!ZONES.includes(d.type)) err(`weekPlan.days[${i}].type "${d.type}" は E/M/T/R/rest`);
      if (typeof d.km !== "string") err(`weekPlan.days[${i}].km は文字列（"14〜16" / "0"）`);
      if (!isStr(d.title)) err(`weekPlan.days[${i}].title がない`);
      if (isoDate(tm.date)) {
        const want = addDays(tm.date, i);
        if (d.d !== md(want)) err(`weekPlan.days[${i}].d "${d.d}" は ${md(want)} であること（明日から連続7日）`);
        if (d.dow !== dowOf(want)) err(`weekPlan.days[${i}].dow "${d.dow}" は ${dowOf(want)}`);
      }
      sum += numOf(d.km) || 0;
      if (["M", "T", "R"].includes(d.type)) quality++;
      if (d.type === "rest") restDays++;
    });
    const tot = numOf(wp.totalKm);
    if (tot != null && Math.abs(tot - sum) > 3) warn(`weekPlan.totalKm "${wp.totalKm}" と days の合計 ${sum}km が3km以上ずれている`);
    info(`weekPlan: ${sum}km（下限側）／ 質練習 ${quality}本 ／ 休養 ${restDays}日`);
    // 規定はプロファイルのロードマップ表（DATA.season）から、週プランの初日が属するフェーズのものを使う。
    // 回復週・テーパー週に「質3本」を求めて誤警告しないため。season が無ければ従来どおり 3本 / 1日。
    const ph = D.season && arr(D.season.phases) && isoDate(tm.date)
      ? D.season.phases.find((p) => p.from <= tm.date && tm.date <= p.to) : null;
    const nums = (v) => (String(v || "").match(/\d+/g) || []).map(Number);
    const qMin = ph && nums(ph.quality).length ? nums(ph.quality)[0] : 3;
    const rMax = ph && nums(ph.rest).length ? Math.max(...nums(ph.rest)) : 1;
    const who = ph ? ph.name : "Phase 4/5";
    if (quality < qMin) warn(`weekPlan の質練習が ${quality}本。${who} は週${qMin}本が下限。落とすなら理由を aim と issues に書くこと`);
    if (qMin === 0 && quality > 0) warn(`weekPlan に質練習が ${quality}本ある。${who} は質ゼロの週`);
    if (restDays > rMax) warn(`weekPlan の休養日が ${restDays}日。${who} は週${rMax}日まで。増やすなら警戒サインを aim と issues に書くこと`);
  }

  // --- week ---
  const wk = D.week || {};
  if (!isStr(wk.label)) err("week.label がない");
  for (const k of ["totalKm", "prevKm", "monthKm", "monthTargetKm"]) if (!isNum(wk[k])) err(`week.${k} は数値`);
  for (const k of ["runs", "monthDayCount"]) if (!Number.isInteger(wk[k])) err(`week.${k} は整数`);
  if (!isStr(wk.targetKm)) err("week.targetKm は文字列（\"70〜85\"）");
  if (wk.remainingDays != null && !(Number.isInteger(wk.remainingDays) && wk.remainingDays >= 0 && wk.remainingDays <= 7)) {
    err("week.remainingDays は 0〜7 の整数（省略可）");
  }
  const wd = arr(wk.days);
  if (!wd || wd.length !== 7) err("week.days は7日");
  else {
    let sum = 0, runs = 0;
    wd.forEach((d, i) => {
      if (!ZONES.includes(d.type)) err(`week.days[${i}].type "${d.type}" は E/M/T/R/rest`);
      if (!isNum(d.km)) err(`week.days[${i}].km は数値`);
      if (!(d.hr === null || isNum(d.hr))) err(`week.days[${i}].hr は数値か null`);
      sum += d.km || 0;
      if (d.km > 0) runs++;
    });
    if (isNum(wk.totalKm) && Math.abs(sum - wk.totalKm) > 0.05) err(`week.totalKm ${wk.totalKm} と days の合計 ${sum.toFixed(2)} が合わない`);
    if (Number.isInteger(wk.runs) && runs !== wk.runs) warn(`week.runs ${wk.runs} と km>0 の日数 ${runs} が違う（同日2本なら可）`);
    if (wk.remainingDays == null && wd.some((d) => d.km === 0 && d.type !== "rest")) {
      warn("week.days に km 0 で type が rest 以外の日がある（未走の日）。進行中の週なら week.remainingDays を入れること");
    }
  }

  // --- health ---
  const h = D.health || {};
  if (!isStr(h.label)) err("health.label がない");
  const bl = h.baseline || {};
  if (!isNum(bl.hrvLow) || !isNum(bl.hrvHigh)) err("health.baseline.hrvLow/hrvHigh は数値");
  if (!isStr(bl.hrvStatus)) err("health.baseline.hrvStatus がない");
  const hs = arr(h.summary);
  if (!hs || !hs.length) err("health.summary が空");
  else hs.forEach((s, i) => {
    if (!isStr(s.label)) err(`health.summary[${i}].label がない`);
    if (!(s.value === null || isNum(s.value))) err(`health.summary[${i}].value は数値か null`);
    if (!(s.avg === null || isNum(s.avg))) err(`health.summary[${i}].avg は数値か null`);
    if (!(s.prev === null || s.prev === undefined || isNum(s.prev))) err(`health.summary[${i}].prev は数値か null`);
    if (!STAT_STATES.includes(s.state)) err(`health.summary[${i}].state "${s.state}" は ok/warn/crit`);
    if (!isStr(s.note)) err(`health.summary[${i}].note がない`);
    if (/安静|ストレス/.test(String(s.label)) && s.lowerIsBetter !== true) {
      err(`health.summary[${i}]「${s.label}」に lowerIsBetter: true がない（赤緑が逆になる）`);
    }
  });
  if (!isNum(h.sleepTargetMin)) err("health.sleepTargetMin は数値（通常 420）");
  const hd = arr(h.days);
  if (!hd || hd.length !== 7) err("health.days は直近7日");
  else {
    const keys = ["hrv", "rhr", "sleep", "sleepMin", "sleepDeep", "sleepRem", "sleepLight", "bbLow", "stress", "readiness"];
    hd.forEach((d, i) => {
      if (!isStr(d.d) || !isStr(d.dow)) err(`health.days[${i}] に d/dow がない`);
      for (const k of keys) {
        if (!(k in d)) err(`health.days[${i}].${k} がない（取れない日は null）`);
        else if (!(d[k] === null || isNum(d[k]))) err(`health.days[${i}].${k} は数値か null`);
      }
      // 歩数（2026-09-26 追加・任意）。当日は途中値なので null にする
      if ("steps" in d && !(d.steps === null || isNum(d.steps))) err(`health.days[${i}].steps は数値か null`);
      if (i === hd.length - 1) {
        for (const k of ["bbLow", "stress", "steps"]) {
          if (isNum(d[k])) warn(`health.days の当日（${d.d}）の ${k} に値がある。取得時点までの途中値なので null にすること`);
        }
      }
      if (isoDate(today)) {
        const want = addDays(today, i - 6);
        if (d.d !== md(want)) err(`health.days[${i}].d "${d.d}" は ${md(want)}（今日を末尾に7日）`);
      }
    });
    const missing = hd.filter((d) => keys.every((k) => d[k] === null)).map((d) => d.d);
    if (missing.length) info(`health.days 全項目 null の日: ${missing.join(", ")}`);
    if (!hd.some((d) => "steps" in d)) warn("health.days に steps がない（歩数列が出ない。ドキュメントの「歩数」を写す）");
  }
  const f = h.fitness || {};
  if (!f.race || !Object.values(f.race).some(isStr)) warn("health.fitness.race にレース予測がない");
  if (!isStr(h.read)) err("health.read がない");

  // --- season（splice_dashboard.js が docs/athlete_profile.md から差し込む。Routine は書かない） ---
  if (D.season != null) {
    const ss = D.season;
    if (!arr(ss.phases) || !ss.phases.length) err("season.phases が空");
    else ss.phases.forEach((p, i) => {
      if (!isStr(p.name) || !isoDate(p.from) || !isoDate(p.to) || p.from > p.to) err(`season.phases[${i}] の name/from/to が不正`);
    });
    if (!arr(ss.races) || !ss.races.every((r) => isStr(r.name) && isoDate(r.date))) err("season.races が不正");
    if (isoDate(today) && arr(ss.phases) && !ss.phases.some((p) => p.from <= today && today <= p.to)) {
      warn(`今日（${today}）を含むフェーズが season にない。プロファイルのロードマップ表を確認すること`);
    }
    if (arr(ss.races) && D.race && isStr(D.race.date) && !ss.races.some((r) => r.date === D.race.date)) {
      warn(`race.date ${D.race.date} がプロファイルのレース表に無い。DATA.race とプロファイルが食い違っている`);
    }
  } else {
    info("DATA.season がない（splice_dashboard.js を通していないか、プロファイルを読めなかった）");
  }

  // --- 描画（任意） ---
  if (opts.render || opts.shot) {
    const res = renderCheck(opts.file, opts.shot);
    if (res.skipped) warn(`描画確認をスキップ: ${res.skipped}`);
    else if (res.error) err(`描画確認に失敗: ${res.error}`);
    else {
      if (!res.dom.includes(`class="hero-date">${today}<`)) err("描画結果に today.date が出ていない（ページが真っ白か、スクリプトが落ちている）");
      else info("描画確認 OK（#app に今日の日付が出ている）");
      if (opts.shot) info(`スクリーンショット: ${opts.shot}`);
    }
  }

  return { errors, warns, infos, data: D };
}

// Chromium で描画して DOM を取り出す。Playwright は不要（バイナリだけあればよい）。
function findChromium() {
  const cands = [
    process.env.CHROMIUM_BIN,
    "/opt/pw-browsers/chromium",
    "/usr/bin/chromium", "/usr/bin/chromium-browser", "/usr/bin/google-chrome",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium"
  ].filter(Boolean);
  return cands.find((p) => { try { return fs.statSync(p).isFile() || fs.lstatSync(p).isSymbolicLink(); } catch { return false; } });
}

function renderCheck(file, shot) {
  const bin = findChromium();
  if (!bin) return { skipped: "Chromium が見つからない（CHROMIUM_BIN で指定できる）" };
  const url = "file://" + path.resolve(file);
  const common = ["--headless=new", "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
    "--hide-scrollbars", "--virtual-time-budget=3000"];
  const dump = spawnSync(bin, [...common, "--dump-dom", url], { encoding: "utf8", timeout: 60000 });
  if (dump.error || dump.status !== 0) return { error: (dump.error && dump.error.message) || dump.stderr.slice(-400) };
  if (shot) {
    const s = spawnSync(bin, [...common, "--window-size=1100,2400", `--screenshot=${path.resolve(shot)}`, url],
      { encoding: "utf8", timeout: 60000 });
    if (s.error || s.status !== 0) return { error: "screenshot: " + ((s.error && s.error.message) || s.stderr.slice(-400)) };
  }
  return { dom: dump.stdout };
}

function report({ errors, warns, infos }) {
  for (const s of infos) console.log("  · " + s);
  for (const s of warns) console.log("  ⚠ " + s);
  for (const s of errors) console.log("  ✕ " + s);
  console.log(errors.length ? `NG: エラー ${errors.length} 件、警告 ${warns.length} 件`
    : `OK: エラーなし、警告 ${warns.length} 件`);
  return errors.length ? 1 : 0;
}

module.exports = { check, extractData, report };

if (require.main === module) {
  const args = process.argv.slice(2);
  const file = args.find((a) => !a.startsWith("--"));
  const shotIdx = args.indexOf("--shot");
  const shot = shotIdx >= 0 ? args[shotIdx + 1] : null;
  if (!file || (shotIdx >= 0 && !shot)) {
    console.error("usage: node scripts/check_dashboard.js <dashboard.html> [--render] [--shot out.png]");
    process.exit(2);
  }
  const html = fs.readFileSync(file, "utf8");
  process.exit(report(check(html, { file, render: args.includes("--render"), shot })));
}
