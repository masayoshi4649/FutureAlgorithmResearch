"""受信時点だけでE01を進める、仮想売買の実行管理。"""

from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import queue
import signal
import sys
import time

from .features import FeatureEngine
from .strategy import E01Engine
from .storage import JST, RunLock, Store, iso
from .transport import Feed, MarketClient


SYMBOLS = ('NK225', 'TOPIX')
PRODUCTS = {'NK225': 'NK225マイクロ換算', 'TOPIX': 'TOPIXミニ換算'}


def stamp(value: str) -> float:
    """機能: タイムゾーン必須のAPI時刻をUNIX秒へ変換する。

    引数: value(str)。返り値: UNIX秒(float)。
    """
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None:
        raise ValueError('タイムゾーンのない市場時刻は使えません')
    return date.timestamp()


def identity(options: argparse.Namespace) -> str:
    """機能: 継続運転で異なる戦略や設定が混ざることを検出する。

    引数: options(Namespace)。返り値: 識別指紋(str)。
    """
    digest = hashlib.sha256()
    for name in ('strategy.py', 'features.py', 'runtime.py'):
        digest.update((Path(__file__).parent / name).read_bytes())
    digest.update(json.dumps({key: getattr(options, key) for key in
                             ('base_url', 'fill_mode', 'max_price_age', 'stale_seconds', 'poll_seconds', 'reconnect_grace_seconds')}, sort_keys=True).encode())
    return digest.hexdigest()


class PaperRunner:
    """市場監視・戦略・耐久台帳の境界を管理する。"""

    def __init__(self, options: argparse.Namespace, store: Store):
        """機能: 状態を復元し、再起動後は新鮮な価格を待つ。

        引数: options(Namespace)、store(Store)。返り値: なし(None)。
        """
        self.options = options
        self.store = store
        self.signature = identity(options)
        self.session = None
        self.features = None
        self.engines = {}
        self.registration = {}
        self.generation = ''
        self.started = time.time()
        self.activation = self.started
        self.last_fresh = {symbol: 0.0 for symbol in SYMBOLS}
        self.last_push = {symbol: 0.0 for symbol in SYMBOLS}
        self.last_quote_time = {symbol: 0.0 for symbol in SYMBOLS}
        self.gaps = {symbol: True for symbol in SYMBOLS}
        self.gap_after = {symbol: self.started for symbol in SYMBOLS}
        self.gap_since = {symbol: self.started for symbol in SYMBOLS}
        self.gap_mode = {symbol: 'startup' for symbol in SYMBOLS}
        self.resume_observed = {symbol: False for symbol in SYMBOLS}
        self.ready_after = {symbol: self.started + 120 for symbol in SYMBOLS}
        self.input_offset = {symbol: 0 for symbol in SYMBOLS}
        self.last_poll = 0.0
        self.last_checkpoint = 0.0
        self.last_status = 0.0
        self.last_wall = self.started
        self.pending = []
        self.stopping = False
        self.finished = False
        self.halted = ''
        self.received_count = {symbol: 0 for symbol in SYMBOLS}
        self.rejected_count = 0
        self.latest_features = {}
        self.messages = {}
        saved = store.load()
        if saved:
            if saved.get('signature') != self.signature:
                legacy = json.loads((Path(__file__).parent / 'legacy_compatibility.json').read_text(encoding='utf-8'))
                compatible = legacy['signatures'].get(saved.get('signature'))
                if not compatible or any(getattr(options, k) != v for k, v in compatible.items()):
                    raise ValueError('保存状態と戦略・設定が異なります。既存台帳を保存したまま別の --output を指定してください')
                backup = store.backup()
                self.health('互換更新', '旧版の売買・建玉を引き継ぎます。更新前の正本: ' + backup.name)
            self.session = saved['session']
            self.generation = saved['generation']
            self.registration = saved['registration']
            self.halted = saved.get('halted', '')
            self.input_offset = saved.get('input_offset', self.input_offset)
            if saved['features'] is not None:
                self.features = FeatureEngine.from_state(saved['features'])
                self.last_quote_time = {s: self.features.markets[s].get('last_quote_time') or 0.0 for s in SYMBOLS}
            elapsed = self.started - saved.get('saved_at', 0)
            old_connection = saved.get('connectivity', {})
            self.last_push.update(old_connection.get('last_push', {}))
            self.last_fresh.update(old_connection.get('last_fresh', {}))
            for symbol, state in saved['engines'].items():
                self.engines[symbol] = self.make_engine(symbol, state)
                self.engines[symbol].cancel_entry()
                self.resume_observed[symbol] = True
                self.gap_since[symbol] = min(saved.get('saved_at', self.started), old_connection.get('gap_since', {}).get(symbol, self.started)) if old_connection.get('gaps', {}).get(symbol) else saved.get('saved_at', self.started)
                long_gap = elapsed > options.reconnect_grace_seconds or old_connection.get('gap_mode', {}).get(symbol) == 'long'
                self.gap_mode[symbol] = 'long' if long_gap else 'pause'
                self.ready_after[symbol] = old_connection.get('ready_after', {}).get(symbol, self.started)
                if long_gap and self.features:
                    self.features.reset_short_history(symbol)
            self.health('再開', '建玉と返済条件を復元。短時間の中断では条件を維持し、長時間の欠測だけ復旧時返済します')
        else:
            self.health('開始', 'E01の仮想売買。足は指標の準備だけに使用し、起動前の売買記録は作成しません')

    def make_engine(self, symbol: str, state: dict | None = None) -> E01Engine:
        """機能: 同一セッション内の売買器を作成する。

        引数: symbol(str)、state(dict|None)。返り値: 売買器(E01Engine)。
        """
        return E01Engine(symbol, self.session['id'], self.session['start'], self.session['cutoff'],
                         self.session['end'], state=state, fill_mode=self.options.fill_mode)

    def health(self, kind: str, text: str, now: float | None = None) -> None:
        """機能: 状態変化を記録し、同一警告の連続出力を抑える。

        引数: kind/text(str)、now(float|None)。返り値: なし(None)。
        """
        now = time.time() if now is None else now
        key = kind + text
        if now - self.messages.get(key, 0) < 60:
            return
        self.messages[key] = now
        self.pending.append(('health', {'記録時刻': iso(now), '種別': kind, '内容': text}))
        print(f'{iso(now)} [{kind}] {text}', flush=True)

    def gap(self, reason: str, now: float, symbol: str | None = None, hard: bool = False) -> None:
        """機能: 短い欠測では新規だけ取消し、長い欠測を別に管理する。

        引数: reason(str)、now(float)、symbol(str|None)、hard(bool)。返り値: なし(None)。
        """
        for code in ((symbol,) if symbol else SYMBOLS):
            if not self.gaps[code]:
                self.gap_since[code] = self.last_push[code] or now
                self.gap_after[code] = now
                self.gap_mode[code] = 'pause'
            if hard and self.gap_mode[code] != 'long':
                self.health('長時間・重大なデータ欠測', code + ': ' + reason, now)
                if self.features:
                    self.features.reset_short_history(code)
                self.gap_mode[code] = 'long'
                self.gap_after[code] = max(self.gap_after[code], now)
                self.ready_after[code] = now + 120
            self.gaps[code] = True
            self.resume_observed[code] = True
            if code in self.engines:
                self.engines[code].cancel_entry()

    def accept_candles(self, payload: dict, received: float) -> None:
        """機能: 整合した足だけを受け付け、セッション・世代を管理する。

        引数: payload(dict)、received(float)。返り値: なし(None)。
        """
        batch = payload['batch']
        keys = {(value['snapshot']['sessionId'], value['snapshot']['generation']) for value in batch.values()}
        if len(keys) != 1 or set(batch) != {(s, p) for s in SYMBOLS for p in ('1min', '5min')}:
            self.gap('足のセッション不一致', received)
            return
        snapshot = batch['NK225', '1min']['snapshot']
        session_id, generation = next(iter(keys))
        start = stamp(snapshot['session']['startsAt'])
        end = stamp(snapshot['session']['endsAt'])
        # ----------------------------------------
        # 新しいセッションの価格で古い建玉を返済したことにはしない。
        if self.session is None or self.session['id'] != session_id:
            remaining = {s: e.status()['quantity'] for s, e in self.engines.items() if e.status()['quantity']}
            if remaining:
                self.halted = 'セッション内返済を確認できません: ' + str(remaining)
                self.health('未返済・停止', self.halted, received)
                return
            self.session = {'id': session_id, 'start': start, 'end': end, 'cutoff': end - 600}
            self.features = FeatureEngine(session_id, start)
            self.engines = {s: self.make_engine(s) for s in SYMBOLS}
            self.gaps = {s: True for s in SYMBOLS}
            self.gap_after = {s: received for s in SYMBOLS}
            self.gap_since = {s: received for s in SYMBOLS}
            self.gap_mode = {s: 'startup' for s in SYMBOLS}
            self.resume_observed = {s: False for s in SYMBOLS}
            self.last_push = {s: 0.0 for s in SYMBOLS}
            self.last_fresh = {s: 0.0 for s in SYMBOLS}
            self.last_quote_time = {s: 0.0 for s in SYMBOLS}
            self.ready_after = {s: received + 120 for s in SYMBOLS}
            self.input_offset = {s: 0 for s in SYMBOLS}
            self.activation = received
            self.health('セッション開始', session_id + ' / 新規5枚・10枚、片方向上限10枚・20枚', received)
        elif self.generation != generation:
            self.gap('controllerのデータ世代変更', received, hard=True)
            self.features = FeatureEngine(session_id, start)
            self.input_offset = {s: e.status()['row'] + 1 for s, e in self.engines.items()}
            self.activation = received
            self.health('世代変更', '指標を再取得。建玉と返済条件は保持します', received)
        new_registration = payload['registration']
        if self.registration and any(self.registration[s]['symbol'] != new_registration[s]['symbol'] for s in SYMBOLS):
            if any(e.status()['quantity'] for e in self.engines.values()):
                self.halted = '保有中に参照限月が変更されました。別限月価格で返済せず停止します'
                self.health('限月変更・停止', self.halted, received)
                return
            self.gap('参照限月変更', received, hard=True)
        self.registration = new_registration
        self.generation = generation
        for (symbol, period), value in batch.items():
            if value['snapshot']['code'] != symbol:
                raise ValueError('足の銘柄が要求と一致しません')
            self.features.ingest_candles(symbol, 60 if period == '1min' else 300, value['data'], received)
        self.last_poll = received

    def record_trades(self, trades: list[dict], quote_time: float) -> None:
        """機能: 戦略の仮想新規・返済を日本語CSV列へ変換する。

        引数: trades(list[dict])、quote_time(float)。返り値: なし(None)。
        """
        for trade in trades:
            symbol = trade['symbol']
            direction = trade['direction']
            opening = trade['event'] == '新規'
            side = direction if opening else -direction
            reg = self.registration.get(symbol, {})
            row = {'記録時刻': iso(trade['timestamp']), 'セッション': trade['session_id'], '手法': 'E01_受信時刻版',
                   '参照銘柄': symbol, '仮想商品': PRODUCTS[symbol], '参照限月': reg.get('derivMonth', ''),
                   '参照銘柄番号': reg.get('symbol', ''), '区分': trade['event'],
                   '建玉方向': 'ロング' if direction == 1 else 'ショート', '売買': '買い' if side == 1 else '売り',
                   '枚数': trade['quantity'], '約定価格': trade['price'], '新規価格': trade['entry_price'],
                   '確定損益円': trade['realized_yen'], '確定損益ポイント枚': trade['realized_points'],
                   '処理後保有枚数': trade['position_after'], '初期ATR': trade['initial_atr'],
                   '理由': trade['reason'], '組番号': trade['campaign'], '判断元行': trade['source_row'],
                   '約定行': trade['row'], '市場価格時刻': iso(quote_time), '約定モデル': trade['fill_mode'], '費用円': 0}
            self.pending.append(('trade', row))
            print(f"{row['記録時刻']} {symbol} {row['区分']} {row['売買']} {row['枚数']}枚 @{row['約定価格']} {row['理由']} 損益{row['確定損益円']:+,.0f}円", flush=True)

    def accept_book(self, payload: dict, received: float, now: float) -> None:
        """機能: 新鮮なPUSHのみで、既存注文の執行と次の判断を行う。

        引数: payload(dict)、received/now(float)。返り値: なし(None)。
        """
        if self.features is None or self.halted or received < self.activation:
            return
        symbol = next((s for s in SYMBOLS if str(payload.get('Symbol')) == str(self.registration[s]['symbol'])), None)
        if symbol is None:
            return
        if self.gaps[symbol] and received < self.gap_after[symbol]:
            return
        if now - received > 5:
            self.gap('判定処理が受信に追い付きません', now)
            return
        # ----------------------------------------
        # 約定時刻はPUSH受信時刻ではない。無約定でも届く板で接続を判定する。
        if self.session['start'] <= received < self.session['end']:
            previous_push = self.last_push[symbol]
            if not self.gaps[symbol] and previous_push and received - previous_push > self.options.stale_seconds:
                self.gap('板PUSHの受信待ち', received, symbol)
            if self.gaps[symbol] and self.gap_mode[symbol] == 'pause':
                elapsed = received - self.gap_since[symbol]
                if elapsed > self.options.reconnect_grace_seconds:
                    self.gap('板PUSHを猶予時間以上観測できませんでした', received, symbol, hard=True)
                else:
                    self.gaps[symbol] = False
                    self.gap_mode[symbol] = ''
                    if elapsed > self.options.stale_seconds:
                        self.health('受信再開', symbol + ': 建玉と返済条件を維持して再開', received)
            self.last_push[symbol] = received
        try:
            quote_time = stamp(payload['CurrentPriceTime'])
            price = float(payload['CurrentPrice'])
        except (ValueError, TypeError, KeyError):
            self.rejected_count += 1
            self.engines[symbol].cancel_entry()
            self.resume_observed[symbol] = True
            return
        if (not math.isfinite(price) or price <= 0 or quote_time > received + 5
                or received - quote_time > self.options.max_price_age
                or quote_time < self.last_quote_time[symbol]
                or not self.session['start'] <= quote_time < self.session['end']
                or not self.session['start'] <= received < self.session['end']):
            self.rejected_count += 1
            if code_engine := self.engines.get(symbol):
                code_engine.cancel_entry()
            self.resume_observed[symbol] = True
            return
        self.received_count[symbol] += 1
        self.last_fresh[symbol] = received
        self.last_quote_time[symbol] = quote_time
        engine = self.engines[symbol]
        if self.gaps[symbol]:
            if self.gap_mode[symbol] == 'long' and engine.status()['quantity']:
                self.record_trades(engine.force_flatten(received, price, 'データ中断後の観測価格で返済'), quote_time)
            self.gaps[symbol] = False
            if self.gap_mode[symbol] in ('startup', 'long'):
                self.ready_after[symbol] = received + 120
                self.health('価格受信', symbol + ' / 短期判断を120秒準備します', received)
            self.gap_mode[symbol] = ''
        if self.stopping:
            engine.cancel_entry()
            self.record_trades(engine.force_flatten(received, price, '停止時の観測価格で返済'), quote_time)
            return
        feature = self.features.on_book(symbol, payload, received)
        self.latest_features[symbol] = feature
        peer = 'TOPIX' if symbol == 'NK225' else 'NK225'
        indicator_fresh = all(feature.get(name) is not None and 0 <= received - feature[name] <= maximum
                              for name, maximum in (('main_nominal', 180), ('peer_nominal', 180), ('atr_nominal', 420)))
        recovery = self.resume_observed[symbol]
        allow = (not recovery and indicator_fresh and received >= self.ready_after[symbol] and received >= self.ready_after[peer]
                 and not self.gaps[peer] and received - self.last_fresh[peer] <= self.options.stale_seconds
                 and received - self.last_poll <= max(30, 3 * self.options.poll_seconds)
                 and received < self.session['cutoff'])
        if not allow:
            engine.cancel_entry()
        index = feature.get('input_index')
        origin = feature.get('adverse_source')
        offset = self.input_offset[symbol]
        trades = engine.on_tick(received, price, feature.get('atr') or 0.0,
                                feature.get('direction', 0), adverse=feature.get('adverse', 0),
                                adverse_source=None if origin is None else origin + offset,
                                allow_entry=allow,
                                input_index=None if index is None else index + offset,
                                observed_recovery=recovery)
        self.resume_observed[symbol] = False
        self.record_trades(trades, quote_time)

    def snapshot(self) -> dict:
        """機能: 売買と同じ取引で保存する完全な状態を作る。

        引数: なし。返り値: 状態(dict)。
        """
        return {'signature': self.signature, 'session': self.session, 'generation': self.generation,
                'registration': self.registration, 'halted': self.halted,
                'input_offset': self.input_offset, 'saved_at': time.time(),
                'connectivity': {'last_push': self.last_push, 'last_fresh': self.last_fresh,
                                 'gaps': self.gaps, 'gap_since': self.gap_since,
                                 'gap_mode': self.gap_mode, 'ready_after': self.ready_after},
                'features': self.features.dump_state() if self.features else None,
                'engines': {s: e.snapshot() for s, e in self.engines.items()}}

    def checkpoint(self, now: float, force: bool = False) -> None:
        """機能: 売買時は即時、通常時は2秒ごとに状態を確定保存する。

        引数: now(float)、force(bool)。返り値: なし(None)。
        """
        if force or self.pending or now - self.last_checkpoint >= 2:
            self.store.commit(self.snapshot(), self.pending)
            self.pending.clear()
            self.last_checkpoint = now

    def watch(self, now: float) -> None:
        """機能: 無受信・時計逆行・場内未返済を監視する。

        引数: now(float)。返り値: なし(None)。
        """
        if now < self.last_wall - 1:
            self.gap('コンピューター時計が逆行しました', now, hard=True)
        self.last_wall = now
        for symbol in SYMBOLS:
            active = self.session and self.session['start'] <= now < self.session['end']
            if active and self.last_push[symbol] and now - self.last_push[symbol] > self.options.stale_seconds:
                self.gap('板PUSHの受信待ち', now, symbol)
                if now - self.last_push[symbol] > self.options.reconnect_grace_seconds:
                    self.gap('板PUSHを猶予時間以上観測できません', now, symbol, hard=True)
        if self.session and now >= self.session['cutoff']:
            for engine in self.engines.values():
                engine.cancel_entry()
        if self.session and now >= self.session['end'] and any(e.status()['quantity'] for e in self.engines.values()):
            self.halted = '市場価格を観測できずセッション内に返済できませんでした。未返済玉を残して新規停止'
            self.health('未返済・停止', self.halted, now)
        if now - self.last_status >= 10:
            self.store.export()
            status = {'更新時刻': iso(now), '手法': 'E01_受信時刻版', '実注文API': '未実装・呼出しなし',
                      'セッション': self.session, '停止理由': self.halted,
                      '稼働中': not self.finished, '終了処理中': self.stopping and not self.finished, '新鮮な価格受信数': self.received_count,
                      '無効価格除外数': self.rejected_count, '欠測中': self.gaps,
                      '最終板受信からの秒数': {s: round(now - t, 1) if t else None for s, t in self.last_push.items()},
                      '最終採用価格からの秒数': {s: round(now - t, 1) if t else None for s, t in self.last_fresh.items()},
                      '中断の扱い': self.gap_mode,
                      '新規準備完了予定': {s: iso(t) for s, t in self.ready_after.items()},
                      '建玉': {s: e.status() for s, e in self.engines.items()},
                      '直近の判定材料': self.latest_features,
                      'CSV出力エラー': self.store.last_export_error}
            try:
                self.store.status(status)
            except OSError as exc:
                self.health('状態表示の保存失敗', str(exc), now)
            if self.store.last_export_error:
                self.health('CSV出力待ち', 'Excel等でCSVを閉じると再出力します。正本DBには保存済み', now)
            self.last_status = now
        self.checkpoint(now)


def parser() -> argparse.ArgumentParser:
    """機能: 実注文への切替を持たない起動引数を作る。

    引数: なし。返り値: 引数定義(ArgumentParser)。
    """
    result = argparse.ArgumentParser(description='E01のリアルタイム仮想売買。実注文は発行しません。')
    result.add_argument('--base-url', default='http://10.10.100.1:8080', help='市場データの接続先')
    result.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / '運転記録', help='CSVと復旧状態の保存先')
    result.add_argument('--fill-mode', choices=['specified', 'observed'], default='specified', help='指定条件価格、または観測価格で仮想約定')
    result.add_argument('--seconds', type=float, default=0, help='0で連続実行。正数で指定秒後に終了処理')
    result.add_argument('--poll-seconds', type=float, default=10, help='足の取得間隔秒')
    result.add_argument('--max-price-age', type=float, default=30, help='市場価格時刻の許容経過秒')
    result.add_argument('--stale-seconds', type=float, default=60, help='板PUSHがない場合に新規を見送る秒数')
    result.add_argument('--reconnect-grace-seconds', type=float, default=180, help='建玉と返済条件を維持する通信中断の猶予秒数')
    return result


def main(argv: list[str] | None = None) -> int:
    """機能: 仮想売買を連続運転し、終了時には新鮮な観測で返済を試みる。

    引数: argv(list[str]|None)。返り値: 終了コード(int)。
    """
    options = parser().parse_args(argv)
    if options.seconds < 0 or not 1 <= options.poll_seconds <= 60 or not 1 <= options.max_price_age <= options.stale_seconds <= options.reconnect_grace_seconds:
        raise ValueError('秒数の設定が不正です')
    lock = RunLock(options.output)
    store = None
    feed = None
    runner = None
    code = 0
    stop_requests = [0]
    previous_handler = signal.getsignal(signal.SIGINT)

    def request_stop(signum, frame):
        """機能: イベント処理を途中で中断せず停止要求だけを立てる。

        引数: signum(int)、frame(実行フレーム)。返り値: なし(None)。
        """
        stop_requests[0] += 1

    signal.signal(signal.SIGINT, request_stop)
    try:
        store = Store(options.output)
        runner = PaperRunner(options, store)
        feed = Feed(MarketClient(options.base_url), options.poll_seconds)
        runner.checkpoint(time.time(), True)
        feed.start()
        deadline = time.monotonic() + options.seconds if options.seconds else float('inf')
        stop_deadline = float('inf')
        while True:
            try:
                now = time.time()
                if stop_requests[0]:
                    deadline = 0
                if stop_requests[0] > 1:
                    code = 2
                    runner.health('即時停止要求', '直前の完了イベントまで保存し終了します。未返済玉は状態に残します', now)
                    break
                if time.monotonic() >= deadline and not runner.stopping:
                    runner.stopping = True
                    stop_deadline = time.monotonic() + 15
                    runner.health('終了処理', '新規を取り消し、保有があれば新しい観測価格で返済します', now)
                    for engine in runner.engines.values():
                        engine.cancel_entry()
                if feed.overflow.is_set():
                    runner.gap('受信キューの上限超過', now, hard=True)
                    feed.overflow.clear()
                try:
                    kind, received, payload = feed.events.get(timeout=.25)
                except queue.Empty:
                    kind = ''
                if kind == 'candles':
                    runner.accept_candles(payload, received)
                elif kind == 'book':
                    runner.accept_book(payload, received, time.time())
                elif kind == 'disconnected':
                    runner.gap('WebSocket切断: ' + payload, received)
                elif kind == 'candle_error':
                    runner.health('足取得待ち', payload, received)
                elif kind == 'connected':
                    runner.health('接続', '市場PUSHの受信専用接続が成立しました', received)
                runner.watch(time.time())
                if runner.halted:
                    code = 2
                    break
                if runner.stopping:
                    if not any(e.status()['quantity'] for e in runner.engines.values()):
                        break
                    if time.monotonic() >= stop_deadline:
                        runner.health('未返済で中断', '新鮮な価格がないため架空の返済は記録しません。再起動時に復旧返済します')
                        code = 2
                        break
            except KeyboardInterrupt:
                # 独自にKeyboardInterruptを送出する外部呼出しは異常終了とし、
                # 未完了イベントのメモリ状態をDBへ書き込まない。
                raise
        runner.health('終了', '状態と売買記録を保存しました')
        runner.finished = True
        runner.last_status = 0
        runner.watch(time.time())
        runner.checkpoint(time.time(), True)
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        if feed:
            feed.close()
        # 正常終了だけが上記でcheckpoint済み。例外で部分変更された状態は
        # 確定保存せず、次回起動では最後に完了したDB取引から復旧する。
        if store:
            store.close()
        lock.close()
    return code


if __name__ == '__main__':
    try:
        sys.exit(main())
    except Exception as error:
        print('仮想トレードを停止しました: ' + str(error), file=sys.stderr, flush=True)
        sys.exit(1)
