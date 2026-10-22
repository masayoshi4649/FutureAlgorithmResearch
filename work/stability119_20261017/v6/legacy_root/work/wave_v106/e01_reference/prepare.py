"""追加三場の元E01素材と全33の同一原行気配を準備する。金融は行わない。"""

import argparse
import gc
import pickle

import numpy as np

from bridge import HERE, ROOT, SESSIONS_EXTRA, digest, owned_cache, read, runtime, save, source_hashes
from specification import specification


def quotes(ready: dict, quote: dict) -> dict:
    """
    機能: 同じ原連番の気配だけをE01入力へ接続する。
    引数: ready(dict)は元入力、quote(dict)は保存気配。
    返り値: dict。未来近傍行への補間・代替はしない。
    """
    a, b = np.asarray(ready['seq']), np.asarray(quote['seq'])
    j = np.searchsorted(b, a)
    assert len(b) and np.all(j < len(b)) and np.array_equal(a, b[j])
    np.testing.assert_array_equal(ready['time_s'], quote['time_s'][j])
    price = quote['price'] if 'price' in quote else quote['last']
    np.testing.assert_array_equal(ready['last'], price[j])
    bid, ask = np.asarray(quote['bid'][j], float), np.asarray(quote['ask'][j], float)
    valid = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
    if 'quote_valid' in quote:
        valid &= quote['quote_valid'][j]
    return dict(bid=bid, ask=ask, quote_valid=valid, seq=a.copy(), time_s=ready['time_s'].copy())


def prepare() -> None:
    """
    機能: 旧60入力を再利用し、追加6入力を同一抽出・因果監査で生成する。
    引数: なし。
    返り値: None。入力指紋を保存し正式売買はしない。
    """
    spec = specification()
    out = HERE / 'prepared'
    assert not (out / '入力準備の完了.json').exists()
    with owned_cache():
        rt = runtime()
        before = source_hashes()
        raw = {str(p.relative_to(ROOT)).replace('\\', '/'): digest(p)
               for session in SESSIONS_EXTRA for symbol in ('TOPIX', 'NK225')
               for folder, ext in (('book', '.jsonl'), ('candle_1min', '.csv'), ('candle_5min', '.csv'))
               for p in [ROOT / folder / symbol / (session + ext)]}
        save(out / '追加素材抽出前の固定.json', dict(仕様=spec, 原本SHA256=raw, 実装SHA256=before,
            金融再生=0, API=0, 旧JIT保存先変更=False, JIT=str(HERE / 'jit')))
        for session in SESSIONS_EXTRA:
            folder = out / session
            folder.mkdir(parents=True, exist_ok=True)
            assert not (folder / 'signals.pkl').exists()
            rt['extractor'].HERE = folder
            print(session + ' 元E01素材抽出', flush=True)
            inputs, features = rt['extractor'].extract(session)
            signals = rt['extractor'].signal_audit(inputs, features)
            with (folder / 'signals.pkl').open('wb') as stream:
                pickle.dump(signals, stream, protocol=5)
            q = {}
            for key, ready in inputs.items():
                path = folder / 'features' / f'約定系列_{key[1]}_{session}.npz'
                with np.load(path, allow_pickle=False) as tape:
                    q[key] = quotes(ready, dict(tape))
                assert len(signals['entry'][key]) == len(ready['last'])
            with (folder / 'quotes.pkl').open('wb') as stream:
                pickle.dump(q, stream, protocol=5)
            save(folder / '準備完了.json', dict(全合格=True, 対象=session, 金融再生=0,
                入力SHA256={name: digest(folder / name) for name in ('new_inputs.pkl', 'signals.pkl', 'quotes.pkl')},
                因果検査=read(folder / '信号監査.json')['全合格']))
            del inputs, features, signals, q
            gc.collect()
        # ----------------------------------------
        # 旧価格キャッシュは一回読取り、原連番・時計・CurrentPriceが一致する時だけ気配を使う。
        old_inputs, _, old_hashes = rt['prepare'].load_inputs(verify=True)
        old_path = ROOT / 'work/wave_v83/prepared/inputs.pkl'
        proof = read(ROOT / 'work/wave_v83/prepared/価格入力の照合.json')
        assert digest(old_path) == proof['出力SHA256']
        all_quotes = read(old_path)
        merged = {}
        for key, ready in old_inputs.items():
            merged[key] = quotes(ready, all_quotes[key])
        del all_quotes, old_inputs
        for session in SESSIONS_EXTRA:
            merged.update(read(out / session / 'quotes.pkl'))
        assert len(merged) == 66
        with (out / 'quotes.pkl').open('wb') as stream:
            pickle.dump(merged, stream, protocol=5)
        assert all(digest(ROOT / p) == h for p, h in raw.items())
        assert all(digest(ROOT / p) == h for p, h in before.items())
        save(out / '入力準備の完了.json', dict(全合格=True, 全33=spec['全33'], 入力数=66,
            使用入力SHA256=old_hashes, 旧気配SHA256=proof['出力SHA256'],
            全気配SHA256=digest(out / 'quotes.pkl'),
            追加=[read(out / session / '準備完了.json') for session in SESSIONS_EXTRA],
            原本SHA256=raw, 既存source不変=True, 金融再生=0, API=0,
            気配正常数=sum(int(q['quote_valid'].sum()) for q in merged.values()),
            気配不正数=sum(int((~q['quote_valid']).sum()) for q in merged.values())))
        print('元E01全33素材準備完了・金融0', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='E01同一素材と当行BBOのみを準備')
    parser.add_argument('--prepare', action='store_true')
    args = parser.parse_args()
    assert args.prepare, '--prepare が必要'
    prepare()
