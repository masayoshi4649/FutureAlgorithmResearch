"""玉別利益追尾の比較と全セッション損益を、短い暗色レポートへまとめる。"""

from collections import defaultdict
from datetime import datetime
from html import escape
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
OLD=ROOT/'work/staged137_20261022'
PUBLIC=ROOT/'アルゴリズム調査/00138_玉別の利益トレーリング比較'
sys.path.insert(0,str(OLD))
from report137 import measure
from run138 import read, settings


def names():
    """
    機能: 各固定条件の短い日本語名を生成する。
    引数: なし。
    返り値: dict[str,str]は手法名。
    """
    out={'B05':'5枚一括・元の出口','B02':'2枚固定・元の出口','Wparent':'2枚→3枚追加・元の出口',
         'CWparent':'時計と支持で1/2/5枚→補充・元の出口'}
    for c in settings():
        stem='2枚先行' if c['base']=='Wparent' else '時計配分'
        label=f"{stem}／追加が{c['activation']:g}R順行後、{c['width']:g}R戻りで"
        label+=f"最大{c['protect']}枚を返済" if c['protect'] else '追加残数を返済'
        if c['tighten_at']:
            label+=f"（{c['tighten_at']:g}R順行から幅{c['tight_width']:g}R）"
        out[c['id']]=label
    return out


def stamp(value):
    """
    機能: 原価格の時刻を日本時間へ変換する。
    引数: value(float)はUNIX秒。
    返り値: strは秒付き時刻。
    """
    return datetime.fromtimestamp(float(value),ZoneInfo('Asia/Tokyo')).strftime('%H:%M:%S')


def collect():
    """
    機能: 保存結果を集計し、追加だけの変化を親ごとに対比する。
    引数: なし。
    返り値: tupleは分類済み場会計・比較集計・親差分。
    """
    data=read(HERE/'結果.json');groups=defaultdict(list)
    for path,allowed in ((OLD/'結果.json',{'B05','B02'}),(OLD/'結果3.json',{'Wparent','CWparent'})):
        for row in read(path)['rows']:
            if row['method'] in allowed:groups[row['method']].append(row)
    for row in data['rows']:groups[row['method']].append(row)
    summary={key:{kind:measure([r for r in rows if kind=='全体' or r['kind']==kind])
                  for kind in ('全体','Day','Night')} for key,rows in groups.items()}
    deltas={}
    for c in settings():
        base={r['session']:r for r in groups[c['base']]};changes=[];flip=[];legs=[]
        for row in groups[c['id']]:
            b=base[row['session']];bp={p['id']:p for p in b['parents']}
            if (row['net']>0)!=(b['net']>0):
                flip.append(dict(session=row['session'],before=b['net'],after=row['net']))
            for p in row['parents']:
                if '1' in p['legs']:
                    old=bp[p['id']]['legs']['1']['net'];new=p['legs']['1']['net'];legs.append(new)
                    changes.append(dict(session=row['session'],parent=p['id'],side=p['side'],before=old,after=new,
                                        difference=new-old,parent_before=bp[p['id']]['net'],parent_after=p['net']))
        positive=sorted((v for v in legs if v>0),reverse=True)
        deltas[c['id']]=dict(base=c['base'],changes=changes,flipped=flip,
            added_net=sum(legs),added_wins=sum(v>0 for v in legs),added_losses=sum(v<0 for v in legs),
            added_top3_removed=sum(legs)-sum(positive[:3]),
            better=sum(x['difference']>0 for x in changes),worse=sum(x['difference']<0 for x in changes),
            avoided_loss=sum(x['difference'] for x in changes if x['before']<0),
            old_winner_change=sum(x['difference'] for x in changes if x['before']>0))
    return groups,summary,deltas


def examples(method, changes):
    """
    機能: 改善と悪化の最大例を、保存された入口・出口・判断時刻へ結び付ける。
    引数: method(str)、changes(list[dict])は比較対象。
    返り値: list[dict]は事後診断用の具体例。当時の判断には使用しない。
    """
    plan=read(HERE/'試行計画.json');config=next(c for c in settings() if c['id']==method)
    chosen=sorted(changes,key=lambda x:x['difference'],reverse=True)[:2]+sorted(changes,key=lambda x:x['difference'])[:2]
    output=[];seen=set()
    for change in chosen:
        scene=change['session'];parent=change['parent']
        if (scene,parent) in seen:continue
        seen.add((scene,parent));item=next(x for x in plan['inputs'] if x['session']==scene)
        packet=pickle.loads((ROOT/item['input']['path']).read_bytes());key=(scene,'NK225')
        ready=packet['inputs'][key];ts=ready['time_s']
        with np.load(HERE/'measurement'/f'{scene}.npz',allow_pickle=False) as f:new=f[method]
        b=next(x for x in plan['baselines'] if x['session']==scene)
        with np.load(ROOT/b['path'],allow_pickle=False) as f:old=f[config['base']]
        entry=old[(old[:,2]==parent)&(old[:,8]==0)&(old[:,7]==1)][0]
        detail=dict(change,risk=max(20.,float(ready['atr'][int(entry[1])])),before_orders=[],after_orders=[])
        for label,orders in (('before_orders',old),('after_orders',new)):
            for o in orders[(orders[:,2]==parent)&(orders[:,8]==1)]:
                detail[label].append(dict(fill=stamp(ts[int(o[0])]),decision=stamp(ts[int(o[1])]),
                    side=int(o[3]),quantity=int(o[4]),price=float(o[5]),new=bool(o[7]),reason=int(o[6])))
        output.append(detail)
    return output


def yen(value):
    """
    機能: 金額を桁区切り付きで表示する。
    引数: value(float)は円額。
    返り値: strは符号付き表示。
    """
    return f'{value:+,.0f}'


def render():
    """
    機能: 全条件・全45場と確定した結論文をHTMLへ公開する。
    引数: なし。結論.jsonのshortlist/paragraphsは検証後の説明。
    返り値: None。金融結果は書き換えない。
    """
    groups,summary,deltas=collect();labels=names();PUBLIC.mkdir(parents=True,exist_ok=True)
    decision=read(HERE/'結論.json') if (HERE/'結論.json').exists() else dict(
        headline='追撃玉の利益追尾を比較',paragraphs=['24条件・既知45場の比較結果。'],shortlist=['B05','Wparent','CWparent'])
    concrete={m:examples(m,deltas[m]['changes']) for m in decision['shortlist'] if m in deltas}
    report=dict(summary=summary,comparisons=deltas,examples=concrete,rows=[r for rows in groups.values() for r in rows],
                settings=settings(),decision=decision)
    (PUBLIC/'比較集計.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')

    def comparison(keys):
        """
        機能: 赤字の頻度と大きさを累計と並べる。
        引数: keys(list[str])は表示条件。
        返り値: strは比較表。
        """
        body=[]
        for key in keys:
            s=summary[key]['全体']
            body.append(f'<tr><td>{escape(key)}</td><td>{escape(labels[key])}</td><td>{yen(s["net"])}</td>'
                f'<td>{s["losses"]}/{s["sessions"]}</td><td>{yen(-s["mean_loss"])}</td><td>{yen(-s["max_loss"])}</td><td>{yen(s["top3_removed"])}</td></tr>')
        return '<div class="scroll"><table><thead><tr><th>ID</th><th>内容</th><th>累計円</th><th>赤字場</th><th>赤字場平均円</th><th>最大赤字円</th><th>上位3黒字場を除いた円</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div>'

    sections=[]
    for key,rows in groups.items():
        total=0.;body=[]
        for row in sorted(rows,key=lambda r:r['session']):
            total+=row['net'];style='plus' if row['net']>0 else 'minus'
            body.append(f'<tr><td>{row["session"]}</td><td>{yen(row["profit"])}</td><td>{yen(-row["loss"])}</td><td class="{style}">{yen(row["net"])}</td><td>{yen(total)}</td></tr>')
        s=summary[key]['全体'];body.append(f'<tr class="total"><td>全45場</td><td>{yen(s["profit"])}</td><td>{yen(-s["loss"])}</td><td>{yen(s["net"])}</td><td>{yen(total)}</td></tr>')
        sections.append(f'<details><summary>{escape(key)}：{escape(labels[key])} ／ 累計{yen(total)}円</summary><div class="scroll"><table><thead><tr><th>セッション</th><th>利益円</th><th>損失円</th><th>収支円</th><th>累計円</th></tr></thead><tbody>'+''.join(body)+'</tbody></table></div></details>')
    details=[]
    for method,items in concrete.items():
        for x in items:
            def order_text(o):
                """
                機能: 一注文を短い日本語へ整形する。
                引数: o(dict)は保存注文。
                返り値: strは説明。
                """
                return f'{o["fill"]} {"新規" if o["new"] else "返済"}{"買" if o["side"]>0 else "売"}{o["quantity"]}枚 @{o["price"]:,.0f}'
            details.append(f'<li><b>{escape(method)} / {x["session"]}</b>：追撃分 {yen(x["before"])}→{yen(x["after"])}円。'
                f'<br>従来：{escape("、".join(order_text(o) for o in x["before_orders"]))}'
                f'<br>変更：{escape("、".join(order_text(o) for o in x["after_orders"]))}</li>')
    html='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>玉別の利益トレーリングと全セッション損益</title><style>
    :root{color-scheme:dark;font-family:"Yu Gothic UI",Meiryo,sans-serif;background:#101722;color:#e7edf5}body{margin:0}main{max-width:1400px;margin:auto;padding:24px}h1{font-size:26px}h2{font-size:20px;margin-top:30px}p,li{line-height:1.8}a{color:#8fc6ff}table{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}th,td{border-bottom:1px solid #354255;padding:10px;text-align:right;white-space:nowrap}th:first-child,td:first-child,td:nth-child(2){text-align:left}th{background:#233044;position:sticky;top:0}.scroll{overflow:auto}details{background:#192435;border:1px solid #354255;padding:12px;margin:10px 0}summary{cursor:pointer}.plus{color:#8ce4bd}.minus{color:#ff9f9f}.total{font-weight:bold;background:#26354b}.note{color:#b7c4d7;font-size:14px}.callout{border-left:4px solid #80bcff;padding:5px 16px;background:#1b293d}
    </style></head><body><main><!--
    [コンポーネント概要]
    .callout は結論と売買ルールです。.scroll は横に長い比較表と各場表です。
    details は比較全条件・売買例・各手法の45場結果を開閉します。外部通信や売買機能はありません。
    --><h1>玉別の利益トレーリング</h1>'''
    html+=f'<div class="callout"><b>{escape(decision["headline"])}</b>'+''.join(f'<p>{escape(p)}</p>' for p in decision['paragraphs'])+'</div>'
    html+='<p class="note">日経mini・片方向上限10枚、主担当最大5枚。9/21デイ〜10/21デイの同じ45場、手数料込み。初回と追撃の入口を固定し、追撃の出口だけ変更。24新条件＋保存済み4対照。</p>'
    html+='<h2>主要比較</h2>'+comparison(decision['shortlist'])
    html+='<details><summary>全28条件の比較</summary>'+comparison(list(groups))+'</details>'
    html+='<details><summary>具体的に守れた利益・逃した利益</summary><ul>'+''.join(details)+'</ul></details>'
    html+='<h2>各セッションの利益・損失・収支</h2><p class="note">利益・損失は初回＋追撃を一組として手数料後損益を正負に分けたもの。相殺前の個別返済益・損失とは区別します。各手法名を開くと全45場を表示します。</p>'+''.join(sections)
    html+='<details><summary>計算条件と限界</summary><p>R=max(初回の判断時点で公表済みのATR,20円)。追撃自身の建値から、買いはbid・売りはaskで順行幅を測定。追撃前の高値・安値は使いません。起動後の返済線は利益方向へだけ動かします。</p><p>初回玉の従来損切り・部分返済は維持。追撃保護は一度で、利確後の再補充はしません。元親の返済が同じ原行なら優先し、最後は場内で全返済します。逆指値判断後の次正常気配で約定するため、利益床を割り込むことがあります。</p><p>日経ラージ気配を約定の代理に使用。実mini気配、5秒の最悪遅延、稼働Go本体での数量フィードバックは未検証。既知45場の条件比較で、今後の利益を保証する結果ではありません。段階を増やして2→1→1→1枚と追撃する入口変更と、初回の損切り拡大も今回は未検証です。</p><p><a href="README.md">再現資料と監査</a> ／ <a href="比較集計.json">全数値</a></p></details></main></body></html>'
    (PUBLIC/'玉別の利益トレーリングと全セッション損益.html').write_text(html,encoding='utf-8')
    concise={key:{k:v for k,v in s['全体'].items() if k in ('net','losses','mean_loss','max_loss','top3_removed')} for key,s in summary.items()}
    print(json.dumps(concise,ensure_ascii=False,indent=2))


if __name__=='__main__':render()
