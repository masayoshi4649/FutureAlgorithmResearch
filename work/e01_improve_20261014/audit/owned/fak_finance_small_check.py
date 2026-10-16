"""正式終端後の十八条件小会計を、実金融や台帳の再生なしで独立検算する。"""

from collections import Counter
from pathlib import Path
import hashlib
import importlib.util
import json
import math
import traceback

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
ENGINE = ROOT / 'work/e01_improve_20261014/engine'
HELPER = ROOT / 'work/e01_cross_market_20261014/audit/cross16_finance_check_v2.py'
spec = importlib.util.spec_from_file_location('旧独立小算術', HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)
metrics, stability, ratio, fee = helper.metrics, helper.stability, helper.ratio, helper.fee
SYMBOLS = ('TOPIX', 'NK225')
FIELDS = ('収支変化', '避けた基準損失', '失った基準利益', '共通入口の数量/出口差', '新たな入口の収支')
COUNT_FIELDS = ('公開受理', '試行約定', '試行失効', '未試行取消')
ACTIVITY_FIELDS = ('paper_candidates', 'known_votes', 'gate_accepted', 'actual_accepted', 'actual_newfills', 'fak_expired')
PATHS = (ENGINE / 'finance/結果.json', ENGINE / '試行計画.json', ENGINE / '金融事前固定.json',
         HERE / '正式20源十八政策と六市場保存比較及び登録の独立接続.json')
READS = {}
COUNTS = Counter()


def read_once(path: Path) -> dict:
    """
    機能: 授権済み小資料だけを各一読し、同 bytes 指紋を記録する。
    引数: path(Path) は正式結果・正式計画・固定又は独立金融前証跡。
    返り値: dict は保存 JSON。packet・台帳・原板は開かない。
    """
    assert path in PATHS and path not in READS
    raw = path.read_bytes()
    READS[path] = hashlib.sha256(raw).hexdigest()
    return json.loads(raw.decode('utf-8-sig'))


def same(actual: object, expected: object, label: str = '') -> None:
    """
    機能: 未定義と真偽を保存して独立小会計を照合する。
    引数: actual/expected(object) は保存値と算術値、label(str) は識別文。
    返り値: None。不一致は例外として初版 False を保存する。
    """
    COUNTS['小値照合'] += 1
    if expected is None or isinstance(expected, (bool, str)):
        assert actual == expected, (label, actual, expected)
    elif isinstance(expected, (int, float)):
        assert actual is not None and math.isfinite(actual), (label, actual, expected)
        assert math.isclose(actual, expected, abs_tol=1e-5, rel_tol=1e-11), (label, actual, expected)
    elif isinstance(expected, dict):
        for key, value in expected.items():
            same(actual[key], value, label + '/' + key)
    else:
        assert actual == expected, (label, actual, expected)


def rows_check(rows: list[dict], sessions: list[str], label: str) -> dict:
    """
    機能: 66 商品場の net、親数、枚数、費用及び零取引を独立検算する。
    引数: rows(list[dict]) は場小会計、sessions(list[str]) は固定33場、label(str) は条件。
    返り値: dict は商品場をキーとする小会計。費用後親 net が主指標。
    """
    mapped = {(r['session'], r['symbol']): r for r in rows}
    assert len(rows) == len(mapped) == 66
    assert set(mapped) == {(s, a) for s in sessions for a in SYMBOLS}
    for row in rows:
        assert row['全会計合格'] is True
        for key in ('利益', '損失', '費用', '親数', '新規枚数', '注文件数'):
            assert row[key] >= 0
        same(row['利益'] - row['損失'], row['収支'], label + '/場net')
        same(row['勝ち親'] + row['負け親'] + row['零親'], row['親数'], '親母数')
        same(row['勝ち枚数'] + row['負け枚数'] + row['零枚数'], row['新規枚数'], '枚数保存')
        same(row['PF'], ratio(row['利益'], row['損失']))
        same(row['利益割合'], ratio(row['利益'], row['利益'] + row['損失']))
        same(row['平均利益'], ratio(row['利益'], row['勝ち親']))
        same(row['平均損失'], ratio(row['損失'], row['負け親']))
        assert row['最大買枚数'] <= (10 if row['symbol'] == 'TOPIX' else 20)
        assert row['最大売枚数'] <= (10 if row['symbol'] == 'TOPIX' else 20)
        if row['親数'] == 0:
            same({k: row[k] for k in ('利益', '損失', '収支', '費用', '新規枚数', '注文件数')},
                 {k: 0 for k in ('利益', '損失', '収支', '費用', '新規枚数', '注文件数')})
        COUNTS['場会計'] += 1
    return mapped


def period_check(saved: dict, sessions: list[str], cid: str) -> dict:
    """
    機能: 商品別四期間、正方向別、副表 net を独立集計し主三基準を評価する。
    引数: saved(dict) は新又は保存条件、sessions(list[str]) は33場、cid(str) は条件 ID。
    返り値: dict は二商品四期間と除外場・方向の独立集計。
    """
    result = {}
    for symbol in SYMBOLS:
        own = [r for r in saved['rows'] if r['symbol'] == symbol]
        assert [r['session'] for r in own] == sessions
        full = metrics(own)
        same(saved['symbols'][symbol], full, cid + '/' + symbol)
        top = sorted((r for r in own if r['収支'] > 0), key=lambda r: (-r['収支'], r['session']))[:3]
        excluded = {r['session'] for r in top}
        scopes = {'全33': sessions, '前16': sessions[:16], '後17': sessions[16:],
                  '上位3正収支場除外': [s for s in sessions if s not in excluded]}
        periods = {}
        for name, selected in scopes.items():
            subset = [r for r in own if r['session'] in selected]
            agg, goal = metrics(subset), stability(subset)
            current = saved['periods'][symbol][name]
            same(current['sessions'], selected)
            same(current['aggregate'], agg, cid + '/' + symbol + '/' + name)
            same(current['stability'], goal)
            periods[name] = dict(金額=agg, 基準=goal)
            COUNTS['期間商品集計'] += 1
        same(saved['periods'][symbol]['除外場'], [r['session'] for r in top])
        same(saved['stability'][symbol], periods['全33']['基準'])
        direction = saved['directional_symbols'][symbol]
        for side in ('long', 'short'):
            item = direction[side]
            same(item['利益'] - item['損失'], item['収支'])
            same(item['勝ち親'] + item['負け親'] + item['零親'], item['親数'])
            same(item['利益割合'], ratio(item['利益'], item['利益'] + item['損失']))
            same(item['PF'], ratio(item['利益'], item['損失']))
            same(item['平均利益'], ratio(item['利益'], item['勝ち親']))
            same(item['平均損失'], ratio(item['損失'], item['負け親']))
        for field in ('利益', '損失', '収支', '親数', '勝ち親', '負け親', '零親'):
            same(direction['long'][field] + direction['short'][field], full[field], '方向合計')
        same(direction['long']['枚数'] + direction['short']['枚数'], full['新規枚数'])
        if 'actual_leg_symbols' in saved:
            leg = saved['actual_leg_symbols'][symbol]
            same(leg['利益'] - leg['損失'], full['収支'], '決済玉副表と親net')
            same(leg['勝ち親'] + leg['負け親'] + leg['零親'], leg['親数'])
        result[symbol] = dict(期間=periods, 除外場=[r['session'] for r in top], 方向=direction)
    return result


def boundary_check(config: dict, item: dict, actual: dict, row: dict) -> None:
    """
    機能: 初回受理尺度と次正常モデルの初実約定を、取消後持越しも含め小保存値で照合する。
    引数: config/item/actual/row(dict) は固定条件、出口境界、FAK診断及び同場会計。
    返り値: None。全 UID や真の注文到着・板消費を証明したとは呼ばない。
    """
    symbol = item['symbol']
    value, tick, full, budget = (1000, .5, 5, 5000) if symbol == 'TOPIX' else (10, 10, 10, 2000)
    anchor, line, control = item['anchor'], item['exit_boundary'], item['停止判断']
    same(actual['first_anchor'], anchor)
    same(actual['fixed_exit_boundary'], line)
    source = line['anchor']
    same(anchor['成立'], source is not None)
    same(line['quantity_selection_budget_yen'], budget)
    same(item['新規数量選択予算円'], budget)
    for field in ('arm_yen', 'drawdown_yen', 'floor_yen'):
        same(line[field], None)
    if source is None:
        for field in ('target_yen', 'hard_loss_yen'):
            same(line[field], None)
        for field in ('数量', '受理行', '受理原seq', '受理価格時計', '紙上親', '利益目標円'):
            same(anchor[field], None)
        assert row['親数'] == 0 and not control['発動'] and actual['first_actual'] is None
        COUNTS['未受理場'] += 1
    else:
        q = source['quantity']
        assert type(q) is int and 0 < q <= full and source['published_atr'] > 0 and source['published_spread'] > 0
        same(source['full_quantity'], full)
        same(source['multiplier'], value)
        same(source['atr_yen'], q * source['published_atr'] * value)
        same(source['roundtrip_fee_yen'], 2 * fee(q, symbol))
        same(source['spread_fee_yen'], q * source['published_spread'] * value + 2 * fee(q, symbol))
        expected_goal = q * tick * value if config['target_id'] == 'P1' else .25 * q * source['published_atr'] * value
        same(line['target_yen'], expected_goal)
        same(line['hard_loss_yen'], budget)
        same(item['目標円'], expected_goal)
        same(item['損失予算円'], budget)
        same(anchor['利益目標円'], expected_goal)
        for field, original in (('数量', 'quantity'), ('受理行', 'row'), ('受理原seq', 'raw_seq'),
                                ('受理価格時計', 'price_time_s'), ('紙上親', 'parent'), ('通常全量', 'full_quantity')):
            same(anchor[field], source[original])
        COUNTS['初受理場'] += 1
    first = actual['first_actual']
    if first is not None:
        assert source is not None and first['source_row'] >= anchor['受理行']
        assert first['row'] > first['source_row'] and first['raw_seq'] > first['publication_raw_seq']
        assert first['publication_raw_seq'] >= anchor['受理原seq']
        assert first['price_time_s'] >= first['publication_price_time_s'] >= anchor['受理価格時計']
        assert 0 < first['quantity'] <= full and first['side'] in (-1, 1)
        assert first['fill_ask'] >= first['fill_bid'] > 0 and first['publication_ask'] >= first['publication_bid'] > 0
        same(first['published_spread'], first['publication_ask'] - first['publication_bid'])
        same(first['price'], first['fill_ask'] if first['side'] == 1 else first['fill_bid'], '初実約定正気配')
        if config['execution_id'] != 'MARKET':
            if first['side'] == 1:
                assert first['price'] <= first['publication_ask'] + config['adverse_ticks'] * tick + 1e-8
            else:
                assert first['price'] >= first['publication_bid'] - config['adverse_ticks'] * tick - 1e-8
        COUNTS['初実約定境界'] += 1
    same(actual['first_anchor_to_actual_diff'], first is not None and anchor['受理行'] != first['source_row'])
    carry = bool(source is not None and first is not None and not actual['initial_accepted_actually_filled']
                 and first['source_row'] != anchor['受理行'])
    same(actual['carryover_after_unfilled_initial'], carry)
    same(actual['carryover_quantity_changed'], carry and first['quantity'] != anchor['数量'])
    same(actual['実政策新規数'], row['親数'], '実親と実新規母数')
    for field in COUNT_FIELDS:
        whole, prefix = actual['GU全試行'][field], actual['実政策判断行以下の試行'][field]
        assert 0 <= prefix <= whole
        if config['execution_id'] == 'MARKET':
            same(whole, 0)
        COUNTS['全GUと政策接頭件数'] += 1
    if control['発動']:
        assert source is not None and control['判断行'] >= anchor['受理行']
        assert control['判断原seq'] >= anchor['受理原seq'] and control['判断価格時計'] >= anchor['受理価格時計']
        assert control['返済行'] >= control['判断行']
        assert control['返済原seq'] >= control['判断原seq'] and control['返済価格時計'] >= control['判断価格時計']
        assert control['以後新規なし'] and control['未来返済テンプレート参照'] is False
        same(control['実返済後収支'], row['収支'])
        same(control['判断から返済の悪化'], row['収支'] - control['判断時清算利益'])
        same(actual['実政策判断行'], control['判断行'])
    COUNTS['受理出口境界'] += 1


# ----------------------------------------
def main() -> None:
    """
    機能: 根の terminal 0 通知後に三小資料を各一読し、十八新条件を監査する。
    引数: なし。読取対象と正式 SHA は結果を開く前に本スクリプトへ固定した。
    返り値: None。自所有成功又は False 証跡を保存し共有資料は変更しない。
    """
    output_path = HERE / '十八新条件1188小会計と192期間及びFAK持越しの独立監査.json'
    false_path = HERE / '十八新条件小会計の独立監査False.json'
    scope_path = HERE / '十八新条件小会計の独立読取計画.json'
    assert not any(p.exists() for p in (output_path, false_path, scope_path))
    scope_path.write_text(json.dumps(dict(根終端0通知=True,予定結果SHA256='bc50b5db84cb3f9afe329c9966863a302b0b11a8722e050207cc49c1862860b6',
        小資料各一読=[p.relative_to(ROOT).as_posix() for p in PATHS],予定=dict(新場会計=1188,保存場引用=396,期間商品集計=192,五寄与場=1188,受理境界=1188),
        主指標='完結実親の費用後 net。33 分母。平均黒字場 net で最悪赤字を補填。',
        留保='全親/全UID/全FAKイベントが小結果に無いため分類自体の再トレース・原板補充・物理 FAK 執行は未測。',
        input=0,packet=0,ledger=0,原板=0,NPZ=0,金融再実行=0,API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    try:
        result, plan, fixed, preaudit = [read_once(p) for p in PATHS]
        assert READS[PATHS[0]] == 'bc50b5db84cb3f9afe329c9966863a302b0b11a8722e050207cc49c1862860b6'
        assert READS[PATHS[1]] == fixed['計画SHA256'] == 'fceefa7d703bbbed8e8a9ac158bf46365544c2d923c3a8777483ed1e056b7472'
        assert preaudit['全合格'] and result['全合格'] and result['source開始終端一致']
        assert result['sessions'] == fixed['sessions'] and len(result['sessions']) == 33
        sessions = result['sessions']
        assert Counter(s.rsplit('_',1)[-1] for s in sessions) == dict(Day=17,Night=16)
        assert result['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
        assert len(result['configs']) == len(result['results']) == 18 and len(result['reused_results']) == 6
        assert result['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
        assert len(result['source_SHA256']) == 20 and result['case_SHA256'] == fixed['case_SHA256']
        for path, expected in result['source_SHA256'].items():
            assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == expected
        expected_counts = dict(既input一読=33,旧市場台帳一読=396,保存GU再利用=198,新GUengine=594,新政策会計=1188,旧基準経済同値確認=396)
        same(result['counts'], expected_counts)
        for key, expected in dict(会計口座数=1188,新GUengine=594,保存GU再利用=198,旧基準経済同値確認=396,原板=0,NPZ=0,API=0,現在入力=0,旧金融再生=0).items():
            same(result[key], expected)
        combined = dict(result['reused_results'], **result['results'])
        maps, all_stats = {}, {}
        for cid, saved in combined.items():
            maps[cid] = rows_check(saved['rows'], sessions, cid)
            all_stats[cid] = period_check(saved, sessions, cid)
            if cid in result['reused_results']:
                quoted = fixed['reused_results'][cid]
                for field in quoted:
                    same(saved[field], quoted[field], '六市場保存引用/' + field)
                COUNTS['保存引用場'] += len(saved['rows'])
            else:
                assert len(saved['ledgers']) == 66
                assert {(l['session'],l['symbol']) for l in saved['ledgers']} == set(maps[cid])
                COUNTS['新会計場'] += 66
        assert result['boundary'] == result['初回受理と費用後目標境界']
        contributions, carryovers, causal_examples = {}, {}, []
        for config in result['configs']:
            cid, baseline = config['id'], config['baseline_id']
            assert baseline in combined
            changes = result['各場寄与'][cid]
            assert len(changes) == 66 and {(d['session'],d['symbol']) for d in changes} == set(maps[cid])
            for d in changes:
                key = (d['session'],d['symbol'])
                assert d['baseline_id'] == baseline
                same(d['収支変化'], maps[cid][key]['収支'] - maps[baseline][key]['収支'])
                same(d['収支変化'], d[FIELDS[1]] - d[FIELDS[2]] + d[FIELDS[3]] + d[FIELDS[4]], '五寄与恒等式')
                assert d[FIELDS[1]] >= 0 and d[FIELDS[2]] >= 0
                for p in d['元勝ち親が赤字化']:
                    assert p['old_net'] > 0 and p['new_net'] < 0
                COUNTS['五寄与場'] += 1
            contributions[cid], carryovers[cid] = {}, {}
            bs = {(b['session'],b['symbol']):b for b in result['boundary'][cid]}
            ds = {(d['session'],d['symbol']):d for d in result['fak_diagnosis'][cid]}
            assert len(bs) == len(ds) == 66 and set(bs) == set(ds) == set(maps[cid])
            for key, b in bs.items():
                boundary_check(config,b,ds[key],maps[cid][key])
            for symbol in SYMBOLS:
                subset = [d for d in changes if d['symbol'] == symbol]
                total = {f:math.fsum(d[f] for d in subset) for f in FIELDS}
                total['元勝ち親が赤字化'] = sum(len(d['元勝ち親が赤字化']) for d in subset)
                same(result['diagnosis'][cid][symbol],total)
                contributions[cid][symbol] = total
                records = [d for d in ds.values() if d['symbol'] == symbol]
                counts = {group:{f:sum(r[group][f] for r in records) for f in COUNT_FIELDS}
                          for group in ('GU全試行','実政策判断行以下の試行')}
                counts.update(初受理と実初回差場数=sum(r['first_anchor_to_actual_diff'] for r in records),
                              初受理未約定から後参加への尺度持越し場数=sum(r['carryover_after_unfilled_initial'] for r in records),
                              持越し先の数量差場数=sum(r['carryover_quantity_changed'] for r in records))
                same(result['fak_summary'][cid][symbol],counts)
                carryovers[cid][symbol] = counts
            for d in changes:
                if config['execution_id'] == 'FAK0' and d['symbol'] == 'NK225' and d['新たな入口の収支'] < 0:
                    key = (d['session'],d['symbol'])
                    causal_examples.append(dict(id=cid,session=d['session'],baseline_id=baseline,
                        基準場収支=maps[baseline][key]['収支'],新場収支=maps[cid][key]['収支'],五寄与={f:d[f] for f in FIELDS},
                        初受理と初約定=ds[key],留保='新入口の親別時刻や元勝ちの失効行は小結果未保存。場差と分類小計からだけ述べる。'))
        activities = result['GU_activity']
        assert list(activities) == sessions
        activity_aggregates = {}
        for session, accounts in activities.items():
            assert set(accounts) == set(SYMBOLS)
            for symbol, routes in accounts.items():
                assert len(routes) == 12
                assert len({v['paper_candidates'] for v in routes.values()}) == 1
                assert len({v['known_votes'] for v in routes.values()}) == 1
                for execution in ('MARKET','FAK0','FAK1'):
                    ga = {g: routes[g+'|'+execution]['gate_accepted'] for g in ('G25','G50','G75','G50N4') if g+'|'+execution in routes}
                    if execution != 'MARKET':
                        assert ga['G75'] <= ga['G50'] <= ga['G25'] and ga['G50N4'] <= ga['G50']
                    else:
                        assert ga['G75'] <= ga['G50'] <= ga['G25'] and ga['G50N4'] <= ga['G50']
                for route, data in routes.items():
                    for field in ACTIVITY_FIELDS:
                        assert type(data[field]) is int and data[field] >= 0
                    assert data['actual_accepted'] <= data['gate_accepted'] <= data['known_votes'] <= data['paper_candidates']
                    assert data['actual_newfills'] + data['fak_expired'] <= data['actual_accepted']
                    assert sum(data['overlap_patterns'].values()) == data['paper_candidates']
                    assert data['flags'].get('実予約受理',0) == data['actual_accepted']
                    for group in ('全33',session.rsplit('_',1)[-1]):
                        box = activity_aggregates.setdefault(route,{}).setdefault(symbol,{}).setdefault(group,
                            dict(sessions=0,**{f:0 for f in ACTIVITY_FIELDS},flags=Counter(),overlap_patterns=Counter()))
                        box['sessions'] += 1
                        for field in ACTIVITY_FIELDS:
                            box[field] += data[field]
                        box['flags'].update(data['flags']); box['overlap_patterns'].update(data['overlap_patterns'])
                    COUNTS['全GU候補診断'] += 1
        same(result['GU_activity_summary'],activity_aggregates)
        full_pass = {s:[cid for cid in result['results'] if all_stats[cid][s]['期間']['全33']['基準']['all_targets']] for s in SYMBOLS}
        trim_pass = {s:[cid for cid in result['results'] if all_stats[cid][s]['期間']['上位3正収支場除外']['基準']['all_targets']] for s in SYMBOLS}
        both = sorted(set(full_pass['TOPIX']) & set(full_pass['NK225']))
        both_trim = sorted(set(trim_pass['TOPIX']) & set(trim_pass['NK225']))
        assert COUNTS['新会計場'] == COUNTS['五寄与場'] == COUNTS['受理出口境界'] == 1188
        assert COUNTS['保存引用場'] == 396 and COUNTS['場会計'] == 1584 and COUNTS['期間商品集計'] == 192
        assert COUNTS['全GU候補診断'] == 792
        output = dict(全合格=True,評価='保存小会計と尺度の監査合格。未知成功又は全場利益を意味しない。',
            正式結果SHA256=READS[PATHS[0]],小JSON一読SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},
            検査=dict(COUNTS),正式実行数=expected_counts,新18商品別主三基準合格=full_pass,
            新18両商品主三基準合格=both,新18商品別上位3除外三基準合格=trim_pass,新18両商品上位3除外三基準合格=both_trim,
            商品と期間=all_stats,五寄与=contributions,FAK持越しと試行母数=carryovers,
            FAK0日経の新入口赤字場=causal_examples,全GU候補と昼夜分母=activity_aggregates,
            定義='親netの総利益/(総利益+総損失)>=65%。赤字場/全33<=20%。最悪赤字<=平均黒字場net。無取引は勝ちに数えず、主達成とtop3頑健性を別記。',
            留保=['旧396は保存GU再利用の同値対照で、新たな有効性標本ではない。十八同一データ条件も独立十八日ではない。',
                '全親UID/全FAKイベントを新実台帳で再走査していない。五寄与の親分類は恒等式・基準との差・小計を検算した。',
                '初実約定の正気配・cap・公開時計を検算した。全親の物理FAK到着・部分執行・mini/micro板の厚みと補充は未測。',
                '初受理未約定の取消後もq/ATR目標を保持。後参加のq変更で場目標を最適化し直していない。',
                '全GU診断は実政策停止後suffixを含む。接頭試行と実親勝率の母数は別。重複拒否タグを単独原因件数と呼ばない。',
                '閾値・FAK許容は既知33の原因診断後に固定した既知内探索。商品別静的選択も未知保証を与えない。'],
            独立source_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            独立算術helper_SHA256=hashlib.sha256(HELPER.read_bytes()).hexdigest(),
            input=0,packet=0,ledger=0,原板=0,NPZ=0,金融再実行=0,API=0,共有又は金融源変更=0)
        output_path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        print(json.dumps(dict(全合格=True,検査=dict(COUNTS),両商品主三基準合格=both,
            商品別主三基準合格=full_pass,SHA256=hashlib.sha256(output_path.read_bytes()).hexdigest()),ensure_ascii=False))
    except Exception:
        false_path.write_text(json.dumps(dict(全合格=False,原因=traceback.format_exc(),
            小JSON読取SHA256={p.relative_to(ROOT).as_posix():h for p,h in READS.items()},検査=dict(COUNTS),
            sourceSHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),金融再実行=0,自動再実行=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
