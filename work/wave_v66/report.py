"""短時間の急傾斜について、入口と売買会計を短く説明する。"""

from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
import pickle
import shutil

import numpy as np

import study


HERE=Path(__file__).resolve().parent
OUT=study.OUT
JST=timezone(timedelta(hours=9))
LABELS={'ACCEL_H03_V020':'3分の急加速','STRAIGHT_H05_V020':'5分の直進',
        'BREAK_H03_V020':'3分の加速＋突破','RAW_ACCEL_S060_V050':'1分の急加速',
        'RAW_STRAIGHT_S060_V050':'1分の直進'}


def money(value: float | None) -> str:
    """機能: 未計測を区別して金額を表示する。

    引数: value(float|None)。返り値: 表示(str)。
    """
    return '—' if value is None else f'{value:,.0f}'


def clock(value: float) -> str:
    """機能: 保存時計を日本時間の時刻へ変換する。

    引数: value(float)。返り値: 表示(str)。
    """
    return datetime.fromtimestamp(value,JST).strftime('%H:%M:%S')


def pct(value: float | None) -> str:
    """機能: 比率を百分率へ変換する。

    引数: value(float|None)。返り値: 表示(str)。
    """
    return '—' if value is None else f'{value*100:.1f}%'


def figure(row: dict,meta: dict,ready: dict,q: dict) -> str:
    """機能: 急加速前後を同じ時間・割合縮尺で図示する。

    引数: row/meta/ready/q(dict)。返り値: SVGと売買説明(str)。
    先の価格は事後図示だけで、検知時に未来の線を参照していない。
    """
    times=ready['time_s'];center=times[row['decision_i']]
    left_time,right_time=center-300.,center+900.
    begin=max(0,int(np.searchsorted(times,left_time)))
    end=min(len(times)-1,int(np.searchsorted(times,right_time,side='right'))-1)
    sample=np.unique(np.r_[np.linspace(begin,end,min(end-begin+1,1600)).astype(int),row['decision_i'],row['entry_i'],row['exit_i']])
    anchor=float(q['mid'][row['decision_i']])
    startx,starty,width,height=75.,22.,865.,280.
    x=lambda i: startx+(times[i]-left_time)/(right_time-left_time)*width
    y=lambda p: starty+(.0025-(p/anchor-1.))/.005*height
    line=' '.join(f'{x(i):.2f},{y(q["mid"][i]):.2f}' for i in sample)
    grid=[]
    for offset in (-.0025,-.00125,0.,.00125,.0025):
        yy=y(anchor*(1+offset))
        grid.append(f'<path d="M{startx},{yy:.1f}h{width}" stroke="#30415a"/><text x="67" y="{yy+4:.1f}" fill="#bfccde" text-anchor="end">{offset*100:+.3f}%</text>')
    for offset in (0.,300.,600.,900.,1200.):
        xx=startx+offset/1200.*width
        grid.append(f'<text x="{xx:.1f}" y="326" fill="#bfccde" text-anchor="middle">{clock(left_time+offset)[:5]}</text>')
    markers=[]
    for i,price,name,color in ((row['decision_i'],anchor,'検知','#fbbf24'),
                              (row['entry_i'],row['entry_price'],'新規','#93c5fd'),
                              (row['exit_i'],row['exit_price'],'返済','#fb7185')):
        markers.append(f'<circle cx="{x(i):.1f}" cy="{y(price):.1f}" r="5" fill="{color}"><title>{name} {clock(times[i])} {price}</title></circle>')
    side='買い' if row['side']>0 else '売り'
    title=f'{row["session"]} NK {side} · {clock(row["entry_time"])}→{clock(row["exit_time"])} · {money(row["net"])}円'
    description=f'検知時の1分速度 {meta["slope"]:+.3f}%/分、直進率 {meta["er"]:.2f}。黄＝検知、青＝新規、赤＝返済。'
    return '<figure><figcaption>'+title+'</figcaption><div class="scroll"><svg viewBox="0 0 1000 350" role="img" aria-label="固定縮尺の急加速と売買"><defs><clipPath id="clip'+str(row['entry_seq'])+'"><rect x="75" y="22" width="865" height="280"/></clipPath></defs><rect width="1000" height="350" fill="#101b2b"/>'+''.join(grid)+f'<g clip-path="url(#clip{row["entry_seq"]})"><polyline points="{line}" fill="none" stroke="#c4b5fd" stroke-width="1.5"/>'+''.join(markers)+'</g></svg></div><p class="sub">'+description+'</p></figure>'


def main() -> None:
    """機能: 固定主12条件、全336条件、25場と一回現在確認を公開する。

    引数: なし。返り値: なし(None)。入口・出口の設定を変更しない。
    """
    first=json.loads((HERE/'結果.json').read_text(encoding='utf-8'))
    second=json.loads((HERE/'round2/結果.json').read_text(encoding='utf-8'))
    methods=first['methods']+second['methods']
    scores={m['config']['id']:m for p in (HERE/'入口採点.json',HERE/'round2/入口採点.json') for m in json.loads(p.read_text(encoding='utf-8'))['methods']}
    mids={m['config']['id']:m for m in json.loads((HERE/'判断中値の方向診断.json').read_text(encoding='utf-8'))['methods']}
    primary=[m for m in methods if m['primary']]
    assert len(primary)==12 and len(methods)==336
    public=[]
    for m in primary:
        item={k:v for k,v in m.items() if k!='rows'}
        item['label']=LABELS[m['entry']['id']]+' / '+m['exit']['id']
        item['score']=scores[m['entry']['id']]['summary']
        item['mid_score']=mids[m['entry']['id']]['summary']
        item['weeks']={}
        for symbol in ('TOPIX','NK225'):
            weeks=[]
            for monday in ('2026-09-21','2026-09-28','2026-10-05'):
                start=datetime.fromisoformat(monday).date()
                rows=[r for r in m['rows'] if r['symbol']==symbol and start<=datetime.fromisoformat(r['session'][:10]).date()<start+timedelta(days=7)]
                a=study.exits.summarize(rows)
                weeks.append(dict(label=monday+('週（10/07デイまで）' if monday=='2026-10-05' else '週'),**a))
            item['weeks'][symbol]=weeks
        public.append(item)
    live_path=HERE/'live/現在急傾斜の途中損益.json'
    live=json.loads(live_path.read_text(encoding='utf-8')) if live_path.exists() else None
    live_rows=[]
    if live:
        for m in live['methods']:
            for a in m['accounts']:
                live_rows.append(dict(id=m['config']['id']+'_順',symbol=a['symbol'],session=a['session'],
                    net=a['net'],fees=a['fees'],gross=a['gross'],unrealized=a['unrealized'],wins=a['wins'],losses=a['losses'],trades=a['trades'],
                    long_qty=a['long_qty'],short_qty=a['short_qty'],added=a['追加区間']['net']))
    data=dict(methods=public,live=live_rows)
    study.save(OUT/'表示用集計.json',data)
    # ----------------------------------------
    # 調査の会計・再現資料を作業フォルダへ集約する。
    summaries=[{k:v for k,v in m.items() if k!='rows'} for m in methods]
    study.save(OUT/'全336条件の会計.json',dict(methods=summaries,条件数=336))
    study.save(OUT/'主12条件の全決済.json',dict(methods=[dict(id=m['id'],rows=m['rows']) for m in primary]))
    copies={'実行前固定.json':'1分足の実行前固定.json','round2/実行前固定.json':'5秒足の実行前固定.json',
        '判断中値診断の事前固定.json':'判断中値診断の事前固定.json','audit/急傾斜入口の独立監査.json':'1分入口の独立監査.json',
        'audit/急傾斜192条件と全入口採点の独立監査.json':'192条件の独立監査.json',
        'audit/追加5秒足入口の独立監査.json':'5秒入口の独立監査.json',
        'audit/追加5秒足144条件と全入口採点の独立監査.json':'144条件の独立監査.json',
        'audit/判断中値の独立診断.json':'判断中値の独立診断.json',
        'live/現在急傾斜の途中損益.json':'現在ナイトの途中損益.json',
        'live/現在会計の独立検査.json':'現在会計の独立検査.json',
        'live/現在原本の照合.json':'現在原本の照合.json','live/取得記録.json':'現在の一回取得記録.json',
        'live/候補固定.json':'現在取得前の候補固定.json','live/既知前半と追加区間.json':'現在の既知前半照合.json',
        '時系列選択.json':'前半で選択した条件.json'}
    for old,new in copies.items():
        source=HERE/old
        if source.exists():
            shutil.copyfile(source,OUT/new)
    # ----------------------------------------
    # 角度を比較できるよう二例の時間と価格割合の縮尺をそろえる。
    example=next(m for m in primary if m['id']=='RAW_ACCEL_S060_V050_広幅_順')
    rows=[r for r in example['rows'] if r['symbol']=='NK225' and r['hold_minutes']<=15.]
    chosen=[next(r for r in rows if r['net']<0),next(r for r in rows if r['net']>0)]
    ready=pickle.loads(study.exits.INPUTS.read_bytes());quotes=pickle.loads(study.exits.QUOTES.read_bytes())
    metadata=pickle.loads((HERE/'round2/入口詳細.pkl').read_bytes())
    figures=[]
    for row in chosen:
        key=(row['session'],row['symbol'])
        meta=next(x for x in metadata[key]['RAW_ACCEL_S060_V050'] if x['i']==row['decision_i'])
        figures.append(figure(row,meta,ready[key],quotes[key]))
    options=''.join(f'<option value="{m["id"]}"'+(' selected' if m['id']==example['id'] else '')+'>'+html.escape(m['label'])+'</option>' for m in public)
    embedded=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).replace('</','<\\/')
    source='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>短時間の急傾斜を入口にする検証</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#0c1420;color:#e7eef8;font:16px/1.7 system-ui,'Yu Gothic',sans-serif}main{max-width:1280px;margin:auto;padding:27px}h1{font-size:27px;line-height:1.4}h2{font-size:21px}.card{padding:20px;margin:20px 0;background:#152132;border:1px solid #34485f;border-radius:12px}.sub{font-size:14px;color:#afc0d4}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}td,th{padding:9px;border-bottom:1px solid #354960;text-align:right}td:first-child,th:first-child{text-align:left}thead{background:#20334b}a{color:#93c5fd}select{max-width:100%;color:#e7eef8;background:#0e1928;border:1px solid #637a98;border-radius:6px;padding:8px;font-size:15px}label{display:block;margin:10px 0}figure{margin:18px 0}figcaption{margin:8px 0}svg{min-width:700px;width:100%;font:13px system-ui}summary{cursor:pointer;color:#b8d7ff}code{font-size:13px;overflow-wrap:anywhere}.pos{color:#6ee7b7}.neg{color:#fda4af}@media(max-width:650px){main{padding:14px}.card{padding:14px}h1{font-size:23px}}
</style></head><body><!--
[コンポーネント概要]
#method は結果前に決めた主12条件を選択する領域です。現在損益による再選択はしていません。
#totals は両銘柄の全25場会計、#scores は中値の方向診断と実建値の採点を分離します。
#sessions と #weeks は選択銘柄の全場・週会計です。全て手数料後、無取引場も表示します。
#current は一回取得した現在ナイトの途中会計です。未返済玉の含みと費用を分離します。
.scroll は暗色グラフと表を横スクロールできる領域です。外部通信は行いません。
--><main><p class="sub">作業00063 · 保存25場 · 1分確定足192条件＋生板5秒確定足144条件</p><h1>短時間で強く上がる・下がる場面を取れるか</h1>
<p><strong>急傾斜は機械的に検知できます。ただ、今回の主条件では、検知後の同方向継続に優位性を確認できませんでした。</strong></p>
<p>「直近1分で0.05%以上動き、往復が少なく、直前より加速」のNKは、中値で34/35回が後から0.1%以上順行。対称0.1%の順行が先だったのは17/35回＝48.6%です。実売買は広いトレールで5勝11敗、−45,040円でした。</p>
<section class="card"><h2>45度を、縮尺に依存しない数値へ</h2><p>速度＝価格変化率／分。直進率＝正味の移動／途中の移動の合計。加速＝現在の速度が、直前の同じ長さの区間より強いこと。買い・売りは対称です。ATRは使いません。</p><div class="scroll"><table><thead><tr><th>入口</th><th>強さの基準</th><th>追加確認</th></tr></thead><tbody><tr><td>1分の急加速</td><td>直近1分0.05%以上</td><td>直進率0.7以上・直前の方向速度は現在の半分以下</td></tr><tr><td>1分の直進</td><td>直近1分0.05%以上</td><td>直進率0.7以上</td></tr><tr><td>3分の急加速</td><td>直近3分、毎分0.02%以上</td><td>直進率0.7以上・加速</td></tr><tr><td>5分の直進</td><td>直近5分、毎分0.02%以上</td><td>直進率0.7以上</td></tr><tr><td>3分の加速＋突破</td><td>直近3分、毎分0.02%以上</td><td>直進率・加速・直前高安を1呼値以上突破</td></tr></tbody></table></div><p class="sub">速度は100×log(現在終値／過去終値)÷分数。現在足を除く区間と加速・高安を比較。全条件が0・反対方向から成立へ切り替わった時に検知し、足の公開後の次の原板行で約定します。</p></section>
<section class="card"><h2>入口と出口を選んで確認</h2><label for="method">結果前固定の主条件 <select id="method">'''+options+'''</select></label><p id="rule"></p><div class="scroll"><table id="totals"><thead><tr><th>商品・同時上限</th><th>勝/負取引</th><th>勝率</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>手数料 円</th><th>利益/損失枚数</th><th>平均損益比</th></tr></thead><tbody></tbody></table></div><p class="sub">NKマイクロ20枚、TOPIXミニ10枚を一度に新規。利益・損失は往復費用後、平均損益比は平均利益／平均損失。決済後10分休止、追加なし、当場全返済。無取引は勝ちに数えません。</p><h3>検知後の方向と約定価格を分離</h3><div class="scroll"><table id="scores"><thead><tr><th>銘柄</th><th>約定可能検知数</th><th>中値 0.1%到達</th><th>中値 同幅順行が先</th><th>実建値 0.1%到達</th><th>実建値 同幅順行が先</th></tr></thead><tbody></tbody></table></div><p class="sub">全検知候補を分母にし、検知後から保存場末まで測定。中値は気配差なしの方向診断、実建値は次行ask/bidと返済気配による採点です。どちらも未来の最大値は事後採点専用で、売買には使いません。同じ波の複数検知は独立標本ではありません。</p></section>
<section class="card"><h2>急加速の売買例</h2>'''+''.join(figures)+'''<p class="sub">1分の急加速・広幅の最初の損失例と利益例。横軸20分、縦軸±0.25%の同じ縮尺です。線は中値、売買点は気配約定。目視の角度を変えて結果を良く見せていません。</p></section>
<section class="card"><h2>全セッション・週の収支</h2><label for="symbol">商品 <select id="symbol"><option value="NK225">NKマイクロ20枚</option><option value="TOPIX">TOPIXミニ10枚</option></select></label><div class="scroll"><table id="sessions"><thead><tr><th>セッション</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>手数料 円</th><th>勝/負取引</th><th>利益/損失枚数</th><th>枚数差</th></tr></thead><tbody></tbody></table></div><h3>週合計</h3><div class="scroll"><table id="weeks"><thead><tr><th>週</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>利益/損失枚数</th></tr></thead><tbody></tbody></table></div><p class="sub">全25場は2026/09/21デイ〜10/07デイ。最終週は途中まで。枚数差は利益決済枚数−損失決済枚数で、評価損益の金額とは別です。</p></section>
<section class="card"><h2>現在ナイトを最後に一回確認</h2><p>条件固定後、2026/10/08ナイトを22:38:37まで取得しました。現在の結果で設定を調整していません。</p><div class="scroll"><table id="current"><thead><tr><th>商品</th><th>決済 勝/負</th><th>実現粗損益 円</th><th>発生費用 円</th><th>未返済含み 円</th><th>途中純収支 円</th><th>保有買/売枚数</th></tr></thead><tbody></tbody></table></div><p>1分の直進・短期幅は途中でTOPIX＋28,328円、NK＋3,560円。ただし決済はTOPIX2件・NK1件。保存25場では同じ条件が両銘柄とも赤字でした。</p><p class="sub">未返済玉を架空清算せず、全残玉を返済気配で評価。未執行返済の手数料は未課金。同じ現在場の旧取得前半はなく、状態1回・板各1回だけ取得しました。</p></section>
<details class="card"><summary>全336条件と時間順の比較</summary><p>確定1分足は窓2/3/5/10分、速度0.01/0.02/0.03%/分、速度だけ／直進／加速／突破の4系統。生板5秒確定足は窓60/120秒、速度0.03/0.05/0.08%/分、同じ4系統。正逆方向も同条件で再生しました。</p><p>順方向168条件ではTOPIX黒字6、NK黒字0（赤字150・無取引18）。両銘柄共通黒字は0、逆方向168条件でも共通黒字0。TOPIXの黒字をそのままNKへ適用する優位性は確認できませんでした。</p><p>前半10場だけで両商品10決済以上の条件を選ぶ固定ルールでは、SPEED_H10_V020・広幅が選ばれました。中間10場はTOPIX＋139,052円/NK−244,640円、後半5場はTOPIX−377,540円/NK−67,440円。全25場は過去にも既知で、完全な未見テストとは呼びません。</p><p><a href="全336条件.html">全条件の金額・勝敗</a> · <a href="全336条件の会計.json">全口座と期間会計</a> · <a href="主12条件の全決済.json">主条件の全約定</a> · <a href="前半で選択した条件.json">前半選択の証跡</a></p></details>
<details class="card"><summary>検査と未再現の条件</summary><p>入口は完全な時間グリッド上で計算し、必要足が欠ける時は発火しません。未確定足・未来価格を使わず、次の有効原板行へ注文を進めます。足の公開時に価格が既に逆行していても、後から入口を取り消して成績を良くしていません。</p><p>時刻は原本の最終約定時計CurrentPriceTimeで、受信時刻ではありません。「5秒足」はこの時計での区分です。数量の補充・注文執行側を使う板読みを追加した手法ではなく、板の価格変化で検知しています。</p><p>ラージの気配を小商品の約定代理に使用。小商品実板、通信発注遅延、注文の食い込み・部分約定、証拠金は未再現です。NK片道20枚220円、TOPIX片道10枚418円を新規と返済へ課金しました。</p><p><a href="1分足の実行前固定.json">1分版固定</a> · <a href="5秒足の実行前固定.json">5秒版固定</a> · <a href="192条件の独立監査.json">192条件の独立検算</a> · <a href="144条件の独立監査.json">144条件の独立検算</a> · <a href="判断中値の独立診断.json">方向だけの独立検算</a> · <a href="現在会計の独立検査.json">現在会計の独立検算</a> · <a href="README.md">読む順序と再現</a></p></details><p><a href="../index.html">作業一覧</a></p></main><script>
const data='''+embedded+''';
/**
 * 機能: 金額や未計測を表示文字列へ変換する。
 * @param {number|null} value - 表示値。
 * @param {number} digits - 小数の桁数。
 * @returns {string} 桁区切り表示。
 */
function fmt(value,digits=0){return value===null?'—':value.toLocaleString('ja-JP',{minimumFractionDigits:digits,maximumFractionDigits:digits});}
/**
 * 機能: 比率を百分率へ変換する。
 * @param {number|null} value - 比率。
 * @param {number} digits - 小数の桁数。
 * @returns {string} 百分率表示。
 */
function pct(value,digits=1){return value===null?'—':fmt(value*100,digits)+'%';}
/**
 * 機能: 表のセルを生成する。
 * @param {Array<string|number>} values - セル一覧。
 * @returns {string} 静的会計データの行HTML。
 */
function row(values){return '<tr>'+values.map(v=>'<td>'+v+'</td>').join('')+'</tr>';}
/**
 * 機能: 選択条件と銘柄の全場会計を表示する。
 * @returns {void} 返り値なし。
 */
function render(){
 const m=data.methods.find(x=>x.id===document.getElementById('method').value);
 const symbol=document.getElementById('symbol').value,e=m.exit;
 document.getElementById('rule').textContent=`損切り${pct(e.stop,2)}、順行${pct(e.arm,2)}で追跡開始、追跡幅${pct(e.trail,2)}、最初の利益条件線${pct(e.floor,2)}。`;
 document.querySelector('#totals tbody').innerHTML=['NK225','TOPIX'].map(s=>{const a=m.summary[s];return row([s==='NK225'?'NKマイクロ20枚':'TOPIXミニ10枚',`${a.wins}/${a.losses}`,pct(a.win_rate),fmt(a.profit),fmt(a.loss),fmt(a.net),fmt(a.fees),`${a.win_qty}/${a.loss_qty}`,fmt(a.payoff,2)]);}).join('');
 document.querySelector('#scores tbody').innerHTML=['NK225','TOPIX'].map(s=>{const a=m.score[s],b=m.mid_score[s];return row([s,a.n,pct(b.labels['0.10'].target_rate),pct(b.labels['0.10'].first_rate),pct(a.labels['0.10'].target_rate),pct(a.labels['0.10'].first_rate)]);}).join('');
 document.querySelector('#sessions tbody').innerHTML=m.accounts.filter(a=>a.symbol===symbol).map(a=>row([a.session,fmt(a.profit),fmt(a.loss),fmt(a.net),fmt(a.fees),`${a.wins}/${a.losses}`,`${a.win_qty}/${a.loss_qty}`,a.win_qty-a.loss_qty])).join('');
 document.querySelector('#weeks tbody').innerHTML=m.weeks[symbol].map(a=>row([a.label,fmt(a.profit),fmt(a.loss),fmt(a.net),`${a.win_qty}/${a.loss_qty}`])).join('');
 document.querySelector('#current tbody').innerHTML=data.live.filter(a=>a.id===m.id).map(a=>row([a.symbol,`${a.wins}/${a.losses}`,fmt(a.gross),fmt(a.fees),fmt(a.unrealized),fmt(a.net),`${a.long_qty}/${a.short_qty}`])).join('');
}
document.getElementById('method').addEventListener('change',render);
document.getElementById('symbol').addEventListener('change',render);
render();
</script></body></html>'''
    (OUT/'急傾斜の説明とセッション損益.html').write_text(source,encoding='utf-8')
    # ----------------------------------------
    # 全条件は主案と分け、黒字だけを隠さず各銘柄の勝敗と費用を表示する。
    all_rows=[]
    for m in methods:
        a,b=m['summary']['TOPIX'],m['summary']['NK225']
        cells=[m['id'],'逆方向対照' if m['mirror'] else '順方向',f'{a["wins"]}/{a["trades"]}',money(a['net']),money(a['fees']),
            f'{b["wins"]}/{b["trades"]}',money(b['net']),money(b['fees'])]
        all_rows.append('<tr>'+''.join('<td>'+html.escape(str(v))+'</td>' for v in cells)+'</tr>')
    all_page='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>急傾斜 全336条件</title><style>:root{color-scheme:dark}body{background:#0c1420;color:#e7eef8;font:15px/1.7 system-ui;margin:24px}a{color:#93c5fd}.scroll{overflow:auto}table{border-collapse:collapse;white-space:nowrap}th,td{padding:8px;border-bottom:1px solid #354960;text-align:right}td:first-child,th:first-child{text-align:left}thead{background:#20334b}</style></head><body><!--
[コンポーネント概要]
table は全336条件の25場会計です。方向を反転した対照も全行表示します。
.scroll は表を狭い画面で横へスクロールする領域です。
--><h1>急傾斜 全336条件</h1><p>順方向168・逆方向168。TOPIXミニ10枚／NKマイクロ20枚、往復手数料後。全期間での事後探索結果で、未見成績ではありません。</p><p><a href="急傾斜の説明とセッション損益.html">主案の説明と全セッションへ</a></p><div class="scroll"><table><thead><tr><th>条件ID</th><th>方向</th><th>TOPIX 勝/決済</th><th>TOPIX収支 円</th><th>TOPIX費用 円</th><th>NK 勝/決済</th><th>NK収支 円</th><th>NK費用 円</th></tr></thead><tbody>'''+''.join(all_rows)+'</tbody></table></div></body></html>'
    (OUT/'全336条件.html').write_text(all_page,encoding='utf-8')
    (OUT/'README.md').write_text('''# 短時間の急傾斜を入口にする検証

最初に [急傾斜の説明とセッション損益.html](急傾斜の説明とセッション損益.html) を見てください。

読む順序：数値で定義した急傾斜 → 主12条件の入口採点と費用後損益 → 同じ縮尺の売買例 → 全25セッションと週会計 → 一回取得した現在ナイト。

[全336条件](全336条件.html) は比較資料です。1分足192条件、5秒足144条件を、各段階の損益計算前に固定しました。前段の結果を踏まえた追加段階は別の固定JSONと別コードで保存し、元の結果を変更していません。

入口の中値採点と、次行建値・返済気配の経済的採点を分離しています。未来の価格は採点と図示だけに用い、売買へ渡していません。各商品に片方向の同時上限を適用し、当場で全返済。現在セッションは末尾の架空清算をせず含みを分けています。

再現コード：`../../work/wave_v66/study.py`、`steep_signals.py`、`round2/study_raw.py`、`round2/raw_signals.py`、`mid_diagnostic.py`、`report.py`。初回は各studyをprepare/runの順に実行します。入口キャッシュと結果は作業フォルダ内に保存。既存結果の上書きは拒否します。現在取得は既に1回完了し、再取得を拒否します。

全25保存場は以前にも参照済み。現在確認は2026-10-08ナイト22:38:37まで、状態1回＋板各1回。現在の結果で条件変更・実注文・E01変更はしていません。時計は最終約定時刻で受信時計ではなく、小商品実板・発注遅延・市場への影響は未再現です。
''',encoding='utf-8')
    research=OUT.parent
    index=(research/'index.html').read_text(encoding='utf-8')
    if '<!--00063開始-->' not in index:
        index=index.replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
        article='<!--00063開始--><article class="task latest"><div class="number">作業00063 <span class="badge">最新</span></div><h2>短時間の急傾斜を入口にする検証</h2><p>速度・直進・加速・高安突破。1分足と生板5秒区分の336条件、検知後の方向診断、全25場と一回現在確認。</p><a class="button" href="00063_短時間の急傾斜を入口にする検証/急傾斜の説明とセッション損益.html">急傾斜の説明と損益を開く →</a></article><!--00063終了-->'
        index=index.replace('<!--00062開始-->',article+'<!--00062開始-->')
        index=index.replace('最新00062：候補3の全力新規と0.1%損切り・利益保護トレールを検証。','最新00063：短時間の急傾斜を、方向診断と実売買で検証。')
    index=index.replace('最新作業は00062です。次の作業は00063以降へ追加します。','最新作業は00063です。次の作業は00064以降へ追加します。')
    (research/'index.html').write_text(index,encoding='utf-8')
    readme=(research/'README.md').read_text(encoding='utf-8')
    if '<!--00063案内開始-->' not in readme:
        readme=readme.replace('**最新は00062の','**00062の')
        readme=readme.replace('<!--00062案内開始-->','<!--00063案内開始-->\n**最新は00063の[急傾斜の説明とセッション損益](00063_短時間の急傾斜を入口にする検証/急傾斜の説明とセッション損益.html)。短時間の速度・直進・加速・突破を336条件で検証。方向診断と約定を分離し、25場と一回現在ナイトを掲載。**\n<!--00063案内終了-->\n\n<!--00062案内開始-->')
    readme=readme.replace('今後の新しい作業は `00063_内容`','今後の新しい作業は `00064_内容`')
    (research/'README.md').write_text(readme,encoding='utf-8')
    print('作業00063へ短い説明・全損益・現在確認を保存しました')


if __name__=='__main__':
    main()
