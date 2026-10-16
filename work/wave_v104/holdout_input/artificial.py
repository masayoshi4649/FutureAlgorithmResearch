"""旧77実関数を人工バイト列で実行し、一回collectorと完全旧prepareを検査する。"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

import core


HERE = Path(__file__).resolve().parent
ROOT = core.ROOT
JST = timezone(timedelta(hours=9))
SESSION = '2000-01-03_Day'


def digest(path: Path) -> str:
    """
    機能: 人工検査の参照ソースを指紋化する。
    引数: path(Path)はコード又は計画。
    返り値: strはSHA256。実原本及び金融結果は読まない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def equal(left: object, right: object) -> int:
    """
    機能: 欠測を含む型付き入力を再帰的に全件照合する。
    引数: left/right(object)はdict、ndarray又は値。
    返り値: intは照合配列数。不一致は補完せず停止する。
    """
    if isinstance(left, dict):
        assert left.keys() == right.keys(), (left.keys(), right.keys())
        return sum(equal(left[key], right[key]) for key in left)
    if isinstance(left, np.ndarray):
        assert left.dtype == right.dtype and left.shape == right.shape
        np.testing.assert_array_equal(left, right)
        return 1
    if isinstance(left, float) and np.isnan(left):
        assert np.isnan(right)
    else:
        assert left == right, (left, right)
    return 0


def row(symbol: str, offset: float, index: int, price: float | None = None) -> dict:
    """
    機能: 原本とは無関係な、二時計と十段を持つ人工JSON行を生成する。
    引数: symbol(str)、offset(float)は場開始後秒、index(int)は原seq、price(float | None)は価格指定。
    返り値: dictは人工原行。実データ又は終端損益から値を作らない。
    """
    tick, opening = (.5, 4000.) if symbol == 'TOPIX' else (10., 68000.)
    price = opening+tick*index if price is None else price
    start = datetime(2000, 1, 3, 8, 45, tzinfo=JST)
    time = (start+timedelta(seconds=offset)).isoformat()
    value = dict(Symbol='人工'+symbol, SymbolName='人工限月', Exchange=2,
        CurrentPrice=price, CurrentPriceTime=time, OpeningPrice=opening, OpeningPriceTime=start.isoformat(),
        TradingVolume=index+10, TradingVolumeTime=time, TradingValue=(index+10)*price*1000.)
    for side, direction in (('Buy', -1), ('Sell', 1)):
        for depth in range(1, 11):
            value[side+str(depth)] = dict(Price=price+tick*(depth-1 if side == 'Buy' else depth)*direction,
                                        Qty=100.+index % 7+depth)
    return value


def fixture(symbol: str) -> list[tuple[int, dict]]:
    """
    機能: 同時計、深板欠測、出来高欠測、LP不正、時計欠測、最良不正を含む人工原行を作る。
    引数: symbol(str)は商品。
    返り値: list[tuple[int,dict]]は元順の人工素材。
    """
    offsets = (-5., 0., 5., 5., 10., 15., 20., 21., 25., 30., 35.)
    rows = [(index, row(symbol, offset, index)) for index, offset in enumerate(offsets)]
    rows[4][1].pop('Buy9')
    rows[5][1]['TradingVolume'] = None
    rows[6][1]['CurrentPrice'] = None
    rows[7][1]['CurrentPriceTime'] = None
    rows[9][1]['Sell1']['Price'] = rows[9][1]['Buy1']['Price']
    rows[10][1]['TradingVolume'] = 1
    return rows


def old_normal(rows: list[tuple[int, dict]], symbol: str) -> tuple:
    """
    機能: 不変旧77のextract_extraへ人工バイト列だけを渡し、独立した正常系列を得る。
    引数: rows(list[tuple[int,dict]])は連続原seq人工、symbol(str)は商品。
    返り値: tupleは旧77の全返り値。実book openをBytesIOへ置換し、実原本は読まない。
    """
    assert [seq for seq, _ in rows] == list(range(len(rows)))
    payload = b''.join((json.dumps(raw, ensure_ascii=False)+'\n').encode('utf-8') for _, raw in rows)
    target = (ROOT/'book'/symbol/(SESSION+'.jsonl')).resolve()
    functions = core.modules()
    previous = sys.modules.get('core')
    sys.modules['core'] = functions['grid']
    try:
        legacy = core.module('人工だけの旧77実抽出', 'work/wave_v77/inputs/prepare.py')
    finally:
        if previous is None:
            sys.modules.pop('core', None)
        else:
            sys.modules['core'] = previous
    legacy.EXTRA = SESSION
    original_open, original_stat = Path.open, Path.stat

    def open_fixture(path: Path, *args: object, **kwargs: object) -> object:
        """
        機能: 人工対象bookだけをBytesIOへ置換し、その他は通常のソース読取へ委譲する。
        引数: path(Path)、args(tuple)、kwargs(dict)はopen指定。
        返り値: objectは人工バイト列又は通常stream。実対象bookはopenしない。
        """
        return io.BytesIO(payload) if path.absolute() == target else original_open(path, *args, **kwargs)

    def stat_fixture(path: Path, *args: object, **kwargs: object) -> object:
        """
        機能: 人工対象bookのサイズだけを人工値へ置換する。
        引数: path(Path)、args(tuple)、kwargs(dict)はstat指定。
        返り値: objectは人工サイズ又は通常stat。
        """
        return SimpleNamespace(st_size=len(payload)) if path.absolute() == target else original_stat(path, *args, **kwargs)

    with patch.object(Path, 'open', open_fixture), patch.object(Path, 'stat', stat_fixture):
        return legacy.extract_extra(symbol)


def run() -> None:
    """
    機能: 一回collectorの旧完全一致、reset、v2訂正、未来不変と完全102.prepareの人工を確認する。
    引数: なし。
    返り値: None。人工証跡を所有域に保存。新Day内容、旧32原本、金融結果は読まない。
    """
    source_paths = [HERE/name for name in ('core.py', 'artificial.py', 'data.py', 'prepare.py')]
    before = {str(path.relative_to(ROOT)): digest(path) for path in source_paths}
    checks, counts = {}, {}
    with core.owned_cache():
        functions = core.modules()
        count = 0
        for symbol in core.SYMBOLS:
            rows = fixture(symbol)
            seen = []

            def once() -> object:
                """
                機能: 人工原行を一度だけ公開し、走査回数を記録する。
                引数: なし。
                返り値: Iterator[tuple[int,dict]]は人工原行。
                """
                for seq, raw in rows:
                    seen.append(seq)
                    yield seq, raw

            new = core.extract_rows(once(), SESSION, symbol)
            old = old_normal(rows, symbol)
            count += equal(new['normal']['ready'], old[1])
            count += equal(new['normal']['book'], old[2])
            count += equal(new['normal']['snapshot'], old[3])
            count += equal(new['normal']['record'], functions['helper'].price_record((SESSION, symbol), old[1], old[2]))
            count += equal(new['normal']['probe'], old[5])
            lp = functions['lp'].extract_last_prices(iter(rows), new['normal']['record']['start'], new['normal']['record']['end'])
            count += equal(new['lp'], lp)
            original, _ = functions['source'].extract_rows(iter(rows), new['normal']['record']['start'], new['normal']['record']['end'])
            corrected, _ = functions['correction'].correct_arrays(original)
            for name in corrected:
                if name not in ('normal_execution_row', 'execution_to_raw_index'):
                    count += equal(new['raw'][name], corrected[name])
            checks[symbol+'一回走査'] = seen == list(range(len(rows)))
            checks[symbol+'全原行保持'] = new['raw']['raw_seq'].tolist() == list(range(len(rows)))
            normal = new['normal']['record']
            depth_missing = int(np.flatnonzero(normal['seq'] == 4)[0])
            checks[symbol+'深板不明でも物理quote正常を別保存'] = bool(normal['quote_valid'][depth_missing] and
                not new['normal']['book']['valid'][depth_missing] and not new['raw']['depth_valid'][4])
            volume_missing = int(np.flatnonzero(normal['seq'] == 5)[0])
            checks[symbol+'出来高不明でもLP気配を不明にしない'] = bool(normal['quote_valid'][volume_missing] and
                normal['price_valid'][volume_missing] and not new['raw']['volume_delta_usable'][5] and np.isnan(new['raw']['volume_delta'][5]))
            checks[symbol+'LP不正は独立LPへNaN保持しnormalへ代用しない'] = bool(new['raw']['normal_execution_row'][6] == -1 and
                np.isnan(new['lp']['last'][np.flatnonzero(new['lp']['seq'] == 6)[0]]))
            checks[symbol+'時計欠測後LP断裂を保持'] = bool(new['lp']['reset_reason'][np.flatnonzero(new['lp']['seq'] == 8)[0]] & 4)
            checks[symbol+'最良不正を未来正常行へ移動しない'] = new['raw']['normal_execution_row'][9] == -1
            short = core.extract_rows(iter(rows[:6]), SESSION, symbol)
            for name, value in short['raw'].items():
                expected = new['raw'][name][:len(value)] if name == 'execution_to_raw_index' else new['raw'][name][:6]
                count += equal(value, expected)
            changed = deepcopy(rows)
            for seq, raw in changed:
                if seq >= 6:
                    raw['TradingVolume'] = 900000.+seq
            modified = core.extract_rows(iter(changed), SESSION, symbol)
            for name in new['raw']:
                prefix = len(short['raw'][name])
                count += equal(new['raw'][name][:prefix], modified['raw'][name][:prefix])
            checks[symbol+'接頭及び未来変更不変'] = True
        counts['原行及び旧collector照合配列数'] = count
        # ----------------------------------------
        # 旧94と旧77の逆行拒否を保持し、103v2の二列訂正は別に直接検証する。
        reverse = [(index, row('TOPIX', offset, index)) for index, offset in enumerate((0., 10., 5., 20.))]
        rejected = False
        try:
            core.extract_rows(iter(reverse), SESSION, 'TOPIX')
        except AssertionError:
            rejected = True
        checks['旧normal及び独立LPは時計逆行をソート救済しない'] = rejected
        start, end = functions['raw'].session_bounds(SESSION)
        for _, raw in reverse:
            raw['TradingVolumeTime'] = start.isoformat()
        raw_v1, _ = functions['source'].extract_rows(iter(reverse), start.timestamp(), end.timestamp())
        raw_v2, diagnostic = functions['correction'].correct_arrays(raw_v1)
        checks['前価格時計逆行後usableの既知反例を訂正'] = bool(raw_v1['volume_delta_usable'][-1] and
            not raw_v2['volume_delta_usable'][-1] and np.isnan(raw_v2['volume_delta'][-1]) and diagnostic['不変配列数'] == 42)
        # ----------------------------------------
        # 完全旧格子・候補・4価格lane・LP窓を用いた102.prepare。金融executeは呼ばない。
        full = {}
        for symbol in core.SYMBOLS:
            tick, opening = (.5, 4000.) if symbol == 'TOPIX' else (10., 68000.)
            rows = [(index, row(symbol, index*5., index, opening+tick*(index if index < 120 else 240-index))) for index in range(241)]
            full[symbol] = core.extract_rows(iter(rows), SESSION, symbol)
        material, prepared = core.build_material(full)
        checks['旧material全欄及び完全102prepare接続'] = set(material) == {
            'prices', 'features', 'grids', 'entries', 'legacy', 'price_lanes', 'trend_prices',
            'raw_last_records', 'execution_lp_index', 'metadata', 'paths'} and len(prepared) == 2
        checks['旧prepareのLP気配原seq5列一致'] = True
        checks['I0からI3は別名前空間'] = set(material['price_lanes']) == {'I0', 'I1', 'I2', 'I3'}
        checks['始値は当時利用開始0だけ'] = all(material['metadata']['references'][SESSION+'|'+symbol]['ref_open']['known_from_i'] == 0
                                                 for symbol in core.SYMBOLS)
        checks['旧prepareは簡易signalへ置換しない'] = all('entry_support_base' in value and 'loss_observations' in value['signal'] and
            'entry_peer_bbo' in value['signal'] and 'trend_width' in value['signal'] for value in prepared.values())
        counts['旧prepare返り値信号列数'] = {symbol: len(prepared[SESSION, symbol]['signal']) for symbol in core.SYMBOLS}
        counts['旧格子行数'] = len(material['grids'][SESSION]['grid'])
        counts['旧候補行数'] = {symbol: len(material['legacy'][SESSION, symbol]['candidates']) for symbol in core.SYMBOLS}
        prefix = {}
        for symbol in core.SYMBOLS:
            tick, opening = (.5, 4000.) if symbol == 'TOPIX' else (10., 68000.)
            rows = [(index, row(symbol, index*5., index, opening+tick*(index if index < 120 else 240-index))) for index in range(180)]
            prefix[symbol] = core.extract_rows(iter(rows), SESSION, symbol)
        prefix_material, prefix_prepared = core.build_material(prefix)
        cutoff = full['TOPIX']['normal']['record']['start']+900.
        g = int(np.searchsorted(material['grids'][SESSION]['grid'], cutoff, side='left'))
        prefix_checks = 0
        for symbol in core.SYMBOLS:
            old, short = prepared[SESSION, symbol], prefix_prepared[SESSION, symbol]
            normal_count = len(short['record']['seq'])
            for name, array in old['signal'].items():
                if isinstance(array, np.ndarray) and array.ndim:
                    length = normal_count if len(array) == len(old['record']['seq']) else g if len(array) == len(old['signal']['grid']) else None
                    if length is not None:
                        prefix_checks += equal(array[:length], short['signal'][name][:length])
            assert old['reference_open'] == short['reference_open']
            candidates = material['legacy'][SESSION, symbol]['candidates']
            expected = candidates[candidates[:, 1] < normal_count]
            prefix_checks += equal(expected, prefix_material['legacy'][SESSION, symbol]['candidates'])
        checks['完全旧prepareの過去信号と候補は後続原行なしでも一致'] = True
        counts['完全旧prepare接頭照合配列数'] = prefix_checks
        specification = core.schema()
        checks['新場44列は旧v2の訂正規則で原本由来を別記'] = specification['version'] == 2 and \
            len(specification['columns']) == 44 and specification['columns'] == functions['source'].schema()['columns'] and \
            '旧64口座の原本対応は委譲しない' in specification['訂正']['原本対応']
        # 同場始値を後から公表しても、最初normal時点の観測LP参照を使う。
        late_rows = [(index, row('TOPIX', index*5., index)) for index in range(4)]
        late_rows[0][1]['OpeningPrice'] = None
        late_rows[1][1]['OpeningPrice'] = 9999.
        late = core.extract_rows(iter(late_rows), SESSION, 'TOPIX')
        reference = functions['refs'].opening_ref((SESSION, 'TOPIX'), late['normal']['ready'], late['normal']['probe'])
        checks['後からのOpeningPriceを遡及補完しない'] = reference['value'] == 4000. and reference['known_from_i'] == 0 and reference['fallback']
        checks['Numba保存先は所有域'] = numba_cache_safe()
        # ----------------------------------------
        # 実extractの無指定起動を、原本内容や出力の生成前に拒否する。
        import prepare
        with patch.object(sys, 'argv', ['prepare.py']):
            refused = False
            try:
                prepare.main()
            except SystemExit as error:
                refused = error.code == 2
        checks['正式抽出は根確認フラグなしで拒否'] = refused and not (HERE/'metadata.json').exists()
    assert before == {str(path.relative_to(ROOT)): digest(path) for path in source_paths}
    source_sha = dict(before)
    for value in list(sys.modules.values()):
        path = Path(getattr(value, '__file__', '') or '')
        if path.is_file() and path.suffix == '.py' and path.resolve().is_relative_to((ROOT/'work').resolve()):
            source_sha[str(path.resolve().relative_to(ROOT))] = digest(path)
    schema_path = HERE/'入力schema.json'
    if schema_path.exists():
        assert json.loads(schema_path.read_text(encoding='utf-8')) == specification
    else:
        schema_path.write_text(json.dumps(specification, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    source_sha[str(schema_path.relative_to(ROOT))] = digest(schema_path)
    checks = {name: bool(value) for name, value in checks.items()}
    output = dict(全合格=all(checks.values()), 人工専用=True, 検査=checks, 検査件数=len(checks), 件数=counts,
        コードSHA256=source_sha, 正式追加原本読取=0, 新Day価格閲覧=0, 旧32原本再読取=0,
        旧32大型入力cache読取=0, 金融結果読取=0, 金融再生=0, 現在API取得=0, 実注文=0, goal操作=0,
        前場参照読取=0, 前場参照不要='固定G0.prepareの実関数はref_openのみ要求。人工はref_prevを持たず完全接続。',
        制限=['人工の入力互換性だけの証跡。実新場の取得完全性、到着時刻、収益を証明しない。',
              '旧77逐次表示代理を経済対照の入力だけへ再現し、新103/104に真の方向約定を供給しない。'])
    (HERE/'旧normal独立LPと完全prepareの人工検査.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=output['全合格'], 検査件数=len(checks), 件数=counts,
                         不合格=[name for name, value in checks.items() if not value]), ensure_ascii=False))
    assert output['全合格']


def numba_cache_safe() -> bool:
    """
    機能: 旧コードが途中で要求したNumba保存先が所有域へ固定されたことを確認する。
    引数: なし。
    返り値: boolは現在設定及び旧モジュールcache objectの所有域一致。
    """
    import numba
    assert numba.config.CACHE_DIR == core.CACHE
    for module in list(sys.modules.values()):
        for value in list(getattr(module, '__dict__', {}).values()):
            cache = getattr(value, '_cache', None) if type(value).__name__ == 'CPUDispatcher' else None
            locator = getattr(getattr(cache, '_impl', None), '_locator', None)
            if locator is not None:
                assert Path(locator.get_cache_path()).resolve().is_relative_to(HERE.resolve())
    return True


if __name__ == '__main__':
    run()
