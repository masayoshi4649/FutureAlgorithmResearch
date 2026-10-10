"""全力新規・割合トレール検証の短い説明と全セッション会計を作成する。"""

from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
import pickle

import numpy as np

import replay


HERE = Path(__file__).resolve().parent
OUT = replay.OUT
JST = timezone(timedelta(hours=9))


def money(value: float) -> str:
    """機能: 日本円を端数に応じて表示する。

    引数: value(float)。返り値: 桁区切り文字列(str)。
    """
    return f'{value:,.0f}' if abs(value-round(value)) < 1.e-6 else f'{value:,.1f}'


def pct(value: float | None) -> str:
    """機能: 未計測を区別して百分率を表示する。

    引数: value(float|None)。返り値: 表示(str)。
    """
    return '—' if value is None else f'{value*100:.1f}%'


def clock(value: float) -> str:
    """機能: 保存最終約定時計を日本時間へ変換する。

    引数: value(float)。返り値: 時刻文字列(str)。
    """
    return datetime.fromtimestamp(value,JST).strftime('%H:%M:%S')


def account_table(accounts: list[dict], symbol: str) -> str:
    """機能: 全25場の利益・損失・純収支・手数料と決済枚数を表示する。

    引数: accounts(list[dict])、symbol(str)。返り値: HTML表(str)。
    利益・損失は往復費用後の決済を勝敗で分けた金額。
    """
    rows = []
    for a in accounts:
        if a['symbol'] != symbol:
            continue
        cells = [a['session'],money(a['profit']),money(a['loss']),money(a['net']),money(a['fees']),
                 f'{a["wins"]} / {a["losses"]}',f'{a["win_qty"]} / {a["loss_qty"]}',
                 str(a['gates']['holding']+a['gates']['cooldown']+a['gates']['cutoff']+a['gates']['expired'])]
        rows.append('<tr>'+''.join(f'<td>{v}</td>' for v in cells)+'</tr>')
    head = ['セッション','利益 円','損失 円','収支 円','手数料 円','勝 / 負 取引','利益 / 損失 枚数','見送り入口']
    return '<div class="scroll"><table data-accounts="'+symbol+'"><thead><tr>'+''.join(f'<th>{v}</th>' for v in head)+'</tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'


def chart(row: dict, ready: dict, quotes: dict) -> str:
    """機能: 返済後の動きも含め、損切りと後からの順行を暗色SVGで図解する。

    引数: row/ready/quotes(dict)。返り値: SVGと説明を含むHTML(str)。
    返済後の値は図解だけであり売買判断へ使わない。
    """
    start,end = max(0,row['decision_i']-300),len(ready['seq'])-1
    sample = np.unique(np.r_[np.linspace(start,end,min(1800,end-start+1)).astype(int),row['entry_i'],row['exit_i']])
    times = ready['time_s']
    price = quotes['bid'] if row['side']>0 else quotes['ask']
    low,high = float(price[sample].min()),float(price[sample].max())
    margin = max(20.,(high-low)*.09)
    low,high = low-margin,high+margin
    left,top,width,height = 85.,24.,870.,250.
    base,span = float(times[start]),max(1.,float(times[end]-times[start]))
    x = lambda i: left+(times[i]-base)/span*width
    y = lambda p: top+(high-p)/(high-low)*height
    path = ' '.join(f'{x(i):.2f},{y(price[i]):.2f}' for i in sample)
    grid=[]
    for p in np.linspace(low,high,5):
        grid.append(f'<path d="M{left},{y(p):.1f}h{width}" stroke="#293b51"/><text x="77" y="{y(p)+5:.1f}" text-anchor="end" fill="#b8c6d7">{p:,.0f}</text>')
    for i in np.linspace(start,end,5).astype(int):
        grid.append(f'<text x="{x(i):.1f}" y="300" text-anchor="middle" fill="#b8c6d7">{clock(times[i])[:5]}</text>')
    anchor = row['entry_price']
    stop = anchor-row['side']*anchor*.001
    target = anchor+row['side']*anchor*.001
    lines=[]
    for p,color,name in ((anchor,'#93c5fd','新規価格'),(stop,'#fb7185','初期損切り'),(target,'#6ee7b7','0.1%利益')):
        lines.append(f'<path d="M{left},{y(p):.1f}h{width}" stroke="{color}" stroke-dasharray="6 5"/><text x="{left+8}" y="{y(p)-5:.1f}" fill="{color}">{name} {p:,.2f}</text>')
    points=[]
    for i,p,label,color in ((row['entry_i'],anchor,'新規','#93c5fd'),(row['exit_i'],row['exit_price'],'返済','#fb7185')):
        points.append(f'<circle cx="{x(i):.1f}" cy="{y(p):.1f}" r="5" fill="{color}"><title>{label} {clock(times[i])} {p}</title></circle>')
    title=f'{row["session"]} · {"買い" if row["side"]>0 else "売り"} · {clock(row["entry_time"])}→{clock(row["exit_time"])} · {money(row["net"])}円'
    return '<figure><figcaption>'+title+'</figcaption><div class="scroll"><svg viewBox="0 0 1000 320" role="img" aria-label="返済後も含む売買気配推移"><rect width="1000" height="320" fill="#101b2b"/>'+''.join(grid)+f'<polyline points="{path}" fill="none" stroke="#c4b5fd" stroke-width="1.4"/>'+''.join(lines+points)+'</svg></div></figure>'


def main() -> None:
    """機能: 検算済み売買を全場・週・23入口・12条件へ整理し一覧を更新する。

    引数: なし。返り値: なし(None)。過去作業の成果は変更しない。
    """
    result = json.loads((HERE/'結果.json').read_text(encoding='utf-8'))
    primary = result['methods'][0]
    inputs,quotes = [pickle.loads(p.read_bytes()) for p in (replay.INPUTS,replay.QUOTES)]
    old = pickle.loads(replay.OLD.read_bytes())
    ideal=[]
    for row in primary['rows']:
        item=row.copy()
        item['exit_price']=row['entry_price']+row['side']*row['stop_gain']
        item['gross']=row['stop_gain']*row['qty']*row['value']
        item['net']=item['gross']-item['fees']
        ideal.append(item)
    replay.save(HERE/'指定値約定の理想参照.json',dict(仕様='新規は主案同様、返済だけ条件線の連続値で指定値全約定。実ポートフォリオではない理想感度。',
        summary={s:replay.summarize([r for r in ideal if r['symbol']==s]) for s in ('TOPIX','NK225')},rows=ideal))
    comparison=[]
    for symbol in ('NK225','TOPIX'):
        net=[]
        for key,ledger in old.items():
            if key[1]==symbol:
                net.extend((ledger['trades'][:,8]*2.).tolist())
        comparison.append(dict(symbol=symbol,net=sum(net),trades=len(net),wins=sum(n>0 for n in net),
            losses=sum(n<0 for n in net),win_rate=sum(n>0 for n in net)/len(net)))
    replay.save(HERE/'旧出口の全力枚数比較.json',comparison)
    # ----------------------------------------
    # 主案は結果によらず先頭に固定し、残りはパラメータ順で全条件を表示する。
    summary_rows=[]
    for symbol,label in (('NK225','NKマイクロ20枚'),('TOPIX','TOPIXミニ10枚')):
        a=primary['summary'][symbol]
        cells=[label,f'{a["wins"]} / {a["losses"]}',pct(a['win_rate']),money(a['profit']),money(a['loss']),
            money(a['net']),f'{a["win_qty"]} / {a["loss_qty"]}',money(a['fees']),f'{a["payoff"]:.2f}']
        summary_rows.append('<tr>'+''.join(f'<td>{v}</td>' for v in cells)+'</tr>')
    variations=[]
    for m in result['methods']:
        c=m['config'];a=m['summary']['NK225'];t=m['summary']['TOPIX']
        cells=[c['id']+(' 主案' if c['primary'] else ''),f'{c["stop"]*100:.2f}%',f'{c["arm"]*100:.2f}%',f'{c["trail"]*100:.2f}%',
            money(a['net']),f'{a["wins"]}/{a["trades"]}',f'{a["payoff"]:.2f}',money(t['net'])]
        variations.append('<tr>'+''.join(f'<td>{v}</td>' for v in cells)+'</tr>')
    week_rows=[]
    for symbol,label in (('NK225','NK'),('TOPIX','TOPIX')):
        groups={}
        for r in primary['rows']:
            if r['symbol']!=symbol:
                continue
            day=datetime.strptime(r['session'][:10],'%Y-%m-%d').date()
            monday=day-timedelta(days=day.weekday())
            groups.setdefault(str(monday),[]).append(r)
        for week in ('2026-09-21','2026-09-28','2026-10-05'):
            a=replay.summarize(groups.get(week,[]))
            cells=[label,week+('〜10/07デイ' if week=='2026-10-05' else '週'),money(a['profit']),money(a['loss']),money(a['net']),
                   f'{a["win_qty"]} / {a["loss_qty"]}']
            week_rows.append('<tr>'+''.join(f'<td>{v}</td>' for v in cells)+'</tr>')
    ledger=[]
    nk=[r for r in primary['rows'] if r['symbol']=='NK225']
    for r in nk:
        reason='損切り' if r['reason']==1 else '追跡返済' if r['reason']==2 else '場末返済'
        cells=[r['session'],clock(r['entry_time']),'買い' if r['side']>0 else '売り',money(r['entry_price']),clock(r['exit_time']),
               money(r['exit_price']),reason,money(r['net']),'到達' if r['eventual_target'] else '未到達']
        ledger.append('<tr>'+''.join(f'<td>{v}</td>' for v in cells)+'</tr>')
    first_loss=next(r for r in nk if r['stopped_then_eventual_target'])
    first_win=next(r for r in nk if r['protected'])
    figures=''.join(chart(r,inputs[(r['session'],r['symbol'])],quotes[(r['session'],r['symbol'])]) for r in (first_loss,first_win))
    source='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>候補3の全力新規と利益保護トレール</title><style>
:root{color-scheme:dark}*{box-sizing:border-box}body{background:#0c1420;color:#e8eef8;margin:0;font:16px/1.7 system-ui,'Yu Gothic',sans-serif}main{max-width:1240px;margin:auto;padding:28px}h1{font-size:27px;line-height:1.4}h2{font-size:21px}.card{border:1px solid #34475d;background:#152132;padding:20px;border-radius:12px;margin:20px 0}.sub{font-size:14px;color:#afbdd0}.scroll{overflow:auto}table{border-collapse:collapse;white-space:nowrap;width:100%;font-size:14px}th,td{padding:9px;border-bottom:1px solid #36475c;text-align:right}th:first-child,td:first-child{text-align:left}thead{background:#203249}a{color:#93c5fd}svg{min-width:720px;width:100%;display:block;font:13px system-ui}figure{margin:18px 0}figcaption{margin:8px 0}details{margin:18px 0}summary{cursor:pointer;color:#b9d6ff}code{font-size:13px;overflow-wrap:anywhere}@media(max-width:650px){main{padding:14px}.card{padding:14px}h1{font-size:23px}}
</style></head><body><!--
[コンポーネント概要]
main は、候補3の入口を変えずに全力枚数と割合トレールを検証した資料です。
.card は短い説明、主成績、セッション会計、幅の感度をまとめます。
.scroll は暗色の会計表・売買図を横スクロールできる領域です。
details は全23取引や監査情報を必要なときだけ開きます。外部通信はしません。
--><main><p class="sub">作業00062 · 保存済み25セッション · 2026/09/21デイ〜10/07デイ</p><h1>候補3の全力新規＋0.1%損切り＋利益保護トレール</h1>
<p><strong>提案通りのNKは11勝12敗、費用後−18,120円でした。</strong>0.1%以上へ後から到達した入口でも、先に損切りされるため、前回の22/23を決済勝率へ変換できません。</p>
<section class="card"><h2>今回のルール</h2><p>候補3の入口は固定。直前20分の高安を外へ抜けて戻った後、板が反転方向を支持した時に入り、NKマイクロ20枚（参考TOPIXミニ10枚）を一度に建てます。</p>
<p>実建値から0.1%逆行で返済。0.11%順行で追跡を開始し、最高含み利益から0.01%戻ったら返済します。利益0.50%なら条件線0.49%。0.1%を条件線の下限にします。</p>
<p class="sub">長玉はbid、短玉はaskで含み値幅を監視。条件成立後の次の有効原板行で成行相当約定。条件線は連続値で、呼値へ丸めた保証価格ではありません。決済後10分休止、追加なし、同時上限20/10枚。60分の保有期限・日次損失停止は今回は設けず、監視区間末前に全返済します。</p></section>
<section class="card"><h2>主案：全期間の損益</h2><div class="scroll"><table id="totals"><thead><tr><th>商品 / 同時上限</th><th>勝 / 負 取引</th><th>決済勝率</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>利益 / 損失 枚数</th><th>手数料 円</th><th>平均利益 / 平均損失</th></tr></thead><tbody>'''+''.join(summary_rows)+'''</tbody></table></div><p class="sub">利益・損失は、往復手数料を引いた決済取引を黒字・赤字へ分けて集計。枚数は決済済み枚数で、差は「利益枚数−損失枚数」です。無取引場は勝ちに含めません。NK片道220円、TOPIX片道418円。</p></section>
<section class="card"><h2>95.7%が47.8%になった理由</h2><p>前回は判断中値から場末までの最大順行。今回のNK損切り12件のうち10件は、その後に0.1%以上順行しましたが、建玉は既にありません。</p><p>追跡が始まった11件はすべて黒字でした。ただし0.01%は約6.5〜7円幅で、参照ラージ板の10円刻みより狭く、1回の小さな反落で返済しやすい設定です。平均利益14,105円に対して平均損失14,440円で、利益を十分に伸ばせていません。</p><p>新規価格を同じにして、返済だけ条件線の値段で完全に約定できたと仮定しても、NKは<strong>−5,310円</strong>。約定悪化だけが原因ではありません。実気配での追跡返済3件は、0.1%利益線を下回りました。</p></section>
<section class="card"><h2>損切り後の回復と、細いトレールの例</h2>'''+figures+'''<p class="sub">最初の「損切り後に順行した例」と最初の追跡返済を掲載。線は保有方向の返済気配、点は約定。返済後の値動きは事後の図解専用です。</p></section>
<section class="card"><h2>幅を変える余地はある</h2><p>損切り0.1%を保ち、追跡幅を0.05%へ広げるとNKは<strong>10勝12敗、＋46,320円</strong>。平均利益21,760円、平均損失14,273円で、損益比は1.52へ改善しました。最初の利益線0.1%を維持するため、開始は0.15%へ遅らせています。</p><p>つまり、損小利大の仕組みとしては検討できます。ただし今回の入口と出口の組合せでは高勝率を確認できず、TOPIXにも共通して黒字となる条件はありません。</p><details open><summary>結果前固定した全12条件</summary><div class="scroll"><table id="variants"><thead><tr><th>条件ID</th><th>損切り</th><th>追跡開始</th><th>追跡幅</th><th>NK収支 円</th><th>NK 勝/全取引</th><th>NK平均損益比</th><th>TOPIX収支 円</th></tr></thead><tbody>'''+''.join(variations)+'''</tbody></table></div></details><p class="sub">全て初期利益線0.1%、フル枚数、費用込み。開始幅＝0.1%＋追跡幅。開始と追跡幅を一緒に変更する感度で、追跡幅単独の効果とは区別します。値幅は事前固定、全25場は既知の探索データです。</p></section>
<section class="card"><h2>主案の各セッション</h2><h3>NKマイクロ20枚</h3>'''+account_table(primary['accounts'],'NK225')+'''<details><summary>参考：TOPIXミニ10枚</summary>'''+account_table(primary['accounts'],'TOPIX')+'''</details><h3>週ごとの主案</h3><div class="scroll"><table id="weeks"><thead><tr><th>銘柄</th><th>週</th><th>利益 円</th><th>損失 円</th><th>収支 円</th><th>利益 / 損失 枚数</th></tr></thead><tbody>'''+''.join(week_rows)+'''</tbody></table></div><p class="sub">最終週は10/07デイまで。全場で返済しており、残建玉の仮想清算はありません。</p></section>
<details class="card"><summary>NK全23決済を確認する</summary><div class="scroll"><table id="ledger"><thead><tr><th>セッション</th><th>新規時刻</th><th>方向</th><th>新規価格</th><th>返済時刻</th><th>返済価格</th><th>理由</th><th>純収支 円</th><th>場末までに0.1%</th></tr></thead><tbody>'''+''.join(ledger)+'''</tbody></table></div><p>今回の主案では旧23入口の個別追跡と、上限を守った連続売買の入口・決済が一致しました。幅を広げた条件は保有中の候補を見送るため、取引件数も変わります。個別追跡を足して実戦成績にはしていません。</p></details>
<details class="card"><summary>元の出口・実行仕様・検査資料</summary><p>元の候補3出口を同じNK20枚に換算すると17勝6敗、＋41,880円。元は場の開始価格を基にした幅Wの半分で固定利確、Wで損切り、60分期限です。今回の割合幅は実建値基準なので、出口全体を変更した比較です。</p><p>controllerのトレールには開始価格があり、固定幅追跡は表現できます。ただしNKマイクロは予約API対象外なので、既存E01同様、アプリでラージ板を監視して成行を発注する必要があります。実約定値から条件を計算します。実装可能性の確認であり、既存E01を変更・実注文した検証ではありません。</p><p>ラージ気配を小商品の約定代理にしています。板の食い込み・通信発注時間・IFDの約定照合後の監視開始遅延は未再現。原板順を守り、出口はその時点までの価格のみで判定。事後最大値は売買へ渡していません。時計は保存最終約定時刻で、実受信時刻は不明です。</p><p>Day15:30/Night05:45以後は新規なし。Day15:34/Night05:49以後に返済判断し次行約定。これは保存データの通常監視区間に合わせた時刻です。</p><p><a href="結果.json">全12条件・全口座・全取引JSON</a> · <a href="実行前固定.json">実行前固定</a> · <a href="独立検査.json">独立検査</a> · <a href="指定値約定の理想参照.json">指定値で返済する理想参照</a> · <a href="README.md">読む順序と再現</a></p></details>
<p><a href="../00061_入口の方向予測精度を出口と分離/入口の方向予測精度.html">前回：場末までの最大順行</a> · <a href="../index.html">作業一覧</a></p></main></body></html>'''
    (OUT/'候補3の全力新規とトレール損益.html').write_text(source,encoding='utf-8')
    audit=HERE/'audit/全条件の独立監査.json'
    if audit.exists():
        (OUT/'独立検査.json').write_bytes(audit.read_bytes())
        source=source.replace('今回のNK損切り12件のうち10件は、その後に0.1%以上順行しましたが、建玉は既にありません。</p>',
            '今回のNK損切り12件のうち10件は、その後に0.1%以上順行しましたが、建玉は既にありません。</p><p>旧中値採点で順行0.1%が先だった14件も、実建値へ起点を変えると12件に減り、0.11%で追跡開始を要求すると11件になります。判断時の新規気配だけなら14件のままですが、次行で新規価格が10円・20円悪化した2件が減ります。残る1件は70円順行しても開始幅72.38円に届かず反落。独立検算で原因を分離しました。</p>')
        source=source.replace('<p>ラージ気配を小商品の約定代理にしています。',
            '<p>別式で連続488決済・個別504決済・全600口座を検算し一致。返済判断後まだ約定していない切断を含む1,682件、返済後の価格を変更する488件も検査しました。</p><p>ラージ気配を小商品の約定代理にしています。')
        (OUT/'候補3の全力新規とトレール損益.html').write_text(source,encoding='utf-8')
    for name in ('指定値約定の理想参照.json','指定値参照の事前固定.json','旧出口の全力枚数比較.json'):
        (OUT/name).write_bytes((HERE/name).read_bytes())
    (OUT/'README.md').write_text('''# 候補3の全力新規と利益保護トレール

最初に [候補3の全力新規とトレール損益.html](候補3の全力新規とトレール損益.html) を見てください。

読む順序：主案の結果 → 勝率が変わる理由と2例の売買図 → 12条件の幅感度 → 全25セッション・週の会計 → 全23決済。

候補3の凍結済み入口で、NKmicro20枚、TOPIXmini10枚。逆行0.1%、順行0.11%で開始、固定0.01%追跡幅が主案です。元の60分保有期限は外し場内返済、決済後10分休止は維持しました。全12条件は再生前に固定し、全25場は既知データとして検証しました。

[実行前固定](実行前固定.json)、[結果JSON](結果.json)、[合成検査](合成検査.json)、[独立検査](独立検査.json)、[指定値で返済する理想参照](指定値約定の理想参照.json) に再現情報があります。理想参照は連続値の条件線そのもので返済できる追加仮定です。

再現：プロジェクトルートから `python work/wave_v65/replay.py`（新規結果がない場合）、`python work/wave_v65/report.py`。入口・気配キャッシュは過去作業の凍結済みファイルを読み取ります。原本は変更せず、現在API取得・実注文・E01変更は行いません。
''',encoding='utf-8')
    research=OUT.parent
    index=(research/'index.html').read_text(encoding='utf-8')
    if '<!--00062開始-->' not in index:
        index=index.replace('class="task latest"','class="task"').replace(' <span class="badge">最新</span>','')
        article='<!--00062開始--><article class="task latest"><div class="number">作業00062 <span class="badge">最新</span></div><h2>候補3の全力新規と利益保護トレール</h2><p>0.1%損切り・0.11%で利益追跡開始・0.01%幅の主案と12条件。NK20枚/TOPIX10枚、全25場、原板順・手数料込み。</p><a class="button" href="00062_候補3の全力新規と利益保護トレール/候補3の全力新規とトレール損益.html">提案の検証と全損益を開く →</a></article><!--00062終了-->'
        index=index.replace('<!--00061開始-->',article+'<!--00061開始-->')
        index=index.replace('最新00061：入口の方向予測精度を決済勝率と分離して確認。','最新00062：候補3の全力新規と0.1%損切り・利益保護トレールを検証。')
        index=index.replace('次の新しい作業には 00062','次の新しい作業には 00063')
        (research/'index.html').write_text(index,encoding='utf-8')
    index=(research/'index.html').read_text(encoding='utf-8').replace('最新作業は00061です。次の作業は00062以降へ追加します。','最新作業は00062です。次の作業は00063以降へ追加します。')
    (research/'index.html').write_text(index,encoding='utf-8')
    readme=(research/'README.md').read_text(encoding='utf-8')
    if '<!--00062案内開始-->' not in readme:
        readme=readme.replace('**最新は00061の','**00061の')
        readme=readme.replace('<!--00061案内開始-->','<!--00062案内開始-->\n**最新は00062の[候補3の全力新規とトレール損益](00062_候補3の全力新規と利益保護トレール/候補3の全力新規とトレール損益.html)。主案と12条件を、同時枚数上限・手数料・原板順で検証。全25場と週会計。**\n<!--00062案内終了-->\n\n<!--00061案内開始-->')
        readme=readme.replace('次の新しい作業には `00062`','次の新しい作業には `00063`')
        (research/'README.md').write_text(readme,encoding='utf-8')
    readme=(research/'README.md').read_text(encoding='utf-8').replace('今後の新しい作業は `00043_内容`','今後の新しい作業は `00063_内容`')
    (research/'README.md').write_text(readme,encoding='utf-8')
    print('作業00062の説明と全会計を保存しました')


if __name__ == '__main__':
    main()
