"""日経オプションの保存時計と気配資格を診断する。金融再生や注文は行わない。"""

import gzip
import csv
import hashlib
import json
import math
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT.parent / 'JP_OSE_Data' / 'op'
JST = ZoneInfo('Asia/Tokyo')


def sampled_lines(path):
    """
    機能: 原JSONLの先頭・末尾・等間隔バイト位置から重複のない最大9行を読む。
    引数: path(Path)は原JSONL又はgzipのみがある場合の圧縮ファイル。
    返り値: list[tuple[int, bytes]]は元ファイル内バイト位置と原行。gzip時は先頭のみ。
    """
    if path.suffix == '.gz':
        with gzip.open(path, 'rb') as stream:
            return [(0, stream.readline())]
    size = path.stat().st_size
    result = {}
    with path.open('rb') as stream:
        for part in range(9):
            if part == 8:
                stream.seek(max(0, size - 65536))
                if stream.tell():
                    stream.readline()
                while True:
                    position = stream.tell()
                    raw = stream.readline()
                    if not raw:
                        break
                    if raw.strip():
                        result[position] = raw
                if result:
                    last = max(result)
                    result = {key: value for key, value in result.items()
                              if key < max(0, size - 65536) or key == last}
                continue
            stream.seek(size * part // 8)
            if stream.tell():
                stream.readline()
            position = stream.tell()
            raw = stream.readline()
            if raw.strip():
                result[position] = raw
    # 小ファイルの末尾走査で中間サンプルを落とさないよう先頭も必ず残す。
    with path.open('rb') as stream:
        first = stream.readline()
        if first.strip():
            result[0] = first
    return sorted(result.items())


def valid_number(value):
    """
    機能: JSON数値が有限かを調べる。
    引数: value(object)は対象値。
    返り値: boolは有限数値の場合に真。
    """
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def quote(row):
    """
    機能: Buy1を売却側、Sell1を購入側として正常な最良気配を抽出する。
    引数: row(dict)は保存原板。
    返り値: tuple[float,float]又はNone。正の数量と0<bid<askを要求する。
    """
    buy, sell = row.get('Buy1') or {}, row.get('Sell1') or {}
    bid, ask = buy.get('Price'), sell.get('Price')
    values = (bid, ask, buy.get('Qty'), sell.get('Qty'))
    if all(valid_number(v) for v in values) and 0 < bid < ask and values[2] > 0 and values[3] > 0:
        return float(bid), float(ask)
    return None


def clock_paths(value, prefix=''):
    """
    機能: 時刻・順序の保存項目候補を再帰的に列挙する。
    引数: value(object)はJSON、prefix(str)は階層パス。
    返り値: list[str]はtime/date/received/sequenceを含むキーのパス。
    """
    result = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f'{prefix}.{key}' if prefix else key
            if any(word in key.lower() for word in ('time', 'date', 'receive', 'sequence', 'seqno', 'timestamp')):
                result.append(path)
            result.extend(clock_paths(child, path))
    return result


def session_bounds(session):
    """
    機能: ファイルの場名から当該場の名目範囲を計算する。
    引数: session(str)はYYYY-MM-DD_Day/Night。
    返り値: tuple[datetime,datetime]は日本時間の名目開始・終了。
    """
    date, kind = session.split('_')
    day = datetime.fromisoformat(date).replace(tzinfo=JST)
    if kind == 'Day':
        return day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=45)
    return day + timedelta(hours=17), day + timedelta(days=1, hours=6)


def scan():
    """
    機能: 全オプションファイルの限定標本で保存時計・気配・計算値の資格を診断する。
    引数: なし。DATA配下を読み取り専用で参照する。
    返り値: dictはファイル・場別診断、限界、証拠行。金融損益を計算しない。
    """
    paths = sorted(DATA.glob('*/*.jsonl'))
    paths.extend(sorted(path for path in DATA.glob('*/*.jsonl.gz') if not path.with_suffix('').exists()))
    files, samples, examples = [], [], []
    totals, clock_keys = Counter(), Counter()
    by_session = {}
    for path in paths:
        session = path.parent.name
        start, end = session_bounds(session)
        rows = []
        digest = hashlib.sha256()
        for position, raw in sampled_lines(path):
            digest.update(str(position).encode() + b'\0' + raw)
            row = json.loads(raw)
            clock_keys.update(clock_paths(row))
            q = quote(row)
            trade_at = row.get('CurrentPriceTime')
            trade_in_session = False
            if trade_at:
                stamp = datetime.fromisoformat(trade_at)
                trade_in_session = start <= stamp <= end
            contract = re.search(r'_(\d{6})_([CP])_(\d+)\.jsonl', path.name)
            sample = dict(session=session, file=path.name, byte=position,
                          expiry=contract.group(1), kind=contract.group(2), strike=int(contract.group(3)),
                          trade_at=trade_at, volume_at=row.get('TradingVolumeTime'),
                          trade_in_session=trade_in_session, quote=q,
                          spread=(q[1]-q[0]) if q else None,
                          relative_spread=((q[1]-q[0])/((q[1]+q[0])/2)) if q else None,
                          iv=row.get('IV'), delta=row.get('Delta'), gamma=row.get('Gamma'),
                          theta=row.get('Theta'), vega=row.get('Vega'), last=row.get('CurrentPrice'),
                          clock_fields=clock_paths(row), key_count=len(row))
            rows.append((row, sample))
            samples.append(sample)
            totals['sample_count'] += 1
            totals['valid_bbo'] += int(q is not None)
            totals['trade_clock_null'] += int(not trade_at)
            totals['trade_clock_in_session'] += int(trade_in_session)
            totals['finite_iv'] += int(valid_number(row.get('IV')))
            if q:
                totals['bbo_spread_le_10pct'] += int(sample['relative_spread'] <= .10)
                totals['bbo_spread_gt_50pct'] += int(sample['relative_spread'] > .50)
        for (a, sa), (b, sb) in zip(rows, rows[1:]):
            totals['adjacent_sample_pairs'] += 1
            same = (a.get('CurrentPriceTime') == b.get('CurrentPriceTime')
                    and a.get('TradingVolumeTime') == b.get('TradingVolumeTime'))
            if same:
                totals['same_price_volume_clock_pairs'] += 1
                greek = any(a.get(key) != b.get(key) for key in ('IV','Delta','Gamma','Theta','Vega'))
                bbo = any(a.get(key) != b.get(key) for key in ('Buy1','Sell1'))
                totals['same_clocks_greek_changed'] += int(greek)
                totals['same_clocks_bbo_changed'] += int(bbo)
                if (greek or bbo) and (len(examples) < 4 or session >= '2026-10-22_Night' and len(examples) < 12):
                    examples.append(dict(file=str(path.relative_to(ROOT.parent)), before=sa, after=sb))
        stat = path.stat()
        files.append(dict(path=str(path.relative_to(ROOT.parent)), bytes=stat.st_size,
                          modified_ns=stat.st_mtime_ns, sampled_sha256=digest.hexdigest(), samples=len(rows),
                          sample_only=True))
        target = by_session.setdefault(session, dict(files=0, bytes=0, sample_count=0, valid_bbo=0,
                                trade_clock_in_session=0, finite_iv=0, bbo_spread_le_10pct=0,
                                bbo_spread_gt_50pct=0, strikes={'C': [], 'P': []}, expiries=[]))
        target['files'] += 1
        target['bytes'] += stat.st_size
        for _, s in rows:
            target['sample_count'] += 1
            target['valid_bbo'] += int(s['quote'] is not None)
            target['trade_clock_in_session'] += int(s['trade_in_session'])
            target['finite_iv'] += int(valid_number(s['iv']))
            target['bbo_spread_le_10pct'] += int(s['relative_spread'] is not None and s['relative_spread'] <= .10)
            target['bbo_spread_gt_50pct'] += int(s['relative_spread'] is not None and s['relative_spread'] > .50)
        if rows:
            s = rows[0][1]
            target['strikes'][s['kind']].append((s['expiry'], s['strike']))
            if s['expiry'] not in target['expiries']:
                target['expiries'].append(s['expiry'])

    # ----------------------------------------
    # 同じ満期・権利価格の両側が保存されていても、同時気配や約定可能性の証明ではない。
    for target in by_session.values():
        target['file_level_cp_pairs'] = len(set(target['strikes']['C']) & set(target['strikes']['P']))
        del target['strikes']
    return dict(data_root=str(DATA), file_count=len(files), sessions=by_session, totals=dict(totals),
                clock_fields=dict(clock_keys), examples=examples, files=files, samples=samples,
                financial_replays=0, api_calls=0, actual_orders=0,
                limitations=['各ファイル最大9位置の標本で全行の率ではない。',
                    'CurrentPriceTime/TradingVolumeTimeがnullでも気配を無効にしない。正常BBOは価格・数量から独立判定する。',
                    '原板の行番号・約定時計・ファイル更新日時を受信時刻に変換していない。',
                    '生ファイルがある場合は圧縮版を重複計上せず、生ファイルを参照。',
                    '気配差の標本は非同期であり、実約定費用や場中利益を推計しない。'])


def main():
    """
    機能: 非金融診断を実行し、JSONと短いMarkdownを保存する。
    引数: なし。
    返り値: None。原本や他担当の成果物を変更しない。
    """
    result = scan()
    output = HERE / 'オプション保存資格140.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    total = result['totals']
    lines = ['# オプション保存資格の再点検', '',
             '**約定時計がnullでも、板の価格・数量は観測情報として有効です。nullを板の失格理由には使っていません。別銘柄と同期する受信時計が保存されていないことが、複数脚を同時再生する際の制約です。**', '',
             f"全{result['file_count']}ファイル・{len(result['sessions'])}場から{total['sample_count']}標本を診断。全行の検査・金融再生ではありません。", '',
             f"約定・出来高時計がともに同じ{total['same_price_volume_clock_pairs']}標本対のうち、IV/Greeks変化{total['same_clocks_greek_changed']}対、最良気配/数量変化{total['same_clocks_bbo_changed']}対。", '',
             f"正常両側気配{total['valid_bbo']}/{total['sample_count']}標本、当場内の約定時計{total['trade_clock_in_session']}/{total['sample_count']}標本。", '',
             '| 場 | ファイル | 標本 | 正常気配 | 当場約定時計 | 気配差≦中値10% | 気配差>中値50% |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for session, row in result['sessions'].items():
        lines.append(f"|{session}|{row['files']}|{row['sample_count']}|{row['valid_bbo']}|{row['trade_clock_in_session']}|{row['bbo_spread_le_10pct']}|{row['bbo_spread_gt_50pct']}|")
    lines += ['', '保存されている時計項目：' + '、'.join(result['clock_fields']), '',
              '各比率はファイル内の限定標本です。約定時計の有無と気配の正常性は別々に計上し、これを約定できる場内時間の割合や、利益が出る確率とは扱いません。', '',
              '全階層のキーを再帰走査し、Buy1～Buy10・Sell1～Sell10内の時刻やAskTime/BidTime等も確認しました。標本で見つかった時刻キーは上記6種類だけです。取得元コードは受信時刻をメモリに保持する一方、保存JSONLはpayloadのみで、資料フォルダに各行時計のsidecarは確認できません。', '',
              '原本の受信時刻・共通連番・IV算出時刻が確認できない限り、現在の値を同じCurrentPriceTimeへ結合した先物・オプション同時売買の再生は行いません。前の完了場の情報を次場で固定利用する案と区別します。', '',
              '金融再生0、API取得0、実注文0。詳細な対象ファイル、標本バイト位置、標本SHA256、反例はオプション保存資格140.jsonに保存。']
    (HERE / 'オプション保存資格140.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
    print(json.dumps(dict(files=result['file_count'],sessions=len(result['sessions']),totals=total,clocks=result['clock_fields']), ensure_ascii=False))


def previous_context(result):
    """
    機能: 直前完了場の末尾提供値だけを次場へ渡し、先物50場の固定コンテキストを作る。
    引数: result(dict)はscanの限定標本。各原本の最終行を含む。
    返り値: dictは場ごとのIV・歪度・ストラドル参考値。約定可能価格とは扱わない。
    """
    futures = DATA.parent / 'future' / 'NK225'
    sessions = sorted(path.name for path in futures.iterdir() if path.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}_(Day|Night)', path.name))
    tails = {}
    for sample in result['samples']:
        key = sample['session'], sample['file']
        if key not in tails or tails[key]['byte'] < sample['byte']:
            tails[key] = sample
    features = []
    for index, target in enumerate(sessions):
        source = sessions[index-1] if index else None
        item = dict(session=target, source_session=source, known=False, iv_percent=None,
                    quoted_iv_known=False, quoted_iv_percent=None,
                    call_iv_percent=None, put_iv_percent=None, skew_25delta_iv_pp=None,
                    straddle_mid_points=None, straddle_percent=None, straddle_strike=None,
                    source_underlying_close=None, iv_change_pp=None, reason='直前完了場のOP資料なし')
        if source is None or source not in result['sessions']:
            features.append(item)
            continue
        start, _ = session_bounds(target)
        _, source_end = session_bounds(source)
        assert source_end <= start
        item.update(source_completed_at=source_end.isoformat(), available_from=start.isoformat(),
                    source_clock='場内受信時刻は不明。直前の完了場から1場遅らせて利用。')
        rows = [sample for (scene, _), sample in tails.items() if scene == source]
        valid = [r for r in rows if r['expiry'] > target[:7].replace('-','')
                 and valid_number(r['iv']) and 1 <= r['iv'] <= 200
                 and valid_number(r['delta']) and ((r['kind']=='C' and 0 < r['delta'] < 1)
                                                  or (r['kind']=='P' and -1 < r['delta'] < 0))]
        if not valid:
            item['reason'] = '次月以後・有限IV/Deltaの末尾資料なし'
            features.append(item)
            continue
        expiry = min(r['expiry'] for r in valid)
        valid = [r for r in valid if r['expiry']==expiry]
        sides = {}
        quoted_sides = {}
        for side in ('C','P'):
            eligible = [r for r in valid if r['kind']==side and .25 <= abs(r['delta']) <= .75]
            sides[side] = sorted(eligible, key=lambda r:(abs(abs(r['delta'])-.5),r['strike']))[:3]
            quoted_sides[side] = sorted([r for r in eligible if r['quote'] is not None and r['relative_spread']<=.20],
                                       key=lambda r:(abs(abs(r['delta'])-.5),r['strike']))[:3]
        item['expiry'] = expiry
        item['iv_sources'] = {side:[dict(file=r['file'],byte=r['byte'],iv=r['iv'],delta=r['delta'],
                                         quote=r['quote'],trade_at=r['trade_at']) for r in sides[side]] for side in sides}
        if sides['C'] and sides['P']:
            item.update(known=True, reason='直前完了場の同限月C/PのATM付近提供IV',
                        iv_percent=median([r['iv'] for side in sides.values() for r in side]),
                        call_iv_percent=median(r['iv'] for r in sides['C']),
                        put_iv_percent=median(r['iv'] for r in sides['P']))
        else:
            item['reason'] = 'ATM付近のコール又はプットが不足'
        if quoted_sides['C'] and quoted_sides['P']:
            item.update(quoted_iv_known=True, quoted_iv_percent=median([r['iv'] for side in quoted_sides.values() for r in side]))
        item['iv_source_bbo_qualified'] = sum(r['quote'] is not None and r['relative_spread']<=.20 for side in sides.values() for r in side)
        item['iv_source_count'] = sum(len(side) for side in sides.values())
        near = {side: sorted([r for r in valid if r['kind']==side and .15<=abs(r['delta'])<=.35],
                             key=lambda r:(abs(abs(r['delta'])-.25),r['strike'])) for side in ('C','P')}
        if near['C'] and near['P']:
            item['skew_25delta_iv_pp'] = near['P'][0]['iv']-near['C'][0]['iv']
            item['skew_sources'] = {side:dict(file=near[side][0]['file'],byte=near[side][0]['byte'],
                                             iv=near[side][0]['iv'],delta=near[side][0]['delta']) for side in near}
        candle_path = futures/source/'candle_1min.csv'
        if candle_path.exists():
            with candle_path.open(encoding='utf-8-sig', newline='') as stream:
                candles = [r for r in csv.DictReader(stream) if r.get('closed','').lower()=='true'
                           and r.get('close') and float(r['close']) > 0]
            if candles:
                item['source_underlying_close'] = float(candles[-1]['close'])
                item['source_underlying_candle_at'] = candles[-1]['time']
        quote_valid = [r for r in valid if r['quote'] is not None and r['relative_spread']<=.20]
        pairs = {r['strike']: {'C':[], 'P':[]} for r in quote_valid}
        for row in quote_valid:
            pairs[row['strike']][row['kind']].append(row)
        complete = [(strike,pair['C'][0],pair['P'][0]) for strike,pair in pairs.items() if pair['C'] and pair['P']]
        if complete and item['source_underlying_close']:
            strike, call, put = min(complete,key=lambda pair:(abs(pair[0]-item['source_underlying_close']),pair[0]))
            premium = sum(call['quote'])/2+sum(put['quote'])/2
            item.update(straddle_mid_points=premium, straddle_percent=premium/item['source_underlying_close']*100.,
                        straddle_strike=strike, straddle_sources={side:dict(file=row['file'],byte=row['byte'],quote=row['quote'])
                                                              for side,row in (('C',call),('P',put))})
        if item['known'] and features and features[-1]['session']==source and features[-1]['known']:
            item['iv_change_pp'] = item['iv_percent']-features[-1]['iv_percent']
        features.append(item)
    return dict(rows=features, sessions=len(features), known=sum(r['known'] for r in features),
                specification=dict(iv='直前完了場末尾、次月以後最小限月、absDelta.25～.75、.5に近いC/P各最大3の提供IV中央値。気配のない推定値も含み、同時気配の裏付けは別列。',
                    quoted_iv='上と別に、正常BBOかつ幅/中値20%以内を要求したIVをquoted_iv_known/quoted_iv_percentへ記録。',
                    skew='同限月でabsDelta.15～.35内の.25に最も近いput IV − call IV。厳密同deltaの補間はしない。',
                    straddle='前場のNK225最終確定1分終値へ最も近い同K・同限月C/P末尾中値の和。その先物終値で割った値も保存。',
                    delay='当場のOP行は一切利用しない。直前場が欠測ならもっと古い場へ遡らず未知。',
                    change='対象場コンテキストのIV − 直前場コンテキストのIV。両方既知の場合だけ計算。'),
                caveats=['IV/Deltaは提供推定値で計算時計とモデル入力は不明。',
                         'ストラドルは非同期末尾の参考値で、実行可能な同時売買価格ではない。',
                         'OPのSQと12月先物の限月は同一ではない。',
                         '前場情報は当場に利用可能だが鮮度や予測力を保証しない。'],
                financial_replays=0, api_calls=0, actual_orders=0)


if __name__ == '__main__':
    main()
    result = json.loads((HERE/'オプション保存資格140.json').read_text(encoding='utf-8'))
    context = previous_context(result)
    (HERE/'options_context140.json').write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(context_sessions=context['sessions'],known=context['known']),ensure_ascii=False))
