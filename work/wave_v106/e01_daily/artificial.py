"""実新規UID、部分返済、当時停止判断の小人工を保存する。"""

import numpy as np

import catalog
import common
import core
import reference


def fixture(symbol: str = 'TOPIX') -> tuple[dict, np.ndarray, np.ndarray]:
    """
    機能: 2UID・部分返済・不正気配・後続親のある私有素材を作る。
    引数: symbol(str)は商品。実相場や保存金融を使用しない。
    返り値: tuple[dict,ndarray,ndarray]は気配、実注文、UID。
    """
    bid = np.array([100., 100., 100., 100.5, 101.5, np.nan, 100.5, 103.5, 103.5, 103.5])
    ask = bid+.5; valid = np.isfinite(bid)
    q = dict(bid=bid, ask=ask, quote_valid=valid, seq=np.arange(100, 110, dtype=np.int64),
        time_s=np.arange(10, dtype=float))
    orders = np.array([[1, 0, 0, 1, 5, ask[1], 1, 1], [2, 1, 0, 1, 2, ask[2], 1, 1],
        [3, 2, 0, -1, 3, bid[3], 2, 0], [7, 6, 0, -1, 4, bid[7], 2, 0],
        [8, 7, 1, 1, 5, ask[8], 1, 1], [9, 8, 1, -1, 5, bid[9], 2, 0]], float)
    return q, orders, np.array([0, 1, -1, -1, 2, -1], np.int64)


def run() -> None:
    """
    機能: 注文接頭・UID別切捨て・次気配・無取引と未来不変を人工で確認する。
    引数: なし。
    返り値: None。全金融結果は読まず新しい人工証跡だけを保存する。
    """
    checks = []
    q, orders, uids = fixture()
    base = core.reconstruct(('人工', 'TOPIX'), orders, uids, q)
    np.testing.assert_array_equal(base['reserved_exit_fees'][:4], [0, 209, 292, 166])
    reference.check_reserved(base, base, 'TOPIX')
    checks.append('UID別残返済料209/292/166円。残4枚の合算167円にしない')
    checks.append('旧残返済料sourceの2関数だけAST接続し、人工全行料金と4定数が同値')
    assert base['cumulative_fees'][2] == 292 and base['cumulative_fees'][3] == 417
    checks.append('新規料金は全額先払い。部分返済料は実注文125円')
    policy = dict(profit_ticks=1, loss_ticks=None)
    stopped = core.apply_policy(base, q, policy)
    assert stopped['control']['判断行'] == 4 and stopped['control']['返済行'] == 6
    np.testing.assert_array_equal(stopped['exit_target_uids'][-2:], [0, 1])
    np.testing.assert_array_equal(stopped['orders'][-2:, 4], [2, 2])
    np.testing.assert_array_equal(stopped['order_fees'][-2:], [83, 83])
    assert stopped['summary']['費用'] == 583 and stopped['summary']['収支'] == -583
    checks.append('目標到達3417円でも次正常気配への悪化を含め最終-583円')
    checks.append('部分返済後2UIDを別注文返済。将来親と元返済を取消')
    np.testing.assert_allclose(stopped['equity_yen'][:5], base['equity_yen'][:5])
    np.testing.assert_array_equal(stopped['orders'][:3], orders[:3])
    checks.append('到達行まで元fillとentryfeeを完全保持')
    changed_q = {k: v.copy() for k, v in q.items()}
    changed_q['bid'][7:] += 100.; changed_q['ask'][7:] += 100.
    changed_orders = orders.copy()
    for order in changed_orders:
        if order[0] >= 7:
            order[5] = changed_q['ask' if order[3] > 0 else 'bid'][int(order[0])]
    changed = core.reconstruct(('人工', 'TOPIX'), changed_orders, uids, changed_q)
    final = core.apply_policy(changed, changed_q, policy)
    np.testing.assert_array_equal(final['orders'], stopped['orders'])
    assert final['control'] == stopped['control']
    checks.append('停止後の価格・元将来約定・将来利益変更でも判断と新返済不変')
    # ----------------------------------------
    reflected_q = {k: v.copy() for k, v in q.items()}
    reflected_q['bid'], reflected_q['ask'] = 300-q['ask'], 300-q['bid']
    reflected = orders.copy(); reflected[:, 3] *= -1; reflected[:, 5] = 300-orders[:, 5]
    mirror = core.apply_policy(core.reconstruct(('人工', 'TOPIX'), reflected, uids, reflected_q), reflected_q, policy)
    np.testing.assert_allclose(mirror['liquidation_yen'], stopped['liquidation_yen'])
    assert mirror['summary']['収支'] == stopped['summary']['収支']
    checks.append('買売とbid/ask反射で同じ時刻・収支・UID清算')
    no_hit = core.apply_policy(base, q, dict(profit_ticks=100, loss_ticks=None))
    np.testing.assert_array_equal(no_hit['orders'], orders)
    assert not no_hit['control']['発動']
    checks.append('閾値未到達は元実注文を同値再会計')
    empty = core.reconstruct(('人工', 'TOPIX'), np.empty((0, 8)), np.empty(0, np.int64), q)
    never = core.apply_policy(empty, q, policy)
    assert never['summary']['親数'] == never['summary']['収支'] == 0 and not never['control']['発動']
    checks.append('無取引を黒字や勝ちに含めない')
    losses_q = {k: v.copy() for k, v in q.items()}; losses_q['bid'][4] = 97.5; losses_q['ask'][4] = 98.
    loss_base = core.reconstruct(('人工', 'TOPIX'), orders, uids, losses_q)
    loss_stop = core.apply_policy(loss_base, losses_q, dict(profit_ticks=100, loss_ticks=4))
    assert loss_stop['control']['種別'] == '損失予算' and loss_stop['control']['判断行'] == 4
    checks.append('当時料金後清算の損失予算到達と次正常気配を別記録')
    flat_orders = np.array([[1, 0, 0, 1, 5, q['ask'][1], 1, 1], [4, 3, 0, -1, 5, q['bid'][4], 2, 0]], float)
    flat = core.apply_policy(core.reconstruct(('人工', 'TOPIX'), flat_orders, np.array([0, -1]), q), q, policy)
    assert flat['control']['判断行'] == 4 and flat['control']['返済行'] == 4
    assert flat['control']['残UID別注文数'] == 0 and len(flat['orders']) == 2
    checks.append('到達行で既に全返済なら同じ行の実返済を保持し追加注文ゼロ')
    nk_q, nk_orders, nk_uids = fixture('NK225')
    nk_q['bid'] *= 20; nk_q['ask'] *= 20; nk_orders[:, 5] *= 20
    nk = core.reconstruct(('人工', 'NK225'), nk_orders, nk_uids, nk_q)
    assert nk['summary']['費用'] == int(nk_orders[:, 4].sum()*11)
    checks.append('NKマイクロ片道11円・TOPmini片道41.8円の注文別課金')
    assert len(catalog.CONFIGS) == len({c['id'] for c in catalog.CONFIGS}) == 12
    assert {c['profit_ticks'] for c in catalog.CONFIGS} == {1, 2, 4}
    assert {c['loss_ticks'] for c in catalog.CONFIGS} == {4, 8, 16, None}
    checks.append('目標3種類×損失予算4種類の固定12条件')
    common.write(common.HERE/'UID別場内停止の人工検査_第二固定.json', dict(全合格=True, 検査数=len(checks),
        検査=checks, 実装SHA256=common.source_hashes(), 正式金融読取=0, 金融再生=0, 原本再読取=0, API=0))
    print(f'小人工{len(checks)}項目合格。正式金融0', flush=True)


if __name__ == '__main__':
    run()
