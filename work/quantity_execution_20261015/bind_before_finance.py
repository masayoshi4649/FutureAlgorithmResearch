"""金融前の人工と独立監査を現在の九実装へ束縛する。"""

import argparse
from pathlib import Path

import plan


def main() -> None:
    """
    機能: 所有者人工・独立検算の指紋を現在源と照合し、正式固定の前提を作る。
    引数: コマンドラインのfinal(Path) は独立監査の九源接続JSON。
    返り値: None。金融・入力本文・保存event本文は0。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('final', type=Path)
    args = parser.parse_args()
    paths = [
        plan.HERE / '数量公開からmarket全量と半分追尾へ接続する人工検査_v2.json',
        plan.HERE / 'audit/owned/完成三源と純会計及び場境界の独立接続まとめ.json',
        plan.HERE / 'metrics/注文別floor料と完結親金額及び全場分母の純人工.json',
        plan.HERE / 'audit/metrics/注文別料と親脚金額及び全場三基準の独立SOURCE_ONLY確認.json',
        plan.HERE / 'rootの可逆保存と時刻型の人工.json',
        args.final.resolve()]
    current = plan.sources()
    by_name = {Path(k).name: (k,v) for k,v in current.items()}
    assert len(by_name) == len(current) == 9
    evidence, covered = [], set()
    for path in paths:
        proof = plan.read(path)
        assert proof['全合格'] is True
        for key, sha in proof['source_SHA256'].items():
            name = Path(key).name
            if name in by_name:
                canonical, wanted = by_name[name]
                assert wanted == sha, (path.name, key)
                covered.add(canonical)
        evidence.append(dict(path=path.relative_to(plan.ROOT).as_posix(), SHA256=plan.digest(path)))
    assert covered == set(current)
    final = plan.read(args.final)
    assert final['source_SHA256'] == current
    plan.write(plan.HERE / '金融初読前の人工と独立監査.json', dict(
        全合格=True, 新金融=0, 原NPZ=0, 保存eventNPZ=0, API=0,
        source_SHA256=current, evidence=evidence,
        留保='人工と会計接続の合格であり、収益性や受信時計の正しさを証明しない。',
        旧成功='root診断だけ追加前の人工・SOURCE_ONLY停止初版も消さず保存。'))
    print('九source・六証跡を正式固定前に接続。金融と入力本文は0。')


if __name__ == '__main__':
    main()
