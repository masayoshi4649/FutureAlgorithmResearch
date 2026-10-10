"""固定保有時間を使わず、入口判断後の場内最大順行と途中逆行を測定する。"""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import pickle


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OUT=ROOT/'アルゴリズム調査/00061_入口の方向予測精度を出口と分離'
WIDTHS=(.0005,.001,.002)


def save(path: Path,value: object) -> None:
    """機能: 事後経路採点を有限値のUTF-8 JSONへ保存する。

    引数: path(Path)、value(object)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')


def measure(mid: np.ndarray,index: int,side: int,tick: float) -> dict:
    """機能: 判断後から同じ保存場末までの最大順行・逆行・対称先着を採点する。

    引数: mid(ndarray)、index/side(int)、tick(float)。返り値: 限界値と到達(dict)。
    最大順行が正なら、その値へ初めて到達した行までの逆行も測定する。
    """
    path=side*(mid[index+1:]-mid[index])
    assert len(path)>0
    maximum=float(np.max(path));mfe=max(0.,maximum);mae=max(0.,float(-np.min(path)))
    peak_rel=int(np.argmax(path)) if mfe>0 else None
    peak_i=index+1+peak_rel if peak_rel is not None else None
    before=max(0.,float(-np.min(path[:peak_rel+1]))) if peak_rel is not None else None
    labels={}
    for fraction in WIDTHS:
        width=float(np.ceil(mid[index]*fraction/tick-1e-10)*tick)
        hits=np.flatnonzero(np.abs(path)>=width-1e-9)
        first=int(np.sign(path[hits[0]])) if len(hits) else 0
        labels[f'{fraction*100:.2f}']=dict(幅=width,順行到達=mfe>=width-1e-9,逆行到達=mae>=width-1e-9,先着=first,
            先着行=int(index+1+hits[0]) if len(hits) else None)
    return dict(最大順行=mfe,最大順行割合=mfe/mid[index],最大逆行=mae,最大逆行割合=mae/mid[index],
        最大順行前の逆行=before,最大順行行=peak_i,最大順行価格=float(mid[peak_i]) if peak_i is not None else None,
        一呼値順行=mfe>=tick-1e-9,最大値までの利益幅が途中逆行以上=mfe>0 and before<=mfe,
        最大値までの利益幅が途中逆行の二倍以上=mfe>0 and before*2<=mfe,到達=labels)


def stats(values: list[float]) -> dict:
    """機能: 値幅分布を計算し、未観測を区別する。

    引数: values(list[float])。返り値: 分布(dict)。
    """
    if not values:
        return dict(件数=0,最小=None,四分位25=None,中央値=None,四分位75=None,最大=None,平均=None)
    a=np.asarray(values)
    return dict(件数=len(a),最小=float(a.min()),四分位25=float(np.quantile(a,.25)),中央値=float(np.median(a)),
        四分位75=float(np.quantile(a,.75)),最大=float(a.max()),平均=float(a.mean()))


def summarize(rows: list[dict]) -> dict:
    """機能: 幅ごとの到達率と対称先着を同じ全入口の分母で集計する。

    引数: rows(list[dict])。返り値: 件数・分布・到達率(dict)。
    """
    n=len(rows);out=dict(新規数=n,一呼値順行数=sum(r['extent']['一呼値順行'] for r in rows),
        一度も順行しなかった数=sum(r['extent']['最大順行']==0 for r in rows))
    for field in ('最大順行','最大順行割合','最大逆行','最大逆行割合','最大順行前の逆行'):
        out[field]=stats([r['extent'][field] for r in rows if r['extent'][field] is not None])
    out['一呼値順行率']=out['一呼値順行数']/n
    out['最大値までの利益幅が途中逆行以上率']=sum(r['extent']['最大値までの利益幅が途中逆行以上'] for r in rows)/n
    out['最大値までの利益幅が途中逆行の二倍以上率']=sum(r['extent']['最大値までの利益幅が途中逆行の二倍以上'] for r in rows)/n
    out['到達']={}
    for fraction in WIDTHS:
        name=f'{fraction*100:.2f}';labels=[r['extent']['到達'][name] for r in rows]
        good=sum(d['順行到達'] for d in labels);bad=sum(d['逆行到達'] for d in labels)
        first_good=sum(d['先着']==1 for d in labels);first_bad=sum(d['先着']==-1 for d in labels)
        out['到達'][name]=dict(順行到達=good,逆行到達=bad,両側到達=sum(d['順行到達'] and d['逆行到達'] for d in labels),
            順行到達率=good/n,逆行到達率=bad/n,順行先着=first_good,逆行先着=first_bad,未到達=n-first_good-first_bad,
            全入口での順行先着率=first_good/n,到達内順行先着率=first_good/(first_good+first_bad) if first_good+first_bad else None)
    return out


def pct(value: float) -> str:
    """機能: 比率を表示する。

    引数: value(float)。返り値: 百分率(str)。
    """
    return f'{value*100:.1f}%'


def main() -> None:
    """機能: 訂正された限界値定義を結果前固定し、全281判断を再採点する。

    引数: なし。返り値: なし(None)。入口・方向・実取引の損益は変更しない。
    """
    target=HERE/'最大順行と入口採点.json'
    assert not target.exists(),'既存限界値採点は上書きしません'
    source=json.loads((HERE/'方向採点.json').read_text(encoding='utf-8'))
    save(HERE/'限界値採点前固定.json',dict(時刻=datetime.now(timezone.utc).isoformat(),ユーザー訂正='時間単位ではなく判断後の最大上昇/下落幅を知りたい',
        評価='発注判断中値から、同セッション保存通常区間末まで。固定保有時間と実返済時刻では切らない。',
        主指標='最大順行の中央値/分布と0.05/0.10/0.20%到達率。対称逆行より先か・最高値以前の逆行を併記。',
        起点='前回3候補で実際に新規判断した同じ281行と方向。手数料・気配差を含まない。',
        最大値前逆行='正の最大順行値に最初に到達した原本行まで。順行0なら該当なし。',
        限界='事後採点でのみ未来価格を参照。最高値を事前に予測したものでも実現利益でもない。',
        幅=WIDTHS,コードSHA=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        入力SHA={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (HERE/'方向採点.json',HERE.parent/'wave_v60/inputs.pkl',HERE.parent/'wave_v60/quotes.pkl')},現在API=0))
    inputs=pickle.loads((HERE.parent/'wave_v60/inputs.pkl').read_bytes())
    quotes=pickle.loads((HERE.parent/'wave_v60/quotes.pkl').read_bytes())
    rows=[]
    for old in source['rows']:
        row={k:v for k,v in old.items() if k!='scores'};key=(row['session'],row['symbol']);ready=inputs[key]
        assert np.all(ready['time_s']<ready['limit']+300)
        assert quotes[key]['mid'][row['decision_i']]==row['decision_mid']
        row['extent']=measure(quotes[key]['mid'],row['decision_i'],row['side'],ready['tick'])
        if row['extent']['最大順行行'] is not None:
            peak=row['extent']['最大順行行'];row['extent']['最大順行原本行']=int(ready['seq'][peak])
        rows.append(row)
    methods=[]
    for old in source['methods']:
        m={k:v for k,v in old.items() if k!='summary'}
        m['summary']={s:summarize([r for r in rows if r['method']==m['id'] and r['symbol']==s]) for s in ('TOPIX','NK225')}
        methods.append(m)
    assert len(rows)==281
    packet=dict(methods=methods,rows=rows,新規数=281,除外数=0,採点単位='価格幅、全て同セッション内')
    save(target,packet);save(OUT/'最大順行と入口採点.json',packet)
    # ----------------------------------------
    # 固定時間版は参考資料へ移し、主説明を限界値の採点へ変更する。
    shutil.copyfile(OUT/'入口の方向予測精度.html',OUT/'参考_固定時間の方向採点.html')
    table=[];reach=[]
    for m in methods:
        for symbol,a in m['summary'].items():
            point=a['最大順行']['中央値'];adverse=a['最大順行前の逆行']['中央値'];label=a['到達']['0.10']
            table.append(f'<tr><th>候補{m["number"]}</th><td>{symbol}</td><td>{a["新規数"]}</td><td>{point:,.2f}</td><td>{pct(a["最大順行割合"]["中央値"])}</td><td>{adverse:,.2f}</td><td>{pct(a["一呼値順行率"])}</td><td>{pct(label["順行到達率"])} ({label["順行到達"]})</td><td>{pct(label["逆行到達率"])} ({label["逆行到達"]})</td><td>{pct(label["全入口での順行先着率"])} ({label["順行先着"]})</td></tr>')
            reach.append(f'<tr><th>候補{m["number"]} {symbol}</th>'+''.join(f'<td>{pct(a["到達"][f"{w*100:.2f}"]["順行到達率"])}</td><td>{pct(a["到達"][f"{w*100:.2f}"]["全入口での順行先着率"])}</td>' for w in WIDTHS)+'</tr>')
    document='''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>入口後の最大順行と方向の精度</title><style>:root{color-scheme:dark}body{margin:0;background:#0d1420;color:#e6eef8;font:16px/1.7 system-ui,'Yu Gothic',sans-serif}main{max-width:1300px;margin:auto;padding:26px}h1{font-size:27px}h2{font-size:21px}.card{background:#152132;border:1px solid #344960;border-radius:12px;padding:20px;margin:22px 0}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;white-space:nowrap;font-size:14px}td,th{padding:10px;border-bottom:1px solid #35485c;text-align:right}th:first-child{text-align:left}thead{background:#20334a}.sub{font-size:14px;color:#a7bad1}a{color:#91caff}code{font-size:12px;overflow-wrap:anywhere}@media(max-width:650px){main{padding:15px}h1{font-size:23px}}</style><!--
[コンポーネント概要]
main は固定保有時間を使わない、最大順行と逆行の事後採点です。
.scroll は価格幅と到達率の表を横へスクロールできる領域です。
.card は採点の定義、主表、幅別の到達をまとめる章です。
--><main><p class="sub">作業00061 · 既知25セッション · 前回3候補の281新規判断</p><h1>方向を見定めた後、最大でどこまで動いたか</h1><p>固定の保有時間では区切りません。判断から同じセッションの末までの経路を使い、買い判断なら最高中値までの上昇幅、売り判断なら最低中値までの下落幅を測ります。実際の返済後の価格も含む、入口だけの事後採点です。</p><section class="card"><h2>最大順行と、その前の逆行</h2><p>値幅の単位はTOPIXがpt、NKが円。金額倍率と枚数は関係させません。中央値は「半数の入口で、これ以上の順行があった」幅です。</p><div class="scroll"><table><thead><tr><th>入口</th><th>銘柄</th><th>新規数</th><th>最大順行 中央値</th><th>価格比 中央値</th><th>最大値前の逆行 中央値</th><th>1呼値でも順行</th><th>0.10%順行へ到達</th><th>0.10%逆行も到達</th><th>順行0.10%が先</th></tr></thead><tbody>'''+''.join(table)+'''</tbody></table></div><p class="sub">到達率の分母は同じ全新規数。括弧は件数。0.10%幅は判断価格×0.10%をラージ呼値へ切り上げます。先着は上/下の対称幅で、未到達も分母に含めます。</p></section><section class="card"><h2>どの程度まで進む割合か</h2><div class="scroll"><table><thead><tr><th>入口/銘柄</th><th>0.05% 到達</th><th>同幅順行が先</th><th>0.10% 到達</th><th>同幅順行が先</th><th>0.20% 到達</th><th>同幅順行が先</th></tr></thead><tbody>'''+''.join(reach)+'''</tbody></table></div><p>単に一度でも進んだ割合が高くても、先に大きく逆行した入口を含みます。予測として有用かは、最大順行と、その最大値へ届く前の逆行を一緒に見ます。順行・逆行の両側へ到達する入口もあります。</p></section><section class="card"><h2>3つの入口</h2>'''+''.join(f'<p>候補{m["number"]}：{m["name"]}<br><code>{m["id"]}</code></p>' for m in methods)+'''<p><a href="../00060_決済勝率95パーセントの探索とPDCA/95パーセント探索の説明と全セッション損益.html">元の手法説明と実決済損益</a></p></section><p>最大順行値は事後にしか確定しません。この最大値をすべて利益にできるという計算はしていません。入口の判定に未来の最高値・最安値は使っていません。中値の値幅なので、約定気配差と費用は別です。正の順行がない入口の「最大値前の逆行」は該当なしにしています。</p><p>保存された同一銘柄の原本順を使います。受信時計は不明ですが、今回の限界値には固定の経過時間を使いません。全25場は既知で、将来の方向予測確率の保証ではありません。</p><p><a href="最大順行と入口採点.json">全281入口の限界値JSON</a> · <a href="参考_固定時間の方向採点.html">参考：先に試した固定時間の採点</a> · <a href="README.md">資料案内</a></p></main></html>'''
    (OUT/'入口の方向予測精度.html').write_text(document,encoding='utf-8')
    (OUT/'README.md').write_text('''# 入口の最大順行と方向予測精度

最初に [入口の方向予測精度.html](入口の方向予測精度.html) を見てください。

読む順序：最大順行と最大値前の逆行 → 価格幅別の到達率と対称先着 → [全281入口JSON](最大順行と入口採点.json)。

ユーザーの「時間ではなく判断後の限界値」という訂正を反映しました。固定保有時間と実出口では切らず、同じセッションの保存通常区間末まで測ります。金額・手数料・決済勝率とは分離します。最大値は事後採点専用で、未来値を入口へ入れていません。

[最初に試した固定時間版](参考_固定時間の方向採点.html) は参考として保存しています。同版の採点前固定JSONに「時計超過60秒以上」とある箇所は説明の誤記で、実装は60秒超を除外します。主となる今回の限界値版は、経過時間による終点・除外を使いません。

再現元：`../../work/wave_v64/entry_extent.py`、限界値採点前固定.json。全25場は既知。現在API取得・実注文なし。原本と過去作業は変更していません。
''',encoding='utf-8')
    research=OUT.parent
    index=(research/'index.html').read_text(encoding='utf-8')
    index=index.replace('前回3候補の判断後5〜60分の価格方向と対称幅への先着を採点。','前回3候補の判断後、同じセッション内の最大順行と途中逆行、価格幅別の到達率を採点。')
    (research/'index.html').write_text(index,encoding='utf-8')
    readme=(research/'README.md').read_text(encoding='utf-8').replace('出口・費用を外して、前回3候補の281判断を固定時間と対称先着で採点。','固定時間を使わず、前回3候補の281判断後の最大順行・途中逆行と対称先着を採点。')
    (research/'README.md').write_text(readme,encoding='utf-8')
    for m in methods:
        for symbol,a in m['summary'].items():
            print(m['number'],symbol,json.dumps(a,ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
