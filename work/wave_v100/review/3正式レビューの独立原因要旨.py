"""正式台帳を変えず、独立3証跡の結論と原板例を短い日本語JSONへまとめる。"""

from pathlib import Path

import 共通独立読取 as R


def selected_case(raw: dict, ident: str, session: str, symbol: str, parent: int) -> dict:
    """
    機能: 原板検査済みの代表親だけを説明用に抜き出す。
    引数: raw(dict)、ident/session/symbol(str)、parent(int)。
    返り値: dict。具体seqと価格及び事後原因を残し新規時情報と区別する。
    """
    source = raw['条件別代表'][ident]['原板付き代表親']['|'.join((session, symbol))][str(parent)]
    points = {}
    for label in ('元候補', '発注判断', '実新規', '実返済'):
        value = source['原板'][label]
        points[label] = {name: value[name] for name in ('原本seq', '時刻', 'bid', 'ask')}
    basis = source['実判断格子のLPとBBO別源']['保存59支持列']
    return dict(条件=ident, 場=session, 商品=symbol, 親=parent, 会計と候補=source['親'],
        代表原板=points, 判断と約定の上限=source['判定上限21列'],
        新規時の支持={name: basis[name] for name in ('selected_long_allowed', 'selected_short_allowed',
            'own_lp300_ret_bp', 'peer_lp300_ret_bp', 'own_ofi15_sufficient', 'own_ofi15_ratio',
            'peer_ofi15_sufficient', 'peer_ofi15_ratio')},
        事後MFE=source['正常気配での事後MFE'], 初期S=source['初期停止幅'], 事後原因=source['事後原因分類'])


def main() -> None:
    """
    機能: 完了3レビューを内容指紋へ結び、達成した点と未達を限定した説明を保存する。
    引数: --根許可後(bool)。全31の正式完了通知後だけ実行する。
    返り値: None。新戦略・新条件・主差替え・金融会計変更は一切行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    names = ('全34条件全31の独立親会計と安定性及びNoCap旧620対照一致.json',
        '全34判断価格上限と支持源及び即時の同候補建値差と固有経路の独立分解.json',
        '主とP0及び前16参考と事後RMS上位の最悪3場原板と判断約定上限の独立反証.json')
    paths = [R.HERE / name for name in names]
    account, decomposition, raw = [R.read(path) for path in paths]
    assert all(value['全合格'] and value['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json')
        for value in (account, decomposition, raw))
    primary = fixed['主']
    control = 'P0_L1_C1_A1_X1'
    main_pair = decomposition['比較'][control + '→' + primary]
    whole = main_pair['期間別元候補対応']['全31']
    for symbol in R.SYMBOLS:
        assert whole[symbol]['全経路差円'] == 0
        assert whole[symbol]['元固有親'] == whole[symbol]['新固有親'] == 0
    gate_counts = {}
    for symbol in R.SYMBOLS:
        counted = [value['判断上限'] for key, value in
            decomposition['各口座待機取消消費成立及び上限観測'][primary].items() if key.endswith('|' + symbol)]
        parent_checks = [value for key, value in account['上限全親21列の独立数理'][primary].items()
            if key.endswith('|' + symbol)]
        gate_counts[symbol] = dict(拒否原行数=sum(value['cap_blocked']['原行数'] for value in counted),
            拒否候補数=sum(value['cap_blocked']['候補数'] for value in counted),
            完了親=sum(value['完了親'] for value in parent_checks),
            約定上限超過親=sum(value['約定上限超過親'] for value in parent_checks))
    altered = selected_case(raw, primary, '2026-10-12_Day', 'NK225', 1)
    original = selected_case(raw, control, '2026-10-12_Day', 'NK225', 1)
    diagnostic = 'P05_L0_C1_A1_X1'
    diagnostic_control = 'P0_L0_C1_A1_X1'
    diagnosis = decomposition['比較'][diagnostic_control + '→' + diagnostic]
    cases = [selected_case(raw, primary, '2026-09-29_Night', 'TOPIX', 1),
        selected_case(raw, primary, '2026-09-22_Day', 'TOPIX', 1),
        selected_case(raw, primary, '2026-10-05_Day', 'NK225', 1),
        selected_case(raw, primary, '2026-10-07_Night', 'NK225', 1)]
    summary = dict(全合格=True, 主=primary, 前16固定参考=assembled['selected'], 主変更=False,
        参考事後差替え=False, 会計=dict(口座=account['口座'], 商品期間群=account['商品期間群'],
            注文=account['注文'], 親=account['親'], NoCap旧一致口座=account['NoCap旧口座一致数']),
        両商品金額80=account['両商品金額80'], 活動充足両80=account['活動充足両80'],
        同候補等の検算方向付き比較=decomposition['一軸対照数'], 必須比較群数={
            name: len(values) for name, values in decomposition['必須比較群'].items()},
        主の全31=raw['条件別代表'][primary]['全31安定性と活動'],
        主とP0の同候補恒等差={symbol: {name: whole[symbol][name] for name in (
            '同候補親', '建値改善円', '返済差円', '料金差円', '全経路差円', '厳密同一実新規親',
            '元固有親', '新固有親')} for symbol in R.SYMBOLS}, 主のcap拒否と約定超過=gate_counts,
        主の上限が実経路を変えた例=dict(元=original, 新=altered,
            説明='日経は元候補69110からP0で69190、P1で69180へ新規。返済も69120から69110へ動き、'
                 '10ptの建値改善+1600円と10ptの返済悪化−1600円が相殺、双方−11552円。'
                 '判断時計は双方10:01:43で、後57原行という差を57秒又は真受信待ち時間とは呼ばない。'),
        主の最悪3赤字場=raw['条件別代表'][primary]['最悪3赤字場'],
        主の最悪3場内だけの赤字親原因=raw['条件別代表'][primary]['最悪3場の赤字親原因集計'],
        原板原因代表=cases,
        事後RMS上位の比較=dict(事後対象=diagnostic, 主又は参考の差替えではない=True,
            元=raw['条件別代表'][diagnostic_control]['全31安定性と活動'],
            新=raw['条件別代表'][diagnostic]['全31安定性と活動'],
            同候補と固有経路=diagnosis['期間別元候補対応']['全31'],
            活動及び黒字場遷移=diagnosis['全31場別遷移']),
        結論=[
            '1W上限は主の全損益を改善しませんでした。TOPIXは拒否ゼロ、日経は1候補を実際に遅らせたが'
            '新規と返済の改善悪化が相殺。注文まで全く変わらなかったとは言いません。',
            '主の最悪3場ではTOPIX赤字5親中3親、日経7親中6親が往復料金込み黒字へ一度も届かず、'
            '判断と実fillは全て元候補比1W以内。遠くを追い過ぎたことだけでは損失を説明できません。',
            '残るTOPIX2親・日経1親は黒字を返して負けました。入口不成立型と利益返却型が併存します。'
            '事後の順行やMFEを発注時の既知確度へ戻してはいません。',
            'TOPIX9/22の両LP上昇と両15秒OFI買い優勢、日経10/5の両LP下落と両OFI売り優勢は'
            '当時正常でも負けています。現在までの共通方向の観測は、その後の持続の保証ではありません。',
            '事後RMS上位の半W旧支持はTOPIXで旧勝ち47332円を逃し、避けた旧損失は668円だけ。'
            '日経では旧負け20256円を避けたが、双方とも最大利益日除外は赤字。毎場安定の達成ではありません。',
            '両商品金額利益80%は0。全31既知の結果であり未知期間の安定性を保証しません。'],
        独立原本証拠=dict(原本数=len(raw['原本同seq照合']),
            同seq照合=sum(value['同seq照合'] for value in raw['原本同seq照合'].values())),
        scope='親会計/料金/8期間/安定性/同候補恒等式は独立再計算。原板は少数原因の直接照合。'
              '全raw清算時価及び全潜在最初triggerは別担当。保存cap20/政策40全行を独立再生したとは言わない。',
        SHA256={path.relative_to(R.ROOT).as_posix(): R.digest(path) for path in paths + [Path(__file__)]},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance())
    R.save('3正式レビューの独立原因要旨.json', summary)
    print('100の3独立証跡を数値同値と注文不変を分けた要旨へ保存。新戦略再生0。', flush=True)


if __name__ == '__main__':
    main()
