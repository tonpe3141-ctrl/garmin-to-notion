// サブ3コーチ — iPhone ウィジェット（Scriptable 用）
//
// 直近のランと次のランを、ダッシュボードを開かずにホーム画面・ロック画面で見るためのウィジェット。
// データは Notion の「📱 ウィジェット用データ」ページにある JSON コードブロックを読む。
// その JSON は毎日 12:00 JST に Claude Routine が書き換える（docs/daily_coach_routine.md の STEP 6.8、
// 中身を作るのは scripts/export_widget_data.js）。
//
// 対応サイズ: ホーム画面 小 / 中 / 大、ロック画面 長方形 / 円形 / インライン
// セットアップ手順: widget/README.md

const PAGE_ID = "3e5862c3def7815ca6dac05c5b756c20";
const DASHBOARD_URL = "https://claude.ai/code/artifact/eedcbce5-cbe3-45f2-8181-4fffcd8b79c4";
const TOKEN_KEY = "sub3coach_notion_token";
const CACHE_FILE = "sub3coach_widget_cache.json";

// ダッシュボードと同じ配色（dashboard/index.html の :root）
const C = {
  bg:    Color.dynamic(new Color("#f2f4f3"), new Color("#161c1a")),
  ink:   Color.dynamic(new Color("#161c1a"), new Color("#eef2f0")),
  ink2:  Color.dynamic(new Color("#5a6764"), new Color("#a9b6b2")),
  ink3:  Color.dynamic(new Color("#8b9995"), new Color("#78867f")),
  line:  Color.dynamic(new Color("#d5dcd9"), new Color("#2c3532")),
  accent: Color.dynamic(new Color("#0f6e5c"), new Color("#4fb39e")),
  good:  new Color("#2f7d5f"),
  warn:  new Color("#b3762a"),
  crit:  new Color("#a83c2f"),
};
const ZONE = {
  E:    { color: new Color("#3f8f7f"), label: "E" },
  M:    { color: new Color("#c9932f"), label: "M" },
  T:    { color: new Color("#bd5533"), label: "T" },
  R:    { color: new Color("#8b3a62"), label: "R" },
  rest: { color: new Color("#8b9995"), label: "休" },
};
const VERDICT_COLOR = { "◎": C.good, "○": C.good, "〇": C.good, "△": C.warn, "✕": C.crit };

// ---------- 日付（JST 固定） ----------
const JST_MS = 9 * 3600 * 1000;
const jstNow = () => new Date(Date.now() + JST_MS);           // UTC 系メソッドで JST の値が読める
const ymd = (d) => d.toISOString().slice(0, 10);
const todayStr = () => ymd(jstNow());
const addDays = (s, n) => ymd(new Date(Date.parse(s) + n * 86400000));
const daysBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000);
const md = (s) => { const [, m, d] = s.split("-"); return `${+m}/${+d}`; };

function dayLabel(p, today) {
  if (p.date === today) return "今日";
  if (p.date === addDays(today, 1)) return "明日";
  return `${md(p.date)}(${p.dow})`;
}

// ---------- データ取得 ----------
async function getToken() {
  if (Keychain.contains(TOKEN_KEY)) return Keychain.get(TOKEN_KEY);
  if (config.runsInWidget) return null;
  return await askToken();
}

async function askToken() {
  const a = new Alert();
  a.title = "Notion トークン";
  a.message = "Notion の内部インテグレーションのシークレット（ntn_ で始まる文字列）を貼り付けてください。iPhone のキーチェーンにだけ保存されます。";
  a.addSecureTextField("ntn_...", "");
  a.addAction("保存");
  a.addCancelAction("キャンセル");
  if (await a.presentAlert() === -1) return null;
  const t = a.textFieldValue(0).trim();
  if (!t) return null;
  Keychain.set(TOKEN_KEY, t);
  return t;
}

async function fetchData(token) {
  const req = new Request(`https://api.notion.com/v1/blocks/${PAGE_ID}/children?page_size=100`);
  req.headers = { "Authorization": `Bearer ${token}`, "Notion-Version": "2022-06-28" };
  req.timeoutInterval = 15;
  const res = await req.loadJSON();
  const status = req.response && req.response.statusCode;
  if (status !== 200) {
    const hint = status === 401 ? "トークンが無効です"
      : status === 404 ? "ページにインテグレーションが接続されていません"
      : `Notion API ${status}`;
    throw new Error(hint);
  }
  const code = (res.results || []).find(b => b.type === "code");
  if (!code) throw new Error("JSON ブロックが見つかりません");
  // 長いコードブロックは rich_text が複数に分割されて返るので連結する
  const text = code.code.rich_text.map(r => r.plain_text).join("");
  return JSON.parse(text);
}

const fm = FileManager.local();
const cachePath = fm.joinPath(fm.documentsDirectory(), CACHE_FILE);
const saveCache = (d) => fm.writeString(cachePath, JSON.stringify(d));
const loadCache = () => fm.fileExists(cachePath) ? JSON.parse(fm.readString(cachePath)) : null;

async function load() {
  const token = await getToken();
  if (!token) return { data: loadCache(), error: "アプリで一度実行してトークンを設定してください" };
  try {
    const data = await fetchData(token);
    saveCache(data);
    return { data, error: null };
  } catch (e) {
    return { data: loadCache(), error: String(e.message || e) };
  }
}

// ---------- 表示用の値 ----------
function view(data) {
  const today = todayStr();
  const plan = data.plan || [];
  // Routine が止まっても、手元の週間計画から今日以降の最初の日を拾う
  const up = plan.find(p => p.date >= today) || null;
  const detail = up && data.next && data.next.date === up.date ? data.next : null;
  const race = (data.races || []).find(r => r.date >= today) || null;

  // 12:00 更新なので、昼過ぎに前日付のままなら遅れている
  const gen = String(data.generatedAt || "").slice(0, 10);
  const lag = gen ? daysBetween(gen, today) : 99;
  const stale = lag >= 2 || (lag === 1 && jstNow().getUTCHours() >= 13);

  return {
    today, last: data.last, week: data.week, stale,
    upcoming: up && {
      ...up,
      label: dayLabel(up, today),
      title: detail ? detail.title : up.title,
      pace: detail && detail.pace, hr: detail && detail.hr,
      headline: detail ? detail.headline : up.note,
    },
    later: up ? plan.filter(p => p.date > up.date) : [],
    race: race && { ...race, days: daysBetween(today, race.date) },
    updated: data.generatedAt ? `${md(gen)} ${String(data.generatedAt).slice(11, 16)}` : "—",
  };
}

// ---------- 描画ヘルパー ----------
function text(stack, s, size, opt = {}) {
  const t = stack.addText(String(s ?? "—"));
  t.font = opt.bold ? Font.boldSystemFont(size)
    : opt.semibold ? Font.semiboldSystemFont(size)
    : opt.rounded ? Font.boldRoundedSystemFont(size)
    : Font.systemFont(size);
  t.textColor = opt.color || C.ink;
  t.lineLimit = opt.lines || 1;
  if (opt.shrink) t.minimumScaleFactor = opt.shrink;
  return t;
}

function chip(stack, type, size = 10) {
  const z = ZONE[type] || ZONE.E;
  const s = stack.addStack();
  s.backgroundColor = z.color;
  s.cornerRadius = 3;
  s.setPadding(1, 5, 1, 5);
  text(s, z.label, size, { bold: true, color: Color.white() });
  return s;
}

function caption(stack, s) {
  text(stack, s, 10, { semibold: true, color: C.ink3 });
}

function kmStr(km) {
  return km === "0" || km === 0 ? "—" : `${km}km`;
}

// 横いっぱいの細い区切り線
function hairline(stack) {
  const h = stack.addStack();
  h.backgroundColor = C.line;
  h.size = new Size(0, 1);
  h.addSpacer();
}

// 次のラン。見出し → メニュー名 → ペース・心拍 → 要点の一文
function nextBlock(stack, v, o) {
  const u = v.upcoming;
  const head = stack.addStack();
  head.centerAlignContent();
  caption(head, u ? `次 · ${u.label}` : "次");
  head.addSpacer();
  if (u) chip(head, u.type);
  stack.addSpacer(4);
  if (!u) { text(stack, "予定なし", o.title, { bold: true }); return; }

  text(stack, u.title, o.title, { bold: true, lines: o.titleLines || 1, shrink: o.titleShrink || 0.75 });
  const sub = [u.type !== "rest" && !/km/.test(u.title) ? kmStr(u.km) : null, u.pace, u.hr && `HR${u.hr}`]
    .filter(Boolean).join(" · ");
  if (sub) {
    stack.addSpacer(2);
    text(stack, sub, o.sub, { semibold: true, color: C.accent, shrink: 0.75 });
  }
  if (o.headLines && u.headline) {
    stack.addSpacer(4);
    text(stack, u.headline, o.head, { color: C.ink2, lines: o.headLines });
  }
}

const verdictColor = (l) => VERDICT_COLOR[l.verdict] || C.ink3;
// 評価記号は幅を固定する（隣の種別名が長いと押しつぶされるため）
function verdictMark(row, l, size) {
  const box = row.addStack();
  box.size = new Size(Math.round(size * 1.15), 0);
  text(box, l.verdict || "—", size, { rounded: true, color: verdictColor(l) });
}
const lastStats = (l) => [l.pace && `${l.pace}/km`, l.hr && `HR${l.hr}`].filter(Boolean).join(" · ");

// 中サイズの左列。評価 → 種別 → 距離 → ペース・心拍 を縦に積む（幅が狭いので1行に詰めない）
function lastColumn(stack, v) {
  const l = v.last;
  caption(stack, l ? `直近 · ${md(l.date)}(${l.dow})` : "直近");
  stack.addSpacer(4);
  if (!l) { text(stack, "—", 16, { bold: true }); return; }

  const row = stack.addStack();
  row.centerAlignContent();
  verdictMark(row, l, 24);
  row.addSpacer(5);
  const col = row.addStack();
  col.layoutVertically();
  text(col, l.type, 14, { bold: true, shrink: 0.7 });
  text(col, l.label || "", 10, { semibold: true, color: verdictColor(l) });
  if (!l.km) return; // 休養日で履歴も無いときは距離の行を出さない
  stack.addSpacer(6);
  const km = stack.addStack();
  km.bottomAlignContent();
  text(km, l.km, 20, { rounded: true });
  km.addSpacer(2);
  text(km, "km", 11, { semibold: true, color: C.ink2 });
  stack.addSpacer(1);
  text(stack, lastStats(l), 11, { color: C.ink2, shrink: 0.75 });
}

// 大サイズの直近ラン。1段に評価・種別・距離を並べ、下にコメント
function lastRow(stack, v) {
  const l = v.last;
  caption(stack, l ? `直近 · ${md(l.date)}(${l.dow})` : "直近");
  stack.addSpacer(4);
  if (!l) { text(stack, "—", 16, { bold: true }); return; }

  const row = stack.addStack();
  row.centerAlignContent();
  verdictMark(row, l, 22);
  row.addSpacer(6);
  const col = row.addStack();
  col.layoutVertically();
  text(col, l.type, 13, { bold: true, shrink: 0.7 });
  text(col, l.label || "", 10, { semibold: true, color: verdictColor(l) });
  row.addSpacer();
  const right = row.addStack();
  right.layoutVertically();
  const km = right.addStack();
  km.addSpacer();
  text(km, l.km ? `${l.km}km` : "", 13, { bold: true });
  const st = right.addStack();
  st.addSpacer();
  text(st, lastStats(l), 10.5, { color: C.ink2 });
  if (l.note) {
    stack.addSpacer(4);
    text(stack, l.note, 11, { color: C.ink2, lines: 1, shrink: 0.85 });
  }
}

function footer(w, v, error) {
  const f = w.addStack();
  f.centerAlignContent();
  if (v.race) text(f, `${v.race.name}まで ${v.race.days}日`, 10, { semibold: true, color: C.accent });
  f.addSpacer();
  const warn = error || v.stale;
  text(f, error ? `⚠ ${error}` : `${v.stale ? "⚠ " : ""}${v.updated} 更新`, 9,
    { color: warn ? C.warn : C.ink3, shrink: 0.6 });
}

// ---------- サイズ別レイアウト ----------
function small(w, v, error) {
  // メニュー名が2行になりそうなら、そのぶん要点を1行減らす（幅約130ptに18ptの全角で7〜8字）
  const long = v.upcoming && v.upcoming.title.length > 8;
  nextBlock(w, v, { title: 18, titleLines: 2, sub: 11.5, head: 11, headLines: long ? 2 : 3 });
  w.addSpacer();
  const f = w.addStack();
  if (error || v.stale) text(f, error ? "⚠ 取得失敗" : `⚠ ${v.updated} 更新`, 9, { color: C.warn });
  else if (v.race) text(f, `${v.race.name}まで ${v.race.days}日`, 10, { semibold: true, color: C.accent });
}

function medium(w, v, error) {
  const row = w.addStack();
  row.topAlignContent();
  const left = row.addStack();
  left.layoutVertically();
  left.size = new Size(116, 0);
  lastColumn(left, v);
  row.addSpacer(14);
  const right = row.addStack();
  right.layoutVertically();
  nextBlock(right, v, { title: 18, titleLines: 1, titleShrink: 0.6, sub: 12, head: 11.5, headLines: 3 });
  w.addSpacer();
  footer(w, v, error);
}

function large(w, v, error) {
  nextBlock(w, v, { title: 20, titleLines: 1, titleShrink: 0.65, sub: 12, head: 11.5, headLines: 2 });
  w.addSpacer(10);
  hairline(w);
  w.addSpacer(10);
  lastRow(w, v);
  w.addSpacer(10);
  hairline(w);
  w.addSpacer(10);

  const h = w.addStack();
  caption(h, "この先");
  h.addSpacer();
  if (v.week) caption(h, `今週 ${v.week.km}km / 目標 ${v.week.target}`);
  w.addSpacer(3);

  for (const p of v.later.slice(0, 5)) {
    w.addSpacer(4);
    const r = w.addStack();
    r.centerAlignContent();
    const d = r.addStack();
    d.size = new Size(52, 0);
    text(d, `${md(p.date)}(${p.dow})`, 11, { color: C.ink2 });
    const c = r.addStack();
    c.size = new Size(24, 0);
    chip(c, p.type, 9);
    r.addSpacer(4);
    text(r, p.title, 12.5, { semibold: p.type !== "rest", color: p.type === "rest" ? C.ink2 : C.ink, shrink: 0.75 });
    r.addSpacer();
    text(r, kmStr(p.km), 12, { semibold: true });
  }

  w.addSpacer();
  footer(w, v, error);
}

// ロック画面は単色で描かれるので、色ではなく文字で区別する
function accessoryRect(w, v) {
  const u = v.upcoming;
  text(w, u ? `${u.label} ${u.title}` : "予定なし", 13, { bold: true, color: Color.white(), shrink: 0.55 });
  if (u) {
    const sub = [u.pace, u.hr && `HR${u.hr}`].filter(Boolean).join(" · ") || u.headline;
    text(w, sub || "", 11, { color: Color.white(), shrink: 0.7 });
  }
  const l = v.last;
  if (l) text(w, `前回 ${l.verdict} ${l.type}${l.km ? ` ${l.km}km` : ""}`, 11, { color: Color.white(), shrink: 0.7 });
}

function accessoryCircular(w, v) {
  w.addAccessoryWidgetBackground = true;
  const s = w.addStack();
  s.layoutVertically();
  s.centerAlignContent();
  const top = s.addStack(); top.addSpacer();
  text(top, v.race ? v.race.days : "—", 20, { rounded: true, color: Color.white() });
  top.addSpacer();
  const bot = s.addStack(); bot.addSpacer();
  text(bot, v.race ? v.race.name.slice(0, 2) : "", 9, { color: Color.white() });
  bot.addSpacer();
}

function accessoryInline(w, v) {
  const u = v.upcoming;
  text(w, u ? `🏃 ${u.label} ${u.title}${u.hr ? ` HR${u.hr}` : ""}` : "🏃 予定なし", 12);
}

// 次に描き直してほしい時刻: 日付が変わった直後（今日/明日の表記）か、Routine 更新後の 12:15 JST
function nextRefresh() {
  const now = jstNow();
  const base = Date.parse(ymd(now)) - JST_MS; // 今日 00:00 JST の実時刻
  const cands = [base + (12 * 60 + 15) * 60000, base + 86400000 + 5 * 60000]
    .filter(t => t > Date.now() + 5 * 60000);
  return new Date(Math.min(...cands));
}

// ---------- main ----------
async function build(family) {
  const { data, error } = await load();
  const w = new ListWidget();
  w.url = DASHBOARD_URL;
  w.refreshAfterDate = nextRefresh();

  if (!data) {
    text(w, "サブ3コーチ", 13, { bold: true });
    w.addSpacer(4);
    text(w, error || "データがありません", 11, { color: C.warn, lines: 4 });
    w.backgroundColor = C.bg;
    return w;
  }

  const v = view(data);
  if (family === "accessoryRectangular") accessoryRect(w, v);
  else if (family === "accessoryCircular") accessoryCircular(w, v);
  else if (family === "accessoryInline") accessoryInline(w, v);
  else {
    w.backgroundColor = C.bg;
    w.setPadding(14, 14, 12, 14);
    if (family === "small") small(w, v, error);
    else if (family === "large" || family === "extraLarge") large(w, v, error);
    else medium(w, v, error);
  }
  return w;
}

if (config.runsInWidget) {
  Script.setWidget(await build(config.widgetFamily));
} else {
  // アプリ内で実行したときはプレビューとトークン再設定のメニューを出す
  const m = new Alert();
  m.title = "サブ3コーチ ウィジェット";
  ["プレビュー（中）", "プレビュー（小）", "プレビュー（大）", "トークンを設定し直す"].forEach(x => m.addAction(x));
  m.addCancelAction("閉じる");
  const i = await m.presentSheet();
  if (i === 3) {
    if (Keychain.contains(TOKEN_KEY)) Keychain.remove(TOKEN_KEY);
    await askToken();
  } else if (i >= 0) {
    const fam = ["medium", "small", "large"][i];
    const w = await build(fam);
    await (fam === "small" ? w.presentSmall() : fam === "large" ? w.presentLarge() : w.presentMedium());
  }
}
Script.complete();
