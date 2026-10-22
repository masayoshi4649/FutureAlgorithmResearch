"""九月二十四日デイの保存明細を、金融再生なしで独立照合する。"""

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import hashlib
from html.parser import HTMLParser
from io import BytesIO
import json
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
STAGE = WORK / 'session_20260924_day'
OUT = HERE / '20260924デイ表示の独立照合'
JST = timezone(timedelta(hours=9))
GROUP_KEY = ('side', 'entry_epoch', 'entry_price', 'exit_epoch', 'exit_price',
             'reason', 'entry_decision_epoch', 'exit_decision_epoch')


def digest(payload: bytes) -> str:
    """
    機能: 保全した同bytes資料の内容指紋を返す。
    引数: payload(bytes)は表示用資料又は保存注文玉のNPZ。
    返り値: strはSHA256。原市場を読まない。
    """
    return hashlib.sha256(payload).hexdigest()


def time_text(epoch: float) -> str:
    """
    機能: 保存UNIX秒を同日の日本時刻へ変換する。
    引数: epoch(float)は約定又は判断のUNIX秒。
    返り値: strはHH:MM:SS。時刻の逆算や日付補正を行わない。
    """
    value = datetime.fromtimestamp(float(epoch), JST)
    assert value.strftime('%Y-%m-%d') == '2026-09-24'
    return value.strftime('%H:%M:%S')


class Tables(HTMLParser):
    """公開HTMLの表本文だけを文字列として保持する。"""

    def __init__(self) -> None:
        """
        機能: 商品別の行を受け取る状態を初期化する。
        引数: なし。
        返り値: None。
        """
        super().__init__()
        self.symbol = None
        self.body = False
        self.cell = None
        self.row = None
        self.rows = defaultdict(list)

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """
        機能: 商品節と表本文のセル境界を受け取る。
        引数: tag(str)は要素名、attrs(list)は属性。
        返り値: None。
        """
        attrs = dict(attrs)
        if tag == 'section':
            self.symbol = attrs.get('id')
        elif tag == 'tbody':
            self.body = True
        elif tag == 'tr' and self.body:
            self.row = dict(cells=[], title=attrs['title'], net=float(attrs['data-net']))
        elif tag == 'td' and self.body:
            self.cell = ''

    def handle_data(self, data: str) -> None:
        """
        機能: 表のセル内に現れた表示文字を集める。
        引数: data(str)はHTMLから復号した文字列。
        返り値: None。
        """
        if self.cell is not None:
            self.cell += data

    def handle_endtag(self, tag: str) -> None:
        """
        機能: 表のセル・行・商品節を閉じる。
        引数: tag(str)は終了要素名。
        返り値: None。
        """
        if tag == 'td' and self.body:
            self.row['cells'].append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.body:
            self.rows[self.symbol].append(self.row)
            self.row = None
        elif tag == 'tbody':
            self.body = False
        elif tag == 'section':
            self.symbol = None


def main() -> None:
    """
    機能: 根が抽出した二商品の全玉と集約行を保存NPZと照合する。
    引数: なし。原成果や元監査所有NPZを再読せず、根の新所有コピーを使う。
    返り値: None。同一結果の表示監査であり金融再生・新規試行登録はしない。
    """
    OUT.mkdir(exist_ok=False)
    raw = (STAGE / '表示用の全玉と同時約定集約.json').read_bytes()
    (OUT / '表示用資料.json').write_bytes(raw)
    display_sha = digest(raw)
    data = json.loads(raw)
    assert data['passed'] and data['session'] == '2026-09-24_Day' and data['method'] == 'ROTATE_S2_T1'
    assert data['original_market_reads'] == data['financial_replay'] == 0
    generated = json.loads((STAGE / '生成証跡.json').read_text(encoding='utf-8'))
    html_payload = (ROOT / generated['html_path']).read_bytes()
    assert digest(html_payload) == generated['html_sha256']
    html_text = html_payload.decode('utf-8')
    tables = Tables()
    tables.feed(html_text)
    projection = {}
    inputs = {}
    for symbol, multiple, one_fee, cap, expected_count, expected_profit, expected_loss in (
        ('TOPIX', 1000, 41, 10, 146, 169012, 237484),
        ('NK225', 10, 11, 20, 169, 30768, 65486)):
        shown = data['symbols'][symbol]
        raw = (STAGE / 'owned' / (symbol + '.npz')).read_bytes()
        assert digest(raw) == shown['reference']['sha256']
        (OUT / (symbol + '.npz')).write_bytes(raw)
        inputs[symbol] = dict(path=str(STAGE / 'owned' / (symbol + '.npz')), sha256=digest(raw))
        with np.load(BytesIO(raw), allow_pickle=False) as stored:
            # ----------------------------------------
            # 注文と玉だけを展開し、気配・曲線は読まない。
            orders_all = stored['orders']
            lots_all = stored['lots']
        assert orders_all.shape[1] == 19 and lots_all.shape[1] == 20
        orders = orders_all[orders_all[:, 0] == 14, 1:]
        lots = lots_all[lots_all[:, 0] == 14, 1:]
        assert orders.shape == (2 * expected_count, 18) and lots.shape == (expected_count, 19)
        assert set(orders[:, 1]) == {1, 2} and np.all(orders[:, 11] == 1)
        assert np.all(orders[:, 4] > orders[:, 3]) and np.all(orders[:, 6] >= orders[:, 5])
        assert np.all(orders[:, 8] == one_fee)
        assert np.all(orders[1:, 4] >= orders[:-1, 4])
        ordermap = {(int(order[0]), int(order[1])): order for order in orders}
        assert len(ordermap) == len(orders)
        assert len(set(lots[:, 0])) == len(lots)
        expected_lots = {}
        held = {}
        maximum = {1: 0, -1: 0}
        for order in orders:
            uid, kind, side = map(int, order[:3])
            if kind == 1:
                assert uid not in held
                held[uid] = side
            else:
                assert held.pop(uid) == -side
            for direction in (1, -1):
                maximum[direction] = max(maximum[direction], sum(v == direction for v in held.values()))
        assert not held and max(maximum.values()) <= cap
        for lot in lots:
            uid, side = int(lot[0]), int(lot[1])
            entry, exit_ = ordermap[uid, 1], ordermap[uid, 2]
            assert side in (1, -1) and entry[2] == side and exit_[2] == -side
            assert entry[3] == lot[3] and entry[4] == lot[4] and entry[6] == lot[5] and entry[7] == lot[6]
            assert exit_[3] == lot[7] and exit_[4] == lot[8] and exit_[6] == lot[9] and exit_[7] == lot[10]
            assert entry[10] == exit_[10] == lot[2]
            assert entry[13] == lot[17] and exit_[13] == lot[18]
            assert lot[14] == exit_[9] and lot[14] in (1, 9)
            points = float(side * (lot[10] - lot[6]))
            assert points * multiple == lot[11]
            assert lot[12] == entry[8] + exit_[8] == 2 * one_fee
            assert lot[11] - lot[12] == lot[13] == exit_[16]
            assert entry[16] == 0 and lot[4] <= lot[8]
            expected_lots[uid] = dict(uid=uid, side=side, rung=int(lot[2]),
                entry_epoch=float(lot[5]), exit_epoch=float(lot[9]),
                entry_time=time_text(lot[5]), exit_time=time_text(lot[9]),
                entry_price=float(lot[6]), exit_price=float(lot[10]),
                entry_row=int(lot[4]), exit_row=int(lot[8]),
                entry_decision_epoch=float(entry[5]), exit_decision_epoch=float(exit_[5]),
                entry_decision_time=time_text(entry[5]), exit_decision_time=time_text(exit_[5]),
                points=points, quantity=1, gross=float(lot[11]), fees=float(lot[12]),
                net=float(lot[13]), reason=int(lot[14]))
        assert len(shown['lots']) == len(expected_lots)
        assert {row['uid']: row for row in shown['lots']} == expected_lots
        grouped = defaultdict(list)
        for lot in expected_lots.values():
            grouped[tuple(lot[key] for key in GROUP_KEY)].append(lot)
        assert len(grouped) == len(shown['groups']) == shown['group_count']
        assert len(tables.rows[symbol]) == len(grouped)
        all_group_uids = []
        for number, (group, htmlrow) in enumerate(zip(shown['groups'], tables.rows[symbol]), 1):
            key = tuple(group[key] for key in GROUP_KEY)
            members = grouped.pop(key)
            uids = [row['uid'] for row in members]
            assert set(group['uids']) == set(uids) and len(group['uids']) == len(uids)
            quantity = len(members)
            assert group['quantity'] == quantity
            for name in ('gross', 'fees', 'net'):
                assert group[name] == sum(row[name] for row in members)
            assert group['gross'] == group['points'] * quantity * multiple
            assert group['fees'] == 2 * one_fee * quantity
            assert group['net'] == group['gross'] - group['fees']
            reason = '場末返済' if group['reason'] == 9 else ('追尾利確' if group['net'] > 0 else '追尾返済・損失')
            def fmt(value: float, signed: bool = False) -> str:
                """
                機能: 公開された数値セルの文字列を独立に作る。
                引数: value(float)は価格又は円、signed(bool)は正符号表示。
                返り値: strは桁区切り付きの表示値。
                """
                return format(value, ('+' if signed and value > 0 else '') + ',g')
            cells = [str(number), '買い→売り' if group['side'] == 1 else '売り→買い',
                     group['entry_time'], fmt(group['entry_price']), group['exit_time'], fmt(group['exit_price']),
                     fmt(group['points'], True) + ('pt' if symbol == 'TOPIX' else '円'), str(quantity),
                     fmt(group['gross'], True), fmt(group['fees']), fmt(group['net'], True), reason]
            assert cells == htmlrow['cells'] and htmlrow['net'] == group['net']
            assert htmlrow['title'] == 'UID ' + ','.join(map(str, group['uids'])) + '／新規判断 ' + group['entry_decision_time'] + '／返済判断 ' + group['exit_decision_time']
            all_group_uids.extend(group['uids'])
        assert not grouped and Counter(all_group_uids) == Counter(expected_lots.keys())
        net = lots[:, 13]
        summary = dict(profit=float(np.maximum(net, 0).sum()), loss=float(np.maximum(-net, 0).sum()),
                       net=float(net.sum()), wins=int((net > 0).sum()), losses=int((net < 0).sum()),
                       fees=float(lots[:, 12].sum()), entries=len(lots), closed_lots=len(lots), unclosed=0,
                       max_long=maximum[1], max_short=maximum[-1])
        assert summary['profit'] == expected_profit and summary['loss'] == expected_loss
        assert shown['lot_count'] == expected_count
        for key, value in summary.items():
            assert value == shown['expected'][key]
        assert f"利益 {summary['profit']:,.0f}円（{summary['wins']}枚）／損失 {summary['loss']:,.0f}円（{summary['losses']}枚）／収支 {summary['net']:,.0f}円" in html_text
        assert sum(order[8] for order in orders) == summary['fees']
        reason_summary = {int(reason): dict(lots=int(np.count_nonzero(lots[:, 14] == reason)),
            net=float(net[lots[:, 14] == reason].sum())) for reason in sorted(set(lots[:, 14]))}
        projection[symbol] = dict(**summary, groups=shown['group_count'], orders=len(orders), reasons=reason_summary)
    proof = dict(passed=True, session=data['session'], method=data['method'],
        source_sha256=digest(Path(__file__).read_bytes()), display_sha256=display_sha,
        html_sha256=digest(html_payload), inputs=inputs, projection=projection,
        root_npz_reads=2, display_reads=1, quotes_columns_read=0,
        original_result_reads=0, original_market_reads=0, original_audit_cache_reads=0,
        financial_replay=0, new_trial_registration=0,
        留保='次正常気配であることとBBO価格資格は既1440口座監査へ委譲。本表示監査はorders/lotsだけで原row先後・同時計許容と全数値を再確認した。累計完結枚数は同時保有上限と別。')
    path = OUT / '九月二十四日デイの全玉集約円時刻と公開表の独立照合.json'
    payload = (json.dumps(proof, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    path.write_bytes(payload)
    print(json.dumps(dict(passed=True, sha256=digest(payload), projection=projection), ensure_ascii=False))


if __name__ == '__main__':
    main()
