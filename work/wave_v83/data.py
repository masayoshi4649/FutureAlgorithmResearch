"""注文条件だけの研究へ、現在値・時計・約定気配の最小入力を提供する。"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
import argparse
import hashlib
import json
import pickle
import sys

import numpy as np


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PREPARED = HERE / 'prepared'
ARRAY_FIELDS = ('time_s', 'price', 'bid', 'ask', 'seq', 'source_i', 'price_valid', 'quote_valid')
TUPLE_FIELDS = (*ARRAY_FIELDS, 'tick', 'start', 'end', 'limit')


def digest(path):
    """
    機能: 大きな保存入力を分割して指紋化する。
    引数: path (Path)。
    返り値: str のSHA256。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_json(path):
    """
    機能: 保存仕様だけを読み取る。
    引数: path (Path)。
    返り値: dict の仕様。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def as_tuple(record):
    """
    機能: 価格入力を数値計算へ渡しやすい固定順の組へ変換する。
    引数: record (dict) は一セッション・一商品の入力。
    返り値: tuple。順はTUPLE_FIELDSで公開する。配列の複製はしない。
    """
    return tuple(record[name] for name in TUPLE_FIELDS)


def load_data(verify=True):
    """
    機能: 今回専用の価格列だけを保存物から読む。
    引数: verify (bool) は保存指紋の照合要否。
    返り値: dict[tuple[str,str],dict] の全30場・両商品入力。
    """
    target = PREPARED / 'inputs.pkl'
    if verify:
        metadata = read_json(PREPARED / '価格入力の照合.json')
        assert digest(target) == metadata['出力SHA256'], '価格入力が固定後に変化しています'
    with target.open('rb') as stream:
        data = pickle.load(stream)
    for record in data.values():
        for name in ARRAY_FIELDS:
            record[name].flags.writeable = False
    return data


def source_quotes(key, quote_cache):
    """
    機能: 旧研究の独立保存約定系列から最良価格だけを取得する。
    引数: key (tuple[str,str])、quote_cache (dict) は旧50口座の価格系列。
    返り値: tuple[dict|None,Path|None]。未保存の追加ナイトは原本抽出へ渡す。
    """
    if key in quote_cache:
        return quote_cache[key], ROOT / 'work/wave_v60/quotes.pkl'
    session, symbol = key
    candidates = [ROOT / f'work/wave_v67/prepared/{session}/features/約定系列_{symbol}_{session}.npz',
                  ROOT / f'work/wave_v71/prepared/features/約定系列_{symbol}_{session}.npz']
    for path in candidates:
        if path.exists():
            with np.load(path) as arrays:
                return {name: arrays[name].copy() for name in ('time_s', 'seq', 'bid', 'ask')}, path
    return None, None


def inspect_raw(args):
    """
    機能: 原本全量の指紋と抽出価格を照合し、未保存の気配だけを原本から取り出す。
    引数: args (tuple) は口座キー、最小入力、原本気配抽出要否、既存指紋。
    返り値: tuple[tuple,dict,list[dict],str,int] の口座、入力、抜取証拠、指紋、原本行数。
    """
    key, record, extract, expected = args
    n = len(record['seq'])
    indices = np.unique(np.linspace(0, n - 1, 7, dtype=np.int64))
    samples = {int(record['seq'][i]): int(i) for i in indices}
    path = ROOT / 'book' / key[1] / (key[0] + '.jsonl')
    h = hashlib.sha256(); rows = 0; i = 0; checks = []
    if extract:
        record['bid'] = np.empty(n, np.float64)
        record['ask'] = np.empty(n, np.float64)
    with path.open('rb') as stream:
        for seq, line in enumerate(stream):
            h.update(line); rows = seq + 1
            selected = extract and i < n and int(record['seq'][i]) == seq
            if not selected and seq not in samples:
                continue
            raw = json.loads(line)
            if selected:
                record['bid'][i] = float(raw['Buy1']['Price'])
                record['ask'][i] = float(raw['Sell1']['Price'])
                assert float(raw['CurrentPrice']) == record['price'][i]
                assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == record['time_s'][i]
                i += 1
            if seq in samples:
                j = samples[seq]
                assert float(raw['CurrentPrice']) == record['price'][j]
                assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == record['time_s'][j]
                assert float(raw['Buy1']['Price']) == record['bid'][j]
                assert float(raw['Sell1']['Price']) == record['ask'][j]
                checks.append(dict(source_i=j, seq=seq, CurrentPrice=raw['CurrentPrice'],
                                   CurrentPriceTime=raw['CurrentPriceTime'],
                                   Buy1=raw['Buy1']['Price'], Sell1=raw['Sell1']['Price']))
    if extract:
        assert i == n
    assert len(checks) == len(indices)
    assert h.hexdigest() == expected, ('原本が旧研究の指紋から変化', key)
    return key, record, checks, h.hexdigest(), rows


# ----------------------------------------
def build_inputs():
    """
    機能: 旧準備と原本照合を用い、方向特徴を持たない60口座の入力を生成する。
    引数: なし。
    返り値: dict[tuple[str,str],dict]。損益・未来ラベル・現在APIは参照しない。
    """
    PREPARED.mkdir(parents=True, exist_ok=True)
    assert not (PREPARED / 'inputs.pkl').exists(), '完成した価格入力は上書きしません'
    meta_path = ROOT / 'work/wave_v77/inputs/metadata.json'
    meta = read_json(meta_path)
    fixed = read_json(ROOT / 'work/wave_v81/初回事前固定.json')
    sessions = fixed['全30']
    assert sessions == meta['sessions'] and len(sessions) == 30
    ready_paths = [ROOT / p for p in meta['input_paths']['ready']] + [ROOT / meta['extra_paths']['ready']]
    data = {}; sources = {meta_path, ROOT / 'work/wave_v81/初回事前固定.json', *ready_paths}
    for path in ready_paths:
        with path.open('rb') as stream:
            values = pickle.load(stream)
        for key, r in values.items():
            assert key not in data
            n = len(r['seq'])
            data[key] = dict(time_s=np.asarray(r['time_s'], np.float64), price=np.asarray(r['last'], np.float64),
                             seq=np.asarray(r['seq'], np.int64), source_i=np.arange(n, dtype=np.int32),
                             session=key[0], symbol=key[1], tick=float(r['tick']), start=float(r['start']),
                             end=float(r['limit']) + 300., limit=float(r['limit']))
        del values
    assert len(data) == 60 and set(k[0] for k in data) == set(sessions)
    with (ROOT / 'work/wave_v60/quotes.pkl').open('rb') as stream:
        quotes = pickle.load(stream)
    missing = set()
    for key, r in data.items():
        q, path = source_quotes(key, quotes)
        if q is None:
            missing.add(key)
        else:
            assert np.array_equal(r['seq'], q['seq']) and np.array_equal(r['time_s'], q['time_s'])
            r['bid'] = np.asarray(q['bid'], np.float64)
            r['ask'] = np.asarray(q['ask'], np.float64)
            sources.add(path)
    del quotes
    expected = {tuple(k.split('|')): v for k, v in meta['旧58原本指紋'].items()}
    expected.update({(r['session'], r['symbol']): r['raw_SHA256'] for r in meta['extra_raw_audit']})
    checks = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for key, r, samples, raw_hash, raw_rows in pool.map(inspect_raw, [(k, data[k], k in missing, expected[k]) for k in sorted(data)]):
            n = len(r['time_s'])
            assert (np.diff(r['time_s']) >= 0).all() and (np.diff(r['seq']) > 0).all()
            assert ((r['time_s'] >= r['start']) & (r['time_s'] < r['end'])).all()
            r['price_valid'] = np.isfinite(r['price']) & (r['price'] > 0)
            r['quote_valid'] = np.isfinite(r['bid']) & np.isfinite(r['ask']) & (r['bid'] > 0) & (r['bid'] < r['ask'])
            assert r['price_valid'].all() and r['quote_valid'].all()
            checks.append(dict(session=key[0], symbol=key[1], rows=n, raw_rows=raw_rows,
                               first_time=float(r['time_s'][0]), last_time=float(r['time_s'][-1]),
                               clock_repeated=int(np.sum(np.diff(r['time_s']) == 0)),
                               price_changed=int(np.sum(np.diff(r['price']) != 0)),
                               retained_gaps=int(np.sum(np.diff(r['seq']) != 1)),
                               price_outside_quote=int(np.sum((r['price'] < r['bid']) | (r['price'] > r['ask']))),
                               原本SHA256=raw_hash, 原本価格時計最良照合=samples,
                               最良原本全行抽出=key in missing))
            print(f'{key[0]} {key[1]} {n:,}行 現在値・時計・気配照合完了', flush=True)
    target = PREPARED / 'inputs.pkl'
    with target.open('wb') as stream:
        pickle.dump(data, stream, protocol=5)
    specification = dict(キー='(session,symbol)', 配列順=list(ARRAY_FIELDS), 計算tuple順=list(TUPLE_FIELDS),
        配列型={k: str(next(iter(data.values()))[k].dtype) for k in ARRAY_FIELDS},
        現在値='priceは原本CurrentPrice。lastや中値の予測変数ではなく、条件発動とトレール極値にだけ使う。bid/askから置換しない。',
        約定価格='bidはBuy1.Price、askはSell1.Price。売りbid・買いaskの約定再現に用い、偏り・厚さ・方向予測へは用いない。',
        時計='time_sは原本CurrentPriceTimeのUnix秒。最終約定時計であり真の受信時計ではない。同時計後続はseqの保存順を保つ。',
        行対応='source_iは既存readyの行番号と同一、seqはJSONLの0始まり原本行番号。同時計の末尾へ未来整列せず、補間も行わない。',
        観測窓='start以上end未満。Day08:45〜15:40、Night17:00〜翌05:55。limit=end−300秒は従来研究の売買区切りでありendと混同しない。',
        行の限定='旧研究と同じ最良気配正常・現在値正常の保持行。ロック板・交差板等の原本行は含まれず、seq飛びで追跡できる。未観測極値は補完しない。',
        現在値と気配='最終約定価格は現在気配の外側に残り得る。その場合も観測値を気配内へ修正しない。',
        使わない情報=['ATR','分足','板数量','OFI','板偏り','補充特徴','移動平均','二市場比較','旧方向状態','将来極値'],
        区別='板情報なしの戦略とは、方向予測へ板内容を使わない意味。注文条件の発動には現在値を観測し、約定評価には最良売買価格を使う。価格データも見ない戦略ではない。',
        制約='同時計内の真の経過時間、実受信からの注文待ち、ミニ/マイクロ実板、板待ち順位、全数量約定、途中極値は確証しない。',
        入力読取='旧ready pickleに同梱された未使用互換列は抽出時だけ読み破棄。旧features/signals/direction配列ファイルは読まない。完成入力には上記価格列のみ。',
        全30=sessions, 前16=fixed['前16'], 後14=fixed['後14'], 損益結果参照=False, 現在API取得=0, 実注文=0)
    (PREPARED / '価格入力の仕様.json').write_text(json.dumps(specification, ensure_ascii=False, indent=2), encoding='utf-8')
    proof = dict(全合格=True, 口座数=len(data), 原本有効行数=sum(len(r['seq']) for r in data.values()),
                 原本抜取照合数=sum(len(c['原本価格時計最良照合']) for c in checks), 原本全60指紋再一致=True,
                 出力SHA256=digest(target), コードSHA256=digest(Path(__file__)),
                 入力SHA256={str(p.relative_to(ROOT)): digest(p) for p in sorted(sources)},
                 各口座=checks, 損益結果参照=False, 現在API取得=0, 実注文=0)
    (PREPARED / '価格入力の照合.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='方向予測を含まない価格入力を準備する')
    parser.add_argument('--build', action='store_true')
    args = parser.parse_args()
    if args.build:
        records = build_inputs()
    else:
        records = load_data()
    print(f'{len(records)}口座、{sum(len(r["seq"]) for r in records.values()):,}行')
