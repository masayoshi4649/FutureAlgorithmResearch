"""固定された統合候補を既存結果から独立再集計し、各部品の効果を比較する。"""

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import pickle

import numpy as np


HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX', 'NK225')
PERIODS = ('前16', '後14', '全30')
HASHES = {}


def read(path):
    """
    機能: 完了済み会計を読み、入力指紋を記録する。
    引数: path (Path)。
    返り値: dict は保存資料。
    """
    data = path.read_bytes()
    HASHES[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return json.loads(data.decode('utf-8'))


def read_pickle(path):
    """
    機能: 既存の注文・決済台帳又は判断時計を読む。
    引数: path (Path)。
    返り値: dict は保存済み資料。損益エンジンは呼び出さない。
    """
    data = path.read_bytes()
    HASHES[str(path.relative_to(ROOT))] = hashlib.sha256(data).hexdigest()
    return pickle.loads(data)


def aggregate(rows, sessions, symbol):
    """
    機能: 原本再生せず、場別の確定会計から金額・日数・時価下落を独立再集計する。
    引数: rows (list[dict])、sessions (list[str])、symbol (str)。
    返り値: dict は商品別の期間会計。部分決済相殺はしない。
    """
    selected = sorted([r for r in rows if r['symbol'] == symbol and r['session'] in sessions],
                      key=lambda r: sessions.index(r['session']))
    assert len(selected) == len(sessions)
    sums = ('profit','loss','net','fees','trades','wins','losses','winning_legs','losing_legs',
            'extensions','protections','pauses','rearms','skipped')
    a = {field: sum(r[field] for r in selected) for field in sums}
    assert a['profit']-a['loss'] == a['net']
    a['profit_share'] = a['profit']/(a['profit']+a['loss']) if a['profit']+a['loss'] else None
    a['profit_loss_ratio'] = a['profit']/a['loss'] if a['loss'] else None
    a['payoff'] = (a['profit']/a['winning_legs'])/(a['loss']/a['losing_legs']) if a['winning_legs'] and a['losing_legs'] else None
    a['average_net'] = a['net']/a['trades'] if a['trades'] else None
    a['winning_sessions'] = sum(r['net'] > 0 for r in selected)
    a['losing_sessions'] = sum(r['net'] < 0 for r in selected)
    a['active_sessions'] = sum(r['trades'] > 0 for r in selected)
    a['no_trade_sessions'] = sum(r['trades'] == 0 for r in selected)
    a['flat_active_sessions'] = sum(r['trades'] > 0 and r['net'] == 0 for r in selected)
    a['positive_session_rate'] = a['winning_sessions']/a['active_sessions'] if a['active_sessions'] else None
    balance = peak = drawdown = 0.
    days = {}
    weeks = {}
    for r in selected:
        drawdown = max(drawdown, r['drawdown'], peak-balance-r['curve_min'])
        peak = max(peak, balance+r['curve_max'])
        balance += r['net']
        day = r['session'][:10]
        d = date.fromisoformat(day)
        week = str(d-timedelta(days=d.weekday()))
        days[day] = days.get(day, 0.)+r['net']
        weeks[week] = weeks.get(week, 0.)+r['net']
    a['drawdown'] = drawdown
    a['without_best_day_net'] = a['net']-max(days.values())
    a['without_best_session'] = a['net']-max(r['net'] for r in selected)
    a['worst_session'] = min(r['net'] for r in selected)
    a['worst_day'] = min(days.values())
    a['positive_weeks'] = sum(v > 0 for v in weeks.values())
    a['week_count'] = len(weeks)
    a['weeks_net'] = weeks
    return a


def metrics(result, fixed):
    """
    機能: 前16・後14・全30の独立値を保存期間値と照合する。
    引数: result/fixed (dict)。
    返り値: dict は照合済みのコンパクト会計。
    """
    periods = {}
    for period in PERIODS:
        periods[period] = {}
        for symbol in SYMBOLS:
            a = aggregate(result['rows'], fixed[period], symbol)
            original = result['periods'][period][symbol]
            for key, value in a.items():
                if key in original and key != 'weeks_net':
                    assert value == original[key] or (value is not None and original[key] is not None and abs(value-original[key]) < 1e-8), (result['config']['id'],period,symbol,key,value,original[key])
            periods[period][symbol] = a
    return periods


def score(result):
    """
    機能: 事前固定の前16選定を独立実装する。
    引数: result (dict)。
    返り値: tuple は昇順の悪い側金額比、非黒字活動場率、比率和、ID。
    """
    p = result['periods']['前16']
    losses = [p[s]['money_loss_share'] if p[s]['money_loss_share'] is not None else 1. for s in SYMBOLS]
    red = [1.-p[s]['positive_session_rate'] if p[s]['positive_session_rate'] is not None else 1. for s in SYMBOLS]
    return max(losses), max(red), sum(losses), result['config']['id']


def verify_selection(results, selection):
    """
    機能: 保存された前半代表が後半を使わない固定規則と一致するか確認する。
    引数: results (dict[str,dict])、selection (dict)。
    返り値: dict は独立一致の証跡。
    """
    rows = []
    for chosen in selection['代表']:
        pool = [r for r in results.values() if r['config']['entry'] == chosen['entry']]
        active = [r for r in pool if all(r['periods']['前16'][s]['trades'] >= 20 and r['periods']['前16'][s]['active_sessions'] >= 8 for s in SYMBOLS)]
        positive = [r for r in active if all(r['periods']['前16'][s]['net'] > 0 for s in SYMBOLS)]
        good = [r for r in positive if all(r['periods']['前16'][s]['payoff'] is not None and r['periods']['前16'][s]['payoff'] > 1 for s in SYMBOLS)]
        level = 0 if good else 1 if positive else 2 if active else 3
        expected = min(good or positive or active or pool, key=score)
        assert expected['config']['id'] == chosen['id'] and level == chosen['level']
        rows.append({'ID': chosen['id'], '段階': level, '活動充足数': len(active), '両黒字数': len(positive), '両平均勝負1超数': len(good)})
    expected = min(selection['代表'], key=lambda r: (r['level'], *r['score']))['id']
    assert expected == selection['主候補']
    return {'合格': True, '主候補': expected, '群別': rows, '前16だけ': True}


def identity(config):
    """
    機能: 固定済みの入口と四管理から既存条件IDを求める。
    引数: config (dict)。
    返り値: str は既存ID。
    """
    return f"{config['entry']}_F{config['flow_mode']}_B{config['protect_level']}_H{config['hold_mode']}_R{config['rest_mode']}"


def compare(alt, base):
    """
    機能: 同じ商品と期間で、比較先から対照を引いた効果を整理する。
    引数: alt/base (dict) は独立期間会計。
    返り値: dict は金額差、件数差、損失削減と利益維持の区別。
    """
    output = {}
    for period in PERIODS:
        output[period] = {}
        for symbol in SYMBOLS:
            a, b = alt[period][symbol], base[period][symbol]
            fields = ('profit','loss','net','fees','trades','winning_sessions','losing_sessions','no_trade_sessions','drawdown','without_best_day_net','extensions','protections','pauses','rearms','skipped')
            d = {key: a[key]-b[key] for key in fields}
            d['profit_share'] = a['profit_share']-b['profit_share'] if a['profit_share'] is not None and b['profit_share'] is not None else None
            d['average_net'] = a['average_net']-b['average_net'] if a['average_net'] is not None and b['average_net'] is not None else None
            d['損失削減率'] = 1-a['loss']/b['loss'] if b['loss'] else None
            d['利益維持率'] = a['profit']/b['profit'] if b['profit'] else None
            d['取引削減率'] = 1-a['trades']/b['trades'] if b['trades'] else None
            d['1組平均収支改善'] = bool(d['average_net'] is not None and d['average_net'] > 0)
            output[period][symbol] = d
    return output


def changed_exits(fixed):
    """
    機能: J2のF1追加で実際に変わった同一入口取引を全件特定する。
    引数: fixed (dict) は固定期間。
    返り値: dict は遅延別の改善・悪化の全変更例と、期間別追加効果。
    """
    meta = read(ROOT/'work/wave_v77/inputs/metadata.json')
    ready = {}
    for relative in meta['input_paths']['ready']:
        ready.update(read_pickle(ROOT/relative))
    ready.update(read_pickle(ROOT/'work/wave_v77/inputs/extra_inputs.pkl'))
    output = {}
    jst = timezone(timedelta(hours=9))
    for delay in (1,5,15):
        base = HERE if delay == 5 else HERE/'sensitivity'/f'delay{delay}'
        a_path = base/'ledgers/J2_F1_B0_H0_R0.pkl'
        b_path = base/'ledgers/J2_F0_B0_H0_R0.pkl'
        if not a_path.exists() or not b_path.exists():
            output[str(delay)] = {'未完了': True}
            continue
        alt, baseline = read_pickle(a_path), read_pickle(b_path)
        changes = []
        accounts = 0
        entries = 0
        periods = {p: {s: {'変更組数':0,'改善組数':0,'悪化組数':0,'変更場数':0,'収支差':0.} for s in SYMBOLS} for p in PERIODS}
        for key, account in alt.items():
            at, bt = account['trades'], baseline[key]['trades']
            np.testing.assert_array_equal(at[:,[0,1,3,4,5]], bt[:,[0,1,3,4,5]])
            entries += len(at)
            times = ready[key]['time_s']
            changed = False
            for a,b in zip(at,bt):
                if np.array_equal(a,b):
                    continue
                changed = True
                diff = a[10]-b[10]
                cid = int(a[0])
                ao = account['orders']
                bo = baseline[key]['orders']
                ae = ao[(ao[:,2] == cid)&(ao[:,7] == 0)][0]
                be = bo[(bo[:,2] == cid)&(bo[:,7] == 0)][0]
                changes.append({'セッション':key[0], '商品':key[1], '場内組番号':cid+1,
                    '方向':'買い' if a[3] == 1 else '売り', '枚数':int(a[4]), '新規値':a[5],
                    '新規時刻':datetime.fromtimestamp(times[int(a[1])],jst).isoformat(),
                    '基準返済時刻':datetime.fromtimestamp(times[int(b[2])],jst).isoformat(),
                    '追加返済時刻':datetime.fromtimestamp(times[int(a[2])],jst).isoformat(),
                    '基準返済判断時刻':datetime.fromtimestamp(times[int(be[1])],jst).isoformat(),
                    '追加返済判断時刻':datetime.fromtimestamp(times[int(ae[1])],jst).isoformat(),
                    '基準返済値':b[6], '追加返済値':a[6], '基準収支':b[10], '追加収支':a[10], '収支差':diff,
                    '基準返済理由':int(be[6]), '追加返済理由':int(ae[6]), '同一新規':True})
                for period in PERIODS:
                    if key[0] in fixed[period]:
                        bucket = periods[period][key[1]]
                        bucket['変更組数'] += 1
                        bucket['改善組数'] += int(diff > 0)
                        bucket['悪化組数'] += int(diff < 0)
                        bucket['収支差'] += diff
            if changed:
                accounts += 1
                for period in PERIODS:
                    if key[0] in fixed[period]:
                        periods[period][key[1]]['変更場数'] += 1
        output[str(delay)] = {'同一入口を全件照合':True,'入口組数':entries,'変更口座数':accounts,
                              '全変更取引':changes,'期間別追加効果':periods}
    return output


def main():
    """
    機能: 固定代表・部品単独・一部品除去・遅延感度を会計だけで比較する。
    引数: CLI --require-delays (bool) は遅延結果の完了を要求する。
    返り値: None。担当証拠JSONを保存する。新条件は作らない。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('--require-delays', action='store_true')
    args = parser.parse_args()
    fixed = read(HERE/'事前固定.json')
    selection = read(HERE/'前半選定.json')
    results = {p.stem: read(p) for p in sorted((HERE/'results').glob('*.json'))}
    assert len(results) == 162
    assert set(results) == {c['id'] for c in fixed['条件']}
    validation = verify_selection(results, selection)
    selected = [r['id'] for r in selection['代表']]
    identifiers = set(selected+[selection['基準']])
    comparisons = []
    seen = set()
    for ident in selected:
        c = results[ident]['config']
        base = dict(c, flow_mode=0, protect_level=0, hold_mode=0, rest_mode=0)
        baseline = identity(base)
        options = [('代表と同入口基準', ident, baseline)]
        for key, choices, title in [('flow_mode',(1,2),'反対撤退'),('protect_level',(1,2),'同幅の建値保護'),('hold_mode',(1,2),'保有延長'),('rest_mode',(1,),'連敗休止')]:
            options += [(title+'単独', identity(dict(base, **{key:value})), baseline) for value in choices]
            if c[key] != 0:
                options.append((title+'を代表へ加えた差', ident, identity(dict(c, **{key:0}))))
        options.append(('条件延長と固定90分の差', identity(dict(base, hold_mode=1)), identity(dict(base, hold_mode=2))))
        if c['hold_mode'] != 0:
            options.append(('代表の条件延長と固定90分の差', identity(dict(c, hold_mode=1)), identity(dict(c, hold_mode=2))))
        for title, alt, reference in options:
            if (alt,reference) in seen or alt == reference:
                continue
            seen.add((alt,reference))
            comparisons.append({'比較':title, '比較先':alt, '対照':reference})
            identifiers.update((alt,reference))
    # ----------------------------------------
    # 既存全量会計だけを用いる。遅延の未実施資料は0円へ補完しない。
    accounts = {ident: metrics(results[ident], fixed) for ident in sorted(identifiers)}
    for c in comparisons:
        c['差'] = compare(accounts[c['比較先']], accounts[c['対照']])
    delays = {}
    missing = []
    for delay in (1,15):
        branch = {}
        for ident in selection['感度対象']:
            path = HERE/'sensitivity'/f'delay{delay}'/'results'/f'{ident}.json'
            if not path.exists():
                missing.append(f'{delay}/{ident}')
                continue
            branch[ident] = metrics(read(path), fixed)
        delays[str(delay)] = branch
    if args.require_delays:
        assert not missing, missing
    exit_changes = changed_exits(fixed)
    primary = accounts[selection['主候補']]
    conclusions = []
    for symbol in SYMBOLS:
        full = primary['全30'][symbol]
        back = primary['後14'][symbol]
        bm = accounts[selection['基準']]['全30'][symbol]
        conclusions.append({'商品':symbol, '主候補':selection['主候補'], '全30収支':full['net'],
            '基準比収支':full['net']-bm['net'], '金額利益割合':full['profit_share'],
            '後14収支':back['net'], '後14平均勝負':back['payoff'],
            '黒字赤字無取引場': [full['winning_sessions'],full['losing_sessions'],full['no_trade_sessions']],
            '全場黒字':full['winning_sessions'] == len(fixed['全30']),
            '80達成':bool(full['profit_share'] is not None and full['profit_share'] >= .8),
            '後半最低活動充足':back['trades'] >= 10 and back['active_sessions'] >= 6,
            '後半黒字損小利大大勝日除外充足':bool(back['net'] > 0 and back['payoff'] is not None and back['payoff'] > 1 and back['without_best_day_net'] > 0)})
    output = {'新損益再生':False, '条件追加':False, '後半で代表差替え':False,
        '全30は既知資料':True, '未知期間検証ではない':True, 'API取得':0,'実注文':0,
        '独立選定照合':validation, '主要結論':conclusions, '代表':[{'ID':i,'会計':accounts[i]} for i in selected],
        '基準':{'ID':selection['基準'],'会計':accounts[selection['基準']]},
        '同入口部品対照':comparisons, '対照全会計':accounts, '遅延感度':delays, '未完了遅延':missing,
        'F1追加で変わった全取引':exit_changes,
        '部品の短い解釈':[
            'F1の主5秒での全30改善はTOPIX5万円・日経8千円だが、変更は3組だけ。前半9月30日の2組を助け、後半10月7日夜間TOPIXの回復前に返して7.5万円悪化。',
            'F1追加効果は遅延1秒でTOPIX+3万円・日経-2千円、15秒でTOPIX-1.5万円・日経+8千円。増益差が両商品で安定したとはいえず、基準からの昇格は保留が妥当。',
            'J2のF2は全30で基準と同じ。反対実気配も15秒持続する確認では実際の返済が変わらず、追加確認の能力は未判定。',
            'J2の条件延長H1は延長0回でH0固定30分と同じ。条件延長の一般的無効を示さず、今回の厳しい条件で作動しなかった。',
            'J2の建値保護B1/B2はトレール幅一定でも両商品収支を削った。損失削減だけを見ず、勝ちの利益減少も含める必要がある。',
            'J2の固定90分H2はTOPIX収支を増やすが日経を減らし、時価最大下落は両商品で悪化。連敗休止R1もTOPIX改善・日経悪化で共通改善ではなかった。'],
        '解釈上の区別':[
            'B1/B2はトレール幅を0.4%に固定したまま、順行後の建値保護だけを変更。旧00073の保護＋幅縮小との同時変更と異なる。',
            'H1条件延長はH0固定30分とH2固定90分の両方と比較する。保有を長くした効果と、延長を選ぶ効果を分ける。',
            'R1は確定連敗後の将来入口を見送る。取引数の減少、総損失の減少、利益維持、1組平均を分ける。損失を最初から防げる方式ではない。',
            '部品変更で返済時点と次入口可否が変わる。固定された入口候補列の通し運用比較であり、同一取引を機械的に切り貼りした差ではない。',
            '全日安定は黒字場数と赤字場数を表示し、無取引を勝ちに数えない。金額利益割合80%とも別基準。',
            '基準J2から別入口群の代表への差は入口と管理の複合差。同入口基準と一部品除去で単独効果を確認する。',
            '前16で選定していても全30は過去に研究済み。良い後半結果を未見検証と呼ばず、新たな未知セッションでの固定運用が必要。'],
        '出典SHA256':HASHES, '解析器SHA256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    target = HERE/'evidence/統合部品の効果と失敗.json'
    target.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    print(json.dumps({'出力':str(target),'主要結論':conclusions,'遅延未完了数':len(missing)},ensure_ascii=False))


if __name__ == '__main__':
    main()
