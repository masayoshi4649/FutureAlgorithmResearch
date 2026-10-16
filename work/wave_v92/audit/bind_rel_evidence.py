"""完了した全場検算と、独立した中心解除取消の補足反例を指紋付きで接続する。"""

from pathlib import Path

import common
import full


def main():
    """
    機能: 全2232口座検算へ初回監査失敗・補足適用・正負例と未来不変の証跡を併記する。
    引数: なし。
    返り値: None。会計・売買・凍結資料を変更せず監査証跡だけ接続する。
    """
    target = common.HERE/'全36条件全31場の回復と中心帰還及び全原板清算会計の独立検算.json'
    supplement = common.HERE/'中心解除取消の原入力と最初成立及び先約定の補足監査.json'
    proof,fixture = full.read(target),full.read(supplement)
    assert proof['全合格'] and fixture['全合格']
    assert proof['検査件数']['口座']==2232 and proof['検査件数']['商品期間集計']==576
    for evidence in (proof,fixture):
        for relative,digest in evidence['SHA256'].items():
            assert common.sha(common.ROOT/relative)==digest,relative
    fixed = full.read(common.WORK/'事前固定.json')
    for relative,digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT/relative)==digest,relative
    proof['独立監査の補足'].update(
        最初の失敗と適用範囲=fixture['最初の失敗と適用範囲'],
        人工正例数=len(fixture['人工正例']),人工故障を拒絶=fixture['人工故障を拒絶'],
        新競合枝の未来不変=fixture['新競合枝の未来不変'],
        全原板と最初成立の独立検算を省略しない=True,
        正式売買又は結果の修正ではなく監査契約の補足=True)
    proof['SHA256'].update(common.fingerprint([Path(__file__),supplement,
        common.HERE/'rel_supplement_checks.py',common.HERE/'protocol_rel.py',common.HERE/'run_full_rel.py']))
    common.save(target.name,proof)
    print(common.sha(target),flush=True)


if __name__=='__main__':
    main()
