"""現在支持の観測是正と安定収益の成否を分けた、正式結果後の短い原因要旨。"""

from pathlib import Path

import 共通独立読取 as R


def summary_metric(result: dict, symbol: str) -> dict:
    """
    機能: 総収益だけで改善扱いしないため活動と赤字の深さをまとめる。
    引数: result(dict)、symbol(str)。
    返り値: dict。無取引を黒字へ数えず最大利益日除外も併記する。
    """
    value, stable = result['periods']['全31'][symbol], result['stability']['全31'][symbol]
    return dict(利益円=value['profit'], 損失円=value['loss'], 収支円=value['net'],
        親数=value['campaigns'], 黒字場=value['positive_sessions'], 赤字場=value['losing_sessions'],
        活動場=value['active_sessions'], 無取引場=value['no_trade_sessions'], 金額利益割合=value['profit_share'],
        活動黒字率=stable['positive_session_rate'], 平均赤字円=stable['mean_losing_session_yen'],
        最大赤字円=stable['worst_session_loss_yen'], 下方偏差=stable['downside_rms_units'],
        最大利益日除外収支円=value['without_best_day']['net'])


def main() -> None:
    """
    機能: 三正式独立レビューの原板・会計・安定性から原因要旨を新reviewへ保存する。
    引数: --根許可後(bool)は全31正式完了の通知後に必須。
    返り値: None。新条件、主差替え、未来の入口制限の損益計算は行わない。
    """
    R.permission()
    fixed, assembled = R.validate()
    names = ('全34条件全31の独立親会計と安定性及びL0旧対照一致.json',
        '全34現在支持の同候補建値差と勝ち刈り及び固有経路の独立分解.json',
        '主と参考及び現在支持対照の最悪3場原板と源及び再準備の独立反証.json')
    account, cause, board = [R.read(R.HERE / name) for name in names]
    assert all(value['全合格'] and value['根集計SHA256'] == R.digest(R.WORK / 'analysis/比較結果.json')
        for value in (account, cause, board))
    primary = assembled['results'][fixed['主']]
    top_loss = board['最悪3場'][fixed['主']]['TOPIX'][0]['大損3親'][0]
    entry = top_loss['入口保存診断']
    assert entry['candidate_quote'] == 4063.5 and entry['fill_price'] == 4080.
    assert top_loss['候補から発注秒'] == 296.
    chase = dict(場='2026-09-24_Night', 方向='買い', 元候補価格=entry['candidate_quote'],
        候補時刻=top_loss['元候補原板']['時刻'], 候補原seq=top_loss['元候補原板']['原本seq'],
        局所有利peak=entry['favorable_peak'], 局所不利extreme=entry['opposite_extreme'],
        局所押しpt=entry['favorable_peak']-entry['opposite_extreme'], 必要押しW=entry['pullback_width'],
        局所回復pt=entry['trigger_quote']-entry['opposite_extreme'], 必要回復幅=entry['recovery_width'],
        支持格子時刻=R.clock(top_loss['現在支持の公表格子と別源原板']['支持59保存列']['grid_time']),
        候補から支持格子秒=295., 候補から実発注秒=top_loss['候補から発注秒'],
        発注時刻=top_loss['発注判断原板']['時刻'], 発注原seq=top_loss['発注判断原板']['原本seq'],
        発注quote=entry['trigger_quote'], 候補から発注の不利上乗せpt=top_loss['候補から発注の方向付き進行pt'],
        実新規時刻=top_loss['実新規原板']['時刻'], 実新規原seq=top_loss['実新規原板']['原本seq'],
        実新規価格=entry['fill_price'], 候補から実建値の不利上乗せpt=16.5,
        返済時刻=top_loss['実返済原板']['時刻'], 返済原seq=top_loss['実返済原板']['原本seq'],
        返済価格=top_loss['返済価格'], 初期停止S=top_loss['初期S'], 追尾D=top_loss['利益追尾D'],
        事後保有中の最良清算変位pt=top_loss['事後保有中の最良清算変位pt'], 純額円=top_loss['純額円'],
        解釈='局所peakからの押し回復は成立したが、元候補より16.5pt高く買った。押し回復と有利な取得価格は別。')
    counter = []
    for day in board['最悪3場'][fixed['主']]['NK225']:
        if day['場'] != '2026-09-28_Day': continue
        for parent in day['大損3親']:
            if parent['親'] != 2: continue
            d = parent['入口保存診断']
            assert d['candidate_quote'] == d['fill_price'] == 66660.
            counter.append(dict(場=day['場'], 候補時刻=parent['元候補原板']['時刻'],
                候補原seq=parent['元候補原板']['原本seq'], 元候補quote=66660.,
                新規時刻=parent['実新規原板']['時刻'], 新規原seq=parent['実新規原板']['原本seq'],
                実建値=66660., 返済時刻=parent['実返済原板']['時刻'],
                返済原seq=parent['実返済原板']['原本seq'], 返済価格=parent['返済価格'],
                MFE清算pt=parent['事後保有中の最良清算変位pt'], 初期S=parent['初期S'],
                利益保護発火の必要2S=2*parent['初期S'], 純額円=parent['純額円'],
                解釈='元候補と同値の買いでも損失。新規後100pt順行したが2S140ptの保護条件には届かなかった。追っ掛けだけで全損失を説明できない。'))
    assert len(counter) == 1
    pairs = {}
    fields = ('元収支円', '新収支円', '同候補親', '建値改善円', '返済差円', '料金差円',
        '同候補収支差円', '元固有親', '新固有親', '逃した元固有利益円', '避けた元固有損失円',
        '新固有利益円', '新固有損失円')
    for name in ('L0_C1_A7_X3→L1_C1_A7_X3', 'L0_C1_A1_X1→L1_C1_A1_X1',
                 'L0_C3_A7_X3→L1_C3_A7_X3', 'L0_C3_A1_X1→L1_C3_A1_X1'):
        pairs[name] = {s: {k: cause['比較'][name]['期間別元候補対応']['全31'][s][k] for k in fields}
            for s in R.SYMBOLS}
    metrics = {name: {s: summary_metric(assembled['results'][name], s) for s in R.SYMBOLS}
        for name in (fixed['主'], 'L0_C1_A1_X1', 'L1_C1_A1_X1', 'L0_C3_A1_X1', 'L1_C3_A1_X1', 'A0_X1')}
    R.save('3正式レビューの独立原因要旨.json', dict(
        全合格=True, 主=fixed['主'], 前16固定参考=assembled['selected'], 主変更=False,
        独立口座=2108, 注文=account['注文'], 完了親=account['親'], 商品期間群=544,
        旧L0及びA0一致口座=1116, 一軸対照=138, 両商品金額80=account['両商品金額80'],
        活動充足両80=account['活動充足両80'],
        結論=[
            '現在支持を独立LPへ替えても毎セッションの安定収益は未達。主TOPは2活動場で1黒字/1赤字、NKは10親に1利益親を含むが8活動場すべて赤字。',
            '主のL0共通NK5親は取得・出口・料金の差0。追加5親の利益6,048円に対して損失46,208円が加わり、活動増は精度改善ではない。',
            'C1A1のTOP黒字場は11/26→12/26に増えたが、最大赤字38,004→73,336円、平均赤字30,979→35,240円、下方偏差も悪化。',
            'C1A1のNKは35→43親・23→25活動場へ増え、黒字9→10場でも赤字14→15場、収支+34,080→−16,736円、最大赤字26,304→39,456円へ悪化。',
            'C3の支持源変更は再準備の時刻・局所peak/armにも作用する。TOP14/NK25候補の保存再準備経路が異なり、最終入口だけの差と説明しない。',
            '安定性の全31事後診断上位はL0_C3_A1_X1/L0_C1_A1_X1。事前参考A0_X1は維持。少活動による円損失縮小と毎場の黒字化を区別する。'],
        主要同候補経済差=pairs, 安定性比較=metrics, 主TOPの局所回復と不利な取得=chase,
        追っ掛けだけが原因ではない具体反例=counter,
        C3保存再準備経路差={s: row['再準備経路が異なる候補']
            for s, row in board['C3現在支持で変わった再準備'].items()},
        原本同seq照合=dict(原本数=len(board['原本同seq照合']),
            独自seq=sum(row['同seq照合'] for row in board['原本同seq照合'].values())),
        検査scope='全親会計・8期間安定性・公開支持59の原LP現在/起点と窓断裂/変位/支持及び旧BBO・実渡し2列SHA。固定LP採用indexからの照合でありasof源採用全過程や政策40の全行独立再現ではない。',
        次の未測定仮説='元候補からの判断quoteの不利な上乗せを入口制限する比較。未実装・未測定で、勝ちも消し得る。判断価格への制限だけでは次気配の実約定上乗せまで保証しない。',
        注意=['全31既知。真受信時計及び両市場共通受信順は未観測、未来不変は代理公開順仮定内。',
            '保有後のMFEを当時の新規条件に戻さない。次仮説の損益を今回の結論へ混ぜない。'],
        根拠SHA256={name: R.digest(R.HERE / name) for name in names},
        計算コードSHA256=R.digest(Path(__file__)), **R.provenance()))


if __name__ == '__main__':
    main()
