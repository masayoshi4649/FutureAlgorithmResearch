"""金融を実行せず、保存TOPIX四十場と指定原板末尾の観測終点を調べる。"""

from datetime import datetime, timedelta, timezone
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path

import numpy as np


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
JST = timezone(timedelta(hours=9))
KEYS = ('row', 'time', 'last', 'bid', 'ask')


def digest(data: bytes) -> str:
    """
    機能: 既に読み取ったbytesだけから指紋を計算する。
    引数: data(bytes)は一読済み内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(data).hexdigest()


def stamp(value: float) -> str | None:
    """
    機能: epoch秒を日本時間の実日付時刻へ表示する。
    引数: value(float)はepoch秒。
    返り値: strまたはNone。未観測は推定しない。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat() if math.isfinite(value) else None


def record(q: dict, index: int | None) -> dict | None:
    """
    機能: 指定観測行の実時刻・Last・BBOを小資料へ投影する。
    引数: q(dict[str,ndarray])、index(intまたはNone)。
    返り値: dictまたはNone。気配更新時刻を価格時計と同一視しない。
    """
    if index is None:
        return None
    return dict(index=int(index), row=int(q['row'][index]),
                epoch=float(q['time'][index]), JST=stamp(q['time'][index]),
                Last=float(q['last'][index]), bid=float(q['bid'][index]),
                ask=float(q['ask'][index]), spread=float(q['ask'][index]-q['bid'][index]),
                同値気配=bool(q['bid'][index] == q['ask'][index]))


def save(path: Path, value: dict) -> None:
    """
    機能: UTF-8の小さな検査資料を新規保存する。
    引数: path(Path)、value(dict)。
    返り値: None。既存資料を上書きしない。
    """
    assert not path.exists(), path
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def raw_tail() -> dict:
    """
    機能: 先に保全した原板末尾だけから引け時計とLast/BBOの有無を調べる。
    引数: なし。
    返り値: dictは末尾範囲に限定した事実。原板は再読しない。
    """
    folder = HERE/'owned_raw_tail'
    metadata = json.loads((folder/'取得範囲.json').read_text(encoding='utf-8'))
    data = (ROOT/metadata['saved_path']).read_bytes()
    assert digest(data) == metadata['saved_sha256']
    rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    valid_last = [r for r in rows if r.get('CurrentPriceTime') and r.get('CurrentPrice') is not None]
    after = [r for r in valid_last if datetime.fromisoformat(r['CurrentPriceTime']).time().isoformat() >= '15:45:00']
    times = [r['CurrentPriceTime'] for r in valid_last]
    last = rows[-1]
    endpoint = dict(CurrentPriceTime=last.get('CurrentPriceTime'), CurrentPrice=last.get('CurrentPrice'),
                    TradingVolumeTime=last.get('TradingVolumeTime'), TradingVolume=last.get('TradingVolume'),
                    Buy1=last.get('Buy1'), Sell1=last.get('Sell1'),
                    AskPrice=last.get('AskPrice'), BidPrice=last.get('BidPrice'),
                    CurrentPriceStatus=last.get('CurrentPriceStatus'),
                    CurrentPriceChangeStatus=last.get('CurrentPriceChangeStatus'))
    clock_keys = sorted({key for r in rows for key in r if 'time' in key.lower()})
    return dict(**metadata, 観測した価格時計最小=min(times), 観測した価格時計最大=max(times),
                引け時計以降のLast行数=len(after), 最終行=endpoint, 時刻キー=clock_keys,
                独立気配時刻キーなし=not any(k in rows[0] for k in ('BuyTime', 'SellTime', 'BidTime', 'AskTime', 'received_at', 'timestamp')),
                結論='原板末尾1330行の価格時計は15:39:58まで。15:45のLast/BBOを新たに示す行は末尾にはない。',
                留保='末尾2MiBの検査であり原板全履歴の完全走査ではない。価格時計と真受信時刻・気配更新時刻は別。')


def main() -> None:
    """
    機能: 固定四十場のquotes五列を各一読保全し、引け前六分代理の可否を保存する。
    引数: なし。
    返り値: None。注文・玉・曲線の配列は取得せず、金融再生は行わない。
    """
    source = ROOT/'work/stability121_20261017/入力目録.json'
    meta_bytes = source.read_bytes()
    meta = json.loads(meta_bytes)
    inputs = meta['inputs']
    assert len(inputs) == 40 and len({item['session'] for item in inputs}) == 40
    assert {item['symbol'] for item in inputs} == {'TOPIX'}
    owned = HERE/'owned'
    assert not owned.exists(), '同一四十場を再読しません'
    owned.mkdir()
    details = []
    copies = []
    for item in inputs:
        payload = (ROOT/item['path']).read_bytes()
        assert digest(payload) == item['sha256'], item['path']
        with np.load(BytesIO(payload), allow_pickle=False) as archive:
            q = {key: archive['quotes__'+key].copy() for key in KEYS}
        del payload
        n = len(q['row'])
        assert n > 0 and all(len(v) == n for v in q.values())
        assert np.all(np.diff(q['row']) > 0)
        memory = BytesIO()
        np.savez_compressed(memory, **{'quotes__'+k: v for k, v in q.items()})
        saved = memory.getvalue()
        target = owned/(item['session']+'.npz')
        target.write_bytes(saved)
        day = datetime.strptime(item['session'].split('_')[0], '%Y-%m-%d').replace(tzinfo=JST)
        is_day = item['session'].endswith('_Day')
        closing = day.replace(hour=15, minute=45) if is_day else (day+timedelta(days=1)).replace(hour=6)
        opening = day.replace(hour=8, minute=45) if is_day else day.replace(hour=17)
        ending, beginning = closing.timestamp(), opening.timestamp()
        finite_clock = np.isfinite(q['time'])
        observable = (finite_clock & np.isfinite(q['last']) & (q['last'] > 0)
                      & np.isfinite(q['bid']) & np.isfinite(q['ask'])
                      & (q['bid'] > 0) & (q['ask'] >= q['bid']))
        inside = observable & (q['time'] >= beginning) & (q['time'] <= ending)
        accepted = np.zeros(n, dtype=bool)
        watermark = -math.inf
        for i in np.flatnonzero(inside):
            if q['time'][i] >= watermark:
                accepted[i] = True
                watermark = float(q['time'][i])
        before = np.flatnonzero(accepted & (q['time'] >= ending-360.))
        at = np.flatnonzero(accepted & (q['time'] == ending))
        after = np.flatnonzero(observable & (q['time'] > ending) & (q['time'] <= ending+360.))
        endpoints = np.flatnonzero(accepted)
        last_accepted = int(endpoints[-1]) if len(endpoints) else None
        last_finite = int(np.flatnonzero(finite_clock)[-1]) if finite_clock.any() else None
        proxy = int(before[-1]) if len(before) else None
        detail = dict(session=item['session'], symbol='TOPIX', kind='Day' if is_day else 'Night',
                      引け指定JST=closing.isoformat(), 引け指定epoch=ending, rows=n,
                      finite_clock_rows=int(finite_clock.sum()), 観測可能行数=int(observable.sum()),
                      非逆行場内正常行数=int(accepted.sum()),
                      最終有限時計行=record(q, last_finite), 最終正常行=record(q, last_accepted),
                      引け直前六分の正常行数=len(before), 引け同秒の正常行数=len(at),
                      引け後六分の観測可能行数=len(after),
                      六分代理可能=proxy is not None, 採用可能な終端代理=record(q, proxy),
                      引けまでの秒差=None if proxy is None else ending-float(q['time'][proxy]),
                      source=dict(path=item['path'], sha256=item['sha256'], reads=1, arrays=list(KEYS)),
                      owned=dict(path=target.relative_to(ROOT).as_posix(), sha256=digest(saved)))
        details.append(detail)
        copies.append(dict(session=item['session'], symbol='TOPIX', **detail['owned'],
                           source_path=item['path'], source_sha256=item['sha256'],
                           terminal_proxy_index=proxy, terminal_proxy=detail['採用可能な終端代理']))
    tail = raw_tail()
    result = dict(passed=True, scope='TOPIX既知40場・quotes五列の実観測終点と9/24Day原板末尾',
                  source_manifest=dict(path=source.relative_to(ROOT).as_posix(), sha256=digest(meta_bytes)),
                  sessions=meta['sessions'], count=len(details), details=details, raw_tail=tail,
                  summary=dict(六分代理可能=sum(r['六分代理可能'] for r in details),
                               引け同秒あり=sum(r['引け同秒の正常行数'] > 0 for r in details),
                               引け後六分あり=sum(r['引け後六分の観測可能行数'] > 0 for r in details),
                               Day=sum(r['kind']=='Day' for r in details), Night=sum(r['kind']=='Night' for r in details)),
                  観測資格='有限の場内CurrentPriceTime代理、正のLastとbid/ask、bid<=ask、原行順で非逆行。表示数量や受信時刻は保存五列にない。',
                  代理精算='ユーザー指定の直前六分以内の最終正常BBOを終値の代用にできるかだけを判定。15:45/06:00で本当に約定したとはしない。',
                  source_npz_reads=40, source_arrays=list(KEYS), original_book_tail_reads=1,
                  original_book_full_reads=0, API=0, financial_replays=0)
    save(HERE/'TOPIX四十場の引け前六分と原板末尾.json', result)
    save(HERE/'所有気配入力目録.json', dict(sessions=meta['sessions'], inputs=copies,
                                         arrays=['quotes__'+k for k in KEYS],
                                         source_manifest=result['source_manifest'],
                                         purpose='原板や元金融台帳を再読せず、元と同値のquotes五列だけを次の固定金融で使う。',
                                         numerical_reads=40, financial_replays=0, API=0))
    lines = ['# TOPIXの引け時刻と観測終点', '',
             f"指定引け同秒の正常気配は{result['summary']['引け同秒あり']}/40場。直前六分以内の代理気配は{result['summary']['六分代理可能']}/40場にある。",
             '', '価格時計を付した最後の正常BBOであり、引け注文の実約定値や真の受信時刻を証明しない。Lastを約定BBOに読み替えない。', '',
             '| セッション | 最終正常価格時計（JST） | 引けまで秒 | Last | bid / ask | 六分代理 |',
             '| --- | --- | ---: | ---: | --- | --- |']
    for row in details:
        p = row['採用可能な終端代理'] or row['最終正常行']
        lines.append(f"| {row['session']} | {p['JST'] if p else 'なし'} | {row['引けまでの秒差']} | {p['Last'] if p else '—'} | {str(p['bid'])+' / '+str(p['ask']) if p else '—'} | {'可' if row['六分代理可能'] else '不可'} |")
    lines += ['', '9/24Dayの原板末尾2MiB（1330完全行）は15:39:58まで。最終Last4056とBuy1/Sell1の4062同値気配は別の値。15:45のLastを新たに示す行はこの末尾にはない。',
              '', '[全検査JSON](TOPIX四十場の引け前六分と原板末尾.json) / [次工程用の所有気配目録](所有気配入力目録.json)']
    (HERE/'観測終点と六分代理.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(passed=True, summary=result['summary'],
                          minimum_gap=min(r['引けまでの秒差'] for r in details if r['六分代理可能']),
                          maximum_gap=max(r['引けまでの秒差'] for r in details if r['六分代理可能']),
                          missing=[r['session'] for r in details if not r['六分代理可能']],
                          manifest= 'work/stability122_20261017/coverage/所有気配入力目録.json',
                          manifest_sha256=digest((HERE/'所有気配入力目録.json').read_bytes()),
                          proof_sha256=digest((HERE/'TOPIX四十場の引け前六分と原板末尾.json').read_bytes())), ensure_ascii=False))


if __name__ == '__main__':
    main()
