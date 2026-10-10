"""改良理由を固定し、過去ラウンドの実装を保存して次の対照条件を作る。"""

import argparse
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent


def save_previous_code(round_number: int) -> None:
    """機能: 既に計算したラウンドの元コードをSHA照合後に別保存する。

    引数: round_number(int)。返り値: なし(None)。固定仕様は変更しない。
    """
    destination=HERE/f'round{round_number}'/'code'
    destination.mkdir(exist_ok=True)
    frozen=json.loads((destination.parent/'実行前固定.json').read_text(encoding='utf-8'))
    for name in ('core.py','run.py'):
        path=HERE/name
        assert hashlib.sha256(path.read_bytes()).hexdigest()==frozen['SHA'][str(path)]
        (destination/name).write_bytes(path.read_bytes())


def prepare_round2() -> None:
    """機能: 微小な利確幅と反復費用の問題に対し、一軸対照条件を固定する。

    引数: なし。返り値: なし(None)。新しい結果の計算前に保存する。
    """
    path=HERE/'round2'
    path.mkdir(exist_ok=True)
    target=path/'条件案.json'
    assert not target.exists()
    previous=json.loads((HERE/'round1'/'集計結果.json').read_text(encoding='utf-8'))
    bases=[m['config'] for m in previous['methods'] if m['config']['target'] in (8,16) and m['config']['hold']==600]
    assert len(bases)==12
    conditions=[]
    for base in bases:
        for treatment,change in (('対照',{}),('方向反転',dict(direction=-1)),('利益保護',dict(protect=1)),
            ('保有30分',dict(hold=1800)),('休止60秒',dict(cooldown=60)),('休止300秒',dict(cooldown=300))):
            c=dict(base,**change)
            c['id']=base['id'].replace('M1_','M2_')+'_'+treatment
            c['control_id']=base['id']
            c['treatment']=treatment
            conditions.append(c)
    document=dict(理由='R1は1tick気配差を越える優位が弱く、連打で損失を増やした。方向を逆にした対照、利益保護、時間余裕、再突入を減らす休止を、一軸だけ変えて分ける。',
        当てはまりから追加した新条件=False,条件の列挙基準='結果の金額順位を見ず、両機構全3強さの8/4と16/8、H600を全て基準にする。',conditions=conditions)
    target.write_text(json.dumps(document,ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'第2ラウンド{len(conditions)}条件を先に固定')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--archive',type=int)
    parser.add_argument('--prepare-round2',action='store_true')
    args=parser.parse_args()
    save_previous_code(args.archive) if args.archive else prepare_round2()
