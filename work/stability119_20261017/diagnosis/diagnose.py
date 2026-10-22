"""事前に読む範囲を固定し、完成後の保存結果だけで119の損失と勝ちを対照する。"""

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
OWNER = HERE.parent
ROOT = OWNER.parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(OWNER))
import plan119

PLAN = HERE / '損失上位と勝ち対照の保存cache限定読取計画.json'
RESULT = OWNER / 'recovery119/戦略自動選択と全四十場の復元結果.json'
JST = timezone(timedelta(hours=9))
REASONS = {1: '値幅損切り', 2: '固定値幅利確', 3: '順行後のトレーリング',
           4: '家族の反証退出', 5: '場損失予算', 6: '場利益停止', 7: '場末返済', 8: '半分利確'}


def digest(payload: bytes) -> str:
    """
    機能: 一度読んだbytesの同一性を確認する。
    引数: payload(bytes) は源又は許可された保存ファイル。
    返り値: str はSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def primitive(value: object) -> object:
    """
    機能: 未知をnullとして有限なJSON原始型へ変換する。
    引数: value(object) は合成又は保存結果から得た値。
    返り値: object はdict/list又はJSON原始型。未知の価格を0へ変えない。
    """
    if isinstance(value, dict):
        return {str(k): primitive(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [primitive(v) for v in value]
    if isinstance(value, np.ndarray):
        return primitive(value.tolist())
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def save(path: Path, value: dict) -> None:
    """
    機能: 所有域に新しい証跡だけを保存する。
    引数: path(Path)、value(dict) は出力先と有限化する値。
    返り値: None。既存結果や原市場を更新しない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(primitive(value), ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def clock(value: float) -> str | None:
    """
    機能: 価格時計を日本時間で表示する。
    引数: value(float) は保存epoch秒。
    返り値: str|None は時刻。実受信時刻と呼ばない。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat() if math.isfinite(float(value)) else None


def prepare() -> None:
    """
    機能: 結果を見る前に対象の選び方と読取上限を固定する。
    引数: なし。市場値・完成結果・cacheは読まない。
    返り値: None。根の結果SHA解除後だけexecuteを使える計画を保存する。
    """
    save(PLAN, dict(状態='未測定の読取準備', 金融=0, 原市場=0, 既金融結果=0, API=0,
        source_SHA256=plan119.sources(), 診断源SHA256=digest(Path(__file__).read_bytes()),
        結果=str(RESULT.relative_to(ROOT)),
        接続訂正='根の登録形式修正後sourceへ再束縛。金融再生なしの完成会計復元結果を根指定SHAで読む。旧準備計画と源はarchive保全。',
        対象='各商品につき選択6で固定された単体先頭とPORT。候補を選び直さない。',
        場選定='それぞれnet<0の最悪3場、net>0の最大1場。同値はsession昇順。和集合最大16scene-symbol。',
        cache読取='和集合のprepared一回、PORT対象がある場のportfolio一回。元市場は再読しない。',
        親選定='赤字対象は完結親net下位3、勝ち対照は上位3。全親集計と別に示す。',
        算術='新規/返済BBO、親net/各注文floor料、当時までの前1/5/20分、保有中の反対気配値幅と部分清算後の親局所資産。',
        欠測='返済判断原rowは台帳未保存。返済時計−保存lagは価格時計としてのみ示し原rowを補完しない。',
        禁止='損失親を事後削除した新成績、再金融、原NPZ/API、補充/主体/真受信順の断定を行わない。',
        上限=dict(scene_symbol=16, prepared_reads=16, portfolio_reads=8, result_reads=1)))
    print(json.dumps(dict(準備=True, 結果本文読取=0, cache本文読取=0, 計画=str(PLAN)), ensure_ascii=False))


def targets(result: dict) -> list[dict]:
    """
    機能: 結果前に決めた基準だけで負けと勝ちの読取対象を選ぶ。
    引数: result(dict) は根が解除した保存結果。
    返り値: list[dict] は最大16場商品と、それぞれに必要な方法と役割。
    """
    picked = {}
    for symbol in ('TOPIX', 'NK225'):
        chosen = result['selection'][symbol]['chosen']
        methods = [('PORT', result['portfolios'])]
        if chosen:
            methods.append((chosen[0], result['runs']))
        for mid, rows in methods:
            pool = [r for r in rows if r['symbol'] == symbol and r['method'] == mid]
            red = sorted([r for r in pool if r['net'] < 0], key=lambda r: (r['net'], r['session']))[:3]
            green = sorted([r for r in pool if r['net'] > 0], key=lambda r: (-r['net'], r['session']))[:1]
            for role, group in (('赤字上位', red), ('勝ち反証', green)):
                for rank, item in enumerate(group, 1):
                    key = (symbol, item['session'])
                    record = picked.setdefault(key, dict(symbol=symbol, session=item['session'], methods=[]))
                    record['methods'].append(dict(id=mid, role=role, rank=rank, saved_summary=item))
    assert len(picked) <= 16
    return sorted(picked.values(), key=lambda r: (r['symbol'], r['session']))


def quote_at(quotes: dict, row: int) -> dict:
    """
    機能: 保存済み正常気配から約定原rowを一意に照合する。
    引数: quotes(dict)、row(int) は正常気配列と保存原row。
    返り値: dict は価格時計と最良気配・数量。補充状況は観測しない。
    """
    indexes = np.flatnonzero(quotes['row'] == row)
    assert len(indexes) == 1
    i = int(indexes[0])
    assert 0 < quotes['bid'][i] < quotes['ask'][i]
    return dict(raw_row=row, price_time_s=float(quotes['time'][i]), 価格時計=clock(quotes['time'][i]),
                bid=float(quotes['bid'][i]), ask=float(quotes['ask'][i]),
                bid_quantity=float(quotes['bq'][i]), ask_quantity=float(quotes['aq'][i]))


def parent_detail(legs: np.ndarray, bars: dict, quotes: dict, spec: dict,
                  quantity: int, symbol: str) -> dict:
    """
    機能: 同じ実親の全脚から価格経路・費用・退出理由を因果資料として射影する。
    引数: legs(float[M,16])、bars/quotes/spec(dict)、quantity(int)、symbol(str)。
    返り値: dict は事後の親診断。改善後損益や入口成功率を計算しない。
    """
    legs = legs[np.argsort(legs[:, 2], kind='stable')]
    first = legs[0]
    side, entry_row, exit_row = int(first[5]), int(first[1]), int(legs[-1, 2])
    entry_price, ebar = float(first[7]), int(first[14])
    mult, fee = (1000., 41.8) if symbol == 'TOPIX' else (10., 11.)
    assert np.all(legs[:, 1] == entry_row) and np.all(legs[:, 5] == side)
    assert np.all(legs[:, 7] == entry_price) and 0 <= ebar < len(bars['valid'])
    closed = int(legs[:, 6].sum())
    assert 0 < closed <= quantity
    complete = closed == quantity
    entry_quote = quote_at(quotes, entry_row)
    if spec['entry_mode'] == 0:
        assert entry_price == entry_quote['ask' if side == 1 else 'bid']
    else:
        assert entry_quote['ask'] <= entry_price + 1e-8 if side == 1 else entry_quote['bid'] >= entry_price - 1e-8
    exits = []
    for leg in legs:
        q = int(leg[6])
        quote = quote_at(quotes, int(leg[2]))
        assert float(leg[8]) == quote['bid' if side == 1 else 'ask']
        gross = side * (float(leg[8]) - entry_price) * q * mult
        inf = math.floor(quantity * fee + 1e-9) * q / quantity
        outf = math.floor(q * fee + 1e-9)
        assert abs(float(leg[9]) - gross) <= 1e-5
        assert abs(float(leg[10]) - inf) <= 1e-5 and float(leg[11]) == outf
        assert abs(float(leg[12]) - gross + inf + outf) <= 1e-5
        exits.append(dict(quantity=q, quote=quote, price=float(leg[8]), gross=gross,
                          allocated_entry_fee=inf, exit_fee=outf, net=float(leg[12]),
                          reason=int(leg[13]), 理由=REASONS.get(int(leg[13]), '未定義'),
                          返済判断価格時計=clock(float(leg[4]) - float(leg[15])),
                          返済判断原row=None, 判断から約定までの価格時計差=float(leg[15])))
    qi = np.flatnonzero((quotes['row'] >= entry_row) & (quotes['row'] <= exit_row))
    paths = side * ((quotes['bid'][qi] if side == 1 else quotes['ask'][qi]) - entry_price)
    peak_at, trough_at = int(np.argmax(paths)), int(np.argmin(paths))
    cash, held, local, next_leg = -math.floor(quantity * fee + 1e-9), quantity, [], 0
    for i in qi:
        qr = int(quotes['row'][i])
        while next_leg < len(legs) and int(legs[next_leg, 2]) <= qr:
            leg = legs[next_leg]
            cash += float(leg[9] - leg[11])
            held -= int(leg[6])
            next_leg += 1
        xp = float(quotes['bid'][i] if side == 1 else quotes['ask'][i])
        local.append(cash + side * (xp - entry_price) * held * mult - math.floor(held * fee + 1e-9))
    if complete:
        assert abs(local[-1] - legs[:, 12].sum()) <= 1e-5
    prior = {}
    for minutes in (1, 5, 20):
        good = ebar >= minutes and bool(bars['valid'][ebar-minutes:ebar+1].all())
        prior[str(minutes)] = float(bars['close'][ebar] - bars['close'][ebar-minutes]) if good else None
    return dict(parent=int(first[0]), 完結=complete, side=side, 売買='買い' if side == 1 else '売り',
                initial_quantity=quantity, closed_quantity=closed, entry_quote=entry_quote, entry_price=entry_price,
                公開原row=int(bars['pub_raw_row'][ebar]), 公開価格時計=clock(bars['pub_price_time_s'][ebar]),
                公開anchor=float(bars['anchor'][ebar]), 公開時幅=float(spec['width']),
                前の確定足終値差=prior, 親net=float(legs[:, 12].sum()), exits=exits,
                順行最大価格幅=float(paths[peak_at]), 逆行最大価格幅=float(paths[trough_at]),
                順行最大気配=quote_at(quotes, int(quotes['row'][qi[peak_at]])),
                最大順行から最後返済まで戻り幅=float(paths[peak_at] - paths[-1]),
                部分返済と費用込み親局所資産最大=float(max(local)),
                部分返済と費用込み親局所資産最小=float(min(local)),
                留保='保有経路は事後診断。順行極値をその場で利確できたとの成績ではない。')


def execute(expected_sha: str) -> None:
    """
    機能: 根指定SHAの完成結果を一読し、選定済みcacheを各一読で診断する。
    引数: expected_sha(str) は根が完成後に解除した結果SHA256。
    返り値: None。原市場・原API・新金融・再政策実行を伴わない。
    """
    prepared = json.loads(PLAN.read_text(encoding='utf-8'))
    assert prepared['source_SHA256'] == plan119.sources()
    assert prepared['診断源SHA256'] == digest(Path(__file__).read_bytes())
    assert len(expected_sha) == 64 and not (HERE / 'completed').exists()
    payload = RESULT.read_bytes()
    assert digest(payload) == expected_sha
    (HERE / 'completed').mkdir()
    (HERE / 'completed/根指定結果の一読保全.json').write_bytes(payload)
    result = json.loads(payload)
    chosen = targets(result)
    save(HERE / 'completed/本文読取前の対象固定.json', dict(結果SHA256=expected_sha, targets=chosen, scene_symbol=len(chosen)))
    read_log, details = [], []
    for target in chosen:
        symbol, scene = target['symbol'], target['session']
        meta = next(c for c in result['cache'] if c['symbol'] == symbol and c['session'] == scene)
        blob = (ROOT / meta['path']).read_bytes()
        assert digest(blob) == meta['SHA256']
        with np.load(BytesIO(blob), allow_pickle=False) as stored:
            bars = {k[6:]: stored[k].copy() for k in stored.files if k.startswith('bars__')}
            quotes = {k[8:]: stored[k].copy() for k in stored.files if k.startswith('quotes__')}
            all_ledger = stored['ledger'].copy()
            widths = stored['policies__width'].copy()
        read_log.append(dict(path=meta['path'], SHA256=meta['SHA256'], reads=1, kind='prepared'))
        port_ledger = None
        if any(m['id'] == 'PORT' for m in target['methods']):
            pm = next(c for c in result['portfolio_cache'] if c['symbol'] == symbol and c['session'] == scene)
            blob = (ROOT / pm['path']).read_bytes()
            assert digest(blob) == pm['SHA256']
            with np.load(BytesIO(blob), allow_pickle=False) as stored:
                port_ledger = stored['ledger'].copy()
            read_log.append(dict(path=pm['path'], SHA256=pm['SHA256'], reads=1, kind='portfolio'))
        for method in target['methods']:
            mid = method['id']
            if mid == 'PORT':
                ledger = port_ledger
                ids = result['selection'][symbol]['chosen']
                quantities = (4, 3, 3) if symbol == 'TOPIX' else (8, 6, 6)
                by_slot = {i: (v, quantities[i]) for i, v in enumerate(ids)}
            else:
                k = next(i for i, s in enumerate(result['specs']) if s['id'] == mid)
                ledger = all_ledger[all_ledger[:, 0] == k].copy()
                by_slot = {k: (mid, 10 if symbol == 'TOPIX' else 20)}
            parents = []
            for slot in sorted(by_slot):
                method_id, quantity = by_slot[slot]
                k = next(i for i, s in enumerate(result['specs']) if s['id'] == method_id)
                spec = result['specs'][k]
                rows = ledger[ledger[:, 0] == slot, 1:]
                for parent in np.unique(rows[:, 0]):
                    legs = rows[rows[:, 0] == parent]
                    b = int(legs[0, 14])
                    parents.append(dict(slot=slot, method=method_id,
                        **parent_detail(legs, bars, quotes, dict(spec, width=float(widths[k, b])), quantity, symbol)))
            summary = method['saved_summary']
            assert abs(sum(p['親net'] for p in parents) - summary['profit'] + summary['loss']) <= 1e-4
            eligible = [p for p in parents if p['親net'] > 0] if method['role'] == '勝ち反証' else [p for p in parents if p['親net'] < 0]
            order = sorted(eligible, key=lambda p: (p['親net'], p['slot'], p['parent']),
                           reverse=method['role'] == '勝ち反証')[:3]
            details.append(dict(symbol=symbol, session=scene, **method,
                台帳親数=len(parents), 完結親数=sum(p['完結'] for p in parents),
                全脚net=sum(p['親net'] for p in parents), 注目親=order,
                親一覧=[{k: p[k] for k in ('slot', 'parent', 'method', '完結', '親net')} for p in parents]))
    assert len({i['path'] for i in read_log}) == len(read_log)
    assert prepared['source_SHA256'] == plan119.sources()
    save(HERE / 'completed/選択単体と三枠の負け上位及び勝ち対照の具体診断.json',
         dict(全合格=True, 結果SHA256=expected_sha, 原市場再読=0, 新金融=0, API=0,
              source_SHA256=prepared['source_SHA256'], 診断源SHA256=prepared['診断源SHA256'],
              read_log=read_log, details=details,
              留保='最大損失原因は事後資料。ここでの親や場の削除は新手法損益ではない。価格時計は受信時計でない。'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='119の結果完成前に読取範囲を固定し、解除後のみ保存cacheを診断する。')
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--root-execute', action='store_true')
    parser.add_argument('--result-sha')
    args = parser.parse_args()
    if args.prepare:
        assert not args.root_execute and args.result_sha is None
        prepare()
    else:
        assert args.root_execute and args.result_sha
        execute(args.result_sha)
