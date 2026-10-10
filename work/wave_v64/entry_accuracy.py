"""前回3候補の発注判断だけを起点に、出口を使わず方向予測を採点する。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import pickle
import re

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREVIOUS = ROOT/'アルゴリズム調査/00060_決済勝率95パーセントの探索とPDCA'
OUT = ROOT/'アルゴリズム調査/00061_入口の方向予測精度を出口と分離'
HORIZONS = (5, 15, 30, 60)
WIDTHS = (.0005, .001)


def save(path: Path, value: object) -> None:
    """機能: UTF-8で有限値の日本語JSONを保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def entry_rows(method: dict) -> dict:
    """機能: 判断行と予測方向を、既存の実新規台帳から抽出する。

    引数: method(dict)。返り値: 各口座の判断行・方向配列(dict)。
    """
    ledger_path = PREVIOUS/'台帳'/f'候補{method["number"]}_原簿.pkl'
    ledgers = pickle.loads(ledger_path.read_bytes())
    result={}
    for key,ledger in ledgers.items():
        orders=ledger['orders']
        if orders.shape[1]==9:
            rows=orders[orders[:,2]==1]
            result[key[:2]]=rows[:,[0,3]].astype(np.int64)
        else:
            assert orders.shape[1]==16
            rows=orders[orders[:,4]==1]
            result[key[:2]]=rows[:,[2,5]].astype(np.int64)
    return result


def score(times: np.ndarray, mids: np.ndarray, index: int, side: int, limit: float, tick: float) -> dict:
    """機能: 固定時点の符号と、対称幅への先着を独立採点する。

    引数: times/mids(ndarray)、index/side(int)、limit/tick(float)。返り値: 各採点結果(dict)。
    """
    output={}
    for minutes in HORIZONS:
        target=float(times[index])+minutes*60
        j=int(np.searchsorted(times,target,side='left'))
        available=target<limit+300 and j<len(times) and times[j]-target<=60
        if available:
            movement=float(side*(mids[j]-mids[index]))
            verdict=1 if movement>0 else -1 if movement<0 else 0
            output[str(minutes)]=dict(有効=True,判定=verdict,方向変位=movement,評価行=j,時計超過秒=float(times[j]-target))
        else:
            output[str(minutes)]=dict(有効=False,理由='同じ場で固定時点まで観測できない、又は評価時計が60秒超過')
    thirty=output['30']
    for fraction in WIDTHS:
        name=f'先着{fraction*100:.2f}'
        if not thirty['有効']:
            output[name]=dict(有効=False)
            continue
        width=float(np.ceil(mids[index]*fraction/tick-1e-10)*tick)
        # 終点の初回原本行までに限定し、その時計を超える行は含めない。
        last=thirty['評価行']
        if times[last]>times[index]+1800:
            last-=1
        displacement=side*(mids[index+1:last+1]-mids[index])
        reached=np.flatnonzero(np.abs(displacement)>=width-1e-9)
        verdict=int(np.sign(displacement[reached[0]])) if len(reached) else 0
        output[name]=dict(有効=True,判定=verdict,幅=width,評価行=int(index+1+reached[0]) if len(reached) else None)
    return output


def aggregate(rows: list[dict], label: str) -> dict:
    """機能: 方向正答・逆行・横ばい又は未到達と除外件数を集計する。

    引数: rows(list[dict])、label(str)。返り値: 件数と正答率(dict)。
    """
    valid=[r for r in rows if r['scores'][label]['有効']]
    correct=sum(r['scores'][label]['判定']==1 for r in valid)
    wrong=sum(r['scores'][label]['判定']==-1 for r in valid)
    neutral=len(valid)-correct-wrong
    always_long=sum(r['scores'][label]['判定']*r['side']==1 for r in valid)
    always_short=sum(r['scores'][label]['判定']*r['side']==-1 for r in valid)
    return dict(新規数=len(rows),評価数=len(valid),正答=correct,逆行=wrong,横ばい又は未到達=neutral,除外=len(rows)-len(valid),
        正答率=correct/len(valid) if valid else None,到達又は変化内正答率=correct/(correct+wrong) if correct+wrong else None,
        同時点常時買い正答率=always_long/len(valid) if valid else None,同時点常時売り正答率=always_short/len(valid) if valid else None,
        同時点コイントス期待正答率=.5*(correct+wrong)/len(valid) if valid else None)


def percentage(value: float | None) -> str:
    """機能: 正答率を表示する。

    引数: value(float|None)。返り値: 表示文字列(str)。
    """
    return '未観測' if value is None else f'{value*100:.1f}%'


def main() -> None:
    """機能: 評価定義を固定し、281新規の方向精度を報告する。

    引数: なし。返り値: なし(None)。新規算法選択・実注文・API取得は行わない。
    """
    HERE.mkdir(exist_ok=True);OUT.mkdir(exist_ok=True)
    target=HERE/'方向採点.json'
    assert not target.exists(),'方向採点を上書きしません'
    packet=json.loads((PREVIOUS/'比較3候補.json').read_text(encoding='utf-8'))
    methods=[dict(number=i,id=m['id'],name=m['name'],accounts=m['accounts']) for i,m in enumerate(packet['methods'],1)]
    save(HERE/'採点前固定.json',dict(時刻=datetime.now(timezone.utc).isoformat(),主基準='発注判断中値を起点に30分後の予測方向変位>0。横ばいは正答に含めない。',
        補助時間分=HORIZONS,先着幅=WIDTHS,幅の基準='各入口中値×価格比をラージ呼値へ切上げ、対称。30分内に最初に到達した側。',
        除外='同場で期限まで追えない入口と終点の時計超過60秒以上。除外を勝ちにしない。',
        価格='中値のみ。費用・約定気配差・出口条件を含めない。',
        時間='CurrentPriceTime由来の約定時計。受信時計ではない。評価時点は最初の原本行。',
        既知データ='25場は既読、前回選定された3候補の実新規判断。独立未知試験ではない。',
        コードSHA=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),現在API=0,実注文=False))
    inputs=pickle.loads((HERE.parent/'wave_v60/inputs.pkl').read_bytes())
    quotes=pickle.loads((HERE.parent/'wave_v60/quotes.pkl').read_bytes())
    all_rows=[]
    for method in methods:
        entries=entry_rows(method);rows=[]
        for key,signals in sorted(entries.items()):
            ready=inputs[key];q=quotes[key]
            for origin,side in signals:
                if method['number']==3:
                    index=int(np.searchsorted(ready['seq'],origin))
                    assert ready['seq'][index]==origin
                else:
                    index=int(origin)
                rows.append(dict(method=method['id'],session=key[0],symbol=key[1],decision_i=index,decision_seq=int(ready['seq'][index]),side=int(side),
                    decision_time=float(ready['time_s'][index]),decision_mid=float(q['mid'][index]),
                    scores=score(ready['time_s'],q['mid'],index,int(side),ready['limit'],ready['tick'])))
        expected=sum(a['cycles'] for a in method['accounts'])
        assert len(rows)==expected
        method['summary']={s:{label:aggregate([r for r in rows if r['symbol']==s],label) for label in [*[str(h) for h in HORIZONS],*[f'先着{w*100:.2f}' for w in WIDTHS]]} for s in ('TOPIX','NK225')}
        del method['accounts'];all_rows.extend(rows)
    assert len(all_rows)==281
    save(target,dict(methods=methods,rows=all_rows,新規数=281,出口独立=True))
    save(OUT/'方向採点.json',dict(methods=methods,rows=all_rows,新規数=281,出口独立=True))
    # ----------------------------------------
    # 短い主表と定義を公開し、全時間軸は補助表へ分ける。
    main_rows=[];details=[]
    for m in methods:
        for symbol in ('TOPIX','NK225'):
            a=m['summary'][symbol]['30'];b=m['summary'][symbol]['先着0.05']
            main_rows.append(f'<tr><th>候補{m["number"]}</th><td>{symbol}</td><td>{a["正答"]}/{a["評価数"]}</td><td>{percentage(a["正答率"])}</td><td>{a["横ばい又は未到達"]}</td><td>{a["除外"]}</td><td>{b["正答"]}/{b["評価数"]} ({percentage(b["正答率"])})</td><td>{b["横ばい又は未到達"]}</td></tr>')
            details.append(f'<tr><th>候補{m["number"]} {symbol}</th>'+''.join(f'<td>{percentage(m["summary"][symbol][str(h)]["正答率"])} ({m["summary"][symbol][str(h)]["評価数"]})</td>' for h in HORIZONS)+f'<td>{percentage(a["同時点常時買い正答率"])}</td><td>{percentage(a["同時点常時売り正答率"])}</td></tr>')
    doc='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>入口の方向予測精度</title><style>:root{color-scheme:dark}body{margin:0;background:#0d1420;color:#e5eef9;font:16px/1.7 system-ui,'Yu Gothic',sans-serif}main{max-width:1160px;margin:auto;padding:26px}h1{font-size:28px}h2{font-size:21px}.card{background:#152132;border:1px solid #344961;border-radius:12px;padding:20px;margin:22px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}td,th{padding:11px;border-bottom:1px solid #35495e;text-align:right}th:first-child{text-align:left}thead{background:#20334b}a{color:#90c9ff}.sub{color:#a7b9cf;font-size:14px}code{font-size:12px;overflow-wrap:anywhere}@media(max-width:650px){main{padding:16px}h1{font-size:24px}}</style><!--
[コンポーネント概要]
main は入口だけの方向採点です。最初の表は固定30分と対称先着の正答率。
.scroll は横スクロール領域、.sub は評価条件と制限の補足です。
--><main><p class="sub">作業00061 · 既知25セッション · 前回3候補の281新規判断</p><h1>入口の方向予測は何％当たったか</h1><p><b>方向は機械的に判定できます。ただし、高精度で当たるという結論にはなっていません。</b></p><p>「現在の上昇・下落を認識すること」と「その後の方向を当てること」を区別します。ここでは後者を採点しました。前回の決済勝率73.9%とは別の指標です。</p><section class="card"><h2>30分後の方向正答率</h2><p>入口で買い判断なら30分後の中値が高い、売り判断なら低い場合を正答。横ばいも分母へ含めます。費用と返済条件は含めません。</p><div class="scroll"><table><thead><tr><th>入口</th><th>銘柄</th><th>30分後 正答/評価</th><th>正答率</th><th>横ばい</th><th>終盤等の除外</th><th>対称先着 正答/評価</th><th>未到達</th></tr></thead><tbody>'''+''.join(main_rows)+'''</tbody></table></div><p class="sub">対称先着は、入口から上下同じ0.05%幅（呼値切上げ）のどちらへ30分内に先に到達したか。逆行後に戻って正答になる30分後評価との違いを示します。未到達は正答へ数えません。</p></section><section class="card"><h2>時間軸を変えるとどうか</h2><div class="scroll"><table><thead><tr><th>入口/銘柄</th><th>5分後</th><th>15分後</th><th>30分後</th><th>60分後</th><th>30分 常に買い</th><th>30分 常に売り</th></tr></thead><tbody>'''+''.join(details)+'''</tbody></table></div><p class="sub">括弧は評価数。常に買い/売りは同じ入口時刻の対照で、あとから有利な側を選ぶアルゴリズムではありません。最も良い時間だけを精度として採用していません。</p></section><section class="card"><h2>どの入口か</h2>'''+''.join(f'<p>候補{m["number"]}：{m["name"]}<br><code>{m["id"]}</code></p>' for m in methods)+'''<p><a href="../00060_決済勝率95パーセントの探索とPDCA/95パーセント探索の説明と全セッション損益.html">前回の手法説明と損益</a></p></section><p>時刻は保存された最終約定時計で、実受信時刻ではありません。30分後はその時計以降の最初の原本行を使い、60秒を超えて観測が遅れた場合と場内に期限まで追えない場合は除外しました。対称先着は期限時計を超えた行を含めません。板の中値なので、そのまま約定利益になる精度でもありません。</p><p>これは既知データで選んだ入口の観測値です。取引は時間的に重なり、独立標本ではありません。未知の将来で同じ確率になることは未確認です。</p><p><a href="方向採点.json">全判断と採点JSON</a> · <a href="README.md">資料案内</a></p></main></html>'''
    (OUT/'入口の方向予測精度.html').write_text(doc,encoding='utf-8')
    (OUT/'README.md').write_text('''# 入口の方向予測精度

最初に [入口の方向予測精度.html](入口の方向予測精度.html) を見てください。

読む順序：30分後の主表 → 対称幅先着との違い → 5/15/30/60分の補助表 → [全281判断のJSON](方向採点.json)。

前回3候補の実新規判断を抽出し、発注判断時の中値から出口を使わず採点しました。価格の符号だけの正答率で、決済損益の勝率ではありません。現在セッションの取得と実注文は行っていません。

再現元：`../../work/wave_v64/entry_accuracy.py`、同フォルダの採点前固定.json。25場は既知で、未知の予測確率の保証ではありません。
''',encoding='utf-8')
    research=OUT.parent
    index=(research/'index.html').read_text(encoding='utf-8').replace('class="task latest"','class="task"').replace('<span class="badge">最新</span>','')
    card=f'<!--00061開始--><article class="task latest"><div class="number">作業00061 <span class="badge">最新</span></div><h2>入口の方向予測精度</h2><p>決済勝率と分離し、前回3候補の判断後5〜60分の価格方向と対称幅への先着を採点。</p><a class="button" href="{OUT.name}/入口の方向予測精度.html">方向の正答率を開く →</a></article><!--00061終了-->'
    assert '<!--00061開始-->' not in index
    index=index.replace('<!--00060開始-->',card+'<!--00060開始-->',1)
    index=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00061：入口の方向予測精度を決済勝率と分離して確認。</p>',index,count=1,flags=re.S)
    index=re.sub(r'<footer>最新作業は.*?</footer>','<footer>最新作業は00061です。次の作業は00062以降へ追加します。</footer>',index,count=1,flags=re.S)
    (research/'index.html').write_text(index,encoding='utf-8')
    readme=(research/'README.md').read_text(encoding='utf-8').replace('最新は00060の','00060の')
    head,rest=readme.split('\n',1)
    notice=f'<!--00061案内開始-->\n**最新は00061の[入口の方向予測精度]({OUT.name}/入口の方向予測精度.html)。出口・費用を外して、前回3候補の281判断を固定時間と対称先着で採点。**\n<!--00061案内終了-->\n'
    (research/'README.md').write_text(head+'\n\n'+notice+'\n'+rest.lstrip('\n'),encoding='utf-8')
    for m in methods:
        print(m['number'],m['name'],json.dumps({s:{label:m['summary'][s][label] for label in ('30','先着0.05')} for s in ('TOPIX','NK225')},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
