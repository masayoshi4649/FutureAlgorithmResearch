"""反転方向の人工と、変更していない会計部品の証拠を接続する。"""

import argparse
from pathlib import Path

import plan


def main() -> None:
    """
    機能: 現九源へ反転人工・独立接続・同bytes会計の証拠を金融前に束ねる。
    引数: CLI --owner/--independent(Path) は完成した反転人工と独立証跡。
    返り値: None。元会計の人工再実行を有効性の追加標本にしない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--owner', type=Path, required=True)
    parser.add_argument('--independent', type=Path, required=True)
    args = parser.parse_args()
    old = plan.ROOT/'work/quantity_execution_20261015'
    paths = [args.owner.resolve(), args.independent.resolve(),
        plan.HERE/'rootの可逆保存と時刻型の人工.json',
        old/'metrics/注文別floor料と完結親金額及び全場分母の純人工.json',
        old/'audit/metrics/注文別料と親脚金額及び全場三基準の独立SOURCE_ONLY確認.json']
    current = plan.sources()
    by_name = {Path(k).name:(k,v) for k,v in current.items()}
    assert len(by_name) == 9
    evidence, covered = [], set()
    for path in paths:
        value = plan.read(path)
        assert value['全合格'] is True
        for name, digest in value['source_SHA256'].items():
            base = Path(name).name
            if base in by_name:
                canonical, expected = by_name[base]
                assert digest == expected, (path.name, name)
                covered.add(canonical)
        evidence.append(dict(path=path.relative_to(plan.ROOT).as_posix(),SHA256=plan.digest(path)))
    assert covered == set(current)
    assert plan.read(args.independent)['source_SHA256'] == current
    plan.write(plan.HERE/'金融初読前の人工と独立監査.json',dict(
        全合格=True,新金融=0,原NPZ=0,保存eventNPZ=0,API=0,
        source_SHA256=current,evidence=evidence,
        留保='旧会計・入力契約・kernelの同bytes部分は保存人工を再利用。反転の実運転成績はこの後一回だけ測定。'))
    print('反転の現九源と既存会計の証拠を接続。実金融は0。')


if __name__ == '__main__':
    main()
