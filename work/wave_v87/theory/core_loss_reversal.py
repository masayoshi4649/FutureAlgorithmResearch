"""元GUの負けを順行経路で分け、保険開始の機会と反例だけを診断する。"""

from pathlib import Path
import importlib.util
import json
import pickle
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True


def helper_module():
    """
    機能: 既存診断の指紋照合・親会計関数を読み取る。
    引数: なし。
    返り値: module。売買再生は呼び出さない。
    """
    spec = importlib.util.spec_from_file_location('wave87_original_core_risk', HERE / 'risk_structure.py')
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def account(rows):
    """
    機能: 既存の親組を金額で集計し、負け親損失と負け脚損失を区別する。
    引数: rows(list[dict]) は既存親の明細。
    返り値: dict の件数と料金後損益。保険の損益ではない。
    """
    net = [r['収支'] for r in rows]
    return dict(親組数=len(rows), 勝親数=sum(v > 0 for v in net), 負親数=sum(v < 0 for v in net),
                利益=sum(max(0., v) for v in net), 損失=sum(max(0., -v) for v in net),
                収支=sum(net), 料金=sum(r['手数料'] for r in rows),
                親内の全赤字決済脚損失=sum(r['赤字脚損失'] for r in rows),
                親内の全黒字決済脚利益=sum(r['黒字脚利益'] for r in rows))


def bands(row):
    """
    機能: 元価格の最大順行を既存の粗い固定幅で分類する。
    引数: row(dict)。
    返り値: str の診断分類。未来の入口判定には使用しない。
    """
    mfe = row['最大順行ATR']
    if mfe <= 1e-12:
        return '一度も建値より順行しない'
    if mfe < .25:
        return '一度は順行したが025ATR未満'
    if mfe < .5:
        return '025以上050ATR未満'
    if mfe < .75:
        return '050以上075ATR未満'
    if mfe < 1.5:
        return '075以上150ATR未満'
    return '150ATR以上'


def first_trigger(indices, prices, entry, atr, direction, tick, arm, distance):
    """
    機能: 現在までの順行極値から反対へ進む最初の観測だけを求める。
    引数: indices/prices(ndarray)、entry/atr/tick/arm/distance(float)、direction(int)。
    返り値: dict 又はNone。注文・約定・保険損益は生成しない。
    """
    peak = entry
    peak_index = -1
    armed = arm == 0.
    for k, (i, price) in enumerate(zip(indices, prices)):
        raw_line = peak - direction * max(distance * atr, tick)
        line = (np.floor(raw_line / tick + 1e-9) if direction > 0 else
                np.ceil(raw_line / tick - 1e-9)) * tick
        if armed and direction * (price - line) <= 1e-8:
            after = direction * (prices[k+1:] - price) / atr
            return dict(成立行=int(i), 成立価格=float(price), 指定可能な逆指値線=float(line),
                        直前までの極値=float(peak), 極値行=int(peak_index),
                        成立時順行ATR=float(direction * (price - entry) / atr),
                        成立前最大順行ATR=float(direction * (peak-entry) / atr),
                        次有効観測行=int(indices[k+1]) if k+1 < len(indices) else None,
                        成立後の追加逆行ATR=max(0., float(-after.min())) if len(after) else 0.,
                        成立後の再順行ATR=max(0., float(after.max())) if len(after) else 0.)
        if direction * (price - peak) > 0:
            peak, peak_index = float(price), int(i)
        if direction * (peak-entry) / atr >= arm:
            armed = True
    return None


def summarize(rows):
    """
    機能: 元損失の内訳と保険開始条件が既存勝ちにも当たる頻度をまとめる。
    引数: rows(list[dict]) は一商品・一期間。
    返り値: dict の事後診断。対象親損失額を救済額とは解釈しない。
    """
    losses = [r for r in rows if r['収支'] < 0]
    total_loss = sum(-r['収支'] for r in losses)
    categories = {}
    for name in ('一度も建値より順行しない', '一度は順行したが025ATR未満', '025以上050ATR未満',
                 '050以上075ATR未満', '075以上150ATR未満', '150ATR以上'):
        group = [r for r in losses if r['順行分類'] == name]
        categories[name] = dict(**account(group), 総負親損失の割合=sum(-r['収支'] for r in group)/total_loss if total_loss else 0.)
    assert abs(sum(v['損失'] for v in categories.values())-total_loss) < 1e-7
    triggers = {}
    for condition in ('順行不要_逆行025', '順行025_逆行025', '順行050_逆行025',
                      '順行不要_逆行050', '順行025_逆行050', '順行050_逆行050'):
        touched = [r for r in rows if r['逆行開始診断'][condition] is not None]
        ahead = [r for r in touched if r['逆行開始診断'][condition]['成立行'] < r['返済行']]
        next_ahead = [r for r in ahead if r['逆行開始診断'][condition]['次有効観測行'] is not None
                      and r['逆行開始診断'][condition]['次有効観測行'] < r['返済行']]
        continuing = [r for r in next_ahead if r['逆行開始診断'][condition]['成立後の追加逆行ATR'] >= .25]
        triggers[condition] = dict(元全親に対する成立=account(touched),
            全返済前に成立=account(ahead), 次観測も全返済前=account(next_ahead),
            うち元負親=account([r for r in next_ahead if r['収支'] < 0]),
            うち元勝親=account([r for r in next_ahead if r['収支'] > 0]),
            成立後さらに025ATR逆行した元親=account(continuing),
            うち元負親でさらに025ATR逆行=account([r for r in continuing if r['収支'] < 0]),
            元全返済行で初めて成立=account([r for r in touched if r['逆行開始診断'][condition]['成立行'] == r['返済行']]),
            限定='成立対象の元親収支であり保険収支・節約額ではない。反対玉の実約定・停止・追尾・数量変化は未再生。')
    return dict(元全親=account(rows), 元負親=account(losses), 負親の最大順行別=categories,
                最初の非ゼロ移動別={name: account([r for r in losses if r['最初の非ゼロ方向'] == name])
                                     for name in ('逆行', '順行', '変化なし')},
                最初は逆行したが後で025ATR以上順行した負親=account([r for r in losses if r['最初の非ゼロ方向'] == '逆行' and r['最大順行ATR'] >= .25]),
                保険開始の機会と反例=triggers)


def main():
    """
    機能: 元GUの既存278親と原価格を照合して損失分類と事前案を保存する。
    引数: なし。
    返り値: None。新PL探索・原データ更新・report編集は行わない。
    """
    helper = helper_module()
    old_rows_path = HERE / '既存親組の価格経路明細.json'
    old_rows = helper.read(old_rows_path)['E01_G_U']
    proof_path = ROOT / 'work/wave_v85/prepared/入力準備の完了.json'
    proof = helper.read(proof_path)
    inputs, hashes = {}, {str(old_rows_path.relative_to(ROOT)): helper.sha(old_rows_path)}
    for pair in proof['入力対応']:
        path = ROOT / pair['inputs']
        digest = helper.sha(path)
        assert digest == proof['使用入力SHA256'][pair['inputs']]
        hashes[pair['inputs']] = digest
        inputs.update(pickle.loads(path.read_bytes()))
    ledger_path = ROOT / 'work/wave_v86/observed/ledgers/E01_G_U.pkl'
    result_path = ledger_path.parent.parent / 'results/E01_G_U.json'
    original = helper.read(result_path)
    hashes[str(ledger_path.relative_to(ROOT))] = helper.sha(ledger_path)
    assert hashes[str(ledger_path.relative_to(ROOT))] == original['ledger_SHA256']
    ledgers = pickle.loads(ledger_path.read_bytes())
    rows = []
    for source in old_rows:
        row = dict(source)
        key = (row['セッション'], row['銘柄'])
        ready, ledger = inputs[key], ledgers[key]
        start, end, direction, atr, entry = row['新規行'], row['返済行'], row['方向'], row['固定ATR'], row['建値']
        idx = np.arange(start+1, end+1)
        idx = idx[np.isfinite(ready['last'][idx]) & (ready['last'][idx] > 0)]
        prices = ready['last'][idx]
        progress = direction * (prices-entry) / atr
        assert np.isclose(max(0.,float(progress.max())), row['最大順行ATR'])
        parts = [t for t in ledger['net_trades'] if t['組'] == row['組']]
        assert abs(sum(t['収支'] for t in parts)-row['収支']) < 1e-7
        row['赤字脚損失'] = sum(max(0., -float(t['収支'])) for t in parts)
        row['黒字脚利益'] = sum(max(0., float(t['収支'])) for t in parts)
        row['順行分類'] = bands(row)
        nonzero = np.flatnonzero(np.abs(prices-entry) > 1e-8)
        row['最初の非ゼロ方向'] = ('順行' if progress[nonzero[0]] > 0 else '逆行') if len(nonzero) else '変化なし'
        row['新規原本行'] = int(ready['seq'][start])+1
        row['返済原本行'] = int(ready['seq'][end])+1
        row['逆行開始診断'] = {}
        for arm, label in ((0., '不要'), (.25, '025'), (.5, '050')):
            for distance, width in ((.25, '025'), (.5, '050')):
                trigger = first_trigger(idx, prices, entry, atr, direction, float(ready['tick']), arm, distance)
                if trigger is not None:
                    trigger['成立原本行'] = int(ready['seq'][trigger['成立行']])+1
                row['逆行開始診断'][f'順行{label}_逆行{width}'] = trigger
        rows.append(row)
    assert len(rows) == 278
    periods = {}
    for period in ('全30', '前16', '後14'):
        periods[period] = {}
        for symbol in ('TOPIX', 'NK225'):
            selected = [r for r in rows if r['銘柄'] == symbol and r['セッション'] in proof[period]]
            period_value = summarize(selected)
            assert abs(period_value['元全親']['収支']-original['periods'][period][symbol]['net']) < 1e-7
            periods[period][symbol] = period_value
    payload = dict(対象='元E01_G_U・全30既知場・観測現在値・TOPIXミニ初回5枚/日経マイクロ初回10枚',
        新PL探索=False, 旧278親の会計一致=True,
        定義={
            '損失額': '同一初回注文の全決済脚・全料金を合計した赤字親組の損失。部分利確を別勝ちとして水増ししない。赤字脚合計は参考別列。',
            '即逆行': '曖昧なので二つに分ける。一度も建値より有利に進まなかった経路と、最初の非ゼロ移動だけが不利だった経路は同じでない。',
            '順行後反転': '元の実建値から有利側へ進んだことがある赤字親。0.25/0.5/0.75/1.5ATRで粗く分け、1呼値の微小な順行を大きな成功とは呼ばない。',
            '保険機会': '新規時固定ATR、現在までの順行極値、反対0.25/0.5ATRの逆指値線を呼値丸め。現観測で更新した極値と準備は次観測から判定。実発注・約定・追尾は生成しない。',
            '将来用途禁止': '最大順行、最終赤字、成立後の経路は全て事後分類。実際の保険許可はその時点で既知の極値と進行幅だけにする。',
            '二値にしない理由': '一度も順行なしを除いた全損失を保険で救える損失とはしない。微小順行、保険開始後の反発、主玉との終了競合と料金が残る。',
        }, 期間別=periods, 参照SHA256=hashes)
    (HERE / '元GU負け初回の順行前後別損失と保険機会.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (HERE / '元GU逆行開始の全278親診断.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps({s: dict(元全親=periods['全30'][s]['元全親'],
                             負親の最大順行別=periods['全30'][s]['負親の最大順行別'],
                             最初の非ゼロ移動別=periods['全30'][s]['最初の非ゼロ移動別'])
                      for s in ('TOPIX', 'NK225')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
