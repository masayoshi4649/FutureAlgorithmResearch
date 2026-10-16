"""完成sourceだけを新私有コピーへ結び、原公開票と独立ORIGIN実玉参照を照合する。"""

import ast
import copy
from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import traceback
import numpy as np
from entry_information_reference import Price, Volume, admitted, fak_allowance, price_both, volume_allowed
from entry_state_reference import EntryReference


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENGINE = ROOT / 'work/e01_entry_information_20261014/engine'
PRIVATE = HERE / 'private_entry_information'
sys.dont_write_bytecode = True
sys.path.append(str(ROOT / 'work/e01_protect_reentry_20261014/audit/owned'))
from protect_source_check import fixture, execute_actual


def tree(path: Path) -> ast.Module:
    """
    機能: sourceの説明を除き、経済構文だけを差分照合用に取り出す。
    引数: path(Path) は完成新源又は新所有旧源copy。
    返り値: ast.Module は独立構文木。金融源へ書き戻さない。
    """
    value = ast.parse(path.read_text(encoding='utf-8-sig'))
    for node in ast.walk(value):
        if isinstance(node, (ast.Module, ast.FunctionDef)) and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant) and isinstance(node.body[0].value.value, str):
            node.body.pop(0)
    return value


def source_delta() -> None:
    """
    機能: 新mask末尾引数とreason95採否一枝だけを外し、旧109同構文へ戻るか確認する。
    引数: なし。完成新源と新所有baselineだけを読む。
    返り値: None。FAK/料金/退出/静観へ別経済差があれば止める。
    """
    old = tree(ENGINE / 'baseline_core.py')
    new = tree(ENGINE / 'core.py')
    function = next(n for n in new.body if isinstance(n, ast.FunctionDef) and n.name == 'simulate')
    assert function.args.args[-1].arg == 'entry_allowed' and function.args.defaults[-1].value is None
    function.args.args.pop(); function.args.defaults.pop()
    changed = []
    for node in ast.walk(new):
        if isinstance(node, ast.If) and isinstance(node.test, ast.UnaryOp) and isinstance(node.test.operand, ast.IfExp):
            branch = node.test.operand
            if ast.unparse(branch.body) == 'entry_allowed[i]':
                assert ast.unparse(branch.test) == 'entry_allowed is not None'
                assert any(isinstance(n, ast.Assign) and ast.unparse(n) == 'reason = 95' for n in node.body)
                node.test.operand = branch.orelse; changed.append(node)
    assert len(changed) == 1 and ast.dump(old, include_attributes=False) == ast.dump(new, include_attributes=False)
    assert (ENGINE / 'baseline_core.py').read_bytes() == (ROOT / 'work/e01_price_exit_ablation_20261014/engine/core.py').read_bytes()


class Proxy:
    """
    機能: 既独立fixtureの入力を保ち、反票OFFと公開maskだけを追加する。
    引数: core(object)、allowed(ndarray[bool]|None)、legacy(bool) は新私有核心と固定入口。
    返り値: Proxy は旧入力形を受ける純試験アダプタ。
    """
    def __init__(self, core: object, allowed: np.ndarray | None, legacy: bool = False,
                 peers: dict | None = None):
        """
        機能: Python/JITの両方へ同一maskを固定する。
        引数: core(object)、allowed(ndarray[bool]|None)、legacy(bool)、peers(dict|None)。
        返り値: None。現在票・価格・影feedは変更しない。
        """
        self.core, self.allowed, self.legacy, self.peers = core, allowed, legacy, peers

    def inputs(self, args: tuple) -> tuple:
        """
        機能: 旧helperが自己票を複製したpeer欄を、独立に指定した当時peer票へ差し替える。
        引数: args(tuple) は旧人工入力。
        返り値: tuple はpeer三配列だけを正した入力。元実データは扱わない。
        """
        if self.peers is None:
            return args
        values = list(args)
        values[12:15] = [self.peers[k] for k in ('peer_known', 'peer_count', 'peer_balance')]
        return tuple(values)

    def __call__(self, *args: tuple) -> tuple:
        """
        機能: 旧引数へ必要な固定末尾部品だけを加え私有JITを呼ぶ。
        引数: args(tuple) は人工旧simulate入力。
        返り値: tuple は九出力。
        """
        values = self.inputs(args)
        return self.core.simulate(*values, False) if self.legacy else self.core.simulate(*values, False, self.allowed)

    def py_func(self, *args: tuple) -> tuple:
        """
        機能: 同じ人工入力をPython版へ渡す。
        引数: args(tuple) は人工旧simulate入力。
        返り値: tuple は九出力。金融は実行しない。
        """
        values = self.inputs(args)
        return self.core.simulate.py_func(*values, False) if self.legacy else self.core.simulate.py_func(*values, False, self.allowed)


def account(symbol: str, rows: list, events: dict, up: int, down: int,
            known: bool = True) -> tuple[dict, dict]:
    """
    機能: 独立fixtureから元公開行と旧判断行が異なる明示人工口座を作る。
    引数: symbol(str)、rows(list)、events(dict)、up/down(int)、known(bool)。
    返り値: tuple[dict,dict] は出来高系譜付き人工口座と現在価格票。
    """
    n = len(rows); feed = []; volumes = {}
    mapping = np.arange(n, dtype=np.int64) * 2 + 100
    seq = np.arange(n, dtype=np.int64) * 3 + 400
    for row, group in events.items():
        for event in group:
            feed.append([row, max(0, row - 1), event['cid'], event['side'], event['q'], event.get('price', rows[row].last), 0, int(event['new'])])
            if event['new']:
                a, b = (up, down) if event['side'] > 0 else (down, up)
                count = up + down
                volumes[row] = dict(window_seconds=60, known=known, reason=0 if known else 8,
                    candidate_raw_row=int(mapping[row]), candidate_raw_seq=int(seq[row]), candidate_price_time_s=rows[row].clock,
                    up_votes=a if known else None, down_votes=b if known else None,
                    direction_votes=count if known else None, balance=(up-down)/count if known and count else None)
    a = dict(symbol=symbol, mapping=mapping, record=dict(price=np.array([r.last for r in rows]),
        time_s=np.array([r.clock for r in rows]), seq=seq), feed=np.array(feed, dtype=float).reshape(-1, 8), trade_features={'60': volumes})
    own = dict(known=np.array([r.own['known'] for r in rows], bool), count=np.array([r.own['count'] for r in rows], np.int64),
               balance=np.array([r.own['balance'] if r.own['balance'] is not None else np.nan for r in rows]))
    features = dict(own=own, peer_known=np.array([r.other['known'] for r in rows], bool),
        peer_count=np.array([r.other['count'] for r in rows], np.int64),
        peer_balance=np.array([r.other['balance'] if r.other['balance'] is not None else np.nan for r in rows]))
    return a, features


def gate_checks(gate: object, catalog: object) -> int:
    """
    機能: 完成入口源を既独立signed真偽表と公開系譜の反例へ照合する。
    引数: gate/catalog(object) は完成私有コピー。
    返り値: int は純入口照合数。
    """
    checks = 0
    for symbol, side, up, down, qualified in itertools.product(('TOPIX', 'NK225'), (-1, 1), range(6), range(6), (False, True)):
        rows, events = fixture(symbol, side, 'ORIGIN', 'TARGET', 'native_protection')
        a, f = account(symbol, rows, events, up, down, qualified)
        for config in catalog.configs()[::3]:
            actual = gate.build(a, f, config)
            expected = np.zeros(len(rows), bool)
            for order in a['feed'][a['feed'][:, 7] == 1]:
                row = int(order[0]); v = a['trade_features']['60'][row]
                original = Volume(row, int(a['mapping'][row]), int(a['record']['seq'][row]), rows[row].clock,
                                  qualified, v['up_votes'], v['down_votes'], v['direction_votes'], v['balance'])
                vok = volume_allowed(original, symbol, side, row, original.raw_row, original.raw_seq, original.price_time)
                selected = volume_allowed(original, symbol, side, row, original.raw_row, original.raw_seq, original.price_time, True)
                p = price_both(Price(**rows[row].own), Price(**rows[row].other), side)
                expected[row] = admitted(config['entry_id'], vok, selected, p)
                assert actual['diagnostics'][row]['price_accepted'] == p
            np.testing.assert_array_equal(actual['allowed'], expected); checks += 1
        if symbol == 'NK225':
            selected_config = next(c for c in catalog.configs() if c['entry_id']=='VOL_SELECTED' and c['exit_id']=='TARGET')
            twentyfive_config = next(c for c in catalog.configs() if c['entry_id']=='VOL25' and c['exit_id']=='TARGET')
            np.testing.assert_array_equal(gate.build(a,f,selected_config)['allowed'],gate.build(a,f,twentyfive_config)['allowed'])
            checks += 1
    # ----------------------------------------
    rows, events = fixture('TOPIX', -1, 'ORIGIN', 'TARGET', 'native_protection')
    a, f = account('TOPIX', rows, events, 3, 1)
    config = next(c for c in catalog.configs() if c['entry_id'] == 'VOL_SELECTED' and c['exit_id'] == 'TARGET')
    for key, replacement in (('candidate_raw_row', 999), ('candidate_raw_seq', 999), ('candidate_price_time_s', 999.),
                             ('direction_votes', 3), ('balance', -.5), ('balance', float('nan'))):
        modified = copy.deepcopy(a); modified['trade_features']['60'][1][key] = replacement
        try:
            gate.build(modified, f, config)
        except AssertionError:
            checks += 1
        else:
            raise AssertionError(key)
    return checks


# ----------------------------------------
def main() -> None:
    """
    機能: 完成署名源へ純期待を接続し、PRICE旧同値とVOL実玉の因果接頭を検査する。
    引数: なし。owner完成通知後だけ実行する。
    返り値: None。失敗をFalse保存し、金融源は変更しない。
    """
    destination = HERE / '入口情報一枝と旧PRICE九出力及び完成17源の独立接続.json'
    assert not destination.exists()
    source = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(ENGINE.glob('*.py'))}
    owner_path = ENGINE / '原新規の出来高signed票とPRICE保存同値及び接頭の人工検査_v3.json'
    owner_raw = owner_path.read_bytes(); owner = json.loads(owner_raw.decode('utf-8-sig'))
    assert len(source) == 17 and owner['全合格'] and owner['source_SHA256'] == source
    PRIVATE.mkdir(exist_ok=True)
    for relative, sha in source.items():
        target = PRIVATE / Path(relative).name
        if target.exists():
            assert hashlib.sha256(target.read_bytes()).hexdigest() == sha
        else:
            shutil.copyfile(ROOT / relative, target)
    sys.path.insert(0, str(PRIVATE))
    import core, baseline_core, catalog, entry_gate
    count = dict(入口真偽=0,PRICE旧同値口座=0,VOL独立実玉口座=0,配列=0,接頭=0)
    try:
        source_delta()
        count['入口真偽'] = gate_checks(entry_gate, catalog)
        for symbol, side, exit_id, case in itertools.product(('TOPIX', 'NK225'), (-1, 1),
                ('TARGET', 'TIGHT_TRAIL', 'WIDE_TRAIL'), ('known', 'unknown', 'one_vote', 'opposite', 'refused')):
            rows, events = fixture(symbol, side, 'ORIGIN', exit_id, 'native_protection')
            if case == 'unknown':
                rows = [replace(r, own=dict(known=False, count=0, balance=None), other=dict(known=False, count=0, balance=None)) for r in rows]
            elif case == 'one_vote':
                rows = [replace(r, own=dict(known=True, count=1, balance=float(side)), other=dict(known=True, count=1, balance=float(side))) for r in rows]
            elif case == 'opposite':
                rows = [replace(r, own=dict(known=True, count=4, balance=float(-side)), other=dict(known=True, count=4, balance=float(-side))) for r in rows]
            a, features = account(symbol, rows, events, 3, 1)
            config = next(c for c in catalog.configs() if c['entry_id'] == ('VOL25_PRICE_BOTH' if case == 'refused' else 'VOL25') and c['exit_id'] == exit_id)
            if case == 'refused':
                features['own']['known'][:] = False
                rows = [replace(r, own=dict(known=False, count=0, balance=None)) for r in rows]
            allowed = entry_gate.build(a, features, config)['allowed']
            adapter = SimpleNamespace(simulate=Proxy(core, allowed, peers=features))
            py = execute_actual(adapter, catalog, symbol, 'ORIGIN', exit_id, rows, events, False)
            jit = execute_actual(adapter, catalog, symbol, 'ORIGIN', exit_id, rows, events, True)
            for left, right in zip(py[:8], jit[:8]):
                np.testing.assert_allclose(left, right, equal_nan=True, atol=1e-5, rtol=1e-12); count['配列'] += 1
            assert py[8] == jit[8]
            expected = EntryReference(symbol, exit_id, allowed.tolist())
            for row, point in enumerate(rows):
                expected.step(row, point, events.get(row, []))
            orders = np.array([[o[k] for k in ('row', 'source', 'cid', 'side', 'q', 'price')] + [int(o['new'])]
                               for o in expected.orders], float).reshape(-1, 7)
            np.testing.assert_array_equal(py[0][:, [0, 1, 2, 3, 4, 5, 7]], orders)
            np.testing.assert_array_equal(py[1], [o['uid'] for o in expected.orders])
            np.testing.assert_allclose(py[2][:, 1], [r['liquidation'] for r in expected.curve], atol=1e-5, rtol=1e-12)
            count['配列'] += 3; count['VOL独立実玉口座'] += 1
            for cut in (3, 7):
                prefix_features = {k:features[k][:cut] for k in ('peer_known', 'peer_count', 'peer_balance')}
                prefix_adapter = SimpleNamespace(simulate=Proxy(core, allowed[:cut], peers=prefix_features))
                prefix = execute_actual(prefix_adapter, catalog, symbol, 'ORIGIN', exit_id, rows[:cut], {i:v for i,v in events.items() if i < cut}, False)
                np.testing.assert_array_equal(prefix[0], py[0][py[0][:, 0] < cut])
                np.testing.assert_allclose(prefix[2], py[2][:cut], equal_nan=True, atol=1e-5, rtol=1e-12)
                count['接頭'] += 1
            if case in ('known', 'unknown', 'one_vote', 'opposite'):
                price_config = dict(config, entry_id='PRICE_BOTH')
                price_allowed = entry_gate.build(a, features, price_config)['allowed']
                current = execute_actual(SimpleNamespace(simulate=Proxy(core, price_allowed)), catalog, symbol, 'ORIGIN', exit_id, rows, events, False)
                former = execute_actual(SimpleNamespace(simulate=Proxy(baseline_core, None, True)), catalog, symbol, 'ORIGIN', exit_id, rows, events, False)
                for left, right in zip(current[:8], former[:8]):
                    np.testing.assert_array_equal(left, right); count['配列'] += 1
                assert current[8] == former[8]; count['PRICE旧同値口座'] += 1
        current_source = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in ENGINE.glob('*.py')}
        assert current_source == source
        result = dict(全合格=True,完成source_SHA256=source,所有人工SHA256=hashlib.sha256(owner_raw).hexdigest(),独立確認=count,
                      独立source_SHA256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
                        (HERE / 'entry_information_reference.py', HERE / 'entry_state_reference.py', Path(__file__))},
                      留保='全値は合成人工。実出来高票のtrue攻撃数量、実受信因果又は実利益の証明ではない。',
                      金融=0,原入力=0,台帳=0,API=0,正式登録接続=False)
    except BaseException:
        result = dict(全合格=False,完成source_SHA256=source,独立確認=count,原因=traceback.format_exc(),金融=0,原入力=0,台帳=0,API=0)
        destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
        raise
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True,独立確認=count,SHA256=hashlib.sha256(destination.read_bytes()).hexdigest()), ensure_ascii=False))


if __name__ == '__main__':
    main()
