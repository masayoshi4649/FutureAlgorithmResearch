"""同じ銘柄の安定性と活動量を分けて集計し、保留場を見る前に候補を固定する。"""

import argparse
from pathlib import Path
import json
import numpy as np

HERE=Path(__file__).resolve().parent


def read(name):
    """
    機能: 今回の結果資料を読む。
    引数: name(str)は作業域内の相対パス。
    返り値: dict/listはJSON内容。
    """
    return json.loads((HERE/name).read_text(encoding='utf-8-sig'))


def save(name,data):
    """
    機能: 元の結果を変えず集計資料を新規保存する。
    引数: name(str)、data(dict/list)は保存先と内容。
    返り値: None。
    """
    with (HERE/name).open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2,allow_nan=False)


def stats(rows,method,symbol,scope='known',name=''):
    """
    機能: 場ごとの黒赤、通常損失、大勝ち除外、活動を計算する。
    引数: rows(list[dict])、method/symbol/scope/name(str)は対象と表示名。
    返り値: dictは銘柄内で比較する指標。
    """
    net=np.asarray([r['net'] for r in rows]);negative=net[net<0];positive=net[net>0]
    first=[r['first_minutes'] for r in rows if r['first_minutes'] is not None]
    return dict(method=method,name=name,symbol=symbol,scope=scope,sessions=len(rows),wins=int(sum(net>0)),
        losses=int(sum(net<0)),flat=int(sum(r['entries']==0 for r in rows)),net=float(net.sum()),
        profit=sum(r['profit'] for r in rows),loss=sum(r['loss'] for r in rows),median=float(np.median(net)),
        worst=float(net.min()),avg_loss=float(-negative.mean()) if len(negative) else 0.,
        median_loss=float(-np.median(negative)) if len(negative) else 0.,avg_win=float(positive.mean()) if len(positive) else 0.,
        ex_top3=float(net.sum()-np.sort(positive)[-3:].sum()),entries=sum(r['entries'] for r in rows),
        first_minutes=float(np.mean(first)) if first else None,held_minutes=float(np.mean([r['held_minutes'] for r in rows])),
        max_per_side=max(r['max_per_side'] for r in rows),fees=sum(r['fees'] for r in rows))


def names():
    """
    機能: 固定計画から簡潔な手法名を作る。
    引数: なし。
    返り値: dict[str,str]は手法IDと表示名。
    """
    plan=read('試行計画140_v2.json');result={'B5':'現行基準：T06／T04・U06'}
    for c in plan['configs']['reentry']:result[c['id']]='利確後再参加：'+c['name']
    for c in plan['configs']['active']:
        title=f"{c['window']}分／{c['name']}／最大{c['maximum']}枚"
        result[c['id']]=title
        result['C'+c['id'][1:]]='現行と先着採用：'+title
    return result


def summarize():
    """
    機能: 既知場だけの候補比較を保存し、次の分析に使う順位を表示する。
    引数: なし。
    返り値: None。選択自体は読取り後に別ファイルへ固定する。
    """
    rows=read('known/結果140.json')['rows'];labels=names();summary=[];parts=[]
    for symbol in ('NK225','TOPIX'):
        for method in sorted({r['method'] for r in rows}):
            selected=[r for r in rows if r['symbol']==symbol and r['method']==method]
            summary.append(stats(selected,method,symbol,name=labels[method]))
            for field,values in [('kind',['Day','Night']),('market',['上昇','下落'])]:
                for value in values:
                    subset=[r for r in selected if (r['kind']==value if field=='kind' else (r['market_change']>0 if value=='上昇' else r['market_change']<0))]
                    if subset:parts.append(dict(stats(subset,method,symbol,name=labels[method]),group=value))
        result=[r for r in summary if r['symbol']==symbol]
        print(symbol,'安定性順',flush=True)
        ranked=sorted(result,key=lambda x:(x['flat']>0,x['losses'],-x['ex_top3'],-x['median']))[:12]
        for s in ranked:print({k:s[k] for k in ('method','net','wins','losses','flat','avg_loss','worst','ex_top3','entries','first_minutes')},flush=True)
    save('known_summary140.json',dict(summary=summary,parts=parts))


if __name__=='__main__':
    summarize()
