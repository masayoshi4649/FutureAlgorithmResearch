"""売買を実行せず、価格四系統と変更しない旧執行・板素材を別々に保存する。"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys

import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'prepared'
SYMBOLS = ('TOPIX', 'NK225')


def module(name: str, path: Path) -> object:
    """
    機能: 損益を参照しない入力部品を固有名で読む。
    引数: name(str)、path(Path)。
    返り値: object。読み込んだモジュール。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(path: Path) -> str:
    """
    機能: 生原本を含む資料の指紋を一定メモリーで求める。
    引数: path(Path)。
    返り値: str。SHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def deny(*args: object, **kwargs: object) -> None:
    """
    機能: 入力準備からの外部通信を拒絶する。
    引数: args(tuple)、kwargs(dict)。
    返り値: None。常に例外で停止する。
    """
    raise RuntimeError('保存済み原本だけで価格素材を準備します')


def save(path: Path, value: object) -> None:
    """
    機能: 新規の担当準備領域へだけ入力素材を保存する。
    引数: path(Path)、value(object)。
    返り値: None。旧入力と正式売買は変更しない。
    """
    assert path.resolve().is_relative_to(OUT.resolve()) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == '.pkl':
        with path.open('wb') as stream:
            pickle.dump(value, stream, protocol=5)
    else:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def coupled_last_features(record: dict, market: dict, core: object) -> dict:
    """
    機能: 旧の源行と窓資格を保ち、価格値だけLPへ変更する単独対照を作る。
    引数: record(dict)は旧執行入力、market(dict)は旧格子特徴、core(object)は高安計算部品。
    返り値: dict。旧源点に対応するLP current/windows/ranges。
    旧midのERや高安をLPへ代用せず再計算する。源不明とLP総変動ゼロは区別する。
    """
    prices = record['price']
    times = record['time_s']
    seq = record['seq']
    now = market['current']['index'].copy()
    safe_now = np.maximum(now, 0)
    size = len(now)
    value = prices[safe_now].copy()
    value[now < 0] = np.nan
    raw_seq = seq[safe_now].copy()
    raw_seq[now < 0] = -1
    source_time = times[safe_now].copy()
    source_time[now < 0] = np.nan
    current = dict(index=now, raw_seq=raw_seq, time_s=source_time, value=value, last=value.copy(),
                   valid=now >= 0, age=market['current']['age'].copy(),
                   actual_age=market['current']['actual_age'].copy())
    first = np.flatnonzero(np.r_[True, np.diff(times) != 0])
    first_prices = prices[first]
    assert np.isfinite(first_prices).all()
    tv = np.r_[0., np.cumsum(np.abs(np.diff(first_prices)))]
    now_position = np.searchsorted(first, safe_now, side='left')
    output = dict(source_kind='旧源行と旧資格を保ったLastPrice対照', current=current, windows={}, ranges={})
    for seconds, old_values in market['windows'].items():
        old = old_values['old'].copy()
        safe_old = np.maximum(old, 0)
        old_position = np.searchsorted(first, safe_old, side='left')
        valid = old_values['source_valid'].copy()
        displacement = prices[safe_now] - prices[safe_old]
        variation = tv[now_position] - tv[old_position]
        efficiency = np.full(size, np.nan)
        good = valid & (variation > 0)
        efficiency[good] = np.abs(displacement[good]) / variation[good]
        assert (efficiency[good] <= 1 + 1e-9).all()
        old_seq = seq[safe_old].copy()
        old_seq[old < 0] = -1
        values = dict(old=old, now=now.copy(), old_seq=old_seq, now_seq=raw_seq.copy(),
                      old_age=old_values['old_age'].copy(), source_valid=valid,
                      same_row=old_values['same_row'].copy(),
                      reset_or_invalid_cross=old_values['reset_or_invalid_cross'].copy(),
                      zero_variation=valid & (variation <= 0),
                      unique_observations=old_values['unique_observations'].copy(),
                      actual_seconds=times[safe_now] - times[safe_old],
                      ret_bp=displacement / prices[safe_old] * 10000., displacement=displacement,
                      total_variation=variation, efficiency=efficiency)
        for name in ('actual_seconds', 'ret_bp', 'displacement', 'total_variation'):
            values[name][~valid] = np.nan
        output['windows'][seconds] = values
        if seconds in market['ranges']:
            high, low = core.extrema(first_prices, old_position, now_position)
            count = (now_position - old_position).astype(np.int32)
            range_valid = market['ranges'][seconds]['source_valid'] & (count >= 2) & np.isfinite(high) & np.isfinite(low)
            width = high - low
            position = np.full(size, np.nan)
            positioned = range_valid & (width > 0)
            position[positioned] = (prices[safe_now][positioned] - low[positioned]) / width[positioned]
            bounds = dict(old=old.copy(), now=now.copy(), source_valid=range_valid, position_valid=positioned,
                          unique_observations=count, high=high, low=low, width=width, position=position,
                          high_distance_points=prices[safe_now] - high, low_distance_points=prices[safe_now] - low,
                          first_time=times[safe_old], last_time=times[first[np.maximum(now_position - 1, 0)]])
            for name in ('high', 'low', 'width', 'high_distance_points', 'low_distance_points', 'first_time', 'last_time'):
                bounds[name][~range_valid] = np.nan
            bounds['unique_observations'][~range_valid] = 0
            output['ranges'][seconds] = bounds
    return output


def prepare_one(key: tuple[str, str], record: dict, grid: np.ndarray, old_market: dict) -> dict:
    """
    機能: 一原本を保存順で全読取し、LPと抽出済み中値の価格資格を独立に準備する。
    引数: key(tuple[str,str])、record(dict)は旧執行入力、grid(ndarray)は旧格子、old_market(dict)は旧特徴。
    返り値: dict。I1/I2/I3の価格素材、LP系列と同原本の診断。
    旧原板のseq・時計・LastPrice・最良価格を全件照合する。数量を約定保証へ転用しない。
    """
    core = module('価格分離入力94_' + '|'.join(key), HERE / 'inputs/core.py')
    last = module('原本LP入力94_' + '|'.join(key), HERE / 'inputs/last_price.py')
    path = ROOT / 'book' / key[1] / (key[0] + '.jsonl')
    size = len(record['seq'])
    bqty = np.full(size, np.nan)
    aqty = np.full(size, np.nan)
    pointer = 0
    raw_count = 0
    identity = None
    hasher = hashlib.sha256()

    def rows() -> object:
        """
        機能: 同じ保存原本を一度だけ読み、原seqとJSONをLP抽出器へ渡す。
        引数: なし。
        返り値: Iterator[tuple[int,dict]]。未観測行を補完又は並べ替えしない。
        """
        nonlocal pointer, raw_count, identity
        with path.open('rb') as stream:
            for seq, line in enumerate(stream):
                hasher.update(line)
                raw_count += 1
                raw = json.loads(line)
                current_identity = tuple(raw.get(field) for field in ('Symbol', 'SymbolName', 'Exchange'))
                assert all(value is not None for value in current_identity), ('銘柄識別欠測', key, seq)
                if identity is None:
                    identity = current_identity
                assert current_identity == identity, ('銘柄又は限月を跨ぐ入力', key, seq)
                if pointer < size and seq == record['seq'][pointer]:
                    assert last.clock(raw.get('CurrentPriceTime')) == record['time_s'][pointer], (key, seq, '時計')
                    assert last.number(raw.get('CurrentPrice')) == record['price'][pointer], (key, seq, 'LP')
                    bid = raw.get('Buy1') or {}
                    ask = raw.get('Sell1') or {}
                    assert bid.get('Price') == record['bid'][pointer], (key, seq, '買価格')
                    assert ask.get('Price') == record['ask'][pointer], (key, seq, '売価格')
                    bqty[pointer] = last.number(bid.get('Qty'))
                    aqty[pointer] = last.number(ask.get('Qty'))
                    assert np.isfinite(bqty[pointer]) and np.isfinite(aqty[pointer]), (key, seq, '最良数量')
                    pointer += 1
                yield seq, raw

    lp = last.extract_last_prices(rows(), float(record['start']), float(record['end']))
    assert pointer == size and lp['diagnostic']['読取原本行'] == raw_count
    mid_book = dict(bid=record['bid'], ask=record['ask'], mid=(record['bid'] + record['ask']) / 2.,
                    last=record['price'], bid_qty=bqty, ask_qty=aqty)
    ready = dict(seq=record['seq'], time_s=record['time_s'], tick=record['tick'], last=record['price'])
    separated = core.price_features(grid, 1, ready, mid_book)
    coupled = coupled_last_features(record, old_market, core)
    raw_lp = last.last_price_features(grid, 1, lp)
    for current in (separated['current'], raw_lp['current']):
        accepted = current['valid']
        assert (current['time_s'][accepted] < grid[accepted] - 1.).all()
    diagnosis = dict(場=key[0], 商品=key[1], 識別=dict(zip(('Symbol', 'SymbolName', 'Exchange'), identity)),
                     原本相対位置=str(path.relative_to(ROOT)), 原本SHA256=hasher.hexdigest(), 原本行数=raw_count,
                     旧執行列全件一致=True, 旧執行行数=size, 独立LP=lp['diagnostic'],
                     中値源現在有効=int(separated['current']['valid'].sum()),
                     LP源現在有効=int(raw_lp['current']['valid'].sum()),
                     中値300ER有限=int(np.isfinite(separated['windows'][300]['efficiency']).sum()),
                     LP300ER有限=int(np.isfinite(raw_lp['windows'][300]['efficiency']).sum()),
                     時計='CurrentPriceTime代理時計。真の受信時計の証明ではない。', 新損益計算=0)
    print(f'{key[0]} {key[1]} 原本{raw_count:,}行・旧執行{size:,}行一致・価格のみ生成', flush=True)
    return dict(key=key, mid=separated, coupled_lp=coupled, lp=raw_lp, lp_record=lp, diagnosis=diagnosis)


def main() -> None:
    """
    機能: 人工入力検査後に62原本の価格素材を別保存し、旧実行入力は指紋参照で保持する。
    引数: なし。
    返り値: None。売買実行・損益閲覧・API取得を行わない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    assert not (OUT / 'metadata.json').exists(), '完成入力は上書きしません'
    proof_path = HERE / 'inputs/価格資格と原LPの人工正負及び未来不変.json'
    proof = json.loads(proof_path.read_text(encoding='utf-8'))
    assert proof['全人工合格'] and proof['売買計算'] == 0
    for relative, expected in proof['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    source = module('旧入力93を不変読取94', ROOT / 'work/wave_v93/data.py')
    material = source.load_inputs()
    sessions = material['metadata']['sessions']
    assert len(sessions) == 31 and len(material['prices']) == 62
    for symbol in SYMBOLS:
        assert {path.stem for path in (ROOT / 'book' / symbol).glob('*.jsonl')} == set(sessions)
    before = {str(path.relative_to(ROOT)): digest(path) for path in material['paths']}
    code_paths = [Path(__file__), HERE / '結果前の設計案.json', proof_path,
                  HERE / 'inputs/core.py', HERE / 'inputs/strict_board.py', HERE / 'inputs/last_price.py']
    code_sha = {str(path.relative_to(ROOT)): digest(path) for path in code_paths}
    lanes = {kind: {session: dict(grid=material['grids'][session]['grid'], markets={}) for session in sessions}
             for kind in ('I1', 'I2', 'I3')}
    diagnoses = []
    records = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs = {pool.submit(prepare_one, key, record, material['grids'][key[0]]['grid'],
                            material['grids'][key[0]]['markets'][key[1]]): key
                for key, record in sorted(material['prices'].items())}
        for job in as_completed(jobs):
            value = job.result()
            key = value['key']
            lanes['I1'][key[0]]['markets'][key[1]] = value['mid']
            lanes['I2'][key[0]]['markets'][key[1]] = value['coupled_lp']
            lanes['I3'][key[0]]['markets'][key[1]] = value['lp']
            records[key] = value['lp_record']
            diagnoses.append(value['diagnosis'])
    for relative, expected in before.items():
        assert digest(ROOT / relative) == expected, ('旧入力変更', relative)
    for relative, expected in code_sha.items():
        assert digest(ROOT / relative) == expected, ('生成途中のコード変更', relative)
    assert len(records) == 62
    save(OUT / 'price_lanes.pkl', lanes)
    save(OUT / 'raw_last_records.pkl', records)
    metadata = dict(全31既知=True, 新未見確認場数=0, sessions=sessions, 口座数=62,
                    入力='I0は旧素材の指紋参照。I1/I2/I3だけ別保存し、旧執行currentとQ及びflowを上書きしない。',
                    源名前空間='中値indexはretained板系列内。LPindexは全原本LP系列内。原seqを常に別記する。',
                    素材取得診断=sorted(diagnoses, key=lambda value: (value['場'], value['商品'])),
                    旧入力SHA256=before, 新コードSHA256=code_sha,
                    新入力SHA256={str(path.relative_to(ROOT)): digest(path)
                                  for path in (OUT / 'price_lanes.pkl', OUT / 'raw_last_records.pkl')},
                    新条件売買実行=0, 新損益閲覧=0, 新損益計算=0, 現在API取得=0, 実注文=0)
    save(OUT / 'metadata.json', metadata)
    print('全62原本の独立価格素材を生成。正式損益は未実行です。', flush=True)


if __name__ == '__main__':
    main()
