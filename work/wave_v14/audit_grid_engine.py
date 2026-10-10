"""有限格子の手計算・全玉会計・未来打切りを人工価格列だけで検査する。"""

from pathlib import Path
import hashlib
import json

import numpy as np

import grid_engine as engine

OUT = Path(__file__).resolve().parent


def fixture(prices: list[float], limit: float = 100000., clock: list[float] | None = None) -> dict:
    """機能: セッション・原本順・現在価格を持つ人工再生入力を作る。

    引数: prices (list[float])、limit (float)、clock (list[float]|None)。返り値: 入力 (dict)。
    """
    return dict(seq=np.arange(len(prices), dtype=np.int64),
        time_s=np.asarray(clock if clock is not None else np.arange(len(prices)), dtype=float),
        last=np.asarray(prices, dtype=float), atr=np.full(len(prices), 20.),
        symbol='NK225', session='人工日中', start=0., limit=limit)


def case(name: str, prices: list[float], changes: dict, expected: dict,
         limit: float = 100000., clock: list[float] | None = None) -> tuple[dict, dict]:
    """機能: 独立に計算した期待値と有限格子の結果を比較する。

    引数: name (str)、prices (list[float])、changes/expected (dict)、limit (float)、clock (list|None)。
    返り値: 検査結果・再現入力 (tuple[dict, dict])。
    """
    ready = fixture(prices, limit, clock)
    cfg = dict(engine.DEFAULTS, directions='long', max_legs=1, gap_mode='ticks', gap_value=1.,
               warmup_min=0., entry_deadline_min=0., reset_min=100.)
    cfg.update(changes)
    result = engine.simulate(ready, cfg, detail=True)
    for key, value in expected.items():
        actual = result['incomplete_cycle_ids'] if key == 'incomplete_cycle_ids' else result['summary'][key]
        np.testing.assert_allclose(actual, value, err_msg=name + ':' + key)
    for row in result['raw']:
        assert row[5] > row[4], name + ':新規が条件作成と同じ行'
        assert not row[14] or row[6] > row[5], name + ':返済が新規と同じ行'
    return dict(名称=name, 期待値=expected, 合格=True), dict(ready=ready, config=cfg, result=result)


def equity_at(raw: np.ndarray, ready: dict, length: int) -> np.ndarray:
    """機能: 全脚の過去約定と現在価格だけから、独立に全行の評価損益を作る。

    引数: raw (ndarray)、ready (dict)、length (int)。返り値: 全行評価損益円 (ndarray)。
    """
    curve = np.zeros(length)
    for i in range(length):
        value = 0.
        if not np.isfinite(ready['last'][i]):
            curve[i] = curve[i - 1] if i else 0.
            continue
        for row in raw:
            if row[5] > i:
                continue
            value += row[15] if row[14] and row[6] <= i else row[2] * (ready['last'][i] - row[8])
        curve[i] = value * engine.MULTIPLIERS[ready['symbol']]
    return curve


def prefix(cases: list[dict], all_lengths: bool = True) -> tuple[int, int]:
    """機能: 未来の原本を削除し、確定脚・含み損・最大下落が不変か確認する。

    引数: cases (list[dict])、all_lengths (bool)。返り値: 打切り数と会計確認数 (tuple[int, int])。
    """
    cuts = checks = 0
    for item in cases:
        ready, cfg, full = item['ready'], item['config'], item['result']
        full_curve = equity_at(full['raw'], ready, len(ready['seq']))
        dd = np.maximum.accumulate(np.r_[0., full_curve])[1:] - full_curve
        np.testing.assert_allclose(full_curve[-1], full['summary']['net_yen'])
        np.testing.assert_allclose(dd.max(), full['summary']['max_drawdown_yen'])
        for row in full['equity']:
            index = np.searchsorted(ready['seq'], int(row[1]))
            np.testing.assert_allclose(row[2], full_curve[index])
        lengths = range(2, len(ready['seq'])) if all_lengths else sorted(set([2, len(ready['seq']) // 3, len(ready['seq']) // 2, len(ready['seq']) - 1]))
        for length in lengths:
            short = dict(ready)
            for key in ('seq', 'time_s', 'last', 'atr'):
                short[key] = ready[key][:length].copy()
            result = engine.simulate(short, cfg, detail=True)
            expected = full['raw'][(full['raw'][:, 14] == 1) & (full['raw'][:, 6] < length)]
            actual = result['raw'][result['raw'][:, 14] == 1]
            np.testing.assert_allclose(actual, expected, equal_nan=True)
            np.testing.assert_allclose(result['summary']['net_yen'], full_curve[length - 1])
            np.testing.assert_allclose(result['summary']['max_drawdown_yen'], dd[:length].max())
            np.testing.assert_allclose(result['raw'][:, 15].sum() * engine.MULTIPLIERS[ready['symbol']], full_curve[length - 1])
            assert result['summary']['gross_peak'] <= cfg['max_legs']
            cuts += 1
            checks += 4 + len(actual)
    return cuts, checks


def main() -> None:
    """機能: 人工例だけで検査し、結果と実装ハッシュを保存する。

    引数: なし。返り値: なし (None)。実データやAPIは読まない。
    """
    definitions = [
        ('利益だけを確定しても残った含み損を含む', [100, 90, 100, 110, 140], dict(directions='both', max_legs=2),
         dict(net_yen=-20000, closed_net_yen=10000, open_yen=-30000, max_drawdown_yen=30000, incomplete_cycle_ids=[0])),
        ('買い10枠の上限とギャップ約定', [1000, 890], dict(max_legs=10),
         dict(net_yen=-550000, entry_count=10, gross_peak=10, ideal_entry_gap_count=10)),
        ('同じ指値水準で次の押しを待って再配置', [100, 90, 100, 90, 100], {},
         dict(net_yen=20000, closed_count=2, open_count=0, incomplete_cycle_ids=[0])),
        ('逆指値は既に突破した水準へ即再注文しない', [100, 110, 130, 130, 130],
         dict(entry_kind='stop', initial_stop_gap=1., target_gap=2.),
         dict(net_yen=20000, entry_count=1, closed_count=1)),
        ('指値損切り後の不利価格で同じ損失を即反復しない', [100, 90, 70, 70, 70],
         dict(initial_stop_gap=1., target_gap=2.), dict(net_yen=-10000, entry_count=1, closed_count=1)),
        ('逆指値の手前へ戻った後の再突破', [100, 110, 130, 100, 110, 130],
         dict(entry_kind='stop', initial_stop_gap=1., target_gap=2.), dict(net_yen=40000, entry_count=2, closed_count=2)),
        ('指値損切り後も手前へ戻るまで待機', [100, 90, 70, 100, 90, 110],
         dict(initial_stop_gap=1., target_gap=2.), dict(net_yen=10000, win_count=1, loss_count=1, entry_count=2)),
        ('返済期限の次行で全脚を返済', [100, 90, 80, 70, 60], {},
         dict(net_yen=-20000, closed_count=1, open_count=0, incomplete_cycle_ids=[]), 2.),
        ('期限成立行で打ち切れば未返済評価', [100, 90, 80], {},
         dict(net_yen=-10000, closed_count=0, open_count=1, incomplete_cycle_ids=[0]), 2.),
        ('保有時間上限は成立後の次行返済', [100, 90, 80, 70], dict(holding_min=1 / 60),
         dict(net_yen=-20000, closed_count=1, incomplete_cycle_ids=[0])),
        ('かご損失は全玉評価して次行全返済', [100, 80, 70, 60], dict(max_legs=2, target_gap=None, basket_stop_gap=2.),
         dict(net_yen=-50000, closed_count=2, open_count=0, incomplete_cycle_ids=[])),
        ('かご利確は個別の含み損も合算', [100, 80, 100, 110], dict(max_legs=2, target_gap=None, basket_target_gap=2.),
         dict(net_yen=50000, closed_count=2, incomplete_cycle_ids=[])),
        ('かご追跡は前行の最大評価を使う', [100, 90, 120, 105, 100],
         dict(target_gap=None, basket_trail_start_gap=2., basket_trail_gap=1.),
         dict(net_yen=10000, closed_count=1, incomplete_cycle_ids=[])),
        ('個別追跡の変更は次行から有効', [100, 90, 120, 100],
         dict(initial_stop_gap=1., target_gap=None, trail_gap=1., trail_start_gap=1.),
         dict(net_yen=20000, closed_count=1)),
        ('順行利益75%を呼値へ切り下げて保護', [100, 90, 120, 100],
         dict(initial_stop_gap=1., target_gap=None, protect_start_gap=2., protect_fraction=.75),
         dict(net_yen=20000, closed_count=1)),
        ('８枠併設は両方向建玉も総枚数で制限', [100, 120], dict(entry_kind='mixed', directions='both', max_legs=8),
         dict(net_yen=0, entry_count=4, gross_peak=4, ideal_fill_benefit_yen=0)),
        ('損失発生後はセッション中の新規を全面停止', [100, 90, 70, 100, 90, 110],
         dict(initial_stop_gap=1., target_gap=2., disable_add_after_loss=True),
         dict(net_yen=-10000, entry_count=1, entry_halted=1, incomplete_cycle_ids=[])),
        ('セッション損失上限で次行全返済', [100, 90, 70, 60], dict(target_gap=None, session_stop_gap=2.),
         dict(net_yen=-30000, closed_count=1, entry_halted=1, incomplete_cycle_ids=[])),
        ('未来足高安ではなく同時刻の原本順を守る', [100, 90, 100], {},
         dict(net_yen=10000, closed_count=1), 100000., [0, 0, 0]),
        ('無効現在価格は補完せず判定を飛ばす', [100, np.nan, 90, 100], {},
         dict(net_yen=10000, closed_count=1)),
        ('売り片側も反対称の利確', [100, 110, 100], dict(directions='short'),
         dict(net_yen=10000, closed_count=1)),
        ('前進再配置は利確価格の１段先', [100, 110, 130, 140, 160],
         dict(entry_kind='stop', initial_stop_gap=1., target_gap=2., rearm='advance'),
         dict(net_yen=40000, entry_count=2, closed_count=2)),
    ]
    reports, cases = [], []
    for definition in definitions:
        report, item = case(*definition)
        reports.append(report)
        cases.append(item)
    cuts, checks = prefix(cases)
    # ----------------------------------------
    # 再配置回数は枚数上限とは別。配列拡張しても脚番号の再利用を正しく扱う。
    prices = [100.] + [value for _ in range(350) for value in [90., 100.]]
    report, large = case('350回の再配置と配列拡張', prices, {}, dict(net_yen=3500000, closed_count=350, gross_peak=1))
    reports.append(report)
    c, k = prefix([large], all_lengths=False)
    cuts, checks = cuts + c, checks + k
    random_cases = []
    rng = np.random.default_rng(20260925)
    for cfg in engine.catalog():
        engine.parameters(cfg)
        prices = 1000 + np.cumsum(rng.choice([-20., -10., 0., 10., 20.], 120))
        ready = fixture(prices.tolist(), limit=110., clock=np.arange(120, dtype=float) * 1.)
        candidate = dict(cfg, warmup_min=0., entry_deadline_min=0., reset_min=.01, holding_min=.1)
        result = engine.simulate(ready, candidate, detail=True)
        brief = engine.simulate(ready, candidate, detail=False)
        assert result['summary'] == brief['summary']
        np.testing.assert_allclose(result['raw'], brief['raw'], equal_nan=True)
        assert result['summary']['open_count'] == 0
        assert result['incomplete_cycle_ids'] == []
        random_cases.append(dict(ready=ready, config=candidate, result=result))
    c, k = prefix(random_cases)
    cuts, checks = cuts + c, checks + k
    frozen = json.loads((OUT / '格子条件_損益前固定.json').read_text(encoding='utf-8'))
    assert frozen['条件一覧'] == engine.catalog()
    record = dict(合格=True, 手計算=reports, 条件数=len(random_cases), 未来打切り数=cuts,
        会計確認数=checks, 実データ参照=False, API取得回数=0,
        実装SHA256=hashlib.sha256((OUT / 'grid_engine.py').read_bytes()).hexdigest(),
        損益前条件固定_SHA256=hashlib.sha256((OUT / '格子条件_損益前固定.json').read_bytes()).hexdigest(),
        サイクル未完了='全脚返済済みでも同じ中心の再配置が続く場合はincomplete_cycle_idsへ記録。')
    (OUT / '格子再生_手計算と未来打切り監査.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(合格=True, 手計算数=len(reports), 条件数=len(random_cases), 未来打切り数=cuts, 会計確認数=checks), ensure_ascii=False))


if __name__ == '__main__':
    main()
