"""E01と改修を短い説明・全場会計・売買図で公開する。"""

from collections import defaultdict
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path

import pandas as pd

import study

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = ROOT / 'アルゴリズム調査/00064_E01への回帰と知見を用いた改修'


def selected(data: dict, model: str) -> dict:
    """機能: 前十六場だけを使用し、事前指定の共通候補を選ぶ。

    引数: data(dict)、model(str)。返り値: 選定証跡(dict)。
    """
    candidates = []
    for identifier, result in data[model].items():
        if identifier == 'E01':
            continue
        accounts = result['periods']['前16']
        eligible = all(a['campaigns'] >= 20 and a['active_sessions'] >= 8 and a['net'] > 0
            and a['campaign_payoff'] is not None and a['campaign_payoff'] > 1 for a in accounts.values())
        if eligible:
            candidates.append(dict(id=identifier, score=min(a['mean_r'] for a in accounts.values())))
    candidates.sort(key=lambda a: (-a['score'], a['id']))
    return dict(model=model, 選定=candidates[0]['id'] if candidates else None, 前半だけの順位=candidates,
        全場や後半を見た選び直し=False)


def robustness(rows: list, names: list, symbol: str) -> dict:
    """機能: 日単位の利益集中と連続赤字を追加診断する。

    引数: rows(list)、names(list[str])、symbol(str)。返り値: 診断(dict)。
    """
    subset = [r for r in rows if r['session'] in names and r['symbol'] == symbol]
    days = defaultdict(float)
    for row in subset:
        days[row['session'][:10]] += row['net']
    best = max(days, key=days.get)
    streak, longest = 0, 0
    cumulative, peak, drawdown = 0., 0., 0.
    for row in sorted(subset, key=lambda r: r['session']):
        streak = streak + 1 if row['net'] < 0 else 0
        longest = max(longest, streak)
        cumulative += row['net']
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return dict(最大利益日=best, 当日利益=days[best], 最大利益日を除く収支=sum(days.values()) - days[best],
        最大赤字連続場数=longest, 場末収支の最大下落=drawdown)


def entry_decomposition(base: dict, modified: dict) -> dict:
    """機能: 同一の実入口・消えた入口・新しく生じた入口に収支差を分解する。

    引数: base/modified(dict)。返り値: 銘柄別分解(dict)。
    """
    def campaigns(result: dict, symbol: str) -> dict:
        """機能: 元建行・方向・価格・枚数・ATRが一致する組を識別する。

        引数: result(dict)、symbol(str)。返り値: 識別子と組収支(dict)。
        """
        values = {}
        for ledger in result['ledgers']:
            if ledger['symbol'] != symbol:
                continue
            cycles = {int(c[0]): c for c in ledger['cycles']}
            for order in ledger['orders']:
                if order[7] != 1:
                    continue
                cid = int(order[2])
                c = cycles[cid]
                key = (ledger['session'], int(order[0]), int(order[3]), order[5], order[4], c[5])
                assert key not in values
                values[key] = sum(t['収支'] for t in ledger['trades'] if t['組'] == cid)
        return values
    output = {}
    for symbol in study.SYMBOLS:
        a, b = campaigns(base, symbol), campaigns(modified, symbol)
        common, removed, added = set(a) & set(b), set(a) - set(b), set(b) - set(a)
        same_delta = sum(b[k] - a[k] for k in common)
        removed_net = sum(a[k] for k in removed)
        added_net = sum(b[k] for k in added)
        expected = sum(b.values()) - sum(a.values())
        assert abs(expected - (same_delta - removed_net + added_net)) < 1e-5
        output[symbol] = dict(共通入口=len(common), 消えた入口=len(removed), 新しい入口=len(added),
            消えた勝ち組=sum(a[k] > 0 for k in removed), 消えた負け組=sum(a[k] < 0 for k in removed),
            消えた組の元収支=removed_net, 新しい組の収支=added_net, 共通入口の出口差=same_delta, 改修収支差=expected)
    return output


def public_data(data: dict) -> dict:
    """機能: HTML表示用に会計・図の素材と誤読防止の補足をまとめる。

    引数: data(dict)。返り値: 表示データ(dict)。
    """
    fixed = study.read(HERE / '事前固定.json')
    display = dict(条件=study.replay.catalog(), 固定=fixed, 選定={m: selected(data, m) for m in data}, 結果={}, 足={})
    for model, methods in data.items():
        display['結果'][model] = {}
        for identifier, result in methods.items():
            public = {key: result[key] for key in ('variant', 'periods', 'rows')}
            public['頑健性'] = {period: {s: robustness(result['rows'], names, s) for s in study.SYMBOLS}
                for period, names in [('全28', fixed['全セッション']), ('後12', fixed['後12'])]}
            public['入口差'] = entry_decomposition(methods['E01'], result)
            public['orders'] = {l['session'] + '|' + l['symbol']: l['orders'] for l in result['ledgers']}
            display['結果'][model][identifier] = public
    for symbol in study.SYMBOLS:
        for session in fixed['全セッション']:
            frame = pd.read_csv(ROOT / 'candle_5min' / symbol / (session + '.csv'))
            display['足'][session + '|' + symbol] = [[datetime.fromisoformat(row.time).timestamp(),
                float(row.open), float(row.high), float(row.low), float(row.close)] for row in frame.itertuples()]
    quote = HERE / 'theory/気配価格置換の集計.json'
    if quote.exists():
        value = study.read(quote)
        display['気配表示'] = {model: {r['variant']['id']: {
            s: dict(complete=r['periods']['全28'][s]['complete'], net=r['periods']['全28'][s]['net'],
                delta=r['periods']['全28'][s]['quote_net_change']) for s in study.SYMBOLS}
            for r in value['methods'] if r['origin_model'] == model} for model in ('specified', 'observed')}
    return display


def document(data: dict, all_conditions: bool = False) -> str:
    """機能: 外部通信なしのダークHTMLを生成する。

    引数: data(dict)、all_conditions(bool)。返り値: HTML(str)。
    """
    payload = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('</', '<\\/')
    title = '全16改修条件の比較' if all_conditions else 'E01と改修の説明と全セッション損益'
    css = '''
:root{color-scheme:dark;background:#0b111b;color:#e3ebf7;font-family:Meiryo,"Yu Gothic UI",sans-serif}*{box-sizing:border-box}body{margin:0;line-height:1.65}main{max-width:1240px;margin:auto;padding:32px 22px 60px}h1{font-size:clamp(22px,3vw,32px);margin:8px 0 12px}h2{font-size:21px;margin:0 0 15px}p{margin:8px 0}a{color:#91c5ff}section,.panel{background:#131f30;border:1px solid #31435d;border-radius:12px;padding:22px;margin:20px 0}.note{color:#b4c4da;font-size:13px}.good{color:#77deb4}.bad{color:#ff91a8}.number{font-variant-numeric:tabular-nums;white-space:nowrap}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #31435d;padding:9px;text-align:right;vertical-align:top}th{color:#bfd0e6;background:#192a40}th:first-child,td:first-child{text-align:left}.scroll{overflow-x:auto}select{background:#20344f;color:#eaf3ff;border:1px solid #507395;border-radius:6px;padding:8px;font:inherit}label{display:inline-block;margin:7px 17px 7px 0}.stages{display:grid;grid-template-columns:repeat(3,1fr);gap:14px}.stage{background:#1a2c43;border-radius:8px;padding:13px}.stage strong{color:#aacfff}.pill{font-size:13px;padding:4px 10px;border-radius:7px;background:#203958;color:#c1dcff;display:inline-block}.plot{width:100%;height:auto;display:block;background:#0d1623;border:1px solid #31435d}.brief{background:#192b41;border-left:4px solid #79bbff;padding:16px}summary{cursor:pointer;color:#a4ccff;font-weight:bold}.selected{background:#203b54}button{background:#294768;color:#e7f1ff;border:1px solid #547596;padding:7px 12px;border-radius:6px;cursor:pointer}.legend{color:#aec2db;font-size:13px}@media(max-width:650px){main{padding:20px 12px}.stages{grid-template-columns:1fr}section{padding:15px}td,th{padding:7px}label{font-size:14px}}
'''
    body = '''
<p><a href="../index.html">作業一覧</a> / <a href="README.md">資料案内</a></p>
<span class="pill">00064 · 保存28セッション · 2026/09/21〜10/08 · 手数料込み</span>
<h1>__TITLE__</h1>
<div class="brief"><strong>元E01は黒字候補として残る。改修はR01の「新規時のEMA再確認」が有望。</strong><p>ただし勝率は約55%。後半12場は最大利益日を除くと両銘柄とも赤字で、安定して稼げると断定する段階ではありません。</p></div>
<p class="note">初回TOPIXミニ5枚／日経マイクロ10枚、片方向上限10／20枚。増玉なし。ラージ価格の換算であり、小商品の実約定結果ではありません。</p>
<div class="panel"><label>約定前提 <select id="model"><option value="observed">発動時の観測価格で再運転</option><option value="specified">旧レポートの指定価格で再運転</option></select></label><p class="note">どちらも前行までの条件を次の原本行以降で執行。観測価格版は建値・返済線・次の入口まで再計算します。手数料は新規・返済とも、注文の枚数×片道料金を1円未満切捨てます。</p></div>
<section><h2>元E01と前半だけで選んだ改修</h2><div id="comparison" class="scroll"></div><p class="note">利益・損失は手数料を配賦した部分決済の合計。部分決済勝率と、初回新規から全返済までを一組とする組勝率を分けて表示。1枚平均勝／負＝勝ち決済の利益÷勝ち枚数 ÷（負け決済の損失÷負け枚数）。</p><p id="selection" class="note"></p></section>
<section><h2>何を変えたか</h2><div class="stages"><div class="stage"><strong>入口</strong><p>E01は1分EMA15/60の方向が両銘柄で一致し、30秒の板中値が支持したら、0.25ATRの反発・反落を待って入る。</p></div><div class="stage"><strong>途中</strong><p>1.5ATR進んだ後、新しい2分・30秒の動きが逆なら一度半減。2ATRで元枠の半分を利確。減らした玉は戻さない。</p></div><div class="stage"><strong>出口</strong><p>最初は0.75ATRの組損失枠。1.5ATRから幅3ATRで追跡し、3ATR進めば幅0.75ATRへ。360分又は場末で全返済。</p></div></div><p><strong>R01の変更は入口だけ。</strong>前観測でも両銘柄のEMA差が0.15ATR超、長いEMAの3本傾きが0.02ATR超で入口方向に揃うことを要求。失効を観測したら、次の原本行から待機新規を取り消す。</p><p class="note">E01の方向保持はEMA差が反対になるまで続きます。R01は古い方向のまま入る場面を減らす案です。通常の押し戻しも見送るので、常に改善するとは限りません。</p><details><summary>ATR・注文時計・内部の仮想建玉</summary><p class="note">ATRは確定5分TRを1/12で再帰平滑、3本目から利用し準備時に固定。1分足は開始＋120秒、5分ATRは開始＋360秒、相手指標は更に60秒待つ。EMA60と3本傾きには通常63本必要です。</p><p class="note">通常の仮想建玉と、早い出口用の仮想建玉を並行計算します。実際の保有を減らしても、次回参加を許す時計は通常仮想玉の終了＋5分です。損失枠や建値線はこの仮想玉で計算するため、実玉の最大損失や手数料後ゼロを保証しません。実玉には別途1ATR損失予算があります。</p><p class="note">E01が1.5ATRで始める幅3ATRのトレールは、その瞬間の利益を保護する線ではありません。3ATRに達して幅を短縮するまで、大きい押し戻しを許します。</p></details></section>
<section><h2>他の改修はどうだったか</h2><div id="parts" class="scroll"></div><p class="note">再参加の増加は、取引機会と往復損の双方を増やしました。早い利確は勝率を上げても、大きい利益を削ります。全条件は<a href="全16改修条件.html">別表</a>で確認できます。</p></section>
<section><h2>各セッションの損益</h2><label>手法 <select id="method"></select></label><label>銘柄 <select id="symbol"><option value="TOPIX">TOPIXミニ</option><option value="NK225">日経マイクロ</option></select></label><div id="method-note" class="note"></div><div id="sessions" class="scroll"></div><p id="stability" class="note"></p></section>
<section><h2>5分足で売買を確認</h2><label>セッション <select id="session"></select></label><div id="price-chart"></div><p class="legend">水色○：新規　桃色◇：返済。マーカーに重ねると価格・枚数・理由を表示。板判断と注文執行は足の確定時刻に限定されません。</p><details><summary>売買記録</summary><div id="orders" class="scroll"></div></details></section>
<section><h2>約定価格と安定性の限界</h2><div id="quotes"></div><p class="note">主比較もラージの価格系列です。Goアプリは小商品の価格・呼値、実受信時刻と実約定数量を使うので、この金額の保証にはなりません。今回App/E01は変更していません。</p><p class="note">前16場で選び後12場で測定。ただし過去研究で後半にも既知データが含まれ、完全な未見検証ではありません。新3場の一部には前回の現在確認で見た行もあります。現在APIの追加取得・実注文は0です。</p></section>
<details class="panel"><summary>検証資料</summary><p><a href="報告データ.json">表示データ</a> · <a href="../../work/wave_v67/事前固定.json">16条件の事前固定</a> · <a href="../../work/wave_v67/接続器の因果検査.json">切断・未来変更検査</a> · <a href="../../work/wave_v67/audit/E01と改修全32条件の独立FIFO会計.json">独立会計</a></p><p class="note">旧E01の23場46口座を完全再現。16条件×2約定モデル・1,792口座の注文会計をFIFOで独立検算。追加5場は元指標を切断・未来変更・上下反射・同秒順で検査。原板と保存足には一部OHLC差があるため、比較は元E01と同じ保存足に統一しました。</p><p class="note">参照研究：<a href="https://arxiv.org/abs/1011.6402">最良板の注文フローと価格変化</a>、<a href="https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf">多条件探索と過剰適合</a>。これらは本手法の収益性を証明する資料ではありません。</p></details>
'''.replace('__TITLE__', title)
    js = r'''
const D=__DATA__, $=id=>document.getElementById(id);
const labels={TOPIX:'TOPIXミニ',NK225:'日経マイクロ'};
const remarks={R02:'どちらかの長いEMAが入口方向と逆なら見送る。',R04:'直近5分の二指数同士が反対方向なら見送る。両方とも入口と逆方向の場合は通す。',R09:'出口用の仮想玉の料金前合算建値線を保護。実玉の手数料後ゼロは保証しない。',R10:'出口用仮想玉の終了から5分で再検討。実玉だけが1ATR予算で先に閉じた場合は出口仮想玉を待つ。'};
/**
 * 金額を日本語の桁区切りで表示する。
 * @param {number} v - 金額。
 * @returns {string} 表示文字列。
 */
function money(v){return (v>0?'+':'')+Math.round(v).toLocaleString('ja-JP')+'円';}
/**
 * 符号に応じた金額セルを生成する。
 * @param {number} v - 金額。
 * @returns {string} HTMLセル。
 */
function cell(v){return `<td class="number ${v>0?'good':v<0?'bad':''}">${money(v)}</td>`;}
/**
 * 比率を表示する。
 * @param {number|null} v - 比率。
 * @returns {string} 二桁又は該当なし。
 */
function ratio(v){return v===null?'—':v.toFixed(2);}
/**
 * 日本時間の時刻を表示する。
 * @param {number} t - UNIX秒。
 * @returns {string} 日本時間文字列。
 */
function clock(t){return new Intl.DateTimeFormat('ja-JP',{timeZone:'Asia/Tokyo',hour:'2-digit',minute:'2-digit',second:'2-digit'}).format(new Date(t*1000));}
/**
 * 期間集計の行を生成する。
 * @param {string} id - 手法ID。
 * @param {string} period - 期間。
 * @param {string} symbol - 銘柄。
 * @returns {string} HTML行。
 */
function periodRow(id,period,symbol){const a=D.結果[$('model').value][id].periods[period][symbol];return `<tr><td>${id} / ${labels[symbol]} / ${period}</td>${cell(a.profit)}${cell(-a.loss)}${cell(a.net)}<td>${(100*a.win_rate).toFixed(1)}%</td><td>${ratio(a.lot_payoff)}</td><td>${a.winning_lots} / ${a.losing_lots}</td></tr>`;}
/**
 * 手法の説明と全セッション会計を更新する。
 * @returns {undefined} 表示更新のみ。
 */
function render(){const model=$('model').value,id=$('method').value,symbol=$('symbol').value,methods=D.結果[model],chosen=D.選定[model].選定;
 $('comparison').innerHTML='<table><thead><tr><th>手法・銘柄・期間</th><th>利益</th><th>損失</th><th>収支</th><th>部分決済勝率</th><th>組勝率</th><th>1枚平均勝／負</th><th>勝ち／負け枚数</th></tr></thead><tbody>'+['E01',chosen].filter((v,i,a)=>v&&a.indexOf(v)===i).flatMap(v=>['TOPIX','NK225'].flatMap(s=>['全28','後12'].map(p=>periodRow(v,p,s)))).join('')+'</tbody></table>';
 $('selection').textContent=`前16場の規則による選定：${chosen||'該当なし'}。金額の大小でNKとTOPIXを単純比較せず、各銘柄の初回数量×ATRで割った組損益の弱い側を比較しました。`;
 const parts=['R01','R05','R06','R07','R08','R09','R10','R11'];
 $('parts').innerHTML='<table><thead><tr><th>改修</th><th>TOPIX全28</th><th>NK全28</th><th>TOPIX後12</th><th>NK後12</th></tr></thead><tbody>'+parts.map(v=>`<tr><td>${v} ${methods[v].variant.name}<br><small>${remarks[v]||''}</small></td>`+['全28','後12'].flatMap(p=>['TOPIX','NK225'].map(s=>cell(methods[v].periods[p][s].net))).join('')+'</tr>').join('')+'</tbody></table>';
 const result=methods[id], total=result.periods.全28[symbol];
 $('method-note').textContent=result.variant.name+'。'+(remarks[id]||'')+' 初回'+(symbol==='TOPIX'?5:10)+'枚、増玉なし。';
 $('sessions').innerHTML='<table><thead><tr><th>セッション</th><th>利益</th><th>損失</th><th>収支</th><th>手数料</th><th>勝ち／負け枚数</th></tr></thead><tbody>'+result.rows.filter(r=>r.symbol===symbol).map(r=>`<tr><td>${r.session.replace('_Day',' 日中').replace('_Night',' 夜間')}</td>${cell(r.profit)}${cell(-r.loss)}${cell(r.net)}<td>${r.fees.toLocaleString('ja-JP')}円</td><td>${r.winning_lots} / ${r.losing_lots}</td></tr>`).join('')+`<tr class="selected"><td>全28合計</td>${cell(total.profit)}${cell(-total.loss)}${cell(total.net)}<td>${total.fees.toLocaleString('ja-JP')}円</td><td>${total.winning_lots} / ${total.losing_lots}</td></tr></tbody></table>`;
 const full=result.頑健性.全28[symbol], later=result.頑健性.後12[symbol], diff=result.入口差[symbol];
 $('stability').textContent=`最大利益日を除く収支：全28 ${money(full.最大利益日を除く収支)}、後12 ${money(later.最大利益日を除く収支)}。最大連続赤字 ${full.最大赤字連続場数}場。場内最大資産下落 ${money(-total.max_session_drawdown)}。元E01から消えた入口 ${diff.消えた入口}組（元勝ち${diff.消えた勝ち組}／元負け${diff.消えた負け組}）、新しい入口 ${diff.新しい入口}組。`;
 draw(); quoteTable();
}
/**
 * 5分足と実際の仮想注文を同じ価格軸へ描く。
 * @returns {undefined} SVGと注文表の更新のみ。
 */
function draw(){const key=$('session').value+'|'+$('symbol').value,result=D.結果[$('model').value][$('method').value], bars=D.足[key],orders=result.orders[key];
 const W=1120,H=400,L=80,R=30,T=22,B=45,low=Math.min(...bars.map(b=>b[3]),...orders.map(o=>o[5])),high=Math.max(...bars.map(b=>b[2]),...orders.map(o=>o[5]));const pad=Math.max((high-low)*.07,1),lo=low-pad,hi=high+pad,first=bars[0][0],last=bars[bars.length-1][0]+300;
 const x=t=>L+(t-first)/(last-first)*(W-L-R),y=p=>T+(hi-p)/(hi-lo)*(H-T-B);let svg=`<svg class="plot" viewBox="0 0 ${W} ${H}" role="img" aria-label="5分足と新規返済">`;
 for(let i=0;i<5;i++){let p=lo+(hi-lo)*i/4;svg+=`<line x1="${L}" y1="${y(p)}" x2="${W-R}" y2="${y(p)}" stroke="#2d3e56"/><text x="${L-8}" y="${y(p)+5}" text-anchor="end" fill="#bfd0e5" font-size="13">${p.toFixed($('symbol').value==='TOPIX'?1:0)}</text>`;}
 const cw=Math.max(2,(W-L-R)/bars.length*.6);for(const b of bars){const fill=b[4]>=b[1]?'#73d8b0':'#ff90a5';svg+=`<line x1="${x(b[0]+150)}" y1="${y(b[2])}" x2="${x(b[0]+150)}" y2="${y(b[3])}" stroke="${fill}"/><rect x="${x(b[0]+150)-cw/2}" y="${Math.min(y(b[1]),y(b[4]))}" width="${cw}" height="${Math.max(1,Math.abs(y(b[1])-y(b[4])))}" fill="${fill}"><title>${clock(b[0])} 始${b[1]} 高${b[2]} 安${b[3]} 終${b[4]}</title></rect>`;}
 const reasons={1:'組の損切り',2:'追跡返済',7:'2ATR部分利確',8:'保有期限',9:'場内返済',11:'建値線',30:'悪化半減',32:'実玉損失予算'};const row=result.rows.find(r=>r.session===$('session').value&&r.symbol===$('symbol').value);
 const detail=D.時刻[key];
 for(const o of orders){let xx=x(detail[o[0]]),yy=y(o[5]),caption=`${clock(detail[o[0]])} ${o[7]===1?'新規':'返済'} ${o[3]>0?'買い':'売り'} ${o[4]}枚 @${o[5]} ${reasons[o[6]]||'追跡新規'}`;svg+=o[7]===1?`<circle cx="${xx}" cy="${yy}" r="5" fill="#77d7ff" stroke="#0b1420"><title>${caption}</title></circle>`:`<path d="M${xx},${yy-6} l6,6 l-6,6 l-6,-6Z" fill="#ff91d1" stroke="#0b1420"><title>${caption}</title></path>`;}
 for(let i=0;i<5;i++){let t=first+(last-first)*i/4;svg+=`<text x="${x(t)}" y="${H-16}" text-anchor="middle" fill="#bdcee3" font-size="13">${clock(t).slice(0,5)}</text>`;}svg+='</svg>';$('price-chart').innerHTML=svg;
 $('orders').innerHTML='<table><thead><tr><th>時刻</th><th>新規／返済</th><th>方向</th><th>枚数</th><th>価格</th><th>理由</th></tr></thead><tbody>'+orders.map(o=>`<tr><td>${clock(detail[o[0]])}</td><td>${o[7]===1?'新規':'返済'}</td><td>${o[3]>0?'買い':'売り'}</td><td>${o[4]}</td><td>${o[5]}</td><td>${reasons[o[6]]||'追跡新規'}</td></tr>`).join('')+'</tbody></table>';
}
/**
 * 固定注文の気配価格感度を別枠で表示する。
 * @returns {undefined} 表示更新のみ。
 */
function quoteTable(){if(!D.気配表示){$('quotes').innerHTML='<p class="note">固定した注文を売買気配で価格置換する感度は、別資料へ記録します。発動や再参加を再計算する再運転とは区別します。</p>';return;}
 const ids=['E01',D.選定[$('model').value].選定].filter(Boolean);$('quotes').innerHTML='<p class="note">下表は<strong>注文の時刻・数量を固定</strong>し、買いを売り気配、売りを買い気配で置き換えた感度です。保護線と次の入口を再計算していません。</p><div class="scroll"><table><thead><tr><th>方式</th><th>選択した約定の全28収支</th><th>同じ注文を気配価格へ置換</th><th>価格による収支差</th></tr></thead><tbody>'+ids.flatMap(id=>['TOPIX','NK225'].map(s=>{const q=D.気配表示[$('model').value][id][s];return `<tr><td>${id} ${labels[s]}</td>${cell(D.結果[$('model').value][id].periods.全28[s].net)}${q.complete?cell(q.net):'<td>未採点注文あり</td>'}${q.complete?cell(q.delta):'<td>—</td>'}</tr>`;})).join('')+'</tbody></table></div>';
}
// ----------------------------------------
// 初期選択とイベントを接続し、保存済みデータだけで表示する。
$('method').innerHTML=D.条件.map(v=>`<option value="${v.id}">${v.id} ${v.name}</option>`).join('');$('session').innerHTML=D.固定.全セッション.map(s=>`<option>${s}</option>`).join('');$('session').value=D.固定.全セッション[D.固定.全セッション.length-1];
['model','method','symbol'].forEach(id=>$(id).addEventListener('change',render));$('session').addEventListener('change',draw);render();document.body.dataset.ready='完了';
'''.replace('__DATA__', payload)
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title><style>{css}</style></head><body><!--
[コンポーネント概要]
#model は元の指定価格と観測値再運転の比較を切り替えます。
#method / #symbol / #session は売買方式・商品・保存セッションを指定します。
#comparison / #sessions は手数料後の期間集計と全場損益を表示します。
#price-chart / #orders は5分足の新規返済位置と執行記録を表示します。
#quotes は注文固定の気配価格感度で、再運転とは別に表示します。
外部通信は行いません。
--><main>{body}</main><script>{js}</script></body></html>'''


def main() -> None:
    """機能: 全結果を検証し、主HTMLと十六条件一覧を新番号へ保存する。

    引数: なし。返り値: なし(None)。
    """
    data = {model: {v['id']: study.read(HERE / model / (v['id'] + '.json.gz'))
        for v in study.replay.catalog()} for model in ('specified', 'observed')}
    assert all(len(result['rows']) == 56 for methods in data.values() for result in methods.values())
    public = public_data(data)
    inputs, _, _ = study.load_inputs()
    public['時刻'] = {key[0] + '|' + key[1]: {str(int(o[0])): float(inputs[key]['time_s'][int(o[0])])
        for methods in data.values() for result in methods.values() for ledger in result['ledgers']
        if (ledger['session'], ledger['symbol']) == key for o in ledger['orders']} for key in inputs}
    quote_display = HERE / 'theory/気配感度の表示集計.json'
    if quote_display.exists():
        public['気配表示'] = study.read(quote_display)
    OUT.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(public, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
    (OUT / '報告データ.json').write_bytes(raw)
    (OUT / 'E01と改修の説明と全セッション損益.html').write_text(document(public), encoding='utf8')
    # ----------------------------------------
    # 全条件一覧は詳細本文を増やさず、一つの比較表へ集約する。
    rows = []
    for model, methods in data.items():
        for identifier, result in methods.items():
            cells = ''.join(f'<td>{result["periods"][p][s]["net"]:,.0f}円</td>'
                for p in ('前16', '後12', '全28') for s in study.SYMBOLS)
            explanation = {'R02': 'どちらかの長いEMAが入口と逆なら見送る。',
                'R04': '二指数同士の直近5分の不一致を見送る。',
                'R09': '出口仮想玉の料金前合算建値線。実玉の純損益保護ではない。'}.get(identifier, result['variant']['name'])
            rows.append(f'<tr><td>{model}</td><td>{identifier}</td><td>{html.escape(explanation)}</td>{cells}</tr>')
    all_page = f'''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>全16改修条件</title><style>body{{background:#0b111b;color:#e5edf8;font-family:Meiryo;margin:28px}}a{{color:#a3caff}}table{{border-collapse:collapse;font-size:13px}}td,th{{border:1px solid #31435d;padding:9px}}th{{background:#1a2c43}}.scroll{{overflow:auto}}td{{white-space:nowrap}}</style><h1>全16改修条件</h1><p><a href="E01と改修の説明と全セッション損益.html">説明と全セッション損益へ</a></p><p>specified＝旧指定価格、observed＝発動時の観測値。どちらも手数料込み・ラージ価格換算・初回5/10枚。</p><div class="scroll"><table><thead><tr><th>約定</th><th>ID</th><th>変更</th><th>前16 TOP</th><th>前16 NK</th><th>後12 TOP</th><th>後12 NK</th><th>全28 TOP</th><th>全28 NK</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div></html>'''
    (OUT / '全16改修条件.html').write_text(all_page, encoding='utf8')
    study.save(HERE / '報告選定と安定性.json', dict(選定=public['選定'],
        主2方式={model: {identifier: {k: methods[identifier][k] for k in ('頑健性', '入口差')}
            for identifier in ('E01', 'R01')} for model, methods in public['結果'].items()},
        表示SHA256=hashlib.sha256(raw).hexdigest()))
    print('00064の主HTML・全16条件・表示データを保存しました')


if __name__ == '__main__':
    main()
