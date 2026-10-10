"""残玉保護の新機構を合成経路で、既定互換だけを保存済み原本で独立監査する。"""

from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'wave_v23'
PREVIOUS = HERE.parent / 'wave_v28'
SIGNALS = HERE.parent / 'wave_v27'
for folder in (OLD, HERE.parent / 'wave_v25', PREVIOUS, HERE):
    sys.path.insert(0, str(folder))
import engine_context as BASE_ENGINE
import engine_protection as ENGINE
import managers
import discovery_managers
import protection_design
from context_engine_audit import accounting, equal


def digest(path: Path) -> str:
    """機能: 監査中の変更を検出する指紋を計算する。

    引数: path (Path)。返り値: SHA256 (str)。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def structure() -> dict:
    """機能: 新しい2パラメータの床計算以外の旧処理をASTで比較する。

    引数: なし。返り値: 許可した構造差分の記録 (dict)。
    """
    old = ast.parse((PREVIOUS / 'engine_context.py').read_text(encoding='utf-8'))
    new = ast.parse((HERE / 'engine_protection.py').read_text(encoding='utf-8'))
    before = {x.name: x for x in old.body if isinstance(x, ast.FunctionDef)}
    after = {x.name: x for x in new.body if isinstance(x, ast.FunctionDef)}
    current = deepcopy(after['simulate'])
    changes = {'残玉床の追加': 0, '利益保護の始動R': 0}

    class Normalize(ast.NodeTransformer):
        """機能: 明示的に許可した2処理だけを旧ASTへ戻す。

        引数: 各visitのnode (AST)。返り値: 変換済みAST又はNone。
        """
        def visit_If(self, node: ast.If):
            """機能: par[40]の残玉床条件だけを除去する。

            引数: node (ast.If)。返り値: AST又はNone。
            """
            text = ast.unparse(node.test)
            if text == 'par[40] > 0 and split_done and (inv[0] > 0.5)':
                changes['残玉床の追加'] += 1
                return None
            return self.generic_visit(node)

        def visit_BinOp(self, node: ast.BinOp):
            """機能: 新しい始動Rの乗算だけを旧riskへ戻す。

            引数: node (ast.BinOp)。返り値: AST。
            """
            if ast.unparse(node) == 'par[41] * risk':
                changes['利益保護の始動R'] += 1
                return ast.Name(id='risk', ctx=ast.Load())
            return self.generic_visit(node)

    current = Normalize().visit(current)
    assert changes == {'残玉床の追加': 1, '利益保護の始動R': 1}, changes
    assert ast.dump(current, include_attributes=False) == ast.dump(before['simulate'], include_attributes=False)
    for name in ('rounded', 'inventory', 'close_positions'):
        assert ast.dump(before[name], include_attributes=False) == ast.dump(after[name], include_attributes=False)
    assert ENGINE.PARAMS == BASE_ENGINE.PARAMS + ['residual_risk_cap', 'lock_activation_r']
    assert ENGINE.REASONS == BASE_ENGINE.REASONS
    return dict(許可した差分=changes, 価格優先順と旧会計は同一=True)


def ready(prices: list[float] | np.ndarray, atr: float = 4., tick: float = 1., times: np.ndarray | None = None) -> dict:
    """機能: 受信行順と同値時刻を持てる合成入力を作成する。

    引数: prices (list[float]|ndarray)、atr/tick (float)、times (ndarray|None)。返り値: 入力 (dict)。
    """
    price = np.asarray(prices, float)
    clock = np.arange(len(price), dtype=float) if times is None else np.asarray(times, float)
    return dict(last=price, atr=np.full(len(price), atr), tick=tick, time_s=clock,
                seq=np.arange(len(price)), start=0., limit=float(clock[-2]), us_open=1e9,
                symbol='TOPIX', session='合成・成績非評価')


def config(quantity: int = 5, **changes) -> dict:
    """機能: D273の価格規則を基礎に、合成専用の準備時間で設定する。

    引数: quantity (int)、changes (dict)。返り値: 管理設定 (dict)。
    """
    spec = next(s for s in discovery_managers.catalog() if s['id'] == 'D273')
    value = managers.make_config(spec, 'TOPIX' if quantity <= 5 else 'NK225', {})
    value.update(initial_qty=quantity, point_value=1., warmup_min=0., entry_cutoff_min=0.,
                 entry_mode=2, cooldown_min=100., ttl_seconds=1000.)
    value.update(changes)
    return value


def economic_equal(left: dict, right: dict) -> dict:
    """機能: 理由コードだけを除き、約定・損益・全行時価を照合する。

    引数: left/right (dict)。返り値: 理由だけの差分件数 (dict)。
    """
    for name, reason_column in (('orders', 6), ('trades', 9), ('cycles', 9)):
        assert left[name].shape == right[name].shape
        columns = [i for i in range(left[name].shape[1]) if i != reason_column]
        np.testing.assert_allclose(left[name][:, columns], right[name][:, columns], atol=1e-7, rtol=0)
    np.testing.assert_allclose(left['curve'], right['curve'], atol=1e-7, rtol=0)
    np.testing.assert_allclose(left['stats'], right['stats'], atol=1e-7, rtol=0)
    return {name: int(np.count_nonzero(left[name][:, column] != right[name][:, column]))
            for name, column in (('orders', 6), ('trades', 9), ('cycles', 9))}


def prefix_compare(full: dict, other: dict, length: int) -> None:
    """機能: 指定位置までの台帳と時価曲線を完全比較する。

    引数: full/other (dict)、length (int)。返り値: なし (None)。
    """
    for name, column in (('orders', 0), ('trades', 7), ('cycles', 2)):
        np.testing.assert_array_equal(full[name][full[name][:, column] < length],
                                      other[name][other[name][:, column] < length])
    np.testing.assert_array_equal(full['curve'][:length], other['curve'][:length])


def reflect(data: dict, entry: np.ndarray, context: np.ndarray | None, cfg: dict, result: dict) -> None:
    """機能: 価格・入口・保有方向を上下反射し、売買の対称性を検査する。

    引数: data/cfg/result (dict)、entry (ndarray)、context (ndarray|None)。返り値: なし (None)。
    """
    mirror = dict(data, last=2000. - data['last'])
    actual = ENGINE.run(mirror, -entry, cfg, detail=True, context=None if context is None else -context)
    accounting(mirror, actual, cfg)
    expected = result['orders'].copy()
    expected[:, 3] *= -1
    expected[:, 5] = 2000. - expected[:, 5]
    np.testing.assert_allclose(expected, actual['orders'], atol=1e-7, rtol=0)
    expected = result['trades'].copy()
    expected[:, 2] *= -1
    expected[:, 4:6] = 2000. - expected[:, 4:6]
    np.testing.assert_allclose(expected, actual['trades'], atol=1e-7, rtol=0)
    expected = result['cycles'].copy()
    expected[:, 8] *= -1
    np.testing.assert_allclose(expected, actual['cycles'], atol=1e-7, rtol=0)
    np.testing.assert_allclose(result['curve'][:, [0, 1, 4]], actual['curve'][:, [0, 1, 4]], atol=1e-7, rtol=0)


def synthetic() -> dict:
    """機能: 利確後の床、始動R、包含、呼値、未来不使用を合成だけで検査する。

    引数: なし。返り値: 論理ケースと因果性の件数 (dict)。
    """
    cases, containment = [], []
    rows = reflections = prefix = future = 0

    def run(label: str, prices: list[float], cfg: dict, atr: float = 4.) -> tuple[dict, dict]:
        """機能: 合成1経路を実行し会計・反射を同時検査する。

        引数: label (str)、prices (list[float])、cfg (dict)、atr (float)。返り値: 入力と台帳 (tuple[dict,dict])。
        """
        nonlocal rows, reflections
        data = ready(prices + [prices[-1]] * 4, atr=atr)
        entry = np.ones(len(data['last']), np.int8)
        result = ENGINE.run(data, entry, cfg, detail=True)
        rows += accounting(data, result, cfg)
        reflect(data, entry, None, cfg, result)
        reflections += 1
        cases.append(dict(名称=label, orders=result['orders'].tolist(), trades=result['trades'].tolist(),
                          cycles=result['cycles'].tolist(), 合成=True))
        return data, result

    # ----------------------------------------
    # 既存追跡の包含と、追跡を切った純粋な残玉床の作動を別ケースにする。
    for qty in (5, 10):
        cfg = config(qty, residual_risk_cap=1, main_trail=1000., activation_atr=1000.)
        _, result = run(f'{qty}枚・追跡なしでは初回1ATR残玉床が実際に働く', [1000, 1000, 1008, 999, 995, 980], cfg)
        exits = result['trades']
        assert exits[0, 3] == qty // 2 and exits[0, 9] == 7
        assert exits[1, 3] == qty - qty // 2 and exits[1, 5] == 996 and exits[1, 7] == 4
        assert exits[:, 3].sum() == qty
        for label, prices, atr in (
                ('小刻み', [1000, 1000, 1006, 1008, 1008, 997, 996, 980], 4.),
                ('利確後逆行飛び', [1000, 1000, 1006, 1008, 975, 960], 4.),
                ('利確時順行飛び', [1000, 1000, 1006, 1020, 990, 980], 4.),
                ('新規直後順行飛び', [1000, 1000, 1020, 990, 980], 4.),
                ('呼値端数', [1000, 1000, 1007, 1009, 998, 990], 4.3),
                ('利確なし', [1000, 1000, 1005, 1003, 998, 995], 4.)):
            data, base = run(f'{qty}枚・既存追跡・{label}', prices, config(qty), atr)
            entry = np.ones(len(data['last']), np.int8)
            cap_cfg = config(qty, residual_risk_cap=1)
            capped = ENGINE.run(data, entry, cap_cfg, detail=True)
            rows += accounting(data, capped, cap_cfg)
            changes = economic_equal(base, capped)
            reflect(data, entry, None, cap_cfg, capped)
            reflections += 1
            containment.append(dict(枚数=qty, 経路=label, 経済的台帳一致=True, 理由だけの差分=changes))

        # 利確前の1R始動と、利確後の3Rが単純な3ATRでないことを確かめる。
        cfg = config(qty, lock_fraction=.5, lock_activation_r=1., main_trail=1000., activation_atr=1000.)
        _, result = run(f'{qty}枚・1R保護は部分利確より先', [1000, 1000, 1004, 1001, 990], cfg)
        assert len(result['trades']) == 1 and result['trades'][0, 9] == 11
        assert result['trades'][0, 5] == 1002 and result['trades'][0, 7] == 3
        cfg = config(qty, lock_fraction=.5, lock_activation_r=3., main_trail=1000., activation_atr=1000.)
        data, result = run(f'{qty}枚・3R始動は部分利確後の全組時価で判定', [1000, 1000, 1008, 1012, 1002, 1016, 1003, 990], cfg)
        assert result['trades'][0, 9] == 7 and result['trades'][0, 3] == qty // 2
        assert result['trades'][1, 7] == 6 and result['trades'][1, 9] == 11
        assert result['trades'][1, 5] == (1005 if qty == 5 else 1004)
        changed = dict(data, atr=data['atr'].copy())
        changed['atr'][2:] = 400.
        equal(result, ENGINE.run(changed, np.ones(len(data['last']), np.int8), cfg, detail=True))

    # ----------------------------------------
    # 全50設定は合成のみ。新実データでの機構別損益を監査前に計算しない。
    length = 601
    index = np.arange(length)
    prices = 1000. + np.rint(26 * np.sin(index / 19.) + 5 * np.sin(index / 3.))
    clock = np.floor(index / 3.) * 30.
    data = ready(prices, times=clock)
    data['atr'] = 3. + (index % 17) / 10.
    entry = np.where((index // 91) % 2, -1, 1).astype(np.int8)
    specs = protection_design.catalog()
    for qty in (5, 10):
        for spec in specs:
            cfg = managers.make_config(spec, 'TOPIX' if qty == 5 else 'NK225', {})
            cfg.update(warmup_min=0., entry_cutoff_min=0.)
            full = ENGINE.run(data, entry, cfg, detail=True)
            rows += accounting(data, full, cfg)
            reflect(data, entry, None, cfg, full)
            reflections += 1
            for fraction in (.37, .69):
                cut = int(length * fraction)
                short = {name: value[:cut].copy() if isinstance(value, np.ndarray) else value for name, value in data.items()}
                partial = ENGINE.run(short, entry[:cut], cfg, detail=True)
                prefix_compare(full, partial, cut)
                prefix += 1
                altered = deepcopy(data)
                altered['last'][cut:] = 2000. - altered['last'][cut:] + 111
                altered['atr'][cut:] *= 4
                signal = entry.copy(); signal[cut:] *= -1
                held = entry.copy(); held[cut:] = 0
                modified = ENGINE.run(altered, signal, cfg, detail=True, context=held)
                prefix_compare(full, modified, cut)
                future += 1

    return dict(論理ケース=cases, 残玉cap包含=containment, 合成50設定を両枚数で実行=True,
                上下反射件数=reflections, prefix件数=prefix, 未来価格ATR入口保有方向改変件数=future,
                合成注文会計行数=rows, ATR固定を検査=True)


def reject_invalid() -> dict:
    """機能: 新機能の不正値と、複数建値になる併用を拒否するか検査する。

    引数: なし。返り値: 拒否件数 (dict)。
    """
    data = ready([1000.] * 10)
    state = np.ones(10, np.int8)
    count = 0
    invalid = [dict(residual_risk_cap=x) for x in (-1, .5, 2, float('nan'), float('inf'), '1')]
    invalid += [dict(lock_activation_r=x) for x in (0, -1, float('nan'), float('inf'), '2')]
    for mechanism in (dict(residual_risk_cap=1), dict(lock_activation_r=2.)):
        for field, value in (('add_mode', 1), ('hedge_ratio', .5), ('cover_add', 1), ('reverse_mode', 1)):
            invalid.append(dict(mechanism, **{field: value}))
    for changes in invalid:
        try:
            ENGINE.run(data, state, config(**changes))
        except ValueError:
            count += 1
            continue
        raise AssertionError(f'不正な新機能設定を受理: {changes}')
    return dict(拒否件数=count, 追加カバー反転の禁止=True)


def compatible_only() -> dict:
    """機能: 新機構を無効にした旧互換だけを13セッション全26入力で照合する。

    引数: なし。返り値: 完全一致件数・会計行数 (dict)。損益順位や新機構の成績を出力しない。
    """
    inputs = pickle.loads((OLD / 'inputs.pkl').read_bytes())
    specs = [s for s in managers.manager_catalog() if s['id'] in ('G03', 'G05', 'G11', 'G12', 'G14')]
    d273 = next(s for s in discovery_managers.catalog() if s['id'] == 'D273')
    specs.append(d273)
    k000 = protection_design.catalog()[0]
    assert k000['id'] == 'K000'
    for symbol in ('TOPIX', 'NK225'):
        old = managers.make_config(d273, symbol, {})
        new = managers.make_config(k000, symbol, {})
        assert all(old[k] == new[k] for k in BASE_ENGINE.PARAMS + ['audit_cap'])
        assert new['residual_risk_cap'] == 0 and new['lock_activation_r'] == 1.
    count = rows = kcount = 0
    with np.load(SIGNALS / 'directions/H019.npz', allow_pickle=False) as archive:
        for key, data in inputs.items():
            state = archive['|'.join(key)]
            for spec in specs:
                cfg = managers.make_config(spec, key[1], data)
                old = BASE_ENGINE.run(data, state, cfg, detail=True)
                new = ENGINE.run(data, state, cfg, detail=True)
                equal(old, new)
                rows += accounting(data, new, cfg)
                count += 1
                if spec['id'] == 'D273':
                    new_cfg = managers.make_config(k000, key[1], data)
                    equal(old, ENGINE.run(data, state, new_cfg, detail=True))
                    kcount += 1
    return dict(既定互換管理数=len(specs), 入力数=len(inputs), 既定互換比較数=count,
                K000とD273の完全一致数=kcount, 注文会計行数=rows,
                新機構を有効にした実データ比較数=0)


def main() -> None:
    """機能: 新機構を成績前に監査し、参照不変と合否をJSON/日本語で保存する。

    引数: なし。返り値: なし (None)。API・現在スナップショット・新損益集計を使用しない。
    """
    start = time.perf_counter()
    paths = [Path(__file__), HERE / 'engine_protection.py', HERE / 'protection_design.py',
             PREVIOUS / 'engine_context.py', OLD / 'engine.py', OLD / 'managers.py',
             HERE.parent / 'wave_v25/discovery_managers.py', SIGNALS / 'directions/H019.npz', OLD / 'inputs.pkl']
    hashes = {str(path): digest(path) for path in paths}
    structural = structure()
    rejected = reject_invalid()
    simulated = synthetic()
    print('構造・新機構合成・包含・全50設定の反射/未来不使用が一致', flush=True)
    real = compatible_only()
    assert hashes == {str(path): digest(path) for path in paths}, '監査中に参照ファイルが変更された'
    result = dict(合格=True, API取得数=0, 現在データ使用=False, 新機構の実データ成績計算=False,
                  構造=structural, 不正設定=rejected, 合成=simulated, 旧互換=real, 参照不変=True,
                  SHA256=hashes, 経過秒=time.perf_counter() - start)
    (HERE / 'protection_independent_audit.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    lines = ['# 第5反復・残玉と利益保護の独立監査', '',
             '新機構は合成経路だけで検査した。旧13セッションは既定互換とK000＝D273の照合に限定した。', '',
             f'- 旧の売買優先順・会計処理は同一。simulateの差分は残玉床と始動Rの2箇所だけ。',
             f'- K000とD273は全{real["K000とD273の完全一致数"]}入力で理由まで完全一致。旧既定互換{real["既定互換比較数"]}比較も一致。',
             f'- 新50設定×両枚数の合成を実行。prefix {simulated["prefix件数"]}件、未来改変{simulated["未来価格ATR入口保有方向改変件数"]}件、上下反射{simulated["上下反射件数"]}件が一致。',
             '- 部分利確後も当初RとATRを保持。3R始動は全組の実現＋含み利益で判定し、部分利確後の3ATR順行とは同義でない。',
             '- 1R利益保護は2ATR部分利確より前にも働く。部分利確だけの事後保護とは説明しない。',
             '- D273の残玉1ATR capは小刻み・飛び・呼値端数・買い/売りで既存3ATR追跡に包含された。返済理由コードだけが変わる場合があるが、経済的台帳は一致した。',
             '- 追跡を無効にした診断専用経路ではcapが作動することも確認。探索基準を変更してcapの優位を作るための条件ではない。',
             '- 価格床は次行以降の返済条件であり、損失や利益残存額の無条件保証ではない。新機能の追加・カバー・反転併用は拒否。',
             '- 新機構の実データ収支・順位と現在データは使用していない。監査合格は収益性を意味しない。', '']
    (HERE / 'protection_independent_audit.md').write_text('\n'.join(lines), encoding='utf-8')
    print(json.dumps(dict(合格=True, 旧互換=real, 合成prefix=simulated['prefix件数'], 経過秒=result['経過秒']), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
