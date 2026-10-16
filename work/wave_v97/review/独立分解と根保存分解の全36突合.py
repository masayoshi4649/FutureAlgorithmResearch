"""独立に完成した原候補分解を、根の別実装保存へ最後に突合する。"""

from pathlib import Path

import 共通独立読取 as R


def close(actual: object, expected: object) -> None:
    """
    機能: 会計数値又は未定義状態の同値を検査する。
    引数: actual/expected(object)は数値又はNone。
    返り値: None。不一致は例外で停止し正答へ値を合わせない。
    """
    assert actual is None and expected is None or actual is not None and expected is not None \
        and abs(float(actual) - float(expected)) < 1e-4, (actual, expected)


def main() -> None:
    """
    機能: 正式親から完成済みの独立36分解を、根の別計算出力と全商品で突合する。
    引数: --根許可後(bool)は根の全31完了通知後のみ必須。
    返り値: None。根の出力や分解関数を独立計算の入力又は正答生成に使わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    own_path = R.HERE / '全36待機の同候補建値差と勝ち刈り及び固有経路の独立分解.json'
    root_path = R.WORK / 'analysis/待機の実建値差と旧勝ちの取り逃し及び新固有親.json'
    own, root = R.read(own_path), R.read(root_path)
    assert own['全合格'] and root['全合格'] and root['条件数'] == 36
    pairs = {'old_net': '元収支円', 'new_net': '新収支円', 'net_change': '全経路差円',
        '同候補親': '同候補親', '有利建値親': '有利建値親', '不利建値親': '不利建値親', '同値親': '同値建値親',
        '建値改善円': '建値改善円', '返済差円': '返済差円', '同候補収支差': '同候補収支差円',
        '平均待機秒': '平均待機秒', '旧固有勝ち円': '逃した元固有利益円',
        '旧固有負け円': '避けた元固有損失円', '新固有親': '新固有親', '新固有収支': '新固有収支円'}
    checked = 0
    for config in fixed['条件']:
        ident = config['id']; immediate = 'A0_' + ident.split('_')[1]
        for symbol in R.SYMBOLS:
            wanted = root['comparison'][ident][symbol]
            if ident == immediate:
                metric = assembled['results'][ident]['periods']['全31'][symbol]
                close(wanted['old_net'], metric['net']); close(wanted['new_net'], metric['net'])
                close(wanted['同候補親'], metric['campaigns']); close(wanted['同値親'], metric['campaigns'])
                for name in ('net_change', '有利建値親', '不利建値親', '建値改善円', '返済差円',
                        '同候補収支差', '旧固有勝ち親', '旧固有勝ち円', '旧固有負け親',
                        '旧固有負け円', '新固有親', '新固有収支'):
                    close(wanted[name], 0.)
                close(wanted['平均待機秒'], 0. if metric['campaigns'] else None)
            else:
                value = own['比較'][immediate + '→' + ident]['期間別元候補対応']['全31'][symbol]
                for root_name, independent_name in pairs.items():
                    close(wanted[root_name], value[independent_name])
                close(value['料金差円'], 0.)
                close(wanted['旧固有勝ち親'], sum(v['純額円'] > 1e-5 for v in value['元固有一覧']))
                close(wanted['旧固有負け親'], sum(v['純額円'] < -1e-5 for v in value['元固有一覧']))
                assert wanted['同候補符号変化'].keys() == value['同候補符号変化'].keys()
                for name, cohort in value['同候補符号変化'].items():
                    close(wanted['同候補符号変化'][name]['親'], cohort['親'])
                    close(wanted['同候補符号変化'][name]['収支差'], cohort['差円'])
            checked += 1
    R.save('独立元候補分解と根別保存の全36商品突合.json', dict(
        全合格=True, 条件数=36, 商品比較=checked,
        方式='独立注文/親会計分解を先に完成してから根別実装の保存と突合。根の分解実装を正答計算へ委譲しない。',
        根拠SHA256={str(path.relative_to(R.ROOT)): R.digest(path) for path in (own_path, root_path)},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))
    print('独立分解と根別保存の全36×両商品72比較が一致。', flush=True)


if __name__ == '__main__':
    main()
