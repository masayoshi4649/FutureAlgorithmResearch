"""保存板の直前情報と事後経路を分けて調べる。売買・金融再生は行わない。"""

from __future__ import annotations

import gzip
import hashlib
import json
import pickle
from datetime import datetime, timezone, timedelta
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[3]
OWN = Path(__file__).resolve().parent
POLICY = 'E01_DAILY_P1_L8'
TICK = {'TOPIX': .5, 'NK225': 10.}
TZ = timezone(timedelta(hours=9))


def digest(path: Path) -> str:
    """
    機能: 保存入力の内容指紋を求める。
    引数: path(Path)は読取専用の入力位置。
    返り値: strはSHA256。原本板はこの関数へ渡さない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name: str, value: dict) -> None:
    """
    機能: 私有領域へ日本語の診断証跡を保存する。
    引数: name(str)はファイル名、value(dict)は有限値またはnullの診断。
    返り値: None。売買結果や既存資料を変更しない。
    """
    (OWN/name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def stamp(value: float) -> str | None:
    """
    機能: 原価格時計を日本時間へ整形する。
    引数: value(float)は価格時計の秒。
    返り値: str|Noneは価格時計表示。受信時刻とは呼ばない。
    """
    return datetime.fromtimestamp(float(value), TZ).isoformat() if np.isfinite(value) else None


def finite(value: float) -> float | None:
    """
    機能: 非有限値を未知として保持する。
    引数: value(float)は保存配列値。
    返り値: float|NoneはJSONへ保存できる値。
    """
    return float(value) if np.isfinite(value) else None


def highs(a: dict) -> np.ndarray:
    """
    機能: 同一価格時計の後続行を使わない最初の新最大時計行を作る。
    引数: a(dict[str,ndarray])は原行順を保持した保存板。
    返り値: ndarray[int]は新最大時計を最初に公表した原行位置。
    """
    t = np.where(a['price_time_valid'], a['price_time_s'], -np.inf)
    previous = np.r_[-np.inf, np.maximum.accumulate(t)[:-1]]
    return np.flatnonzero(np.isfinite(t) & (t > previous))


def peer_direction(peer: dict, event_time: float, side: int, tick: float) -> dict:
    """
    機能: 相手の厳密過去の最初の新最大時計に限り、直前30秒の両気配を比較する。
    引数: peer(dict)は保存板、event_time(float)、side(int)、tick(float)。
    返り値: dictは支持・反対・中立・曖昧・未知と、その当時の原行根拠。
    """
    ix = peer['_highs']; ts = peer['price_time_s'][ix]
    k = int(np.searchsorted(ts, event_time, side='left'))-1
    out = {'判定': '未知', '理由': None, '相手終端原seq': None, '相手終端時刻': None}
    if k < 0:
        out['理由'] = '厳密過去の価格時計なし'; return out
    end = int(ix[k]); now = float(ts[k])
    out.update(相手終端原seq=int(peer['raw_seq'][end]), 相手終端時刻=stamp(now), 価格時計の古さ秒=event_time-now)
    if event_time-now > 15 or not peer['price_row_valid'][end]:
        out['理由'] = '相手価格時計が15秒超または終端気配不正'; return out
    j = int(np.searchsorted(ts, now-30, side='right'))-1
    if j < 0:
        out['理由'] = '30秒前の価格時計なし'; return out
    begin = int(ix[j]); gap = now-30-float(ts[j])
    out.update(相手始点原seq=int(peer['raw_seq'][begin]), 相手始点時刻=stamp(ts[j]), 始点不足秒=gap)
    if gap > 15 or not peer['price_row_valid'][begin]:
        out['理由'] = '始点が15秒超または気配不正'; return out
    segment = np.arange(begin+1, end+1)
    if np.any(peer['price_reset_reason'][segment] & (2 | 4 | 8 | 16)):
        out['理由'] = '窓内の時計または原seq断絶'; return out
    db = side*(float(peer['bid'][end])-float(peer['bid'][begin]))/tick
    da = side*(float(peer['ask'][end])-float(peer['ask'][begin]))/tick
    spread = (peer['ask'][end]-peer['bid'][end])-(peer['ask'][begin]-peer['bid'][begin])
    out.update(方向付きbid進行tick=db, 方向付きask進行tick=da)
    if db*da < 0 or spread > 0:
        out['判定'] = '曖昧'
    elif min(db, da) >= 1:
        out['判定'] = '支持'
    elif max(db, da) <= -1:
        out['判定'] = '反対'
    else:
        out['判定'] = '中立'
    return out


def quantity_path(a: dict, indexes: np.ndarray, tick: float, side: int) -> dict:
    """
    機能: 十段内で連続観測した同価格の表示減少・追加・減少後回復を測る。
    引数: a(dict)、indexes(ndarray[int])は当時までの原行、tick(float)、side(int)。
    返り値: dictは表示量の厚さ正規化値。約定・取消の識別や十段外の推定を行わない。
    """
    output = {}; good = a['depth_valid'][indexes]
    coverage = float(np.mean(good)) if len(good) else 0.
    for label, prefix in (('買板', 'bid'), ('売板', 'ask')):
        med = float(np.median(a[prefix+'_qty'][indexes[good]])) if np.any(good) else 0.
        deficit = {}; adds = removes = recovery = 0.; changes = transitions = 0
        for pos in range(1, len(indexes)):
            old, new = int(indexes[pos-1]), int(indexes[pos])
            if new != old+1 or not a['depth_transition_valid'][new]:
                deficit.clear(); continue
            transitions += 1
            prev = dict(zip(a[prefix+'_prices'][old].tolist(), a[prefix+'_quantities'][old].tolist()))
            current = dict(zip(a[prefix+'_prices'][new].tolist(), a[prefix+'_quantities'][new].tolist()))
            deficit = {price: amount for price, amount in deficit.items() if price in current and price in prev}
            mid = .5*(float(a['bid'][new])+float(a['ask'][new]))
            for price in current.keys() & prev.keys():
                delta = current[price]-prev[price]
                if delta == 0:
                    continue
                changes += 1; weight = 1./(1.+abs(price-mid)/tick)
                if delta < 0:
                    removes += -delta*weight; deficit[price] = deficit.get(price, 0.)-delta
                else:
                    adds += delta*weight
                    restored = min(delta, deficit.get(price, 0.)); recovery += restored*weight
                    deficit[price] = max(0., deficit.get(price, 0.)-restored)
        output[label] = {'厚さ分母_最良表示量中央値': med, '有効連続更新': transitions, '同価格数量変更': changes,
            '追加_距離重み量': adds, '減少_距離重み量': removes, '減少後回復_距離重み量': recovery,
            '追加_厚さ比': adds/med if med else None, '減少_厚さ比': removes/med if med else None,
            '減少後回復_厚さ比': recovery/med if med else None}
    supporting, opposite = ('買板', '売板') if side > 0 else ('売板', '買板')
    sr, rr = output[supporting]['減少後回復_厚さ比'], output[opposite]['減少後回復_厚さ比']
    output.update(十段正常行率=coverage, 支持側=supporting, 反対側=opposite,
        反対板回復優勢=(rr > sr and rr > 0.) if coverage >= .5 and sr is not None and rr is not None else None)
    return output


def volume_path(a: dict, indexes: np.ndarray, event_time: float, side: int) -> dict:
    """
    機能: 観測累計差と最終価格による一意な方向代理を分けて集計する。
    引数: a(dict)、indexes(ndarray[int])、event_time(float)、side(int)。
    返り値: dictは直前二つの15秒量と分類被覆。真の売買別約定量ではない。
    """
    half = []
    for lo, hi, lower_open in ((event_time-30, event_time-15, True), (event_time-15, event_time, True)):
        rows = indexes[(a['price_time_s'][indexes] > lo) & (a['price_time_s'][indexes] <= hi)]
        total = same = opposite = classified = 0.; unknown = 0
        for i in rows.tolist():
            if i == 0 or not a['volume_delta_usable'][i]:
                unknown += 1; continue
            delta = float(a['volume_delta'][i])
            if not np.isfinite(delta) or delta < 0:
                unknown += 1; continue
            total += delta
            direction = 0
            if delta > 0 and a['volume_time_s'][i] == a['price_time_s'][i] and a['price_transition_valid'][i]:
                if a['last'][i] >= a['ask'][i-1]:
                    direction = 1
                elif a['last'][i] <= a['bid'][i-1]:
                    direction = -1
            if direction:
                classified += delta
                if direction == side:
                    same += delta
                else:
                    opposite += delta
        half.append({'観測usable差合計': total, '方向一致代理量': same, '反対代理量': opposite,
            '方向代理被覆率': classified/total if total > 0 else None, '量不明行': unknown, '対象行': len(rows)})
    earlier, recent = half
    covered = all(x['方向代理被覆率'] is not None and x['方向代理被覆率'] >= .5 for x in half)
    weak = recent['方向一致代理量'] <= .5*earlier['方向一致代理量'] if covered and earlier['方向一致代理量'] > 0 else None
    return {'前15秒': earlier, '後15秒': recent, '方向代理量が半減': weak}


def past(a: dict, peer: dict, end: int, side: int, tick: float, peer_tick: float) -> dict:
    """
    機能: 指定原行で既に観測済みの直前30秒だけを測定する。
    引数: a/peer(dict)、end(int)は自己原行終端、side(int)、tick/peer_tick(float)。
    返り値: dictは固定四観点と当時の量・気配。後続の同時計行を混ぜない。
    """
    t = float(a['price_time_s'][end]); allix = np.arange(end+1)
    ix = allix[a['price_time_valid'][:end+1] & a['in_session'][:end+1] &
        (a['price_time_s'][:end+1] >= t-30) & (a['price_time_s'][:end+1] <= t)]
    old = allix[a['price_time_valid'][:end+1] & a['in_session'][:end+1] & (a['price_time_s'][:end+1] <= t-30)]
    anchor = int(old[-1]) if len(old) else -1
    goodanchor = anchor >= 0 and t-30-float(a['price_time_s'][anchor]) <= 15 and a['price_row_valid'][anchor] and a['price_row_valid'][end]
    key = 'bid' if side > 0 else 'ask'
    signed = side*(float(a[key][end])-float(a[key][anchor]))/tick if goodanchor else None
    valid = ix[a['price_row_valid'][ix]]; path = a[key][valid]
    adverse = float(np.maximum(0., -side*np.diff(path)/tick).sum()) if len(path) > 1 else None
    quantity = quantity_path(a, ix, tick, side); volume = volume_path(a, ix, t, side)
    other = peer_direction(peer, t, side, peer_tick)
    return {'原seq': int(a['raw_seq'][end]), '価格時計': stamp(t), 'bid': finite(a['bid'][end]), 'ask': finite(a['ask'][end]),
        '当時までの窓原行数': len(ix), '窓の最初原seq': int(a['raw_seq'][ix[0]]) if len(ix) else None,
        '支持気配の方向付き進行tick': signed, '支持気配の逆行積算tick': adverse,
        '自己支持気配が1tick以上後退': signed <= -1 if signed is not None else None,
        '量': quantity, '出来高': volume, '相手': other,
        '固定観点': {'相手反対': other['判定'] == '反対' if other['判定'] in ('支持', '反対', '中立') else None,
            '代理出来高半減': volume['方向代理量が半減'], '反対表示量回復優勢': quantity['反対板回復優勢'],
            '支持気配後退': signed <= -1 if signed is not None else None}}


def snapshot(a: dict, i: int) -> dict:
    """
    機能: 保存原行の十段表示をそのまま小さな証跡へ抜き出す。
    引数: a(dict)は保存板、i(int)は原行位置。
    返り値: dictは価格・数量・累計・資格。受信時刻や補間値を作らない。
    """
    return {'原seq': int(a['raw_seq'][i]), '価格時計': stamp(a['price_time_s'][i]),
        '最終価格': finite(a['last'][i]), '累計出来高': finite(a['volume'][i]), '出来高時計': stamp(a['volume_time_s'][i]),
        '観測出来高差': finite(a['volume_delta_observed'][i]), '出来高差usable': bool(a['volume_delta_usable'][i]),
        '十段正常': bool(a['depth_valid'][i]),
        '買板': [[finite(p), finite(q)] for p, q in zip(a['bid_prices'][i], a['bid_quantities'][i])],
        '売板': [[finite(p), finite(q)] for p, q in zip(a['ask_prices'][i], a['ask_quantities'][i])]}


def around(a: dict, end: int) -> dict:
    """
    機能: 判断前後30秒の原板を事後説明専用に抽出する。
    引数: a(dict)、end(int)は中心の原行。
    返り値: dictは過去・当行・未来と表示量。未来値は固定観点へ渡さない。
    """
    t = float(a['price_time_s'][end]); samples = []
    for offset in (-30, -15, -5, 0, 5, 15, 30):
        if offset == 0:
            i = end
        elif offset < 0:
            candidates = np.flatnonzero(a['price_time_valid'][:end+1] & a['in_session'][:end+1] & (a['price_time_s'][:end+1] <= t+offset))
            i = int(candidates[-1]) if len(candidates) else -1
        else:
            candidates = np.flatnonzero(a['price_time_valid'][end+1:] & a['in_session'][end+1:] & (a['price_time_s'][end+1:] >= t+offset))
            i = int(candidates[0])+end+1 if len(candidates) else -1
        samples.append({'指定差秒': offset, '区分': '事後のみ' if offset > 0 else '当時まで',
            '実差秒': float(a['price_time_s'][i])-t if i >= 0 else None,
            '板': snapshot(a, i) if i >= 0 else None})
    return {'中心原seq': int(a['raw_seq'][end]), '中心価格時計': stamp(t), '前後板': samples}


def plateau(a: dict, session: str, symbol: str) -> dict:
    """
    機能: 最終価格時計の15秒超停滞に残る原seqと板更新を数える。
    引数: a(dict)は保存全原行、session/symbol(str)は対象識別子。
    返り値: dictは時計間隙の分類と最長実例。板の実受信間隔とは解釈しない。
    """
    hi = a['_highs']; examples = []; changed = total = 0
    for j in range(1, len(hi)):
        lo, end = int(hi[j-1]), int(hi[j]); gap = float(a['price_time_s'][end]-a['price_time_s'][lo])
        if gap <= 15 or not a['in_session'][lo] or not a['in_session'][end]:
            continue
        total += 1
        ix = np.arange(lo+1, end); normal = a['price_row_valid'][ix] if len(ix) else np.empty(0, bool)
        previous = ix-1
        bbo = (a['bid'][ix] != a['bid'][previous]) | (a['ask'][ix] != a['ask'][previous])
        qty = np.any(a['bid_quantities'][ix] != a['bid_quantities'][previous], axis=1) | np.any(a['ask_quantities'][ix] != a['ask_quantities'][previous], axis=1)
        qb = int(np.sum(normal & bbo)); qq = int(np.sum(a['depth_valid'][ix] & a['depth_valid'][previous] & qty))
        if qb or qq:
            changed += 1
        examples.append({'session': session, 'symbol': symbol, '価格時計差秒': gap, '前原seq': int(a['raw_seq'][lo]),
            '次原seq': int(a['raw_seq'][end]), '前価格時計': stamp(a['price_time_s'][lo]), '次価格時計': stamp(a['price_time_s'][end]),
            '間の原行数': len(ix), '原seq連続': bool(np.all(np.diff(a['raw_seq'][lo:end+1]) == 1)),
            '間の正常気配行': int(normal.sum()), '間の気配変化': qb, '間の十段数量変化': qq})
    examples.sort(key=lambda x: (x['間の十段数量変化']+x['間の気配変化'], x['価格時計差秒']), reverse=True)
    return {'session': session, 'symbol': symbol, '15秒超時計差数': total, 'その間に板が変化した数': changed,
        '受信時刻欄あり行': int(a['received_at_present'].sum()), '原行数': len(a['raw_seq']), '代表': examples[:2]}


def rate(records: list[dict]) -> list[dict]:
    """
    機能: 固定四観点について、親勝敗と場勝敗の分母を分けて集計する。
    引数: records(list[dict])は全33場の最初の実入口のみ。
    返り値: list[dict]は既知・未知・無取引を区別する事後記述統計。
    """
    out = []
    for symbol in ('TOPIX', 'NK225'):
        entries = [x for x in records if x['symbol'] == symbol and x['実入口あり']]
        no = sum(x['symbol'] == symbol and not x['実入口あり'] for x in records)
        for event in ('紙上新規公開', '実指値到達'):
            for name in ('相手反対', '代理出来高半減', '反対表示量回復優勢', '支持気配後退'):
                for value in (True, False, None):
                    subset = [x for x in entries if x['入口'][event]['直前30秒']['固定観点'][name] is value]
                    parentwins = sum(x['初回親収支'] > 0 for x in subset); sessionwins = sum(x['場収支'] > 0 for x in subset)
                    out.append({'symbol': symbol, '入口時点': event, '固定観点': name,
                        '条件値': value, '実入口分母': len(subset), '初回親黒字件数': parentwins,
                        '初回親黒字率': parentwins/len(subset) if subset else None, '場黒字件数': sessionwins,
                        '場黒字率': sessionwins/len(subset) if subset else None, '全実入口数': len(entries), '無取引場': no})
    return out


def main() -> None:
    """
    機能: 許可済み保存会計と十段板から、金融再生なしの原因診断を一度実行する。
    引数: なし。入出力は私有領域の固定計画に記載する。
    返り値: None。入力指紋・全33分母・具体板例・時計監査を保存する。
    """
    OWN.mkdir(parents=True, exist_ok=True)
    finance_path = ROOT/'work/wave_v106/e01_daily/finance/結果.json'
    meta_paths = [ROOT/'work/wave_v103/input_v2/metadata.json', ROOT/'work/wave_v104/holdout_input/metadata.json']
    finance = json.loads(finance_path.read_text(encoding='utf-8')); policy = finance['results'][POLICY]
    accounts = {}
    for path in meta_paths:
        metadata = json.loads(path.read_text(encoding='utf-8')); assert metadata['全合格']
        accounts.update(metadata['accounts'])
    selected = {}
    for symbol in ('TOPIX', 'NK225'):
        selected[symbol] = [x['session'] for x in sorted((x for x in policy['rows'] if x['symbol'] == symbol and x['収支'] < 0), key=lambda x: x['収支'])[:3]]
    save('数量原因の事前診断計画.json', {'scope': '既知33場・政策P1L8・保存数量の事後診断のみ', '全合格': True,
        '赤字上位3': selected, '固定過去窓秒': 30, '前後参考秒': [-30,-15,-5,0,5,15,30],
        '機械的選定': '各商品の収支昇順。同額は元会計rows順を保持',
        '観点': ['相手の厳密過去30秒が両気配1tick以上反対', '方向代理量が後15秒に半減（各半分の代理被覆50%以上）',
            '同価格の減少後回復が反対板で優勢（十段正常50%以上）', '自己支持気配の直前30秒が1tick以上逆行'],
        '未来禁止': '過去観点は自己原seq以下。相手はstrict-past first-newmax。後30秒の板は説明専用',
        'NPZ': 66, '保存quote_pickle': 1, '保存政策台帳': 66, '原本追加読取': 0,
        '金融再生': 0, 'API': 0, '実装SHA256': digest(Path(__file__))})
    qpath = ROOT/'work/wave_v106/e01_reference/prepared/quotes.pkl'
    quotes = pickle.loads(qpath.read_bytes()); assert len(quotes) == 66
    ledgers = {}; input_sha = {str(finance_path.relative_to(ROOT)): digest(finance_path), str(qpath.relative_to(ROOT)): digest(qpath)}
    for path in meta_paths:
        input_sha[str(path.relative_to(ROOT))] = digest(path)
    for item in policy['ledgers']:
        path = ROOT/item['path']; actual_sha = digest(path); assert actual_sha == item['SHA256']
        ledger = pickle.loads(gzip.decompress(path.read_bytes())); key = (item['session'], item['symbol'])
        assert tuple(ledger['key']) == key; ledgers[key] = ledger; input_sha[item['path']] = actual_sha
    records = []; examples = []; clocks = []; checks = 0
    sessions = finance['sessions']
    for session in sessions:
        arrays = {}
        for symbol in ('TOPIX', 'NK225'):
            item = accounts[f'{session}|{symbol}']; path = ROOT/item['出力位置']
            sha = digest(path); assert sha == item['出力SHA256']; input_sha[str(path.relative_to(ROOT))] = sha
            with np.load(path, allow_pickle=False) as npz:
                a = {key: npz[key] for key in npz.files}
            assert len(a) == 44 and a['bid_prices'].shape == (item['raw_rows'], 10)
            assert a['ask_quantities'].shape == a['bid_prices'].shape
            assert np.all(np.diff(a['raw_seq']) == 1)
            a['_highs'] = highs(a); arrays[symbol] = a; clocks.append(plateau(a, session, symbol))
        for symbol in ('TOPIX', 'NK225'):
            a = arrays[symbol]; peer = arrays['NK225' if symbol == 'TOPIX' else 'TOPIX']; ledger = ledgers[(session,symbol)]
            q = quotes[(session,symbol)]; other_tick = TICK['NK225' if symbol == 'TOPIX' else 'TOPIX']
            entryorders = ledger['orders'][ledger['orders'][:,7] == 1]
            normal_order = []
            for row in ledger['orders']:
                n = int(row[0]); rawseq = int(q['seq'][n]); raw = int(np.searchsorted(a['raw_seq'], rawseq))
                assert a['raw_seq'][raw] == rawseq and a['price_time_s'][raw] == q['time_s'][n]
                assert a['bid'][raw] == q['bid'][n] and a['ask'][raw] == q['ask'][n]
                checks += 1; normal_order.append(raw)
            def event(orderrow: int, side: int) -> dict:
                """
                機能: 保存正常行を原seqへ対応し、当時過去と原板を記録する。
                引数: orderrow(int)は旧正常行、side(int)は親方向。
                返り値: dictは原行一致の入口・停止時点診断。
                """
                nonlocal checks
                seq = int(q['seq'][orderrow]); raw = int(np.searchsorted(a['raw_seq'], seq))
                assert a['raw_seq'][raw] == seq and a['price_time_s'][raw] == q['time_s'][orderrow]
                assert a['bid'][raw] == q['bid'][orderrow] and a['ask'][raw] == q['ask'][orderrow]
                checks += 1
                return {'正常行': orderrow, '原行位置': raw, '直前30秒': past(a,peer,raw,side,TICK[symbol],other_tick), '板推移': around(a,raw)}
            record = {'session': session, 'symbol': symbol, '場収支': ledger['summary']['収支'], '実入口あり': bool(len(entryorders))}
            if len(entryorders):
                first = entryorders[0]; cid = int(first[2]); parent = next(x for x in ledger['parent'] if x['親'] == cid)
                record.update(初回親=cid, 初回方向=int(first[3]), 初回親収支=parent['収支'],
                    入口={'紙上新規公開': event(int(first[1]), int(first[3])), '実指値到達': event(int(first[0]), int(first[3]))})
            records.append(record)
            if session in selected[symbol]:
                negatives = sorted((x for x in ledger['parent'] if x['収支'] < 0), key=lambda x: x['新規行'])
                parent = negatives[0]; cid = parent['親']; first = next(x for x in entryorders if int(x[2]) == cid); side = int(first[3])
                control = ledger['control']; assert control['発動'] and control['種別'] == '損失予算'
                events = {'紙上新規公開': event(int(first[1]),side), '実指値到達': event(int(first[0]),side),
                    '最初の損失親の返済': event(int(parent['最終返済行']),side), '場の損失停止判断': event(int(control['判断行']),side)}
                rows = ledger['orders'][ledger['orders'][:,2] == cid]
                examples.append({'session':session,'symbol':symbol,'場収支':ledger['summary']['収支'],
                    '最初の損失親': parent, '対象実注文': rows.tolist(), '場停止':control, '時点':events,
                    '注意':'損失親を結果から選んだ事後説明。全33最初の実入口対照とは母集団が違う。'})
        print(session, '保存板2口座完了', flush=True)
    save('板数量と直前30秒の全33対照.json', {'全合格': True, 'scope': '全33場の初回実入口のみ・政策P1L8・事後診断',
        '場数':33,'商品場数':len(records),'入力対応検査':checks,'赤字例':selected,'対照':rate(records),'全場':records,
        '数量限界':['同価格表示量の回復は補充の観測代理。取消と約定は識別不能',
            '十段外へ出た価格の数量を減少と見なさず、戻った数量を補充と見なさない',
            '出来高の方向は最後の価格の代理。累計差全量の真の買い売り内訳ではない',
            '30秒はCurrentPriceTime基準。受信時刻ではなく板更新の実間隔を保証しない',
            '少数既知場の関連であり、将来勝率・因果的予測改善や新入口の損益ではない',
            '親黒字率と場黒字率は異なる。無取引を勝ちへ含めない'],
        '入力SHA256':input_sha,'実装SHA256':digest(Path(__file__)),'金融再生':0,'API':0,'原本追加読取':0})
    save('赤字上位3の本物の数量と原板推移.json', {'全合格':True,'scope':'両商品3場ずつ・最初の負け親・事後説明専用',
        '例':examples,'入力対応検査':checks,'入力SHA256':input_sha,'実装SHA256':digest(Path(__file__)),
        '金融再生':0,'API':0,'原本追加読取':0})
    save('価格時計の間に続いた板更新.json', {'全合格':True,'scope':'保存66NPZの価格時計と原seq・数量の監査',
        '全口座':clocks,'価格時計15秒超間隙':sum(x['15秒超時計差数'] for x in clocks),
        'うち間の板変化あり':sum(x['その間に板が変化した数'] for x in clocks),
        '受信時刻欄あり行':sum(x['受信時刻欄あり行'] for x in clocks),
        '結論限界':'価格時計間隙と板更新欠落は同一ではない。受信時刻値を持たないため、板が実時刻でどの秒に来たかは復元できない。',
        '原seq限界':'連続番号は保存行の順番。ネットワーク受信の欠落がなかったことの証明ではない。',
        '入力SHA256':input_sha,'実装SHA256':digest(Path(__file__)), '金融再生':0,'API':0,'原本追加読取':0})
    print('全33数量診断終端合格', flush=True)


if __name__ == '__main__':
    main()
