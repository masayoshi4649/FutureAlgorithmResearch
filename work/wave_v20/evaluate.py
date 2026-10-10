"""追加された９月28日日中を、既存の固定条件だけで再生する。"""

from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import sys
from zoneinfo import ZoneInfo

import numpy as np

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
SESSION = '2026-09-28_Day'
SYMBOLS = ['TOPIX', 'NK225']
MULT = {'TOPIX': 1000., 'NK225': 10.}
CAP = {'TOPIX': 10, 'NK225': 20}
JST = ZoneInfo('Asia/Tokyo')


def module(path: Path, name: str):
    """機能: 既存ソースを書き換えず別名で読み込む。

    引数: path (Path)、name (str)。返り値: 読み込んだモジュール (module)。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


def digest(path: Path) -> str:
    """機能: 原本を読み取りSHA256を計算する。

    引数: path (Path)。返り値: ハッシュ (str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1048576):
            result.update(chunk)
    return result.hexdigest()


def save(name: str, value: object) -> None:
    """機能: 数値型を整えて日本語JSONを保存する。

    引数: name (str)、value (object)。返り値: なし (None)。
    """
    def clean(obj):
        """機能: NumPy値・非有限値をJSON用に整える。

        引数: obj (object)。返り値: JSON互換値 (object)。
        """
        if isinstance(obj, dict): return {str(k): clean(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, np.ndarray)): return [clean(v) for v in obj]
        if isinstance(obj, np.generic): obj = obj.item()
        if isinstance(obj, float) and not np.isfinite(obj): return None
        return obj
    (OUT / name).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2), encoding='utf-8')


def main() -> None:
    """機能: 固定記録、原本入力、両銘柄の売買結果を作成する。

    引数: なし。返り値: なし (None)。API・実注文・条件探索は実行しない。
    """
    source = ROOT / 'work/wave_v19/主候補の条件.json'
    fixed = json.loads(source.read_text(encoding='utf-8'))
    config = fixed['一枚でのエンジン設定']
    assert fixed['候補ID'] == 'V0800' and config['timeout_min'] == 360
    paths = [ROOT / kind / symbol / f'{SESSION}.{extension}'
             for kind, extension in [('book', 'jsonl'), ('candle_1min', 'csv'), ('candle_5min', 'csv')]
             for symbol in SYMBOLS]
    paths += [source, ROOT/'work/wave_v19/engine.py', ROOT/'work/wave_v19/signal_variants.py']
    hashes = {str(p): digest(p) for p in paths}
    save('実行前の固定記録.json', dict(対象=SESSION, 記録時刻=datetime.now(JST).isoformat(),
         主候補='V0800', 比較='元の180分版V0000', 設定変更なし=True, パラメータ探索なし=True,
         設定=config, 元候補資料SHA256=hashes[str(source)], 原本とコードSHA256=hashes,
         現在API取得回数=0, 費用=0, 指定価格約定=True, 枚数='固定１枚とTOPIX10枚/NK20枚を別々に再生'))
    # ----------------------------------------
    # 既存と同じ原本抽出・ATR・入力生成器を、今回の保存先へ接続する。
    reference = module(ROOT/'work/wave_v16/reference.py', 'day28_reference')
    reference.previous.OUT = OUT
    extractor = module(ROOT/'work/wave_v8/raw_features.py', 'day28_raw_features')
    features, audits = {}, []
    for symbol in SYMBOLS:
        path = ROOT/'book'/symbol/f'{SESSION}.jsonl'
        quotes = []
        frame, audit = extractor.extract_features(path, symbol, SESSION, quotes=quotes)
        extractor.write_features(frame, audit, OUT/'features', quotes=quotes)
        book, raw = reference.previous.data.scan_book(path, collect_prices=True)
        tape_path = OUT/'features'/f'約定系列_{symbol}_{SESSION}.npz'
        tape = dict(np.load(tape_path, allow_pickle=False))
        indices = tape['seq'].astype(int)
        tape['last'] = raw['last'][indices]
        tape['volume'] = raw['volume'][indices]
        tape['current_price'] = tape['last'].copy()
        np.savez_compressed(tape_path, **tape)
        assert audit['原本SHA256'] == book['SHA256'] == hashes[str(path)]
        features[symbol] = frame
        consistency = reference.previous.data.candle_consistency(SESSION, symbol, raw)
        audits.append(dict(銘柄=symbol, 生板=book, 抽出=audit, 足整合=consistency,
                           約定系列SHA256=digest(tape_path), 約定系列行数=len(indices)))
        print(f'{symbol}: 原本{book["行数"]}行、評価入力{len(indices)}行', flush=True)
    inputs = reference.previous.build_inputs([SESSION], roots={SESSION: (ROOT, OUT/'features')})
    save('データ確認.json', dict(対象=SESSION, API取得数=0, 原本=audits,
         入力範囲=[dict(銘柄=s, 最初=datetime.fromtimestamp(v['time_s'][0], JST).isoformat(),
                   最後=datetime.fromtimestamp(v['time_s'][-1], JST).isoformat(), 返済条件時刻=datetime.fromtimestamp(v['limit'], JST).isoformat())
                   for (_, s), v in inputs.items()]))
    with (OUT/'入力.pkl').open('wb') as stream:
        pickle.dump(inputs, stream, pickle.HIGHEST_PROTOCOL)
    # ----------------------------------------
    # 元のM3と今回のS00を独立に作り、一致した固定方向だけを使用する。
    signals = module(ROOT/'work/wave_v17/signals.py', 'day28_original_signals')
    states = {key: signals.build_states(ready, inputs[(SESSION, 'NK225' if key[1]=='TOPIX' else 'TOPIX')], features=features[key[1]])
              for key, ready in inputs.items()}
    variants = module(ROOT/'work/wave_v19/signal_variants.py', 'day28_signal_variants')
    directions = variants.build_one(fixed['信号条件'], inputs, states)
    engine = module(ROOT/'work/wave_v19/engine.py', 'day28_engine')
    sys.path.insert(0, str(ROOT/'work/wave_v17'))
    metrics = module(ROOT/'work/wave_v17/research.py', 'day28_metrics')
    metrics.MULT = MULT
    rows, blocks, trades = [], {}, []
    for identifier, holding in [('V0800', 360.), ('V0000', 180.)]:
        for symbol in SYMBOLS:
            ready = inputs[(SESSION, symbol)]
            for quantity in [1, CAP[symbol]]:
                cfg = dict(config, id=identifier, timeout_min=holding, initial_qty=quantity, audit_cap=quantity)
                result = engine.run(ready, directions[(SESSION, symbol)], cfg, detail=True)
                row = metrics.summarize(result, cfg, symbol, SESSION)
                row['quantity'] = quantity
                rows.append(row)
                blocks[(identifier, symbol, quantity)] = dict(config=cfg, **result)
                if quantity == 1:
                    for tr in result['trades']:
                        trades.append(dict(method=identifier, symbol=symbol, campaign=int(tr[0]),
                            side='買い' if tr[2]>0 else '売り', quantity=int(tr[3]),
                            entry_price=tr[4], exit_price=tr[5],
                            entry_time=datetime.fromtimestamp(ready['time_s'][int(tr[6])], JST).isoformat(),
                            exit_time=datetime.fromtimestamp(ready['time_s'][int(tr[7])], JST).isoformat(),
                            entry_seq=int(ready['seq'][int(tr[6])]), exit_seq=int(ready['seq'][int(tr[7])]),
                            reason=engine.REASONS[int(tr[9])], reason_id=int(tr[9]),
                            pnl_points=tr[10], pnl_yen=tr[10]*MULT[symbol], atr=result['cycles'][int(tr[0]),5]))
                assert result['stats'][9] == 0 and result['stats'][2] <= quantity and result['stats'][3] <= quantity
    save('結果.json', rows)
    save('全取引.json', trades)
    with (OUT/'再生台帳.pkl').open('wb') as stream:
        pickle.dump(dict(inputs=inputs, states=states, directions=directions, blocks=blocks), stream, pickle.HIGHEST_PROTOCOL)
    assert all(digest(Path(path)) == value for path, value in hashes.items())
    save('実行完了.json', dict(成功=True, 設定再選択=False, 主候補='V0800', 結果数=len(rows),
         原本不変=True, API取得回数=0, 場末残枚数=0, 将来情報を使わない旧M3とS00が一致=True))
    print(json.dumps([dict(手法=r['method_id'], 銘柄=r['symbol'], 枚数=r['quantity'], 利益=r['gross_profit_yen'],
                          損失=r['gross_loss_yen'], 収支=r['net_yen'], 回数=r['cycles']) for r in rows], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
