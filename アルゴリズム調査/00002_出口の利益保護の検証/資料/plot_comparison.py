"""出口比較の検証済み取引を、保存五分足に重ねた通信不要の図解へ変換する。"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from html.parser import HTMLParser
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "アルゴリズム調査"
SAVED = BASE / "保存版"
OUTPUT = BASE / "出口改善"
SOURCE = Path(__file__).with_name("図解対象.json")
SESSIONS = ["2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night", "2026-09-23_Day"]


def epoch(value: str) -> int:
    """機能: 時差付き日時を描画用の経過ミリ秒へ変換する。

    引数: value (str) は日時。返り値: 経過ミリ秒 (int)。
    """
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def load_bars(folder: str, symbol: str, session: str) -> list[dict]:
    """機能: 保存版の確定ローソクだけを読み込む。

    引数: folder/symbol/session (str) は種類・銘柄・セッション。返り値: ローソクの配列 (list[dict])。
    """
    path = SAVED / folder / symbol / f"{session}.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [
            {"t": epoch(row["time"]), **{key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}}
            for row in csv.DictReader(handle) if row["closed"].lower() == "true"
        ]


def trade_for_chart(trade: dict, method: str, number: int, minute_bars: dict) -> dict:
    """機能: 検証済みの取引へ描画座標と一分終値の保有中経路を補う。

    引数: trade (dict) は取引、method (str) は方式、number (int) は番号、minute_bars (dict) は保存一分足。
    返り値: 描画用取引 (dict)。最大含み益・返却幅は検証エンジンの値を使用する。
    """
    value = dict(trade, id=f"{method}-{number}", number=number, method=method)
    entry, end = epoch(trade["entry_time"]), epoch(trade["exit_time"])
    value.update(entry_time_ms=entry, exit_time_ms=end)
    multiplier = 1000 if trade["symbol"] == "NK225" else 10000
    value["net_yen"] = trade["net_points"] * multiplier
    value["gross_yen"] = trade.get("gross_points", (trade["exit_price"] - trade["entry_price"]) * trade["side"]) * multiplier
    value["fee_yen"] = value["gross_yen"] - value["net_yen"]
    for key in ("mfe_close_points", "giveback_points"):
        if key not in trade:
            raise ValueError(f"{method}/{number}: エンジン算出の {key} がありません")
    value["mfe_yen"] = trade["mfe_close_points"] * multiplier
    value["giveback_yen"] = trade["giveback_points"] * multiplier
    bars = minute_bars[f"{trade['symbol']}/{trade['session']}"]
    path = [{"t": entry, "price": trade["entry_price"], "points": 0.0}]
    path.extend({"t": row["t"] + 60000, "price": row["close"], "points": (row["close"] - trade["entry_price"]) * trade["side"]} for row in bars if entry <= row["t"] < end)
    path.append({"t": end, "price": trade["exit_price"], "points": value["gross_yen"] / multiplier})
    value["holding_path"] = path
    value["peak"] = max(path, key=lambda point: point["points"])
    if abs(value["peak"]["points"] - trade["mfe_close_points"]) > 1e-6:
        raise ValueError(f"{method}/{number}: 保存終値の最大含み益とエンジン値が一致しません")
    value["protection"] = [{"t": epoch(row["time"]), "price": row["stop"]} for row in trade.get("protection_history", []) if row.get("stop") is not None]
    return value


def load_payload(source_path: Path) -> dict:
    """機能: 親の比較結果と保存版のローソクを一つの図解データへまとめる。

    引数: source_path (Path) は親の比較結果JSON。返り値: 埋め込みデータ (dict)。
    """
    source = json.loads(source_path.read_text(encoding="utf-8"))
    candles = {f"{symbol}/{session}": load_bars("candle_5min", symbol, session) for symbol in ("NK225", "TOPIX") for session in SESSIONS}
    minutes = {f"{symbol}/{session}": load_bars("candle_1min", symbol, session) for symbol in ("NK225", "TOPIX") for session in SESSIONS}
    methods = {}
    for method in ("baseline", "fixed_entries", "selected"):
        methods[method] = dict(source[method])
        methods[method]["trades"] = [trade_for_chart(t, method, i, minutes) for i, t in enumerate(source[method]["trades"], 1)]
    return {"sessions": SESSIONS, "candles": candles, "methods": methods, "selection": source.get("selection", {})}


# ----------------------------------------
# 前回の色・余白・書体を継承し、データと操作を一つのHTMLへ閉じ込める。

TEMPLATE = r'''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>出口の比較｜NK225・TOPIX</title><link rel="icon" href="data:,"><style>__STYLE__
.comparison{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:18px}.comparison .metric{background:#f4f7fb;border-radius:10px;padding:12px 15px}.comparison b{font-size:22px}.base-color{color:#748293}.new-color{color:#006dbc}.subchart{display:block;width:100%;height:auto;margin-top:10px}.chart{min-height:0}.mode-note{font-size:12px;color:var(--muted);margin:12px 0}.check-label{display:flex;align-items:center;gap:5px;font-size:12px}.rule{background:#edf5ff;border-left:3px solid #458cc5;padding:12px 16px;margin-top:16px}.after{color:#ac7420}.selected-detail{grid-template-columns:repeat(4,1fr)}.legend{font-size:12px}.summary-table td:nth-child(n+3){text-align:right}.chart-wrap{overflow:visible}.toggle-notes{font-size:12px;color:var(--muted)}@media(max-width:850px){.comparison,.selected-detail{grid-template-columns:1fr 1fr}.chart-head{gap:6px}}@media(max-width:480px){.comparison b{font-size:18px}}
</style></head><body><main>
<div class="eyebrow">保存済み5セッション ／ 同じ入口で出口を比較</div><h1>伸ばした利益を、どこまで残せたか</h1>
<p class="lead">元の「4ATR幅で追跡する出口」と、利益が乗った後に保護を強める候補を重ねました。まず<strong>入口を全く同じに固定</strong>して出口だけの差を確認し、次に再エントリーを含めた運用へ切り替えられます。ローソクは5分足、新規・返済は仮想約定が成立した1分足の開始時刻に表示します。</p>
<!--
[コンポーネント概要]
#mode-select は、元の入口を固定した比較と、早期返済後の再新規を含む運用を切り替えます。
#symbol-select / #session-select は対象の銘柄・セッションを選択します。
#price-chart は確定五分足と両方式の新規・返済を実時刻軸で描きます。
#show-protection は現在足で実際に有効な保護価格を表示します。将来の更新価格は遡って描きません。
#trade-detail は選んだ取引の収支・最大含み益・返却額を表示します。
#profit-chart は選んだ取引と同じ入口の比較取引の一分終値損益を表示します。
#session-table は全セッションの利益・損失・収支と利益返却額を比較します。
#all-trades は比較中の全セッションの取引一覧です。表示ボタンで対象チャートへ移動します。
-->
<section class="card"><div class="toolbar"><div class="control"><label for="mode-select">比較方法</label><select id="mode-select"><option value="fixed_entries">同じ入口で出口比較</option><option value="selected">再エントリーを含む運用</option></select></div><div class="control"><label for="symbol-select">銘柄</label><select id="symbol-select"><option>NK225</option><option>TOPIX</option></select></div><div class="control"><label for="session-select">セッション</label><select id="session-select"></select></div><div class="actions"><button id="zoom-in">＋ 拡大</button><button id="zoom-out">− 縮小</button><button id="view-all">全体</button><button id="view-trade">保有＋返済後</button></div></div>
<div class="note" id="selection-note"></div><div class="rule"><strong id="rule-name"></strong><div id="rule-description"></div></div><p id="mode-note" class="mode-note"></p>
<div id="comparison-metrics" class="comparison" aria-live="polite"></div>
<div class="chart-head"><h2 id="chart-title"></h2><div class="legend"><span><i style="background:#748293"></i>元の出口</span><span><i style="background:#006dbc"></i>利益保護候補</span><span>▲買い新規 / ▼売り新規 / ◆返済</span><span style="color:#ac7420">○ 最大含み益の終値</span></div></div>
<div class="toolbar toggle-notes"><label class="check-label"><input id="show-protection" type="checkbox">有効な保護価格を表示</label><span>点線は保有区間。返済後もローソクを残すので、切り過ぎ・再上昇も確認できます。</span></div>
<div id="chart-wrap" class="chart-wrap"><svg id="price-chart" class="chart" viewBox="0 0 1240 490" role="img" aria-labelledby="chart-title"></svg><div id="chart-tooltip" class="tooltip hidden"></div></div>
<p class="hint">横軸は日本時間。ドラッグで移動、ボタンで拡大縮小。マーカーと一覧行を押すと取引を選択できます。新規・返済のラベルは5分単位に丸めていません。</p>
<div id="trade-detail" class="selected-detail" aria-live="polite"></div><svg id="profit-chart" class="subchart" viewBox="0 0 1240 210" role="img" aria-label="選択取引の一分終値損益と返済時点"></svg><p id="profit-note" class="hint"></p>
<div class="note">最大含み益は新規足以降の<strong>確定1分終値</strong>と実返済価格から測定します。利益返却額＝最大含み益−実現値幅（最低0）で、費用控除前の値動き同士を比較します。ここでいう返却額は最高評価からの低下です。最終的に赤字になった取引や、一度も含み益が出なかった損切りでは、損失分も含みます。最高値・最安値で返済できたと仮定した額ではありません。各方式の最大含み益は、その方式の保有中だけを対象とします。</div></section>
<section class="card"><h2>全セッションの比較</h2><p class="table-caption">単位：万円。ラージ各1枚。利益と損失は往復2ティックの仮定費用を各取引から控除して集計。利益返却は各取引の返却額の合計で、収支や最大ドローダウンとは別の指標です。</p><div class="table-scroll"><table class="summary-table"><thead><tr><th>銘柄</th><th>セッション</th><th>元の利益</th><th>元の損失</th><th>元の収支</th><th>新しい利益</th><th>新しい損失</th><th>新しい収支</th><th>収支差</th><th>元の利益返却</th><th>新しい利益返却</th></tr></thead><tbody id="session-table"></tbody></table></div></section>
<section class="card"><h2 id="trade-list-title">比較中の全取引</h2><p class="table-caption">表示ボタンで対象のセッションと取引を選択します。灰色が元の4ATR出口、青色が利益保護候補です。ナイトの日付は開始日です。</p><div class="table-scroll"><table><thead><tr><th>表示</th><th>方式</th><th>銘柄</th><th>セッション</th><th>方向</th><th>新規時刻</th><th>価格</th><th>返済時刻</th><th>価格</th><th>収支（万円）</th><th>最大含み益</th><th>利益返却</th><th>返済理由</th></tr></thead><tbody id="all-trades"></tbody></table></div></section>
<p class="footer">保存データだけによる探索結果であり、将来の利益を確認したものではありません。保護価格は一分足が確定した後に更新し、次の実在足から有効になる想定です。HTML内に全データを埋め込み、外部通信は行いません。</p></main>
<script id="research-data" type="application/json">__PAYLOAD__</script><script>
"use strict";
const DATA=JSON.parse(document.getElementById("research-data").textContent),NS="http://www.w3.org/2000/svg",MINUTE=60000,BOX={left:82,right:1198,top:50,bottom:428};
const el={symbol:document.getElementById("symbol-select"),session:document.getElementById("session-select"),mode:document.getElementById("mode-select"),svg:document.getElementById("price-chart"),tooltip:document.getElementById("chart-tooltip"),wrap:document.getElementById("chart-wrap"),detail:document.getElementById("trade-detail"),title:document.getElementById("chart-title"),table:document.getElementById("all-trades"),protection:document.getElementById("show-protection"),profit:document.getElementById("profit-chart")};
const clock=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",hour:"2-digit",minute:"2-digit",hourCycle:"h23"}),calendar=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",month:"2-digit",day:"2-digit"});
const state={symbol:"NK225",session:"2026-09-23_Day",mode:"fixed_entries",selected:null,start:0,end:1,fullStart:0,fullEnd:1,ymin:0,ymax:1,drag:null};
/**
 * 機能: 数値を日本語の桁区切りで整形する。
 * 引数: value {number} 数値、digits {number} 最大小数桁。
 * 返り値: {string} 整形した数値。
 */
function number(value,digits=1){return Number(value).toLocaleString("ja-JP",{maximumFractionDigits:digits});}
/**
 * 機能: 金額を符号付き万円へ変換する。
 * 引数: value {number} 円。
 * 返り値: {string} 符号付き万円。
 */
function money(value){return (value>0?"+":"")+number(value/10000,2);}
/**
 * 機能: セッション識別子を日本語へ変換する。
 * 引数: value {string} セッション識別子。
 * 返り値: {string} 日本語表示。
 */
function sessionLabel(value){return value.slice(5,10).replace("-","/")+" "+(value.endsWith("Day")?"デイ":"ナイト");}
/**
 * 機能: SVG要素を作成して追加する。
 * 引数: tag {string} 要素名、attrs {object} 属性、text {string|null} 文字、parent {Element} 追加先。
 * 返り値: {SVGElement} 作成要素。
 */
function svg(tag,attrs={},text=null,parent=el.svg){const node=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text!==null)node.textContent=text;parent.appendChild(node);return node;}
/**
 * 機能: 比較中の方式の全取引を得る。
 * 引数: なし。
 * 返り値: {Array<object>} 取引一覧。
 */
function allTrades(){return DATA.methods.baseline.trades.concat(DATA.methods[state.mode].trades);}
/**
 * 機能: 表示対象の取引を絞り込む。
 * 引数: なし。
 * 返り値: {Array<object>} 取引一覧。
 */
function currentTrades(){return allTrades().filter(t=>t.symbol===state.symbol&&t.session===state.session);}
/**
 * 機能: 方式の表示色を得る。
 * 引数: trade {object} 取引。
 * 返り値: {string} 色。
 */
function tradeColor(trade){return trade.method==="baseline"?"#748293":"#006dbc";}
/**
 * 機能: 日時を横座標へ変換する。
 * 引数: time {number} 経過ミリ秒。
 * 返り値: {number} 横座標。
 */
function x(time){return BOX.left+(time-state.start)/(state.end-state.start)*(BOX.right-BOX.left);}
/**
 * 機能: 価格を縦座標へ変換する。
 * 引数: price {number} 価格。
 * 返り値: {number} 縦座標。
 */
function y(price){return BOX.bottom-(price-state.ymin)/(state.ymax-state.ymin)*(BOX.bottom-BOX.top);}
/**
 * 機能: 対象セッション全体へ表示範囲を設定する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function setFullRange(){const bars=DATA.candles[state.symbol+"/"+state.session];state.fullStart=bars[0].t-8*MINUTE;state.fullEnd=Math.max(bars.at(-1).t+5*MINUTE,...currentTrades().map(t=>t.exit_time_ms))+8*MINUTE;state.start=state.fullStart;state.end=state.fullEnd;}
/**
 * 機能: 取引群の利益・損失・収支・利益返却を集計する。
 * 引数: trades {Array<object>} 取引群。
 * 返り値: {object} 円単位の集計。
 */
function aggregate(trades){return trades.reduce((a,t)=>({profit:a.profit+Math.max(0,t.net_yen),loss:a.loss+Math.max(0,-t.net_yen),net:a.net+t.net_yen,giveback:a.giveback+t.giveback_yen,count:a.count+1}),{profit:0,loss:0,net:0,giveback:0,count:0});}
/**
 * 機能: 全体比較の四つの主要数値を更新する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderMetrics(){const trades=currentTrades(),old=aggregate(trades.filter(t=>t.method==="baseline")),next=aggregate(trades.filter(t=>t.method!=="baseline"));document.getElementById("comparison-metrics").innerHTML=`<div class="metric"><small>元の出口・${old.count}取引</small><b class="base-color">${money(old.net)} 万円</b><span>利益 ${number(old.profit/10000,2)} ／ 損失 ${number(old.loss/10000,2)}</span></div><div class="metric"><small>利益保護候補・${next.count}取引</small><b class="new-color">${money(next.net)} 万円</b><span>利益 ${number(next.profit/10000,2)} ／ 損失 ${number(next.loss/10000,2)}</span></div><div class="metric"><small>収支の差</small><b class="${next.net>=old.net?"positive":"negative"}">${money(next.net-old.net)} 万円</b><span>利益保護候補 − 元の出口</span></div><div class="metric"><small>利益返却額の合計</small><b>${number(old.giveback/10000,2)} → ${number(next.giveback/10000,2)}</b><span>万円 ／ 各取引の保有中終値で評価</span></div>`;}
/**
 * 機能: 現在の表示範囲へ五分足、取引、軸を描く。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderChart(){const bars=DATA.candles[state.symbol+"/"+state.session],trades=currentTrades(),visible=bars.filter(b=>b.t>=state.start-5*MINUTE&&b.t<=state.end),values=[];for(const b of visible)values.push(b.low,b.high);for(const t of trades){if(t.entry_time_ms>=state.start&&t.entry_time_ms<=state.end)values.push(t.entry_price);if(t.exit_time_ms>=state.start&&t.exit_time_ms<=state.end)values.push(t.exit_price);}if(!values.length)for(const b of bars)values.push(b.low,b.high);const lo=Math.min(...values),hi=Math.max(...values),pad=Math.max((hi-lo)*.15,state.symbol==="NK225"?30:1.5);state.ymin=lo-pad;state.ymax=hi+pad;el.svg.replaceChildren();hideTooltip();const defs=svg("defs"),clip=svg("clipPath",{id:"plot-clip"},null,defs);svg("rect",{x:BOX.left,y:BOX.top,width:BOX.right-BOX.left,height:BOX.bottom-BOX.top},null,clip);svg("rect",{x:BOX.left,y:BOX.top,width:BOX.right-BOX.left,height:BOX.bottom-BOX.top,fill:"#fbfcfe"});for(let i=0;i<=5;i++){const price=state.ymin+(state.ymax-state.ymin)*i/5,py=y(price);svg("line",{x1:BOX.left,y1:py,x2:BOX.right,y2:py,stroke:"#e5ebf1"});svg("text",{x:BOX.left-12,y:py+4,"text-anchor":"end",fill:"#65768a","font-size":12},number(price,state.symbol==="NK225"?0:1));}const span=(state.end-state.start)/MINUTE,step=span>550?120:span>250?60:span>110?30:span>55?15:5;for(let t=Math.ceil(state.start/(step*MINUTE))*step*MINUTE;t<state.end;t+=step*MINUTE){svg("line",{x1:x(t),y1:BOX.top,x2:x(t),y2:BOX.bottom,stroke:"#e8edf3","stroke-dasharray":"3 4"});svg("text",{x:x(t),y:BOX.bottom+24,"text-anchor":"middle",fill:"#65768a","font-size":12},clock.format(t));if(clock.format(t)==="00:00")svg("text",{x:x(t),y:BOX.bottom+42,"text-anchor":"middle",fill:"#65768a","font-size":11},calendar.format(t));}const layer=svg("g",{"clip-path":"url(#plot-clip)"});const chosen=trades.find(t=>t.id===state.selected);if(chosen)svg("rect",{x:x(chosen.entry_time_ms),y:BOX.top,width:x(chosen.exit_time_ms)-x(chosen.entry_time_ms),height:BOX.bottom-BOX.top,fill:tradeColor(chosen),opacity:.045},null,layer);const bw=Math.max(1.5,Math.min(16,(BOX.right-BOX.left)/(span/5)*.66));for(const b of visible){const color=b.close>=b.open?"#238774":"#cb5b66";svg("line",{x1:x(b.t),y1:y(b.high),x2:x(b.t),y2:y(b.low),stroke:color,"stroke-width":1.2},null,layer);svg("rect",{x:x(b.t)-bw/2,y:Math.min(y(b.open),y(b.close)),width:bw,height:Math.max(1.4,Math.abs(y(b.open)-y(b.close))),fill:color},null,layer);}for(const t of trades)drawTrade(t,layer);svg("text",{x:BOX.left,y:24,fill:"#65768a","font-size":12},"価格（"+(state.symbol==="NK225"?"円":"ポイント")+"） / 確定5分足");svg("line",{id:"crosshair",x1:0,y1:BOX.top,x2:0,y2:BOX.bottom,stroke:"#617b94","stroke-dasharray":"4 3",visibility:"hidden"});el.title.textContent=state.symbol+" ・ "+sessionLabel(state.session);renderMetrics();renderDetail();for(const row of el.table.rows)row.classList.toggle("selected",row.dataset.rowId===state.selected);}
/**
 * 機能: 実際の一分時刻へ新規・返済と有効な保護価格を描く。
 * 引数: t {object} 取引、parent {SVGElement} 描画先。
 * 返り値: {undefined} なし。
 */
function drawTrade(t,parent){const selected=t.id===state.selected,color=tradeColor(t),ex=x(t.entry_time_ms),ey=y(t.entry_price),xx=x(t.exit_time_ms),xy=y(t.exit_price),size=t.method==="baseline"?8:6;svg("line",{x1:ex,y1:ey,x2:xx,y2:xy,stroke:color,"stroke-width":selected?2:1.3,"stroke-dasharray":t.method==="baseline"?"3 4":"7 4",opacity:.8},null,parent);if(el.protection.checked&&t.protection.length){let d="";t.protection.forEach((p,i)=>{d+=(i?"H":"M")+x(p.t)+(i?"V":" ")+y(p.price);});d+="H"+xx;svg("path",{d,fill:"none",stroke:color,"stroke-width":1.4,opacity:.75,"stroke-dasharray":"2 3"},null,parent);}const g=svg("g",{"data-trade-id":t.id,style:"cursor:pointer"},null,parent),points=t.side===1?`${ex},${ey-size} ${ex-size},${ey+size} ${ex+size},${ey+size}`:`${ex},${ey+size} ${ex-size},${ey-size} ${ex+size},${ey-size}`;svg("polygon",{points,fill:t.method==="baseline"?"white":color,stroke:color,"stroke-width":2},null,g);svg("polygon",{points:`${xx},${xy-size} ${xx+size},${xy} ${xx},${xy+size} ${xx-size},${xy}`,fill:color,stroke:"white","stroke-width":2},null,g);svg("title",{},(t.method==="baseline"?"元":"保護候補")+" "+clock.format(t.entry_time_ms)+" "+number(t.entry_price)+" → "+clock.format(t.exit_time_ms)+" "+number(t.exit_price),g);if(selected){drawLabel(ex,ey,(t.side===1?"買い ":"売り ")+clock.format(t.entry_time_ms)+" / "+number(t.entry_price),color,t.side===1?28:-25,parent);drawLabel(xx,xy,(t.method==="baseline"?"元の返済 ":"保護候補の返済 ")+clock.format(t.exit_time_ms)+" / "+number(t.exit_price),color,t.side===1?-26:28,parent);if(t.mfe_yen>0){svg("circle",{cx:x(t.peak.t),cy:y(t.peak.price),r:5,fill:"white",stroke:"#ac7420","stroke-width":2},null,parent);drawLabel(x(t.peak.t),y(t.peak.price),"終値での最大含み益（費用前）"+money(t.mfe_yen)+"万円","#ac7420",t.side===1?-28:31,parent);}const pair=currentTrades().find(p=>p.method!==t.method&&p.entry_time_ms===t.entry_time_ms&&p.side===t.side);if(pair)drawLabel(x(pair.exit_time_ms),y(pair.exit_price),(pair.method==="baseline"?"元の返済 ":"保護候補の返済 ")+clock.format(pair.exit_time_ms)+" / "+number(pair.exit_price),tradeColor(pair),t.side===1?32:-32,parent);}}
/**
 * 機能: マーカー付近に背景付き文字を描く。
 * 引数: px/py {number} 座標、label/color {string} 文字・色、offset {number} 上下距離、parent {SVGElement} 描画先。
 * 返り値: {undefined} なし。
 */
function drawLabel(px,py,label,color,offset,parent){const anchor=px>BOX.right-220?"end":px<BOX.left+190?"start":"middle",lx=anchor==="end"?px-10:anchor==="start"?px+10:px;svg("text",{x:lx,y:Math.max(BOX.top+15,Math.min(BOX.bottom-7,py+offset)),"text-anchor":anchor,fill:color,"font-size":12,"font-weight":700,stroke:"white","stroke-width":4,"paint-order":"stroke"},label,parent);}
/**
 * 機能: 選んだ取引の具体的な損益と利益返却を表示する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderDetail(){const t=allTrades().find(v=>v.id===state.selected);if(!t){el.detail.textContent="このセッションに取引はありません。";el.profit.replaceChildren();return;}el.detail.innerHTML=`<div class="metric"><small>${t.method==="baseline"?"元の出口":"利益保護候補"} ／ ${t.side===1?"買い":"売り"}</small><b>${clock.format(t.entry_time_ms)} → ${clock.format(t.exit_time_ms)}</b><span>${number(t.entry_price)} → ${number(t.exit_price)} ／ ${number(t.duration_min,0)}分</span></div><div class="metric"><small>費用控除後の収支</small><b class="${t.net_yen>=0?"positive":"negative"}">${money(t.net_yen)} 万円</b><span>${t.reason}</span></div><div class="metric"><small>保有中の最大含み益</small><b>${money(t.mfe_yen)} 万円</b><span>1分終値・費用控除前</span></div><div class="metric"><small>最高評価から返済までの低下</small><b class="after">${number(t.giveback_yen/10000,2)} 万円</b><span>最大含み益 − 実現値幅</span></div>`;renderProfit(t);}
/**
 * 機能: 選択取引と同じ入口の比較取引の保有中損益を描く。
 * 引数: selected {object} 選択取引。
 * 返り値: {undefined} なし。
 */
function renderProfit(selected){el.profit.replaceChildren();const pair=currentTrades().find(t=>t.method!==selected.method&&t.entry_time_ms===selected.entry_time_ms&&t.side===selected.side),trades=pair?[selected,pair]:[selected],mult=selected.symbol==="NK225"?.1:1,start=selected.entry_time_ms,end=Math.max(...trades.map(t=>t.exit_time_ms)),values=trades.flatMap(t=>t.holding_path.map(p=>p.points*mult)),low=Math.min(0,...values),high=Math.max(0,...values),pad=Math.max((high-low)*.12,.2),ymin=low-pad,ymax=high+pad,xx=t=>82+(t-start)/Math.max(MINUTE,end-start)*1116,yy=v=>164-(v-ymin)/(ymax-ymin)*128;for(let i=0;i<=3;i++){const v=ymin+(ymax-ymin)*i/3;svg("line",{x1:82,x2:1198,y1:yy(v),y2:yy(v),stroke:"#e5ebf1"},null,el.profit);svg("text",{x:70,y:yy(v)+4,"text-anchor":"end",fill:"#65768a","font-size":11},number(v,1),el.profit);}svg("line",{x1:82,x2:1198,y1:yy(0),y2:yy(0),stroke:"#9fafbe","stroke-dasharray":"3 4"},null,el.profit);svg("text",{x:82,y:18,fill:"#65768a","font-size":12},"選択取引の含み損益（万円・費用控除前）／ 同じ入口がある場合は重ねて表示",el.profit);for(const t of trades){const color=tradeColor(t),d=t.holding_path.map((p,i)=>(i?"L":"M")+xx(p.t)+" "+yy(p.points*mult)).join(" ");svg("path",{d,stroke:color,"stroke-width":t.id===selected.id?2.2:1.6,fill:"none"},null,el.profit);const last=t.holding_path.at(-1);svg("circle",{cx:xx(last.t),cy:yy(last.points*mult),r:4,fill:color},null,el.profit);svg("text",{x:xx(last.t),y:190,"text-anchor":xx(last.t)>1100?"end":"middle",fill:color,"font-size":11},(t.method==="baseline"?"元の返済 ":"保護候補の返済 ")+clock.format(last.t),el.profit);}svg("text",{x:82,y:190,fill:"#65768a","font-size":11},"新規 "+clock.format(start),el.profit);document.getElementById("profit-note").textContent=pair?"利益保護候補の返済後は、その建玉の損益線を延長していません。元の建玉がその後に取り戻した利益も、失った利益も灰色の線で確認できます。":"この取引と同一時刻・方向の元取引はありません。再エントリーのため、単独の保有中損益を表示しています。";}
/**
 * 機能: 全セッションの収支と利益返却を並べる。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderSummary(){let html="";for(const symbol of ["NK225","TOPIX"]){for(const session of [...DATA.sessions,null]){const filter=t=>t.symbol===symbol&&(!session||t.session===session),a=aggregate(DATA.methods.baseline.trades.filter(filter)),b=aggregate(DATA.methods[state.mode].trades.filter(filter));html+=`<tr${session?"":" style='font-weight:700;background:#edf5ff'"}><td>${symbol}</td><td>${session?sessionLabel(session):"合計"}</td><td>${number(a.profit/10000,2)}</td><td>${number(a.loss/10000,2)}</td><td>${money(a.net)}</td><td>${number(b.profit/10000,2)}</td><td>${number(b.loss/10000,2)}</td><td>${money(b.net)}</td><td class="${b.net>=a.net?"positive":"negative"}">${money(b.net-a.net)}</td><td>${number(a.giveback/10000,2)}</td><td>${number(b.giveback/10000,2)}</td></tr>`;}}document.getElementById("session-table").innerHTML=html;}
/**
 * 機能: 比較中の全取引を一覧にする。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderTable(){let html="";const trades=allTrades().sort((a,b)=>a.session.localeCompare(b.session)||a.symbol.localeCompare(b.symbol)||a.entry_time_ms-b.entry_time_ms||a.method.localeCompare(b.method));for(const t of trades)html+=`<tr data-row-id="${t.id}"><td><button class="row-button" data-trade-id="${t.id}">表示 ${t.number}</button></td><td class="${t.method==="baseline"?"base-color":"new-color"}">${t.method==="baseline"?"元の出口":"利益保護候補"}</td><td>${t.symbol}</td><td>${sessionLabel(t.session)}</td><td>${t.side===1?"買い":"売り"}</td><td>${calendar.format(t.entry_time_ms)} ${clock.format(t.entry_time_ms)}</td><td class="number">${number(t.entry_price)}</td><td>${calendar.format(t.exit_time_ms)} ${clock.format(t.exit_time_ms)}</td><td class="number">${number(t.exit_price)}</td><td class="number ${t.net_yen>=0?"positive":"negative"}">${money(t.net_yen)}</td><td class="number">${money(t.mfe_yen)}</td><td class="number">${number(t.giveback_yen/10000,2)}</td><td>${t.reason}</td></tr>`;el.table.innerHTML=html;document.getElementById("trade-list-title").textContent="比較中の全"+trades.length+"取引";}
/**
 * 機能: 親の比較JSONに記載された手法を説明する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderRule(){const m=DATA.methods.selected,rule=m.rule??{},labels={kind:"出口種類",trigger:"保護開始の利益幅",width:"追跡幅",retain:"利益保持率",window:"参照本数",delay:"追加遅延"};const selectionText=DATA.selection.description??DATA.selection.note??"利益を早く確保する効果と、その後の値動きを逃す代償を見るための比較候補です。元方式を上回る手法として採用を推薦するものではありません。";document.getElementById("selection-note").textContent=selectionText;document.getElementById("rule-name").textContent=m.name??"検証結果の利益保護候補";document.getElementById("rule-description").textContent=m.description??Object.entries(rule).map(([k,v])=>(labels[k]??k)+"："+v).join(" ／ ");document.getElementById("mode-note").textContent=state.mode==="fixed_entries"?"入口固定の比較：元の12取引と同じ時刻・価格・方向で入り、返済だけを変更します。早期返済しても追加の新規は行いません。出口単体の効果を見るための比較で、そのまま自動売買の運用成績ではありません。":"運用の比較：新規ルールは同じでも、早期返済によって45分の待機後に再度エントリーできるため、取引数や次の入口は変わります。入口固定の比較と区別して評価してください。";}
/**
 * 機能: セッション・銘柄・比較方法の切替を反映する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function onSelectionChange(){state.symbol=el.symbol.value;state.session=el.session.value;state.mode=el.mode.value;state.selected=currentTrades().find(t=>t.method!=="baseline")?.id??currentTrades()[0]?.id??null;renderRule();renderSummary();renderTable();setFullRange();renderChart();}
/**
 * 機能: マーカーや表の行で取引を選ぶ。
 * 引数: event {Event} クリックイベント。
 * 返り値: {undefined} なし。
 */
function onTradeClick(event){const target=event.target.closest("[data-trade-id]");if(!target)return;state.selected=target.dataset.tradeId;const t=allTrades().find(v=>v.id===state.selected);state.symbol=t.symbol;state.session=t.session;el.symbol.value=state.symbol;el.session.value=state.session;setFullRange();renderChart();}
/**
 * 機能: 表示範囲を保存された時間範囲へ収める。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function clampRange(){if(state.start<state.fullStart){state.end+=state.fullStart-state.start;state.start=state.fullStart;}if(state.end>state.fullEnd){state.start-=state.end-state.fullEnd;state.end=state.fullEnd;}}
/**
 * 機能: 時間軸を拡大・縮小する。
 * 引数: factor {number} 表示幅の倍率。
 * 返り値: {undefined} なし。
 */
function zoom(factor){const center=(state.start+state.end)/2,span=Math.max(30*MINUTE,Math.min(state.fullEnd-state.fullStart,(state.end-state.start)*factor));state.start=center-span/2;state.end=center+span/2;clampRange();renderChart();}
/**
 * 機能: 選択取引の入口から、元の返済または改善返済の後まで表示する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function viewTrade(){const t=allTrades().find(v=>v.id===state.selected);if(!t)return;const pair=currentTrades().find(p=>p.method!==t.method&&p.entry_time_ms===t.entry_time_ms&&p.side===t.side),last=Math.max(t.exit_time_ms,pair?.exit_time_ms??t.exit_time_ms);state.start=Math.max(state.fullStart,t.entry_time_ms-20*MINUTE);state.end=Math.min(state.fullEnd,last+60*MINUTE);renderChart();}
/**
 * 機能: ブラウザー座標をSVG座標へ変換する。
 * 引数: event {PointerEvent} 操作イベント。
 * 返り値: {DOMPoint} SVG座標。
 */
function pointerPosition(event){return new DOMPoint(event.clientX,event.clientY).matrixTransform(el.svg.getScreenCTM().inverse());}
/**
 * 機能: チャート移動の開始位置を記憶する。
 * 引数: event {PointerEvent} 押下イベント。
 * 返り値: {undefined} なし。
 */
function onPointerDown(event){if(event.button!==0||event.target.closest("[data-trade-id]"))return;const p=pointerPosition(event);state.drag={x:p.x,start:state.start,end:state.end};el.svg.setPointerCapture(event.pointerId);}
/**
 * 機能: チャートを移動するか、五分足の値を表示する。
 * 引数: event {PointerEvent} 移動イベント。
 * 返り値: {undefined} なし。
 */
function onPointerMove(event){const p=pointerPosition(event);if(state.drag){const offset=(p.x-state.drag.x)/(BOX.right-BOX.left)*(state.drag.end-state.drag.start);state.start=state.drag.start-offset;state.end=state.drag.end-offset;clampRange();renderChart();return;}if(p.x<BOX.left||p.x>BOX.right||p.y<BOX.top||p.y>BOX.bottom){hideTooltip();return;}const time=state.start+(p.x-BOX.left)/(BOX.right-BOX.left)*(state.end-state.start),bars=DATA.candles[state.symbol+"/"+state.session];let near=bars[0];for(const b of bars)if(Math.abs(b.t-time)<Math.abs(near.t-time))near=b;if(Math.abs(near.t-time)>5*MINUTE){hideTooltip();return;}const line=document.getElementById("crosshair");line.setAttribute("x1",x(near.t));line.setAttribute("x2",x(near.t));line.setAttribute("visibility","visible");el.tooltip.innerHTML=`${calendar.format(near.t)} <b>${clock.format(near.t)}〜${clock.format(near.t+5*MINUTE)}</b><br>始値 ${number(near.open)}　高値 ${number(near.high)}<br>安値 ${number(near.low)}　終値 ${number(near.close)}<br>出来高 ${number(near.volume,0)}`;el.tooltip.classList.remove("hidden");const r=el.wrap.getBoundingClientRect();el.tooltip.style.left=Math.max(0,Math.min(r.width-el.tooltip.offsetWidth-4,event.clientX-r.left+15))+"px";el.tooltip.style.top=Math.max(0,event.clientY-r.top-el.tooltip.offsetHeight-12)+"px";}
/**
 * 機能: チャート移動を終了する。
 * 引数: event {PointerEvent} 解放イベント。
 * 返り値: {undefined} なし。
 */
function onPointerUp(event){state.drag=null;if(el.svg.hasPointerCapture(event.pointerId))el.svg.releasePointerCapture(event.pointerId);}
/**
 * 機能: 五分足の情報表示を隠す。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function hideTooltip(){el.tooltip.classList.add("hidden");const line=document.getElementById("crosshair");if(line)line.setAttribute("visibility","hidden");}

// ----------------------------------------
// 初期画面を九月二十三日のNK225に設定し、表示の操作を接続する。
for(const session of DATA.sessions){const o=document.createElement("option");o.value=session;o.textContent=sessionLabel(session);el.session.appendChild(o);}el.session.value=state.session;
for(const control of [el.symbol,el.session,el.mode])control.addEventListener("change",onSelectionChange);el.protection.addEventListener("change",renderChart);el.table.addEventListener("click",onTradeClick);el.svg.addEventListener("click",onTradeClick);
document.getElementById("zoom-in").addEventListener("click",()=>zoom(.65));document.getElementById("zoom-out").addEventListener("click",()=>zoom(1/.65));document.getElementById("view-all").addEventListener("click",()=>{setFullRange();renderChart();});document.getElementById("view-trade").addEventListener("click",viewTrade);
el.svg.addEventListener("pointerdown",onPointerDown);el.svg.addEventListener("pointermove",onPointerMove);el.svg.addEventListener("pointerup",onPointerUp);el.svg.addEventListener("pointercancel",onPointerUp);el.svg.addEventListener("pointerleave",hideTooltip);onSelectionChange();
</script></body></html>'''


def main() -> None:
    """機能: 比較結果を読み込み、通信不要のHTMLと構造検査を保存する。

    引数: なし。返り値: なし (None)。
    """
    arguments = argparse.ArgumentParser(description="保存データの出口比較図を作成する")
    arguments.add_argument("--input", type=Path, default=SOURCE, help="親が確定した比較対象JSON")
    options = arguments.parse_args()
    payload = load_payload(options.input)
    spec = importlib.util.spec_from_file_location("previous_chart", BASE / "図解HTMLを生成.py")
    previous = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(previous)
    style = previous.TEMPLATE.split("<style>", 1)[1].split("</style>", 1)[0]
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).replace("<", "\\u003c")
    html = TEMPLATE.replace("__STYLE__", style).replace("__PAYLOAD__", encoded)
    parser = previous.StructureCheck()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids))
    assert not parser.external and "fetch(" not in html and "XMLHttpRequest" not in html
    assert len(payload["candles"]) == 10 and all(payload["candles"].values())
    assert len(payload["methods"]["baseline"]["trades"]) == len(payload["methods"]["fixed_entries"]["trades"]) == 12
    entry_fields = ("symbol", "session", "entry_time", "entry_price", "side", "atr")
    original_entries = sorted(tuple(t[k] for k in entry_fields) for t in payload["methods"]["baseline"]["trades"])
    fixed_entries = sorted(tuple(t[k] for k in entry_fields) for t in payload["methods"]["fixed_entries"]["trades"])
    assert original_entries == fixed_entries, "入口固定比較の新規条件が一致しません"
    for name, method in payload["methods"].items():
        assert all(t["entry_time_ms"] <= t["exit_time_ms"] for t in method["trades"])
        assert all(abs(t["giveback_yen"] - max(0, t["mfe_yen"] - t["gross_yen"])) < 1e-6 for t in method["trades"])
    check = {"判定": "合格", "五分足数": sum(map(len, payload["candles"].values())), "銘柄セッション組数": len(payload["candles"]), "方式別取引数": {k: len(v["trades"]) for k, v in payload["methods"].items()}, "利益返却": "検証エンジン値を採用、保存一分終値の最大含み益との一致も確認", "保護価格": "当該足で有効なstopを描画。next_stopは同一足へ遡及しない", "時刻丸め": "なし", "外部読込": 0}
    check["比較入力"] = str(options.input.resolve())
    check["比較入力SHA256"] = hashlib.sha256(options.input.read_bytes()).hexdigest()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "出口比較.html").write_text(html, encoding="utf-8")
    (OUTPUT / "出口比較HTML_静的検査.json").write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(check, ensure_ascii=False))


if __name__ == "__main__":
    main()
