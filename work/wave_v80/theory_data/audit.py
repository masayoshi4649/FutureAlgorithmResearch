"""秒単位検証の時計・板・費用の可観測性を監査し、売買損益は計算しない。"""

from collections import Counter
from datetime import datetime
import hashlib
import json
from pathlib import Path
import pickle
import re
import socket

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SYMBOLS = ('TOPIX', 'NK225')
CLOCK = re.compile(r'(?:Time|time|Date|date|Stamp|stamp|Receiv|receiv|Receipt|receipt|Seq|seq)')


def load(name: str) -> object:
    """機能: 保存済み入力を読み取る。

    引数: name(str)。返り値: 読込値(object)。売買台帳は開かない。
    """
    path = ROOT/name
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def clean(value: object) -> object:
    """機能: 配列型と未定義値をJSONへ変換する。

    引数: value(object)。返り値: JSON対応値(object)。
    """
    if isinstance(value, dict): return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (tuple, list, np.ndarray)): return [clean(v) for v in value]
    if isinstance(value, np.generic): return clean(value.item())
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


def save(name: str, value: object) -> None:
    """機能: 今回担当領域だけへ監査結果を保存する。

    引数: name(str)、value(object)。返り値: なし(None)。
    """
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE/name).write_text(json.dumps(clean(value), ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def digest(path: Path) -> str:
    """機能: 監査に使用した保存素材の指紋を一定メモリーで計算する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    result = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4*1024*1024): result.update(chunk)
    return result.hexdigest()


def quantile(values: np.ndarray) -> dict:
    """機能: 有限値だけの分位点を報告する。

    引数: values(ndarray)。返り値: 件数と分位点(dict)。
    """
    values = np.asarray(values); values = values[np.isfinite(values)]
    return dict(件数=len(values), **{f'p{p}': float(np.percentile(values, p)) if len(values) else None for p in (0, 25, 50, 75, 90, 95, 99, 100)})


def account(key: tuple, r: dict, f: dict) -> tuple:
    """機能: 口座別に代理時計の重複、間隔、板変化、原本欠落を数える。

    引数: key(tuple)、r/f(dict)。返り値: 監査集計と合算用配列(tuple)。
    同時計は同時受信を意味せず、時計間隔は約定時計間隔であって板受信間隔ではない。
    """
    t = r['time_s']; dt = np.diff(t); same = dt == 0
    first = np.flatnonzero(np.r_[True, dt != 0]); multiplicity = np.diff(np.r_[first, len(t)])
    valid = f['valid'] & ~f['reset']
    good_pair = valid[1:] & valid[:-1] & (np.diff(r['seq']) == 1)
    price_change = (np.diff(f['bid']) != 0) | (np.diff(f['ask']) != 0)
    quantity_change = (np.diff(f['bid_qty']) != 0) | (np.diff(f['ask_qty']) != 0)
    nonzero = valid & np.isfinite(f['best_ofi']) & (f['best_ofi'] != 0)
    spread = (f['ask']-f['bid'])/r['tick']
    row = dict(セッション=key[0], 銘柄=key[1], 準備行数=len(t), 独立時計数=len(first), 同時計隣接数=int(same.sum()),
               同時計隣接割合=float(same.mean()), 時計逆行数=int((dt < 0).sum()),
               同時計内最良価格変化数=int((same & good_pair & price_change).sum()),
               同時計内最良数量変化数=int((same & good_pair & quantity_change).sum()),
               時計正差分位秒=quantile(dt[dt > 0]), 同時計行数分位=quantile(multiplicity),
               時計差5秒超数=int((dt > 5).sum()), 時計差15秒超数=int((dt > 15).sum()), 時計差30秒超数=int((dt > 30).sum()),
               準備系列の原本非連続箇所=int((np.diff(r['seq']) != 1).sum()),
               板十段無効行数=int((~f['valid']).sum()), 板状態リセット数=int(f['reset'].sum()),
               最良OFI非零行数=int(nonzero.sum()), OFI非零かつ累積出来高不変数=int((nonzero & (f['volume_delta'] == 0)).sum()),
               スプレッドラージ呼値=quantile(spread[valid]), **{'1呼値スプレッド割合':float((spread[valid] == 1).mean()),
               '2呼値以下スプレッド割合':float((spread[valid] <= 2).mean())},
               代理時計範囲秒=float(t[-1]-t[0]), 準備行数毎代理時計秒=float(len(t)/(t[-1]-t[0])))
    return row, dict(dt=dt[dt > 0], multiplicity=multiplicity, spread=spread[valid])


def movement(r: dict, f: dict) -> list[dict]:
    """機能: 前半だけで5秒後に残る観測幅を無条件に測り、方向選択をしない。

    引数: r/f(dict)。返り値: 時計点別の小幅観測(list[dict])。
    判断予定は60秒おき。過去参照は厳密過去先頭、将来点は予定以後の先頭。前後5秒超の鮮度不足や区間の無効を除く。
    """
    t = r['time_s']; grid = np.arange(r['start']+300, r['limit']-120, 60.)
    good = f['valid'] & ~f['reset'] & (f['ask'] > f['bid']) & (f['ask']-f['bid'] <= 2*r['tick']+1e-9)
    broken = np.r_[0, np.cumsum(~good)]
    output = []
    for g in grid:
        p = int(np.searchsorted(t, g, side='left'))-1
        if p < 0: continue
        p = int(np.searchsorted(t, t[p], side='left'))
        if not good[p] or not 0 < g-t[p] <= 5: continue
        arrival = int(np.searchsorted(t, g+5, side='left'))
        if arrival >= len(t) or not good[arrival] or t[arrival]-(g+5) > 5: continue
        if broken[arrival+1] != broken[p]: continue
        for h in (5, 15, 30, 60):
            end = int(np.searchsorted(t, g+5+h, side='left'))
            if end >= len(t) or not good[end] or t[end]-(g+5+h) > 5: continue
            if broken[end+1] != broken[arrival]: continue
            delta = (f['mid'][end]-f['mid'][arrival])/r['tick']
            wait = (f['mid'][arrival]-f['mid'][p])/r['tick']
            output.append(dict(予定保有秒=h, 発注待ち中値変化呼値=float(wait), 到着後中値変化呼値=float(delta),
                               実発注待ち秒=float(t[arrival]-g), 実観測間隔秒=float(t[end]-t[arrival])))
    return output


def raw_samples(ready: dict) -> list[dict]:
    """機能: 各原本から既存準備系列の五位置を抽出し、時計項目と板価格を再照合する。

    引数: ready(dict)。返り値: 六十原本の五点標本(list[dict])。
    全量はハッシュするがJSONの時計キー確認は標本だけ。全行のキー不在を証明したとはしない。
    """
    output = []
    for key, r in sorted(ready.items()):
        indexes = np.unique(np.linspace(0, len(r['seq'])-1, 5).astype(int))
        requested = {int(r['seq'][i]): int(i) for i in indexes}
        path = ROOT/'book'/key[1]/(key[0]+'.jsonl'); hasher = hashlib.sha256(); samples = []
        with path.open('rb') as stream:
            for seq, line in enumerate(stream):
                hasher.update(line)
                if seq not in requested: continue
                raw = json.loads(line); i = requested[seq]
                assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == r['time_s'][i]
                assert raw['CurrentPrice'] == r['last'][i]
                samples.append(dict(原本seq=seq, 準備行=i, 時刻=raw['CurrentPriceTime'],
                    時計に関わるキー={k: raw[k] for k in raw if CLOCK.search(k)}, 商品名=raw.get('SymbolName'),
                    bid=raw['Buy1']['Price'], ask=raw['Sell1']['Price'], 買数量=raw['Buy1']['Qty'], 売数量=raw['Sell1']['Qty']))
        output.append(dict(セッション=key[0], 銘柄=key[1], 原本行数=seq+1, bytes=path.stat().st_size,
                           SHA256=hasher.hexdigest(), 標本=samples, 時刻現在値照合=True))
    return output


def main() -> None:
    """機能: 全三十場の可観測性と前半十六場の無条件変化幅を保存する。

    引数: なし。返り値: なし(None)。戦略損益・未来側を使った条件選定・API取得をしない。
    """
    def unavailable(*args, **kwargs):
        """機能: 通信禁止を強制する。

        引数: 任意(tuple/dict)。返り値: なし(None)、常に例外。
        """
        raise RuntimeError('保存資料の監査中は通信しない')
    socket.socket.connect = unavailable; socket.create_connection = unavailable
    meta = load('work/wave_v77/inputs/metadata.json'); ready = {}; books = {}; paths = []
    for kind, out in [('ready', ready), ('features', books)]:
        for name in [*meta['input_paths'][kind], meta['extra_paths'][kind]]:
            out.update(load(name)); paths.append(name)
    front = set(meta['sessions'][:16]); rows = []; pool = {s: [] for s in SYMBOLS}; moves = {s: [] for s in SYMBOLS}
    for key in sorted(ready):
        row, arrays = account(key, ready[key], books[key]); rows.append(row); pool[key[1]].append(arrays)
        if key[0] in front: moves[key[1]].extend(movement(ready[key], books[key]))
    totals = {}
    for symbol in SYMBOLS:
        own = [r for r in rows if r['銘柄'] == symbol]
        fields = ['準備行数', '独立時計数', '同時計隣接数', '同時計内最良価格変化数', '同時計内最良数量変化数',
                  '時計差5秒超数', '時計差15秒超数', '時計差30秒超数', '板十段無効行数', '板状態リセット数',
                  '最良OFI非零行数', 'OFI非零かつ累積出来高不変数']
        totals[symbol] = {f: sum(r[f] for r in own) for f in fields}
        totals[symbol]['同時計隣接割合'] = totals[symbol]['同時計隣接数']/(totals[symbol]['準備行数']-len(own))
        totals[symbol]['時計正差分位秒'] = quantile(np.concatenate([v['dt'] for v in pool[symbol]]))
        totals[symbol]['同時計行数分位'] = quantile(np.concatenate([v['multiplicity'] for v in pool[symbol]]))
        totals[symbol]['スプレッドラージ呼値'] = quantile(np.concatenate([v['spread'] for v in pool[symbol]]))
    observations = {}
    for symbol in SYMBOLS:
        observations[symbol] = {}
        for horizon in (5, 15, 30, 60):
            selected = [m for m in moves[symbol] if m['予定保有秒'] == horizon]
            absolute = np.array([abs(m['到着後中値変化呼値']) for m in selected])
            observations[symbol][horizon] = dict(有効点数=len(selected), 到着後絶対中値変化呼値=quantile(absolute),
                **{'1ラージ呼値以上割合':float((absolute >= 1).mean()) if len(absolute) else None,
                '2ラージ呼値以上割合':float((absolute >= 2).mean()) if len(absolute) else None,
                '3ラージ呼値以上割合':float((absolute >= 3).mean()) if len(absolute) else None},
                発注待ち絶対中値変化呼値=quantile(np.array([abs(m['発注待ち中値変化呼値']) for m in selected])),
                実発注待ち秒=quantile(np.array([m['実発注待ち秒'] for m in selected])),
                実観測間隔秒=quantile(np.array([m['実観測間隔秒'] for m in selected])))
    save('時計と微小値幅の監査.json', dict(対象='既存30場60口座。変化幅は前半16場だけ。', 全体=totals, 口座別=rows,
         前半16場の無条件小幅観測=observations,
         小幅の定義='60秒おきの予定時点。参照は厳密な過去先頭、5秒後の最初の有効時刻を到着代理とし、その5/15/30/60秒後の中値差絶対値。両端の時刻ずれ5秒以下、無効跨ぎ除外。方向を当てて得た利益ではない。',
         解釈限界=['CurrentPriceTimeは最終約定時計。0秒重複や秒差を板の実受信間隔と呼べない。',
                    '同時計内にも気配価格・数量の更新がある。将来行を同時刻として入口に混ぜない。',
                    '正の時計差が大きいのは約定停止かデータ欠落か区別できない。',
                    '指値の待ち行列・取消ID・個々の約定イベント・実商品気配がない。',
                    '到着後絶対変化の方向は事前には不明。反復エントリー可能回数や正答率や損益ではない。'],
         手数料と呼値=dict(TOPIX=dict(実商品='TOPIXmini', 数量=10, ラージ呼値=.5, 実商品呼値=.25, 価格倍率=1000,
                                     往復料円=836, 実商品1呼値粗利円=2500, 同料金後円=1664, 料金相当pt=.0836),
                           NK225=dict(実商品='NK225micro', 数量=20, ラージ呼値=10, 実商品呼値=5, 価格倍率=10,
                                     往復料円=440, 実商品1呼値粗利円=1000, 同料金後円=560, 料金相当pt=2.2)),
         原板ディレクトリ=sorted(p.name for p in (ROOT/'book').iterdir() if p.is_dir()),
         実商品原板有無={s: (ROOT/'book'/s).exists() for s in ('TOPIXmini', 'NK225mini', 'NK225micro')},
         入力SHA256={name: digest(ROOT/name) for name in paths}, 解析器SHA256=digest(Path(__file__)),
         戦略損益再生=0, 損益結果閲覧=0, API取得=0))
    print(json.dumps(clean(dict(全体=totals, 前半16場の無条件小幅観測=observations)), ensure_ascii=False), flush=True)
    samples = raw_samples(ready)
    expected = dict(meta['旧58原本指紋'])
    expected.update({x['session']+'|'+x['symbol']: x['raw_SHA256'] for x in meta['extra_raw_audit']})
    assert all(x['SHA256'] == expected[x['セッション']+'|'+x['銘柄']] for x in samples)
    clock_keys = sorted({k for x in samples for s in x['標本'] for k in s['時計に関わるキー']})
    save('原板時計の標本監査.json', dict(口座数=len(samples), 標本数=sum(len(x['標本']) for x in samples), 原板=samples,
         既往入力の全60原板ハッシュ一致=True, 全標本の時計キー集合=clock_keys,
         確認範囲='全原本はbytes/hashを確認し、各準備系列の0/25/50/75/100%の5点で時刻・現在値を再照合。時計キーは標本検査であり全行のキー不存在証明ではない。', API取得=0, 戦略損益再生=0))


if __name__ == '__main__':
    main()
