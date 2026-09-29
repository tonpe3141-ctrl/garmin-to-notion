#!/usr/bin/env node
/**
 * 「成長の記録」タブ（カレンダー・推移）用の履歴を書き出す。
 *
 *   node scripts/export_run_history.js <dashboard.html | entry.json> <out.json>
 *
 * 入力は次のどちらか:
 *   - dashboard.html … DATA.today を写す（毎日の STEP 6.6）
 *   - entry.json     … DATA.today と同じ形のオブジェクト1つ（取りこぼした日の後追い記録。STEP 6.7）
 *
 * 中身はすでに書いてある値の丸写しなので、モデルに書き起こさせずここで機械的にコピーする。
 * 日々の生成コストを増やさないための仕組み。出来た JSON を ArtifactData の set / batch に
 * file_path で渡す。
 *
 * 同じ日に2本以上走った日は `extra: [ {…} ]` に2本目以降を DATA.today と同じ形で入れる。
 * 2本目以降は doc_id `<日付>-2`, `<日付>-3` … として <out>-2.json, <out>-3.json … に書く。
 * 最後に「doc_id -> ファイル」の一覧を出すので、そのまま batch 書き込みに使う。
 */
const fs = require("fs");
const path = require("path");

const [src, out] = process.argv.slice(2);
if (!src || !out) {
  console.error("usage: node scripts/export_run_history.js <dashboard.html | entry.json> <out.json>");
  process.exit(2);
}

// その日の Garmin フル予測と VO2max。「成長の記録」タブとホームの「現在地」がこれを並べて推移を描く（DATA.health.fitness の丸写し）。
// 後追い記録（entry.json）には健康データが無いので付かない。それでよい。
let fitness = {};
// その日の「今日の読みもの」（DATA.news）。ダッシュボードの「読みものの記録」と、
// 翌日以降に同じ記事を選ばないための照合（scripts/recent_news.js）に使う。1本目だけに付ける。
let news = null;

function loadToday(file) {
  const text = fs.readFileSync(file, "utf8");
  if (!/\.html?$/i.test(file)) {
    try { return JSON.parse(text); }
    catch (e) { console.error(`${file} が JSON として読めない: ${e.message}`); process.exit(1); }
  }
  // ⚠ 正規表現で <script id="coach-data"> を探してはいけない。
  //   ファイル冒頭の説明コメントの中にも同じ文字列が現れるので、そちらに当たる。
  //   「行全体がそのタグである行」だけを目印にする。
  const lines = text.split("\n");
  const from = lines.findIndex((l) => l.trim() === '<script id="coach-data">');
  const to = from < 0 ? -1 : lines.findIndex((l, i) => i > from && l.trim() === "</script>");
  if (from < 0 || to < 0) { console.error("DATA ブロックが見つかりません: " + file); process.exit(1); }
  const DATA = Function(lines.slice(from + 1, to).join("\n") + "\n; return DATA;")();
  const f = (DATA.health && DATA.health.fitness) || {};
  fitness = { pred: (f.race && f.race.full) || null, vo2: f.vo2max == null ? null : f.vo2max };
  const n = DATA.news;
  if (n && n.title && n.url) {
    // 短いキーで持つ（t=タイトル / u=URL / s=媒体 / th=テーマ / k=種類 / p=公開日）
    news = { t: n.title, u: n.url, s: n.source || "", th: n.theme || "", k: n.kind || "", p: n.published || "" };
  }
  return DATA.today || {};
}

const t = loadToday(src);
if (!t.date) { console.error("today.date がありません"); process.exit(1); }

// 1本ぶんを履歴の形に写す。seq は同じ日の何本目か（1本目は付けない＝従来どおり）。
function toDoc(run, date, dow, seq) {
  const pick = (label) => {
    const s = (run.stats || []).find((x) => x.label === label);
    return s ? s.value : null;
  };
  // ラップは "秒:心拍" のカンマ区切り1行。ペースは秒から復元できるので持たない。
  const laps = (run.laps || [])
    .map((l) => `${l.sec}:${l.hr == null ? "" : l.hr}`)
    .join(",");
  const doc = {
    d: date,
    dow: dow || "",
    type: run.type || "",
    verdict: run.verdict || "",
    verdictLabel: run.verdictLabel || "",
    km: pick("距離"),
    pace: pick("平均ペース"),
    hr: pick("平均心拍"),
    headline: run.headline || "",
    points: run.points || [],
    stats: run.stats || [],
    effect: run.effect || "",
    laps
  };
  if (seq > 1) doc.seq = seq;
  // 1本目にだけ付ける（その日の値なので2本目に重ねない）
  if (seq === 1 && fitness.pred) doc.pred = fitness.pred;
  if (seq === 1 && fitness.vo2 != null) doc.vo2 = fitness.vo2;
  if (seq === 1 && news) doc.news = news;
  return doc;
}

const outs = [];
const write = (docId, doc, file) => {
  fs.writeFileSync(file, JSON.stringify(doc));
  outs.push({ docId, file, laps: (doc.laps ? doc.laps.split(",").length : 0) });
};

write(t.date, toDoc(t, t.date, t.dow, 1), out);
(Array.isArray(t.extra) ? t.extra : []).forEach((run, i) => {
  const seq = i + 2;
  const ext = path.extname(out);
  const file = out.slice(0, out.length - ext.length) + `-${seq}` + ext;
  write(`${t.date}-${seq}`, toDoc(run, t.date, t.dow, seq), file);
});

for (const o of outs) {
  console.log(`${o.docId} -> ${o.file} (${fs.statSync(o.file).size} bytes, laps=${o.laps})`);
}
