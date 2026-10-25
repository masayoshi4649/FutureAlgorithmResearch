"""保存F1を、当場始値と引け直前Lastの方向・深夜を除く保有時間で独立監査する。"""

import csv
import hashlib
import json
import pickle
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo
import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRIOR = ROOT/'work/conditional142_20261024'
RAW = ROOT/'work/raw_diagnosis141_20261024/raw_features'
OLD = ROOT/'work/aggressive140_20261024'
DATA = ROOT.parent/'JP_OSE_Data/future'
JST = ZoneInfo('Asia/Tokyo')
sys.path.insert(0, str(PRIOR))
import verify_mechanics142 as checks


def digest(path):
    """
    機能: 大きな原資料を全件メモリへ展開せず内容指紋を確認する。
    引数: path(Path)は読取対象。
    返り値: strはSHA256。
    """
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def bounds(scene):
    """
    機能: 公式場の開始・終了と、保有率評価の終了を日本時間で定める。
    引数: scene(str)は日付とDay/Night。
    返り値: tuple[float,float,float]は開始、公式終了、03時除外の評価終了。
    """
    day = datetime.fromisoformat(scene[:10]).replace(tzinfo=JST)
    if scene.endswith('_Day'):
        return day.replace(hour=8, minute=45).timestamp(), day.replace(hour=15, minute=45).timestamp(), day.replace(hour=15, minute=45).timestamp()
    following = day + timedelta(days=1)
    return day.replace(hour=17).timestamp(), following.replace(hour=6).timestamp(), following.replace(hour=3).timestamp()


def text_time(value):
    """
    機能: 有効なepoch時計を日本時間へ表示変換する。
    引数: value(float)は保存価格時計。
    返り値: strはタイムゾーン付きISO時計。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def side_name(value):
    """
    機能: 符号だけで上昇・下落・同値を分類する。
    引数: value(float)は価格差。
    返り値: strは方向名。予測入力へ戻さず事後の評価分類だけに使用する。
    """
    return '上昇' if value > 0 else '下落' if value < 0 else '同値'


def excerpt(path, source, index):
    """
    機能: 原行のbyte位置と行SHAから、始終値の根拠原文を照合する。
    引数: path(Path)、source(NpzFile)、index(int)は原資料・保存索引・原行。
    返り値: dictは参照した原行の時計・値。生板全量をLLMへ読ませた意味ではない。
    """
    offset, length = int(source['byte_offset'][index]), int(source['byte_length'][index])
    with path.open('rb') as stream:
        stream.seek(offset)
        raw = stream.read(length)
    sha = hashlib.sha256(raw).hexdigest()
    assert sha == bytes(source['line_sha256'][index]).hex()
    record = json.loads(raw)
    return dict(seq0=index, byte_offset=offset, line_sha256=sha,
        fields={k: record.get(k) for k in ('CurrentPrice', 'CurrentPriceTime', 'CurrentPriceStatus',
            'TradingVolumeTime', 'OpeningPrice', 'OpeningPriceTime', 'PreviousClose', 'PreviousCloseTime', 'ClearingPrice')})


def direction(scene):
    """
    機能: 当場の最初と最後の有効Lastを原文・1分足と照合する。
    引数: scene(str)は評価場。
    返り値: dictは公式引け確定又は6分以内代理の分類と欠測・時計の根拠。
    """
    start, end, _ = bounds(scene)
    book_path = DATA/'NK225'/scene/'book.jsonl'
    candle_path = book_path.with_name('candle_1min.csv')
    with candle_path.open(encoding='utf-8-sig', newline='') as stream:
        candles = list(csv.DictReader(stream))
    assert len(candles) > 0
    clocks = np.array([datetime.fromisoformat(c['time']).timestamp() for c in candles])
    assert np.all(np.diff(clocks) > 0) and clocks[0] == start
    for candle, clock in zip(candles, clocks):
        op, hi, lo, cl = map(float, (candle['open'], candle['high'], candle['low'], candle['close']))
        assert start <= clock <= end and lo <= min(op, cl) <= max(op, cl) <= hi
        assert candle['closed'].lower() == 'true'
    with np.load(RAW/f'NK225_{scene}.npz') as source:
        sha = digest(book_path)
        assert sha == str(source['source_sha256'])
        t, p = source['time_s'], source['last']
        usable = np.flatnonzero(np.isfinite(t) & np.isfinite(p) & (p > 0) & (t >= start) & (t <= end))
        assert len(usable)
        first_time, last_time = float(t[usable].min()), float(t[usable].max())
        first = int(usable[np.flatnonzero(t[usable] == first_time)[0]])
        last = int(usable[np.flatnonzero(t[usable] == last_time)[-1]])
        beginning, ending = excerpt(book_path, source, first), excerpt(book_path, source, last)
        assert beginning['fields']['CurrentPriceStatus'] == ending['fields']['CurrentPriceStatus'] == 1
        assert float(beginning['fields']['CurrentPrice']) == p[first]
        assert float(ending['fields']['CurrentPrice']) == p[last]
        assert float(candles[0]['open']) == p[first], (scene, '原Lastと1分足始値の相違')
        assert float(candles[-1]['close']) == p[last], (scene, '原Lastと1分足最終値の相違')
        first_price, last_price = float(p[first]), float(p[last])
        exact = last_time == end
        permitted = exact or 0 <= end-last_time <= 360.
        op_time = ending['fields']['OpeningPriceTime']
        opening_field_valid = bool(op_time and start <= datetime.fromisoformat(op_time).timestamp() <= end)
        return dict(session=scene, official_start=text_time(start), official_end=text_time(end),
            first_price=first_price, first_price_time=text_time(first_time), start_lag_seconds=first_time-start,
            final_price=last_price, final_price_time=text_time(last_time), seconds_before_official_end=end-last_time,
            official_close_observed=exact, direction_qualified=permitted,
            basis='公式終端時刻の有効Last' if exact else '直前6分以内の最終観測Last' if permitted else '公式終端も許容代理も欠測',
            direction=side_name(last_price-first_price) if permitted else '未確定',
            change=last_price-first_price if permitted else None, raw_rows=int(len(t)),
            candle_first=candles[0], candle_last=candles[-1], candle_rows=len(candles),
            candle_sha256=digest(candle_path), book_sha256=sha, first_evidence=beginning, final_evidence=ending,
            opening_field_time_is_current_session=opening_field_valid,
            original_OpeningPrice_used=False, final_BBO_used=False, official_missing_is_not_zero=True)


def ledger(orders, ready, quotes, scene):
    """
    機能: 保存親の利益損失・売買方向と、03～06時を除く実保有率を独立会計する。
    引数: orders(ndarray)、ready/quotes(dict)、scene(str)は保存注文と原資料。
    返り値: dictは親会計と保有率。夜間の損益自体は03時で打ち切らない。
    """
    net = checks.audit_orders(orders, dict(ready=ready, quotes=quotes), 10)
    start, end, evaluation_end = bounds(scene)
    times = ready['time_s']
    parents, tickets, events = {}, {}, {}
    for o in orders:
        fill, source, parent, side, quantity = map(int, o[:5])
        new, uid, fee = int(o[7]), int(o[8]), int(o[9])
        price = float(o[5])
        p = parents.setdefault(parent, dict(parent=parent, side=side, gross=0., fees=0, first=text_time(times[fill]),
            last=text_time(times[fill]), quantity=0, fill_seq0=int(ready['seq'][fill]), role='追加' if 3_000_000 <= parent < 4_000_000 else '補完' if uid == 999 else '主担当'))
        p['fees'] += fee
        p['last'] = text_time(times[fill])
        if new:
            tickets[parent, uid] = [quantity, price, side]
            p['quantity'] += quantity
        else:
            held, entry, original_side = tickets[parent, uid]
            p['gross'] += original_side*(price-entry)*quantity*100.
            tickets[parent, uid][0] -= quantity
        at = float(times[fill])
        events[at] = events.get(at, 0) + (quantity if new else -quantity)
    for p in parents.values():
        p['net'] = p['gross'] - p['fees']
    held = 0
    previous = start
    occupied = full_occupied = 0.
    for at, delta in sorted(events.items()):
        if held:
            occupied += max(0., min(at, evaluation_end)-max(previous, start))
            full_occupied += max(0., min(at, end)-max(previous, start))
        held += delta
        assert held >= 0
        previous = at
    assert held == 0
    assert abs(sum(p['net'] for p in parents.values())-net) < 1e-7
    return dict(net=net, profit=sum(p['net'] for p in parents.values() if p['net'] > 0),
        loss=-sum(p['net'] for p in parents.values() if p['net'] < 0), parents=list(parents.values()),
        evaluation_minutes=(evaluation_end-start)/60., held_minutes_excluding_03_06=occupied/60.,
        holding_ratio_excluding_03_06=occupied/(evaluation_end-start),
        full_holding_ratio=full_occupied/(end-start), minutes_excluded_from_numerator=(full_occupied-occupied)/60.)


def summarize(rows):
    """
    機能: 選んだ評価区分の親損益・赤字頻度・保有率を集計する。
    引数: rows(list[dict])は事後方向区分に属する場。
    返り値: dictは費用後統計。0場又は損失0はnullを区別する。
    """
    profit, loss = sum(r['profit'] for r in rows), sum(r['loss'] for r in rows)
    parents = [p for r in rows for p in r['parents']]
    by_side = {}
    for side, label in ((1, '買い'), (-1, '売り')):
        chosen = [p for p in parents if p['side'] == side]
        gains = sum(p['net'] for p in chosen if p['net'] > 0)
        costs = -sum(p['net'] for p in chosen if p['net'] < 0)
        by_side[label] = dict(parents=len(chosen), profit=gains, loss=costs, net=gains-costs,
            pf=gains/costs if costs else None, quantity=sum(p['quantity'] for p in chosen))
    return dict(sessions=len(rows), profit=profit, loss=loss, net=profit-loss,
        pf=profit/loss if loss else None, negative_sessions=sum(r['net'] < 0 for r in rows),
        mean_holding_ratio=mean(r['holding_ratio_excluding_03_06'] for r in rows) if rows else None,
        time_weighted_holding_ratio=sum(r['held_minutes_excluding_03_06'] for r in rows)/sum(r['evaluation_minutes'] for r in rows) if rows else None,
        buy_sell=by_side, worst_sessions=[dict(session=r['session'], net=r['net'], direction=r['direction']) for r in sorted(rows, key=lambda x:x['net'])[:3]])


def main():
    """
    機能: 同じ50場の完整性、始終値の代理資格、方向別の損益と保有を検査する。
    引数: なし。
    返り値: None。入力・売買条件を変えず、根拠JSONと短いMarkdownを作成する。
    """
    report = checks.read(PRIOR/'report_data142.json')
    original = [r for r in report['rows'] if r['symbol'] == 'NK225' and r['method'] == 'F1']
    expected = {r['session'] for r in original}
    manifests = {x['session']: x for f in (OLD/'known_manifest140.json', OLD/'inputs/input_manifest.json') for x in checks.read(f)['packets']}
    directories = {s: {p.name for p in (DATA/s).iterdir() if p.is_dir()} for s in ('NK225', 'TOPIX')}
    assert len(expected) == 50 and set(manifests) == expected
    assert directories['NK225'] == directories['TOPIX'] == expected
    cache = {r['session']: r for r in checks.read(PRIOR/'結果142.json')['cache'] if r['symbol'] == 'NK225'}
    rows = []
    for prior in original:
        scene = prior['session']
        endpoint = direction(scene)
        ref = manifests[scene]
        path = ROOT/ref['path']
        assert digest(path) == ref['sha256']
        packet = pickle.loads(path.read_bytes())
        order_ref = cache[scene]
        path = ROOT/order_ref['path']
        assert digest(path) == order_ref['sha256']
        with np.load(path) as values:
            calculated = ledger(values[prior['component_method']], packet['inputs'][scene, 'NK225'], packet['quotes'][scene, 'NK225'], scene)
        for key in ('profit', 'loss', 'net'):
            assert calculated[key] == prior[key]
        assert abs(calculated['full_holding_ratio']-prior['holding_ratio']) < 1e-12
        rows.append(dict(**endpoint, **calculated, kind=prior['kind'], method='F1',
            previous142_change=prior['market_change'], previous142_direction=side_name(prior['market_change']),
            previous142_basis='セッション開始から売買清算判断時刻15:35/05:50までの正常中値差'))
        print(scene, endpoint['basis'], endpoint['direction'], flush=True)
    groups = {}
    for kind in ('全場', 'Day', 'Night'):
        chosen = [r for r in rows if kind == '全場' or r['kind'] == kind]
        for market in ('全方向', '上昇', '下落', '同値', '未確定'):
            subset = [r for r in chosen if market == '全方向' or r['direction'] == market]
            groups[f'{kind}_{market}'] = summarize(subset)
    result = dict(新金融再生=0,対象='NK225mini・片方向上限10枚・標準手数料後F1保存注文',
        手法構成='昼M1（B5＋G02追加）、夜J04（Z04＋C13追加）。変更なし。',
        同一50場=dict(NK225=50, TOPIX=50,保存F1=50, missing=[], extra=[], NK225原板内容指紋全一致=True),
        定義='当場最初の有効Lastと1分足Openを照合。公式終了時刻Lastがなければ、既存指定の直前6分以内の最終有効Lastを代理に採用。最終方向は事後評価専用で売買判断に渡さない。',
        保有率定義='1枚以上の保有区間を重複なく積分。Day08:45～15:45の420分、Night17:00～翌03:00の600分で各場を割った単純平均。損益は元の全セッションのまま。',
        公式引け確認数=sum(r['official_close_observed'] for r in rows),
        直前6分代理数=sum(r['direction_qualified'] and not r['official_close_observed'] for r in rows),
        未確定数=sum(not r['direction_qualified'] for r in rows),
        旧分類からの変更=[dict(session=r['session'], old=r['previous142_direction'], new=r['direction'],
            old_change=r['previous142_change'], new_change=r['change']) for r in rows if r['direction'] != r['previous142_direction']],
        原OpeningPriceが当場時計ではない場数=sum(not r['opening_field_time_is_current_session'] for r in rows),
        分類集計=groups, sessions=rows,
        限界='独立受信時計なし。保有秒数は保存価格時計上であり、原行間の欠測や取引停止の実時間を証明しない。公式引け価格は代理値と区別し、原板の最終BBO・前終値・清算値で穴埋めしない。')
    checks.save(HERE/'F1始終値方向と深夜除外保有率143.json', result)
    write_note(result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('sessions', '分類集計')}, ensure_ascii=False))
    print(json.dumps({k: v for k, v in groups.items() if k in ('全場_全方向', 'Day_上昇', 'Day_下落', 'Night_上昇', 'Night_下落')}, ensure_ascii=False))


def write_note(result):
    """
    機能: 方向・保有率の検査結果と重要な欠測を短い日本語で報告する。
    引数: result(dict)は原文照合済みの監査結果。
    返り値: None。元の損益資料と注文は変更しない。
    """
    lines = ['# F1の方向別成績と03時以降を除く保有率', '',
        f"対象は従来と同じ50場（昼25・夜25）。日経・TOPIXの保存フォルダとも一致。日経原板50本の内容指紋を再確認し、始値と最後の有効Lastは全場で1分足と一致した。公式引け確認は{result['公式引け確認数']}場、直前6分以内の最終Last代理が{result['直前6分代理数']}場、未確定は{result['未確定数']}場。", '',
        '方向は当場の最初の有効Lastとの差。前夜から残るOpeningPrice、最終BBO、清算値は使っていない。最終方向は事後の採点用で、売買条件へ渡していない。', '',
        '|対象|場数|利益|損失|収支|利益/損失|赤字場|平均保有率|', '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in ('全場_全方向', 'Day_全方向', 'Night_全方向', 'Day_上昇', 'Day_下落', 'Night_上昇', 'Night_下落'):
        g = result['分類集計'][name]
        lines.append(f"|{name}|{g['sessions']}|{g['profit']:,.0f}|{g['loss']:,.0f}|{g['net']:+,.0f}|{g['pf']:.3f}|{g['negative_sessions']}|{g['mean_holding_ratio']:.1%}|")
    lines += ['', '保有率の分母は昼420分、夜600分。夜は03:00～06:00の保有を分子・分母から除いた。損益は保存された全セッションのままで、03時以降の売買を削除した成績ではない。', '',
        '|売買方向|完結親数|利益|損失|収支|利益/損失|', '|---|---:|---:|---:|---:|---:|']
    for label, v in result['分類集計']['全場_全方向']['buy_sell'].items():
        lines.append(f"|{label}|{v['parents']}|{v['profit']:,.0f}|{v['loss']:,.0f}|{v['net']:+,.0f}|{v['pf']:.3f}|")
    lines += ['', f"00142の15:35／05:50までの中値分類から変わったのは{len(result['旧分類からの変更'])}場。", '']
    for r in result['旧分類からの変更']:
        lines.append(f"- {r['session']}：旧{r['old']}（{r['old_change']:+g}）→最終Last代理では{r['new']}（{r['new_change']:+g}）。")
    lines += ['', '赤字寄与の大きい3場と売買方向別の内訳はJSONに保持した。保有時間は価格時計基準であり、受信時計ではない。今回の分類変更・再集計を新たな収益性の検証結果とは数えない。']
    (HERE/'F1始終値方向と深夜除外保有率143.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
