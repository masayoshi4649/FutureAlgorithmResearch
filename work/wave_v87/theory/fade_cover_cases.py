"""固定反対追加候補の全親・指定赤字場・商品別悪化上位三場を読むだけで診断する。"""

from pathlib import Path
import hashlib
import json
import pickle
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
JST = ZoneInfo('Asia/Tokyo')
sys.dont_write_bytecode = True
METHOD = 'C_H05_S25'


def read(path):
    """
    機能: 保存JSONを読む。
    引数: path(Path)。
    返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def stamp(ready, index):
    """
    機能: 保存行に対応する価格時計を日本時間で表記する。
    引数: ready(dict)、index(int)。
    返り値: str。真の受信時計ではない。
    """
    return datetime.fromtimestamp(float(ready['time_s'][index]), JST).isoformat()


def order_rows(orders, ready):
    """
    機能: 全新規・返済を時刻・原本行付きにする。
    引数: orders(ndarray)、ready(dict)。
    返り値: list[dict]。
    """
    result = []
    for order in orders:
        i, source = int(order[0]), int(order[1])
        assert float(order[5]) == ready['last'][i]
        assert 0 <= source < i
        result.append(dict(保存行=i, 原本行=int(ready['seq'][i])+1,
                           根拠行=source, 根拠原本行=int(ready['seq'][source])+1,
                           時計=stamp(ready, i), 売買=int(order[3]), 枚数=int(order[4]),
                           価格=float(order[5]), 理由=int(order[6]), 新規=bool(order[7])))
    return result


def class_name(core, sat, reason, present):
    """
    機能: 元玉と保険の確定損益から排他的な事後分類を作る。
    引数: core/sat(float)、reason(int)、present(bool)。
    返り値: str。実取引の許可条件ではない。
    """
    if not present:
        return '保険なしで主玉負け' if core < 0 else '保険なしで主玉勝ち又はゼロ'
    if sat < 0 and core < 0:
        return '保険停止後に主玉も負け' if reason == 81 else '保険と主玉がともに負け'
    if sat < 0:
        return '主玉勝ちの利益を保険停止が削る' if reason == 81 else '主玉勝ちの利益を保険が削る'
    if core < 0:
        return '保険利益で主玉負けを補い合算黒字' if core+sat > 0 else '保険利益では主玉負けを補い切れない'
    return '主玉と保険がともに利益又はゼロ'


def extract(key, ledger, ready):
    """
    機能: 元玉の全決済脚と保険全脚を価格経路へ対応させる。
    引数: key(tuple)、ledger/ready(dict)。
    返り値: list[dict]。価格の最大幅は事後診断だけに使う。
    """
    core = ledger['core_ledger']
    value, fee = (1000., 41.8) if key[1] == 'TOPIX' else (10., 11.)
    result = []
    for cycle in core['cycles']:
        cid, start, end = map(int, cycle[:3])
        direction, atr = int(cycle[8]), float(cycle[5])
        co = core['orders'][core['orders'][:, 2] == cid]
        so = ledger['satellite_orders'][ledger['satellite_orders'][:, 2] == cid]
        st = ledger['satellite_trades'][ledger['satellite_trades'][:, 0] == cid]
        assert len(st) <= 1 and len(so) == 2*len(st)
        parts = [t for t in core['net_trades'] if t['組'] == cid]
        core_net = sum(float(t['収支']) for t in parts)
        sat_gross = float(st[:, 10].sum())*value
        sat_fees = float(np.floor(so[:, 4]*fee+1e-8).sum())
        sat_net = sat_gross-sat_fees
        merged = sum(float(t['収支']) for t in ledger['net_trades'] if t['組'] == cid)
        assert abs(merged-core_net-sat_net) < 1e-6
        entry = float(co[0, 5])
        idx = np.arange(start+1, end+1)
        idx = idx[np.isfinite(ready['last'][idx]) & (ready['last'][idx] > 0)]
        progress = direction*(ready['last'][idx]-entry)/atr
        mfe, mae = max(0.,float(progress.max())), max(0.,float(-progress.min()))
        zero = np.flatnonzero(np.abs(progress) > 1e-8)
        initial = '順行' if len(zero) and progress[zero[0]] > 0 else '逆行' if len(zero) else '変化なし'
        reason = int(st[0, 9]) if len(st) else 0
        row = dict(セッション=key[0], 銘柄=key[1], 親=cid, 主玉収支=core_net, 保険粗損益=sat_gross,
            保険料金=sat_fees, 保険収支=sat_net, 合算収支=core_net+sat_net,
            分類=class_name(core_net, sat_net, reason, bool(len(st))),
            主玉新規行=start, 主玉全返済行=end, 主玉方向=direction, 固定ATR=atr,
            主玉建値=entry, 主玉最大順行ATR=mfe, 主玉最大逆行ATR=mae,
            主玉の最初の非ゼロ移動=initial, 主玉最終理由=int(cycle[9]),
            主玉全注文=order_rows(co, ready), 主玉全決済脚=parts,
            保険全注文=order_rows(so, ready), 保険最終理由=reason,
            照合追加行=[int(idx[int(np.argmax(progress))]), int(idx[int(np.argmin(progress))])])
        if len(st):
            trade = st[0]
            si, se = int(trade[6]), int(trade[7])
            before = ready['last'][start:si]
            peak = float(np.max(direction*(before-entry))) if len(before) else 0.
            at = float(direction*(ready['last'][si]-entry))
            path = ready['last'][si+1:se+1]
            side = int(trade[2])
            sat_progress = side*(path-float(trade[4]))/atr
            after = ready['last'][se+1:end+1] if se < end else np.empty(0)
            adverse = -direction*(after-float(trade[5]))/atr if len(after) else np.empty(0)
            held = int(co[0, 4])
            over = False
            for order in co[1:]:
                if int(order[0]) <= si:
                    held -= int(order[4])
                    over |= held < int(trade[3])
                elif int(order[0]) < se:
                    held -= int(order[4])
                    over |= held < int(trade[3])
            row['保険開始経路'] = dict(開始時の主玉順行ATR=at/atr,
                開始時は主玉方向の過去極値以上=at >= peak-1e-8,
                直前主玉極値からの反転ATR=max(0.,(peak-at)/atr),
                保険最大順行ATR=max(0.,float(sat_progress.max())) if len(sat_progress) else 0.,
                保険最大逆行ATR=max(0.,float(-sat_progress.min())) if len(sat_progress) else 0.,
                保険終了後にさらに主玉方向へ逆行ATR=max(0.,float(adverse.max())) if len(adverse) else 0.,
                保険終了は主玉全返済より前=se < end,
                保険保有中に主玉部分返済で純反対化=over,
                保険保有時計差秒=float(ready['time_s'][se]-ready['time_s'][si]),
                保険停止後から主玉終了まで時計差秒=float(ready['time_s'][end]-ready['time_s'][se]))
            events = ledger['satellite_events']
            local = events[(events[:, 1] == cid) & np.isin(events[:, 2], [2, 3, 4, 6])]
            row['保険停止追尾の全線更新'] = [dict(保存行=int(e[0]), 原本行=int(ready['seq'][int(e[0])])+1,
                種別=int(e[2]), 根拠行=int(e[3]), 価格=float(e[6]), 理由=int(e[9]), 追尾始動=bool(e[11])) for e in local]
            for offset, label in ((np.argmax(sat_progress), '保険最高行'), (np.argmin(sat_progress), '保険最悪行')) if len(sat_progress) else []:
                row[label] = si+1+int(offset)
                row['照合追加行'].append(row[label])
        else:
            line = entry+direction*.5*atr
            line = (np.ceil(line/ready['tick']-1e-9) if direction > 0 else np.floor(line/ready['tick']+1e-9))*ready['tick']
            row['保険なし理由診断'] = dict(開始指定線=float(line),
                旧主玉保有中に開始線まで順行せず=bool(np.max(direction*(ready['last'][idx]-line)) < -1e-8),
                最大順行分類='順行なし' if mfe == 0 else '025ATR未満' if mfe < .25 else '025以上050ATR未満' if mfe < .5 else '050ATR以上')
        result.append(row)
    return result


def aggregate(rows):
    """
    機能: 排他的原因分類ごとの主玉・保険・合算収支をまとめる。
    引数: rows(list[dict])。
    返り値: dict。
    """
    return dict(親数=len(rows), 主玉負け数=sum(r['主玉収支'] < 0 for r in rows),
        主玉収支=sum(r['主玉収支'] for r in rows), 保険収支=sum(r['保険収支'] for r in rows),
        保険料金=sum(r['保険料金'] for r in rows), 合算収支=sum(r['合算収支'] for r in rows),
        保険回数=sum(bool(r['保険全注文']) for r in rows),
        保険損失=sum(max(0.,-r['保険収支']) for r in rows), 保険利益=sum(max(0.,r['保険収支']) for r in rows),
        保険停止数=sum(r['保険最終理由'] == 81 for r in rows),
        原因別={label: dict(親数=sum(r['分類'] == label for r in rows),
                            主玉収支=sum(r['主玉収支'] for r in rows if r['分類'] == label),
                            保険収支=sum(r['保険収支'] for r in rows if r['分類'] == label),
                            合算収支=sum(r['合算収支'] for r in rows if r['分類'] == label))
                 for label in sorted({r['分類'] for r in rows})})


def verify_raw(key, rows, ready):
    """
    機能: 対象場の全主玉・保険注文、根拠行、重要極値を原板へ照合する。
    引数: key(tuple)、rows(list[dict])、ready(dict)。
    返り値: dict。価格経路の計算自体は保存全観測を使用している。
    """
    indices = set()
    for row in rows:
        indices.update(row['照合追加行'])
        for name in ('主玉全注文', '保険全注文'):
            for order in row[name]:
                indices.update([order['保存行'], order['根拠行']])
        for event in row.get('保険停止追尾の全線更新', []):
            indices.add(event['保存行'])
    lookup = {int(ready['seq'][i])+1: i for i in indices}
    path = ROOT / 'book' / key[1] / (key[0]+'.jsonl')
    records = []
    with path.open(encoding='utf-8-sig') as stream:
        for number, text in enumerate(stream, 1):
            if number not in lookup:
                continue
            raw = json.loads(text)
            raw = raw.get('data', raw)
            i = lookup[number]
            assert float(raw['CurrentPrice']) == ready['last'][i]
            assert datetime.fromisoformat(raw['CurrentPriceTime']).timestamp() == ready['time_s'][i]
            records.append(dict(原本行=number, 保存行=i, 価格=raw['CurrentPrice'], 時計=raw['CurrentPriceTime']))
            if len(records) == len(lookup):
                break
    assert len(records) == len(lookup)
    return dict(原本=str(path.relative_to(ROOT)), SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),
                原本直接照合件数=len(records), 注文根拠極値と線更新=records)


def main():
    """
    機能: 候補の全親分類と、指定場・各商品悪化上位三場の全足を保存する。
    引数: なし。
    返り値: None。新PL探索・閾値変更・report編集はしない。
    """
    root = ROOT / 'work/wave_v87/round7/observed'
    path = root / 'ledgers' / (METHOD+'.pkl')
    result = read(root / 'results' / (METHOD+'.json'))
    assert hashlib.sha256(path.read_bytes()).hexdigest() == result['ledger_SHA256']
    ledgers = pickle.loads(path.read_bytes())
    proof = read(ROOT / 'work/wave_v85/prepared/入力準備の完了.json')
    inputs = {}
    for pair in proof['入力対応']:
        raw = (ROOT / pair['inputs']).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == proof['使用入力SHA256'][pair['inputs']]
        inputs.update(pickle.loads(raw))
    selected = {('2026-09-24_Night', s) for s in ('TOPIX', 'NK225')}
    rankings = {}
    for symbol in ('TOPIX', 'NK225'):
        worst = sorted([r for r in result['rows'] if r['symbol'] == symbol], key=lambda r: (r['satellite_net'], r['session']))[:3]
        rankings[symbol] = [dict(セッション=r['session'], 主玉収支=r['core_net'], 保険差額=r['satellite_net'], 合算収支=r['net']) for r in worst]
        selected.update((r['session'], symbol) for r in worst)
    all_rows, cases = [], []
    for key, ledger in sorted(ledgers.items()):
        rows = extract(key, ledger, inputs[key])
        saved = next(r for r in result['rows'] if (r['session'], r['symbol']) == key)
        group = aggregate(rows)
        assert abs(group['保険収支']-saved['satellite_net']) < 1e-6
        assert abs(group['合算収支']-saved['net']) < 1e-6
        assert abs(group['主玉収支']-saved['core_net']) < 1e-6
        all_rows.extend(rows)
        if key in selected:
            cases.append(dict(セッション=key[0], 銘柄=key[1], 会計=group, 全親=rows,
                               原本照合=verify_raw(key, rows, inputs[key])))
    assert len(all_rows) == 278
    periods = {period: {symbol: aggregate([r for r in all_rows if r['銘柄'] == symbol and r['セッション'] in proof[period]])
                       for symbol in ('TOPIX', 'NK225')} for period in ('全30', '前16', '後14')}
    diagnostic = dict(候補=METHOD, モデル='観測CurrentPrice', 新PL試行=False, 閾値変更=False,
        対象選択='元GUとの差額を同商品内で昇順にした上位3場ずつ＋指定9月24日ナイト両商品。円額の大小で商品間順位を混ぜない。',
        既知性='保存済み全30場の事後診断。元親勝敗は分類用で取引許可に使わない。',
        商品別悪化上位3=rankings, 期間別=periods, 具体場=cases,
        根拠台帳SHA256=result['ledger_SHA256'], 全278親会計一致=True,
        原本照合合計=sum(c['原本照合']['原本直接照合件数'] for c in cases),
        限界='全価格経路を旧入力から読み、対象場の全注文・根拠・極値・保険線更新を原板へ直接照合。CurrentPriceTimeは代理時計で真の経過秒を保証しない。')
    (HERE / '反対追加候補の指定赤字場と悪化上位三場の原因.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    (HERE / '反対追加候補の全278親原因明細.json').write_text(json.dumps(all_rows, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    print(json.dumps(dict(悪化順位=rankings, 全体=periods['全30'],
                         指定場=[{k:v for k,v in c.items() if k in ('セッション','銘柄','会計')} for c in cases],
                         原本照合合計=diagnostic['原本照合合計']), ensure_ascii=False))


if __name__ == '__main__':
    main()
