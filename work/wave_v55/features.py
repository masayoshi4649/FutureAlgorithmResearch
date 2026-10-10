"""保存原本からの気配と価格だけを用い、確定した分足の単純な特徴を作る。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np
import pandas as pd


HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
QUOTE_PATH = ROOT / 'work/wave_v52/measurement/quotes.pkl'
INPUT_PATHS = [ROOT / 'work/wave_v47/inputs.pkl']
INPUT_PATHS += [ROOT / 'work/wave_v48' / folder / 'new_inputs.pkl'
                for folder in ('update_20260930', 'update_20261001')]
INPUT_PATHS += [ROOT / 'work/wave_v50' / folder / 'new_inputs.pkl'
                for folder in ('update_20261001_day', 'update_20261002_two', 'update_20261007_added')]
INPUT_KEYS = ('time_s', 'seq', 'last', 'start', 'limit', 'symbol', 'session', 'tick')
ARRAY_KEYS = ('time_s', 'seq', 'last')
COLUMNS = (
    'time_s', 'seq', 'ready_index', 'source_bar_start', 'bar_start', 'source_last_seq',
    'source_last_time', 'source_count', 'open', 'high', 'low', 'close',
    'last', 'bid', 'ask', 'mid', 'session_open', 'session_open_mid',
    'mean20', 'std20', 'prior20_high', 'prior20_low', 'ema8', 'ema21',
    'prev_open', 'prev_high', 'prev_low', 'prev_close', 'prev_ema8',
    'prev_ema21', 'prev_mean20', 'prev_std20', 'bars_seen', 'continuous20',
    'previous_minute_contiguous', 'bar_age', 'elapsed_s', 'can_trade', 'prev_can_trade',
)


def clean_input(value: dict) -> dict:
    """機能: 既存入力から価格・時刻・場情報だけを取り出す。

    引数: value(dict) は既存の逐次入力。返り値: 許可したキーだけの辞書(dict)。
    旧指標、旧準備判定、旧売買分類は参照せず、この段階で破棄する。
    """
    result = {key: value[key] for key in INPUT_KEYS}
    for key in ARRAY_KEYS:
        result[key] = np.asarray(result[key], dtype=np.int64 if key == 'seq' else np.float64)
    size = len(result['seq'])
    assert size == len(result['time_s']) == len(result['last']) and size > 0
    assert (np.diff(result['seq']) > 0).all()
    assert (np.diff(result['time_s']) >= 0).all()
    assert np.isfinite(result['last']).all() and (result['last'] > 0).all()
    return result


def load_inputs() -> dict:
    """機能: 売買結果を開かず、許可した保存入力だけを全口座について集める。

    引数: なし。返り値: (セッション,銘柄) をキーとする辞書(dict)。
    旧特徴計算コードは実行せず、読み込んだ各辞書を直ちに許可列へ限定する。
    """
    result = {}
    for path in INPUT_PATHS:
        values = pickle.loads(path.read_bytes())
        assert not set(result).intersection(values), path
        result.update({key: clean_input(value) for key, value in values.items()})
    assert len(result) == 46
    return result


def load_inputs_only() -> dict:
    """機能: 約定計算側の共通API名で、指標を除外した価格入力を取得する。

    引数: なし。返り値: load_inputsと同じ全口座入力(dict)。
    """
    return load_inputs()


def empty_features() -> pd.DataFrame:
    """機能: 確定足がまだない場合にも、通常出力と同じ列型の空表を作る。

    引数: なし。返り値: 行数0の特徴表(pd.DataFrame)。
    """
    integer_columns = {'seq', 'ready_index', 'source_last_seq', 'source_count', 'bars_seen'}
    boolean_columns = {'continuous20', 'previous_minute_contiguous', 'can_trade', 'prev_can_trade'}
    return pd.DataFrame({column: pd.Series(dtype=(np.int64 if column in integer_columns else
                                                  bool if column in boolean_columns else np.float64))
                         for column in COLUMNS})


def build_features(ready: dict, quotes: dict) -> pd.DataFrame:
    """機能: 過去の確定1分足と、その次の分の最初の公開行だけで特徴を作る。

    引数: ready(dict) は価格入力、quotes(dict) は同じ原本行の気配配列。
    返り値: 公開時刻順の特徴表(pd.DataFrame)。未完了の末尾足は返さない。
    空白分は補間せず、平均・標準偏差・直前高安の必要区間では連続性を要求する。
    """
    tape = clean_input(ready)
    stamps, seq = tape['time_s'], tape['seq']
    assert np.array_equal(seq, quotes['seq'])
    assert np.array_equal(stamps, quotes['time_s'])
    mid = np.asarray(quotes['mid'], dtype=np.float64)
    bid, ask = np.asarray(quotes['bid']), np.asarray(quotes['ask'])
    assert len(mid) == len(seq) and np.isfinite(mid).all()
    assert (bid > 0).all() and (ask > bid).all()
    assert np.array_equal(mid, (bid + ask) / 2.)
    buckets = np.floor(stamps / 60.) * 60.
    starts = np.r_[0, np.flatnonzero(np.diff(buckets) != 0) + 1]
    if len(starts) < 2:
        return empty_features()

    # ----------------------------------------
    # 確定足の源区間と公開原本行を分離する。現在公開行の気配は足へ混入しない。
    source_first, published = starts[:-1], starts[1:]
    source_last = published - 1
    frame = pd.DataFrame({
        'time_s': stamps[published], 'seq': seq[published], 'ready_index': published,
        'source_bar_start': buckets[source_first], 'bar_start': buckets[source_first], 'source_last_seq': seq[source_last],
        'source_last_time': stamps[source_last], 'source_count': published - source_first,
        'open': mid[source_first], 'high': np.maximum.reduceat(mid, starts)[:-1],
        'low': np.minimum.reduceat(mid, starts)[:-1], 'close': mid[source_last],
        'last': tape['last'][published], 'bid': bid[published], 'ask': ask[published],
        'mid': mid[published], 'session_open': tape['last'][0], 'session_open_mid': mid[0],
    })
    close, source_time = frame['close'], frame['source_bar_start']
    previous_contiguous = source_time.diff().eq(60.)
    continuous20 = source_time.sub(source_time.shift(19)).eq(19 * 60.)
    prior_continuous = source_time.sub(source_time.shift(20)).eq(20 * 60.)
    frame['mean20'] = close.rolling(20, min_periods=20).mean().where(continuous20)
    frame['std20'] = close.rolling(20, min_periods=20).std(ddof=0).where(continuous20)
    frame['prior20_high'] = frame['high'].shift(1).rolling(20, min_periods=20).max().where(prior_continuous)
    frame['prior20_low'] = frame['low'].shift(1).rolling(20, min_periods=20).min().where(prior_continuous)
    frame['ema8'] = close.ewm(span=8, adjust=False).mean()
    frame['ema21'] = close.ewm(span=21, adjust=False).mean()
    for column in ('open', 'high', 'low', 'close', 'ema8', 'ema21', 'mean20', 'std20'):
        frame[f'prev_{column}'] = frame[column].shift(1).where(previous_contiguous)

    # ----------------------------------------
    # 準備完了は経過時間・足の連続・公開遅延だけで決め、値動き幅に依存させない。
    frame['bars_seen'] = np.arange(1, len(frame) + 1, dtype=np.int64)
    frame['continuous20'] = continuous20
    frame['previous_minute_contiguous'] = previous_contiguous
    frame['bar_age'] = frame['time_s'] - (source_time + 60.)
    frame['elapsed_s'] = frame['time_s'] - float(tape['start'])
    frame['can_trade'] = (frame['elapsed_s'].ge(20 * 60.) & continuous20
                          & frame['bar_age'].between(0., 60.))
    frame['prev_can_trade'] = frame['can_trade'].shift(1, fill_value=False) & previous_contiguous
    assert (frame['source_last_seq'] < frame['seq']).all()
    assert (frame['source_last_time'] < frame['time_s']).all()
    assert (source_time + 60. <= frame['time_s']).all()
    return frame.loc[:, COLUMNS]


def slice_inputs(ready: dict, quotes: dict, size: int) -> tuple[dict, dict]:
    """機能: 原本有効行の途中で入力を切り、将来行を除いた検証入力を作る。

    引数: ready(dict)、quotes(dict)、size(int) は残す行数。
    返り値: 切断後の価格入力と気配入力(tuple[dict,dict])。
    """
    result = clean_input(ready)
    for key in ARRAY_KEYS:
        result[key] = result[key][:size]
    return result, {key: np.asarray(value)[:size] for key, value in quotes.items()}


def audit_features(key: tuple, ready: dict, quotes: dict, frame: pd.DataFrame) -> dict:
    """機能: 原本公開順と複数の入力途中切断で特徴値が不変かを監査する。

    引数: key(tuple)、ready(dict)、quotes(dict)、frame(pd.DataFrame)。
    返り値: 口座別の検査件数と準備開始状況(dict)。損益は読まない。
    """
    checks = []
    for size in (1, int(len(ready['seq']) * .35), int(len(ready['seq']) * .75)):
        shorter, shorter_quotes = slice_inputs(ready, quotes, size)
        prefix = build_features(shorter, shorter_quotes)
        expected = frame[frame['seq'] <= shorter['seq'][-1]].reset_index(drop=True)
        pd.testing.assert_frame_equal(prefix, expected, check_exact=True)
        checks.append(dict(原本有効行数=size, 公開済特徴行数=len(prefix), 完全一致=True))
    can = frame[frame['can_trade']]
    result = dict(セッション=key[0], 銘柄=key[1], 原本有効行数=len(ready['seq']),
                  特徴行数=len(frame), 新規可能行数=len(can),
                  観測始値=float(ready['last'][0]), 最初の観測時刻=float(ready['time_s'][0]),
                  場開始との差秒=float(ready['time_s'][0] - ready['start']),
                  最初の準備完了時刻=None if can.empty else float(can.iloc[0]['time_s']),
                  最初の準備完了経過秒=None if can.empty else float(can.iloc[0]['elapsed_s']),
                  途中切断=checks)
    assert set(ready) == set(INPUT_KEYS)
    assert frame['seq'].is_monotonic_increasing
    assert np.array_equal(frame['seq'], ready['seq'][frame['ready_index'].to_numpy(dtype=int)])
    assert np.array_equal(frame['time_s'], ready['time_s'][frame['ready_index'].to_numpy(dtype=int)])
    assert (can['elapsed_s'] >= 1200).all() and can['continuous20'].all()
    assert can['bar_age'].between(0., 60.).all()
    return result


def hash_file(path: Path) -> str:
    """機能: 読み取り専用の原本が気配キャッシュ作成時と同一か照合する値を作る。

    引数: path(Path) は対象ファイル。返り値: SHA256文字列(str)。
    """
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        while block := stream.read(4 * 1024 * 1024):
            hasher.update(block)
    return hasher.hexdigest()


def save_json(path: Path, value: dict) -> None:
    """機能: 日本語の仕様または監査結果をUTF-8で保存する。

    引数: path(Path)、value(dict)。返り値: なし(None)。
    """
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def main() -> None:
    """機能: 全保存入力の分足特徴を生成し、因果性・原本不変・入力範囲を監査する。

    引数: なし。返り値: なし(None)。現在API、売買結果、将来収益は参照しない。
    """
    inputs = load_inputs()
    quotes = pickle.loads(QUOTE_PATH.read_bytes())
    assert set(inputs) == set(quotes)
    inventory = {(path.stem, symbol): path for symbol in ('NK225', 'TOPIX')
                 for path in (ROOT / 'book' / symbol).glob('*.jsonl')}
    added = sorted(set(inventory) - set(inputs))
    missing = sorted(set(inputs) - set(inventory))
    assert not missing, missing
    baseline = json.loads((QUOTE_PATH.parent / '気配キャッシュ監査.json').read_text(encoding='utf8'))
    old_hashes = {(item['セッション'], item['銘柄']): item['原本SHA256'] for item in baseline['原本別']}
    keys = sorted(inputs)
    with ThreadPoolExecutor(max_workers=4) as pool:
        hashes = list(pool.map(hash_file, [inventory[key] for key in keys]))
    for key, digest in zip(keys, hashes):
        assert digest == old_hashes[key], (key, '既存原本が更新されています')

    # ----------------------------------------
    # 旧指標を除いた入力と、新規計算した単純特徴だけを保存する。
    output, audits = {}, []
    for key in keys:
        frame = build_features(inputs[key], quotes[key])
        audit = audit_features(key, inputs[key], quotes[key], frame)
        output[key] = frame
        audits.append(audit)
        print(f'{key[0]} {key[1]}: {len(frame):,} 確定足 / 準備済 {audit["新規可能行数"]:,}', flush=True)
    (HERE / 'clean_inputs.pkl').write_bytes(pickle.dumps(inputs, pickle.HIGHEST_PROTOCOL))
    (HERE / '特徴.pkl').write_bytes(pickle.dumps(output, pickle.HIGHEST_PROTOCOL))
    specification = dict(
        入力='保存原本の有効最良気配を全行保持した価格入力と、同一原本行の買い・売り気配。旧指標や旧準備判定は破棄。',
        計算禁止='ATRは特徴・初期化・準備判定の全てで不使用。旧特徴表は読み込まない。',
        許可入力キー=list(INPUT_KEYS), 特徴列=list(COLUMNS),
        始値='session_openは当場最初に観測した有効最終価格。実際の寄付値の観測を保証しない。中値始値はsession_open_midに分離。',
        分足='mid=(Buy1.Price+Sell1.Price)/2 の観測OHLC。該当分の原本行だけで計算。空白分は補間しない。',
        公開='当該分より後の分の最初の有効原本行で確定公開。末尾の未完了分は破棄。seq/timeは公開行、source_last_seq/timeは源区間末尾。',
        時計の限界='CurrentPriceTimeは約定時刻であり受信時刻ではない。実際の受信遅延や同時刻更新の到着時刻は復元できない。',
        平均と標準偏差='現在確定足を含めた20連続分の終値。標準偏差はddof=0。0も既知の値として保持。',
        直前高安='現在確定足を除く直前20分の中値high/low。現在分への接続も含む21連続分が必要。',
        指数移動平均='当場最初の確定終値で初期化。EMA8/21、adjust=False。空白分に架空価格を挿入しない。空白があっても過去観測EMAを保持する。',
        前値='prev_*はひとつ前の確定足の値。ただし間が60秒でなければNaN。prev_can_tradeもその場合はFalse。',
        新規準備='場開始から20分以上、現在を含む20連続確定分、分の終了から公開まで0〜60秒。値動き幅や標準偏差の大小に依存しない。',
        板の意味='bidはBuy1、askはSell1。取引量・注文方向・板数量の指標は今回計算しない。',
        将来と売買結果='将来ラベル・成績・売買台帳は読み込まない。',
        原本数=len(inputs), セッション数=len({key[0] for key in inputs}),
        追加原本=[list(key) for key in added], 現在API取得数=0,
    )
    save_json(HERE / '測定仕様.json', specification)
    summary = dict(合格=True, 原本数=len(inputs), セッション数=len({key[0] for key in inputs}),
                   原本有効行数=sum(len(value['seq']) for value in inputs.values()),
                   特徴行数=sum(len(value) for value in output.values()),
                   途中切断完全一致件数=sum(len(item['途中切断']) for item in audits),
                   公開時刻原本行整合=True, 原本SHA256一致=True, 入力許可キー限定=True,
                   旧特徴参照=False, ATR計算参照準備条件=False, 売買結果未使用=True,
                   現在API取得数=0, 追加原本=[list(key) for key in added],
                   コードSHA256=hash_file(Path(__file__)), 原本別=audits)
    save_json(HERE / '特徴監査.json', summary)


if __name__ == '__main__':
    main()
