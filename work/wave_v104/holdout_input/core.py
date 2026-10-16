"""一回原本走査から旧normal、独立LP、訂正済み全原行を分離する。"""

from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import types

import numba
import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SESSION = '2026-10-13_Day'
SYMBOLS = ('TOPIX', 'NK225')
CACHE = str(HERE/'jit')


class CacheConfig:
    """旧ソースが要求するJIT保存場所を所有領域へ限定する一時的な設定代理。"""

    def __init__(self, original: object) -> None:
        """
        機能: 通常設定を保持し、CACHE_DIRだけを所有領域へ制限する。
        引数: original(object)は元のnumba.config。
        返り値: None。旧ソースの数値関数は変更しない。
        """
        object.__setattr__(self, 'original', original)

    def __getattr__(self, name: str) -> object:
        """
        機能: CACHE_DIR以外のNumba設定を通常設定へ委譲する。
        引数: name(str)は設定項目。
        返り値: objectは設定値。CACHE_DIRは常に所有領域。
        """
        return CACHE if name == 'CACHE_DIR' else getattr(self.original, name)

    def __setattr__(self, name: str, value: object) -> None:
        """
        機能: 旧コードのCACHE_DIR書換えだけを所有領域へ固定する。
        引数: name(str)は設定項目、value(object)は要求値。
        返り値: None。その他の設定は元の設定へ委譲する。
        """
        setattr(self.original, name, CACHE if name == 'CACHE_DIR' else value)


@contextmanager
def owned_cache() -> object:
    """
    機能: 旧入力関数の読取・人工JITを所有領域へ限定する。
    引数: なし。
    返り値: contextmanagerは一時設定。退出時は元の設定と環境変数を復元する。
    """
    original, old_dir = numba.config, numba.config.CACHE_DIR
    old_env = os.environ.get('NUMBA_CACHE_DIR')
    original.CACHE_DIR = CACHE
    numba.config = CacheConfig(original)
    os.environ['NUMBA_CACHE_DIR'] = CACHE
    try:
        yield
    finally:
        numba.config = original
        original.CACHE_DIR = old_dir
        if old_env is None:
            os.environ.pop('NUMBA_CACHE_DIR', None)
        else:
            os.environ['NUMBA_CACHE_DIR'] = old_env


def module(name: str, relative: str) -> object:
    """
    機能: 旧入力の純関数を固有名で読取接続する。
    引数: name(str)は固有名、relative(str)はルート相対ソース位置。
    返り値: objectはモジュール。main、金融再生、旧cache読取は呼ばない。
    """
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT/relative)
        value = importlib.util.module_from_spec(spec)
        sys.modules[name] = value
        spec.loader.exec_module(value)
    return sys.modules[name]


def modules() -> dict:
    """
    機能: 旧77/91、94独立LP、103原抽出とv2訂正の読取部品を接続する。
    引数: なし。
    返り値: dictは関数所有モジュール。データのload_inputsやplayは実行しない。
    """
    return dict(raw=module('追加Dayの旧8気配関数', 'work/wave_v8/raw_features.py'),
        board=module('追加Dayの旧57逐次表示関数', 'work/wave_v57/features.py'),
        grid=module('追加Dayの旧77価格格子', 'work/wave_v77/inputs/core.py'),
        helper=module('追加Dayの旧91価格欄', 'work/wave_v91/inputs/prepare.py'),
        lp=module('追加Dayの独立94LP', 'work/wave_v94/inputs_r1/last_price.py'),
        source=module('追加Dayの103全原行抽出', 'work/wave_v103/input/core.py'),
        correction=module('追加Dayの103v2二列訂正', 'work/wave_v103/input_v2/correction.py'),
        refs=module('追加Dayの当時始値関数', 'work/wave_v74/inputs/prepare_refs.py'))


class LPCollector:
    """旧94の価格のみの抽出と同じ保存順・欠測・場外断裂を、一行ずつ更新する。"""

    def __init__(self, start: float, end: float, source: object) -> None:
        """
        機能: 独立LPの場と既存数値/時計関数を登録する。
        引数: start/end(float)は場境界、source(object)は旧94 LPモジュール。
        返り値: None。板価格・数量・出来高を参照する状態は作らない。
        """
        self.start, self.end, self.source = start, end, source
        self.previous_raw = self.previous_saved = None
        self.previous_clock, self.pending = -math.inf, 0
        self.sequences, self.times, self.prices, self.reasons = [], [], [], []
        self.count = self.missing = self.outside = self.invalid = 0

    def step(self, seq: int, raw: dict) -> None:
        """
        機能: 一原行から独立LPを更新し、旧94と同じ断裂を保存する。
        引数: seq(int)は0起点原行、raw(dict)は原JSON。
        返り値: None。時計欠測は次保存行へ断裂を伝え、価格不正は時刻付きNaN。
        """
        assert self.previous_raw is None or seq > self.previous_raw
        if self.previous_raw is not None and seq != self.previous_raw+1:
            self.pending |= 2
        self.previous_raw = int(seq)
        self.count += 1
        stamp = self.source.clock(raw.get('CurrentPriceTime'))
        if not math.isfinite(stamp):
            self.missing += 1
            self.pending |= 4
            return
        assert stamp >= self.previous_clock, '旧独立LPは時計逆行を救済しません'
        self.previous_clock = stamp
        if not self.start <= stamp < self.end:
            self.outside += 1
            self.pending |= 8
            return
        reason = self.pending
        if self.previous_saved is None:
            reason |= 1
        elif seq != self.previous_saved+1:
            reason |= 2
        price = self.source.number(raw.get('CurrentPrice'))
        self.invalid += int(not math.isfinite(price))
        self.sequences.append(seq); self.times.append(stamp)
        self.prices.append(price); self.reasons.append(reason)
        self.previous_saved, self.pending = int(seq), 0

    def finish(self) -> dict:
        """
        機能: 旧94と完全同じ列・dtype・診断の独立LPを返す。
        引数: なし。
        返り値: dictはLP系列。物理執行のnormalとは別の名前空間。
        """
        reason = np.asarray(self.reasons, np.uint8)
        prices = np.asarray(self.prices, np.float64)
        return dict(seq=np.asarray(self.sequences, np.int64), time_s=np.asarray(self.times, np.float64),
            last=prices, valid=np.isfinite(prices)&(prices > 0), reset=reason != 0, reset_reason=reason,
            source_kind='原本CurrentPriceのみ', start=self.start, end=self.end,
            diagnostic=dict(読取原本行=self.count, 保存時計行=len(self.times), 時計欠測=self.missing,
                場外=self.outside, 価格不正=self.invalid, 板参照=0, 損益計算=0))


class NormalCollector:
    """旧77 extract_extraの原行採否と旧57の状態を再現し、原本のopenだけを分離する。"""

    def __init__(self, session: str, symbol: str, functions: dict) -> None:
        """
        機能: 正常系列の場・商品・旧逐次板状態を初期化する。
        引数: session/symbol(str)は対象、functions(dict)は旧入力関数。
        返り値: None。新場の価格や終端によって基準を変更しない。
        """
        self.session, self.symbol, self.f = session, symbol, functions
        start, end = functions['raw'].session_bounds(session)
        self.start, self.end, self.start_datetime = start.timestamp(), end.timestamp(), start
        self.tick = functions['raw'].TICKS[symbol]
        self.state = functions['board'].ReplenishmentState(functions['board'].MULTIPLIER[symbol])
        self.fields = {key: [] for key in (*functions['board'].FLOAT_COLUMNS, 'valid', 'reset', 'reset_reason')}
        self.snapshots = {key: [] for key in functions['grid'].LEGACY.SNAPSHOT_FIELDS}
        self.times, self.sequences, self.lasts, self.snapshot_valid, self.events = [], [], [], [], []
        self.first_valid = self.earliest = self.latest = None
        self.previous_time = -math.inf
        self.rejected = dict(時計欠測=0, 場外=0, 最良気配不正=0, 現在値不正=0)

    def step(self, seq: int, raw: dict) -> None:
        """
        機能: 旧77と同じ順番で価格時計、場内、最良気配、現在値を検査する。
        引数: seq(int)は原行番号、raw(dict)は原JSON。
        返り値: None。十段欠測を返済quote_validへ転用しない。
        """
        text = raw.get('CurrentPriceTime')
        if not text:
            self.rejected['時計欠測'] += 1
            return
        stamp = datetime.fromisoformat(text)
        assert stamp.tzinfo is not None and stamp.timestamp() >= self.previous_time
        time = stamp.timestamp()
        self.previous_time = time
        if not self.start <= time < self.end:
            self.rejected['場外'] += 1
            return
        current = self.f['board'].finite(raw.get('CurrentPrice'))
        if current is not None and current > 0:
            point = dict(value=current, seq=seq, time=time, kind='observed_CurrentPrice')
            if self.earliest is None:
                self.earliest = point
            self.latest = point
        quote, _ = self.f['raw'].parse_snapshot(raw)
        if quote is None:
            self.rejected['最良気配不正'] += 1
            return
        if current is None:
            self.rejected['現在値不正'] += 1
            return
        index = len(self.sequences)
        value, events = self.state.step(self.f['board'].snapshot(raw), seq, time, index)
        instant = self.f['grid'].LEGACY.snapshot_values(raw, self.tick)
        assert instant['valid'] == value['valid']
        self.times.append(time); self.sequences.append(seq); self.lasts.append(current)
        self.events.extend(events)
        for name in self.fields:
            self.fields[name].append(value[name])
        for name in self.snapshots:
            self.snapshots[name].append(instant[name])
        self.snapshot_valid.append(instant['valid'])
        if self.first_valid is None:
            self.first_valid = raw

    def finish(self) -> dict:
        """
        機能: 旧77のready/book/snapshotと旧91の物理執行recordを生成する。
        引数: なし。
        返り値: dictは完全旧normal素材、当時参照probe、除外診断。
        """
        assert self.first_valid is not None and self.earliest is not None and self.latest is not None
        ready = dict(seq=np.asarray(self.sequences, np.int64), time_s=np.asarray(self.times, np.float64),
            last=np.asarray(self.lasts, np.float64), session=self.session, symbol=self.symbol,
            start=self.start, limit=self.end-300., tick=self.tick,
            us_open=self.start_datetime.replace(hour=22, minute=30).timestamp())
        book = {name: np.asarray(value, bool if name in ('valid', 'reset') else np.uint8 if name == 'reset_reason' else np.float64)
                for name, value in self.fields.items()}
        book.update(seq=ready['seq'].copy(), time_s=ready['time_s'].copy())
        snapshot = {name: np.asarray(value) for name, value in self.snapshots.items()}
        snapshot.update(seq=ready['seq'].copy(), time_s=ready['time_s'].copy(), valid=np.asarray(self.snapshot_valid, bool))
        record = self.f['helper'].price_record((self.session, self.symbol), ready, book)
        probe = dict(first_valid=self.first_valid, earliest=self.earliest, latest=self.latest, end=self.end)
        return dict(ready=ready, book=book, snapshot=snapshot, record=record, probe=probe,
                    rejected=self.rejected, display_events=np.asarray(self.events, float).reshape((-1, 10)))


def extract_rows(rows: object, session: str, symbol: str) -> dict:
    """
    機能: 同じ原行iteratorを一度だけ進め、全原行v2・旧normal・独立LPへ分配する。
    引数: rows(Iterable[tuple[int,dict]])は元保存順、session/symbol(str)は場と商品。
    返り値: dictはraw/normal/lp/diagnosis。原本再読、未来正常行への移動、金融は行わない。
    """
    with owned_cache():
        functions = modules()
        normal = NormalCollector(session, symbol, functions)
        lp = LPCollector(normal.start, normal.end, functions['lp'])

        def fanout() -> object:
            """
            機能: 一原行を旧normalと独立LPへ公開し、同じ行を103全原行抽出へ渡す。
            引数: なし。
            返り値: Iterator[tuple[int,dict]]は同一保存順。別原本openはない。
            """
            for seq, raw in rows:
                normal.step(seq, raw)
                lp.step(seq, raw)
                yield seq, raw

        raw, diagnostic = functions['source'].extract_rows(fanout(), normal.start, normal.end)
        raw, correction = functions['correction'].correct_arrays(raw)
        retained, price_only = normal.finish(), lp.finish()
        record = retained['record']
        indexes = np.searchsorted(raw['raw_seq'], record['seq'])
        assert (indexes < len(raw['raw_seq'])).all()
        for name, old in (('raw_seq', 'seq'), ('price_time_s', 'time_s'), ('last', 'price'), ('bid', 'bid'), ('ask', 'ask')):
            np.testing.assert_array_equal(raw[name][indexes], record[old])
        raw['normal_execution_row'][indexes] = np.arange(len(indexes), dtype=np.int32)
        raw['execution_to_raw_index'] = indexes.astype(np.int64)
        normal_lp = np.searchsorted(price_only['seq'], record['seq'])
        assert (normal_lp < len(price_only['seq'])).all()
        for name, old in (('seq', 'seq'), ('time_s', 'time_s'), ('last', 'price')):
            np.testing.assert_array_equal(price_only[name][normal_lp], record[old])
        diagnostic['qualifications']['volume_delta_usable'] = int(raw['volume_delta_usable'].sum())
        diagnostic.update(normal_execution_rows=len(indexes), normal_seq_time_lp_bid_ask_equal=True,
            correction=correction, independent_lp=price_only['diagnostic'], raw_open_count=0)
        return dict(session=session, symbol=symbol, raw=raw, normal=retained, lp=price_only,
                    execution_lp_index=normal_lp.astype(np.int32), diagnosis=diagnostic)


def extract_jsonl(path: Path, session: str, symbol: str) -> dict:
    """
    機能: 新場の一原本を一回だけ読み、同じ読取でhashし3系列へ分配する。
    引数: path(Path)は新場原本、session/symbol(str)は固定対象。
    返り値: dictは抽出結果及び一回原本hash。旧32をopenしない。
    """
    assert session == SESSION and symbol in SYMBOLS
    assert path.resolve() == (ROOT/'book'/symbol/(SESSION+'.jsonl')).resolve()
    before = path.stat()
    hasher, byte_count = hashlib.sha256(), 0

    def rows() -> object:
        """
        機能: 新場の原本バイト列を一回hashし、同じバイト列をJSON解釈する。
        引数: なし。
        返り値: Iterator[tuple[int,dict]]は全原行。空行やJSON不正は停止する。
        """
        nonlocal byte_count
        with path.open('rb') as stream:
            for seq, line in enumerate(stream):
                hasher.update(line)
                byte_count += len(line)
                yield seq, json.loads(line)

    value = extract_rows(rows(), session, symbol)
    after = path.stat()
    assert (before.st_size, before.st_mtime_ns) == (after.st_size, after.st_mtime_ns)
    assert byte_count == before.st_size
    value['diagnosis'].update(raw_SHA256=hasher.hexdigest(), raw_bytes=byte_count, raw_open_count=1,
                              raw_stat_size=before.st_size, raw_stat_mtime_ns=before.st_mtime_ns)
    return value


def build_material(extracted: dict[str, dict]) -> tuple[dict, dict]:
    """
    機能: 新場2商品の旧normalと独立LPから、完全旧素材と不変102.prepareを生成する。
    引数: extracted(dict[str,dict])は同場の2抽出結果。
    返り値: tuple[dict,dict]は旧materialとprepare結果。簡易signalに置換せず、金融は実行しない。
    """
    assert set(extracted) == set(SYMBOLS)
    sessions = {item['session'] for item in extracted.values()}
    assert len(sessions) == 1
    session = sessions.pop()
    with owned_cache():
        functions = modules()
        ready = {(session, symbol): item['normal']['ready'] for symbol, item in extracted.items()}
        books = {(session, symbol): item['normal']['book'] for symbol, item in extracted.items()}
        snapshots = {(session, symbol): item['normal']['snapshot'] for symbol, item in extracted.items()}
        prices = {(session, symbol): item['normal']['record'] for symbol, item in extracted.items()}
        grid = functions['grid'].session_features(ready, books, snapshots, session, 1)
        signal = module('追加Dayの旧77入口関数', 'work/wave_v77/signals.py')
        entry = signal.build({session: grid}, ready)[session]
        # ----------------------------------------
        # 旧75のimport名を一時接続し、原本高安/PLから入口を生成しない。
        old_inputs, old_core = sys.modules.get('inputs'), sys.modules.get('inputs.core')
        package = types.ModuleType('inputs')
        package.__path__ = [str(ROOT/'work/wave_v75/inputs')]
        sys.modules['inputs'] = package
        try:
            legacy_core = module('inputs.core', 'work/wave_v75/inputs/core.py')
            legacy_signal = module('追加Dayの旧75共同入口', 'work/wave_v75/signals.py')
            legacy = module('追加Dayの旧77候補生成', 'work/wave_v77/prepared/prepare_legacy.py')
            candidate_grid = legacy_core.session_sync(ready, books, session, delays=(1,), step=15., max_age=30.)['grid']
            legacy.EXTRA = session
            candidates = legacy.build_extra(legacy_signal, candidate_grid, ready, books, 1)
        finally:
            for name, old in (('inputs', old_inputs), ('inputs.core', old_core)):
                if old is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = old
        old_data = sys.modules.get('data')
        sys.modules['data'] = module('追加Dayの旧95入力関数だけ', 'work/wave_v95/data.py')
        try:
            trend = module('追加Dayの旧95独立LP窓', 'work/wave_v95/prepare_prices.py')
        finally:
            if old_data is None:
                sys.modules.pop('data', None)
            else:
                sys.modules['data'] = old_data
        price_core = module('追加Dayの旧94価格資格', 'work/wave_v94/inputs_r1/core.py')
        lanes_helper = module('追加Dayの旧94I0関数', 'work/wave_v94/data_r1.py')
        price_helper = module('追加Dayの旧94結合LP関数', 'work/wave_v94/prepare_inputs_r1.py')
        lanes = {name: {session: dict(grid=grid['grid'], markets={})} for name in ('I0', 'I1', 'I2', 'I3')}
        raw_lp, mappings, trend_markets, references, features = {}, {}, {}, {}, {}
        for symbol, item in extracted.items():
            key, record, book = (session, symbol), item['normal']['record'], item['normal']['book']
            probe, raw = item['normal']['probe'], item['lp']
            reference = functions['refs'].opening_ref(key, item['normal']['ready'], probe)
            assert reference['known_from_i'] == 0, '後から判明した始値を過去へ補完しません'
            references['|'.join(key)] = dict(session=session, symbol=symbol, ref_open=reference)
            features[key] = dict(quality=np.asarray(book['valid']&record['quote_valid']&
                (record['ask']-record['bid'] <= 2*record['tick']+1e-9), bool), reset=np.asarray(book['reset'], bool))
            market = grid['markets'][symbol]
            lanes['I0'][session]['markets'][symbol] = lanes_helper.old_price_channel(market, record)
            mid_book = dict(bid=record['bid'], ask=record['ask'], mid=(record['bid']+record['ask'])/2.,
                            last=record['price'], bid_qty=book['bid_qty'], ask_qty=book['ask_qty'])
            lanes['I1'][session]['markets'][symbol] = price_core.price_features(grid['grid'], 1, item['normal']['ready'], mid_book)
            lanes['I2'][session]['markets'][symbol] = price_helper.coupled_last_features(record, market, price_core)
            lanes['I3'][session]['markets'][symbol] = functions['lp'].last_price_features(grid['grid'], 1, raw)
            trend_markets[symbol] = trend.price_features(grid['grid'], raw)
            for name in ('index', 'raw_seq', 'time_s', 'value', 'valid', 'age', 'actual_age'):
                np.testing.assert_array_equal(trend_markets[symbol]['current'][name], lanes['I3'][session]['markets'][symbol]['current'][name])
            raw_lp[key], mappings[key] = raw, item['execution_lp_index']
        positions = np.searchsorted(grid['grid'], candidate_grid)
        np.testing.assert_array_equal(grid['grid'][positions], candidate_grid)
        material = dict(prices=prices, features=features, grids={session: grid}, entries={session: entry},
            legacy=candidates, price_lanes=lanes, trend_prices={'I3': {session: dict(grid=grid['grid'], markets=trend_markets,
                candidate_grid=candidate_grid, candidate_positions=positions.astype(np.int32))}},
            raw_last_records=raw_lp, execution_lp_index=mappings,
            metadata=dict(sessions=[session], accounts=2, references=references), paths=[])
        config = module('追加Dayの旧102固定条件', 'work/wave_v102/catalog.py')
        reference_config = next(value for value in config.catalog() if value['id'] == 'G0_Q1_X1')
        strategy = module('追加Dayの完全旧102準備', 'work/wave_v102/strategy.py')
        prepared = strategy.prepare(material, reference_config)
        assert set(prepared) == set(prices)
        for key, value in prepared.items():
            assert value['reference_open'] == references['|'.join(key)]['ref_open']['value']
            for name in prices[key]:
                if isinstance(prices[key][name], np.ndarray):
                    np.testing.assert_array_equal(value['record'][name], prices[key][name])
                else:
                    assert value['record'][name] == prices[key][name]
        return material, prepared


def schema() -> dict:
    """
    機能: 新一場の44列を旧103v2と同じ定義にし、原本対応の由来を新一回抽出へ分ける。
    引数: なし。
    返り値: dictは型形状・reset・二列訂正の仕様。旧64原本対応の委譲を新場の合格とは呼ばない。
    """
    with owned_cache():
        value = deepcopy(modules()['source'].schema())
    value['version'] = 2
    value['volume_delta_usable'] += ' 直前price_reset_reasonの価格時計逆行bit8も0を要求する。'
    value['訂正'] = dict(変更列=['volume_delta_usable', 'volume_delta'], 不変列数=42,
        明示式='usable_v2 = usable_v1 & ~previous(price_reset_reason & 8 != 0); delta_v2 = where(usable_v2, volume_delta_observed, NaN)',
        由来='旧103v2のcorrect_arraysを同じ新一回抽出のメモリー上で適用。旧v1誤定義の反例は人工検査で再現。',
        原本対応='新2原本の一回read/hashと原seq/時計/LP/bid/ask全件一致。旧64口座の原本対応は委譲しない。')
    value['normal_alignment'] += ' 完全旧77/91の同normalにquote_valid/price_valid/source_iを付け、入口の深板/量資格とは分離。'
    return value
