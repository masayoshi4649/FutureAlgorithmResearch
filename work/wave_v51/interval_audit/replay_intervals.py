"""現在の一観測だけを受ける会計器で、売買台帳を30分区間へ再生する。"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))


def stamp(value: float) -> str:
    """機能: 観測時計を日本時間の文字列へ変換する。

    引数: value(float) はUnix秒。返り値: str は日本時間。
    """
    return datetime.fromtimestamp(value, JST).isoformat()


@dataclass(frozen=True, slots=True)
class Fill:
    """現在行に成立した約定。注文方向は買い+1、売り-1。"""
    raw_index: int
    source_index: int
    cycle: int
    side: int
    quantity: int
    price: float
    opening: bool


class IntervalAccount:
    """未来の配列を持たず、現在の観測・約定と保存済み口座状態だけを処理する。"""

    def __init__(self, start: float, end: float, point_value: float, cap: int, minutes: int = 30):
        """機能: 場内口座と時間区間を初期化する。

        引数: start/end/point_value(float)、cap/minutes(int)。返り値: なし(None)。
        """
        assert start < end and point_value > 0 and cap > 0 and minutes > 0
        self.start, self.end, self.point_value, self.cap = start, end, point_value, cap
        self.width = minutes * 60
        self.left = start
        self.right = min((math.floor(start / self.width) + 1) * self.width, end)
        self.rows = []
        self.lots = {}
        self.balance = self.profit = self.loss = 0.
        self.first_unrealized = self.last_unrealized = 0.
        self.last_price = None
        self.last_time = start
        self.last_seq = self.last_index = -1
        self.entries = self.closed = self.win_units = self.loss_units = self.flat_units = 0
        self.max_long = self.max_short = self.count = 0
        self.finalized = False

    def unrealized(self) -> float:
        """機能: 最後に受けた価格だけで現在建玉を時価評価する。

        引数: なし。返り値: float は円換算の含み損益。
        """
        if not self.lots:
            return 0.
        assert self.last_price is not None
        return sum(side * qty * (self.last_price - entry) * self.point_value
                   for side, qty, entry in self.lots.values())

    def close_interval(self) -> None:
        """機能: 区間端より前に受けた最後の価格で当区間を確定する。

        引数: なし。返り値: なし(None)。未来価格の補間はしない。
        """
        closing = self.unrealized()
        realized = self.profit - self.loss
        change = closing - self.first_unrealized
        long_qty = sum(qty for side, qty, _ in self.lots.values() if side == 1)
        short_qty = sum(qty for side, qty, _ in self.lots.values() if side == -1)
        self.rows.append(dict(開始=stamp(self.left), 終了_未満=stamp(self.right),
                              確定利益円=self.profit, 確定損失円=self.loss, 確定収支円=realized,
                              開始含み円=self.first_unrealized, 終了含み円=closing, 含み増減円=change,
                              時価収支円=realized + change, 新規件数=self.entries, 返済枚数=self.closed,
                              利益返済枚数=self.win_units, 損失返済枚数=self.loss_units, 同値返済枚数=self.flat_units,
                              終了買い枚数=long_qty, 終了売り枚数=short_qty,
                              評価価格=self.last_price, 評価価格時刻=stamp(self.last_time) if self.last_price is not None else None,
                              評価原本行=self.last_seq if self.last_price is not None else None,
                              価格観測数=self.count))
        self.last_unrealized = closing
        self.first_unrealized = closing
        self.profit = self.loss = 0.
        self.entries = self.closed = self.win_units = self.loss_units = self.flat_units = self.count = 0
        self.left = self.right
        self.right = min(self.right + self.width, self.end)

    def on_event(self, raw_index: int, seq: int, at: float, price: float, fills: tuple[Fill, ...] = ()) -> None:
        """機能: 現在の一観測とその行に成立した約定だけを順次処理する。

        引数: raw_index/seq(int)、at/price(float)、fills(tuple[Fill,...])。
        返り値: なし(None)。同時刻も原本行の順序を保つ。
        """
        assert not self.finalized and raw_index > self.last_index and seq > self.last_seq
        assert self.last_time <= at < self.end and math.isfinite(price) and price > 0
        while at >= self.right:
            self.close_interval()
        self.last_time, self.last_price = at, price
        self.last_seq, self.last_index = seq, raw_index
        self.count += 1
        for fill in fills:
            assert fill.raw_index == raw_index and 0 <= fill.source_index < raw_index
            assert fill.side in (-1, 1) and fill.quantity > 0
            assert math.isfinite(fill.price) and fill.price > 0
            if fill.opening:
                assert fill.cycle not in self.lots
                self.lots[fill.cycle] = (fill.side, fill.quantity, fill.price)
                self.entries += 1
            else:
                side, remaining, entry = self.lots[fill.cycle]
                assert fill.side == -side and fill.quantity <= remaining
                pnl = side * fill.quantity * (fill.price - entry) * self.point_value
                self.balance += pnl
                self.profit += max(pnl, 0.)
                self.loss += max(-pnl, 0.)
                self.closed += fill.quantity
                self.win_units += fill.quantity if pnl > 0 else 0
                self.loss_units += fill.quantity if pnl < 0 else 0
                self.flat_units += fill.quantity if pnl == 0 else 0
                if remaining == fill.quantity:
                    del self.lots[fill.cycle]
                else:
                    self.lots[fill.cycle] = (side, remaining - fill.quantity, entry)
            long_qty = sum(qty for side, qty, _ in self.lots.values() if side == 1)
            short_qty = sum(qty for side, qty, _ in self.lots.values() if side == -1)
            assert max(long_qty, short_qty) <= self.cap
            self.max_long = max(self.max_long, long_qty)
            self.max_short = max(self.max_short, short_qty)

    def snapshot(self) -> dict:
        """機能: 途中切断比較用に現在までの状態だけを返す。

        引数: なし。返り値: dict は現在口座と確定区間の状態。
        """
        return dict(現金=self.balance, 含み=self.unrealized(), 建玉=dict(self.lots),
                    時刻=self.last_time, 行=self.last_seq, 区間始=self.left, 区間終=self.right,
                    区間利益=self.profit, 区間損失=self.loss, 新規=self.entries, 返済=self.closed,
                    買い最大=self.max_long, 売り最大=self.max_short, 完了区間=list(self.rows))

    def finish(self) -> list[dict]:
        """機能: 場末までの区間を確定し、無建玉と損益の望遠和を確認する。

        引数: なし。返り値: list[dict] は時間区間会計。
        """
        assert not self.finalized and not self.lots
        while self.left < self.end:
            self.close_interval()
        self.finalized = True
        assert self.last_unrealized == 0
        assert abs(sum(r['確定収支円'] for r in self.rows) - self.balance) < 1e-7
        assert abs(sum(r['時価収支円'] for r in self.rows) - self.balance) < 1e-7
        assert abs(sum(r['含み増減円'] for r in self.rows)) < 1e-7
        return self.rows


def read(path: Path) -> object:
    """機能: JSON又はgzip圧縮JSONを読む。

    引数: path(Path)。返り値: object は内容。
    """
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == '.gz' else data)


def normalize(ready: dict, ledger: dict) -> tuple[dict[int, tuple[Fill, ...]], float]:
    """機能: E01型又は独立新方式型の台帳を共通の現在約定イベントへ変換する。

    引数: ready/ledger(dict)。返り値: 約定行別イベントと期待損益(tuple[dict,float])。
    """
    result = {}
    cycle = -1
    active_directions = {}
    value = 1000. if ready['symbol'] == 'TOPIX' else 10.
    for row in ledger['orders']:
        if len(row) == 8:
            fill, source, cid, side, qty, price, _, opening = row
            fill, source, cid = int(fill), int(source), int(cid)
        elif len(row) == 10:
            decision_time, fill_time, source_seq, fill_seq, kind, side, qty, price, _, _ = row
            fill = int(np.searchsorted(ready['seq'], int(fill_seq)))
            source = int(np.searchsorted(ready['seq'], int(source_seq)))
            assert ready['seq'][fill] == fill_seq and ready['seq'][source] == source_seq
            assert ready['time_s'][fill] == fill_time and ready['time_s'][source] == decision_time
            opening = kind == 1
            if opening:
                cycle += 1
                assert int(side) not in active_directions
                cid = cycle
                active_directions[int(side)] = [cid, int(qty)]
            else:
                position_side = -int(side)
                cid, remaining = active_directions[position_side]
                assert int(qty) <= remaining
                if int(qty) == remaining:
                    del active_directions[position_side]
                else:
                    active_directions[position_side] = [cid, remaining - int(qty)]
        else:
            raise ValueError(f'未対応の注文列数: {len(row)}')
        assert source < fill and ready['time_s'][source] <= ready['time_s'][fill]
        assert int(qty) == qty and int(side) == side
        result.setdefault(fill, []).append(Fill(fill, source, cid, int(side), int(qty), float(price), bool(opening)))
    if ledger['trades']:
        size = len(ledger['trades'][0])
        expected = sum(row[10] * value if size == 11 else row[6] for row in ledger['trades'])
    else:
        expected = 0.
    return {index: tuple(fills) for index, fills in result.items()}, expected


def run_account(ready: dict, ledger: dict, prefix_check: bool = False) -> tuple[list[dict], dict]:
    """機能: 原本順の価格・現時点約定を流し、区間会計と必要時の接頭辞不変性を確認する。

    引数: ready/ledger(dict)、prefix_check(bool)。返り値: 区間行と監査(dict)の組。
    """
    by_index, expected = normalize(ready, ledger)
    value, cap = (1000., 10) if ready['symbol'] == 'TOPIX' else (10., 20)
    end = ready['limit'] + 300
    account = IntervalAccount(ready['start'], end, value, cap)
    cutoffs = {len(ready['last']) // 3, len(ready['last']) * 2 // 3} if prefix_check else set()
    checkpoint = {}
    for i, (at, seq, price) in enumerate(zip(ready['time_s'], ready['seq'], ready['last'])):
        account.on_event(i, int(seq), float(at), float(price), by_index.get(i, ()))
        if i in cutoffs:
            checkpoint[i] = account.snapshot()
    rows = account.finish()
    assert abs(account.balance - expected) < 1e-7
    actual_pnl = [row[10] * value if len(row) == 11 else row[6] for row in ledger['trades']]
    assert abs(sum(row['確定利益円'] for row in rows) - sum(max(v, 0.) for v in actual_pnl)) < 1e-7
    assert abs(sum(row['確定損失円'] for row in rows) - sum(max(-v, 0.) for v in actual_pnl)) < 1e-7
    assert sum(row['返済枚数'] for row in rows) == sum(int(row[3]) for row in ledger['trades'])
    # ----------------------------------------
    # 未来の価格も注文も渡さず、途中までのイベントだけで同じ口座状態へ到達する。
    for cutoff in sorted(cutoffs):
        shorter = IntervalAccount(ready['start'], end, value, cap)
        for i in range(cutoff + 1):
            shorter.on_event(i, int(ready['seq'][i]), float(ready['time_s'][i]), float(ready['last'][i]), by_index.get(i, ()))
        assert shorter.snapshot() == checkpoint[cutoff]
    audit = dict(セッション=ready['session'], 銘柄=ready['symbol'], 区間数=len(rows),
                 価格観測数=len(ready['last']), 新規件数=sum(r['新規件数'] for r in rows),
                 返済枚数=sum(r['返済枚数'] for r in rows), 確定収支円=account.balance,
                 時価収支合計円=sum(r['時価収支円'] for r in rows), 含み増減合計円=sum(r['含み増減円'] for r in rows),
                 最大買い枚数=account.max_long, 最大売り枚数=account.max_short,
                 場末建玉ゼロ=True, 既存台帳損益一致=True, 利益損失枚数別照合=True, 接頭辞比較数=len(cutoffs))
    return rows, audit


def main() -> None:
    """機能: E01/O03と指定された追加台帳を同じ逐次会計器で区間化する。

    引数: コマンド引数 --include 名前=台帳パス を任意個。返り値: なし(None)。
    """
    parser = argparse.ArgumentParser(description='現在イベントだけを読む時間区間会計')
    parser.add_argument('--include', action='append', default=[], help='追加の手法名=台帳JSON/gzipパス')
    args = parser.parse_args()
    target = HERE.parent / 'overlay' / 'research.py'
    spec = importlib.util.spec_from_file_location('overlay_input_adapter', target)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    inputs, baseline = module.load()
    methods = {'E01': baseline}
    source_paths = {'E01': '既存検証済みE01台帳（overlay.loadと共通）'}
    o03 = HERE.parent / 'overlay' / 'O03_台帳.json.gz'
    methods['O03'] = {(row['session'], row['symbol']): row for row in read(o03)}
    source_paths['O03'] = str(o03.relative_to(ROOT))
    for value in args.include:
        name, path_text = value.split('=', 1)
        assert name not in methods
        path = Path(path_text)
        source_paths[name] = str(path)
        methods[name] = {(row['session'], row['symbol']): row for row in read(path)}
    output, audits = [], []
    for name, ledgers in methods.items():
        assert set(ledgers) == set(inputs)
        for key, ready in sorted(inputs.items()):
            prefix_check = key[0] in ('2026-09-21_Day', '2026-10-05_Night')
            rows, audit = run_account(ready, ledgers[key], prefix_check)
            output.append(dict(手法=name, セッション=key[0], 銘柄=key[1], 区間=rows))
            audits.append(dict(手法=name, **audit))
        print(f'{name}: 46口座の逐次区間会計を確認', flush=True)
    doc = dict(区間分=30, 区間境界='日本時間の毎時00分/30分で区切る。[開始,終了)。日中初回08:45〜09:00と場末は短い区間。',
               評価終了='既存入力の強制返済開始limitから300秒後。原本解析対象終端と同じ。',
               時計制約='time_sはCurrentPriceTime由来の約定時計であり受信時刻ではない。同時刻の原本行順を保持。受信遅延は再現しない。',
               費用=0, 約定='元の検証台帳の約定を現在イベントとして再生。新規シグナルは再選択しない。',
               評価='端点より前の最後の価格。未来補間なし。時価収支=確定収支+終了含み-開始含み。',
               元台帳=source_paths, 口座=output)
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / '時間区間損益.json.gz').write_bytes(gzip.compress(json.dumps(doc, ensure_ascii=False, allow_nan=False).encode('utf8'), mtime=0))
    summary = dict(全合格=True, 手法数=len(methods), 口座数=len(audits), 区間数=sum(a['区間数'] for a in audits),
                   接頭辞比較数=sum(a['接頭辞比較数'] for a in audits), 結果=audits,
                   実装SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (HERE / '監査結果.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')
    print(json.dumps({k: v for k, v in summary.items() if k != '結果'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
