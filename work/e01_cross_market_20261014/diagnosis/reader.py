"""完成した同母二商品の43実親を、固定した目的別各一読で診断する。"""

import argparse
from collections import Counter
import gzip
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import pickle
import sys
import traceback

import numpy as np

sys.dont_write_bytecode = True
sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
VALUE = {'TOPIX': 1000., 'NK225': 10.}
TICK = {'TOPIX': .5, 'NK225': 10.}
REASON = {91: '元GU返済', 92: '静観前返済', 93: '場内終了返済', 94: '利益目標停止', 95: '損失予算停止'}


def digest(path: Path) -> str:
    """
    機能: 小source・完成小資料の指紋を求める。
    引数: path(Path)は小source又は小JSON。
    返り値: strはSHA256。大型入力の事前走査をしない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(name: str, value: dict) -> None:
    """
    機能: 自所有域へ未保存の小診断を保存する。
    引数: name(str)、value(dict)は新位置と診断内容。
    返り値: None。元台帳・source・公開資料を変更しない。
    """
    path = HERE/name
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def checked(item: dict, counts: Counter, kind: str) -> dict:
    """
    機能: 固定した保存packet又は対象活動台帳を、同bytes各一読する。
    引数: item(dict)、counts(Counter)、kind(str)は固定位置/指紋と一読種別。
    返り値: dictは保存内容。金融・原板・APIを実行しない。
    """
    path = ROOT/item['path']
    assert path.resolve().is_relative_to(ROOT/'work') and not counts['path:'+item['path']]
    saved = path.read_bytes()
    assert hashlib.sha256(saved).hexdigest() == item['SHA256']
    counts['path:'+item['path']] += 1
    counts[kind] += 1
    return pickle.loads(gzip.decompress(saved))


def at(value: object, row: int, n: int) -> float:
    """
    機能: 保存normal行のplateau又は配列を前方保持で参照する。
    引数: value(object)、row(int)、n(int)は保存値、参照行、normal全長。
    返り値: floatは保存値。未来の行を参照しない。
    """
    if isinstance(value, np.ndarray):
        assert len(value) == n
        return float(value[row])
    assert value['length'] == n and value['rows'][0] == 0
    i = np.searchsorted(value['rows'], row, side='right')-1
    return float(value['values'][i])


def clean(value: object) -> object:
    """
    機能: 保存numpyスカラー等を小JSONへ写す。
    引数: value(object)は保存数値又は再帰構造。
    返り値: objectは通常型。欠測を数量ゼロや有効観測へ置換しない。
    """
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, np.ndarray):
        return clean(value.tolist())
    if isinstance(value, np.generic):
        return clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def view(account: dict, row: int, helper: object) -> dict:
    """
    機能: normal当行の原行・価格・最良気配を射影する。
    引数: account(dict)、row(int)、helper(module)は保存口座と参照行。
    返り値: dictは当行だけの観測。価格時計を実受信時計とは呼ばない。
    """
    q = account['quotes']
    return dict(**helper.clock(account, row), raw_row=int(account['mapping'][row]),
        Last=float(account['record']['price'][row]), bid=float(q['bid'][row]), ask=float(q['ask'][row]),
        quote_valid=bool(q['quote_valid'][row]))


def observation(session: str, ledger: dict, account: dict, parent: dict, config: dict, helper: object) -> dict:
    """
    機能: 実親の公開/約定/返済と尺度・費用・事後経路を切り分ける。
    引数: session(str)、ledger/account/parent/config(dict)、helper(module)は同母保存実親。
    返り値: dictは診断射影。別出口の収益・最適救済を作らない。
    """
    cid = int(parent['親']); symbol = account['symbol']; multiplier = VALUE[symbol]; tick = TICK[symbol]
    orders = ledger['orders'][ledger['orders'][:, 2] == cid]
    new = orders[orders[:, 7] == 1]
    assert len(new) == 1
    initial = new[0]
    pub, first, last, side, qty = map(int, (initial[1], initial[0], orders[-1, 0], initial[3], initial[4]))
    assert pub < first <= last and side in (-1, 1) and qty > 0
    feed = account['feed'][(account['feed'][:, 2] == cid) & (account['feed'][:, 7] == 1)]
    assert len(feed) == 1 and int(feed[0, 0]) == pub and int(feed[0, 3]) == side
    atr = float(feed[0, 9]); assert math.isfinite(atr) and atr > 0
    q = account['quotes']; n = len(account['record']['price']); risk = qty*atr*multiplier
    assert q['quote_valid'][pub] and q['quote_valid'][first]
    assert float(initial[5]) == float(q['ask' if side == 1 else 'bid'][first])
    published = view(account, pub, helper); entry = view(account, first, helper)
    feature = account['trade_features']['60'][pub]
    assert feature['candidate_raw_row'] == published['raw_row'] and feature['candidate_raw_seq'] == published['raw_seq']
    assert feature['known'] and feature['direction_votes'] >= 2 and feature['balance'] >= .25
    assert at(ledger['long_qty'], pub, n) == at(ledger['short_qty'], pub, n) == 0
    prior = at(ledger['liquidation_yen'], pub, n)
    goal = float(ledger['control']['目標']); loss = float(ledger['control']['損失予算'])
    anchor = ledger['goal_anchor']; first_qty = int(anchor['数量']); full = int(config['quantity'][symbol])
    assert goal == config['profit_goal_yen'][symbol]*first_qty/full
    assert loss == config['loss_budget_yen'][symbol]
    one_fee = helper.fee(qty, symbol); round_fee = 2*one_fee
    entry_price = float(initial[5]); exit0 = float(q['bid' if side == 1 else 'ask'][first])
    pub_spread = published['ask']-published['bid']; spread = entry['ask']-entry['bid']
    assert pub_spread > 0 and spread > 0
    need_entry = (goal-prior+round_fee)/(qty*multiplier)
    need_exit0 = need_entry+spread
    loss_entry = (loss+prior-round_fee)/(qty*multiplier)
    loss_exit0 = loss_entry-spread
    paid = sum(helper.fee(int(o[4]), symbol) for o in orders)
    gross = sum(-int(o[3])*int(o[4])*float(o[5])*multiplier for o in orders)
    assert sum(int(o[3])*int(o[4]) for o in orders) == 0
    assert np.isclose(gross, parent['粗損益'], rtol=0., atol=1e-5)
    assert paid == parent['費用'] and np.isclose(gross-paid, parent['収支'], rtol=0., atol=1e-5)
    assert sum(int(o[4]) for o in orders if o[7] == 0) == qty
    rows = ledger['sizing_events']; matching = rows[(rows[:, 0] == pub) & (rows[:, 1] == cid)]
    assert len(matching) == 1 and int(matching[0, 4]) == qty
    sizing = dict(zip(ledger['sizing_event_columns'], matching[0].tolist()))
    assert sizing['published_ATR'] == atr and bool(sizing['gate_accepted']) and bool(sizing['actual_pending'])
    last_path = side*(account['record']['price'][first:last+1]-entry_price)
    last_max, last_min = int(np.argmax(last_path)), int(np.argmin(last_path))
    valid = q['quote_valid'] & np.isfinite(q['bid']) & np.isfinite(q['ask']) & (q['bid'] > 0) & (q['ask'] > q['bid'])
    previous = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    assert np.all(previous[first:last+1] >= 0)
    exit_path = side*(q['bid' if side == 1 else 'ask'][previous[first:last+1]]-entry_price)
    exit_max, exit_min = int(np.argmax(exit_path)), int(np.argmin(exit_path))
    peak = helper.parent_path(ledger, account, cid)
    exits = [dict(判断=view(account, int(o[1]), helper), 約定=view(account, int(o[0]), helper),
        price=float(o[5]), q=int(o[4]), reason=int(o[6]), 理由=REASON.get(int(o[6]), '未分類保存reason'),
        floor料=helper.fee(int(o[4]), symbol)) for o in orders if o[7] == 0]
    result = dict(session=session, symbol=symbol, paper_parent=cid, side=side, 公開=published, 新規=entry,
        実新規価格=entry_price, 実初回q=qty, 初回受理アンカーq=first_qty, 通常全量=full,
        実q全量比=qty/full, アンカーq全量比=first_qty/full,
        初回か再参加='初回' if prior == 0 else '前親清算後の再参加', 公開時前親清算=prior,
        公開ATR=atr, 観測呼値=tick, ATR呼値数=atr/tick, R円=risk,
        公開W60=feature, 初回方向票数=int(feature['direction_votes']), 候補方向釣合い=float(feature['balance']),
        公開spread=pub_spread, 公開spread_ATR比=pub_spread/atr, 実fillspread=spread,
        実fillspread_ATR比=spread/atr, 公開予定往復料=round_fee, 公開予定往復料_R比=round_fee/risk,
        実往復料=paid, 実往復料_R比=paid/risk, 公開予定初期清算費用=qty*pub_spread*multiplier+round_fee,
        公開予定初期清算費用_R比=(qty*pub_spread*multiplier+round_fee)/risk,
        実fill初期清算費用=qty*spread*multiplier+round_fee,
        実fill初期清算費用_R比=(qty*spread*multiplier+round_fee)/risk,
        実fill時の返済側気配価格=exit0, 公開からfillの新規側不利移動呼値=side*(entry_price-(published['ask'] if side == 1 else published['bid']))/tick,
        保存利益線円=goal, 保存損失予算円=loss, 名目利益線_R比=goal/risk, 名目損失線_R比=loss/risk,
        残利益線_R比=(goal-prior)/risk, 残損失線_R比=(loss+prior)/risk,
        新規約定価格起点_全量一往復の必要利益値幅=need_entry,
        新規約定価格起点_必要利益呼値数=need_entry/tick,
        新規約定価格起点_必要利益呼値切上げ=math.ceil(need_entry/tick),
        新規約定価格起点_必要利益_ATR比=need_entry/atr,
        初期返済側気配起点_必要利益値幅=need_exit0,
        初期返済側気配起点_必要利益呼値数=need_exit0/tick,
        初期返済側気配起点_必要利益呼値切上げ=math.ceil(need_exit0/tick),
        初期返済側気配起点_必要利益_ATR比=need_exit0/atr,
        新規約定価格起点_全量一往復の損失許容逆行値幅=loss_entry,
        初期返済側気配起点_損失許容逆行値幅=loss_exit0,
        新規約定価格起点_損失許容_ATR比=loss_entry/atr,
        初期返済側気配起点_損失許容_ATR比=loss_exit0/atr,
        事後Last最大順行値幅=float(last_path[last_max]), 事後Last最大順行_ATR比=float(last_path[last_max]/atr),
        事後Last最大順行時刻=view(account, first+last_max, helper),
        事後Last最大逆行値幅=float(-last_path[last_min]), 事後Last最大逆行_ATR比=float(-last_path[last_min]/atr),
        事後Last最大逆行時刻=view(account, first+last_min, helper),
        事後清算側最大順行値幅=float(exit_path[exit_max]), 事後清算側最大順行_ATR比=float(exit_path[exit_max]/atr),
        事後清算側最大順行時刻=view(account, first+exit_max, helper),
        事後清算側最大逆行値幅=float(-exit_path[exit_min]), 事後清算側最大逆行_ATR比=float(-exit_path[exit_min]/atr),
        事後清算側最大逆行時刻=view(account, first+exit_min, helper),
        実親清算経路=peak, 実親=parent, 返済=exits, 部分返済あり=len(exits) > 1,
        当時数量判断=sizing,
        診断分類=dict(一度も費用後黒字なし=peak['事後の最大清算利益'] <= 0,
            費用後黒字を経て最終赤字=peak['事後の最大清算利益'] > 0 and parent['収支'] < 0,
            粗利が黒字で料により赤字=parent['粗損益'] > 0 and parent['収支'] < 0,
            前親赤字後の再参加=prior < 0),
        尺度留保='必要距離は実新規約定価格と初期返済側気配を区別。q全量一往復の算術であり実partial後の保証ではない。事後ピークは別出口の実現利益ではない。')
    return clean(result)


def distribution(rows: list, field: str) -> dict:
    """
    機能: 固定尺度の連続分布を記述する。
    引数: rows(list[dict])、field(str)は実親集合と既定尺度。
    返り値: dictは件数と五数要約。成績で閾値を選ばない。
    """
    a = np.asarray([r[field] for r in rows], dtype=float)
    if not len(a):
        return dict(件数=0)
    assert np.isfinite(a).all()
    return dict(件数=len(a), 最小=float(a.min()), 第1四分位=float(np.quantile(a, .25)),
        中央=float(np.median(a)), 第3四分位=float(np.quantile(a, .75)), 最大=float(a.max()))


def aggregate(rows: list) -> dict:
    """
    機能: 実親の金額/勝敗/当時尺度/事後分類を集計する。
    引数: rows(list[dict])は同じ比較群の完結実親。
    返り値: dictは保存実収支と記述分布。新金融を作らない。
    """
    fields = ('ATR呼値数', '実q全量比', '初回方向票数', '候補方向釣合い', '公開spread_ATR比',
        '実往復料_R比', '実fill初期清算費用_R比', '名目利益線_R比', '名目損失線_R比',
        '残利益線_R比', '残損失線_R比', '新規約定価格起点_必要利益呼値数',
        '初期返済側気配起点_必要利益呼値数', '初期返済側気配起点_必要利益_ATR比',
        '新規約定価格起点_損失許容_ATR比', '事後Last最大順行_ATR比', '事後Last最大逆行_ATR比',
        '公開からfillの新規側不利移動呼値')
    return dict(親数=len(rows), 勝ち=sum(r['実親']['収支'] > 0 for r in rows),
        負け=sum(r['実親']['収支'] < 0 for r in rows), 粗損益=sum(r['実親']['粗損益'] for r in rows),
        費用=sum(r['実親']['費用'] for r in rows), 収支=sum(r['実親']['収支'] for r in rows),
        出口理由=dict(Counter(e['理由'] for r in rows for e in r['返済'])),
        部分返済親数=sum(r['部分返済あり'] for r in rows),
        診断分類={k: sum(r['診断分類'][k] for r in rows) for k in ('一度も費用後黒字なし', '費用後黒字を経て最終赤字', '粗利が黒字で料により赤字', '前親赤字後の再参加')},
        尺度={field: distribution(rows, field) for field in fields})


def run() -> None:
    """
    機能: 根が授権した全33保存packetと42活動台帳を一読し、43実親の小射影を保存する。
    引数: なし。
    返り値: None。金融source・原板・NPZ・API・公開へ触れない。
    """
    plan_path = HERE/'同母二商品差の診断固定計画.json'
    plan = json.loads(plan_path.read_text(encoding='utf-8-sig'))
    for group in ('source_SHA256', '小資料', '金融source_SHA256'):
        assert all(digest(ROOT/p) == sha for p, sha in plan[group].items())
    write('診断開始.json', dict(全合格=True, 計画SHA256=digest(plan_path), 根授権='固定後33packet/42活動台帳の目的別各一読', 新金融=0))
    helper_path = ROOT/'work/wave_v106/e01_trade_gate/diagnosis/tools.py'
    spec = importlib.util.spec_from_file_location('同母保存親の純診断', helper_path)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    counts = Counter(); observations = []; sessions = {}
    for session in plan['sessions']:
        packet = checked(plan['input_cache'][session], counts, '因果packet')
        assert packet['session'] == session
        for symbol in ('TOPIX', 'NK225'):
            key = session+'|'+symbol
            if key in plan['inactive_metadata']:
                sessions[key] = plan['inactive_metadata'][key]
                continue
            ledger = checked(plan['active_ledgers'][key], counts, '対象goal活動台帳')
            account = packet['accounts'][symbol]
            assert ledger['key'] == (session, symbol)
            assert clean(ledger['goal_anchor']) == plan['boundary'][key]['anchor']
            saved = helper.parents(ledger)
            assert len(saved) == plan['rows'][key]['親数']
            assert all(ledger['summary'][field] == plan['rows'][key][field] for field in ('利益', '損失', '収支', '費用', '新規枚数'))
            own = [observation(session, ledger, account, saved[cid], plan['config'], helper) for cid in sorted(saved)]
            observations.extend(own)
            sessions[key] = dict(row=plan['rows'][key], boundary=plan['boundary'][key],
                実親=[r['paper_parent'] for r in own], 実注文数=len(ledger['orders']),
                元台帳SHA256=plan['active_ledgers'][key]['SHA256'], 保存停止=clean(ledger['control']))
        del packet
        print(session+' 同母実親を射影、金融0。', flush=True)
    assert counts['因果packet'] == 33 and counts['対象goal活動台帳'] == 42
    assert len(observations) == 43 and len(sessions) == 66
    groups = {}
    for symbol in ('TOPIX', 'NK225'):
        own = [r for r in observations if r['symbol'] == symbol]
        groups[symbol] = dict(全親=aggregate(own),
            勝親=aggregate([r for r in own if r['実親']['収支'] > 0]),
            負親=aggregate([r for r in own if r['実親']['収支'] < 0]),
            買い=aggregate([r for r in own if r['side'] == 1]),
            売り=aggregate([r for r in own if r['side'] == -1]),
            Day=aggregate([r for r in own if r['session'].endswith('_Day')]),
            Night=aggregate([r for r in own if r['session'].endswith('_Night')]))
        expected = plan['expected'][symbol]; got = groups[symbol]['全親']
        assert got['親数'] == expected['親数'] and got['勝ち'] == expected['勝ち親'] and got['負け'] == expected['負け親']
        assert np.isclose(got['収支'], expected['収支'], atol=1e-5, rtol=0.) and got['費用'] == expected['費用']
    worst = {s: [dict(row=r, 実親=[o for o in observations if o['session'] == r['session'] and o['symbol'] == s])
                for r in plan['赤字上位三場'][s]] for s in ('TOPIX', 'NK225')}
    for group in ('source_SHA256', '金融source_SHA256'):
        assert all(digest(ROOT/p) == sha for p, sha in plan[group].items())
    write('同母二商品43実親の原因射影.json', dict(全合格=True, 条件ID=plan['条件ID'],
        計画SHA256=digest(plan_path), source_SHA256=plan['source_SHA256'], 金融source_SHA256=plan['金融source_SHA256'],
        source開始終端一致=True, 分母=plan['分母'], 実親=observations, 集計=groups,
        場別=sessions, 赤字上位最大三場=worst, 元入口別保存比較=plan['旧full入口別保存比較'],
        一読記録=dict(counts), 新金融=0, 原板=0, NPZ=0, API=0, 公開変更=0, 共通知見変更=0,
        注意=plan['因果留保']+['全量一往復の必要距離は新規約定価格と初期返済側気配の起点を明示。partial後の保証ではない。',
            '事後MFE/MAEや親ピークを別出口の実現収支へ加えない。実policy後のGU suffixは未実施。']))
    print('TOP19/NK24の原行・会計・尺度・事後経路照合が完了。', flush=True)


def main() -> None:
    """
    機能: 根授権後の固定一読診断だけを開始する。
    引数: CLI --root-reviewed(bool)は根の授権済み操作。
    返り値: None。失敗時は保存し、自動再開始しない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--root-reviewed', action='store_true')
    assert parser.parse_args().root_reviewed
    assert not (HERE/'診断開始.json').exists() and not (HERE/'診断False.json').exists()
    try:
        run()
    except Exception:
        write('診断False.json', dict(全合格=False, 原因=traceback.format_exc(), 自動再開始=False, 新金融=0))
        raise


if __name__ == '__main__':
    main()
