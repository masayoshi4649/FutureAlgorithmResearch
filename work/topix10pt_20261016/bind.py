"""十源に入力・特徴・先着・学習・独立接続の証拠を束ねる。"""

import argparse
from pathlib import Path

import plan


def main() -> None:
    """
    機能: 源の現指紋と人工・独立監査を実測前に接続する。
    引数: CLI --independent(Path) は現十源を含む独立証跡。
    返り値: None。市場読取・金融0、旧Falseは削除しない。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--independent',type=Path,required=True)
    args=parser.parse_args()
    current=plan.sources()
    paths=[plan.HERE/'input_artificial/現在値採用と閉足公開及び二入力生成元同値の純人工_v2.json',
        plan.HERE/'特徴量32条件とMA欠測因果及び保存統合の人工検査_v2.json',
        plan.HERE/'十ポイント先着と公開基準及び純future極値の人工検査.json',
        plan.HERE/'学習と固定適用の人工検証.json',args.independent.resolve()]
    evidence=[];covered=set()
    for path in paths:
        value=plan.read(path);assert value['全合格']
        for key,sha in value['source_SHA256'].items():
            matched=[name for name in current if Path(name).name==Path(key).name]
            assert len(matched)==1 and current[matched[0]]==sha,(path,key)
            covered.add(matched[0])
        evidence.append(dict(path=path.relative_to(plan.ROOT).as_posix(),SHA256=plan.digest(path)))
    assert covered==set(current) and plan.read(args.independent)['source_SHA256']==current
    plan.write(plan.HERE/'実測前の検査.json',dict(全合格=True,source_SHA256=current,evidence=evidence,
        原NPZ=0,新JSONL=0,新金融=0,API=0,留保='人工合格は市場での成功を意味しない。固定後に対象74入力を各一回測定する。'))
    print('十源の人工と独立接口を接続。市場本文0。')


if __name__=='__main__':main()
