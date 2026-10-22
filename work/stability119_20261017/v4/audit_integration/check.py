"""元保存方針の順逆・時刻因子と既存kernelへの接続だけを合成素材で確認する。"""

import ast
from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent
ENGINE = HERE.parents[0]
BASE = ENGINE.parent
ROOT = BASE.parents[1]
COUNTS = []


def require(condition: bool, label: str) -> None:
    """
    機能: 独立期待との一致を名前付きで記録する。
    引数: condition(bool)は検証式、label(str)は検査内容。
    返り値: None。不一致なら後続を実行しない。
    """
    assert condition, label
    COUNTS.append(label)


def load(path: Path, name: str) -> object:
    """
    機能: 完成通知済みの源だけを通常moduleとして読み込む。
    引数: path(Path)はPython源、name(str)は私有module名。
    返り値: objectは定義済みmodule。mainは呼ばない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    """
    機能: 対象source又は小目録の指紋を計算する。
    引数: path(Path)はこの監査の許可範囲のファイル。
    返り値: strはSHA256。市場cacheを開くためには使用しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def quiet_oracle(stamp: float) -> bool:
    """
    機能: 当時時刻だけから固定窓を独立に判定する。
    引数: stamp(float)は公開価格時計。
    返り値: boolは半開区間の窓内。未知は窓内へ補完しない。
    """
    if not np.isfinite(stamp):
        return False
    jp = datetime.fromtimestamp(stamp, timezone(timedelta(hours=9)))
    ny = jp.astimezone(ZoneInfo('America/New_York'))
    own = (jp.hour, jp.minute, jp.second, jp.microsecond)
    peer = (ny.hour, ny.minute, ny.second, ny.microsecond)
    return ((8, 45, 0, 0) <= own < (9, 15, 0, 0)
        or (8, 15, 0, 0) <= peer < (8, 45, 0, 0)
        or (9, 15, 0, 0) <= peer < (9, 45, 0, 0))


def base_fixture(n: int) -> dict:
    """
    機能: 成績に依存しない三つの元方針を合成する。
    引数: n(int)は公開足数。
    返り値: dictはG0三元IDと五つの配列。退出方向を非対称にする。
    """
    entries = np.asarray([[1 if (i + k) % 4 == 0 else -1 if (i + k) % 4 == 2 else 0
                           for i in range(n)] for k in range(3)], np.int8)
    return dict(specs=[dict(id=f'{family}_L20_X0_E0_G0', family=family,
                           name=family, description='独立合成方針')
                       for family in ('COMMON', 'OPEN', 'LAG')],
        entry=entries, exit_long=np.asarray([[(i+k) % 3 == 0 for i in range(n)] for k in range(3)], bool),
        exit_short=np.asarray([[(i+k) % 5 == 0 for i in range(n)] for k in range(3)], bool),
        width=np.asarray([[5. + k + i / 100 for i in range(n)] for k in range(3)], np.float64),
        valid=np.asarray([[(i+k) % 7 != 0 for i in range(n)] for k in range(3)], bool))


def array_tests(run: object) -> None:
    """
    機能: 48方針の反転・時刻・接頭と元配列非変更を独立期待へ照合する。
    引数: run(object)は完成run_v4部品。
    返り値: None。実保存policyは読まない。
    """
    times = []
    for month, day in ((1, 15), (7, 15)):
        for zone in (timezone(timedelta(hours=9)), ZoneInfo('America/New_York')):
            for hour, minute in ((8, 15), (8, 45), (9, 15), (9, 45)):
                edge = datetime(2026, month, day, hour, minute, tzinfo=zone).timestamp()
                times.extend((edge - .001, edge, edge + .001))
    times = np.asarray(times + [np.nan], float)
    base = base_fixture(len(times))
    before = {key: base[key].copy() for key in run.POLICY_KEYS}
    actual = run.build_variants(base, times)
    quiet = np.asarray([quiet_oracle(t) for t in times], bool)
    require(np.array_equal(actual['time_quiet'], quiet), '夏冬時間と半開窓の独立境界')
    require(len(actual['specs']) == len({s['id'] for s in actual['specs']}) == 48, '48ID一意')
    for k, spec in enumerate(actual['specs']):
        origin = ('COMMON', 'OPEN', 'LAG').index(spec['family'].removesuffix('20'))
        inverse = spec['direction_mode'] == 'reverse'
        expected = {name: before[name][origin].copy() for name in run.POLICY_KEYS}
        expected['entry'] *= -1 if inverse else 1
        if inverse:
            expected['exit_long'], expected['exit_short'] = expected['exit_short'], expected['exit_long']
        if spec['time_mode']:
            expected['entry'][quiet] = 0
            expected['valid'][quiet] = False
            expected['exit_long'][quiet] = expected['exit_short'][quiet] = True
        for key in run.POLICY_KEYS:
            require(np.array_equal(actual[key][k], expected[key], equal_nan=True), spec['id'] + '/' + key)
        require(spec['guard'] == 2 and spec['exit_mode'] in (4, 5)
                and spec['execution_mode'] in (0, 3), spec['id'] + '/固定因子')
    for key in run.POLICY_KEYS:
        require(np.array_equal(base[key], before[key]), '元配列非変更/' + key)
    for end in (1, 17, len(times)-1):
        prefix = run.build_variants(dict(specs=base['specs'], **{k: before[k][:, :end] for k in run.POLICY_KEYS}), times[:end])
        for key in run.POLICY_KEYS:
            require(np.array_equal(prefix[key], actual[key][:, :end]), f'独立接頭{end}/{key}')
    changed = times.copy()
    changed[17:] = datetime(2026, 10, 17, 8, 50, tzinfo=timezone(timedelta(hours=9))).timestamp()
    suffix = run.build_variants(base, changed)
    for key in run.POLICY_KEYS:
        require(np.array_equal(suffix[key][:, :17], actual[key][:, :17]), '未来時計変更不変/' + key)

    # ----------------------------------------
    # 元のG0/G1は同じ保存配列の索引対照であり、新guard2の実損益同値とは別。
    tree = ast.parse((BASE / 'run119.py').read_text(encoding='utf8'))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'variants')
    namespace = dict(itertools=itertools, np=np)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<元派生関数の純抽出>', 'exec'), namespace)
    original = dict(base, specs=[dict(s, id=s['family'] + '_L20') for s in base['specs']])
    expanded = namespace['variants'](original)
    for family in ('COMMON', 'OPEN', 'LAG'):
        indexes = [next(i for i, s in enumerate(expanded['specs']) if s['id'] == family + f'_L20_X0_E0_G{g}') for g in (0, 1)]
        for key in run.POLICY_KEYS:
            require(np.array_equal(expanded[key][indexes[0]], expanded[key][indexes[1]]), family + '/G0G1/' + key)


def small_market(scene: str, symbol: str) -> tuple[dict, dict, dict]:
    """
    機能: 旧市場を参照せず約定先後を確認できる価格列を作る。
    引数: scene/symbol(str)は人工場名と商品名。
    返り値: tuple[dict,dict,dict]は足、正常気配、元三方針。
    """
    date = datetime.fromisoformat(scene[:10]).replace(tzinfo=timezone(timedelta(hours=9)))
    start = date + timedelta(hours=18 if scene.endswith('Night') else 10)
    tick = .5 if symbol == 'TOPIX' else 10.
    price = 4000. if symbol == 'TOPIX' else 60000.
    clock = start.timestamp() + np.arange(26) * 2.
    quotes = dict(row=np.arange(26, dtype=np.int64), time=clock,
        bid=price + np.asarray([0, 0, 3, 4, -2, -4, -5, -2, 0, 4, 5, 2, 0] * 2) * tick,
        last=np.full(26, price), bq=np.full(26, 100.), aq=np.full(26, 100.))
    quotes['ask'] = quotes['bid'] + tick
    rows = np.asarray([0, 4, 8, 12, 16, 20], np.int64)
    bars = dict(valid=np.ones(6, bool), anchor=quotes['last'][rows], pub_raw_row=rows,
        pub_price_time_s=clock[rows], t_s=clock[rows], close=quotes['last'][rows])
    base = base_fixture(6)
    base['valid'][:] = True
    base['width'][:] = 5 * tick
    base['entry'][:] = 0
    base['entry'][:, 0] = 1
    base['entry'][:, 3] = -1
    base['exit_long'][:] = base['exit_short'][:] = False
    base['exit_long'][:, 2] = True
    base['exit_short'][:, 4] = True
    return bars, quotes, base


def kernel_tests(run: object) -> None:
    """
    機能: 少数の独立実side・料金・後rawrow・未返済を旧kernelへ接続する。
    引数: run(object)は完成driver。replayはpy_funcへ限定する。
    返り値: None。kernel単体監査の大規模再試験は行わない。
    """
    for symbol in ('TOPIX', 'NK225'):
        bars, quotes, base = small_market('2026-10-01_Day', symbol)
        model = run.build_variants(base, bars['pub_price_time_s'])
        for index, spec in enumerate(model['specs']):
            if spec['family'] != 'COMMON20' or spec['time_mode'] != 0:
                continue
            config = run.run_v2.settings(symbol, '2026-10-01_Day', spec['execution_mode'], spec['exit_mode'], 2)
            config['close_time'] = quotes['time'][-2]
            policy = {key: model[key][index] for key in run.POLICY_KEYS}
            answer = run.engine_v2.run_policy(bars, quotes, policy, config)
            ledger = answer['ledger']
            require(len(ledger) > 0, symbol + spec['id'] + '/実返済あり')
            expected_side = -1 if spec['direction_mode'] == 'reverse' else 1
            require(int(ledger[0, 5]) == expected_side, symbol + spec['id'] + '/実side')
            for row in ledger:
                first = np.flatnonzero(quotes['row'] == int(row[1]))[0]
                final = np.flatnonzero(quotes['row'] == int(row[2]))[0]
                side = int(row[5])
                require(row[7] == quotes['ask' if side == 1 else 'bid'][first]
                        and row[8] == quotes['bid' if side == 1 else 'ask'][final], spec['id'] + '/実反対気配')
                expected_net = side * (row[8] - row[7]) * row[6] * config['multiplier'] - row[10] - row[11]
                require(abs(row[12] - expected_net) < 1e-7, spec['id'] + '/円会計')
            require(abs(answer['summary']['profit'] - answer['summary']['loss'] - answer['summary']['realized']) < 1e-7,
                    symbol + spec['id'] + '/完結会計')
            require(int(ledger[0, 1]) > int(bars['pub_raw_row'][int(ledger[0, 14])]), spec['id'] + '/新規は公開後原行')
    top = run.run_v2.settings('TOPIX', '2026-10-01_Day', 0, 5, 2)
    nk = run.run_v2.settings('NK225', '2026-10-01_Night', 3, 4, 2)
    require((top['quantity'], top['multiplier'], top['fee'], top['order_tick'], top['observed_tick']) == (10, 1000., 41.8, .25, .5), 'TOP実契約')
    require((nk['quantity'], nk['multiplier'], nk['fee'], nk['order_tick'], nk['observed_tick']) == (20, 10., 11., 5., 10.), 'NK実契約')
    for config, hours in ((top, (15, 0, 15, 20)), (nk, (5, 20, 5, 40))):
        a, b = (datetime.fromtimestamp(config[k], timezone(timedelta(hours=9))) for k in ('entry_end', 'close_time'))
        require((a.hour, a.minute, b.hour, b.minute) == hours, '場内締切')


def main() -> None:
    """
    機能: 完成sourceと少数人工を結び、原市場を開かず独立証跡を保存する。
    引数: なし。
    返り値: None。正式freeze・register・金融mainは実行しない。
    """
    sys.dont_write_bytecode = True
    run = load(ENGINE / 'run_v4.py', '_独立119d運転')
    plan = load(ENGINE / 'plan_v4.py', '_独立119d計画')
    sources = plan.economic_sources()
    require(sha(ENGINE / 'run_v4.py') == 'fc503c0e3caeeff2ecc948077628c2917c8bc2146f9acf7ea6a4ff46464a9800', '完成run指紋')
    require(sha(ENGINE / 'plan_v4.py') == 'a402aef407bb17a7ebf45869a0e3920271772a7d08246a1d8ea0a41248f3e132', '完成plan指紋')
    original = run.engine_v2.replay
    run.engine_v2.replay = original.py_func
    try:
        array_tests(run)
        kernel_tests(run)
    finally:
        run.engine_v2.replay = original
    require(plan.economic_sources() == sources, '経済七源不変更')
    clean = run.run_v2.clean(dict(a=np.bool_(True), b=np.int64(4), c=np.float64(np.nan), d=np.asarray([np.inf, 1.])))
    require(json.loads(json.dumps(clean, allow_nan=False)) == dict(a=True, b=4, c=None, d=[None, 1.]), '保存型と未知None')
    proof = dict(全合格=True, 確認数=len(COUNTS), 確認=COUNTS, source_SHA256=sources,
        元候補='保存G0三元ID。G1との差は派生guardだけで元五配列は同値。',
        scope='SOURCE_ONLYと合成素材。正式八部品と実登録の指紋は根freeze後の別接続。',
        留保=['元公開候補時点は共通だが、実受理集合は同一とは限らない。',
              '全24の金融とは異なり、48へ増やす前の実測は一切ない。',
              '時間窓は公開時に適用し、窓開始時の強制timer又は窓内約定禁止ではない。',
              '実効Rの場尺度開始も移り得る。事後選択や損益単純反転は行わない。'],
        原市場読取=0, 保存cache本文読取=0, 金融結果本文読取=0,
        試行台帳本文読取=0, 金融再生=0, 正式登録=0, API=0)
    output = HERE / '保存元三方針の順逆と四十八政策及び既存kernelの独立接続.json'
    assert not output.exists()
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')
    print(json.dumps(dict(全合格=True, 確認数=len(COUNTS), 証跡=output.name, SHA256=sha(output)), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
