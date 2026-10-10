"""損小利大・入口幅・条件付き追跡・時間帯対応を暗色の図解へまとめる。"""

from __future__ import annotations

import html
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'work' / 'wave_v10'
DEST = ROOT / 'アルゴリズム調査' / '00005_損小利大と時間帯別ルールの検証'


def read_json(path: Path, default: object = None) -> object:
    """機能: 日本語JSONを読み、ファイルがない場合は既定値を返す。

    引数: path (Path)、default (object)。返り値: JSON内容または既定値 (object)。
    """
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def clean(value: object) -> object:
    """機能: 非有限数やNumPy値をHTML埋込み可能なJSON型へ変換する。

    引数: value (object)。返り値: JSON互換値 (object)。
    """
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean(item) for item in value]
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def amount(value: object) -> str:
    """機能: 金額を万円単位の表示へ変換する。

    引数: value (object)。返り値: 金額文字列 (str)。
    """
    return '—' if value is None else f'{float(value) / 10000:+,.1f}'


def markdown_table(rows: list[dict], columns: list[str] | None = None) -> str:
    """機能: 日本語集計をMarkdown表に整形する。

    引数: rows (list[dict])、columns (list[str]|None)。返り値: Markdown (str)。
    """
    if not rows:
        return '該当する記録はありません。'
    columns = columns or list(rows[0])
    lines = ['| ' + ' | '.join(columns) + ' |', '| ' + ' | '.join('---' for _ in columns) + ' |']
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if value is None:
                formatted = '—'
            elif isinstance(value, float):
                value = 0.0 if abs(value) < 1e-12 else value
                formatted = f'{value:,.2f}'.rstrip('0').rstrip('.')
            else:
                formatted = str(value)
            values.append(formatted.replace('|', '／').replace('\n', ' '))
        lines.append('| ' + ' | '.join(values) + ' |')
    return '\n'.join(lines)


def compact_trades(rows: list[dict]) -> list[dict]:
    """機能: 注文再生明細を図解用の最小情報へ整形する。

    引数: rows (list[dict])。返り値: 図解用売買 (list[dict])。
    """
    output = []
    multipliers = {'NK225': 1000., 'TOPIX': 10000.}
    for row in rows:
        output.append(dict(method=row['方式'], session=row['セッション'], symbol=row['銘柄'],
                           side=row['side'], signal=row['signal_time_s'], sp=row['signal_price'],
                           condition=row['condition_time_s'], entry=row['entry_time_s'], ep=row['entry_price'],
                           exit=row.get('exit_time_s', row.get('mark_time_s')),
                           xp=row.get('exit_price', row.get('mark_price')), closed=row['closed'],
                           net=row['net_points'] * multipliers[row['銘柄']], atr=row['atr'],
                           mfe=row['max_favorable'] * multipliers[row['銘柄']],
                           giveback=max(0, row['max_favorable'] - row['net_points'] - (20 if row['銘柄'] == 'NK225' else 1)) * multipliers[row['銘柄']],
                           duration=row['duration_min'], reason=row.get('exit_reason', '未返済の評価値'),
                           evidence=row.get('reason', {})))
    return output


def append_live_chart(chart: dict) -> None:
    """機能: 既知区間の図と区別して、追加照合の足・指標・新規転換の売買を付ける。

    引数: chart (dict)。返り値: なし (None)。渡された表示用辞書を更新する。
    """
    record = read_json(OUT / '現在照合_取得記録.json')
    if not record or record.get('status') != '取得と検査完了':
        return
    import signals
    session = record['session']
    display_session = session + '（追加照合）'
    chart['live_session'] = display_session
    chart['live_methods'] = record['selected_ids']
    chart['live_start'] = pd.Timestamp(record['known_cutoff']).timestamp()
    chart['live_end'] = pd.Timestamp(record['cutoff']).timestamp()
    for item in record['candles']:
        if item['minutes'] != 5:
            continue
        frame = pd.read_csv(ROOT / item['path'])
        chart['candles'][f"{item['symbol']}|{display_session}"] = [
            [pd.Timestamp(row['time']).timestamp(), row['open'], row['high'], row['low'], row['close']]
            for row in frame.to_dict('records')]
    original = signals.ROOT
    signals.ROOT = OUT / 'live'
    try:
        for item in record['books']:
            price = signals.price_grid(session, item['銘柄'], pd.Timestamp(item['最後']).timestamp())
            chart.setdefault('averages', {})[f"{item['銘柄']}|{display_session}"] = [
                [row['available_time_s'], row.get('ema3'), row.get('ema8'), row.get('ema21')]
                for row in price.to_dict('records')]
    finally:
        signals.ROOT = original
    added = [dict(row, セッション=display_session) for row in read_json(OUT / '現在照合_全取引.json', [])
             if row['評価区分'] == '追加区間の新規転換']
    chart['trades'].extend(compact_trades(added))


def build_html(payload: dict, chart: dict) -> str:
    """機能: 集計と売買図を自己完結する暗色HTMLへ埋め込む。

    引数: payload/chart (dict)。返り値: 完全なHTML文書 (str)。
    """
    data = dict(payload)
    data['chart'] = chart
    data.setdefault('methods', chart.get('methods', []))
    definitions = {row['id']: row for row in read_json(OUT / '信号条件一覧.json', [])}
    for method in data['methods']:
        definition = definitions.get(method.get('family'), {})
        description = definition.get('description', method.get('signal_name', ''))
        if method.get('family') == 'S17':
            description = ('板圧力は最良気配OFI・気配の更新・同じ価格での表示数量純変化について、'
                           '60秒指標を３つ平均したもの。圧力が反対側の±0.1を２ブロック連続で満たすと反転。'
                           '自銘柄は反転後５分以内、相手銘柄は元時刻から３分以内かつ公開後60秒待機し、'
                           '両方の反転方向が一致したときだけその方向を採用します。')
        method.setdefault('label', f"{method['id']}｜{method.get('signal_name', '')}・{method.get('exit_name', '')}")
        method.setdefault('rules', [
            f"転換検知：{description}",
            f"エントリー：{method.get('entry_name', '')}。検知から{method.get('max_age_min', 10):g}分以内に成立が必要。返済後{method.get('cooldown_min', 10):g}分休止。",
            f"イグジット：{method.get('exit_name', '')}。初期損切り{method.get('initial_stop_atr', 2):g}ATR。通常追跡幅{method.get('trail_atr', 2):g}ATR。",
            f"時間帯：{method.get('time_name', '変更なし')}。",
        ])
        if method.get('entry_offset') == 0:
            method['rules'].append('初動の買いは条件設定時の売り気配以上、売りは買い気配以下を後の行で確認し、成立後の次の有効気配で約定。即座に同じ行で約定したことにはしません。')
    encoded = json.dumps(clean(data), ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c')
    return TEMPLATE.replace('__PAYLOAD__', encoded)


TEMPLATE = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>00005｜損小利大と時間帯別ルールの検証</title>
<style>
:root{color-scheme:dark;--bg:#090e18;--panel:#111b2b;--panel2:#172338;--line:#2c3e58;--text:#edf3ff;--muted:#aebed5;--green:#57e4b0;--red:#ff8c99;--blue:#7dbaff;--amber:#ffd375}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px/1.75 "Yu Gothic UI","Meiryo",sans-serif}main{max-width:1480px;margin:auto;padding:32px 26px 80px}a{color:var(--blue)}h1{font-size:32px;line-height:1.35;margin:12px 0 18px}h2{font-size:23px;line-height:1.4;margin:0 0 20px}h3{font-size:18px;margin:22px 0 12px}p{margin:10px 0}.eyebrow{color:var(--blue);letter-spacing:.12em;font-size:12px}.lede{max-width:1000px;font-size:17px;color:#d4dfef}.panel{background:var(--panel);border:1px solid var(--line);border-radius:16px;padding:25px;margin:24px 0}.notice{border-left:4px solid var(--amber);background:#292719;padding:14px 18px;color:#f6e6b4;margin:18px 0}.muted{color:var(--muted)}.small{font-size:12px}.cards{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:22px 0}.card{padding:18px;background:var(--panel2);border-radius:12px}.card strong{display:block;font-size:27px}.card span{color:var(--muted);font-size:13px}.positive{color:var(--green)}.negative{color:var(--red)}.controls{display:flex;flex-wrap:wrap;gap:14px;align-items:flex-end}.controls label{font-size:12px;color:var(--muted);display:flex;flex-direction:column;gap:5px}select,button{background:#1b2a40;border:1px solid #486184;color:var(--text);border-radius:8px;padding:9px 12px;font:inherit;max-width:100%}button{cursor:pointer}button:hover{background:#294064}select#method{max-width:670px}.scroll{overflow-x:auto;max-height:650px}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th,td{padding:11px 13px;border-bottom:1px solid var(--line);text-align:right}th{position:sticky;top:0;background:#1c2a40;color:#dbe7f8;font-weight:600;z-index:1}td:first-child,th:first-child{text-align:left}tbody tr:hover{background:#1a2b44}.wraptable{white-space:normal}.wraptable td{min-width:90px}.chartbox{position:relative;background:#0b1220;border:1px solid var(--line);border-radius:12px;overflow:hidden;margin:18px 0}canvas{display:block;width:100%;height:490px;background:#0b1220}.tooltip{position:absolute;display:none;pointer-events:none;background:#17263e;border:1px solid #708bad;border-radius:8px;padding:9px 12px;box-shadow:0 8px 20px #0008;font-size:12px;color:#edf3ff;max-width:330px}.legend{display:flex;gap:18px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend b{padding-right:4px}.method-rule{border-left:3px solid var(--blue);padding:6px 18px;background:#142139;border-radius:0 9px 9px 0}.method-rule p{margin:6px 0}.selected-trade{background:#243653!important}.badge{display:inline-block;border:1px solid #5b7498;color:#cadbf4;border-radius:5px;padding:1px 7px;font-size:11px;margin-right:5px}details{border:1px solid var(--line);border-radius:9px;padding:12px 16px;margin:12px 0}summary{cursor:pointer;color:#d5e5fa;font-weight:600}.grid2{display:grid;grid-template-columns:1fr 1fr;gap:22px}.foot{border-top:1px solid var(--line);padding-top:20px;color:var(--muted);font-size:12px}.filelinks{display:flex;gap:20px;flex-wrap:wrap}code{color:#b9d7ff}.result-list li{margin:9px 0}@media(max-width:900px){main{padding:22px 14px}.panel{padding:18px}.cards{grid-template-columns:repeat(2,1fr)}.grid2{grid-template-columns:1fr}h1{font-size:25px}canvas{height:440px}}
</style></head><body><main>
<!--
[コンポーネント概要]
#overview は時系列検証の結果と探索成績を区別して表示します。
#method/#symbol/#session は図解に使用する条件・銘柄・セッションを選びます。
#chart は確定５分足、検知、新規、返済、米国開始前後の区間を描きます。
#trade-table の行を選ぶと該当売買を図上で強調します。
#comparison は入口・出口・時間帯の対照比較を表示します。
#audit は先読み・約定順序・選択手順の検査を表示します。
-->
<div class="eyebrow">00005 · 保存板データによる機械的な売買検証</div>
<h1>波の途中で入り、損失を抑えて利益を残す</h1>
<p class="lede">入口の反発幅、損切りと追跡幅、条件を満たした後の利益保護、米国市場開始前後の扱いを比較しました。各セッションの損益と実際の売買位置を確認できます。</p>
<div class="filelinks"><a href="検証結果.md">文章の報告書</a><a href="README.md">資料の読む順序</a><a href="../index.html">調査一覧</a></div>
<section class="panel" id="overview"><h2>結果の要点</h2><div id="conclusions"></div><div class="cards" id="cards"></div><div class="notice" id="qualification"></div><div id="primary-table"></div></section>
<section class="panel"><h2>評価範囲と前提</h2><div id="scope"></div><div class="grid2"><div><h3>売買ルールの共通部分</h3><ul><li>転換イベントの公開後に条件を設定し、成立後の次の有効な気配で約定させます。</li><li>買いは売り気配、売りは買い気配で約定。返済も反対側の気配を使います。</li><li>注文条件を設定した時点のATRを固定。同じ転換イベントを繰り返し使いません。</li><li>デイ15:35・ナイト翌05:50に返済を開始し、次の気配で処理します。途中データでは人工的に返済しません。</li></ul></div><div><h3>費用と時計</h3><ul><li>ラージ各１枚。気配差に加え往復２tickを費用として控除し、４tickの場合も比較します。</li><li>米国株の通常開始は対象日の22:30 JST。固定窓22:15〜23:00で対応を切り替えます。</li><li>生板に共通の受信時刻がないため、板の行順と解放後の代理時刻を使います。</li><li>短縮後のストップ価格は不利方向に緩めません。短縮条件が消えた後の追跡幅は元の幅へ戻る場合があります。</li></ul></div></div></section>
<section class="panel" id="comparison"><h2>どの変更が役に立ったか</h2><p class="muted">各設定の比較は、他の条件をそろえた対照を優先します。探索範囲での優劣と、過去だけで選んだ次セッションの成績を混同しません。</p><div id="comparisons"></div></section>
<section class="panel"><h2>５分足でエントリーとイグジットを確認</h2><p class="muted">図解は選んだ固定条件を各セッションへ適用した追試です。上段の「過去だけで選んだ次セッション」の評価とは範囲が異なります。</p><div class="controls"><label>図解する条件<select id="method"></select></label><label>銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label>セッション<select id="session"></select></label><label>表示範囲<select id="range"><option value="all">セッション全体</option><option value="us">米国開始の前後</option><option value="added">追加照合の40分間</option></select></label><button id="reset">売買の強調を解除</button></div><div class="method-rule" id="method-rule"></div><div class="cards" id="session-cards"></div><div class="legend"><span><b style="color:#ffdc82">―</b>参考EMA3</span><span><b style="color:#8cc6ff">―</b>参考EMA8</span><span><b style="color:#b69bff">―</b>参考EMA21</span><span><b style="color:#ffd375">○</b>転換検知</span><span><b style="color:#57e4b0">▲</b>買いエントリー</span><span><b style="color:#ff8c99">▼</b>売りエントリー</span><span><b style="color:#dce8fa">×</b>返済</span><span><b style="color:#9fabc2">◇</b>未返済の評価</span><span><b style="color:#9b8bff">■</b>米国開始前後22:15〜23:00</span></div><div class="chartbox"><canvas id="chart" aria-label="確定５分足と検知・新規・返済の位置"></canvas><div class="tooltip" id="tooltip"></div></div><p class="small muted">ローソクは表示用の確定５分足です。注文は分足の高安へ当て込まず、生の気配を１行ずつ使って再生しています。表の行をクリックすると該当の売買を強調します。</p><div id="trade-table"></div><details><summary>選択条件のセッション別損益</summary><div id="method-sessions"></div></details></section>
<section class="panel"><h2>先読み防止と評価の限界</h2><div id="diagnostics"></div><div id="audit"></div></section>
<p class="foot">この資料は保存データでの検証結果です。統計的な確実性、実際の受信遅延、注文受付・取消・約定の再現精度には限界があります。過去の取引記録を見て選んだ候補の好成績だけを、将来の利益の証拠にはしていません。米国開始時刻の根拠：<a href="https://www.nyse.com/trade/hours-calendars">NYSEの取引時間</a>、<a href="https://www.nist.gov/pml/time-and-frequency-division/popular-links/daylight-saving-time-dst">NISTの夏時間</a>。</p>
</main><script id="payload" type="application/json">__PAYLOAD__</script><script>
const DATA=JSON.parse(document.getElementById('payload').textContent);const $=id=>document.getElementById(id);const PLOT={points:[],selected:-1,selectedKey:'',bounds:null};
/**
 * 機能: HTMLへ埋め込む文字列の特殊文字をエスケープする。
 * @param {unknown} value - 表示する値。
 * @returns {string} 安全なHTML文字列。
 */
function esc(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
/**
 * 機能: 円を符号付き万円に整形する。
 * @param {number|null} value - 円。
 * @returns {string} 万円表記。
 */
function yen(value){if(value==null)return '—';if(Math.abs(value)<1e-9)value=0;return `${value>0?'+':''}${(value/10000).toLocaleString('ja-JP',{minimumFractionDigits:1,maximumFractionDigits:1})}万円`;}
/**
 * 機能: Unix秒を日本時間で表示する。
 * @param {number} value - Unix秒。
 * @param {boolean} full - 日付と秒を含めるか。
 * @returns {string} 日本時間の文字列。
 */
function stamp(value,full=false){return new Date(value*1000).toLocaleString('ja-JP',{timeZone:'Asia/Tokyo',...(full?{month:'2-digit',day:'2-digit',second:'2-digit'}:{}),hour:'2-digit',minute:'2-digit'});}
/**
 * 機能: 列名に応じて表の値を整形する。
 * @param {string} key - 列名。
 * @param {unknown} value - 値。
 * @returns {string} 表示用文字列。
 */
function cell(key,value){if(value==null)return '—';if(typeof value==='number'){if(key.endsWith('円'))return yen(value);return value.toLocaleString('ja-JP',{maximumFractionDigits:3});}if(typeof value==='object')return esc(JSON.stringify(value));return esc(value);}
/**
 * 機能: 辞書配列をスクロール可能な表へ変換する。
 * @param {Array<object>} rows - 表示行。
 * @param {Array<string>|null} columns - 表示する列。
 * @returns {string} 表のHTML。
 */
function table(rows,columns=null){if(!rows?.length)return '<p class="muted">該当する記録はありません。</p>';const keys=columns||Object.keys(rows[0]);return `<div class="scroll"><table><thead><tr>${keys.map(k=>`<th>${esc(k)}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${keys.map(k=>`<td class="${typeof row[k]==='number'&&k.includes('収支')?(row[k]<0?'negative':'positive'):''}">${cell(k,row[k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
/**
 * 機能: 金額カードを作る。
 * @param {string} title - タイトル。
 * @param {string} value - 主な値。
 * @param {string} note - 補足。
 * @returns {string} カードHTML。
 */
function card(title,value,note=''){return `<div class="card"><span>${esc(title)}</span><strong>${esc(value)}</strong><span>${esc(note)}</span></div>`;}
/**
 * 機能: 結果の本文と比較表を描画する。
 * @returns {undefined} 返り値はない。
 */
function renderText(){const primary=DATA.primary||{};$('conclusions').innerHTML=`<ul class="result-list">${(DATA.conclusions||[]).map(s=>`<li>${esc(s)}</li>`).join('')}</ul>`;$('qualification').textContent=DATA.qualification||'候補数に対して独立したセッションが少なく、再現性のある法則を確認できたとはまだ判断しません。';$('scope').innerHTML=(DATA.scope||[]).map(s=>`<p>${esc(s)}</p>`).join('');$('primary-table').innerHTML=`<h3>${esc(primary.label||'時系列で選んだ条件の評価')}</h3>${table(primary.rows||[],primary.columns||null)}`;$('cards').innerHTML=(DATA.cards||[]).map(c=>card(c.title,c.value,c.note)).join('');$('comparisons').innerHTML=Object.entries(DATA.comparisons||{}).map(([name,group])=>`<h3>${esc(name)}</h3>${group.note?`<p class="muted">${esc(group.note)}</p>`:''}${table(Array.isArray(group)?group:group.rows,group.columns||null)}`).join('');$('diagnostics').innerHTML=(DATA.diagnostic_notes||[]).map(s=>`<p>${esc(s)}</p>`).join('')+Object.entries(DATA.diagnostics||{}).map(([name,rows])=>`<details><summary>${esc(name)}</summary>${table(Array.isArray(rows)?rows:[rows])}</details>`).join('');$('audit').innerHTML=(DATA.audit_notes||[]).map(s=>`<p>${esc(s)}</p>`).join('');}
/**
 * 機能: 選択中の条件と売買を取得する。
 * @returns {{method:object,trades:Array<object>,candles:Array<Array<number>>,key:string}} 表示対象。
 */
function current(){const method=DATA.methods.find(m=>m.id===$('method').value)||DATA.methods[0];const key=`${$('symbol').value}|${$('session').value}`;return {method,key,trades:(DATA.chart.trades||[]).filter(t=>t.method===method.id&&t.symbol===$('symbol').value&&t.session===$('session').value),candles:DATA.chart.candles[key]||[]};}
/**
 * 機能: 設定値を入口・出口の説明へ変換する。
 * @param {object} method - 売買条件。
 * @returns {string} 日本語の条件説明HTML。
 */
function rules(method){const config=method.config||method;const lines=method.rules||[];if(!lines.length){lines.push(`入口：${config.signal_name||config.family}。${config.entry_name||''}。`);lines.push(`出口：${config.exit_name||''}。初期損切り${config.initial_stop_atr??2}ATR、通常追跡${config.trail_atr??2}ATR。`);lines.push(`時間帯：${config.time_name||'変更なし'}。`);}return `<p><span class="badge">${esc(method.id)}</span>${esc(method.label||method.chart_label||method.signal_name||'')}</p>${lines.map(s=>`<p>${esc(s)}</p>`).join('')}`;}
/**
 * 機能: 選択条件の損益カード・売買表を再描画する。
 * @returns {undefined} 返り値はない。
 */
function renderSelection(){const before=$('method').value,added=$('session').value.includes('追加照合'),allowed=DATA.methods.filter(m=>!added||DATA.chart.live_methods.includes(m.id));$('method').innerHTML=allowed.map(m=>`<option value="${esc(m.id)}">${esc(m.label||m.chart_label||m.id)}</option>`).join('');$('method').value=allowed.some(m=>m.id===before)?before:(allowed.some(m=>m.id===DATA.default_method)?DATA.default_method:allowed[0].id);const {method,trades}=current();$('method-rule').innerHTML=rules(method);if($('session').value.includes('追加照合')){$('method-rule').innerHTML+='<p class="muted">追加照合は23:22以降に新たに検知した転換だけを表示しています。17:00から状態を引き継いで再生し、既知区間由来の建玉はこの集計に加えていません。</p>';if(!DATA.chart.live_methods.includes(method.id)){$('session-cards').innerHTML=card('追加照合','対象外','この方式は取得前に固定した６条件に含まれません');$('trade-table').innerHTML='<p>追加データではこの条件を検証していません。</p>';$('method-sessions').innerHTML='';draw();return;}}const closed=trades.filter(t=>t.closed),opened=trades.filter(t=>!t.closed),profit=closed.reduce((s,t)=>s+Math.max(0,t.net),0),loss=-closed.reduce((s,t)=>s+Math.min(0,t.net),0);$('session-cards').innerHTML=card('確定収支',yen(profit-loss),`利益 ${yen(profit)} ／ 損失 ${yen(loss)}`)+card('勝ち／返済済',`${closed.filter(t=>t.net>0).length}／${closed.length}`,`未返済 ${opened.length}件`)+card('未返済の評価損益',yen(opened.reduce((s,t)=>s+t.net,0)),'確定収支には含めない')+card('最大順行からの返却',yen(closed.reduce((s,t)=>s+t.giveback,0)),'費用控除前・各返済済取引の合計');const rows=trades.map((t,i)=>`<tr data-trade="${i}" class="${PLOT.selected===i?'selected-trade':''}"><td>${i+1}</td><td>${t.side>0?'ロング':'ショート'}</td><td>${stamp(t.signal,true)}</td><td>${stamp(t.entry,true)}</td><td>${t.ep.toLocaleString()}</td><td>${stamp(t.exit,true)}</td><td>${t.xp.toLocaleString()}</td><td class="${t.net<0?'negative':'positive'}">${yen(t.net)}</td><td>${yen(t.mfe)}</td><td>${yen(t.giveback)}</td><td>${t.atr.toFixed(2)}</td><td>${esc(t.reason)}</td></tr>`);$('trade-table').innerHTML=rows.length?`<div class="scroll"><table><thead><tr>${['番号','方向','検知','新規','新規価格','返済／評価','返済／評価価格','確定／評価損益','最大順行','利益返却','固定ATR','返済理由'].map(k=>`<th>${k}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`:'<p class="muted">この条件では当該セッションに約定がありません。信号があっても、期限・反発幅・保有中などの条件で約定しない場合があります。</p>';document.querySelectorAll('[data-trade]').forEach(row=>row.addEventListener('click',()=>{PLOT.selected=Number(row.dataset.trade);renderSelection();}));$('method-sessions').innerHTML=table((DATA.session_rows||[]).filter(r=>r.方式===method.id),DATA.session_columns||null);draw();}
/**
 * 機能: 暗色キャンバスへ確定５分足、米国開始窓、実約定位置を描く。
 * @returns {undefined} 返り値はない。
 */
function draw(){const {trades,candles}=current();const canvas=$('chart'),dpr=window.devicePixelRatio||1,w=canvas.clientWidth,h=canvas.clientHeight;canvas.width=w*dpr;canvas.height=h*dpr;const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);ctx.fillStyle='#0b1220';ctx.fillRect(0,0,w,h);PLOT.points=[];if(!candles.length){ctx.fillStyle='#b8c9df';ctx.fillText('表示用の確定５分足がありません',24,40);return;}let t0=candles[0][0]-150,t1=candles.at(-1)[0]+450;const session=$('session').value,night=session.includes('_Night'),midnight=Date.parse(session.slice(0,10)+'T00:00:00+09:00')/1000,us0=midnight+22*3600+15*60,us1=midnight+23*3600;if($('range').value==='us'&&night){t0=Math.max(t0,us0-45*60);t1=Math.min(t1,us1+60*60);}if($('range').value==='added'&&session.includes('追加照合')){t0=DATA.chart.live_start;t1=Math.max(t0+60,DATA.chart.live_end);}const visible=candles.filter(c=>c[0]+300>=t0&&c[0]<=t1);let low=Math.min(...visible.map(c=>c[3])),high=Math.max(...visible.map(c=>c[2]));for(const t of trades){if(t.entry>=t0&&t.entry<=t1){low=Math.min(low,t.ep);high=Math.max(high,t.ep);}if(t.exit>=t0&&t.exit<=t1){low=Math.min(low,t.xp);high=Math.max(high,t.xp);}}const pad=Math.max((high-low)*.10,$('symbol').value==='NK225'?30:1);low-=pad;high+=pad;const L=14,R=78,T=26,B=43,W=w-L-R,H=h-T-B,x=t=>L+(t-t0)/(t1-t0)*W,y=p=>T+(high-p)/(high-low)*H;PLOT.bounds={t0,t1,low,high};if(night&&us1>=t0&&us0<=t1){ctx.fillStyle='#9683ff1f';ctx.fillRect(x(Math.max(t0,us0)),T,x(Math.min(t1,us1))-x(Math.max(t0,us0)),H);ctx.fillStyle='#b6a7ff';ctx.font='11px sans-serif';ctx.fillText('米国開始前後',Math.max(L+4,x(us0)+5),T+15);}ctx.font='11px sans-serif';for(let i=0;i<=5;i++){const price=low+(high-low)*i/5,py=y(price);ctx.strokeStyle='#23324a';ctx.beginPath();ctx.moveTo(L,py);ctx.lineTo(w-R,py);ctx.stroke();ctx.fillStyle='#afc0d8';ctx.fillText(price.toLocaleString('ja-JP',{maximumFractionDigits:$('symbol').value==='NK225'?0:1}),w-R+9,py+4);}for(let i=0;i<=6;i++){const t=t0+(t1-t0)*i/6,px=x(t);ctx.fillStyle='#99aecb';ctx.fillText(stamp(t),Math.max(4,Math.min(w-52,px-17)),h-17);}const bw=Math.max(2,Math.min(12,W/(t1-t0)*300*.65));for(const c of visible){const px=x(c[0]+150);ctx.strokeStyle=ctx.fillStyle=c[4]>=c[1]?'#57e4b0':'#ff8c99';ctx.beginPath();ctx.moveTo(px,y(c[2]));ctx.lineTo(px,y(c[3]));ctx.stroke();ctx.fillRect(px-bw/2,Math.min(y(c[1]),y(c[4])),bw,Math.max(1.5,Math.abs(y(c[1])-y(c[4]))));PLOT.points.push({x:px,y:y(c[4]),label:`５分足 ${stamp(c[0],true)}<br>始値 ${c[1]} ／ 高値 ${c[2]}<br>安値 ${c[3]} ／ 終値 ${c[4]}`}); }ctx.save();ctx.beginPath();ctx.rect(L,T,W,H);ctx.clip();const averages=DATA.chart.averages[`${$('symbol').value}|${session}`]||[];for(let col=1;col<=3;col++){ctx.strokeStyle=['','#ffdc82','#8cc6ff','#b69bff'][col];ctx.lineWidth=1.1;ctx.globalAlpha=.75;ctx.beginPath();let started=false;for(const row of averages){if(row[0]<t0||row[0]>t1||!Number.isFinite(row[col]))continue;if(!started){ctx.moveTo(x(row[0]),y(row[col]));started=true;}else ctx.lineTo(x(row[0]),y(row[col]));}ctx.stroke();}ctx.globalAlpha=1;if(session.includes('追加照合')&&DATA.chart.live_start>=t0&&DATA.chart.live_start<=t1){ctx.strokeStyle='#ffd375';ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(x(DATA.chart.live_start),T);ctx.lineTo(x(DATA.chart.live_start),h-B);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#ffd375';ctx.fillText('追加照合23:22〜',Math.min(w-R-110,x(DATA.chart.live_start)+5),T+30);}trades.forEach((tr,i)=>{const active=PLOT.selected===i,color=tr.side>0?'#57e4b0':'#ff8c99';ctx.lineWidth=active?2.5:1.3;ctx.globalAlpha=PLOT.selected>=0&&!active?.35:1;ctx.strokeStyle=color;ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(x(tr.entry),y(tr.ep));ctx.lineTo(x(tr.exit),y(tr.xp));ctx.stroke();ctx.setLineDash([]);if(tr.signal>=t0&&tr.signal<=t1){ctx.strokeStyle='#ffd375';ctx.beginPath();ctx.arc(x(tr.signal),y(tr.sp),active?6:4,0,2*Math.PI);ctx.stroke();PLOT.points.push({x:x(tr.signal),y:y(tr.sp),label:`#${i+1} 転換検知 ${stamp(tr.signal,true)}<br>条件設定 ${stamp(tr.condition,true)}`});}if(tr.entry>=t0&&tr.entry<=t1){const px=x(tr.entry),py=y(tr.ep),s=active?9:7;ctx.fillStyle=color;ctx.beginPath();ctx.moveTo(px,py);ctx.lineTo(px-s,py+tr.side*s*1.7);ctx.lineTo(px+s,py+tr.side*s*1.7);ctx.closePath();ctx.fill();ctx.fillStyle='#edf3ff';ctx.font=active?'bold 13px sans-serif':'11px sans-serif';ctx.fillText(String(i+1),px+9,py+tr.side*13);PLOT.points.push({x:px,y:py,label:`#${i+1} ${tr.side>0?'買い':'売り'} ${stamp(tr.entry,true)}<br>価格 ${tr.ep} ／ ATR ${tr.atr.toFixed(2)}`});}if(tr.exit>=t0&&tr.exit<=t1){const px=x(tr.exit),py=y(tr.xp),s=active?7:5;ctx.strokeStyle=tr.closed?'#f2f6ff':'#a9b8d0';ctx.beginPath();if(tr.closed){ctx.moveTo(px-s,py-s);ctx.lineTo(px+s,py+s);ctx.moveTo(px-s,py+s);ctx.lineTo(px+s,py-s);}else{ctx.moveTo(px,py-s);ctx.lineTo(px+s,py);ctx.lineTo(px,py+s);ctx.lineTo(px-s,py);ctx.closePath();}ctx.stroke();PLOT.points.push({x:px,y:py,label:`#${i+1} ${tr.closed?'返済':'未返済の評価'} ${stamp(tr.exit,true)}<br>価格 ${tr.xp} ／ ${yen(tr.net)}<br>${esc(tr.reason)}`});}ctx.globalAlpha=1;});ctx.restore();}
/**
 * 機能: マウスに近いローソクまたは売買の説明を表示する。
 * @param {MouseEvent} event - マウス位置。
 * @returns {undefined} 返り値はない。
 */
function tooltip(event){const rect=$('chart').getBoundingClientRect(),x=event.clientX-rect.left,y=event.clientY-rect.top;let nearest=null,distance=24;for(const point of PLOT.points){const d=Math.hypot(x-point.x,y-point.y);if(d<distance){nearest=point;distance=d;}}const tip=$('tooltip');if(!nearest){tip.style.display='none';return;}tip.innerHTML=nearest.label;tip.style.display='block';tip.style.left=Math.min(rect.width-340,Math.max(4,x+15))+'px';tip.style.top=Math.max(5,y-65)+'px';}
/**
 * 機能: 選択肢と操作イベントを初期化する。
 * @returns {undefined} 返り値はない。
 */
function initialize(){renderText();DATA.methods=DATA.methods||[];if(!DATA.methods.length)return;$('method').innerHTML=DATA.methods.map(m=>`<option value="${esc(m.id)}">${esc(m.label||m.chart_label||m.id)}</option>`).join('');const sessions=[...new Set(Object.keys(DATA.chart.candles||{}).map(k=>k.split('|')[1]))].sort();$('session').innerHTML=sessions.map(s=>`<option value="${esc(s)}">${esc(s.replace('_Day',' デイ').replace('_Night',' ナイト'))}</option>`).join('');if(DATA.default_method)$('method').value=DATA.default_method;if(DATA.default_session)$('session').value=DATA.default_session;for(const name of ['method','symbol','session','range'])$(name).addEventListener('change',()=>{PLOT.selected=-1;renderSelection();});$('reset').addEventListener('click',()=>{PLOT.selected=-1;renderSelection();});$('chart').addEventListener('mousemove',tooltip);$('chart').addEventListener('mouseleave',()=>{$('tooltip').style.display='none';});window.addEventListener('resize',draw);renderSelection();}
initialize();
</script></body></html>'''


def main() -> None:
    """機能: 親の固定集計と図解資料からHTML・報告書・読む順序を生成する。

    引数: なし。返り値: なし (None)。新作業00005内だけへ成果物を保存する。
    """
    payload = read_json(OUT / '報告入力.json')
    chart = read_json(OUT / '図解資料.json')
    if payload is None or chart is None:
        raise FileNotFoundError('報告入力.jsonと図解資料.jsonの確定出力を先に作成してください。')
    if chart.get('trades') and 'method' not in chart['trades'][0]:
        chart['trades'] = compact_trades(chart['trades'])
    append_live_chart(chart)
    if 'session_rows' not in payload:
        candidates = {row['id'] for row in chart.get('methods', [])}
        summary_path = OUT / '全条件セッション集計.csv'
        if summary_path.exists():
            frame = pd.read_csv(summary_path)
            columns = ['方式', 'セッション', '銘柄', '取引数', '勝ち数', '利益円', '損失円', '収支円',
                       '費用倍収支円', '平均利益円', '平均損失円', '最大順行からの返却円', '未返済数', '評価損益円']
            payload['session_rows'] = frame.loc[frame.方式.isin(candidates), columns].to_dict('records')
            payload['session_columns'] = columns[1:]
            fresh = pd.read_csv(OUT / '現在照合_セッション集計.csv')
            fresh['セッション'] += '（追加照合）'
            payload['session_rows'].extend(fresh.reindex(columns=columns).to_dict('records'))
    DEST.mkdir(parents=True, exist_ok=True)
    (DEST / '損小利大と時間帯の検証.html').write_text(build_html(payload, chart), encoding='utf-8')
    parts = ['# 損小利大と時間帯別ルールの検証',
             '[図解HTMLを開く](損小利大と時間帯の検証.html)',
             '\n'.join(payload.get('conclusions', [])), payload.get('qualification', ''),
             '## 評価の範囲', '\n\n'.join(payload.get('scope', []))]
    primary = payload.get('primary', {})
    parts += ['## ' + primary.get('label', '時系列で選んだ条件の評価'),
              markdown_table(primary.get('rows', []), primary.get('columns'))]
    chosen = next((method for method in chart['methods'] if method['id'] == payload.get('default_method')), None)
    if chosen:
        parts += ['## 最終主候補の機械的な条件', chosen['id'], '\n\n'.join(chosen.get('rules', []))]
    for name, group in payload.get('comparisons', {}).items():
        parts += ['## ' + name, group.get('note', '') if isinstance(group, dict) else '',
                  markdown_table(group if isinstance(group, list) else group.get('rows', []),
                                 group.get('columns') if isinstance(group, dict) else None)]
    parts += ['## 先読み防止と限界', '\n\n'.join(payload.get('diagnostic_notes', [])),
              '\n\n'.join(payload.get('audit_notes', [])),
              '## セッション別の明細', 'HTMLで方式を選択すると、利益・損失・差引と売買の位置を確認できます。資料フォルダに再集計用の明細も保存しています。']
    (DEST / '検証結果.md').write_text('\n\n'.join(parts) + '\n', encoding='utf-8')
    (DEST / 'README.md').write_text(
        '# 00005 損小利大と時間帯別ルールの検証\n\n'
        '**最初に見るファイル：[損小利大と時間帯の検証.html](損小利大と時間帯の検証.html)**\n\n'
        'HTMLはダークテーマです。インターネット接続なしで、５分足と検知・新規・返済を確認できます。\n\n'
        '読む順序：\n\n1. HTML冒頭の結果と評価範囲。\n2. 入口・出口・米国開始前後の対照比較。\n'
        '3. 条件・銘柄・セッションを選び、５分足と売買明細を確認。\n'
        '4. [検証結果.md](検証結果.md)で文章と集計を確認。\n'
        '5. [資料](資料/)の条件一覧、全条件集計、監査記録を確認。\n\n'
        '過去の00004は変更していません。今回の比較には前回の固定条件も含みます。\n\n'
        '再計算はプロジェクトルートで `python work/wave_v10/research.py` を実行します。'
        '現在照合の保存データだけを再計算する場合は `python work/wave_v10/live_check.py --evaluate` です。'
        '一回取得済みなので、新しい取得は実行しません。'
        '資料内のPythonファイルは参照用で、その場所から直接実行する構成ではありません。\n', encoding='utf-8')
    assets = DEST / '資料'
    assets.mkdir(exist_ok=True)
    for path in OUT.iterdir():
        if path.is_file() and path.suffix in ('.json', '.csv', '.md', '.py', '.npz') and path.name not in ('図解資料.json', '報告入力.json') and 'fixture' not in path.name:
            shutil.copy2(path, assets / path.name)
    (assets / 'README.md').write_text(
        '# 再集計資料\n\n条件一覧・全条件集計・選択記録・全売買数値とその形式・独立監査を保存しています。\n\n'
        'Pythonファイルは参照用です。実行する場合は元プロジェクトルートの `work/wave_v10` を使用してください。'
        '価格原本、過去版の監査済み特徴、確定足は元の保存場所を参照します。\n\n'
        '保存データの再計算：`python work/wave_v10/research.py`\n\n'
        '取得済み現在照合の再計算：`python work/wave_v10/live_check.py --evaluate`\n\n'
        '報告生成：`python work/wave_v10/prepare_report.py` の後に `python work/wave_v10/report.py`\n', encoding='utf-8')
    hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in assets.iterdir()
              if path.is_file() and path.name != '資料SHA256.json'}
    (assets / '資料SHA256.json').write_text(json.dumps(hashes, ensure_ascii=False, indent=2), encoding='utf-8')
    print(str(DEST / '損小利大と時間帯の検証.html'))


if __name__ == '__main__':
    main()
