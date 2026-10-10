"""既存三候補の前半16場だけを、入口時点の既知情報と決済後の損失構造に分ける。"""

from collections import defaultdict
import hashlib
import json
from pathlib import Path
import pickle
import socket

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v76'
IDS = ('B_F15_E0_M0_C0_T40_H30', 'B_FD15_E0_M1_C15_T40_H30', 'Q25_E10_M2_C30_T40_HS')
SYMBOLS = ('TOPIX', 'NK225')
LABELS = ('両OFI支持15秒', '短期価格一致15秒', '5分方向一致', '5分足並み', '自5分の伸び', '高安近接', '共同距離板支持')


def load(path: Path) -> object:
    """機能: 保存された仕様又は台帳だけを読み取る。

    引数: path(Path)。返り値: 保存内容(object)。原本・旧結果を変更しない。
    """
    return pickle.loads(path.read_bytes()) if path.suffix == '.pkl' else json.loads(path.read_text(encoding='utf8'))


def digest(path: Path) -> str:
    """機能: 読み取った保存入力を内容指紋で識別する。

    引数: path(Path)。返り値: SHA256(str)。
    """
    h = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(4 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def deny(*args: object, **kwargs: object) -> None:
    """機能: 前半保存診断からのネットワーク接続を禁止する。

    引数: args(tuple)、kwargs(dict)。返り値: なし(None)、例外を送出する。
    """
    raise RuntimeError('前半保存診断からの通信は禁止')


def past_price(r: dict, f: dict, index: int, stamp: float, window: float) -> float | None:
    """機能: 代理参照期限から指定秒前の価格を、厳密に過去の先頭観測で求める。

    引数: r/f(dict)、index(int)、stamp/window(float)。返り値: 中値又はなし(float|None)。
    欠測救済なし、鮮度30秒、区間の不正観測やresetをまたがない。
    """
    times = r['time_s']
    target = stamp - 5. - window
    end = int(np.searchsorted(times, target, side='left') - 1)
    if end < 0:
        return None
    first = int(np.searchsorted(times, times[end], side='left'))
    if first >= index or not 0 < target - times[first] <= 30.:
        return None
    good = f['valid'][first] and not f['reset'][first] and 0 < f['bid'][first] < f['ask'][first]
    good = good and f['ask'][first] - f['bid'][first] <= 2 * r['tick'] + 1e-8
    if not good or np.any(f['reset'][first + 1:index + 1] | ~f['valid'][first + 1:index + 1]):
        return None
    return float(f['mid'][first])


def past_labels(session: str, symbol: str, decision: int, side: int, ready: dict,
                book: dict, grids: dict, extrema: dict) -> dict:
    """機能: 発注判断までの二市場価格・OFI・表示板から事前指定した状態ラベルを作る。

    引数: session/symbol(str)、decision/side(int)、ready/book/grids/extrema(dict)。
    返り値: 入口ラベルと過去参照証跡(dict)。返済行、将来価格、損益は引数に取らない。
    """
    data = grids[session]
    grid = data['grid']
    stamp = float(ready[(session, symbol)]['time_s'][decision])
    g = int(np.searchsorted(grid, stamp, side='right') - 1)
    if g < 0:
        return dict(ラベル={name: '観測不能' for name in LABELS}, 格子=-1)
    own, peer = symbol, 'NK225' if symbol == 'TOPIX' else 'TOPIX'
    returns, flow, short, depths, source = {}, {}, {}, {}, {}
    for s in SYMBOLS:
        market = data['markets'][s]
        c, w = market['current'], market['windows'][15]
        i = int(c['index'][g])
        source[s] = i
        if not c['valid'][g] or i < 0:
            returns[s] = flow[s] = short[s] = depths[s] = None
            continue
        assert ready[(session, s)]['time_s'][i] < grid[g] - 5.
        if s == symbol:
            assert i < decision
        current = float(book[(session, s)]['mid'][i])
        old = past_price(ready[(session, s)], book[(session, s)], i, float(grid[g]), 300.)
        returns[s] = side * (current / old - 1.) * 10000. if old else None
        flow[s] = side * float(w['ofi_ratio'][g]) if w['valid'][g] and w['nonzero_ofi_count'][g] >= 3 else None
        short[s] = side * float(w['mid_change_bp'][g]) if w['source_valid'][g] else None
        depths[s] = side * float(c['depth_imbalance'][g])
    labels = {}
    if all(flow[s] is not None for s in SYMBOLS):
        labels['両OFI支持15秒'] = '両市場支持' if min(flow.values()) >= .10 else '反対OFIあり' if min(flow.values()) <= -.10 else '弱い又は混在'
    else:
        labels['両OFI支持15秒'] = '少数零OFI又は無効'
    if all(short[s] is not None for s in SYMBOLS):
        labels['短期価格一致15秒'] = '両市場順行' if min(short.values()) > 0 else '片方逆行又は停滞'
    else:
        labels['短期価格一致15秒'] = '観測不能'
    if all(returns[s] is not None for s in SYMBOLS):
        labels['5分方向一致'] = '両市場順行' if min(returns.values()) > 0 else '片方逆行又は停滞'
        if min(returns.values()) > 0:
            ratio = min(returns.values()) / max(returns.values())
            labels['5分足並み'] = '進行量比0.25未満' if ratio < .25 else '進行量比0.25以上'
        else:
            labels['5分足並み'] = '同方向でない'
    else:
        labels['5分方向一致'] = labels['5分足並み'] = '観測不能'
    labels['自5分の伸び'] = '観測不能' if returns[own] is None else '6bp超順行済み' if returns[own] > 6. else '6bp以下'
    labels['共同距離板支持'] = '観測不能' if any(depths[s] is None for s in SYMBOLS) else '両市場支持' if min(depths.values()) >= .10 else '反対板あり' if min(depths.values()) <= -.10 else '弱い又は混在'
    own_index = source[own]
    proximity = None
    if own_index >= 0 and data['markets'][own]['current']['valid'][g]:
        current = float(book[(session, own)]['mid'][own_index])
        high, low = extrema[(session, own)]
        proximity = (high[own_index] - current) / current * 10000. if side == 1 else (current - low[own_index]) / current * 10000.
    labels['高安近接'] = '観測不能' if proximity is None else 'セッション極値3bp以内' if proximity <= 3. else '極値から3bp超'
    return dict(ラベル=labels, 格子=g, 共通代理時計=float(grid[g]), 発注代理時計=stamp,
                自参照行=own_index, 相手参照行=source[peer], 方向調整5分変化bp=returns,
                方向調整15秒OFI=flow, 方向調整15秒価格bp=short,
                方向調整距離板偏り=depths, 極値から距離bp=proximity)


def future_description(t: np.ndarray, r: dict, f: dict, symbol: str) -> dict:
    """機能: 実際の保有区間内だけの最大順行・逆行・利益返上を説明する。

    引数: t(ndarray)、r/f(dict)、symbol(str)。返り値: 事後説明用指標(dict)。入口判定へ渡さない。
    """
    entry, exit_i, side = int(t[1]), int(t[2]), int(t[3])
    quote = f['bid'][entry:exit_i + 1] if side == 1 else f['ask'][entry:exit_i + 1]
    bid, ask = f['bid'][entry:exit_i + 1], f['ask'][entry:exit_i + 1]
    valid = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask >= bid)
    assert valid.any()
    move = side * (quote[valid] - float(t[5]))
    value = 1000. if symbol == 'TOPIX' else 10.
    qty, fees = float(t[4]), float(t[7] + t[8])
    best, worst = float(move.max()), float(move.min())
    peak_net = best * qty * value - fees
    return dict(最大順行bp=best / float(t[5]) * 10000., 最大逆行bp=worst / float(t[5]) * 10000.,
        区間最高評価収支=peak_net, 区間最低評価収支=worst * qty * value - fees,
        最高評価からの利益返上=max(0., peak_net - float(t[10])),
        費用後含み益を一度も作れず=peak_net <= 0.,
        費用後含み益後に赤字返済=bool(peak_net > 0. and t[10] < 0.),
        保有分=float(r['time_s'][exit_i] - r['time_s'][entry]) / 60.)


def money(rows: list[dict]) -> dict:
    """機能: 固定ラベルごとの全利益・全損失と平均を相殺前に示す。

    引数: rows(list[dict])。返り値: 会計と損失構造(dict)。
    """
    count = len(rows)
    p, loss = sum(max(0., r['収支']) for r in rows), sum(max(0., -r['収支']) for r in rows)
    loses = [r for r in rows if r['収支'] < 0]
    return dict(取引数=count, 利益=p, 損失=loss, 収支=p - loss,
        金額利益割合=p / (p + loss) if p + loss else None,
        平均一取引収支=(p - loss) / count if count else None,
        勝数=sum(r['収支'] > 0 for r in rows), 負数=len(loses),
        平均負け=loss / len(loses) if loses else None,
        含み益を一度も作れなかった負け=sum(r['事後']['費用後含み益を一度も作れず'] for r in loses),
        含み益後に赤字返済した負け=sum(r['事後']['費用後含み益後に赤字返済'] for r in loses),
        含み益後赤字返済の損失=sum(-r['収支'] for r in loses if r['事後']['費用後含み益後に赤字返済']),
        最大順行10bp以上後の赤字返済損失=sum(-r['収支'] for r in loses if r['事後']['最大順行bp'] >= 10.),
        最高評価からの利益返上=sum(r['事後']['最高評価からの利益返上'] for r in rows))


def main() -> None:
    """機能: 前16だけの既存三候補を診断し、新候補の再生を行わず証拠を保存する。

    引数: なし。返り値: なし(None)。後13と新しい追加場の損益は集計しない。
    """
    socket.socket.connect = deny
    socket.create_connection = deny
    fixed_path = OLD / '事前固定.json'
    fixed = load(fixed_path)
    sessions = fixed['前16']
    assert len(sessions) == 16
    spec_path = OLD / 'inputs/入力と即時板特徴の仕様.json'
    spec = load(spec_path)
    paths = [fixed_path, spec_path, Path(__file__), OLD / 'inputs/grids.pkl']
    ready, book = {}, {}
    for name, destination in (('ready', ready), ('book', book)):
        for value in spec['input_paths'][name]:
            path = ROOT / value
            all_values = load(path)
            destination.update({key: r for key, r in all_values.items() if key[0] in sessions})
            paths.append(path)
    grids = load(OLD / 'inputs/grids.pkl')[5]
    grids = {s: grids[s] for s in sessions}
    extrema = {}
    for key, f in book.items():
        good = f['valid'] & np.isfinite(f['mid']) & (f['mid'] > 0)
        extrema[key] = (np.maximum.accumulate(np.where(good, f['mid'], -np.inf)),
                        np.minimum.accumulate(np.where(good, f['mid'], np.inf)))
    outputs = {}
    for ident in IDS:
        result_path, ledger_path = OLD / 'results' / (ident + '.json'), OLD / 'ledgers' / (ident + '.pkl')
        result = load(result_path)
        assert digest(ledger_path) == result['ledger_SHA256']
        archive = {key: value for key, value in load(ledger_path).items() if key[0] in sessions}
        paths += [result_path, ledger_path]
        records = []
        for key, ledger in archive.items():
            entries = {int(o[2]): o for o in ledger['orders'] if o[7] == 1}
            exits = {int(o[2]): o for o in ledger['orders'] if o[7] == 0}
            for t in ledger['trades']:
                en, ex = entries[int(t[0])], exits[int(t[0])]
                past = past_labels(key[0], key[1], int(en[1]), int(t[3]), ready, book, grids, extrema)
                # ----------------------------------------
                # 判定ラベルが完成してから、保有区間の事後説明と実収支を結び付ける。
                records.append(dict(セッション=key[0], 銘柄=key[1], 取引番号=int(t[0]),
                    新規理由=int(en[6]), 返済理由=int(ex[6]), 入口=past,
                    事後=future_description(t, ready[key], book[key], key[1]), 収支=float(t[10])))
        symbols = {}
        for symbol in SYMBOLS:
            rows = [r for r in records if r['銘柄'] == symbol]
            summary = money(rows)
            old_summary = result['periods']['前16'][symbol]
            for label, field in (('利益', 'profit'), ('損失', 'loss'), ('収支', 'net'), ('取引数', 'trades')):
                assert abs(summary[label] - old_summary[field]) < 1e-5
            groups = {}
            for field in LABELS:
                grouped = defaultdict(list)
                for r in rows:
                    grouped[r['入口']['ラベル'][field]].append(r)
                groups[field] = {label: money(part) for label, part in sorted(grouped.items())}
                assert sum(part['取引数'] for part in groups[field].values()) == len(rows)
            symbols[symbol] = dict(全体=summary, 入口の既知状態別=groups,
                大きい損失の説明例=sorted((r for r in rows if r['収支'] < 0), key=lambda r:r['収支'])[:3])
        outputs[ident] = dict(固定設定=result['config'], 商品別=symbols, 全入口ラベルと事後分離明細=records)
    output = dict(対象期間='前16だけ', 前16=sessions, 既存候補=list(IDS), 新損益再生=False,
        後13採点=False, 追加1場採点=False, API取得数=0, 実注文数=0,
        境界='OFI/距離板0.10、15秒の同方向価格、5分進行量比0.25、5分の伸び6bp、既知場極値から3bp。結果で閾値を調整しない。',
        事後隔離='最大順行・最大逆行・利益返上は実保有区間の説明専用。入口ラベル関数の引数に返済・収支・将来価格を含めない。',
        時計限界='格子5秒・参照遅延5秒・鮮度30秒、最終約定の代理時計。共通受信時刻ではない。',
        比較限界='状態別金額は既存売買の分類。該当状態だけを取引した新アルゴリズムの再生結果ではない。',
        候補=outputs, 入力SHA256={str(p.relative_to(ROOT)):digest(p) for p in sorted(set(paths))})
    target = HERE / '既存3候補の前16損失構造.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps(dict(前16会計照合=True, 既存候補数=len(outputs), 新損益再生=False), ensure_ascii=False))


if __name__ == '__main__':
    main()
