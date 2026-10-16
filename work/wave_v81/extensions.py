"""既存13方向を保ったまま、値幅・板イベント数だけを広げた9方向を追加する。"""

from pathlib import Path
import hashlib
import json
import pickle
import sys
import numpy as np
import numba
from numba import njit


sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT = HERE / 'extended'
numba.config.CACHE_DIR = str(OUT / 'numba_cache')
WIDTHS = (1, 2, 4, 8, 16, 32, 64)
SPANS = (8, 32, 128, 512, 2048)


def digest(path):
    """
    機能: 内容を分割読取して指紋を求める。
    引数: path (Path) はファイル。
    返り値: str のSHA256。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def load(path):
    """
    機能: 保存済み素材を読み込む。
    引数: path (Path) はJSON又はpickle。
    返り値: object の保存内容。
    """
    if path.suffix == '.pkl':
        with path.open('rb') as stream:
            return pickle.load(stream)
    return json.loads(path.read_text(encoding='utf-8'))


def save_json(name, value):
    """
    機能: 拡張担当の領域に証跡JSONを保存する。
    引数: name (str) はファイル名、value (object) は内容。
    返り値: なし。
    """
    target = OUT / name
    assert target.resolve().is_relative_to(OUT.resolve())
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def model_catalog(original):
    """
    機能: 元13の順序を変えず、固定した9モデルだけを末尾へ追加する。
    引数: original (list) は元の固定モデル。
    返り値: list の計22モデル。
    """
    assert len(original) == 13
    addition = [dict(id=f'D1_K{k:02d}', family='価格転換', ticks=k) for k in (16, 32, 64)]
    addition += [dict(id=f'D2_N{n:03d}_T{int(t*100):02d}', family='板フロー', span=n, threshold=t)
                 for n in (512, 2048) for t in (.15, .30)]
    addition += [dict(id=f'D3_K{k:02d}_N{n:03d}_T{int(t*100):02d}', family='価格と板の一致', ticks=k, span=n, threshold=t)
                 for k, n, t in ((16, 512, .15), (32, 2048, .30))]
    return list(original) + addition


# ----------------------------------------
@njit(cache=True)
def event_features(times, seq, bid, ask, bq, aq, usable, tick, widths_ticks, spans):
    """
    機能: 元の遷移を可変個数に拡張し、価格方向と非ゼロOFI平均を逐次計算する。
    引数: 時刻・原本番号・最良価格数量・有効性(ndarray)、tick(float)、widths_ticks/spans(ndarray)。
    返り値: tuple の方向・フロー・件数・隣接比較可否・価格極値。原本飛びはOFI比較元だけを切る。
    """
    size = len(times); nw = len(widths_ticks); ns = len(spans)
    directions = np.zeros((nw, size), np.int8)
    flow = np.full((ns, size), np.nan, np.float32)
    counts = np.zeros(size, np.int32)
    comparable = np.zeros(size, np.bool_)
    extremes = np.full((nw, size), np.nan, np.float32)
    direction = np.zeros(nw, np.int8); extreme = np.zeros(nw)
    numerator = np.zeros(ns); denominator = np.zeros(ns)
    alphas = 2. / (spans + 1.)
    widths = widths_ticks * tick
    anchor = 0.; count = 0; previous = -1; initialized = False
    for i in range(size):
        if i > 0 and times[i] < times[i-1]:
            direction[:] = 0; numerator[:] = 0.; denominator[:] = 0.
            count = 0; previous = -1; initialized = False
        if i > 0 and seq[i] != seq[i-1]+1:
            previous = -1
        if not usable[i]:
            previous = -1
            for k in range(nw):
                if initialized:
                    extremes[k, i] = extreme[k]
            for s in range(ns):
                if denominator[s] > 0.:
                    flow[s, i] = numerator[s] / denominator[s]
            counts[i] = count
            continue
        mid = (bid[i]+ask[i])/2.
        if not initialized:
            anchor = mid; extreme[:] = mid; initialized = True
        changed = previous < 0
        if previous >= 0:
            comparable[i] = True
            changed = bid[i] != bid[previous] or ask[i] != ask[previous] or bq[i] != bq[previous] or aq[i] != aq[previous]
            if changed:
                e = 0.
                if bid[i] >= bid[previous]: e += bq[i]
                if bid[i] <= bid[previous]: e -= bq[previous]
                if ask[i] <= ask[previous]: e -= aq[i]
                if ask[i] >= ask[previous]: e += aq[previous]
                if e != 0.:
                    count += 1
                    for s in range(ns):
                        numerator[s] = (1.-alphas[s])*numerator[s] + alphas[s]*e
                        denominator[s] = (1.-alphas[s])*denominator[s] + alphas[s]*abs(e)
        if changed:
            for k in range(nw):
                if direction[k] == 0:
                    if mid-anchor >= widths[k]-1e-8:
                        direction[k] = 1; extreme[k] = mid
                    elif anchor-mid >= widths[k]-1e-8:
                        direction[k] = -1; extreme[k] = mid
                elif direction[k] == 1:
                    if mid > extreme[k]: extreme[k] = mid
                    if extreme[k]-mid >= widths[k]-1e-8:
                        direction[k] = -1; extreme[k] = mid
                else:
                    if mid < extreme[k]: extreme[k] = mid
                    if mid-extreme[k] >= widths[k]-1e-8:
                        direction[k] = 1; extreme[k] = mid
        previous = i
        for k in range(nw):
            directions[k, i] = direction[k]; extremes[k, i] = extreme[k]
        for s in range(ns):
            if denominator[s] > 0.:
                flow[s, i] = numerator[s] / denominator[s]
        counts[i] = count
    return directions, flow, counts, comparable, extremes


def market_features(ready, book, models):
    """
    機能: 正常な最良板から22方向の状態と有効性を求める。
    引数: ready/book (dict) は既存準備素材、models (list) は固定22モデル。
    返り値: dict の状態と検査用系列。気配差拡大や原本飛びで価格方向・EMAを消さない。
    """
    times, seq = ready['time_s'], ready['seq']
    assert np.all(np.diff(times) >= 0) and np.array_equal(times, book['time_s']) and np.array_equal(seq, book['seq'])
    bid, ask, bq, aq = (book[k] for k in ('bid', 'ask', 'bid_qty', 'ask_qty'))
    usable = np.isfinite(bid) & np.isfinite(ask) & np.isfinite(bq) & np.isfinite(aq)
    usable &= (bid > 0) & (ask > bid) & (bq > 0) & (aq > 0)
    direction, flow, count, comparable, extremes = event_features(
        times, seq, bid, ask, bq, aq, usable, float(ready['tick']), np.asarray(WIDTHS, np.float64), np.asarray(SPANS, np.float64))
    states = np.zeros((len(models), len(times)), np.int8)
    valid = np.zeros_like(states, np.bool_)
    for i, model in enumerate(models):
        if model['id'].startswith('D1'):
            states[i] = direction[WIDTHS.index(model['ticks'])]; valid[i] = usable
        else:
            j = SPANS.index(model['span'])
            sufficient = usable & comparable & (count >= model['span']) & np.isfinite(flow[j])
            f = np.zeros(len(times), np.int8)
            f[sufficient & (flow[j] >= np.float32(model['threshold']))] = 1
            f[sufficient & (flow[j] <= -np.float32(model['threshold']))] = -1
            if model['id'].startswith('D2'):
                states[i] = f
            else:
                d = direction[WIDTHS.index(model['ticks'])]
                agree = sufficient & (d == f)
                states[i, agree] = d[agree]
            valid[i] = sufficient
    return dict(states=states, valid=valid, flow=flow, count=count, comparable=comparable, extremes=extremes)


def project(base, own, peer):
    """
    機能: 既存の自己行・相手厳密過去行を使い、方向配列だけを22行へ拡張する。
    引数: base (dict) は既存二市場素材、own/peer (dict) は追加計算した市場状態。
    返り値: dict の同スキーマ素材。元の13モデル以外の既存補助列は保持する。
    """
    source = base['source_peer']; safe = np.maximum(source, 0)
    fresh = (source >= 0) & (base['age_peer'] > 0.) & (base['age_peer'] <= 10.)
    pv = peer['valid'][:, safe] & fresh
    ps = peer['states'][:, safe].copy(); ps[~pv] = 0
    both = own['valid'] & pv
    common = np.where(both & (own['states'] == ps), ps, 0).astype(np.int8)
    out = dict(base)
    out.update(states_self=own['states'], states_peer=ps, states=common,
               valid_self=own['valid'], valid_peer=pv, valid=both)
    return out


def truncated(record, length):
    """
    機能: 未来の入力行を物理的に切り捨てる。
    引数: record (dict)、length (int) は残す行数。
    返り値: dict の入力前半。
    """
    size = len(record['time_s'])
    return {k: v[:length] if isinstance(v, np.ndarray) and v.ndim and len(v) == size else v for k, v in record.items()}


def prefix_check(ready, books, original, output, models, session):
    """
    機能: 両市場の未来原本を除いた3地点で全22方向と同期を再照合する。
    引数: ready/books/original/output (dict)、models (list)、session (str)。
    返り値: int の口座地点照合数。
    """
    checks = 0
    fields = ('states_self', 'states_peer', 'states', 'valid_self', 'valid_peer', 'valid')
    for symbol in ('TOPIX', 'NK225'):
        peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
        key, pkey = (session, symbol), (session, peer)
        size = len(ready[key]['time_s'])
        for fraction in (.2, .5, .8):
            count = max(1, int(size*fraction)); deadline = ready[key]['time_s'][count-1]
            pcount = max(1, int(np.searchsorted(ready[pkey]['time_s'], deadline, side='left')))
            own = market_features(truncated(ready[key], count), truncated(books[key], count), models)
            other = market_features(truncated(ready[pkey], pcount), truncated(books[pkey], pcount), models)
            base = truncated(original[key], count)
            candidate = project(base, own, other)
            for field in fields:
                assert np.array_equal(candidate[field], output[key][field][:, :count]), (key, fraction, field)
            source = base['source_peer']; known = source >= 0
            assert np.all(source[known] < pcount)
            assert np.all(ready[pkey]['time_s'][source[known]] < base['time_s'][known])
            checks += 1
    return checks


def gap_check():
    """
    機能: 原本番号飛びと最良無効でOFI隣接だけを切り、価格方向・EMAを保つ例を確認する。
    引数: なし。
    返り値: dict の小さな因果境界確認。
    """
    times = np.arange(7, dtype=np.float64); seq = np.array([0, 1, 3, 4, 5, 6, 7], np.int64)
    bid = np.array([100., 102., 103., 104., 105., 106., 105.]); ask = bid+1.
    qty = np.full(7, 10.); usable = np.ones(7, np.bool_); usable[3] = False
    direction, flow, count, comparable, _ = event_features(times, seq, bid, ask, qty, qty, usable, 1., np.asarray(WIDTHS, float), np.asarray(SPANS, float))
    assert count.tolist() == [0, 1, 1, 1, 1, 2, 3]
    assert not comparable[2] and not comparable[3] and not comparable[4] and comparable[5]
    assert direction[0, 1] == 1 and direction[0, 2] == 1 and direction[0, 4] == 1 and direction[0, 6] == -1
    assert np.all(flow[:, 2] == flow[:, 1]) and np.all(flow[:, 4] == flow[:, 2])
    return {'合格': True, '原本飛びで架空OFIを加えない': True, '復帰初行でOFI比較をしない': True,
            'D1とEMAは保持': True, '実観測による反転は継続': True}


# ----------------------------------------
def main():
    """
    機能: 追加9モデルを損益前に固定し、元13完全一致・未来切断を検査して拡張素材を保存する。
    引数: なし。
    返り値: なし。extensions.py と extended 内だけを担当し、損益ファイルを読まない。
    """
    OUT.mkdir(parents=True, exist_ok=True)
    fixed = load(HERE / '初回事前固定.json'); models = model_catalog(fixed['モデル'])
    original_path = HERE / 'prepared/signals.pkl'
    spec = {'目的': '小さい往復を波の反転として数え過ぎる可能性を、価格変位と非ゼロ板イベント数の尺度だけで調べる。',
            '新モデルの損益未参照': True, 'モデル': models, '元モデル数': 13, '追加モデル数': 9,
            '固定する追加': models[13:], '時間出口': '追加しない。利確幅・保有期限・休止時間も追加しない。',
            '品質': '元の最良正常性を使用。spread拡大と10段valid/resetで方向やEMAを消さない。seq飛び・最良無効ではOFI比較元だけ破棄する。',
            '同期': '自己は現在の既読原本行、相手は既存source_peerによる厳密過去の時計先頭。age10秒制約も元と同じ。',
            '出力': 'states_self/states_peer/states と valid_self/valid_peer/valid の6列を22行へ拡張。他の既存列は元13の補助情報のまま保持。flow補助列は従来8/32/128だけであり追加モデルを含まない。',
            'コードSHA256': digest(Path(__file__)), '元signalsコードSHA256': digest(HERE / 'signals.py'),
            '元素材SHA256': digest(original_path), '現在API取得': 0, '実注文': 0}
    frozen = OUT / '拡張事前固定.json'
    if frozen.exists():
        assert load(frozen) == spec, '固定後の仕様・コード・元素材の変更'
    else:
        save_json(frozen.name, spec)
    print('追加9定義を損益参照前に固定', flush=True)
    metadata = load(ROOT / 'work/wave_v77/inputs/metadata.json')
    ready, books = {}, {}
    for kind, target, extra in (('ready', ready, 'extra_inputs.pkl'), ('features', books, 'extra_features.pkl')):
        for path in [ROOT / p for p in metadata['input_paths'][kind]] + [ROOT / 'work/wave_v77/inputs' / extra]:
            part = load(path); assert not set(target) & set(part); target.update(part)
    original = load(original_path); output = {}; proof_rows = []; checks = 0
    gap = gap_check()
    fields = ('states_self', 'states_peer', 'states', 'valid_self', 'valid_peer', 'valid')
    for session in fixed['全30']:
        markets = {s: market_features(ready[(session, s)], books[(session, s)], models) for s in ('TOPIX', 'NK225')}
        for symbol in ('TOPIX', 'NK225'):
            key = (session, symbol); peer = 'NK225' if symbol == 'TOPIX' else 'TOPIX'
            out = project(original[key], markets[symbol], markets[peer]); output[key] = out
            for field in fields:
                assert np.array_equal(out[field][:13], original[key][field]), (key, field, '既存13が変化')
            assert np.array_equal(markets[symbol]['flow'][:3], original[key]['flow_self'], equal_nan=True)
            assert np.array_equal(markets[symbol]['count'], original[key]['flow_count_self'])
            assert np.array_equal(markets[symbol]['comparable'], original[key]['flow_comparable_self'])
            assert np.array_equal(markets[symbol]['extremes'][:4], original[key]['turn_extreme_self'], equal_nan=True)
            assert out['states'].shape == (22, len(out['time_s']))
            assert np.all(out['states'][~out['valid']] == 0)
            proof_rows.append({'セッション': session, '商品': symbol, '原本準備行数': len(out['time_s']),
                '追加モデル': {m['id']: {'自己方向あり': int(np.count_nonzero(out['states_self'][i])),
                    '共同方向あり': int(np.count_nonzero(out['states'][i])), '共同有効': int(out['valid'][i].sum())}
                    for i, m in enumerate(models) if i >= 13}})
        checks += prefix_check(ready, books, original, output, models, session)
        print(f'拡張と未来切断合格 {session}', flush=True)
    assert digest(original_path) == spec['元素材SHA256']
    target = OUT / 'signals.pkl'
    with target.open('wb') as stream:
        pickle.dump(output, stream, protocol=5)
    proof = {'全合格': True, 'モデル数': 22, '旧13完全一致口座数': len(output), '旧13一致対象': list(fields),
             '旧フロー3種と極値4種も完全一致': True, '未来切断照合数': checks, '小境界例': gap,
             '元素材未変更': True, '損益参照': False, '各場': proof_rows,
             'signals_SHA256': digest(target), '拡張事前固定_SHA256': digest(frozen)}
    save_json('拡張方向準備と因果照合.json', proof)
    save_json('metadata.json', {'モデル': models, '全30': fixed['全30'], '前16': fixed['前16'], '後14': fixed['後14'],
                               '旧13保持': True, '追加9': models[13:], 'signals_SHA256': proof['signals_SHA256'],
                               '補助列の注意': spec['出力']})
    print(json.dumps({k: v for k, v in proof.items() if k != '各場'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
