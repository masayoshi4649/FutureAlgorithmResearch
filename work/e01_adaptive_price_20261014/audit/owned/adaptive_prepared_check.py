"""新源完成前に、公開票による許容固定の純参照と反例を保存する。"""

from copy import deepcopy
from decimal import Decimal
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import traceback
import adaptive_reference as reference

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
OLD = ROOT/'work/e01_improve_20261014/audit/owned/fak_reference.py'
spec = importlib.util.spec_from_file_location('旧純参照',OLD)
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)


def published(vote: dict, base: float, threshold: float) -> tuple[bool,int]:
    """
    機能: 公開時の既知票と入口方向釣合いだけから門と許容0/1を決める。
    引数: vote(dict) は既知・方向票・釣合い、base/threshold(float) は門と適応閾値。
    返り値: tuple[bool,int] は入口門と当公開予約の許容。未来票は受け取らない。
    """
    known = vote['known'] and math.isfinite(vote['balance'])
    accepted = known and vote['direction_votes'] >= 2 and vote['balance'] >= base
    allowance = int(accepted and vote['balance'] >= threshold)
    return accepted, allowance


def main() -> None:
    """
    機能: 完成前新源の import を避け、境界・定数同値・未来反例を純人工で先に固定する。
    引数: なし。旧独立純参照だけを比較元として使う。
    返り値: None。自所有証跡へ保存し、完成新経済 source の合格とは呼ばない。
    """
    target = HERE/'公開balance適応閾値と予約固定の純参照.json'
    failed = HERE/'公開balance適応の純参照False.json'
    assert not target.exists() and not failed.exists()
    try:
        truth=[]; constant=[]; future=[]
        values=(-1.,0.,.25,math.nextafter(.5,0),.5,math.nextafter(.75,0),.75,math.nextafter(.75,1),math.nextafter(1.,0),1.)
        for base in (.25,.5):
            for threshold in (.75,1.):
                for known in (False,True):
                    for count in (0,1,2,4,20):
                        for balance in values:
                            vote=dict(known=known,direction_votes=count,balance=balance)
                            gate,allowed=published(vote,base,threshold)
                            expected=known and count>=2 and Decimal(str(balance))>=Decimal(str(base))
                            eallow=int(expected and Decimal(str(balance))>=Decimal(str(threshold)))
                            assert (gate,allowed)==(expected,eallow)
                            truth.append(dict(base=base,threshold=threshold,**vote,accepted=gate,adverse_ticks=allowed))
        kinds=('再参加数量','通常同値','静観と第一正常が同列','紙上全返済と第一正常が同列',
               '紙上全返済だけが先着','累積部分返済','部分返済待機の重複防止','価格内の拡幅',
               '第一正常の前に不正気配','期限と第一正常が同列')
        fields=('orders','accepts','states','fee_curve','attempts','anchor','uid_count')
        for symbol in ('TOPIX','NK225'):
            for side in (1,-1):
                for kind in kinds:
                    source=reference.fixture(symbol,side,kind)
                    for allowance in (0,1):
                        mapping={r['row']:allowance for r in source['rows']}
                        actual=reference.run(source,'FAK0',adverse_by_publication=mapping)
                        prior=old.run(source,'FAK1' if allowance else 'FAK0')
                        for field in fields:
                            assert actual[field]==prior[field],(symbol,side,kind,allowance,field)
                        constant.append(dict(symbol=symbol,side=side,kind=kind,adverse=allowance,exact=True))
                source=reference.fixture(symbol,side,'再参加数量')
                for initial in (0,1):
                    mapping={r['row']:1-initial for r in source['rows']};mapping[1]=initial
                    actual=reference.run(source,'FAK0',adverse_by_publication=mapping)
                    # 第一正常の同じ気配でも公開許容だけで成立又は失効を決める。
                    assert actual['attempts'][0]['filled']==bool(initial)
                    assert actual['anchor']['row']==1 and actual['anchor']['selected_quantity']==3
                    # 試行当行やその先の許容を反転しても、公開1行の予約は同一である。
                    future_mapping=dict(mapping)
                    for row in range(2,len(source['rows'])):
                        future_mapping[row]=1-mapping[row]
                    altered=reference.run(source,'FAK0',adverse_by_publication=future_mapping)
                    for field in ('states','fee_curve'):
                        assert actual[field][:6]==altered[field][:6]
                    assert actual['attempts'][0]==altered['attempts'][0]
                    assert actual['anchor']==altered['anchor']
                    assert [o for o in actual['orders'] if o['row']<=5]==[o for o in altered['orders'] if o['row']<=5]
                    # 当行許容を誤用する仮実装なら期待と反転する反例である。
                    wrong=dict(mapping);wrong[1]=mapping[2]
                    bad=reference.run(source,'FAK0',adverse_by_publication=wrong)
                    assert bad['attempts'][0]['filled']!=actual['attempts'][0]['filled']
                    # 未来気配だけが悪化しても公開受理、選択qと固定アンカーは不変。
                    quote=deepcopy(source)
                    quote['rows'][2]['bid']+=side*source['tick']*100
                    quote['rows'][2]['ask']+=side*source['tick']*100
                    qresult=reference.run(quote,'FAK0',adverse_by_publication=mapping)
                    assert actual['accepts'][0]==qresult['accepts'][0] and actual['anchor']==qresult['anchor']
                    assert not qresult['attempts'][0]['filled']
                    future.append(dict(symbol=symbol,side=side,initial_adverse=initial,
                        後続許容変更で初予約不変=True,試行票で再選択すると成否が反転=True,
                        未来quote悪化で公開qアンカー不変=True,未約定取消後もanchor保持=True))
        assert len(truth)==400 and len(constant)==80 and len(future)==8
        output=dict(全合格=True,状態='新 source 完成前の純参照のみ。正式 source・金融の合格ではない。',
            真偽表=truth,全0全1と旧定数の独立参照同値=constant,未来反例=future,
            留保=['baseG25/G50の既知・二票・釣合い条件を通った公開だけが対象。許容は後の強さや気配から変更しない。',
                '1T許容を強支持へ与える目的は勝機消失との折衷であり、強支持が価格続伸を保証する論理ではない。',
                '公開 .75/1.0 は同じ既知33の原因を見た後の探索。未来未知日や全場安定の証明ではない。',
                '許容0でも発注側の価格が同じなら反対気配の悪化・拡幅を防げない。幅審査は今回部品外。',
                '未約定初受理 q/ATR の尺度が後参加と異なる問題は不変で、取消後に再アンカーしない。',
                '経済源が完成したら全12配列・Python/JIT・接頭を別証跡で束縛する。'],
            sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            referenceSHA256=hashlib.sha256((HERE/'adaptive_reference.py').read_bytes()).hexdigest(),
            oldReferenceSHA256=hashlib.sha256(OLD.read_bytes()).hexdigest(),
            新源import=0,入力=0,台帳=0,金融=0,原板=0,NPZ=0,API=0,旧源又は共有変更=0)
        target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,真偽表=400,定数同値=80,未来反例=8,
            SHA256=hashlib.sha256(target.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        failed.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),自動再実行=False,
            新源import=0,入力=0,金融=0,台帳=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__=='__main__':
    main()
