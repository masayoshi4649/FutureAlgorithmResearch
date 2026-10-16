"""100の旧支持十対照を99保存20配列へ公差0で照合する。"""

import hashlib
from pathlib import Path

import numpy as np

import common
import support


def array_sha(value: np.ndarray) -> str:
    """
    機能: 保存台帳と同じ配列バイトのSHA256を計算する。
    引数: value(ndarray)は経済又は原板状態。
    返り値: str。現在配列の16進指紋。
    """
    return hashlib.sha256(value.tobytes()).hexdigest()


def prepared_sha(prepared: dict) -> str:
    """
    機能: 共有原板/信号内の全配列と保存始値を順に読み、変更を検出する。
    引数: prepared(dict[tuple,dict])は共有入力。
    返り値: str。キー・型・形状と全配列の結合指紋。
    """
    digest = hashlib.sha256()
    def visit(value: object) -> None:
        """
        機能: 共有支持源を含む全入れ子配列を読取り、再生前後の変化を検出する。
        引数: value(object)は配列、辞書、列又は不変値。
        返り値: None。外側の指紋だけを更新する。
        """
        if isinstance(value, np.ndarray):
            digest.update(repr((value.dtype.str, value.shape)).encode('utf-8'))
            digest.update(value.tobytes())
        elif isinstance(value, dict):
            for key in sorted(value, key=repr):
                digest.update(repr(key).encode('utf-8'))
                visit(value[key])
        elif isinstance(value, (list, tuple)):
            for item in value:
                visit(item)
        else:
            digest.update(repr(value).encode('utf-8'))
    visit(prepared)
    return digest.hexdigest()


def main() -> None:
    """
    機能: NoCap八待機とA0二即時の全620口座を、旧99の20配列及び支持へ照合する。
    引数: なし。
    返り値: None。有限capの実損益は計算しない。共有prepared及び旧989依存を保持する。
    """
    common.old_immutable()
    catalog = common.module('100独立null条件', common.BASE / 'catalog.py')
    data = common.module('100独立null入力', common.BASE / 'data.py')
    strategy = common.module('100独立null戦略', common.BASE / 'strategy.py')
    configs = [value for value in catalog.catalog() if value['entry_price_cap_multiple'] is None]
    assert len(configs) == 10
    material = data.load_inputs()
    prepared = strategy.prepare(material, configs[0])
    # ----------------------------------------
    # 旧nullに先立ち、全31の新支持資格を別のscalar式から照合する。新売買はまだ行わない。
    for session, price in material['trend_prices']['I3'].items():
        allowed = support.lp_allowed(price, material['grids'][session])
        for symbol in catalog.SYMBOLS:
            support.verify_material((session, symbol), material, prepared[session, symbol])
            for side in (-1, 1):
                common.exact(prepared[session, symbol]['trend_lp_allowed'][side], allowed[side], '全格子独立LP支持')
    before = prepared_sha(prepared)
    counts, paths = dict(条件=10, 口座=0, 注文=0, 決済親=0, 原板行=0), []
    for config in configs:
        previous = {}
        for part in ('front', 'back'):
            path = common.ROOT / 'work/wave_v99' / part / 'ledgers' / (config['previous_support_id'] + '.pkl')
            previous.update(common.read(path))
            paths.append(path)
        assert len(previous) == 62 and set(previous) == set(prepared)
        for key in sorted(previous):
            actual = strategy.play(config, key, prepared)
            saved = previous[key]
            for name in ('orders', 'trades', 'events', 'stats', 'slots', 'range_parent_diagnostics',
                         'loss_reentry_events', 'trend_parent_diagnostics', 'entry_parent_diagnostics',
                         'entry_wait_events', 'entry_policy_events'):
                common.exact(actual[name], saved[name], config['id'] + '/' + str(key) + '/' + name)
            common.exact(actual['entry_support_state_trace'], saved['entry_support_state_trace'], '旧支持59完全一致')
            assert actual['entry_support_input_SHA256'] == saved['entry_support_input_SHA256'], '旧実支持2列SHA差'
            for name, field in (
                ('curve', 'curve_SHA256'), ('source_curve', 'source_curve_SHA256'),
                ('target_trace', 'target_trace_SHA256'), ('range_state_trace', 'range_state_SHA256'),
                ('risk_state_trace', 'risk_state_SHA256'), ('price_source_trace', 'price_source_SHA256'),
                ('trend_exit_state_trace', 'trend_exit_state_SHA256'), ('watch_state_trace', 'watch_state_SHA256'), ('entry_policy_state_trace', 'entry_policy_state_SHA256')):
                assert array_sha(actual[name]) == saved[field], (config['id'], key, name)
            assert array_sha(prepared[key]['signal']['event']) == saved['trend_event_SHA256']
            counts['口座'] += 1
            counts['注文'] += len(actual['orders'])
            counts['決済親'] += len(actual['trades'])
            counts['原板行'] += len(prepared[key]['record']['time_s'])
        print(config['id'] + ': 対応99全62の旧20配列と候補が完全一致', flush=True)
    assert counts['口座'] == 620 and prepared_sha(prepared) == before
    common.old_immutable()
    paths += [common.BASE / name for name in ('engine.py', 'strategy.py', 'catalog.py', 'data.py')]
    paths += [Path(__file__), common.HERE / 'common.py', common.HERE / 'support.py', common.ROOT / 'work/wave_v99/事前固定.json']
    common.save(common.HERE / '上限なし旧十条件の99全620口座と旧20及び支持源の完全一致.json', dict(
        合格=True, 検査件数=counts, 公差=0, 共有prepared不変=True, 共有preparedSHA256=before,
        新政策正式損益=0, 旧変更=0, API取得=0, 実注文=0, SHA256=common.fingerprint(paths)))


if __name__ == '__main__':
    main()
