"""旧条件の私有人工で数学上限の接続だけを検査し、新正式損益を開かない。"""

from copy import deepcopy
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import sys

os.environ['NUMBA_DISABLE_JIT'] = '1'
sys.dont_write_bytecode = True
import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
OLD_ARRAYS = ('orders', 'trades', 'curve', 'source_curve', 'target_trace', 'events', 'stats', 'slots',
    'range_state_trace', 'risk_state_trace', 'range_parent_diagnostics', 'price_source_trace',
    'loss_reentry_events', 'trend_exit_state_trace', 'trend_parent_diagnostics', 'watch_state_trace',
    'entry_parent_diagnostics', 'entry_wait_events', 'entry_policy_state_trace', 'entry_policy_events')


def module(name: str, path: Path) -> object:
    """
    機能: 正式素材とmainを開かず局所実装又は人工fixtureだけを取り込む。
    引数: name(str)、path(Path)。
    返り値: objectは読取モジュール。過去領域へのキャッシュを生成しない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 結果前の実装と事前期待値へ証跡を結び付ける。
    引数: path(Path)。
    返り値: strはSHA256。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(value: object) -> str:
    """
    機能: 私有人工の設定及び共有配列の不変を調べる。
    引数: value(object)。
    返り値: strはpickle内容指紋。
    """
    return hashlib.sha256(pickle.dumps(value, protocol=5)).hexdigest()


def first_decision(output: dict) -> int | None:
    """
    機能: 人工の最初の実新規に対応する判断行を読む。
    引数: output(dict)。
    返り値: int|None。無取引は勝ち又は精度改善として数えない。
    """
    rows = output['orders'][output['orders'][:, 7] == 1]
    return int(rows[0, 1]) if len(rows) else None


def main() -> None:
    """
    機能: 売買反射・拒否保持・旧優先取消・次約定超過と代理公開順内の未来不変を確認する。
    引数: なし。新金融入力又は新正式損益を開く機能はない。
    返り値: None。自担当review_preだけへ結果前の人工証跡を保存する。
    """
    fixture_path = ROOT / 'work/wave_v97/review_pre/36仕様の局所状態境界と源及び共有入力の独立反証.py'
    paths = [BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', '結果前の設計案.json')]
    paths += [ROOT / 'work/wave_v99/engine.py', ROOT / 'work/wave_v99/strategy.py', fixture_path,
        HERE / '判断価格上限の結果前独立反証仕様.py',
        HERE / '判断価格上限の独立仕様及び局所実装への事前期待値.json']
    before = {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    assert before['work/wave_v100/engine.py'] == 'be34cd52ff6fa0fe625dae79f7a2e3444a12c54768c27ae6b6f55b3434a0e0e2'
    assert before['work/wave_v100/strategy.py'] == 'ee6fbba64fea5947eba92c2b4a794e884c93eadcbea26ceaeb07667b071b2457'
    strategy = module('100価格上限の局所独立反証', BASE / 'strategy.py')
    old_strategy = module('99経済nullだけの局所読取100', ROOT / 'work/wave_v99/strategy.py')
    catalog = module('100価格上限の固定局所条件', BASE / 'catalog.py')
    fixture = module('97短い状態fixtureだけを局所読取100', fixture_path)
    configs = {value['id']: value for value in catalog.catalog()}
    assert len(configs) == 34 and catalog.PRIMARY == 'P1_L1_C1_A1_X1'
    evidence, counts = [], dict(半呼値正負=0, 不利等号=0, 有利価格=0, 支持買売非対称=0,
        拒否後再入域及びpulse消費=0, 候補と局所極値の分離=0, 旧取消優先=0,
        peer又は支持不明を救済しない=0, 次行cap外fill=0, 旧P0少数null=0, 人工接頭未来=0)

    def artificial(ident: str, side: int, progress: list[float], times: list[float] | None = None,
                   opening: float = 4000., change: object = None) -> dict:
        """
        機能: 旧の短いTOPIX状態機械人工へ方向別支持を注入し数学上限だけの配線を作る。
        引数: ident(str)、side(int)、progress/times(list[float]|None)、opening(float)、change(callable|None)。
        返り値: dictは私有prepared。bool注入はLP源窓の再構成又は価格支持の正解認定ではない。
        """
        record, signal = fixture.fixture(configs[ident], side, progress, times)
        n = len(signal['grid'])
        quote = opening + side * np.asarray(progress, float)
        record['bid'] = quote - .5 if side == 1 else quote.copy()
        record['ask'] = quote.copy() if side == 1 else quote + .5
        record['price'] = .5 * (record['bid'] + record['ask'])
        signal['trend_width'] = max(2, math.ceil(opening * .004 / .5 - 1e-10)) * .5
        signal['entry_j2_long'][:] = side == 1
        signal['entry_j2_short'][:] = side == -1
        basis = np.full((n, 59), np.nan)
        basis[:, 0] = np.arange(n); basis[:, 1] = signal['grid']
        value = dict(record=record, signal=signal, reference_open=opening,
            trend_lp_allowed={1: np.full(n, side == 1, bool), -1: np.full(n, side == -1, bool)},
            entry_support_base=basis)
        if change is not None:
            change(value)
        return {('2000-01-03_人工', 'TOPIX'): value}

    def run(ident: str, prepared: dict) -> dict:
        """
        機能: 私有人工だけを実行し診断20/21列を価格と候補から独立算出して比較する。
        引数: ident(str)、prepared(dict)。
        返り値: dictは人工出力。金融成績の追加候補を生成しない。
        """
        key = next(iter(prepared))
        initial = fingerprint((prepared, configs[ident]))
        output = strategy.play(configs[ident], key, prepared, finish=False)
        assert fingerprint((prepared, configs[ident])) == initial
        trace = output['entry_cap_state_trace']
        assert trace.shape == (len(prepared[key]['record']['time_s']), 20)
        assert len(output['entry_cap_state_columns']) == 20 and len(output['entry_cap_parent_columns']) == 21
        multiple = configs[ident]['entry_price_cap_multiple']
        enabled = multiple is not None
        assert np.all(trace[:, 0] == enabled)
        for row, saved in enumerate(trace):
            assert bool(saved[14]) == bool(saved[13] and (not enabled or saved[12]))
            assert bool(saved[15]) == bool(saved[13] and enabled and not saved[12])
            if saved[4] <= 0 or not saved[10]:
                continue
            side, candidate = int(saved[8]), saved[6]
            quote = prepared[key]['record']['ask' if side == 1 else 'bid'][row]
            assert saved[9] == quote
            adverse = side * (quote - candidate)
            assert saved[11] == adverse
            expected = not enabled or adverse <= multiple * saved[7]
            assert bool(saved[12]) == expected
            if enabled:
                assert saved[2] == multiple * saved[7]
        for parent in output['entry_cap_parent_diagnostics']:
            assert parent[13] == parent[3] * (parent[12] - parent[5])
            if np.isfinite(parent[17]):
                assert parent[18] == parent[3] * (parent[17] - parent[5])
            else:
                assert np.isnan(parent[18])
            assert parent[14] == 1.
            if enabled:
                assert parent[9] == multiple * parent[6]
                assert parent[13] <= parent[9]
                if np.isfinite(parent[18]):
                    assert parent[19] == max(0., parent[18] - parent[9])
                else:
                    assert np.isnan(parent[19])
        return output

    # ----------------------------------------
    # capは呼値化したWに掛けた数学上限で、買ask/売bidの方向付き幅を直接用いる。
    for side in (-1, 1):
        ident = 'P05_L1_C1_A1_X1'
        half = run(ident, artificial(ident, side, [0., 2.5, 2., 2.5], opening=4500.))
        assert first_decision(half) == 2
        assert half['entry_cap_state_trace'][1, 2] == 2.25
        assert half['entry_cap_state_trace'][1, 11] == 2.5
        assert half['entry_cap_state_trace'][1, 15] == 1.
        counts['半呼値正負'] += 1
        equal = run(ident, artificial(ident, side, [0., 2., 2.5]))
        assert first_decision(equal) == 1
        assert equal['entry_cap_parent_diagnostics'][0, 13] == equal['entry_cap_parent_diagnostics'][0, 9] == 2.
        counts['不利等号'] += 1
        evidence.append(dict(方向=side, W4点5の上限=2.25, 不利2点5拒否=True, 不利2点0受理=True,
            W4の不利2点0等号受理=True, 買ask売bidの独立価格一致=True))

        # 自己quoteが候補より有利なままではA1の自己BBO進行と両立しないため、A7の極値後回復を使う。
        for cap in ('P05', 'P1', 'P2'):
            ident = cap + '_L1_C1_A7_X3'
            favorable = run(ident, artificial(ident, side, [0., 6., -4., -2., -1.5]))
            assert first_decision(favorable) == 3
            assert favorable['entry_cap_parent_diagnostics'][0, 13] == -2.
            counts['有利価格'] += 1

    # ----------------------------------------
    # 拒否は旧watchを終わらせず、局所幾何の更新及び元TTLを保持する。
    for side in (-1, 1):
        ident = 'P1_L1_C1_A1_X1'
        def another_pulse(value: dict) -> None:
            """
            機能: cap拒否行に反対のpulseを置き待機枠の消費を検査する。
            引数: value(dict)。
            返り値: None。
            """
            value['signal']['event'][1] = -side
        held = run(ident, artificial(ident, side, [0., 5., 1., 1.5], change=another_pulse))
        assert first_decision(held) == 2
        state = held['watch_state_trace'][1]
        assert state[0] == 1 and state[3] == 1 and state[7] == 4000. and state[8] == 600.
        assert held['entry_cap_state_trace'][1, 15] == 1.
        busy = held['entry_wait_events']
        assert np.any((busy[:, 0] == 1) & (busy[:, 1] == 2) & (busy[:, 2] == 7))
        assert held['entry_parent_diagnostics'][0, 1] == 1.
        assert held['target_trace'][1, 4] == 8.
        counts['拒否後再入域及びpulse消費'] += 1
        ident = 'P1_L1_C1_A7_X3'
        geometry = run(ident, artificial(ident, side, [0., 12., 8., 10., 2., 4., 4.5]))
        assert first_decision(geometry) == 5
        assert geometry['entry_cap_state_trace'][3, 15] == 1.
        assert geometry['watch_state_trace'][3, 7] == 4000.
        assert geometry['watch_state_trace'][3, 14] == 4000. + side * 8.
        assert geometry['watch_state_trace'][4, 14] == 4000. + side * 2.
        assert geometry['watch_state_trace'][4, 8] == 600.
        assert geometry['entry_parent_diagnostics'][0, 5] == 4000.
        counts['候補と局所極値の分離'] += 1
        evidence.append(dict(方向=side, 拒否後同候補受理行=2, 元期限=600., 他pulse消費=True,
            A7の局所回復10ptを候補cap4ptで拒否=True, 新極値2ptから回復4ptで受理行=5))

    # ----------------------------------------
    # cap内へ戻った行でも旧取消は先行し、現在支持及びpeer未知を埋めない。
    for side in (-1, 1):
        ident = 'P1_L1_C1_A1_X1'
        for label, expected_reason in (('TTL', 2), ('reset', 4), ('quote', 5), ('hard', 6), ('cut', 1)):
            def fault(value: dict) -> None:
                """
                機能: 再入域行へ旧強制取消を与える。
                引数: value(dict)。
                返り値: None。cap及び新支持に優先する旧ルールだけを変える。
                """
                if label == 'reset': value['signal']['reset'][2] = True
                elif label == 'quote': value['record']['quote_valid'][2] = False
                elif label == 'hard': value['signal']['wait_opposite_' + ('long' if side == 1 else 'short')][2] = True
                elif label == 'cut': value['record']['limit'] = 602.
            times = [300., 301., 600., 601.] if label == 'TTL' else None
            cancelled = run(ident, artificial(ident, side, [0., 5., 1., 1.5], times=times, change=fault))
            assert first_decision(cancelled) is None
            events = cancelled['entry_wait_events']
            assert np.any((events[:, 0] == 2) & (events[:, 1] == 3) & (events[:, 2] == expected_reason))
            assert cancelled['entry_cap_state_trace'][2, 13:16].sum() == 0.
            counts['旧取消優先'] += 1
        for label in ('peer', 'support', 'wrong_side'):
            def withheld(value: dict) -> None:
                """
                機能: cap再入域行の必要資格を不成立にし、次の正常行だけ許可する。
                引数: value(dict)。
                返り値: None。逆側支持を自己側へ転用しない。
                """
                if label == 'peer': value['signal']['entry_peer_bbo'][2, 5] = 0.
                else:
                    value['trend_lp_allowed'][side][2] = False
                    if label == 'wrong_side': value['trend_lp_allowed'][-side][2] = True
            delayed = run(ident, artificial(ident, side, [0., 5., 1., 1.5, 2.], change=withheld))
            assert first_decision(delayed) == 3
            assert delayed['entry_cap_state_trace'][2, 12] == 1.
            assert delayed['entry_cap_state_trace'][2, 13:16].sum() == 0.
            counts['peer又は支持不明を救済しない'] += 1
            if label == 'wrong_side': counts['支持買売非対称'] += 1

    # ----------------------------------------
    # 判断上限は次行market fillの上限ではない。未知執行行も飛ばして旧約定資格を保つ。
    for side in (-1, 1):
        ident = 'P05_L1_C1_A1_X1'
        overshoot = run(ident, artificial(ident, side, [0., 2., 6., 6.5]))
        parent = overshoot['entry_cap_parent_diagnostics'][0]
        assert first_decision(overshoot) == 1
        assert parent[13] == 2. and parent[18] == 6. and parent[19] == 4.
        counts['次行cap外fill'] += 1
        def invalid_fill(value: dict) -> None:
            """
            機能: 最初の予約後行の執行気配を不明にする。
            引数: value(dict)。
            返り値: None。次正常BBOのcap外約定を維持する。
            """
            value['record']['quote_valid'][2] = False
        later = run(ident, artificial(ident, side, [0., 2., 6., 6.5], change=invalid_fill))
        assert first_decision(later) == 1
        assert later['entry_cap_parent_diagnostics'][0, 15] == 3.
        assert later['entry_cap_parent_diagnostics'][0, 19] == 4.5
        counts['次行cap外fill'] += 1
        evidence.append(dict(方向=side, 判断不利幅=2., 数学上限=2., 次行約定不利幅=6.,
            約定超過=4., 気配未知後の次正常行も超過約定=True))

    # ----------------------------------------
    # P0十対照の局所nullは旧全20配列と現在支持59及び実入力2列指紋を比較する。
    for ident, config in configs.items():
        if config['entry_price_cap_multiple'] is not None:
            continue
        for side in (-1, 1):
            prepared = artificial(ident, side, [0., 12., 8., 10., 1., 3., 3.5])
            key = next(iter(prepared))
            output = run(ident, prepared)
            old = old_strategy.play(catalog.PREVIOUS[config['previous_support_id']], key, prepared, finish=False)
            for name in OLD_ARRAYS + ('entry_support_state_trace',):
                np.testing.assert_array_equal(output[name], old[name])
            assert output['entry_support_input_SHA256'] == old['entry_support_input_SHA256']
            counts['旧P0少数null'] += 1
    assert counts['旧P0少数null'] == 20

    # ----------------------------------------
    # future fill及び相手気配と支持の変更が既に公表済みのcap判断を変えないことを確認する。
    for ident in ('P05_L1_C1_A1_X1', 'P1_L1_C1_A7_X3'):
        whole_input = artificial(ident, 1, [0., 12., 8., 10., 2., 4., 4.5, 7., 0.])
        whole = run(ident, whole_input)
        key = next(iter(whole_input))
        for cut in (2, 4, 5, 6, 7):
            prefix_input = deepcopy(whole_input)
            for name, array in prefix_input[key]['record'].items():
                if isinstance(array, np.ndarray): prefix_input[key]['record'][name] = array[:cut].copy()
            for name in ('mapped', 'event', 'quality', 'reset'):
                prefix_input[key]['signal'][name] = prefix_input[key]['signal'][name][:cut].copy()
            prefix = run(ident, prefix_input)
            altered_input = deepcopy(whole_input)
            altered_input[key]['record']['bid'][cut:] += 500.
            altered_input[key]['record']['ask'][cut:] += 500.
            altered_input[key]['signal']['entry_peer_bbo'][cut:, 3:5] += 2000.
            altered_input[key]['trend_lp_allowed'][1][cut:] = False
            altered_input[key]['entry_support_base'][cut:, 11:] = 987654.
            altered = run(ident, altered_input)
            for name in ('curve', 'target_trace', 'watch_state_trace', 'entry_policy_state_trace', 'entry_cap_state_trace'):
                np.testing.assert_array_equal(prefix[name], whole[name][:cut])
                np.testing.assert_array_equal(altered[name][:cut], whole[name][:cut])
            for name in ('orders', 'events', 'entry_wait_events', 'entry_policy_events'):
                expected = whole[name][whole[name][:, 0] < cut]
                np.testing.assert_array_equal(prefix[name], expected)
                np.testing.assert_array_equal(altered[name][altered[name][:, 0] < cut], expected)
            expected_support = whole['entry_support_state_trace'][whole['entry_support_state_trace'][:, 0] < cut]
            np.testing.assert_array_equal(prefix['entry_support_state_trace'], expected_support)
            counts['人工接頭未来'] += 1
    assert counts['人工接頭未来'] == 10
    assert before == {path.relative_to(ROOT).as_posix(): digest(path) for path in paths}
    result = dict(全合格=True, 種類='100判断価格上限の結果前局所独立反証', 条件数=34,
        主=catalog.PRIMARY, 対照=catalog.CONTROL, 合格数=counts, 主要期待値=evidence,
        全行20列及び全親21列の独立数理照合=True, 共有prepared及び設定不変=True,
        コード及び根拠SHA256=before,
        SHA256=dict(before, **{Path(__file__).relative_to(ROOT).as_posix(): digest(Path(__file__))}),
        計算コードSHA256=digest(Path(__file__)),
        scope='私有TOPIX人工の売買反射と既存20配列の少数null。支持は正負boolの配線であり'
              'LP原本窓生成の正解又は全620正式旧対照の一致をこの証跡で認定しない。'
              '新40政策補助flagsの全行独立再構成も認定しない。',
        未保証='再生時計はCurrentPriceTime由来で真受信時計及び二市場の共通受信順は未観測。'
                '接頭及び未来不変は代理公開順仮定内。全入力2列SHAは未来格子が変われば変わり得る。',
        新正式損益閲覧=0, 新正式売買実行=0, 現在API取得=0, 実注文=0, 過去成果編集=0)
    target = HERE / '判断価格上限の局所状態及び約定超過と未来不変の独立反証.json'
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    print('100価格上限の局所数理・旧20少数null・次約定超過・人工未来不変が合格。新正式PL0。', flush=True)


if __name__ == '__main__':
    main()
