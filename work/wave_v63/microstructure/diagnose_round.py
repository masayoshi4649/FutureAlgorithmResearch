"""短期板のラウンド結果を集計し、勝率と収支の交換を見える形にする。"""

import argparse
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent


def main(round_number: int) -> None:
    """機能: 達成件数と一軸改良の差を保存し、次のPDCAへ渡す。

    引数: round_number(int)。返り値: なし(None)。売買条件を変更しない。
    """
    result=json.loads((HERE/f'round{round_number}'/'集計結果.json').read_text(encoding='utf-8'))
    output={}
    for s in ('TOPIX','NK225'):
        rows=[dict(id=m['id'],config=m['config'],**m['summary'][s]) for m in result['methods']]
        ranked=sorted(rows,key=lambda x:(x['cycles']<20,x['net']<=0,-(x['win_rate'] or 0),-(x['pf'] or 0),-x['net']))
        output[s]=dict(件数=len(rows),黒字=sum(x['net']>0 for x in rows),勝率95実測=sum(x['win95_observed'] for x in rows),
            損小利大を伴う95=sum(x['goal95'] for x in rows),十分さ目安も達成=sum(x['goal95_with_sample'] for x in rows),上位=ranked[:5])
    if round_number==2:
        earlier=json.loads((HERE/'round1'/'集計結果.json').read_text(encoding='utf-8'))
        lookup={m['id']:m for m in earlier['methods']}
        differences=[]
        for m in result['methods']:
            base=lookup[m['config']['control_id']]
            differences.append(dict(id=m['id'],対照=base['id'],改良=m['config']['treatment'],
                変化={s:dict(収支=m['summary'][s]['net']-base['summary'][s]['net'],
                    勝率=(m['summary'][s]['win_rate'] or 0)-(base['summary'][s]['win_rate'] or 0),
                    組数=m['summary'][s]['cycles']-base['summary'][s]['cycles']) for s in ('TOPIX','NK225')}))
        output['一軸改良差']=differences
    (HERE/f'round{round_number}'/'PDCA評価.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({s:{k:v for k,v in out.items() if k!='上位'} | dict(上位=[{k:x[k] for k in ('id','net','win_rate','cycles','payoff','pf','active_sessions')} for x in out['上位']]) for s,out in output.items() if s in ('TOPIX','NK225')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--round',type=int)
    main(parser.parse_args().round)
