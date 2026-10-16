"""保存済み第三段階の入口変更と、その後の価格経路を診断する。売買を再生しない。"""
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
import importlib.util
import json
import pickle
import sys
import numpy as np

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ROUND = HERE.parent / 'round3'
JST = timezone(timedelta(hours=9))


def module(name, path):
    """
    機能: 保存資料の読取関数だけを固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


helper = module('wave87_entry_analysis_helper', ROOT / 'work/wave_v86/analysis/independent.py')


def stamp(value):
    """
    機能: 保存された代理時計を日本時間で表示する。
    引数: value(float)。
    返り値: str。
    """
    return datetime.fromtimestamp(float(value), JST).isoformat()


def finite(value):
    """
    機能: 欠測値をJSONのnullへ変換する。
    引数: value(float)。
    返り値: float又はNone。
    """
    return float(value) if np.isfinite(value) else None


def pending_at(account, row):
    """
    機能: 疎な証跡から待機方向・極値・公開可否・注文線だけを復元する。
    引数: account(dict)、row(int)。
    返り値: ndarray又はNone。支持元は疎イベントから補間せず別特徴を読む。
    """
    events = account['support_events']
    index = np.searchsorted(events[:, 0], row, side='right') - 1
    return events[index, :5] if index >= 0 else None


def snapshot(short, ready, row, side, extreme):
    """
    機能: 約定より前の公開判断行だけで支持と極値の前後関係を記録する。
    引数: short/ready(dict)、row/side/extreme(int)。
    返り値: dict。年齢はCurrentPriceTime代理時計差である。
    """
    output = dict(row=int(row), raw_seq=int(ready['seq'][row]), jst=stamp(ready['time_s'][row]))
    for market in ('self', 'peer'):
        valid = bool(short[market+'_valid'][row])
        value = short[market+'_value'][row]
        release = short[market+'_release_time'][row]
        source = short[market+'_source_time'][row]
        output[market] = dict(valid=valid, value_atr=finite(value), supports=bool(valid and side*value > .05),
            source_seq=int(short[market+'_source_seq'][row]), source_time=finite(source),
            release_seq=int(short[market+'_release_seq'][row]), release_time=finite(release),
            endpoint_age_seconds=finite(ready['time_s'][row]-source),
            release_age_seconds=finite(ready['time_s'][row]-release),
            endpoint_after_extreme=bool(extreme >= 0 and
                (short['self_source_seq'][row] > ready['seq'][extreme] if market == 'self'
                 else source > ready['time_s'][extreme])))
    if not output['self']['valid']:
        group = '自己最新支持が欠測'
    elif not output['self']['supports']:
        group = '自己最新支持が方向を支持せず'
    elif not output['self']['endpoint_after_extreme']:
        group = '自己最新支持はあるが終端は極値以前又は同じ'
    else:
        group = '自己最新支持の終端が極値後'
    output['支持区分'] = group
    return output


def annotate(ledgers, result, inputs, shorts):
    """
    機能: 親組へ入口以前の根拠と、保有中の事後経路を別項目で付加する。
    引数: ledgers/result/inputs/shorts(dict)。
    返り値: list[dict]。事後経路で売買条件を再選択しない。
    """
    campaigns = helper.extract(ledgers, result)
    for c in campaigns:
        key = (c['session'], c['symbol'])
        r, a, short = inputs[key], ledgers[key], shorts[key]
        cycle = next(x for x in a['cycles'] if int(x[0]) == c['campaign'])
        entry, end, side, atr = int(cycle[1]), int(cycle[2]), c['direction'], float(cycle[5])
        prep = a['entry_preparations'][a['entry_preparations'][:, 1] == entry]
        assert len(prep) == 1, (key, c['campaign'], '準備対応')
        prep_row = int(prep[0, 3])
        orders = a['orders'][(a['orders'][:, 2] == c['campaign']) & (a['orders'][:, 7] == 1)]
        first = orders[np.argmin(orders[:, 0])]
        slots = a['slot_events'][(a['slot_events'][:, 0] == entry) &
            (a['slot_events'][:, 2] == c['campaign']) & (a['slot_events'][:, 4] == 1)]
        assert len(slots) and len(np.unique(slots[:, 10])) == 1
        plan_row = int(slots[0, 10])
        assert plan_row < entry and int(first[1]) < entry
        pending = pending_at(a, plan_row)
        assert pending is not None and int(pending[1]) == side and int(pending[3]) == 1
        extreme = int(pending[2])
        assert 0 <= extreme <= plan_row
        before = snapshot(short, r, plan_row, side, extreme)
        fill = snapshot(short, r, entry, side, extreme)
        price = float(first[5])
        path = side*(r['last'][entry:end+1]-price)/atr
        valid = np.isfinite(path) & (r['last'][entry:end+1] > 0)
        assert valid.any()
        favorable = np.flatnonzero(valid & (path >= .75))
        adverse = np.flatnonzero(valid & (path <= -.75))
        first_up = int(favorable[0]) if len(favorable) else None
        first_down = int(adverse[0]) if len(adverse) else None
        if first_down is not None and (first_up is None or first_down < first_up):
            outcome = '0.75ATR順行より先に0.75ATR逆行'
        elif first_up is not None and (first_down is None or first_up < first_down):
            outcome = '0.75ATR逆行より先に0.75ATR順行'
        else:
            outcome = '返済まで双方の基準幅に届かず'
        reached = np.flatnonzero(valid & (path >= a['settings']['activation_atr']))
        c.update(entry_row=entry, exit_row=end, prepare_row=prep_row,
            prepare_seq=int(r['seq'][prep_row]), prepare_jst=stamp(r['time_s'][prep_row]),
            order_source_row=int(first[1]), order_source_jst=stamp(r['time_s'][int(first[1])]),
            plan_row=plan_row, extreme_row=extreme, extreme_seq=int(r['seq'][extreme]),
            extreme_jst=stamp(r['time_s'][extreme]), extreme_price=float(r['last'][extreme]),
            entry_jst=stamp(r['time_s'][entry]), exit_jst=stamp(r['time_s'][end]),
            entry_price=price, atr=atr, entry_distance_from_extreme_atr=float(side*(price-r['last'][extreme])/atr),
            preparation_to_entry_seconds=float(r['time_s'][entry]-r['time_s'][prep_row]),
            order_source_to_entry_seconds=float(r['time_s'][entry]-r['time_s'][int(first[1])]),
            prior_published=before, fill_observation=fill,
            posthoc=dict(mfe_atr=float(np.max(path[valid])), mae_atr=float(-np.min(path[valid])),
                barrier_order=outcome, trail_activation_atr=float(a['settings']['activation_atr']),
                trail_activation_reached=bool(len(reached)),
                adverse_before_favorable_seconds=float(r['time_s'][entry+first_down]-r['time_s'][entry])
                    if first_down is not None else None,
                support_disappeared_at_fill=bool(before['self']['supports'] and not fill['self']['supports'])))
    return campaigns


def prepare_key(c):
    """
    機能: 同じ準備の原本行と方向だけで対応キーを作る。
    引数: c(dict)。
    返り値: tuple。
    """
    return c['session'], c['symbol'], c['prepare_seq'], c['direction']


def removal_state(c, after, after_ledgers, inputs):
    """
    機能: 旧入口が消えた時点の新手法の状態を、支持取消と保有経路差に分ける。
    引数: c(dict)、after(list[dict])、after_ledgers/inputs(dict)。
    返り値: str。消失をすべて支持フィルターの直接効果とは呼ばない。
    """
    key = c['session'], c['symbol']
    if any(x['entry_row'] <= c['entry_row'] <= x['exit_row'] for x in after
           if (x['session'], x['symbol']) == key):
        return '別の組の保有経路に置換'
    a, r = after_ledgers[key], inputs[key]
    prep = a['prepare_events'][a['prepare_events'][:, 1] <= c['plan_row']]
    if not len(prep) or int(r['seq'][int(prep[-1, 1])]) != c['prepare_seq'] or int(prep[-1, 2]) != c['direction']:
        return '同じ準備が存在せず又は別準備へ移行'
    state = pending_at(a, c['plan_row'])
    if state is None or int(state[1]) == 0:
        return '同じ準備の待機が終了'
    return '同じ準備で支持条件により非公開' if not bool(state[3]) else '同じ準備で注文公開中だが別の約定経路'


def compare(before, after, after_ledgers, inputs, symbol, sessions):
    """
    機能: 入口の同一・追加・消失と同準備の時点変更を金額で照合する。
    引数: before/after(list[dict])、after_ledgers/inputs(dict)、symbol(str)、sessions(set[str])。
    返り値: dict。対応は時系列比較であり完全な因果分解ではない。
    """
    left = {helper.entry_key(c): c for c in before if c['symbol'] == symbol and c['session'] in sessions}
    right = {helper.entry_key(c): c for c in after if c['symbol'] == symbol and c['session'] in sessions}
    common = left.keys() & right.keys()
    removed = [left[k] for k in left.keys()-right.keys()]
    added = [right[k] for k in right.keys()-left.keys()]
    pairs_left, pairs_right = defaultdict(list), defaultdict(list)
    for c in removed: pairs_left[prepare_key(c)].append(c)
    for c in added: pairs_right[prepare_key(c)].append(c)
    shifted = []
    for key in pairs_left.keys() & pairs_right.keys():
        if len(pairs_left[key]) != 1 or len(pairs_right[key]) != 1:
            continue
        b, a = pairs_left[key][0], pairs_right[key][0]
        shifted.append(dict(session=a['session'], symbol=symbol, direction=a['direction'],
            prepare_seq=a['prepare_seq'], before_entry=b['entry'], after_entry=a['entry'],
            before_jst=b['entry_jst'], after_jst=a['entry_jst'],
            delay_seconds=a['entry_time']-b['entry_time'], row_shift=a['entry_row']-b['entry_row'],
            unfavorable_price_change=a['direction']*(a['entry_price']-b['entry_price']),
            before_net=b['net'], after_net=a['net'], net_change=a['net']-b['net']))
    causes = defaultdict(list)
    for c in removed: causes[removal_state(c, after, after_ledgers, inputs)].append(c)
    value = dict(共通元=helper.summarize([left[k] for k in common]),
        共通新=helper.summarize([right[k] for k in common]),消失=helper.summarize(removed),追加=helper.summarize(added),
        消失時の新手法状態={k:helper.summarize(v) for k,v in causes.items()},同準備の入口変更=shifted)
    delta = sum(x['net'] for x in right.values())-sum(x['net'] for x in left.values())
    reconstructed = value['共通新']['net']-value['共通元']['net']+value['追加']['net']-value['消失']['net']
    assert abs(delta-reconstructed) < 1e-6
    value['収支差'] = delta
    value['差分会計一致'] = True
    return value


def main():
    """
    機能: 二十結果が揃った後だけ、保存台帳と当時の特徴を読み独立診断する。
    引数: なし。
    返り値: None。保存先は今回analysis配下だけ。
    """
    fixed = helper.read(ROUND/'事前固定.json')
    identifiers = [c['id'] for c in fixed['catalog']]
    missing = [str(ROUND/m/'results'/(i+'.json')) for m in fixed['models'] for i in identifiers
               if not (ROUND/m/'results'/(i+'.json')).exists()]
    if missing:
        raise RuntimeError('全二十結果の完了待ち: '+str(len(missing))+'件')
    prepare = module('wave87_diagnostic_prepare', ROOT/'work/wave_v85/prepare.py')
    inputs, unused_signals, hashes = prepare.load_inputs(verify=True)
    del unused_signals
    assert hashes == fixed['input_SHA256']
    short_prepare = module('wave87_diagnostic_short', ROUND/'prepare.py')
    shorts, proof = short_prepare.load(verify=True)
    sources = {str(ROUND/'prepared/short.pkl'):proof['出力SHA256']}
    comparisons, groups, details, worst = [], [], [], []
    for model in fixed['models']:
        accounts, campaigns = {}, {}
        for ident in identifiers:
            result_path = ROUND/model/'results'/(ident+'.json')
            ledger_path = ROUND/model/'ledgers'/(ident+'.pkl')
            result = helper.read(result_path)
            assert helper.sha(ledger_path) == result['ledger_SHA256']
            account = pickle.loads(ledger_path.read_bytes())
            accounts[ident] = account
            campaigns[ident] = annotate(account, result, inputs, shorts)
            sources[str(result_path.relative_to(ROOT))] = helper.sha(result_path)
            sources[str(ledger_path.relative_to(ROOT))] = result['ledger_SHA256']
            local = campaigns[ident]
            for period in ('前16','後14','全30'):
                for symbol in ('TOPIX','NK225'):
                    selected = [c for c in local if c['session'] in fixed[period] and c['symbol'] == symbol]
                    partitions = defaultdict(list)
                    for c in selected:
                        partitions[c['prior_published']['支持区分']].append(c)
                    for name, subset in partitions.items():
                        losers = [c for c in subset if c['net'] < 0]
                        adverse = [c for c in subset if c['posthoc']['barrier_order'] == '0.75ATR順行より先に0.75ATR逆行']
                        groups.append(dict(model=model,id=ident,period=period,symbol=symbol,group=name,
                            成績=helper.summarize(subset),赤字組だけ=helper.summarize(losers),
                            順行前に逆行=helper.summarize(adverse),
                            始動幅未達=helper.summarize([c for c in subset if not c['posthoc']['trail_activation_reached']]),
                            料金前赤字=helper.summarize([c for c in subset if c['gross'] < 0]),
                            料金で赤字化=helper.summarize([c for c in subset if c['gross'] >= 0 and c['net'] < 0])))
            details.extend(dict(c,model=model,id=ident) for c in local)
            worst.extend(dict(c,model=model,id=ident) for symbol in ('TOPIX','NK225')
                for c in sorted((c for c in local if c['symbol'] == symbol),key=lambda c:c['net'])[:3])
            print(model,ident,'台帳と入口根拠照合済み',flush=True)
        # ----------------------------------------
        # 入口対応には収益・将来価格を用いず、同原本行又は同準備だけを用いる。
        for ident in identifiers:
            parent = ident.split('_')[0]+'_F0'
            if ident == parent:
                continue
            for period in ('前16','後14','全30'):
                for symbol in ('TOPIX','NK225'):
                    value = compare(campaigns[parent],campaigns[ident],accounts[ident],inputs,symbol,set(fixed[period]))
                    comparisons.append(dict(model=model,before=parent,after=ident,period=period,symbol=symbol,**value))
        del accounts,campaigns
    # ----------------------------------------
    # 初期停止幅との先着比較は損失の事後説明であり、新しい最適閾値ではない。
    output = dict(定義={
        '目的':'最新支持でも損失になるのか、支持が極値以前のままなのか、入口経路の変化と分ける。',
        '参照時点':'発注sourceは注文線の設定元。支持は実際に評価された前の公開plan行で判定し、約定当行の支持低下による遡及取消は行わない。',
        '疎イベント':'待機方向・極値行・許可・注文線だけを補間する。支持値と元時計は保存済み全行特徴から読む。',
        '鮮度':'極値より後は支持窓終端の前後であり30秒窓全体の新しさではない。新しい秒数閾値は設けない。',
        '即失敗':'時間で分類せず、共通の0.75ATR順行へ届く前に0.75ATR逆行したかを保有中だけ事後確認する。',
        '照合':'同一入口は原本seqと方向、入口変更は同じ準備seqと方向の一対一対応だけ。消失・追加には保有経路の変化も含む。',
        '時計':'CurrentPriceTimeは代理時計。同時計別行を秒数ゼロの同一情報とは見なさない。',
        '制限':'全30場既知。新しい売買再生・候補選択・閾値探索なし。価格経路と最悪例は事後診断だけ。'},
        input_SHA256=hashes,source_SHA256=sources,比較=comparisons,支持別成績=groups,最悪例=worst,全親組=details)
    path = HERE/'第三段階の入口変化と失敗経路.json'
    path.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print('独立診断保存',path,'親組',len(details),flush=True)


if __name__ == '__main__':
    main()
