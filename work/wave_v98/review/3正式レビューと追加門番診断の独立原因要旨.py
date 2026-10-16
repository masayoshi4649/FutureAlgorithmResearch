"""34条件の正式独立検算と追加門番診断を、売買を変えず短い原因要旨へまとめる。"""

from pathlib import Path

import 共通独立読取 as R


def main() -> None:
    """
    機能: 完了した三正式レビュー及び追加原因診断の指紋と結論を統合する。
    引数: --根許可後(bool)は全31正式完了の根通知後に必須。
    返り値: None。結果後の条件・主・参考変更及び取引再生は行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    files = (
        '全34条件全31の独立親会計と安定性及びC0旧対照一致.json',
        '全34待機の同候補建値差と勝ち刈り及び固有経路の独立分解.json',
        '主と参考及びC0即時の最悪3場原板と政策休止及び門番の独立反証.json',
        '主TOPIXの押し回復と旧J2が重ならない具体的独立原因.json',
    )
    proofs = [R.read(R.HERE / name) for name in files]
    assert all(value['全合格'] for value in proofs)
    assert all(value['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json') for value in proofs)
    account, cause, boards, gate = proofs
    assert account['口座'] == 2108 and cause['口座'] == 2108
    short = {}
    for old, new in (('C0_A7_X3', 'C1_A7_X3'), ('C1_A7_X3', 'C2_A7_X3'),
                     ('C1_A7_X3', 'C3_A7_X3'), ('A0_X3', 'C1_A7_X3'),
                     ('C0_A1_X1', 'C1_A1_X1'), ('C1_A1_X1', 'C2_A1_X1'),
                     ('C1_A1_X1', 'C3_A1_X1')):
        key = old + '→' + new
        short[key] = {}
        for symbol in R.SYMBOLS:
            value = cause['比較'][key]['期間別元候補対応']['全31'][symbol]
            fields = ('元収支円', '新収支円', '同候補親', '建値改善円', '返済差円', '料金差円',
                '同候補収支差円', '元固有親', '新固有親', '逃した元固有利益円',
                '避けた元固有損失円', '新固有利益円', '新固有損失円')
            short[key][symbol] = {name: value[name] for name in fields}
    stability = {ident: dict(全31=assembled['results'][ident]['periods']['全31'],
        全31安定性=account['独立安定性'][ident]['全31']) for ident in
        ('C0_A7_X3', 'C1_A7_X3', 'C2_A7_X3', 'C3_A7_X3', 'A0_X1', 'A0_X3',
         'C1_A1_X1', 'C2_A1_X1', 'C3_A1_X1')}
    primary_points = []
    for day in boards['最悪3場'][fixed['主']]['NK225']:
        for parent in day['大損3親']:
            primary_points.append(dict(場=day['場'], 純額円=parent['純額円'],
                新規時刻=parent['実新規原板']['時刻'], 新規原seq=parent['実新規原板']['原本seq'],
                新規価格=parent['新規価格'], 返済時刻=parent['実返済原板']['時刻'],
                返済原seq=parent['実返済原板']['原本seq'], 返済価格=parent['返済価格'],
                事後保有中最良清算変位pt=parent['事後保有中の最良清算変位pt']))
    R.save('3正式レビューと追加門番診断の独立原因要旨.json', dict(
        全合格=True, 条件数=34, 独立口座=2108, 注文=account['注文'], 完了親=account['親'],
        商品期間群=544, 一軸対照=114, 主=fixed['主'], 前16固定参考=assembled['selected'],
        両商品金額80=account['両商品金額80'], 活動充足両80=account['活動充足両80'],
        主変更=False, 新策略再生=0, 条件追加=0,
        原因結論=[
            'CurrentPriceTime gapの取消を外しても、主A7はTOP0親。NKは旧共通2親が完全同額のまま新規3負け−33,056円を追加した。',
            'C2の各anchor seq更新へ変更しても主の全5親は同額。時計の緩和が常に取得価格又は期待値を改善するわけではない。',
            'C3は主NKの新規3負けを除き旧2負けへ戻しただけ。主での建値改善、既存赤字の利益化、利益追加は0。',
            'TOP回復成立は203保存変化点・異なる2候補。148点で両BBO進行まで成立したが、全203点で旧NK300秒mid窓が不明のためJ2が拒否した。',
            'このTOP拒否は実方向の反転と同義ではない。独立LPが正常な点もあるが、両気配進行不足・逆OFI・LP方向不同が残る点もある。',
            'A1ではgap取消除去により新固有親が両商品とも合計黒字になった。入力取消の是正自体を価値なしと一般化できない。',
            'それでも全34の両金額80は0。無取引と少活動を安定収益の成功へ置換しない。'],
        重要会計差=short, 主と主要対照の安定性=stability, 主NK最悪3場の原板=primary_points,
        TOP回復門番の追加根拠=gate['四政策局所反証']['C1_A7_X3'],
        検証範囲=dict(
            経済='全2108口座の注文・親・料金・源・売買方向・8期間・安定性及びC0全620旧口座一致。',
            局所観測='三正式レビュー38原本487seq、追加門番4原本30seqをそれぞれ直接照合。重複があるため合計独自件数とは呼ばない。',
            内部='保存watch極値を所与とする幾何検算と回復成立点のJ2/BBO局所反証。40政策状態及び補助10旗の全行独立再現は未証明。',
            時間='今回の再生clockはCurrentPriceTime由来。真受信時計と二市場の共通受信順は未観測。未来不変は代理公開順仮定内。'),
        次段の未検証='正常LPによる現在J2の価格資格と今回待機機構を組み合わせる一軸対照は今回未測定。BBO/OFI資格をLPで救済せず、取引増・逃した勝ち・新規負けを全会計へ含める必要がある。',
        根拠SHA256={name: R.digest(R.HERE / name) for name in files},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))


if __name__ == '__main__':
    main()
