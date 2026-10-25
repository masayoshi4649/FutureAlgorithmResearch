"""原板診断後の比較を、昼夜と標本範囲を分けて再集計する。"""

import json
import sys
from pathlib import Path
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'work/aggressive140_20261024'))
from analyze140 import stats


def read(path):
    """
    機能: 保存JSONをUTF-8で読む。
    引数: path(Path)は読取資料。
    返り値: dict/listは保存内容。
    """
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def aggregate(rows, names):
    """
    機能: 全50・診断3・対照47、昼夜、上昇下落で集計する。
    引数: rows(list[dict])は場別会計、names(dict)は表示名。
    返り値: tuple[list,list]は全体と分割統計。
    """
    summary=[];parts=[]
    for scope in ('all','known','new'):
        scope_rows=[r for r in rows if scope=='all' or (r['session']>='2026-10-22_Night')==(scope=='new')]
        for symbol,method in sorted({(r['symbol'],r['method']) for r in scope_rows}):
            chosen=[r for r in scope_rows if r['symbol']==symbol and r['method']==method]
            summary.append(stats(chosen,method,symbol,scope,names.get(method,method)))
            for group in ('Day','Night','上昇','下落'):
                selected=[r for r in chosen if r['kind']==group] if group in ('Day','Night') else [r for r in chosen if r['market_change']*(1 if group=='上昇' else -1)>0]
                if selected:parts.append(dict(stats(selected,method,symbol,scope,names.get(method,method)),group=group))
    return summary,parts


def main():
    """
    機能: 全条件比較を作り、昼夜の改修候補と副作用を短く表示する。
    引数: なし。
    返り値: None。金融注文は再実行せず、保存会計だけを読む。
    """
    result=read(HERE/('結果141_二巡統合.json' if (HERE/'結果141_二巡統合.json').exists() else '結果141.json'));plan=read(HERE/'試行計画141_v2.json')
    names={'B5':'従来基準','S36':'前回の追加手法を独立併用','C33':'前回の反転を先着併用'}
    names.update({c['id']:c['name'] for c in plan['configs']['active']+plan['configs']['supplement']})
    names.update(plan['configs']['core_exit'])
    if (HERE/'結果141_二巡統合.json').exists():
        second=read(HERE/'第二巡計画141.json')
        names.update({c['id']:c['name'] for c in second['configs']['active']+second['configs']['supplement']})
    rows=[r for r in result['rows'] if not r['method'].startswith('A_')]
    summary,parts=aggregate(rows,names)
    (HERE/'比較集計141.json').write_text(json.dumps(dict(summary=summary,parts=parts,names=names),ensure_ascii=False,indent=2),encoding='utf-8')
    for symbol in ('NK225','TOPIX'):
        for kind in ('Day','Night'):
            selected=[s for s in parts if s['symbol']==symbol and s['group']==kind and s['scope']=='all']
            print(symbol,kind,flush=True)
            ranked=sorted(selected,key=lambda s:(s['flat']>0,s['losses'],s['avg_loss'],-s['ex_top3']))
            show=[s for s in selected if s['method'] in ('B5','S36','C33')]+ranked[:6]
            for s in show:
                print({k:s[k] for k in ('method','net','losses','flat','avg_loss','worst','ex_top3','entries')},flush=True)
    print('診断3場',flush=True)
    for symbol in ('NK225','TOPIX'):
        selected=[s for s in summary if s['symbol']==symbol and s['scope']=='new']
        for s in sorted(selected,key=lambda x:-x['net']):
            print({k:s[k] for k in ('symbol','method','net','losses','flat')},flush=True)


if __name__=='__main__':
    main()
