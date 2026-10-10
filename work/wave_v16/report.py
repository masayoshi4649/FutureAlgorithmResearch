"""一週間の固定候補・追加区間・最終保留を暗色の図と日本語で説明する。"""

from __future__ import annotations

import hashlib
import html
import json
from pathlib import Path
import re
import shutil

import numpy as np
import pandas as pd

import reference

WORK,ROOT = reference.OUT,reference.ROOT
DEST = ROOT/'アルゴリズム調査'/'00011_一週間データでの再検証'
PAGE = '一週間データでの再検証.html'
with reference.module_aliases({'data':reference.previous.data}):
    base = reference.source_module(ROOT/'work/wave_v13/report.py','v16_report_parts')
metrics = reference.import_v14('metrics')
money,percent,clean = base.money,base.percent,base.clean


def read_json(name: str, default: object = None) -> object:
    """機能: 保存済みの今回資料だけを読み込む。

    引数: name (str)、default (object)。返り値: JSON値 (object)。
    """
    path = WORK/name
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def ratio(value: float | None) -> str:
    """機能: 欠損比率を無限大やゼロへ誤変換せず表示する。

    引数: value (float|None)。返り値: 表示 (str)。
    """
    return '算出対象なし' if value is None or pd.isna(value) else f'{value:.2f}'


def rules(config: dict, profiles: dict) -> list[str]:
    """機能: 変更していない設定を機械的な入口・出口として説明する。

    引数: config/profiles (dict)。返り値: 日本語説明 (list[str])。
    """
    c = config
    if c.get('engine')=='pair':
        signals = {'ratio_mr':'NT対数比の過去60分平均からの標準化乖離',
            'ratio_mom':'NT対数比の15分変化を直近60分の１分変化標準偏差×√15で割った値',
            'residual_mr':'過去60分のlog(NK)対log(TOPIX)回帰の標準化残差'}
        return [f'方向：{signals[c["family"]]}の絶対値が{c["threshold"]:g}以上。'+('同方向へ入る。' if c['family']=='ratio_mom' else '逆方向へ入る。')+'NT買いはNK買い・TOPIX売り、NT売りは逆。',
            '新規：毎分判定。同時刻ブロック封印後60秒待ち、180秒より古い価格は使用しない。判断より後の各脚の最初の生価格で個別約定する。',
            '枚数：'+c['sizing_name']+'。事前の価格・変動から固定。mini相当と連続枚数は診断専用で、実際のmini板による約定結果ではない。',
            '返済：事前変動による１R損切り、2.5R利確、1.5R順行後は最高益から１R反落で返済判断。120分上限。平均回帰型はゼロ交差でも返済判断。各脚の次の生価格で返済する。',
            '時間：日15:05・夜05:20以降の新規は禁止。日15:35・夜05:50に全返済判断。返済後５分待機。１Rは条件判断の尺度であり、実約定損失を１R以内に保証しない。']
    if c.get('engine')=='grid':
        gap = f'{c["gap_value"]:g}ATR' if c['gap_mode']=='atr' else f'{c["gap_value"]:g}呼値（NK100ポイント、TOPIX５ポイント）'
        entry = {'limit':'下に買い指値・上に売り指値','stop':'上に買い逆指値・下に売り逆指値','mixed':'同位置に指値と逆指値を併設'}[c['entry_kind']]
        direction = {'both':'上下両方向','long':'買い側','short':'売り側'}[c['directions']]
        exits = []
        for field,label in [('initial_stop_gap','個別損切り'),('target_gap','個別利確'),('trail_gap','個別追跡'),
            ('basket_stop_gap','組全体の損失上限'),('basket_target_gap','組全体の利確'),('basket_trail_gap','組全体の追跡'),('session_stop_gap','セッション損失上限')]:
            if c.get(field) is not None: exits.append(f'{label}{c[field]:g}段')
        if c.get('holding_min'): exits.append(f'個別保有{c["holding_min"]:g}分上限')
        if c.get('protect_start_gap'): exits.append(f'{c["protect_start_gap"]:g}段順行後に最大利益の{c["protect_fraction"]*100:g}%を保護')
        return [f'配置：開始20分後の価格を中心に、{gap}間隔。{entry}を{direction}へ展開し最大{c["max_legs"]}枚。',
            '返済：'+'、'.join(exits)+'。価格条件は前行で指定した価格。組合算や時間の判断は次行価格で返済。',
            '再配置：'+('返済価格から順行１段先。' if c['rearm']=='advance' else '同じ新規水準。')+'成立側に留まる間は連続約定させず、反対側へ戻った後の再到達を待つ。'+('損切り後は新規追加停止。' if c.get('disable_add_after_loss') else ''),
            '全玉会計：同じ中心で再配置する一連の取引を１組とする。利益玉だけを勝ちへ分割しない。日15:35・夜05:50に全返済を判断し、その30分前から新規禁止。']
    result = base.rules_for(c,profiles)
    if c['family']=='P11' and c.get('signal_multiplier')==-1:
        result[0]='方向：確定１分足の出来高が直前20分平均の1.5倍以上で、終値が直前20分の最高値＋0.05ATR以上なら売り、最安値−0.05ATR以下なら買い。出来高を伴う突破の方向を反転し、戻りを狙う。'
    if c['id']==reference.FIXED_TARGETS['NK225']:
        result.append('２枚のうち１枚だけが利確しても全体では未完了。丸めを無視すると0.75ATR超の順行で残玉の追跡が初期ストップより強まり、1.5ATR順行で残玉ストップが建値へ達する。')
    if c.get('us_pause'):
        result.append('今回の米国市場開始に対応する日本時間22:15以上23:00未満は新規待機を取り消し、新規を休止。既存建玉の損切り・追跡は続ける。')
    if c['id']==reference.FIXED_TARGETS['TOPIX']:
        result.append('上昇の未反映なら方向を反転し価格−0.5ATRへ売り逆指値、下落の未反映なら価格＋0.5ATRへ買い逆指値。通知だけで入らず、反対方向への実際の到達を待つ。')
    if 'guard' in c:
        result.append('追加の新規停止：'+c['guard']['label']+'。全玉返済後の確定損益で判断し、同セッション内では再開しない。ATR換算の損失は利益も相殺した累積純損益で、負け脚だけの合計ではない。')
    return result


def summarize(cycles: list[dict], frame: pd.DataFrame, method: str, symbol: str, sessions: list[str]) -> dict:
    """機能: 同一方式・同一銘柄を指定区間だけでまとめる。

    引数: cycles (list[dict])、frame (DataFrame)、method/symbol (str)、sessions (list[str])。
    返り値: 指標と原本全行に基づく区間最大下落 (dict)。
    """
    selected = [c for c in cycles if c['method']==method and c['symbol']==symbol and c['session'] in sessions]
    result = metrics.summarize(selected,sessions,'yen')
    subset = frame.loc[(frame['方式']==method)&(frame['銘柄']==symbol)&frame['セッション'].isin(sessions)]
    result['full_dd'] = float(subset['max_drawdown_yen'].max()) if len(subset) else 0.
    cumulative,peak,period_dd=0.,0.,0.
    if '最小評価損益円' in subset and '最大評価損益円' in subset:
        for session in sessions:
            cells=subset.loc[subset['セッション']==session]
            if not len(cells): continue
            row=cells.iloc[0]
            period_dd=max(period_dd,float(row['max_drawdown_yen']),peak-cumulative-float(row['最小評価損益円']))
            peak=max(peak,cumulative+float(row['最大評価損益円']))
            cumulative+=float(row['net_yen'])
        result['period_dd']=period_dd
    else:
        result['period_dd']=result['full_dd']
    ordered = sorted((r['net'] for r in result['sessions']),reverse=True)
    result['without_best_two'] = result['all_net']-sum(ordered[:2])
    return result


def comparison_table(doc: object, entries: list[tuple]) -> None:
    """機能: 損小利大・頻度・全玉収支を同一の列で表示する。

    引数: doc (Document)、entries (list[tuple[str,str,str,dict]])。返り値: なし (None)。
    """
    rows=[]
    for symbol,method,label,m in entries:
        rows.append([symbol,method,label,m['complete_cycles'],percent(m['win_rate']),money(m['avg_win']),
            money(m['avg_loss'],False),ratio(m['payoff_ratio']),ratio(m['profit_factor']),money(m['gross_profit']),
            money(-m['gross_loss']),money(m['all_net']),f'{m["positive_sessions"]}/{m["session_count"]}',money(m['period_dd'],False)])
    doc.table(['対象','方式','区分','完了組','勝率','平均勝額','平均負額','勝/負','PF','組利益合計','組損失合計','全収支','黒字区間','期間全体最大下落'],rows)


def chart_controls() -> str:
    """機能: 暗色チャートの選択・凡例・描画領域を作る。

    引数: なし。返り値: HTML (str)。
    """
    return '''<div class="chart-controls"><label>銘柄<select id="symbol"><option>NK225</option><option>TOPIX</option></select></label><label class="wide">固定条件<select id="method"></select></label><label>セッション<select id="session"></select></label><button id="fixed-choice">前回の候補</button><button id="primary">９区間で選んだ候補</button><button id="pair-chart">NT候補</button><button id="reset">セッション全体</button></div>
<div id="rule" class="chart-rule"></div><div id="chart-summary" class="stats"></div><div class="legend"><span class="green">▲ 買い新規</span><span class="orange">▼ 売り新規</span><span class="blue">● 返済</span><span class="purple">縦線：9/25 03:01の既読境界</span></div><div class="chart-box"><canvas id="price" height="490" aria-label="５分足と売買位置"></canvas><div id="tooltip" class="tooltip"></div></div><div class="chart-box"><canvas id="equity" height="190" aria-label="全建玉評価と確定収支"></canvas></div><p id="chart-note" class="note"></p><div id="trade-table" class="table-wrap"></div>'''


def chart_data(configs: dict,selected: dict,profiles: dict,frame: pd.DataFrame) -> dict:
    """機能: 全体再生の実際の建値を５分足へ載せる。

    引数: configs/selected/profiles (dict)、frame (DataFrame)。返り値: 図データ (dict)。
    """
    trades=[]
    for t in read_json('代表_全取引.json'):
        trades.append(dict(method=t['方式'],symbol=t['銘柄'],session=t['セッション'],
            condition=t.get('条件設定時刻',t['新規時刻']),entry=t['新規時刻'],exit=t['返済評価時刻'],
            ep=t['新規価格'],xp=t['返済評価価格'],side=int(t['方向']),closed=bool(t['返済済み']),pnl=t['収支円'],
            reason=t['返済理由'],leg=int(t.get('脚番号',0))+1,cycle=int(t['サイクル番号'])+1,
            atr=float(t.get('固定ATR') or 0),holding=float(t.get('保有分') or (t['返済評価時刻']-t['新規時刻'])/60),qty=t.get('枚数',1)))
    curves=read_json('代表_資産曲線.json')
    summaries={f'{r["方式"]}|{r["セッション"]}|{r["銘柄"]}':r for r in frame.to_dict('records')}
    for mapping in [curves,summaries]:
        for key,value in list(mapping.items()):
            if key.endswith('|NT'):
                for symbol in reference.SYMBOLS: mapping[key[:-2]+symbol]=value
                mapping.pop(key)
    for key,row in summaries.items():
        method,session,symbol=key.split('|')
        part=[t for t in trades if t['method']==method and t['session']==session and (configs[method].get('engine')=='pair' or t['symbol']==symbol)]
        row.update(closed_count=sum(t['closed'] for t in part),open_count=sum(not t['closed'] for t in part),
            profit_yen=sum(max(0,t['pnl']) for t in part if t['closed']),loss_yen=sum(min(0,t['pnl']) for t in part if t['closed']),
            closed_net_yen=sum(t['pnl'] for t in part if t['closed']),open_yen=sum(t['pnl'] for t in part if not t['closed']),net_yen=sum(t['pnl'] for t in part))
    candles={}
    for session in reference.SESSIONS:
        for symbol in reference.SYMBOLS:
            bars=pd.read_csv(ROOT/f'candle_5min/{symbol}/{session}.csv')
            candles[session+'|'+symbol]=[[pd.Timestamp(r['time']).timestamp(),r['open'],r['high'],r['low'],r['close']] for r in bars.to_dict('records')]
    targets=selected['照合対象']
    methods={}
    for target in targets:
        method,symbol=target['method'],target['symbol']
        if method not in methods:
            methods[method]=dict(label=base.label_for(configs[method]),rules=rules(configs[method],profiles),engine=configs[method].get('engine','single'),symbols=[])
        methods[method]['symbols'].extend(reference.SYMBOLS if symbol=='NT' else [symbol])
    primary={s:r['採用']['method'] for s,r in selected['主候補'].items() if r['採用']}
    return clean(dict(candles=candles,trades=trades,curves=curves,summaries=summaries,methods=methods,
        sessions={s:base.session_label(s)+('【最終保留】' if s==reference.HOLDOUT else '【今回追加】' if s==reference.DEVELOPMENT[-1] else '【既読＋追加】' if s==reference.KNOWN_NIGHT else '【既読】') for s in reference.SESSIONS},
        primary=primary,fixed=reference.FIXED_TARGETS,boundary=pd.Timestamp(reference.KNOWN_CUTOFF).timestamp()))


def script() -> str:
    """機能: 既存描画を今回の銘柄別対象と既読境界へ合わせる。

    引数: なし。返り値: JavaScript (str)。元の描画ファイルは変更しない。
    """
    value=base.SCRIPT
    value=value.replace("['利益',yen","['返済脚の利益',yen").replace("['損失',yen","['返済脚の損失',yen").replace('返済脚／未返済','返済脚／未返済脚')
    value=value.replace("definition.label+' ／ '+definition.rules[0]","(definition.engine==='pair'?'【NT２脚合算】 ':'')+definition.label+' ／ '+definition.rules[0]")
    value=value.replace("+'</td><td>'+timeText(t.entry)","+'</td><td>'+t.qty.toLocaleString('ja-JP',{maximumFractionDigits:4})+'</td><td>'+timeText(t.entry)")
    value=value.replace("['組–脚','方向','新規時刻'","['組–脚','方向','枚数','新規時刻'")
    value=value.replace('t.atr.toFixed(2)',"(t.atr?t.atr.toFixed(2):'—')")
    value=value.replace('...visibleTrades.map(t=>t.exit+120)','...visibleTrades.map(t=>t.exit+120),...(DATA.curves[key()]||[]).map(r=>r[0]+120)')
    value=value.replace('drawEquity(start,end);}',"if(DATA.boundary>=start&&DATA.boundary<=end){const bx=g.X(DATA.boundary);ctx.strokeStyle='#c1a2ff';ctx.setLineDash([5,5]);ctx.beginPath();ctx.moveTo(bx,g.p.t);ctx.lineTo(bx,g.p.b);ctx.stroke();ctx.setLineDash([]);ctx.fillStyle='#c1a2ff';ctx.fillText('今回追加 03:01 →',Math.min(bx+8,g.p.r-150),g.p.t+16);}drawEquity(start,end);}")
    initialization="$('method').innerHTML=Object.entries(DATA.methods).map(([id,value])=>'<option value=\"'+esc(id)+'\">'+esc(id+' ／ '+value.label)+'</option>').join('');"
    value=value.replace(initialization,"refreshMethods(DATA.fixed.NK225);")
    value=value.replace("$('method').value=DATA.primary.NK225;","$('method').value=DATA.fixed.NK225;")
    value=value.replace("$('symbol').addEventListener('change',()=>{$('method').value=DATA.primary[$('symbol').value];update();});","$('symbol').addEventListener('change',()=>{const previous=$('method').value;refreshMethods(DATA.methods[previous]?.engine==='pair'?previous:DATA.fixed[$('symbol').value]);update();});")
    value=value.replace("window.addEventListener('resize',draw);update();","$('fixed-choice').addEventListener('click',()=>{$('method').value=DATA.fixed[$('symbol').value];update();});$('pair-chart').addEventListener('click',()=>{$('method').value=DATA.primary.NT;update();});window.addEventListener('resize',draw);update();")
    helper='''
/**
 * 選択銘柄で検証した条件だけを選択肢に入れる。
 * @param {string} preferred - 優先する条件ID。
 * @returns {void} 返り値なし。
 */
function refreshMethods(preferred){const symbol=$('symbol').value,available=Object.entries(DATA.methods).filter(([id,definition])=>definition.symbols.includes(symbol));$('method').innerHTML=available.map(([id,definition])=>'<option value="'+esc(id)+'">'+esc(id+' ／ '+definition.label)+'</option>').join('');$('method').value=available.some(([id])=>id===preferred)?preferred:available[0][0];}
'''
    disclosure='''
/**
 * 詳細内のアンカー移動前に本文を開き、表示幅でグラフを再描画する。
 * @param {string} hash - 移動先のアンカー。
 * @returns {void} 返り値なし。
 */
function revealDetails(hash){const target=document.getElementById(decodeURIComponent(hash.replace(/^#/,''))),panel=$('full-report');if(target&&panel.contains(target)){panel.open=true;requestAnimationFrame(()=>{draw();target.scrollIntoView({block:'start'});});}}
document.addEventListener('click',event=>{const link=event.target.closest('a[href^="#"]');if(link)revealDetails(link.hash);});
window.addEventListener('hashchange',()=>revealDetails(window.location.hash));
$('full-report').addEventListener('toggle',()=>{if($('full-report').open)requestAnimationFrame(draw);});
if(window.location.hash)revealDetails(window.location.hash);
'''
    return helper+value+disclosure


def short_summary() -> tuple[str,str]:
    """機能: 前回候補の追加部分だけを１枚単位で簡潔に表示する。

    引数: なし。返り値: HTMLとMarkdown (tuple[str,str])。再売買計算はしない。
    """
    trades=read_json('追加_全取引.json')
    values={}
    for symbol,method in reference.FIXED_TARGETS.items():
        part=[t for t in trades if t['方式']==method and t['銘柄']==symbol]
        wins=[t for t in part if t['収支円']>0];losses=[t for t in part if t['収支円']<0]
        profit=sum(t['収支円'] for t in wins);loss=-sum(t['収支円'] for t in losses)
        win_count=sum(t.get('枚数',1) for t in wins);loss_count=sum(t.get('枚数',1) for t in losses)
        values[symbol]=[money(profit),money(-loss),money(profit-loss),f'{win_count:g}枚 ／ {loss_count:g}枚',
            f'{profit/loss:.2f}倍',f'{win_count/loss_count:.2f}倍',money(profit/win_count),money(loss/loss_count,False),f'{(profit/win_count)/(loss/loss_count):.2f}倍']
    labels=['利益合計','損失合計','差引収支','勝ち枚数 ／ 負け枚数','利益合計 ÷ 損失額合計','勝ち枚数 ÷ 負け枚数','１枚の平均利益','１枚の平均損失額','平均利益 ÷ 平均損失額']
    rows=[[label,values['NK225'][i],values['TOPIX'][i]] for i,label in enumerate(labels)]
    title='前回の２候補は、追加データでどうなったか'
    period='対象：9/25 03:01以降のナイト後半＋9/25デイ＋9/25ナイト。条件変更なし。'
    conclusion='負け枚数が多くても、小さい損失を大きな利益で回収できれば成立する。今回の追加分はNK225が−42万円、TOPIXが＋18.5万円（３枚のみ）。'
    note='※ NK225の継続１枚は、前回の含み評価からの増減−１万円を負け１枚として集計。元の建値からの確定利益は＋30万円。費用０・指定価格約定。'
    logic_rows=[
        ['NK225：２枚分割利確','１枚を先に利確し、残り１枚で大きな波を狙う。','初期損切りは２枚分。追加分では勝ち玉の平均6.45万円に対し負け玉は7.43万円で、利益が損失を補えなかった。'],
        ['TOPIX：逆指値で確認＋損切り＋追跡','板の信号後、価格が売買方向へ動いた場合だけ入る。損切り幅を決め、利幅は追跡で伸ばす。','勝ち玉平均10.75万円、負け玉平均３万円。追加３枚では狙った損小利大の形になった。']]
    designs=[
        ['早期ストップ・時間切れ撤退','損切りが増えても、１枚の損失を縮めて総損失を抑える。','細かい損切りが増え過ぎると総損失が膨らむ。'],
        ['分割利確・利益に応じた追跡短縮','一部利益を確保し、残玉の伸びも狙う。','早く取り過ぎると平均利益が下がる。組全体で評価する。'],
        ['順行後の増玉','最初は少量で試し、伸びた場面の利益額を大きくする。','増玉直後の反転に備え、全玉合計の損失上限が必要。'],
        ['逆指値・待機条件による入口の選別','想定方向へ動いたものだけに建玉を持つ。','遅い入口や一時的な反発で損切りが増える場合もある。']]
    principle='金額の収支＝勝ち枚数×勝ち１枚の平均利益−負け枚数×負け１枚の平均損失。枚数比が１を超えることは必須ではない。'
    design_note='以下は設計上の狙い。今回の２方式の成績だけで、各工夫単独の改善効果が証明されたわけではない。'
    html_text='<section id="summary"><h2>'+title+'</h2><p>'+period+'</p>'+base.html_table(['項目','NK225・２枚分割利確','TOPIX・板反応'],rows)+'<p class="callout">'+conclusion+'</p><h3>手法の狙いと、実際の結果</h3>'+base.html_table(['前回候補','狙えるメリット','追加データでの結果'],logic_rows)+'<p class="note">'+note+'</p><details><summary>損小利大を作る工夫を見る</summary><p>'+principle+'</p>'+base.html_table(['工夫','狙えるメリット','確認する点'],designs)+'<p class="note">'+design_note+'</p></details><p><a href="#charts">５分足で売買を見る →</a>　<a href="#rules">入口・出口を見る</a></p></section>'
    md='## '+title+'\n\n'+period+'\n\n'+base.markdown_table(['項目','NK225・２枚分割利確','TOPIX・板反応'],rows)+'\n\n'+conclusion+'\n\n'+base.markdown_table(['前回候補','狙えるメリット','追加データでの結果'],logic_rows)+'\n\n'+note+'\n\n<details><summary>損小利大を作る工夫を見る</summary>\n\n'+principle+'\n\n'+base.markdown_table(['工夫','狙えるメリット','確認する点'],designs)+'\n\n'+design_note+'\n</details>\n'
    return html_text,md


def document(configs: dict,selected: dict,profiles: dict,cycles: list[dict],frame: pd.DataFrame,extra: list[dict],extra_frame: pd.DataFrame) -> object:
    """機能: 保存結果から章別の検証文書を生成する。

    引数: configs/selected/profiles (dict)、cycles/extra (list[dict])、frame/extra_frame (DataFrame)。
    返り値: 文書 (Document)。条件再選択・市場取得は行わない。
    """
    doc=base.Document()
    doc.section('fixed','１．前回の２候補を、一週間へ延長した結果')
    doc.text('NK225は適応平均の逆方向へ２枚入り分割返済する N03_R-1_L3_U1、TOPIXは板の価格応答差を逆方向へ使う N15_R-1_A4_U0。前回の入口・出口・枚数・時間帯を変更せず、9/21デイから9/25ナイトまでの10セッションで検証した。')
    doc.text('最終の9/25ナイトは、過去９セッションで候補を固定するまで損益を計算せず保留した。現在APIには接続せず、今回揃った保存データだけを使用した。','callout')
    fixed_extra={s:summarize(extra,extra_frame,m,s,reference.SESSIONS[7:]) for s,m in reference.FIXED_TARGETS.items()}
    fixed_last={s:summarize(cycles,frame,m,s,[reference.HOLDOUT]) for s,m in reference.FIXED_TARGETS.items()}
    doc.text(f'前回候補の追加部分はNK225が{money(fixed_extra["NK225"]["all_net"])}、TOPIXが{money(fixed_extra["TOPIX"]["all_net"])}。最終保留夜だけならNK225{money(fixed_last["NK225"]["all_net"])}、TOPIX{money(fixed_last["TOPIX"]["all_net"])}だった。TOPIXは追加データでも利益が残ったが、追加の完了は{fixed_extra["TOPIX"]["complete_cycles"]}組、最終夜は{fixed_last["TOPIX"]["complete_cycles"]}組。継続検証する候補と、安定した規則の確立を区別する。','callout')
    entries=[]
    for symbol,method in reference.FIXED_TARGETS.items():
        for label,cs,fr,sessions in [('従来の７区間',cycles,frame,reference.TRAIN),('今回の追加部分',extra,extra_frame,reference.SESSIONS[7:]),('最終保留１区間',cycles,frame,[reference.HOLDOUT]),('週10区間・参考',cycles,frame,reference.SESSIONS)]:
            entries.append((symbol,method,label,summarize(cs,fr,method,symbol,sessions)))
    comparison_table(doc,entries)
    doc.text('「今回の追加部分」は9/24ナイトの03:01以降＋9/25デイ＋9/25ナイト。最終保留１区間はその内数で、足し合わせない。前半から保有した玉は03:01直前の時価評価を引き、新しい利益へ過去の含み益を重ねない。','note')
    doc.text('平均勝額・平均負額・PFは全玉返済済みの組単位。NK225の２枚も１組として数える。NK225は１ポイント1,000円、TOPIXは10,000円で、銘柄を跨いだ円利益ランキングは作らない。費用０・指定価格約定という前提は維持している。')
    doc.end()
    doc.section('boundary','２．前回未返済だった玉と、追加データの扱い')
    previous=ROOT/'work/wave_v15/結果_全体.json'
    if previous.exists():
        old=json.loads(previous.read_text(encoding='utf-8'))
        rows=[]
        for cell in old:
            for trade in cell['trades']:
                if trade['返済済み']: continue
                matches=[t for t in read_json('代表_全取引.json') if t['方式']==cell['方式'] and t['銘柄']==cell['銘柄'] and t['セッション']==cell['セッション'] and t['サイクル番号']==trade['サイクル番号'] and t['脚番号']==trade['脚番号']]
                if len(matches)!=1: continue
                t=matches[0]
                rows.append([cell['銘柄'],trade['新規価格'],money(trade['収支円']),pd.Timestamp(t['返済評価時刻'],unit='s',tz='UTC').tz_convert('Asia/Tokyo').strftime('%m/%d %H:%M:%S'),t['返済評価価格'],money(t['収支円']),money(t['収支円']-trade['収支円']),t['返済理由']])
        doc.table(['対象','本来の新規価格','前回末尾の含み','実際の返済時刻','返済価格','この脚の確定収支','前回評価からの増減','理由'],rows)
    doc.table(['区間','今回の用途'],[[base.session_label(s),'過去研究で既読' if s in reference.TRAIN else '03:01未満は既読、以後は今回追加' if s==reference.KNOWN_NIGHT else '開発側へ今回追加' if s!=reference.HOLDOUT else '条件固定後に一回評価する最終保留'] for s in reference.SESSIONS])
    doc.text('同一ナイトの前半からの継続玉は、場またぎではない。すべての方式でセッション内全返済の制約を保つ。最終夜は保存履歴の未読照合であり、実注文の実績ではない。')
    doc.end()
    doc.section('selected','３．９区間で再選択し、最後の夜で答え合わせ')
    doc.text('11,253条件を先頭９区間だけで再評価した。因果性監査で N17 の過去信号が入力末尾の長さにより変わる問題が１件見つかり、同処理を共有する N18 と合わせ２系統528条件を採用対象から除外した。N18自体の不一致は今回の境界では観測していない。NTのmini相当・連続枚数18条件も従来どおり診断専用。損小利大の資格・順位規則は前回のものを維持し、最後の夜を見て主候補を差し替えていない。')
    entries=[]
    for symbol,record in selected['主候補'].items():
        if not record['採用']: continue
        method=record['採用']['method']
        for label,sessions in [('開発９区間',reference.DEVELOPMENT),('最終保留１区間',[reference.HOLDOUT]),('週10区間・参考',reference.SESSIONS)]:
            entries.append((symbol,method,label,summarize(cycles,frame,method,symbol,sessions)))
    comparison_table(doc,entries)
    doc.text('全週の数字が良くても、選択に使った９区間が含まれる。独立した答え合わせは最後の１区間であり、そこで１回勝つことも安定性の証明にはならない。')
    doc.end()
    doc.section('ideas','４．試した思想ごとの結果')
    doc.text('予測だけ、予測と建玉管理、方向を予測しない注文、有限格子、NTペアを分けて読む。思想ごとの代表も最終夜の開封前に固定した。')
    representatives=selected.get('思想別代表',[])
    if isinstance(representatives,dict): representatives=list(representatives.values())
    for record in representatives:
        if not record.get('採用'): continue
        choice=record['採用'];method=choice['method'];symbol=record.get('銘柄',choice['symbol']);idea=record.get('思想',configs[method]['philosophy'])
        doc.parts.append('<h3>'+html.escape(symbol+'：'+idea)+'</h3>');doc.markdown.append('\n### '+symbol+'：'+idea+'\n')
        doc.text(base.PHILOSOPHY_TEXT.get(idea,{'サイクル損失で新規を停止':'損失が続いたら全返済後の新規を停止し、そのセッションで損失を積み上げない。','有限格子と全建玉管理':'格子での小幅利確と残った損失玉を同じ組にまとめ、全玉の損失上限・追跡・時間制限を比較する。','NTペアと整数枚ヘッジ':'相対価格の方向と整数枚による共通方向の残りを分解し、枚数方式を比較する。'}.get(idea,idea)))
        comparison_table(doc,[(symbol,method,label,summarize(cycles,frame,method,symbol,sessions)) for label,sessions in [('開発９',reference.DEVELOPMENT),('最終保留',[reference.HOLDOUT])]])
        doc.text('選択時の判定：'+record.get('判定','記録参照')+'。')
    doc.parts.append('<h3>手動例に近い格子を、同じ条件のまま比較</h3>');doc.markdown.append('\n### 手動例に近い格子を、同じ条件のまま比較\n')
    doc.text('TOPIX５ポイント刻みで利益玉を返済・再配置する格子、同位置に指値と逆指値を併設する格子、全玉合算の追跡と90分の保有上限を持つ逆指値格子を比較する。裁量の利確そのものは、既定幅の機械条件で代理している。')
    grid_rows=[]
    for symbol in reference.SYMBOLS:
        for method in ['G01_T10','G15_T10','G16_A10']:
            for label,sessions in [('週10・参考',reference.SESSIONS),('最終保留',[reference.HOLDOUT])]:
                grid_rows.append((symbol,method,label,summarize(cycles,frame,method,symbol,sessions)))
    comparison_table(doc,grid_rows)
    doc.parts.append('<h3>NT：相対価格の利益と、枚数差の影響を分ける</h3>');doc.markdown.append('\n### NT：相対価格の利益と、枚数差の影響を分ける\n')
    nt_rows=[]
    for target in selected['照合対象']:
        if target['symbol']!='NT': continue
        method=target['method'];part=[c for c in cycles if c['method']==method and c['symbol']=='NT']
        r=metrics.summarize(part,reference.SESSIONS,'r')
        nt_rows.append([method,money(sum(c['net_yen'] for c in part)),money(sum(c['relative_yen'] for c in part)),
            money(sum(c['common_residual_yen'] for c in part)),percent(float(np.mean([c['relative_mismatch'] for c in part]))) if part else '—',
            f'{r["all_net"]:.2f}R',ratio(r['payoff_ratio']),ratio(r['profit_factor'])])
    doc.table(['方式','週収支','相対変動の寄与','共通方向の元本差寄与','平均元本差率','予定リスク換算収支','Rの勝/負','RのPF'],nt_rows)
    doc.text('相対変動と共通方向の寄与を足すと円収支になる。元本差には整数丸めと両脚約定時刻の差が含まれ、β方式では意図的なβ調整も含む。これを全て端数誤差と呼ばない。１Rは実際の数量による事前の10分変動尺度であり、保証損失や証拠金利益率ではない。NTの円額を単独１枚と横並び順位付けしない。')
    doc.end()
    doc.section('rules','５．入口・出口と、持つ時間')
    shown=set()
    targets=[dict(method=m,symbol=s) for s,m in reference.FIXED_TARGETS.items()]+[dict(method=r['採用']['method'],symbol=s) for s,r in selected['主候補'].items() if r['採用']]
    for target in targets:
        method,symbol=target['method'],target['symbol']
        if (method,symbol) in shown: continue
        shown.add((method,symbol));doc.method(symbol+'：'+method,rules(configs[method],profiles))
        part=[c for c in cycles if c['method']==method and c['symbol']==symbol and c['complete']]
        rows=[]
        for label,cs in [('全取引',part),('勝ち組',[c for c in part if c['net_yen']>0]),('負け組',[c for c in part if c['net_yen']<0])]:
            values=[(c['exit_time_s']-c['entry_time_s'])/60 for c in cs if 'entry_time_s' in c]
            rows.append([label,len(cs),f'{np.median(values):.1f}分' if values else '—',f'{max(values):.1f}分' if values else '—'])
        doc.table(['区分','完了組','保有時間中央値','最長保有'],rows)
    doc.text('ATRはその時点で利用可能な確定５分足から計算し、注文幅を採用時点で固定する。未来の足や保有後のATRへ置き換えない。保有時間は全玉を返済するまでで、固定の目標時間ではない。')
    doc.end()
    doc.section('charts','６．５分足と、実際のエントリー・イグジット')
    doc.text('初期表示は前回候補の最終保留夜。銘柄とセッションを切り替え、前回候補と９区間選択候補を比較できる。NTは両銘柄の脚を切り替え、下段は常にペア全体を表示する。')
    doc.parts.append(chart_controls());doc.markdown.append('[５分足と全脚の売買図]('+PAGE+'#charts)\n')
    doc.text('追加区間の会計に使った時価への付替えは、新規マーカーへ使用しない。矢印は本来の新規、丸は実際の返済。薄灰線は確定損益、青線は含みを含む全玉評価。評価線は約１分へ間引いた描画で、表の最大下落は間引かない原本全行から算出する。','note')
    doc.end()
    doc.section('sessions','７．固定候補のセッション別：利益・損失・収支')
    for symbol,method in dict.fromkeys((t['symbol'],t['method']) for t in targets):
        doc.parts.append('<h3>'+html.escape(symbol+'：'+method)+'</h3>');doc.markdown.append('\n### '+symbol+'：'+method+'\n')
        rows=[]
        for session in reference.SESSIONS:
            m=summarize(cycles,frame,method,symbol,[session])
            rows.append([base.session_label(session),'最終保留' if session==reference.HOLDOUT else '開発側',m['complete_cycles'],money(m['gross_profit']),money(-m['gross_loss']),money(m['all_net']),money(m['all_open_net']),ratio(m['payoff_ratio']),ratio(m['profit_factor']),money(m['full_dd'],False)])
        doc.table(['セッション','用途','完了組','組利益','組損失','収支','未返済評価','勝/負','PF','全玉最大下落'],rows)
    doc.text('組利益・組損失は同じ組の複数脚を相殺した後の分類。図の「返済脚の利益・損失」とは単位が違うが、純収支は一致する。最大下落は原本の各行で計算した含み込みの値。第１・３章の期間全体最大下落は、セッションが変わっても過去の確定収支を累積して計算する。建玉は持ち越さない。')
    doc.end()
    doc.section('sensitivity','８．最高利益の区間を取り除いても残るか')
    rows=[]
    for symbol,method in dict.fromkeys((t['symbol'],t['method']) for t in targets):
        m=summarize(cycles,frame,method,symbol,reference.SESSIONS)
        rows.append([symbol,method,money(m['all_net']),money(m['net_without_best_session']),money(m['without_best_two']),money(m['session_worst']),money(m['worst_cycle']),f'{m["positive_sessions"]}/10'])
    doc.table(['対象','方式','週収支','最高１区間を除く','最高２区間を除く','最悪セッション','最悪サイクル','黒字区間'],rows)
    doc.text('最高２区間を除く値は、大きな波１〜２回への依存を見る感度診断であり、最後の夜を見た後の候補変更には使っていない。平均勝負比が大きくても、勝つ回数が足りなければPFは１未満になる。')
    doc.end()
    doc.section('walk','９．毎回、過去だけで選び直した場合')
    path=WORK/'時間順実評価.csv'
    if not path.exists(): path=WORK/'時間順の実評価.csv'
    if path.exists():
        walk=pd.read_csv(path)
        net_column='cycle_all_net' if 'cycle_all_net' in walk else 'net_yen'
        doc.table(['対象','学習区間数','次の区間','選んだ条件','次区間の収支','勝/負','PF'],[[r['銘柄'],r.get('学習数',r.get('train_count','')),base.session_label(r['評価']),r['方式'],money(r[net_column]),ratio(r.get('cycle_payoff_ratio')),ratio(r.get('cycle_profit_factor'))] for r in walk.to_dict('records')])
        doc.table(['対象','次区間収支の合計','黒字／評価区間'],[[s,money(g[net_column].sum()),f'{(g[net_column]>0).sum()}/{len(g)}'] for s,g in walk.groupby('銘柄',sort=False)])
    doc.text('先頭３区間で選び４番目を評価し、以降も直前までだけで選ぶ。今回判明した N17・N18 の因果性問題は各時点の選択でも除外したため、過去報告の時間順選択と採用条件が変わることがある。最後に選んだ良い候補を過去全体へ当てた値とは異なる。既読区間を含むため、研究全体として完全未読の成績とも区別する。')
    doc.end()
    doc.section('audit','10．原本・固定記録・独立監査')
    doc.text('再評価集合は11,253条件。因果性で除外した528条件とNT診断専用18条件を除き、採用可能な候補集合は10,707条件。最終保留の前に主候補、思想別代表、前回固定候補、比較条件を固定した。最終夜の全条件ランキングを作って勝者へ差し替えることはしていない。')
    doc.text('選択資格は完了10組以上、勝ち負け各３組以上、有取引４区間以上、平均勝/負>1、PF>1、過半数区間黒字、最高１区間を除いても補助単位の収支が正。順位は１区間ずつ除外したPFと平均勝/負の最悪値を使い、同銘柄の範囲で決める。')
    doc.text('原本と過去成果は読み取り専用。脚の価格差からの円損益、組への集計、全玉時価評価、既読境界の差分、セッション内返済、条件固定と過去部分不変性を照合した。具体的な検査件数と結果は下記資料に記録する。')
    doc.text('原本は20件、計2,068,610行。時刻欠損7,874行などは既存の固定処理で除外した。保存１分足38本・５分足14本には生CurrentPriceを同時刻集計したOHLCとの不一致があり、今回都合よく修正していない。またCurrentPriceTimeは受信時刻ではないため、実受信時刻に基づく完全なリアルタイム再現を証明したものではない。前回２候補は途中打切り再計算の121信号で不変性を確認した。','note')
    if (WORK/'NT最終保留_独立監査.json').exists():
        doc.text('NTの週最大下落は独立監査で集計上の問題を検出した。描画用に間引いた評価線の極値が使われていたため、原本全行の極値に補正して表示した。売買・セッション収支・各セッションの最大下落・候補選定は変わらない。凍結した取引条件と実行コードは変更していない。','note')
    if (WORK/'報告静的実行検査.json').exists():
        doc.text('表示確認の範囲：生成HTMLの全表示セルを、ローカルの模擬DOM・Canvasで実行して数値、行数、描画座標、リンクを検査した。ブラウザーでローカルHTMLを開く操作はBrowser UseのURLポリシーに拒否されたため、実画面での目視確認は行えていない。別の経路で迂回していない。','note')
    for path in sorted(WORK.iterdir()):
        if path.suffix in ['.md','.json'] and any(key in path.name for key in ['監査','検査','記録','計画','棚卸','一致','凍結']):
            doc.parts.append('<p><a href="資料/'+html.escape(path.name)+'">'+html.escape(path.name)+'</a></p>')
            doc.markdown.append('['+path.name+'](資料/'+path.name+')\n')
    doc.text('今回の利益は手数料・スリッページ・気配差を控除しない指定価格約定の結果。これはユーザー指定の比較前提であり、現実の約定品質を実証した値ではない。一週間には共通の市場環境が含まれ、サイクル数を独立した日数と同一視しない。')
    doc.end()
    return doc


def navigation() -> None:
    """機能: 最新の入口だけを更新し、過去作業のリンクを残す。

    引数: なし。返り値: なし (None)。
    """
    folder=DEST.name
    path=DEST.parent/'README.md';value=path.read_text(encoding='utf-8')
    value=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00011の[一週間データでの再検証]({folder}/{PAGE})です。先頭の短い表で、前回２候補の追加データだけを比較します。**',value,count=1)
    value=re.sub(r'^\| `00011_.*\n','',value,flags=re.M).replace('`00010_候補２方式の現在セッション再生`（最新）','`00010_候補２方式の現在セッション再生`')
    row=f'| `{folder}`（最新） | 前回２候補と11,253条件の週再検証、最終保留夜 | [５分足と結果]({folder}/{PAGE}) | [結果]({folder}/検証結果.md)・[案内]({folder}/README.md) |\n'
    value=value.replace('| --- | --- | --- | --- |\n','| --- | --- | --- | --- |\n'+row,1).replace('`00011_内容`','`00012_内容`')
    path.write_text(value,encoding='utf-8')
    path=DEST.parent/'index.html';value=path.read_text(encoding='utf-8')
    value=re.sub(r'\s*<!--00011開始-->.*?<!--00011終了-->','',value,flags=re.S)
    value=value.replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
    value=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新資料は、前回２候補の追加分を短い表で比較します。詳しい検証と５分足は折りたたんでいます。</p>',value,count=1,flags=re.S)
    value=re.sub(r'<footer>最新作業は.*?</footer>','<footer>最新作業は00011です。過去資料を残し、次の別作業は00012以降へ追加します。</footer>',value,count=1,flags=re.S)
    card=f'''<!--00011開始--><article class="task latest"><div class="number">作業00011 <span class="badge">最新</span></div><h2>一週間データでの再検証</h2><p>前回２候補の追加分だけを、利益・損失・枚数で比較。５分足と詳しい検証も開けます。</p><a class="button" href="{folder}/{PAGE}">結果と５分足売買図を開く →</a><p><a href="{folder}/検証結果.md">検証結果</a> · <a href="{folder}/README.md">読む順序</a></p></article><!--00011終了-->'''
    path.write_text(value.replace('</header>','</header>'+card,1),encoding='utf-8')


def main() -> None:
    """機能: 完成した再生結果から配布用資料を作る。

    引数: なし。返り値: なし (None)。市場データ取得や売買計算を行わない。
    """
    if not (WORK/'最終保留_凍結記録.json').exists(): raise RuntimeError('条件固定記録がありません')
    configs={c['id']:c for c in reference.configs()};selected=read_json('最終選択.json')
    profiles={c['id']:c for c in json.loads((ROOT/'work/wave_v13/信号条件一覧.json').read_text(encoding='utf-8'))}
    cycles=read_json('代表_サイクル.json');frame=pd.read_csv(WORK/'代表_セッション集計.csv')
    extra=read_json('追加_サイクル.json');extra_frame=pd.read_csv(WORK/'追加_セッション集計.csv')
    assert set(frame['セッション'])==set(reference.SESSIONS),'10セッションが揃っていません'
    doc=document(configs,selected,profiles,cycles,frame,extra,extra_frame)
    chart=chart_data(configs,selected,profiles,frame)
    summary_html,summary_md=short_summary()
    DEST.mkdir(parents=True,exist_ok=True);materials=DEST/'資料';materials.mkdir(exist_ok=True)
    for path in WORK.iterdir():
        if path.is_file() and path.suffix in ['.py','.md','.csv','.json']: shutil.copy2(path,materials/path.name)
    payload=json.dumps(chart,ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('</','<\\/')
    page='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>一週間データでの再検証｜00011</title><style>'''+base.CSS+'''</style></head><body>
<!--
[コンポーネント概要]
本文は前回固定候補・開発９区間の再選択・最終保留１区間を区別する調査資料です。
#symbol/#method/#session は表示する銘柄・条件・セッションを選択します。
#fixed-choice は前回候補、#primary は今回９区間選択、#pair-chart はNT候補へ移ります。
#price は５分足と実際の新規返済位置、#equity は含みを含む全玉評価です。
#trade-table は各脚を表示し、行を押すとその取引へ拡大します。外部通信はしません。
--><main><header style="padding:18px 25px;margin-bottom:12px"><div class="eyebrow">作業00011 ／ 追加データだけの比較</div><h1 style="font-size:28px;margin:6px 0">前回の２候補を再検証</h1></header>'''+summary_html+'''<details id="full-report"><summary>詳しい検証・５分足・全週成績を開く</summary><p class="note">先頭表は１枚単位。従来のサイクル単位の平均勝負比（NK225 1.06倍／TOPIX 3.58倍）は、同時に入った全玉を相殺してから数えるため異なります。</p><nav><a href="#charts">５分足</a><a href="#rules">入口・出口</a><a href="#sessions">セッション別</a><a href="#audit">監査</a></nav>'''+''.join(doc.parts)+'''</details><footer><a href="../index.html">全作業の一覧</a> ／ 費用０・指定価格約定。実注文なし。</footer></main><script type="application/json" id="data">'''+payload+'''</script><script>'''+script()+'''</script></body></html>'''
    (DEST/PAGE).write_text(page,encoding='utf-8')
    (DEST/'検証結果.md').write_text('# 一週間データでの再検証\n\n'+summary_md+'\n[５分足で売買を見る]('+PAGE+'#charts)\n\n<details><summary>詳細な検証を開く</summary>\n\n'+'\n'.join(doc.markdown)+'\n</details>\n',encoding='utf-8')
    (DEST/'README.md').write_text(f'''# 00011 一週間データでの再検証

**最初に見るファイル：[検証結果と５分足図]({PAGE})**

読む順序：

1. 最初の表で、前回２候補の追加分の利益・損失・枚数を確認する。
2. 必要なら「５分足で売買を見る」を押す。詳細は自動で開く。
3. 全週成績・再選択・監査は、閉じた「詳しい検証」内に残している。

先頭表は１枚単位。追加期間は9/25 03:01以降＋9/25デイ＋9/25ナイト。
NK225の継続１枚は前回評価から−１万円として計上する（元の取引の確定利益は＋30万円）。

[文字版](検証結果.md)

<details><summary>再現手順・監査資料</summary>

再生成：`python work/wave_v16/report.py`。資料のコードは参照用コピーです。

売買から全計算を再実行する場合の順序：

1. `python work/wave_v16/details.py --final`
2. `python work/wave_v16/audit_nt_holdout.py`
3. `python work/wave_v16/correct_nt_drawdown.py`
4. `python work/wave_v16/audit_nt_holdout.py`
5. `python work/wave_v16/report.py`

凍結済み `details.py` はNTの区間極値を間引き曲線から出力するため、最初のNT監査で差を記録し、原本全行の極値へ独立補正してから報告します。
現在の配布済み表は補正後です。訂正はNTの極値と期間最大下落だけで、売買・損益・選定は変更していません。
[NT訂正記録](資料/NT期間下落_訂正記録.json) ／ [NT独立監査](資料/NT最終保留_独立監査.json)

</details>
''',encoding='utf-8')
    navigation();(WORK/'表示構文確認.js').write_text(script(),encoding='utf-8')
    print(json.dumps(dict(報告=str(DEST/PAGE),表示方式=len(chart['methods']),表示脚=len(chart['trades']),表示セル=len(chart['summaries']),SHA256=hashlib.sha256((DEST/PAGE).read_bytes()).hexdigest()),ensure_ascii=False))


if __name__=='__main__':
    main()
