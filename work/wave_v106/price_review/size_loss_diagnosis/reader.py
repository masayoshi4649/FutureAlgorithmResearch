"""数量縮小の保存台帳を、選定場だけ一読して損失原因と旧勝ち反証へ分解する。"""

import argparse
from collections import Counter
from datetime import datetime, timezone, timedelta
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
ROOT = HERE.parents[3]
CID = 'E01_SIZE_W60_VETO_D0_P2_L2_A1'
RESULT = 'work/wave_v106/e01_risk_sizing/finance/結果.json'
RESULT_SHA = '2f6d414138c37e53887b0b893a50f7cea360c69695eda6a4e1cf9990a17b5beb'
FIXED = 'work/wave_v106/e01_risk_sizing/金融事前固定.json'
HELPER = 'work/wave_v106/e01_trade_gate/diagnosis/tools.py'
VALUE = {'TOPIX': 1000., 'NK225': 10.}
TICK = {'TOPIX': .5, 'NK225': 10.}


def digest(path: Path) -> str:
    """
    機能: 小metadata及びsourceの指紋を求める。
    引数: path(Path)は対象位置。
    返り値: strはSHA256。大型入力の事前走査には使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def small(path: str) -> dict:
    """
    機能: 小結果JSONを読む。
    引数: path(str)はroot相対位置。
    返り値: dictは保存metadata。金融や原板は呼ばない。
    """
    return json.loads((ROOT/path).read_text(encoding='utf-8-sig'))


def write(name: str, value: dict) -> None:
    """
    機能: 自所有域へ新規の小診断だけを保存する。
    引数: name(str)、value(dict)は新位置と内容。
    返り値: None。既存source・結果・台帳を変更しない。
    """
    path = HERE/name
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8', newline='\n')


def fix() -> None:
    """
    機能: 六最悪商品場と各商品最大の同親勝ち赤字化例を小metadataだけで固定する。
    引数: なし。
    返り値: None。選定六packet・二十一台帳はまだ読まない。
    """
    result, fixed = small(RESULT), small(FIXED)
    assert result['全合格'] and digest(ROOT/RESULT) == RESULT_SHA
    selected = {}
    worst, turned = {}, {}
    for symbol in ('TOPIX', 'NK225'):
        rows = [r for r in result['results'][CID]['rows'] if r['symbol'] == symbol and r['収支'] < 0]
        worst[symbol] = sorted(rows, key=lambda r: (r['収支'], r['session']))[:3]
        changed = [dict(session=c['session'], symbol=symbol, **p) for c in result['各場寄与'][CID]
                   if c['symbol'] == symbol for p in c['比較別']['旧P1L8']['元勝ち親が赤字化']]
        turned[symbol] = sorted(changed, key=lambda p: (p['new_net']-p['old_net'], p['session'], p['parent']))[0]
        for row in worst[symbol]+[turned[symbol]]:
            selected[row['session']+'|'+symbol] = dict(session=row['session'], symbol=symbol)
    assert len(selected) == 7 and len({v['session'] for v in selected.values()}) == 6
    new_specs = {r['session']+'|'+r['symbol']: r for r in result['results'][CID]['ledgers']}
    changes = {r['session']+'|'+r['symbol']: r['比較別'] for r in result['各場寄与'][CID]}
    for key, value in selected.items():
        value['ledgers'] = dict(新数量=new_specs[key])
        for kind in ('同額固定数量L2', '旧P1L8'):
            ref = fixed['comparisons'][CID][kind]
            value['ledgers'][kind] = ref['ledgers'][key]
        value['元保存五寄与'] = {k: changes[key][k] for k in ('同額固定数量L2', '旧P1L8')}
    sources = {Path(__file__).relative_to(ROOT).as_posix(): digest(Path(__file__)), HELPER: digest(ROOT/HELPER)}
    write('固定診断計画.json', dict(全合格=True, 条件ID=CID,
        目的='数量縮小後に旧利益を取れず、元GU撤回・後入口入替・q0で損失又は活動消失が起きた具体時点の読取診断',
        選定='商品別新赤字収支の下位三場。同値は場名順。旧P1L8同親勝ち→新負けの最大悪化を各商品一例。',
        最悪三場=worst, 同親勝ち赤字化例=turned, selected=selected,
        input_cache={s: fixed['input_cache'][s] for s in sorted({v['session'] for v in selected.values()})},
        小metadata={RESULT: RESULT_SHA, FIXED: digest(ROOT/FIXED)}, source_SHA256=sources,
        新source_SHA256=result['source_SHA256'], config=next(c for c in result['configs'] if c['id'] == CID),
        一読上限=dict(選定packet=6, 選定新台帳=7, 選定旧L2台帳=7, 選定旧P1L8台帳=7),
        内容=['同normal/rawseq/時刻の公開・entry・exit、実q、公開ATR、実PL、絶対goalまでの単一保有必要値幅',
              '実親期間の自己Last最大順行と実UID料込み清算ピーク',
              '共通親・消え親・追加親で旧L2と旧P1L8の五寄与を再検算',
              '旧勝ち期間の小q全量保持を事後参考に測る。将来値を判断に使わず、新金融結果へ加算しない。'],
        範囲='政策停止後のsizing_events/GUは影として明記。実利益又は実追加玉へ合算しない。',
        新金融=0, 原paper再計算=0, 原板=0, NPZ=0, API=0, 台帳又はpacket事前読取=0))
    print('6packet/7商品場/21台帳の目的とsourceを固定、まだ大型読取0。', flush=True)


def checked(item: dict, counts: Counter, name: str) -> dict:
    """
    機能: 固定した保存packet又は台帳を同bytes一回だけ読む。
    引数: item(dict)、counts(Counter)、name(str)は位置/指紋と一読種別。
    返り値: dictは保存資料。JIT・金融・APIを実行しない。
    """
    path = ROOT/item['path']
    assert path.resolve().is_relative_to(ROOT/'work')
    assert not counts['path:'+item['path']]
    saved = path.read_bytes()
    assert hashlib.sha256(saved).hexdigest() == item['SHA256']
    counts['path:'+item['path']] += 1
    counts[name] += 1
    return pickle.loads(gzip.decompress(saved))


def expand(value: object, count: int) -> np.ndarray:
    """
    機能: 保存plateauを前方保持で復元する。
    引数: value(object)、count(int)は圧縮資料又は配列とnormal行数。
    返り値: ndarrayは保存時価等。新約定・新判断を作らない。
    """
    if isinstance(value, np.ndarray):
        assert len(value) == count
        return value
    assert value['length'] == count and value['rows'][0] == 0
    return value['values'][np.searchsorted(value['rows'], np.arange(count), side='right')-1]


def observation(ledger: dict, account: dict, cid: int, goal: float, helper: object) -> dict:
    """
    機能: 実親の公開、数量選択、実新規、返済、事後ピークと必要値幅を保存する。
    引数: ledger/account(dict)、cid(int)、goal(float)、helper(module)は同保存実親と絶対目標。
    返り値: dictは当時判断と事後参考。別出口や再entryを実行しない。
    """
    parent = helper.parents(ledger)[cid]
    orders = ledger['orders'][ledger['orders'][:, 2] == cid]
    new = orders[orders[:, 7] == 1]
    assert len(new) == 1
    initial = new[0]
    pub, first, last, side, quantity = map(int, (initial[1], initial[0], orders[-1, 0], initial[3], initial[4]))
    feed = account['feed'][(account['feed'][:, 2] == cid) & (account['feed'][:, 7] == 1)]
    assert len(feed) == 1 and int(feed[0, 0]) == pub and int(feed[0, 3]) == side
    q = account['quotes']; n = len(account['record']['price'])
    assert pub < first <= last
    prior = float(expand(ledger['liquidation_yen'], n)[pub])
    assert expand(ledger['long_qty'], n)[pub] == expand(ledger['short_qty'], n)[pub] == 0
    width = (goal-prior+2*helper.fee(quantity, account['symbol']))/(quantity*VALUE[account['symbol']])
    own = side*(account['record']['price'][first:last+1]-initial[5])
    best = first+int(np.argmax(own))
    sizing = []
    if 'sizing_events' in ledger:
        rows = ledger['sizing_events']; match = rows[(rows[:, 0] == pub) & (rows[:, 1] == cid)]
        assert len(match) == 1 and int(match[0, 4]) == quantity
        sizing = dict(zip(ledger['sizing_event_columns'], match[0].tolist()))
        assert int(sizing['side']) == side and sizing['published_ATR'] == float(feed[0, 9])
    result = dict(親=cid, side=side, 実初回q=quantity, 元paper初回q=int(feed[0, 4]),
        公開=helper.clock(account, pub), 公開raw_row=int(account['mapping'][pub]),
        公開ATR=float(feed[0, 9]), 公開Last=float(feed[0, 5]),
        公開bid=float(q['bid'][pub]), 公開ask=float(q['ask'][pub]), 公開W60=account['trade_features']['60'][pub],
        新規=helper.clock(account, first), 実新規価格=float(initial[5]),
        返済=[dict(判断=helper.clock(account, int(o[1])), 約定=helper.clock(account, int(o[0])),
                   price=float(o[5]), q=int(o[4]), reason=int(o[6])) for o in orders if o[7] == 0],
        保存完結親=parent, 公開時の前親累積清算=prior, 保存政策目標=ledger['control']['目標'], 比較用新P2絶対利益目標=goal,
        全量保持と一往復だけの場合の目標必要順行値幅=width, 目標必要呼値=width/TICK[account['symbol']],
        目標必要順行_呼値切上げ=math.ceil(max(0., width)/TICK[account['symbol']])*TICK[account['symbol']],
        当時数量判断=sizing, 自己Last最大順行値幅=float(own.max()), 自己Last最大順行時刻=helper.clock(account, best),
        実親清算ピーク=helper.parent_path(ledger, account, cid),
        原行照合=dict(candidate_raw_row=account['trade_features']['60'][pub]['candidate_raw_row'],
                      candidate_raw_seq=account['trade_features']['60'][pub]['candidate_raw_seq']))
    assert result['原行照合']['candidate_raw_row'] == result['公開raw_row']
    assert result['原行照合']['candidate_raw_seq'] == result['公開']['raw_seq']
    return result


def absent(ledger: dict, old: dict, account: dict, cid: int, helper: object) -> dict:
    """
    機能: 消えた旧実親を数量0・政策場停止・busy等の保存証拠へ対応する。
    引数: ledger/old/account(dict)、cid(int)、helper(module)は新旧同親の保存資料。
    返り値: dictは原因と公開記録。shadowの数量0を実損益と呼ばない。
    """
    initial = old['orders'][(old['orders'][:, 2] == cid) & (old['orders'][:, 7] == 1)]
    assert len(initial) == 1
    pub = int(initial[0, 1]); control = ledger['control']
    result = dict(親=cid, 旧親=helper.parents(old)[cid], 公開=helper.clock(account, pub), 原因='追加原因未確認')
    if control.get('発動') and pub > control['判断行']:
        result['原因'] = '実政策の場停止後。後続sizingは影であり実数量審査ではない'
        result['停止'] = control
        return result
    s = ledger['sizing_events']; rows = s[(s[:, 0] == pub) & (s[:, 1] == cid)]
    if len(rows):
        assert len(rows) == 1
        r = dict(zip(ledger['sizing_event_columns'], rows[0].tolist()))
        result['当時数量判断'] = r
        if not r['gate_accepted']:
            result['原因'] = '元公開gate拒否'
        elif r['selected_actual_quantity'] == 0 and not r['actual_pending']:
            result['原因'] = '予定額又は未知による数量0' if r['size_reason'] in (96, 97) else '数量0、理由は別記'
        else:
            proof = ledger['limit_events']
            records = proof[(proof[:, 2] == cid) & (proof[:, 1] == 1)]
            result['保存公開証跡'] = records.tolist()
            if len(records) and records[0, 14] and records[0, 17] == 94:
                result['原因'] = '実保有又は予約busy'
    return result


def oldwin_reference(new: dict, old: dict, account: dict, cid: int, goal: float, helper: object) -> dict:
    """
    機能: 同じ旧勝ちの期間を新実qで全量保持した場合の事後評価尺度だけを測る。
    引数: new/old/account(dict)、cid(int)、goal(float)、helper(module)は同共通親と固定目標。
    返り値: dictは時点比較と事後参考。仮想の新収支として合算しない。
    """
    a = old['orders'][old['orders'][:, 2] == cid]; b = new['orders'][new['orders'][:, 2] == cid]
    af, bf = a[a[:, 7] == 1][0], b[b[:, 7] == 1][0]
    assert int(af[0]) == int(bf[0]) and int(af[1]) == int(bf[1]) and af[5] == bf[5] and af[3] == bf[3]
    start, end, q, side = map(int, (af[0], a[-1, 0], bf[4], bf[3]))
    quotes = account['quotes']; symbol = account['symbol']; n = len(quotes['bid'])
    valid = quotes['quote_valid'] & np.isfinite(quotes['bid']) & np.isfinite(quotes['ask']) & (quotes['bid'] > 0) & (quotes['ask'] > quotes['bid'])
    prior = np.maximum.accumulate(np.where(valid, np.arange(n), -1))
    assert np.all(prior[start:end+1] >= 0)
    liquidation_price = quotes['bid' if side == 1 else 'ask'][prior[start:end+1]]
    reference = side*(liquidation_price-bf[5])*q*VALUE[symbol]-2*helper.fee(q, symbol)
    peak = start+int(np.argmax(reference)); old_decision = int(a[-1, 1])
    actual_curve = expand(new['liquidation_yen'], n)
    return dict(旧親=helper.parents(old)[cid], 新親=helper.parents(new)[cid],
        同一公開及び実新規=True, 旧最終返済判断=helper.clock(account, old_decision),
        旧最終返済約定=helper.clock(account, end), 旧返済判断時の新実口座清算=float(actual_curve[old_decision]),
        同時点での絶対目標不足=goal-float(actual_curve[old_decision]),
        新q全量保持の事後最大清算参考=float(reference.max()), 参考最大時刻=helper.clock(account, peak),
        旧最終返済時点の新q全量保持参考=float(reference[-1]),
        注意='同じ新規から旧親期間末までq一定と一往復料を評価した事後尺度。部分返済・新規条件・実政策は再生せず、新収益でも実現可能な別出口でもない。')


def run() -> None:
    """
    機能: root確認後に選定六packetと二十一台帳を各一読し、具体損失・反証を保存する。
    引数: なし。
    返り値: None。保存診断のみ。原板・NPZ・金融再生を呼ばない。
    """
    plan = small((HERE/'固定診断計画.json').relative_to(ROOT).as_posix())
    assert all(digest(ROOT/p) == sha for p, sha in plan['source_SHA256'].items())
    assert all(digest(ROOT/p) == sha for p, sha in plan['小metadata'].items())
    assert all(digest(ROOT/p) == sha for p, sha in plan['新source_SHA256'].items())
    write('診断開始.json', dict(全合格=True, 計画SHA256=digest(HERE/'固定診断計画.json'), 新金融=0))
    spec = importlib.util.spec_from_file_location('保存台帳の純診断', ROOT/HELPER)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    counts = Counter(); scenes = {}
    for session, item in plan['input_cache'].items():
        packet = checked(item, counts, '選定packet')
        assert packet['session'] == session
        for key, selected in plan['selected'].items():
            if selected['session'] != session:
                continue
            symbol = selected['symbol']; account = packet['accounts'][symbol]
            ledgers = {kind: checked(ref, counts, kind+'台帳') for kind, ref in selected['ledgers'].items()}
            new = ledgers['新数量']; goal = plan['config']['profit_goal_yen'][symbol]
            assert new['key'] == (session, symbol)
            own = dict(新=new['summary'], 政策停止=new['control'], 比較={}, 新実親=[],
                       影GU注意='sizing_events/limit_events/GUは政策停止後も保存される。実注文採否と区別する。')
            for parent in new['parent']:
                own['新実親'].append(observation(new, account, int(parent['親']), goal, helper))
            for kind in ('同額固定数量L2', '旧P1L8'):
                old = ledgers[kind]
                assert old['key'] == new['key']
                delta = helper.contribution(old, new)
                renamed = {('共通入口の数量/出口差' if k == '共通入口の出口変化' else k): v for k, v in delta.items()}
                for field in ('収支変化', '避けた基準損失', '失った基準利益', '共通入口の数量/出口差', '新たな入口の収支'):
                    assert np.isclose(renamed[field], selected['元保存五寄与'][kind][field], atol=1e-5, rtol=0.)
                a, b = helper.parents(old), helper.parents(new)
                own['比較'][kind] = dict(旧=old['summary'], 五寄与=renamed,
                    消えた旧実親=[absent(new, old, account, cid, helper) for cid in delta['消えた親']],
                    共通実親=[dict(親=cid, 旧=observation(old, account, cid, goal, helper),
                                   新収支=b[cid]['収支'], 旧収支=a[cid]['収支']) for cid in delta['共通親']],
                    新参加親の旧停止理由=[dict(親=cid, 旧政策停止=old['control'],
                        新公開=helper.clock(account, int(new['orders'][(new['orders'][:, 2] == cid) & (new['orders'][:, 7] == 1)][0, 1])))
                        for cid in delta['新しい親']])
            chosen = plan['同親勝ち赤字化例'][symbol]
            if chosen['session'] == session:
                own['旧勝ち赤字化の事後参考'] = oldwin_reference(new, ledgers['旧P1L8'], account, chosen['parent'], goal, helper)
            scenes[key] = own
        del packet
        print(session+' 選定保存台帳の原行・ピーク・五寄与を診断、新金融0。', flush=True)
    assert counts['選定packet'] == 6 and all(counts[k+'台帳'] == 7 for k in ('新数量', '同額固定数量L2', '旧P1L8'))
    assert len(scenes) == 7
    assert all(digest(ROOT/p) == sha for p, sha in plan['source_SHA256'].items())
    write('最悪六場と旧勝ち赤字化二例の具体診断.json', dict(全合格=True,
        計画SHA256=digest(HERE/'固定診断計画.json'), source_SHA256=plan['source_SHA256'], 条件ID=CID,
        最悪三場=plan['最悪三場'], 同親勝ち赤字化例=plan['同親勝ち赤字化例'], 場別=scenes,
        一読記録=dict(counts), 新金融=0, 原板=0, NPZ=0, API=0, 旧paper再計算=0,
        注意='保存済み実結果と事後参考の診断。旧四赤字入口q0だけで新利益へ置き換えない。'))


def main() -> None:
    """
    機能: 小metadata固定又はroot確認済み一読診断を選ぶ。
    引数: CLI --fix/--root-reviewed(bool)。
    返り値: None。失敗記録は保持し、自動再開始しない。
    """
    parser = argparse.ArgumentParser(); parser.add_argument('--fix', action='store_true'); parser.add_argument('--root-reviewed', action='store_true')
    args = parser.parse_args(); assert args.fix != args.root_reviewed
    if args.fix:
        fix(); return
    assert not (HERE/'診断開始.json').exists() and not (HERE/'診断False.json').exists()
    try:
        run()
    except Exception:
        write('診断False.json', dict(全合格=False, 原因=traceback.format_exc(), 自動再開始=False, 新金融=0))
        raise


if __name__ == '__main__':
    main()
