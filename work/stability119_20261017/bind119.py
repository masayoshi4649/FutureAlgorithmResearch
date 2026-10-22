"""市場を読む前に、独立人工検査と本番ソースを接続する。"""

import plan119 as plan


def main() -> None:
    """
    機能: 五種類の人工検査と当該実装のSHAを一つの市場前記録へまとめる。
    引数: なし。成功済み証跡だけを参照する。
    返り値: None。原市場、既金融結果、APIを読まない。
    """
    names = [
        'input_artificial119_v2/現在値と気配の資格及び公開後次原row接続の純人工検査.json',
        '十八条件の接頭と相手時計及び六系統分離の純人工_v3.json',
        'design/全玉清算教師の選択と接頭不変の純人工.json',
        'audit_engine119/因果約定と親会計及び実商品指値刻みの独立純人工検査_v2.json',
        'audit_integration119/市場前の252政策接続と選択六場及び三枠数量の純人工_v2.json',
    ]
    proofs = []
    for name in names:
        path = plan.HERE / name
        proof = plan.read(path)
        assert proof['全合格'], name
        proofs.append(dict(path=path.relative_to(plan.ROOT).as_posix(), SHA256=plan.digest(path)))
    plan.write(plan.HERE / '実測前の人工検査.json', dict(全合格=True, source_SHA256=plan.sources(),
        証跡=proofs, 原市場=0, 既金融=0, 新金融=0, API=0))
    print('入力・入口・選択・約定会計・全接続の人工検査を結びました。')


if __name__ == '__main__':
    main()
