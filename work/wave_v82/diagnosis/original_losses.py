"""元188条件の前16だけで、負けの安定性と価格・売買費用の内訳を診断する。"""
from datetime import datetime, timezone, timedelta
from pathlib import Path
import hashlib
import json
import pickle
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / 'work/wave_v81'
SYMBOLS = ('TOPIX', 'NK225')
REGIMES = ('上昇', '下落', '横ばい')
THRESHOLD = .001
JST = timezone(timedelta(hours=9))


def read(path):
    """
    機能: JSON又は保存配列を読み取る。
    引数: path (Path)。
    返り値: dict の保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8')) if path.suffix == '.json' else pickle.loads(path.read_bytes())


# ----------------------------------------
def source_inputs(front):
    """
    機能: 既存保存配列から前16の始終観測だけを診断用に接続する。
    引数: front (list[str]) の対象場。
    返り値: tuple[dict, dict, list[Path]] の価格・板・参照ファイル。
    """
    meta = ROOT / 'work/wave_v77/inputs/metadata.json'
    paths = read(meta)['input_paths']
    ready, books, files = {}, {}, [meta]
    for kind, output in (('ready', ready), ('features', books)):
        extra = 'extra_inputs.pkl' if kind == 'ready' else 'extra_features.pkl'
        for path in [ROOT / name for name in paths[kind]] + [ROOT / 'work/wave_v77/inputs' / extra]:
            contents = read(path)
            output.update({key: value for key, value in contents.items() if key[0] in front})
            files.append(path)
    assert len(ready) == len(books) == 32
    return ready, books, files


# ----------------------------------------
def classify(front, ready, books):
    """
    機能: 当場最初と最後の有効中値から、固定±0.1%で事後分類する。
    引数: front (list[str])、ready/books (dict)。
    返り値: dict の場・商品ごとの観測端点と分類。
    """
    out = {}
    for session in front:
        row = {}
        for symbol in SYMBOLS:
            key = (session, symbol)
            r, b = ready[key], books[key]
            bid, ask = np.asarray(b['bid'], dtype=float), np.asarray(b['ask'], dtype=float)
            valid = np.isfinite(bid) & np.isfinite(ask) & (bid > 0) & (ask > bid)
            indices = np.flatnonzero(valid)
            first, last = int(indices[0]), int(indices[-1])
            start, end = float((bid[first] + ask[first]) / 2), float((bid[last] + ask[last]) / 2)
            change = end / start - 1
            group = '上昇' if change >= THRESHOLD else '下落' if change <= -THRESHOLD else '横ばい'
            row[symbol] = dict(分類=group, 始中値=start, 終中値=end, 始終変化率=change,
                始観測JST=datetime.fromtimestamp(float(r['time_s'][first]), JST).isoformat(),
                終観測JST=datetime.fromtimestamp(float(r['time_s'][last]), JST).isoformat(),
                始準備行=first, 終準備行=last, 始原本seq=int(r['seq'][first]), 終原本seq=int(r['seq'][last]))
        row['二市場の分類'] = row['TOPIX']['分類'] + '／' + row['NK225']['分類']
        out[session] = row
    return out


# ----------------------------------------
def aggregate(rows):
    """
    機能: 指定場群の会計を中値損益と約定気配差・手数料に分解する。
    引数: rows (list[dict]) の元手法の場別結果。
    返り値: dict の実会計・中値経路・費用・活動場数。
    """
    sums = {key: sum(row[key] for row in rows) for key in ('profit', 'loss', 'net', 'fees', 'spread_drag', 'trades')}
    mids = [row['net'] + row['fees'] + row['spread_drag'] for row in rows]
    cost = sums['fees'] + sums['spread_drag']
    total_mid = sum(mids)
    assert abs(sums['net'] - (total_mid - cost)) < .01
    n = len(rows)
    active = sum(row['trades'] > 0 for row in rows)
    loss_fraction = sums['loss'] / (sums['profit'] + sums['loss']) if sums['profit'] + sums['loss'] else None
    return dict(場数=n, 稼働場数=active, 赤字場数=sum(row['net'] < 0 for row in rows),
        黒字場数=sum(row['net'] > 0 for row in rows), 無取引場数=sum(row['trades'] == 0 for row in rows),
        稼働差引ゼロ場数=sum(row['trades'] > 0 and row['net'] == 0 for row in rows),
        決済組数=sums['trades'], 利益円=sums['profit'], 損失円=sums['loss'], 収支円=sums['net'],
        中値経路損益円=total_mid, 中値赤字場数=sum(mid < 0 for mid in mids),
        中値黒字場数=sum(mid > 0 for mid in mids), 中値ゼロ場数=sum(mid == 0 for mid in mids),
        気配差負担円=sums['spread_drag'], 手数料円=sums['fees'], 費用C円=cost,
        中値損失が費用Cを上回る場数=sum(-mid > row['fees'] + row['spread_drag'] for mid, row in zip(mids, rows)),
        元の赤字場率=sum(row['net'] < 0 for row in rows) / n if n else None,
        金額損失割合=loss_fraction, 中値赤字場率=sum(mid < 0 for mid in mids) / n if n else None,
        中値損失対費用C=(-total_mid / cost if cost > 0 else None),
        一組平均収支円=sums['net'] / sums['trades'] if sums['trades'] else None,
        場別収支中央値円=float(np.median([row['net'] for row in rows])) if n else None,
        最良場収支円=max((row['net'] for row in rows), default=None),
        最悪場収支円=min((row['net'] for row in rows), default=None))


# ----------------------------------------
def rank(record, direction=False):
    """
    機能: 円額を合算せず、両商品で安定して負けた元手法の順位を付ける。
    引数: record (dict)、direction (bool) は中値側の別順位か。
    返り値: tuple の大きい順評価キー。
    """
    a = [record['前16'][symbol] for symbol in SYMBOLS]
    sufficient = all(x['決済組数'] >= 20 and x['稼働場数'] >= 8 for x in a)
    if direction:
        rates = [x['中値赤字場率'] for x in a]
        ratios = [x['中値損失対費用C'] if x['中値損失対費用C'] is not None else -float('inf') for x in a]
        return sufficient, min(rates), min(ratios), sum(rates) / 2, record['ID']
    rates = [x['元の赤字場率'] for x in a]
    shares = [x['金額損失割合'] if x['金額損失割合'] is not None else -1 for x in a]
    return sufficient, min(rates), min(shares), sum(rates) / 2, sum(shares) / 2, record['ID']


# ----------------------------------------
def main():
    """
    機能: 前半の元188条件だけを診断し、反転時の費用関係と相場分類を保存する。
    引数: なし。
    返り値: None。新規反転損益を作らず、過去成果も変更しない。
    """
    fixed = OLD / '初回事前固定.json'
    front = read(fixed)['前16']
    assert len(front) == 16
    ready, books, paths = source_inputs(front)
    regimes = classify(front, ready, books)
    del ready, books
    outputs = []
    for stage, count in (('first', 86), ('improved', 102)):
        sources = sorted((OLD / stage / 'results').glob('*.json'))
        assert len(sources) == count
        for path in sources:
            result = read(path)
            assert {row['session'] for row in result['rows']} == set(front)
            assert result['config']['latency'] == 5
            metrics, grouped = {}, {}
            for symbol in SYMBOLS:
                rows = [row for row in result['rows'] if row['symbol'] == symbol]
                metrics[symbol] = aggregate(rows)
                assert metrics[symbol]['収支円'] == result['periods']['前16'][symbol]['net']
                grouped[symbol] = {group: aggregate([row for row in rows if regimes[row['session']][symbol]['分類'] == group]) for group in REGIMES}
            joint = {name: {symbol: aggregate([row for row in result['rows'] if row['symbol'] == symbol and regimes[row['session']]['二市場の分類'] == name]) for symbol in SYMBOLS}
                     for name in sorted({value['二市場の分類'] for value in regimes.values()})}
            outputs.append(dict(ID=result['config']['id'], 段階=stage, 設定=result['config'], 前16=metrics,
                自市場の上昇下落横ばい別=grouped, 二市場の始終分類別=joint,
                両商品活動条件=all(metrics[symbol]['決済組数'] >= 20 and metrics[symbol]['稼働場数'] >= 8 for symbol in SYMBOLS)))
            paths.append(path)
    by_money = sorted(outputs, key=rank, reverse=True)
    by_direction = sorted(outputs, key=lambda record: rank(record, True), reverse=True)
    joint_daily = sum(all(record['前16'][symbol]['赤字場数'] == 16 for symbol in SYMBOLS) for record in outputs)
    exceed = [record['ID'] for record in outputs if all(record['前16'][symbol]['中値損失対費用C'] is not None and record['前16'][symbol]['中値損失対費用C'] > 1 for symbol in SYMBOLS)]
    compact = lambda record: {key: record[key] for key in ('ID', '段階', '前16', '両商品活動条件')}
    output = dict(
        対象='wave_v81の初回86・追加102の前16だけ。反転再生、後14、全30の新損益は未参照。',
        順位案=dict(金額負け='両商品20組・8稼働場を優先。両商品の小さい方の赤字場率、同じく金額損失割合、平均赤字場率、平均損失割合の順。円金額を合算しない。',
                    中値の負け='同じ活動条件を優先し、中値赤字場率の両商品最小値、中値損失/Cの両商品最小値、平均中値赤字場率の順。金額負け順位とは別の説明用順位。',
                    注意='16場を分母にする。無取引・差引ゼロを負け又は勝ちと数えない。順位の同点ではIDで決め、後半情報は使わない。'),
        反転の式=dict(定義='M＝同じ新規・返済時刻の中値経路の方向損益。C＝両側の気配差負担＋手数料。元R＝M−C。',
                    関係='同時刻で方向だけ反転すれば、逆R＝−M−C＝−元R−2C。',
                    帰結='元が赤字でも、その中値方向損失がCを上回らなければ、逆も黒字にならない。売買費用が作った損失は反転しても利益に変わらない。',
                    M0='同時刻・同枚数・同じ有効気配を新規と返済に使う成行M0の会計恒等式。元の経路と本当に同じ時刻になることは別途確認が必要。',
                    M1='不利価格制限M1では成立・不成立と再参加が変わるため、上記は元経路固定の参考。反転手法は入口と出口を再実行しなければ評価できない。',
                    中値の注意='中値で売買できるとは仮定しない。判断後の価格変化や遅延は実際の約定時刻までのMと気配差に含む。判断→約定の差をCに再加算しない。'),
        事後相場分類=dict(閾値=THRESHOLD, 規則='当場の最初/最後の保存された有効売買気配中値で（終/始−1）を算出。+0.1%以上＝上昇、−0.1%以下＝下落、その間＝横ばい。',
                       観測の限界='取引所の正式始値・引値ではない。保存区間が欠ければ欠けた区間は補完しない。横ばいは始終差の定義であり、途中に大きな上下がなかった意味ではない。',
                       用途='終値を使った事後の損失説明だけ。取引方向、入口、出口、手法切替、パラメータ選定には使わない。',
                       場別=regimes,
                       商品別場数={symbol: {group: sum(value[symbol]['分類'] == group for value in regimes.values()) for group in REGIMES} for symbol in SYMBOLS}),
        全体事実=dict(条件数=len(outputs), 両商品全16場赤字条件数=joint_daily, 両商品中値損失が費用を上回る条件数=len(exceed), 該当ID=exceed),
        金額負け安定の上位10=[compact(record) for record in by_money[:10]],
        中値方向負けの上位10=[compact(record) for record in by_direction[:10]],
        全188条件の元損益と分類=outputs,
        出典SHA256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in paths + [fixed]})
    target = HERE / '前16だけの負け安定と費用分解.json'
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全体=output['全体事実'], 相場別場数=output['事後相場分類']['商品別場数'],
        金額負け上位=[dict(ID=record['ID'], 前16=record['前16']) for record in by_money[:3]],
        中値負け上位=[dict(ID=record['ID'], 前16=record['前16']) for record in by_direction[:3]]), ensure_ascii=False))


if __name__ == '__main__':
    main()
