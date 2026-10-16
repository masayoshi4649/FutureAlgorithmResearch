"""非金融採点の現八源へ人工と独立証跡を束ねる。"""

import argparse
from pathlib import Path

import plan


def main() -> None:
    """
    機能: 現八源の人工証跡・独立接続を固定し、本文実測は行わない。
    引数: CLI --independent(Path) は完成した独立監査JSON。
    返り値: None。結果前の証拠を新しい有限JSONへ保存する。
    """
    parser=argparse.ArgumentParser()
    parser.add_argument('--independent',type=Path,required=True)
    args=parser.parse_args()
    current=plan.sources()
    paths=[plan.HERE/'三値幅二起点と共通非重複及び保存統合の人工検査.json',
        plan.HERE/'方向採点の分母と非重複及び固定方向対照の純人工_v2.json',plan.HERE/'結線の人工検証.json',args.independent.resolve()]
    evidence=[]
    for path in paths:
        value=plan.read(path)
        assert value['全合格'] is True
        for key,sha in value.get('source_SHA256',value.get('対象指紋',{})).items():
            matched=[v for k,v in current.items() if Path(k).name==Path(key).name]
            assert len(matched)==1 and matched[0]==sha,(path.name,key)
        evidence.append(dict(path=path.relative_to(plan.ROOT).as_posix(),SHA256=plan.digest(path)))
    assert plan.read(args.independent)['source_SHA256']==current
    plan.write(plan.HERE/'実測前の人工と独立監査.json',dict(全合格=True,新金融=0,
        source_SHA256=current,evidence=evidence,原NPZ=0,保存eventNPZ=0,API=0))
    print('現八源の人工・独立監査を接続。実測0、金融0。')


if __name__=='__main__':main()
