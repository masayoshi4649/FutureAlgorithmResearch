"""保存版の五分足と主候補の仮想取引から、通信不要の対話図解を生成する。"""

from __future__ import annotations

import csv
from datetime import datetime
from html.parser import HTMLParser
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent
SAVED = BASE / "保存版"
SESSIONS = ["2026-09-21_Day", "2026-09-21_Night", "2026-09-22_Day", "2026-09-22_Night", "2026-09-23_Day"]


def epoch(value: str) -> int:
    """機能: 時差付き保存時刻を描画用のミリ秒へ変換する。

    引数: value (str) は時差付き日時。返り値: 世界共通の経過ミリ秒 (int)。
    """
    return int(datetime.fromisoformat(value).timestamp() * 1000)


def load_payload() -> dict:
    """機能: 保存版だけから確定五分足と主候補の十二取引を読み込む。

    引数: なし。返り値: 単一HTMLへ埋め込む描画データ (dict)。
    """
    source = json.loads((SAVED / "work/wave_v5/方向主候補.json").read_text(encoding="utf-8"))
    candles = {}
    for symbol in ("NK225", "TOPIX"):
        for session in SESSIONS:
            path = SAVED / "candle_5min" / symbol / f"{session}.csv"
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            candles[f"{symbol}/{session}"] = [
                {"t": epoch(row["time"]), **{key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}}
                for row in rows if row["closed"].lower() == "true"
            ]
    trades = []
    for number, trade in enumerate(source["trades"], 1):
        value = dict(trade, id=number)
        for field in ("entry_time", "exit_time", "signal_time"):
            value[field + "_ms"] = epoch(trade[field])
        multiplier = 1000 if trade["symbol"] == "NK225" else 10000
        value["net_yen"] = trade["net_points"] * multiplier
        value["gross_yen"] = trade["gross_points"] * multiplier
        value["fee_yen"] = (20 if trade["symbol"] == "NK225" else 1) * multiplier
        trades.append(value)
    return {"sessions": SESSIONS, "candles": candles, "trades": trades, "config": source["config"]}


# ----------------------------------------
# 表示・操作・データを一ファイルへ閉じ込め、外部読み込みを使わない。

TEMPLATE = r'''<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>方法①の売買ポイント｜NK225・TOPIX</title>
<style>
:root{color-scheme:light;--ink:#183047;--muted:#65768a;--line:#dce5ed;--bg:#f4f7fb;--blue:#1264b5;--purple:#8a42b7;--amber:#9c640c;--green:#238774;--red:#cb5b66}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:"Yu Gothic UI","Meiryo",sans-serif;font-size:14px;line-height:1.7}main{max-width:1440px;margin:auto;padding:30px 30px 44px}h1{font-size:28px;line-height:1.4;margin:4px 0 10px;letter-spacing:.015em}h2{font-size:19px;margin:0 0 12px}p{margin:8px 0}.eyebrow{font-size:12px;letter-spacing:.11em;color:var(--blue);font-weight:700}.lead{color:var(--muted);max-width:1080px}.card{background:white;border:1px solid var(--line);border-radius:16px;padding:22px;margin-top:20px;box-shadow:0 4px 16px #233c5510}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:22px}.step{background:#fff;border:1px solid var(--line);border-radius:12px;padding:16px}.step b{display:block;font-size:15px}.step small{display:block;margin-top:4px;color:var(--muted);font-size:12px}.step-number{color:var(--blue);font-size:11px;font-weight:700;letter-spacing:.08em}.toolbar{display:flex;align-items:end;gap:14px;flex-wrap:wrap}.control{display:grid;gap:4px}.control label{font-size:12px;color:var(--muted);font-weight:700}select,button{font:inherit;border:1px solid #cbd7e3;background:#fff;color:var(--ink);border-radius:8px;min-height:38px;padding:7px 11px}button{cursor:pointer}button:hover{background:#eff5fc;border-color:#88b0d6}button:focus-visible,select:focus-visible,a:focus-visible{outline:3px solid #89b9f0;outline-offset:2px}.actions{display:flex;gap:6px;flex-wrap:wrap}.status{margin-left:auto;text-align:right;font-size:13px}.status strong{font-size:21px}.chart-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-top:18px}.chart-head h2{margin:0}.legend{display:flex;gap:13px;flex-wrap:wrap;font-size:12px;color:var(--muted)}.legend i{display:inline-block;width:10px;height:10px;margin-right:5px;border-radius:2px}.chart-wrap{position:relative;margin-top:6px;overflow:hidden}.chart{display:block;width:100%;height:auto;min-height:320px;touch-action:none;cursor:crosshair}.chart text{font-family:inherit}.hint{font-size:12px;color:var(--muted);margin:0}.tooltip{position:absolute;pointer-events:none;background:#142d46f5;color:white;border-radius:8px;padding:10px 13px;font-size:12px;z-index:4;min-width:175px;box-shadow:0 5px 18px #142d4622}.hidden{display:none}.selected-detail{display:grid;grid-template-columns:1.25fr repeat(3,1fr);gap:12px;margin-top:16px;padding-top:16px;border-top:1px solid var(--line)}.metric small{display:block;color:var(--muted);font-size:12px}.metric b{display:block;font-size:18px}.metric span{font-size:12px;color:var(--muted)}.long{color:var(--blue)}.short{color:var(--purple)}.positive{color:#08725e}.negative{color:#b44553}.pill{display:inline-block;background:#edf4fc;border:1px solid #dce8f5;border-radius:99px;padding:2px 9px;font-size:12px}.pill.short{background:#f8effd;border-color:#ecd8f5}.note{background:#fff8e9;border-left:3px solid #d6a647;padding:12px 15px;border-radius:5px;font-size:12px;color:#685330;margin-top:16px}.table-scroll{overflow-x:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:13px}th{text-align:left;background:#f4f7fb;color:var(--muted);font-weight:600;font-size:12px}td,th{padding:10px 11px;border-bottom:1px solid #e7edf3}td.number{text-align:right;font-variant-numeric:tabular-nums}tbody tr.selected{background:#edf5ff}tbody tr:hover{background:#f5f9ff}.row-button{border:none;background:transparent;min-height:26px;padding:0;color:var(--blue);text-align:left;text-decoration:underline;text-underline-offset:3px}.row-button:hover{background:transparent}.table-caption{color:var(--muted);font-size:12px;margin:0 0 12px}.spec-grid{display:grid;grid-template-columns:1fr 1fr;gap:22px}.spec-grid p{font-size:13px}.formula{font-family:Consolas,monospace;background:#f4f7fb;border-radius:8px;padding:10px;font-size:12px;white-space:pre-wrap}.footer{font-size:12px;color:var(--muted);margin-top:16px}details summary{cursor:pointer;font-weight:700;font-size:15px}a{color:var(--blue)}@media(max-width:850px){main{padding:18px 12px}.card{padding:14px}.flow{grid-template-columns:1fr 1fr}.selected-detail{grid-template-columns:1fr 1fr}.spec-grid{grid-template-columns:1fr}.status{margin-left:0;text-align:left}.chart-head{align-items:start;flex-direction:column}h1{font-size:23px}.chart{min-height:270px}}
</style>
</head>
<body>
<main>
<div class="eyebrow">保存済み 5 セッション ／ 方法①の仮想売買</div>
<h1>方向を見定め、反発・反落を待って入る</h1>
<p class="lead">5分足の上に、新規と返済の<strong>仮想約定した1分足の開始時刻・価格</strong>を重ねました。方法①は、価格変化の累積から方向を決め、1ATRの反発・反落で新規、2.5ATRの初期損切りと4ATRの追跡幅で返済する方式です。ATRは直近の通常の値動き幅を表します。</p>
<!--
[コンポーネント概要]
.flow は方法①の判断順序を示します。方向判定、新規待機、保有管理、セッション内返済の順に読みます。
#symbol-select と #session-select は表示対象を選択します。
#zoom-in / #zoom-out は横軸を拡大・縮小します。#view-all はセッション全体へ戻し、#view-trade は選択取引の保有区間を表示します。
#price-chart は実時刻軸の五分ローソク、実際の一分時刻に置いた新規・返済マーカー、保有区間線を描きます。
#chart-tooltip はポインター付近の五分足OHLCと出来高を表示します。
#trade-detail は選択取引の方向、実約定時刻・価格、固定ATRと収支を説明します。
#order-path は選択取引の注文経路または採用した情報時刻の意味を補足します。
#all-trades は全十二取引を常時一覧表示します。取引行の表示ボタンは対象チャートと詳細を切り替えます。
.selected は現在選んだ取引行、.hidden は非表示、.long / .short は新規方向の色分けです。
-->
<div class="flow">
<div class="step"><span class="step-number">01　方向を判定</span><b>小さな上下動を控除して累積</b><small>CUSUMが±0.6375へ到達すると買い・売り方向を保持します。</small></div>
<div class="step"><span class="step-number">02　新規を待つ</span><b>買いは1ATR反発、売りは1ATR反落</b><small>開始45分後から。入口ATRは注文待機開始時に固定します。</small></div>
<div class="step"><span class="step-number">03　幅を持たせて保有</span><b>初期損切り2.5ATR・追跡4ATR</b><small>保有中の逆シグナルだけでは返済しません。固定利確はありません。</small></div>
<div class="step"><span class="step-number">04　セッション内で返済</span><b>保護価格到達、または予定時刻</b><small>デイ15:35／ナイト翌05:50以降の最初の実在足で返済します。</small></div>
</div>
<section class="card" aria-label="五分足と売買ポイント">
<div class="toolbar">
<div class="control"><label for="symbol-select">銘柄</label><select id="symbol-select"><option value="NK225" selected>NK225</option><option value="TOPIX">TOPIX</option></select></div>
<div class="control"><label for="session-select">セッション</label><select id="session-select"></select></div>
<div class="actions"><button id="zoom-in" type="button" aria-label="横軸を拡大">＋ 拡大</button><button id="zoom-out" type="button" aria-label="横軸を縮小">− 縮小</button><button id="view-all" type="button">全体</button><button id="view-trade" type="button">保有区間</button></div>
<div id="session-status" class="status" aria-live="polite"></div>
</div>
<div class="chart-head"><h2 id="chart-title"></h2><div class="legend"><span><i style="background:var(--green)"></i>陽線</span><span><i style="background:var(--red)"></i>陰線</span><span><i style="background:var(--blue)"></i>買い新規 ▲</span><span><i style="background:var(--purple)"></i>売り新規 ▼</span><span><i style="background:var(--amber)"></i>返済 ◆</span></div></div>
<div id="chart-wrap" class="chart-wrap"><svg id="price-chart" class="chart" viewBox="0 0 1240 490" role="img" aria-labelledby="chart-title chart-description"></svg><div id="chart-tooltip" class="tooltip hidden"></div></div>
<p id="chart-description" class="hint">横軸は日本時間。ドラッグで移動、ボタンで拡大縮小。ポインターを合わせると五分足の値を表示します。薄い帯と点線は保有区間です。足がない時間も間隔を詰めずに表示します。</p>
<div id="trade-detail" class="selected-detail" aria-live="polite"></div>
<p id="order-path" class="hint" style="margin-top:14px"></p>
<div class="note">ローソクは5分足ですが、新規・返済マーカーは5分へ丸めていません。マーカーの時刻は仮想約定した1分足の開始時刻であり、足内の秒単位の順序は未再現です。追跡条件は1分確定後に更新し、次の実在足から有効にする検証です。</div>
</section>
<section class="card" aria-label="全セッションの取引一覧">
<h2>全12取引の新規・返済</h2><p class="table-caption">「表示」を押すと、その取引のチャートと詳細に切り替わります。ラージ各1枚、収支は各取引の往復費用2ティックを控除した仮想成績です。ナイトの日付は開始日の表記です。</p>
<div class="table-scroll"><table><thead><tr><th>表示</th><th>セッション</th><th>銘柄</th><th>方向</th><th>新規時刻</th><th>新規価格</th><th>返済時刻</th><th>返済価格</th><th>収支（万円）</th><th>返済理由</th></tr></thead><tbody id="all-trades"></tbody></table></div>
</section>
<section class="card"><details><summary>計算と注文条件を確認する</summary><div class="spec-grid">
<div><h2 style="margin-top:16px">方向判定と新規</h2><p>確定1分足の変化量を、その時点の確定5分ATRで割ります。正負の累積和のどちらかが閾値へ達すると、その方向を記憶して両累積和をゼロに戻します。1回の成立で方向が決まり、反対側の成立まで保持します。</p><div class="formula">x = (今回の1分終値 − 前回の1分終値) / ATR
上方向累積 = max(0, 上方向累積 + x − 0.025)
下方向累積 = min(0, 下方向累積 + x + 0.025)
買い方向: 上方向累積 ≧ 0.6375
売り方向: 下方向累積 ≦ −0.6375</div><p>新規注文を作った時の参照終値を追跡安値・高値の初期値にし、その時のATRを固定します。買いは追跡安値＋1ATR、売りは追跡高値−1ATRへの到達で成立。実際に押し目・戻りが生じること自体は必須ではありません。未約定のまま25分超、または方向反転なら取消し、条件があれば作り直します。</p></div>
<div><h2 style="margin-top:16px">幅・時刻・検証上の扱い</h2><p>ATRは5分足の真の値幅を係数1/12で指数平滑した値で、3本から計算、下限2ティックです。1分足は開始時刻tに対してt＋1分で確定し、t＋2分の実在足から情報を利用します。</p><p>初期損切りは新規価格から2.5ATR。保有後は有利な極値から4ATR離れた保護価格へ更新し、既存の保護価格を不利な方向には戻しません。この二つの幅にも<strong>注文待機開始時の同じATR</strong>を使います。</p><p>デイ09:30／ナイト17:45以降に新規可能、返済後は45分待機。デイ15:05／翌05:20から新規禁止。指定返済時刻に足がなければ、その後最初の実在足で返済します。</p><p>主候補のエントリー判断は自銘柄の価格のみです。この成績は5セッションを用いた条件探索の結果であり、将来成績を保証するものではありません。固定の閾値や幅を日ごとに調整した結果ではありません。</p></div>
</div></details></section>
<p class="footer">データ出典：同梱の保存版/candle_5min と 保存版/work/wave_v5/方向主候補.json。HTML内に全データを埋め込んでおり、表示時のネットワーク通信はありません。</p>
</main>
<script id="research-data" type="application/json">__PAYLOAD__</script>
<script>
"use strict";
const DATA=JSON.parse(document.getElementById("research-data").textContent);
const NS="http://www.w3.org/2000/svg", MINUTE=60000, WIDTH=1240, HEIGHT=490;
const BOX={left:82,right:1198,top:50,bottom:428};
const el={symbol:document.getElementById("symbol-select"),session:document.getElementById("session-select"),svg:document.getElementById("price-chart"),tooltip:document.getElementById("chart-tooltip"),wrap:document.getElementById("chart-wrap"),detail:document.getElementById("trade-detail"),status:document.getElementById("session-status"),title:document.getElementById("chart-title"),table:document.getElementById("all-trades")};
const clock=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",hour:"2-digit",minute:"2-digit",hourCycle:"h23"});
const calendar=new Intl.DateTimeFormat("ja-JP",{timeZone:"Asia/Tokyo",month:"2-digit",day:"2-digit"});
const state={symbol:"NK225",session:"2026-09-23_Day",selected:11,start:0,end:1,fullStart:0,fullEnd:1,ymin:0,ymax:1,drag:null};

/**
 * 機能: 数値を日本語の桁区切りで整形する。
 * 引数: value {number} 数値、digits {number} 最大小数桁。
 * 返り値: {string} 整形した数値。
 */
function number(value,digits=1){return Number(value).toLocaleString("ja-JP",{maximumFractionDigits:digits});}
/**
 * 機能: セッション識別子を日本語表記へ変換する。
 * 引数: value {string} セッション識別子。
 * 返り値: {string} 開始日とデイ・ナイト。
 */
function sessionLabel(value){return value.slice(5,10).replace("-","/")+" "+(value.endsWith("Day")?"デイ":"ナイト");}
/**
 * 機能: SVG要素を作成して指定先へ追加する。
 * 引数: tag {string} 要素名、attrs {object} 属性、text {string|null} 文字、parent {Element} 追加先。
 * 返り値: {SVGElement} 作成した要素。
 */
function svg(tag,attrs={},text=null,parent=el.svg){const node=document.createElementNS(NS,tag);for(const [key,value] of Object.entries(attrs))node.setAttribute(key,value);if(text!==null)node.textContent=text;parent.appendChild(node);return node;}
/**
 * 機能: 現在表示する銘柄・セッションの取引を得る。
 * 引数: なし。
 * 返り値: {Array<object>} 対象取引。
 */
function currentTrades(){return DATA.trades.filter(isCurrentTrade);}
/**
 * 機能: 取引が現在の対象に一致するか調べる。
 * 引数: trade {object} 取引。
 * 返り値: {boolean} 一致の有無。
 */
function isCurrentTrade(trade){return trade.symbol===state.symbol&&trade.session===state.session;}
/**
 * 機能: 横軸・縦軸のデータ値を描画座標へ変換する。
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
 * 機能: 全体表示範囲を対象データから設定する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function setFullRange(){const bars=DATA.candles[state.symbol+"/"+state.session],trades=currentTrades();state.fullStart=bars[0].t-8*MINUTE;state.fullEnd=Math.max(bars[bars.length-1].t+5*MINUTE,...trades.map(exitTime))+8*MINUTE;state.start=state.fullStart;state.end=state.fullEnd;}
/**
 * 機能: 取引の返済時刻を取得する。
 * 引数: trade {object} 取引。
 * 返り値: {number} 経過ミリ秒。
 */
function exitTime(trade){return trade.exit_time_ms;}
/**
 * 機能: 現在の表示範囲からローソク、取引、軸を再描画する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderChart(){
 const bars=DATA.candles[state.symbol+"/"+state.session],trades=currentTrades();
 const visible=bars.filter(isVisibleBar),values=[];
 for(const bar of visible)values.push(bar.low,bar.high);
 for(const trade of trades){if(trade.entry_time_ms>=state.start&&trade.entry_time_ms<=state.end)values.push(trade.entry_price);if(trade.exit_time_ms>=state.start&&trade.exit_time_ms<=state.end)values.push(trade.exit_price);}
 if(!values.length)for(const bar of bars)values.push(bar.low,bar.high);
 const min=Math.min(...values),max=Math.max(...values),pad=Math.max((max-min)*.15,state.symbol==="NK225"?30:1.5);state.ymin=min-pad;state.ymax=max+pad;
 el.svg.replaceChildren();el.tooltip.classList.add("hidden");
 const defs=svg("defs"),clip=svg("clipPath",{id:"plot-clip"},null,defs);svg("rect",{x:BOX.left,y:BOX.top,width:BOX.right-BOX.left,height:BOX.bottom-BOX.top},null,clip);
 svg("rect",{x:BOX.left,y:BOX.top,width:BOX.right-BOX.left,height:BOX.bottom-BOX.top,fill:"#fbfcfe"});
 for(let i=0;i<=5;i++){const price=state.ymin+(state.ymax-state.ymin)*i/5,py=y(price);svg("line",{x1:BOX.left,y1:py,x2:BOX.right,y2:py,stroke:"#e5ebf1"});svg("text",{x:BOX.left-12,y:py+4,"text-anchor":"end",fill:"#65768a","font-size":12},number(price,state.symbol==="NK225"?0:1));}
 const span=(state.end-state.start)/MINUTE;let step=span>550?120:span>250?60:span>110?30:span>55?15:5;
 for(let time=Math.ceil(state.start/(step*MINUTE))*step*MINUTE;time<state.end;time+=step*MINUTE){svg("line",{x1:x(time),y1:BOX.top,x2:x(time),y2:BOX.bottom,stroke:"#e8edf3","stroke-dasharray":"3 4"});svg("text",{x:x(time),y:BOX.bottom+24,"text-anchor":"middle",fill:"#65768a","font-size":12},clock.format(time));if(clock.format(time)==="00:00")svg("text",{x:x(time),y:BOX.bottom+43,"text-anchor":"middle",fill:"#65768a","font-size":11},calendar.format(time));}
 const layer=svg("g",{"clip-path":"url(#plot-clip)"});
 for(const trade of trades){const color=trade.side===1?"#1264b5":"#8a42b7";svg("rect",{x:x(trade.entry_time_ms),y:BOX.top,width:Math.max(0,x(trade.exit_time_ms)-x(trade.entry_time_ms)),height:BOX.bottom-BOX.top,fill:color,opacity:trade.id===state.selected ? .055 : .025},null,layer);}
 const bodyWidth=Math.max(1.5,Math.min(16,(BOX.right-BOX.left)/(span/5)*.66));
 for(const bar of visible){const color=bar.close>=bar.open?"#238774":"#cb5b66",px=x(bar.t);svg("line",{x1:px,y1:y(bar.high),x2:px,y2:y(bar.low),stroke:color,"stroke-width":1.35},null,layer);svg("rect",{x:px-bodyWidth/2,y:Math.min(y(bar.open),y(bar.close)),width:bodyWidth,height:Math.max(1.4,Math.abs(y(bar.open)-y(bar.close))),fill:color},null,layer);}
 for(const trade of trades)drawTrade(trade,layer);
 svg("text",{x:BOX.left,y:24,fill:"#65768a","font-size":12},"価格（"+(state.symbol==="NK225"?"円":"ポイント")+"） / 確定5分足");
 svg("line",{id:"crosshair",x1:0,y1:BOX.top,x2:0,y2:BOX.bottom,stroke:"#617b94","stroke-dasharray":"4 3",visibility:"hidden"});
 el.title.textContent=state.symbol+" ・ "+sessionLabel(state.session)+"の売買";
 const net=trades.reduce(sumNet,0);el.status.innerHTML="このセッション："+trades.length+"取引　収支 <strong class='"+(net>=0?"positive":"negative")+"'>"+(net>=0?"+":"")+number(net/10000,2)+"</strong> 万円";
 renderDetail();highlightRows();
}
/**
 * 機能: 五分足が表示範囲と重なるかを判定する。
 * 引数: bar {object} 五分足。
 * 返り値: {boolean} 可視範囲の有無。
 */
function isVisibleBar(bar){return bar.t>=state.start-5*MINUTE&&bar.t<=state.end;}
/**
 * 機能: 取引収支を加算する。
 * 引数: total {number} 合計、trade {object} 取引。
 * 返り値: {number} 更新した合計。
 */
function sumNet(total,trade){return total+trade.net_yen;}
/**
 * 機能: 実時刻位置へ新規・返済マーカーと保有区間線を描く。
 * 引数: trade {object} 取引、parent {SVGElement} 描画先。
 * 返り値: {undefined} なし。
 */
function drawTrade(trade,parent){
 const selected=trade.id===state.selected,color=trade.side===1?"#1264b5":"#8a42b7",ex=x(trade.entry_time_ms),ey=y(trade.entry_price),xx=x(trade.exit_time_ms),xy=y(trade.exit_price),size=selected?8:6;
 svg("line",{x1:ex,y1:ey,x2:xx,y2:xy,stroke:color,"stroke-width":selected?2:1.4,"stroke-dasharray":"5 4",opacity:.8},null,parent);
 const marker=svg("g",{"data-trade-id":trade.id,style:"cursor:pointer"},null,parent);
 const points=trade.side===1?`${ex},${ey-size} ${ex-size},${ey+size} ${ex+size},${ey+size}`:`${ex},${ey+size} ${ex-size},${ey-size} ${ex+size},${ey-size}`;
 svg("polygon",{points,fill:color,stroke:"white","stroke-width":2},null,marker);
 svg("polygon",{points:`${xx},${xy-size} ${xx+size},${xy} ${xx},${xy+size} ${xx-size},${xy}`,fill:"#ad741c",stroke:"white","stroke-width":2},null,marker);
 svg("title",{},"取引 "+trade.id+"："+clock.format(trade.entry_time_ms)+" "+number(trade.entry_price)+" → "+clock.format(trade.exit_time_ms)+" "+number(trade.exit_price),marker);
 if(selected){drawLabel(ex,ey,(trade.side===1?"買い ":"売り ")+clock.format(trade.entry_time_ms)+" / "+number(trade.entry_price),color,trade.side===1?24:-22,parent);drawLabel(xx,xy,"返済 "+clock.format(trade.exit_time_ms)+" / "+number(trade.exit_price),"#9c640c",trade.side===1?-22:24,parent);}
}
/**
 * 機能: マーカー付近へ読みやすい文字ラベルを置く。
 * 引数: px/py {number} 座標、label/color {string} 文字・色、offset {number} 上下距離、parent {SVGElement} 描画先。
 * 返り値: {undefined} なし。
 */
function drawLabel(px,py,label,color,offset,parent){const anchor=px>BOX.right-200?"end":px<BOX.left+170?"start":"middle",lx=anchor==="end"?px-10:anchor==="start"?px+10:px;svg("text",{x:lx,y:Math.max(BOX.top+15,Math.min(BOX.bottom-7,py+offset)),"text-anchor":anchor,fill:color,"font-size":13,"font-weight":700,stroke:"white","stroke-width":4,"paint-order":"stroke"},label,parent);}
/**
 * 機能: 選択取引の具体的な時刻・価格・固定幅を示す。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderDetail(){const trade=DATA.trades.find(isSelectedTrade);if(!trade)return;const side=trade.side===1?"買い・ロング":"売り・ショート",cls=trade.side===1?"long":"short";el.detail.innerHTML=`<div class="metric"><small>選択中：取引 ${trade.id}</small><b class="${cls}">${side}</b><span>${trade.reason} ／ 保有 ${number(trade.duration_min,0)}分</span></div><div class="metric"><small>新規 ${calendar.format(trade.entry_time_ms)} ${clock.format(trade.entry_time_ms)}</small><b>${number(trade.entry_price)}</b><span>返済 ${calendar.format(trade.exit_time_ms)} ${clock.format(trade.exit_time_ms)} ／ ${number(trade.exit_price)}</span></div><div class="metric"><small>注文待機開始時に固定したATR</small><b>${number(trade.atr,3)}</b><span>初期損切り幅 ${number(trade.atr*2.5,2)} ／ 追跡幅 ${number(trade.atr*4,2)}<br>呼値への丸め前の計算幅</span></div><div class="metric"><small>費用控除後の収支</small><b class="${trade.net_yen>=0?"positive":"negative"}">${trade.net_yen>=0?"+":""}${number(trade.net_yen/10000,2)} 万円</b><span>値動き損益 ${number(trade.gross_yen/10000,2)} − 仮定費用 ${number(trade.fee_yen/10000,2)} 万円</span></div>`;
 const path=document.getElementById("order-path");
 if(trade.id===11)path.textContent="この取引の入口：09:30の買い待機を方向反転で取り消し、09:31に売り待機を開始（参照終値67,020、固定ATR126.808）。初期売り条件66,890から、09:31足の高値67,040を受けて次足以降66,910へ更新。09:35足の安値が66,910へ達して売り新規、初期保護価格67,230。15:35に66,800で時刻返済しました。";
 else if(trade.id===1)path.textContent="この取引の入口：09:30に買い待機を開始（参照終値65,050、固定ATR189.846）。初期買い条件65,240から、09:30足の安値64,980を受けて次足以降65,170へ更新。09:40足の高値が65,170へ達して買い新規、初期保護価格64,690。15:35に65,400で時刻返済しました。";
 else path.textContent="この注文に採用した情報の確定時刻："+calendar.format(trade.signal_time_ms)+" "+clock.format(trade.signal_time_ms)+"。この時刻は最初にCUSUMが閾値を超えた時刻ではなく、注文作成に採用した1分足の確定時刻です。新規・返済の具体的な秒時刻は保存1分足からは特定できません。";
}
/**
 * 機能: 現在選択中の取引か判定する。
 * 引数: trade {object} 取引。
 * 返り値: {boolean} 選択の有無。
 */
function isSelectedTrade(trade){return trade.id===state.selected;}
/**
 * 機能: 全取引表を一度生成する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function renderTable(){let html="";for(const trade of DATA.trades){html+=`<tr data-row-id="${trade.id}"><td><button type="button" class="row-button" data-trade-id="${trade.id}" aria-label="取引 ${trade.id} ${trade.symbol} ${sessionLabel(trade.session)} を表示">表示 ${String(trade.id).padStart(2,"0")}</button></td><td>${sessionLabel(trade.session)}</td><td>${trade.symbol}</td><td class="${trade.side===1?"long":"short"}">${trade.side===1?"買い":"売り"}</td><td>${calendar.format(trade.entry_time_ms)} ${clock.format(trade.entry_time_ms)}</td><td class="number">${number(trade.entry_price)}</td><td>${calendar.format(trade.exit_time_ms)} ${clock.format(trade.exit_time_ms)}</td><td class="number">${number(trade.exit_price)}</td><td class="number ${trade.net_yen>=0?"positive":"negative"}">${trade.net_yen>=0?"+":""}${number(trade.net_yen/10000,2)}</td><td>${trade.reason}</td></tr>`;}el.table.innerHTML=html;}
/**
 * 機能: 全取引表の選択行を強調する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function highlightRows(){for(const row of el.table.rows)row.classList.toggle("selected",Number(row.dataset.rowId)===state.selected);}
/**
 * 機能: 対象選択の変更を適用する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function onSelectionChange(){state.symbol=el.symbol.value;state.session=el.session.value;state.selected=currentTrades()[0]?.id??0;setFullRange();renderChart();}
/**
 * 機能: 取引表またはマーカーから取引を選択する。
 * 引数: event {Event} クリック。
 * 返り値: {undefined} なし。
 */
function onTradeClick(event){const target=event.target.closest("[data-trade-id]");if(!target)return;state.selected=Number(target.dataset.tradeId);const trade=DATA.trades.find(isSelectedTrade);state.symbol=trade.symbol;state.session=trade.session;el.symbol.value=state.symbol;el.session.value=state.session;setFullRange();renderChart();}
/**
 * 機能: 指定倍率で横軸の表示幅を変更する。
 * 引数: factor {number} 表示時間幅の倍率。
 * 返り値: {undefined} なし。
 */
function zoom(factor){const center=(state.start+state.end)/2,span=Math.max(30*MINUTE,Math.min(state.fullEnd-state.fullStart,(state.end-state.start)*factor));state.start=center-span/2;state.end=center+span/2;clampRange();renderChart();}
/**
 * 機能: 拡大ボタンの処理を行う。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function onZoomIn(){zoom(.65);}
/**
 * 機能: 縮小ボタンの処理を行う。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function onZoomOut(){zoom(1/.65);}
/**
 * 機能: 表示範囲を保存セッション内に収める。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function clampRange(){if(state.start<state.fullStart){state.end+=state.fullStart-state.start;state.start=state.fullStart;}if(state.end>state.fullEnd){state.start-=state.end-state.fullEnd;state.end=state.fullEnd;}}
/**
 * 機能: セッション全体へ表示を戻す。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function onViewAll(){setFullRange();renderChart();}
/**
 * 機能: 選択取引の保有区間を余白付きで表示する。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function onViewTrade(){const trade=DATA.trades.find(isSelectedTrade);if(!trade)return;const padding=Math.max(15*MINUTE,(trade.exit_time_ms-trade.entry_time_ms)*.07);state.start=Math.max(state.fullStart,trade.entry_time_ms-padding);state.end=Math.min(state.fullEnd,trade.exit_time_ms+padding);renderChart();}
/**
 * 機能: ブラウザー座標をSVG座標へ変換する。
 * 引数: event {PointerEvent} 操作イベント。
 * 返り値: {DOMPoint} SVG座標。
 */
function pointerPosition(event){return new DOMPoint(event.clientX,event.clientY).matrixTransform(el.svg.getScreenCTM().inverse());}
/**
 * 機能: 横軸移動の開始位置を記憶する。
 * 引数: event {PointerEvent} 押下。
 * 返り値: {undefined} なし。
 */
function onPointerDown(event){if(event.button!==0||event.target.closest("[data-trade-id]"))return;const point=pointerPosition(event);state.drag={x:point.x,start:state.start,end:state.end};el.svg.setPointerCapture(event.pointerId);}
/**
 * 機能: 横軸移動または五分足のホバー表示を行う。
 * 引数: event {PointerEvent} 移動。
 * 返り値: {undefined} なし。
 */
function onPointerMove(event){const point=pointerPosition(event);if(state.drag){const offset=(point.x-state.drag.x)/(BOX.right-BOX.left)*(state.drag.end-state.drag.start);state.start=state.drag.start-offset;state.end=state.drag.end-offset;clampRange();renderChart();return;}if(point.x<BOX.left||point.x>BOX.right||point.y<BOX.top||point.y>BOX.bottom){hideTooltip();return;}const time=state.start+(point.x-BOX.left)/(BOX.right-BOX.left)*(state.end-state.start),bars=DATA.candles[state.symbol+"/"+state.session];let nearest=bars[0];for(const bar of bars)if(Math.abs(bar.t-time)<Math.abs(nearest.t-time))nearest=bar;if(Math.abs(nearest.t-time)>5*MINUTE){hideTooltip();return;}const line=document.getElementById("crosshair");line.setAttribute("x1",x(nearest.t));line.setAttribute("x2",x(nearest.t));line.setAttribute("visibility","visible");el.tooltip.innerHTML=`${calendar.format(nearest.t)} <b>${clock.format(nearest.t)}〜${clock.format(nearest.t+5*MINUTE)}</b><br>始値 ${number(nearest.open)}　高値 ${number(nearest.high)}<br>安値 ${number(nearest.low)}　終値 ${number(nearest.close)}<br>出来高 ${number(nearest.volume,0)}`;el.tooltip.classList.remove("hidden");const rect=el.wrap.getBoundingClientRect();el.tooltip.style.left=Math.max(0,Math.min(rect.width-el.tooltip.offsetWidth-4,event.clientX-rect.left+15))+"px";el.tooltip.style.top=Math.max(0,event.clientY-rect.top-el.tooltip.offsetHeight-12)+"px";}
/**
 * 機能: ドラッグ状態を解除する。
 * 引数: event {PointerEvent} 解放。
 * 返り値: {undefined} なし。
 */
function onPointerUp(event){state.drag=null;if(el.svg.hasPointerCapture(event.pointerId))el.svg.releasePointerCapture(event.pointerId);}
/**
 * 機能: OHLC情報と十字線を隠す。
 * 引数: なし。
 * 返り値: {undefined} なし。
 */
function hideTooltip(){el.tooltip.classList.add("hidden");const line=document.getElementById("crosshair");if(line)line.setAttribute("visibility","hidden");}

// ----------------------------------------
// 初期画面と操作を結び付ける。初期取引は九月二十三日デイのNK225ショート。
for(const session of DATA.sessions){const option=document.createElement("option");option.value=session;option.textContent=sessionLabel(session);el.session.appendChild(option);}el.session.value=state.session;
el.symbol.addEventListener("change",onSelectionChange);el.session.addEventListener("change",onSelectionChange);el.table.addEventListener("click",onTradeClick);el.svg.addEventListener("click",onTradeClick);
document.getElementById("zoom-in").addEventListener("click",onZoomIn);document.getElementById("zoom-out").addEventListener("click",onZoomOut);document.getElementById("view-all").addEventListener("click",onViewAll);document.getElementById("view-trade").addEventListener("click",onViewTrade);
el.svg.addEventListener("pointerdown",onPointerDown);el.svg.addEventListener("pointermove",onPointerMove);el.svg.addEventListener("pointerup",onPointerUp);el.svg.addEventListener("pointercancel",onPointerUp);el.svg.addEventListener("pointerleave",hideTooltip);
renderTable();setFullRange();renderChart();
</script>
</body>
</html>'''


class StructureCheck(HTMLParser):
    """機能: 出力HTMLの必須要素と外部依存の不在を確認する。

    引数: なし。返り値: 構造検査器 (StructureCheck)。
    """

    def __init__(self) -> None:
        """機能: 検査で集計する識別子と外部読込先を初期化する。

        引数: self (StructureCheck)。返り値: なし (None)。
        """
        super().__init__()
        self.ids = []
        self.external = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """機能: 要素識別子と外部スクリプト等の読込指定を収集する。

        引数: tag (str) は要素、attrs (list[tuple[str,str|None]]) は属性。返り値: なし (None)。
        """
        values = dict(attrs)
        if "id" in values:
            self.ids.append(values["id"])
        for key in ("src", "href"):
            if values.get(key, "").startswith(("http:", "https:", "//")):
                self.external.append(values[key])


def validate_html(html: str, payload: dict) -> dict:
    """機能: 描画対象の個数・初期売買・時刻位置と自己完結性を検査する。

    引数: html (str) は出力、payload (dict) は埋込データ。返り値: 検査結果 (dict)。
    """
    parser = StructureCheck()
    parser.feed(html)
    assert len(parser.ids) == len(set(parser.ids)), "識別子が重複しています"
    assert not parser.external, "外部読込先があります"
    assert len(payload["candles"]) == 10 and len(payload["trades"]) == 12
    assert all(payload["candles"].values())
    initial = next(t for t in payload["trades"] if t["symbol"] == "NK225" and t["session"] == "2026-09-23_Day")
    assert initial["id"] == 11 and initial["side"] == -1
    assert initial["entry_price"] == 66910 and initial["exit_price"] == 66800
    assert initial["entry_time"][11:16] == "09:35" and initial["exit_time"][11:16] == "15:35"
    assert "x(trade.entry_time_ms)" in html and "x(trade.exit_time_ms)" in html
    assert all(t["entry_time_ms"] <= t["exit_time_ms"] for t in payload["trades"])
    assert "fetch(" not in html and "XMLHttpRequest" not in html
    assert "__PAYLOAD__" not in html
    return {"判定": "合格", "セッション銘柄組": 10, "取引数": 12, "五分足数": sum(map(len, payload["candles"].values())), "初期画面": "NK225 2026-09-23 デイ：09:35 売り66910→15:35 返済66800", "マーカー": "五分足へ丸めない実際の一分時刻", "外部読込": 0, "ブラウザ確認": "別途実施"}


def main() -> None:
    """機能: 保存版からHTMLを生成し、静的自己検査の結果を保存する。

    引数: なし。返り値: なし (None)。
    """
    payload = load_payload()
    embedded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    html = TEMPLATE.replace("__PAYLOAD__", embedded)
    check = validate_html(html, payload)
    (BASE / "売買ポイント図解.html").write_text(html, encoding="utf-8")
    (BASE / "図解HTML_静的検査.json").write_text(json.dumps(check, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(check, ensure_ascii=False))


if __name__ == "__main__":
    main()
