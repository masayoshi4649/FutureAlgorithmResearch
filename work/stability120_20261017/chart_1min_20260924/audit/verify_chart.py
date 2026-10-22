"""一分足と全約定の埋込表示を保存資料だけで独立に検査する。"""

from collections import Counter, defaultdict
import csv
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
from io import StringIO
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
WORK = HERE.parents[1]
ROOT = WORK.parents[1]
JST = timezone(timedelta(hours=9))


def sha(raw: bytes) -> str:
    """
    機能: 同bytes保全と埋込表示の内容指紋を確認する。
    引数: raw(bytes)はCSV・HTML・小証跡の内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(raw).hexdigest()


class Embedded(HTMLParser):
    """JSONを持つ一つのscript要素だけを取り出す。"""

    def __init__(self) -> None:
        """
        機能: 埋込資料の受取状態を初期化する。
        引数: なし。
        返り値: None。
        """
        super().__init__()
        self.capture = False
        self.count = 0
        self.value = ''

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """
        機能: 対象scriptの属性を確認する。
        引数: tag(str)は要素名、attrs(list)は属性一覧。
        返り値: None。
        """
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('id') == 'chart-data':
            assert attrs.get('type') == 'application/json'
            self.capture = True
            self.count += 1

    def handle_data(self, data: str) -> None:
        """
        機能: 対象script内のJSON文字列を受け取る。
        引数: data(str)はHTML上の内容。
        返り値: None。
        """
        if self.capture:
            self.value += data

    def handle_endtag(self, tag: str) -> None:
        """
        機能: scriptの受取を終了する。
        引数: tag(str)は終了要素名。
        返り値: None。
        """
        if tag == 'script':
            self.capture = False


def inspect_inventory(saved: list, displayed: list, first: float, cap: int) -> dict:
    """
    機能: 玉の保有原行区間から全約定数と各原行後の枚数を独立再集計する。
    引数: saved(list)は全完結玉、displayed(list)は埋込枚数線、first(float)は足始端、cap(int)は片方向上限。
    返り値: dictは枚数上限と終端。原行内同clockの描画順を新しい市場順序と解釈しない。
    """
    events = defaultdict(list)
    for lot in saved:
        events[lot['entry_row']].append((lot['entry_epoch'], lot['side'], 1))
        events[lot['exit_row']].append((lot['exit_epoch'], lot['side'], -1))
    assert displayed[0] == [first, 0, 0]
    assert len(displayed) == 1 + 2 * len(saved)
    assert all(a[0] <= b[0] for a, b in zip(displayed, displayed[1:]))
    count = {1: 0, -1: 0}
    maxima = {1: 0, -1: 0}
    cursor = 1
    previous = displayed[0]
    for raw, orders in sorted(events.items()):
        times = {order[0] for order in orders}
        assert len(times) == 1
        increments = []
        for point in displayed[cursor:cursor+len(orders)]:
            assert point[0] in times
            change = (point[1]-previous[1], point[2]-previous[2])
            assert change in ((1, 0), (-1, 0), (0, 1), (0, -1))
            assert 0 <= point[1] <= cap and 0 <= point[2] <= cap
            increments.append(change)
            previous = point
        expected = Counter((delta, 0) if side == 1 else (0, delta) for stamp, side, delta in orders)
        assert Counter(increments) == expected
        for stamp, side, delta in orders:
            count[side] += delta
        assert previous[1:] == [count[1], count[-1]]
        # ----------------------------------------
        # 同じ原行が全て処理された後の保有区間も直接数える。
        held = [lot for lot in saved if lot['entry_row'] <= raw < lot['exit_row']]
        assert count == {side: sum(lot['side'] == side for lot in held) for side in (1, -1)}
        for side in (1, -1):
            maxima[side] = max(maxima[side], count[side])
        cursor += len(orders)
    assert cursor == len(displayed) and count == {1: 0, -1: 0}
    assert displayed[-1][1:] == [0, 0]
    return dict(max_long=maxima[1], max_short=maxima[-1], last_flat=True,
                actual_fills=2*len(saved), inventory_points=len(displayed))


def main() -> None:
    """
    機能: 当日二CSVと既所有売買JSONから埋込図の全数値を確認する。
    引数: なし。新原book・NPZ・API・売買エンジンは一切読まない。
    返り値: None。検査証跡と読取資料の同bytesコピーを自所有域へ保存する。
    """
    owned = HERE / 'owned'
    owned.mkdir(exist_ok=False)
    evidence_path = HERE.parent / '生成と入力照合.json'
    evidence_raw = evidence_path.read_bytes()
    (owned / '生成と入力照合.json').write_bytes(evidence_raw)
    evidence = json.loads(evidence_raw)
    public = ROOT / evidence['html']['path']
    html_raw = public.read_bytes()
    assert sha(html_raw) == evidence['html']['sha256']
    (owned / '公開HTML.html').write_bytes(html_raw)
    html = html_raw.decode('utf-8')
    parser = Embedded()
    parser.feed(html)
    assert parser.count == 1
    data = json.loads(parser.value.replace('<\\/', '</'))
    source_path = WORK / 'audit/20260924デイ表示の独立照合/表示用資料.json'
    source_raw = source_path.read_bytes()
    assert sha(source_raw) == evidence['source']['sha256']
    source = json.loads(source_raw)
    assert (data['session'], data['method']) == (source['session'], source['method']) == ('2026-09-24_Day', 'ROTATE_S2_T1')
    observations = {}
    total_lots = total_markers = total_actual = 0
    for symbol, cap, expected_bars in (('TOPIX', 10, 415), ('NK225', 20, 413)):
        fixed = evidence['symbols'][symbol]
        csv_path = ROOT / fixed['csv']
        raw = csv_path.read_bytes()
        assert sha(raw) == fixed['sha256']
        (owned / (symbol + '.csv')).write_bytes(raw)
        rows = list(csv.DictReader(StringIO(raw.decode('utf-8-sig'), newline='')))
        candles = []
        for row in rows:
            stamp = datetime.fromisoformat(row['time'])
            assert stamp.date().isoformat() == '2026-09-24' and stamp.utcoffset() == timedelta(hours=9)
            assert stamp.second == stamp.microsecond == 0
            candles.append([stamp.timestamp(), *[float(row[key]) for key in ('open', 'high', 'low', 'close', 'volume')],
                            row['volume_complete'] == 'true'])
        chart, saved = data['symbols'][symbol], source['symbols'][symbol]
        assert candles == chart['candles'] and len(candles) == expected_bars
        assert all(a[0] < b[0] for a, b in zip(candles, candles[1:]))
        assert all(candle[3] <= min(candle[1], candle[4]) <= max(candle[1], candle[4]) <= candle[2] for candle in candles)
        expected_minutes = set(range(int(candles[0][0]), int(candles[-1][0])+60, 60))
        missing = sorted(expected_minutes - {int(row[0]) for row in candles})
        assert len(missing) == (0 if symbol == 'TOPIX' else 2)
        assert chart['groups'] == saved['groups'] and chart['summary'] == saved['expected']
        assert chart['lot_count'] == saved['lot_count'] and chart['group_count'] == saved['group_count']
        assert sum(row['quantity'] for row in chart['groups']) == saved['lot_count']
        assert sum(row['net'] for row in chart['groups']) == saved['expected']['net']
        assert Counter(uid for row in chart['groups'] for uid in row['uids']) == Counter(row['uid'] for row in saved['lots'])
        inventory = inspect_inventory(saved['lots'], chart['inventory'], candles[0][0], cap)
        assert inventory['max_long'] == saved['expected']['max_long']
        assert inventory['max_short'] == saved['expected']['max_short']
        assert 2 * len(chart['groups']) == fixed['grouped_markers']
        assert inventory['actual_fills'] == fixed['filled_orders']
        lookup = {row[0]: row for row in candles}
        outside = 0
        for group in chart['groups']:
            for prefix in ('entry', 'exit'):
                stamp, price = group[prefix + '_epoch'], group[prefix + '_price']
                bar = lookup.get(int(stamp // 60) * 60)
                if bar is not None and not bar[3] <= price <= bar[2]:
                    outside += 1
        observations[symbol] = dict(candles=len(candles), missing_minutes=[datetime.fromtimestamp(t, JST).strftime('%H:%M') for t in missing],
            groups=len(chart['groups']), grouped_markers=2*len(chart['groups']), lot_count=saved['lot_count'],
            net=saved['expected']['net'], outside_last_ohlc_markers=outside, **inventory)
        total_lots += saved['lot_count']
        total_actual += inventory['actual_fills']
        total_markers += 2 * len(chart['groups'])
    assert (total_lots, total_actual, total_markers) == (315, 630, 530)
    first = next(row for row in data['symbols']['TOPIX']['groups'] if 1 in row['uids'])
    assert (first['side'], first['quantity'], first['entry_price'], first['exit_price'], first['net']) == (1, 1, 4105.5, 4061.5, -44082)
    assert (first['entry_time'], first['exit_time']) == ('08:45:02', '15:20:01')
    assert 'groups.findIndex(r=>r.uids.includes(1))' in html
    assert "new Date((t+32400)*1000).toISOString()" in html
    assert '足の高安の外に約定マーカーが出る場合があります' in html
    assert '足はラージの約定値（Last）' in html and '同秒の縦線には複数の約定を含みます' in html
    assert 'for(const entry of [true,false])' in html
    assert 'values.push(r.entry_price)' in html and 'values.push(r.exit_price)' in html
    assert all(kind in html for kind in ('entry-long', 'entry-short', 'exit-long', 'exit-short'))
    proof = dict(passed=True, source_sha256=sha(Path(__file__).read_bytes()), html_sha256=sha(html_raw),
                 generator_sha256=sha((HERE.parent/'build_chart.py').read_bytes()),
                 template_sha256=sha((HERE.parent/'chart_template.html').read_bytes()),
                 source_display_sha256=sha(source_raw), symbols=observations,
                 total_lots=total_lots, total_filled_orders=total_actual, total_grouped_markers=total_markers,
                 first_topix_uid1=first, candle_csv_reads=2, raw_book_reads=0, npz_reads=0, financial_replay=0,
                 registry_changes=0, public_changes=0,
                 留保='同一保存結果の表示照合。保有枚数は原行全処理後を照合し、同原行内の描画順を新たな受信順にしない。欠損分を埋めず、Last足とBBO代理約定の価格差を許容。実ブラウザの描画は別担当。')
    output = HERE / '一分足全列と全約定及び保有枚数の独立表示照合.json'
    assert not output.exists()
    payload = (json.dumps(proof, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    output.write_bytes(payload)
    print(json.dumps(dict(passed=True, sha256=sha(payload), symbols=observations), ensure_ascii=False))


if __name__ == '__main__':
    main()
