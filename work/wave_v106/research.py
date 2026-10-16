"""往復帯への参加と反復損失を、事前固定した対照で全セッション検証する。"""

import argparse
from datetime import datetime, timezone
import gzip
import importlib.util
import json
from pathlib import Path
import pickle
import sys
import time

import numpy as np

import accounting
import catalog
import common
import evaluation
import filters


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASELINE = 'C_N30_B4'
SYMBOLS = ('TOPIX', 'NK225')


def write(path: Path, value: dict) -> None:
    """
    機能: 新しい検証資料をUTF-8で保存する。
    引数: path(Path)は新作業内の保存先、value(dict)は資料。
    返り値: None。既存の完了証跡は上書きしない。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists(), path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def load_module(name: str, path: Path) -> object:
    """
    機能: 新作業の部品を識別名付きで読み込む。
    引数: name(str)は識別名、path(Path)はソース。
    返り値: objectは部品。入力と金融の読取を暗黙には行わない。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def source_hashes() -> dict:
    """
    機能: 再生の入口・管理・会計・入力を内容指紋へ結ぶ。
    引数: なし。
    返り値: dict[str,str]は小さい依存ファイルの指紋。
    """
    paths = [HERE/name for name in ('research.py', 'catalog.py', 'filters.py', 'accounting.py',
        'evaluation.py', 'common.py', 'engine/core.py', 'engine/interface.py',
        'input/core.py', 'input/features.py', 'input/data.py', 'input/全33場の因果特徴準備.json')]
    paths += [ROOT/'work/wave_v102/accounting.py']
    return {str(path.relative_to(ROOT)): common.digest(path) for path in paths}


def proposal() -> dict:
    """
    機能: 未実行だった51案の実行理由と完全な比較仕様を記録する。
    引数: なし。
    返り値: dictは重複照合に渡す計画。既存の利益ラベルを条件へ使用しない。
    """
    metadata = common.read(HERE/'input/全33場の因果特徴準備.json')
    assert metadata['全合格']
    configs = catalog.catalog()
    return dict(id='106_往復帯と初期リスク及び再参加の全33対照',
        name='往復帯を避け、失敗した支持帯の再参加を止める統合検証', purpose='不具合修正',
        question='往復を除く入口、初期リスクに対する利益幅、同帯再参加抑制を組み合わせると両銘柄で安定するか。',
        change='105は入力UNKNOWNの対応不備で金融未実行。106で不明窓を正しく保持し、同じ51草案を初めて金融再生する。',
        repeat_reason='金融未実行の105には再利用できる損益がない。104は各1枚、今回はTOPIX10枚・日経20枚の注文ごとの実料金で対照する。',
        compares_to=['研究_wave_v105', '104_C_N30_B4', '104_U_P10_T2'],
        evidence=[{'path':'work/wave_v105/input/全33場の因果特徴準備.json'},
                  {'path':'work/wave_v105/diagnosis/具体的に負けた板と改善の代償.json'}],
        spec=dict(
            entry=dict(saved_series=list(catalog.ENTRIES), variants=[{k:('追加選別なし' if k=='filter_mode' and c[k]=='NONE' else c[k]) for k in
                ('id','entry_id','filter_mode','window','own_path')} for c in configs],
                efficiency='方向付き純進行/総移動が0.5超', noise='当時の停止余裕が過去最大逆行幅を上回る',
                unknown='不明、無更新、曖昧な窓は肯定せず見送る'),
            management=dict(variants=[{k:c[k] for k in ('id','reentry_band','session_brake','session_budget_multiple')} for c in configs],
                reentry='損失した支持帯を順方向へ出て、脱出後の新しい支持根拠でだけ解除',
                timing='開始5分準備、終了5分前新規停止、終了1分前全返済', cooldown=30),
            exit=dict(variants=[{k:c[k] for k in ('id','support_ticks','profit_trail','r_profit','alpha','beta')} for c in configs],
                initial_stop_fraction=.001, wide_trail='既存の始値比0.4%幅',
                fixed_R='実建値から有効損切り線までの幅＋往復手数料幅を呼値へ切上げ、約定時固定'),
            allocation=dict(products={'TOPIX':'TOPIXmini','NK225':'NK225micro'}, quantity={'TOPIX':10,'NK225':20},
                cap_per_direction={'TOPIX':10,'NK225':20}, additional_positions=False),
            costs=dict(per_lot_per_side={'TOPIX':41.8,'NK225':11}, rounding='注文合計の円未満切捨て'),
            execution=dict(buy='判断行より後の最初の正常ask',sell='判断行より後の最初の正常bid',
                price_source='ラージの保存板、同じ正常原行対応', overnight=False, worst_delay_seconds=0),
            data=dict(sessions=sorted(metadata['sessions']), input_manifests=[dict(
                path=str((HERE/'input/全33場の因果特徴準備.json').relative_to(ROOT)),
                sha256=common.digest(HERE/'input/全33場の因果特徴準備.json'))],
                known_sessions=33, unknown_sessions=0, current_API_reads=0), implementation=source_hashes()))


def freeze() -> None:
    """
    機能: 条件と安定性基準を、新しい金融再生の前に固定する。
    引数: なし。
    返り値: None。実行済みの候補を新しい検証とは数えない。
    """
    assert not (HERE/'金融事前固定.json').exists()
    metadata = common.read(HERE/'input/全33場の因果特徴準備.json')
    assert metadata['全合格'] and len(metadata['cache']) == 33
    plan = proposal()
    write(HERE/'試行計画.json', plan)
    write(HERE/'金融事前固定.json', dict(全合格=True, sessions=sorted(metadata['sessions']),
        configs=catalog.catalog(), primary=catalog.PRIMARY, baseline=BASELINE,
        sources=source_hashes(), timestamp=datetime.now(timezone.utc).isoformat(),
        採用基準='両銘柄それぞれ、取引20件以上・活動17場以上・合計黒字・平均利益/平均損失>1・最大利益場除外後黒字。',
        最終目標='両銘柄とも全33セッション黒字、相殺前総利益/総損失>=4。無取引を黒字に含めない。',
        選定='最大の活動場赤字率を最小化、下方偏差、最悪場損失、少ない方の金額利益割合の順。',
        限界='全33場は既知。実時間の未来参照防止と、研究過程の過剰適合は別。未知検証なし。',
        旧資料の金融再生=0, 現在API=0, 実注文=0))
    print('51条件の事前固定と試行計画を保存しました。重複照合・登録後に実行します。', flush=True)


def concise_features(feature: dict | None) -> dict | None:
    """
    機能: 当時特徴を小さい数値に要約する。
    引数: feature(dict|None)は当該判断行だけの過去特徴。
    返り値: dict|None。原経路配列や将来の観測は付加しない。
    """
    if feature is None:
        return None
    fields = ('known','count','directional_net_ticks','total_variation_ticks','efficiency','max_adverse_ticks')
    return {source:{window:{name:values.get(name) for name in fields} for window,values in feature[source].items()}
            for source in ('own','own_normal','peer')}


def save_ledger(path: Path, output: dict, record: dict, features: dict) -> None:
    """
    機能: 全注文・実取引・支持と停止判断を保存し、損失の具体箇所を追跡可能にする。
    引数: path(Path)は保存先、output/record/features(dict)は再生結果と当時入力。
    返り値: None。全行時価は値の変化行だけ保存し、会計では全行を検算済み。
    """
    assert not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    names = ('orders','order_columns','trades','trade_columns','control_events','control_event_columns',
             'control_stats','control_stat_columns','candidate_controls','candidate_control_columns',
             'candidate_integer_keys','candidate_integer_columns','judgments','judgment_columns')
    saved = {name:output[name] for name in names}
    curve = output['curve']
    changes = np.flatnonzero(np.r_[True, np.diff(curve) != 0])
    saved['equity_change_rows'] = changes
    saved['equity_change_values'] = curve[changes]
    saved['row_count'] = len(curve)
    details = []
    for trade in output['trades']:
        decision, entry, exit_row, side = int(trade[15]), int(trade[2]), int(trade[3]), int(trade[4])
        prices = record['bid'][entry:exit_row+1] if side == 1 else record['ask'][entry:exit_row+1]
        valid = record['quote_valid'][entry:exit_row+1] & np.isfinite(prices)
        directed = side*(prices[valid]-trade[6])/record['tick']
        details.append(dict(parent=int(trade[0]), direction=side, net=float(trade[11]),
            decision_row=decision, decision_seq=int(record['seq'][decision]), decision_time=float(record['time_s'][decision]),
            entry_row=entry, entry_seq=int(record['seq'][entry]), entry_time=float(record['time_s'][entry]),
            exit_row=exit_row, exit_seq=int(record['seq'][exit_row]), exit_time=float(record['time_s'][exit_row]),
            entry_price=float(trade[6]), exit_price=float(trade[7]), exit_reason=int(trade[13]),
            max_favorable_ticks=float(directed.max()), max_adverse_ticks=float(max(0,-directed.min())),
            past=concise_features(features.get(decision))))
    saved['trade_details'] = details
    with path.open('wb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0, compresslevel=2) as zipped:
            pickle.dump(saved, zipped, protocol=5)


def one_session(session: str, configs: list[dict], loader: object, engine: object) -> dict:
    """
    機能: 同じ保存入力を一場一回読み、51条件を実数量と実手数料で比較する。
    引数: session(str)、configs(list[dict])、loader/engine(object)は固定条件と部品。
    返り値: dictは66ではなく当該一場の102口座会計・取引対応・対策寄与。
    """
    packet = loader.load_session(session)
    results = {config['id']:dict(rows=[],maps={},ledgers={}) for config in configs}
    for symbol in SYMBOLS:
        prepared = packet['prepared'][symbol]
        record = prepared['record']
        for config in configs:
            ident, entry_id = config['id'], config['entry_id']
            case, features = packet['cases'][entry_id][symbol], packet['features'][entry_id][symbol]
            mask, reasons, diagnostic = filters.apply(prepared, case, features, config)
            output = engine.play(prepared, case, config, quantity=config['quantity'][symbol],
                                 entry_filter=mask, filter_reason=reasons)
            row = accounting.inspect((session,symbol), record, output)
            row['budget_unit'] = output['initial_width']*config['quantity'][symbol]*output['economics']['multiplier']
            row['filter_pass'] = sum(item['accepted'] for item in diagnostic)
            row['filter_reject'] = len(diagnostic)-row['filter_pass']
            row['brake'] = bool(output['control_stats'][2])
            results[ident]['rows'].append(row)
            results[ident]['maps'][symbol] = accounting.trade_map(output,record)
            path = HERE/'finance/ledger'/ident/(session+'_'+symbol+'.pkl.gz')
            save_ledger(path,output,record,features)
            results[ident]['ledgers'][symbol] = dict(path=str(path.relative_to(ROOT)),SHA256=common.digest(path))
            del output, mask, reasons, diagnostic
    contributions = {}
    for config in configs:
        ident, reference = config['id'], config['entry_id']+'_B4'
        contributions[ident] = {symbol:accounting.contribution(results[reference]['maps'][symbol],results[ident]['maps'][symbol])
                               for symbol in SYMBOLS}
    result = dict(cases=results,contributions=contributions)
    write(HERE/'finance/session'/(session+'.json'),result)
    print(session+'：51条件・102口座、全行会計一致・場内全返済を確認',flush=True)
    return result


def run() -> None:
    """
    機能: 事前照合済み51条件を全33場で実行し、原因別の改善と代償を集計する。
    引数: なし。
    返り値: None。無取引を勝ちに数えず、過去からの選定と未知確認を区別する。
    """
    fixed = common.read(HERE/'金融事前固定.json')
    assert fixed['sources'] == source_hashes()
    trials = common.read(ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')['trials']
    assert any(item['id'] == '106_往復帯と初期リスク及び再参加の全33対照' for item in trials)
    assert not (HERE/'finance/results.json').exists()
    loader = load_module('106の完了入力だけを読む',HERE/'input/data.py')
    engine = load_module('106の新入力を固定Rと再参加へ接続',HERE/'engine/interface.py')
    configs, sessions = fixed['configs'],fixed['sessions']
    cases = {config['id']:dict(rows=[],ledgers={}) for config in configs}
    contribution_fields = ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
    diagnosis = {config['id']:{symbol:{name:0. for name in contribution_fields} for symbol in SYMBOLS} for config in configs}
    started = time.monotonic()
    for session in sessions:
        path = HERE/'finance/session'/(session+'.json')
        result = common.read(path) if path.exists() else one_session(session,configs,loader,engine)
        for ident,value in result['cases'].items():
            cases[ident]['rows'] += value['rows']
            cases[ident]['ledgers'][session] = value['ledgers']
            for symbol in SYMBOLS:
                for name in contribution_fields:
                    diagnosis[ident][symbol][name] += result['contributions'][ident][symbol][name]
    assessment = evaluation.assess(cases,sessions,BASELINE)
    for ident,value in cases.items():
        value['summary'] = assessment['results'][ident]['symbols']
        value['first_half'] = {symbol:evaluation.summarize(value['rows'],symbol,sessions[:16]) for symbol in SYMBOLS}
        value['second_half'] = {symbol:evaluation.summarize(value['rows'],symbol,sessions[16:]) for symbol in SYMBOLS}
    ranked = sorted(cases,key=lambda ident:(
        not assessment['results'][ident]['eligible'],
        max(v['losing_active_rate'] if v['losing_active_rate'] is not None else 1. for v in cases[ident]['summary'].values()),
        max(v['downside_rms'] for v in cases[ident]['summary'].values()),
        max(v['worst_normalized_loss'] for v in cases[ident]['summary'].values()),
        -min(v['profit_share'] if v['profit_share'] is not None else 0. for v in cases[ident]['summary'].values()),ident))
    selected = list(dict.fromkeys([*assessment['ranking'][:3],*ranked]))[:3]
    achieved = [ident for ident in ranked if all(v['positive_sessions']==33 and v['profit_share'] is not None
        and v['profit_share']>=.8 and v['payoff'] is not None and v['payoff']>1 for v in cases[ident]['summary'].values())]
    write(HERE/'finance/results.json',dict(全合格=True,sessions=sessions,configs=configs,cases=cases,
        evaluation=assessment,selected=selected,baseline=BASELINE,diagnosis=diagnosis,
        target_achieved=achieved,unknown_sessions=0,known_sessions=33,current_API_reads=0,actual_orders=0,
        account_count=len(configs)*len(sessions)*2,elapsed_seconds=time.monotonic()-started))
    print(json.dumps(dict(候補=selected,目標達成=achieved,採用=assessment['adopted']),ensure_ascii=False),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='新しい51条件の事前固定と全場比較')
    parser.add_argument('action',choices=('freeze','run'))
    arguments = parser.parse_args()
    freeze() if arguments.action == 'freeze' else run()
