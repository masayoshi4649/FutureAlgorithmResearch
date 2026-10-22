"""検証済み状態機械へ固定価格の段間隔と利確後の段数再準備を加える。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main() -> None:
    """
    機能: 旧源を変更せず、明示した差分だけを新しい経済源へ適用する。
    引数: なし。
    返り値: None。人工及び実市場の再生は行わない。
    """
    old=ROOT/'work/stability120_20261017/recovery_e1/engine120e1.py'
    raw=old.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='5fcecd4aa8061ce4be46291e90bfd7d912b11dbd0c1f7f7e3e535b34f346830a'
    source=raw.decode('utf-8').replace('\r\n','\n')
    replacements=[
        ('observed_tick,fraction,mode,trail,','observed_tick,unit,mode,trail,spacing,reset_after_profit,'),
        ('cap/mode(int)、multiplier/fee/observed_tick/fraction/trail/場内時刻(float)。',
         'cap/mode(int)、multiplier/fee/observed_tick/unit/trail/spacing/場内時刻(float)、reset_after_profit(bool)。'),
        ('assert cap>0 and mode in (0,1,2) and observed_tick>0. and fraction>0. and trail>0.',
         'assert cap>0 and mode==2 and observed_tick>0. and unit>0. and trail>0. and spacing>0.'),
        ('    price=np.zeros((2,cap))',
         '    level=np.zeros((2,cap),np.int64)\n    for ss in range(2):\n        for jj in range(cap):\n            level[ss,jj]=jj\n    held_level=np.zeros((2,cap),np.int64)\n    reset_row=np.full(2,-1,np.int64)\n    profit_reset=np.zeros(2,np.bool_)\n    price=np.zeros((2,cap))'),
        ('            step=max(observed_tick,math.floor(mid*fraction/observed_tick+.5)*observed_tick)',
         '            step=unit'),
        ('        # 既判断の返済を先に実行する。新規同行の返済と価格線での架空約定は行わない。\n',
         '        # 既判断の返済を先に実行する。新規同行の返済と価格線での架空約定は行わない。\n        profit_reset[:]=False\n'),
        ('dtime[s,j],now,xp,fee_one,why[s,j],j,1.,dmid[s,j],reference,',
         'dtime[s,j],now,xp,fee_one,why[s,j],held_level[s,j],1.,dmid[s,j],reference,'),
        ('np.array([uid[s,j],side,j,edrow[s,j],erow[s,j],',
         'np.array([uid[s,j],side,held_level[s,j],edrow[s,j],erow[s,j],'),
        ('                state[s,j]=0\n                anchor[s,j]=reference\n        if phase==3',
         '''                if reset_after_profit and why[s,j]==1 and net>0.:
                    profit_reset[s]=True
                state[s,j]=0
                anchor[s,j]=reference
        # ----------------------------------------
        # 利確した方向の未約定だけ、物理枠と独立した段数をゼロから振り直す。
        # 保有済みの建値・UID・利益最高値と反対方向は変更しない。
        for s in range(2):
            if not profit_reset[s]:
                continue
            next_level=0
            for j in range(cap):
                if state[s,j]>=2:
                    continue
                if state[s,j]==1:
                    canceled+=1
                state[s,j]=0
                anchor[s,j]=reference
                level[s,j]=next_level
                next_level+=1
            reset_row[s]=raw
        if phase==3'''),
        ('                price[s,j]=xp',
         '                price[s,j]=xp\n                held_level[s,j]=level[s,j]'),
        ('dtime[s,j],now,xp,fee_one,0.,j,1.,dmid[s,j],reference,',
         'dtime[s,j],now,xp,fee_one,0.,held_level[s,j],1.,dmid[s,j],reference,'),
        ('            anchor[:,:]=reference\n            basket_peak=0.\n            basket_armed=False\n            saturated=False\n\n        # ----------------------------------------\n        # 全玉を返済側',
         '            anchor[:,:]=reference\n            for ss in range(2):\n                for jj in range(cap):\n                    level[ss,jj]=jj\n            basket_peak=0.\n            basket_armed=False\n            saturated=False\n\n        # ----------------------------------------\n        # 全玉を返済側'),
        ('        for s in range(2):\n            side=1 if s==0 else -1\n            for j in range(cap):\n                if state[s,j]!=0:',
         '        for s in range(2):\n            side=1 if s==0 else -1\n            if raw==reset_row[s]:\n                continue\n            for j in range(cap):\n                if state[s,j]!=0:'),
        ('                line=anchor[s,j]+side*(3.+j)*step',
         '                line=anchor[s,j]+side*(3.+level[s,j]*spacing)*step'),
    ]
    changes=[]
    for before,after in replacements:
        assert source.count(before)==1,(before,source.count(before))
        source=source.replace(before,after,1)
        changes.append({'before':before,'after':after})
    source=source.replace('"""利益カバーを個別に外さず、全玉の清算純益で組を返済する独立状態機械。"""',
        '"""固定段間隔と利益玉の五ポイント追尾及び方向別段数再準備の比較。"""')
    target=HERE/'engine121.py'
    if target.exists():
        assert target.read_bytes()==source.encode('utf-8')
    else:
        target.write_bytes(source.encode('utf-8'))
    (HERE/'源の最小差分.json').write_text(json.dumps({'source':str(old.relative_to(ROOT)),
        'source_sha256':hashlib.sha256(raw).hexdigest(),'engine_sha256':hashlib.sha256(target.read_bytes()).hexdigest(),
        'changes':changes,'financial_accounts':0},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('固定価格・段間隔・方向別段数再準備の源だけを作成。金融0。')


if __name__=='__main__':
    main()
