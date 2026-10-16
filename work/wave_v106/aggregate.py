"""既知全セッションの安定性を、突出した利益への依存を除いて集計する。売買は再生しない。"""

from copy import deepcopy
import argparse
import gzip
from pathlib import Path
import pickle

import numpy as np

import accounting
import common
import evaluation
import research


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SYMBOLS = ('TOPIX','NK225')


def stability(rows: list[dict], symbol: str) -> dict:
    """
    機能: 全場の中央値と利益上位への依存を計算する。
    引数: rows(list[dict])は一条件の場別会計、symbol(str)は商品。
    返り値: dictは中央値・上位3除外・最大利益場寄与など。無取引は収支0として中央値へ含む。
    """
    selected = [row for row in rows if row['symbol']==symbol]
    nets = np.array([row['net'] for row in selected],float)
    positive = sorted([row['net'] for row in selected if row['net']>0],reverse=True)
    return dict(median_session_net=float(np.median(nets)),without_top3_net=float(nets.sum()-sum(positive[:3])),
        best_session_share_of_session_positive_net=positive[0]/sum(positive) if positive else None,
        lower_quartile=float(np.quantile(nets,.25)),upper_quartile=float(np.quantile(nets,.75)),
        positive_session_net_sum=sum(positive),net_standard_deviation=float(np.std(nets)),
        worst_session_net=float(nets.min()),mean_session_net=float(nets.mean()),
        interpretation='最大場寄与の分母は黒字セッションの収支合計。相殺前の取引総利益とは異なる。')


def simple_map(trades: np.ndarray, original_ledger: dict) -> dict:
    """
    機能: 同一初回入口を、場内停止の前後で対応させる。
    引数: trades(ndarray)は返済取引、original_ledger(dict)は元入口の原seq資料。
    返り値: dictは当時判断seqと方向を鍵にした実取引。
    """
    meta = {item['parent']:item for item in original_ledger['trade_details']}
    result = {}
    for row in trades:
        original = meta[int(row[0])]
        key = str(original['decision_seq'])+'|'+str(int(row[4]))
        assert key not in result
        result[key] = dict(net=float(row[11]),entry_row=int(row[2]),exit_row=int(row[3]),
            entry_price=float(row[6]),exit_price=float(row[7]),quantity=int(row[5]),side=int(row[4]))
    return result


def second_contribution(first: dict, second: dict) -> dict:
    """
    機能: 利益目標と損失枠の収支差を、同じ基準の全取引と照合する。
    引数: first/second(dict)は第一・第二段階の完成会計。
    返り値: dictは避けた損失と見送った利益などの全場合計。
    """
    fields = ('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')
    result = {config['id']:{symbol:{name:0. for name in fields} for symbol in SYMBOLS} for config in second['configs']}
    for config in second['configs']:
        ident,base = config['id'],config['base_id']
        for session in first['sessions']:
            for symbol in SYMBOLS:
                original_path = ROOT/first['cases'][base]['ledgers'][session][symbol]['path']
                changed_path = ROOT/second['cases'][ident]['ledgers'][session+'|'+symbol]['path']
                with gzip.open(original_path,'rb') as stream:
                    original = pickle.load(stream)
                with gzip.open(changed_path,'rb') as stream:
                    changed = pickle.load(stream)
                delta = accounting.contribution(simple_map(original['trades'],original),simple_map(changed['trades'],original))
                for name in fields:
                    result[ident][symbol][name] += delta[name]
    return result


def main() -> None:
    """
    機能: 完成した各段階をまとめ、安定性順の検証代表を選ぶ。
    引数: --output-dir(Path)は完成集計の新規保存領域。入力位置は各段階で固定。
    返り値: None。保存済み集計だけを使い、追加注文を生成しない。
    """
    parser = argparse.ArgumentParser(description='保存済み会計の安定性を再集計する。売買は再生しない。')
    parser.add_argument('--output-dir', type=Path, default=HERE/'finance')
    args = parser.parse_args()
    first = common.read(HERE/'finance/results.json')
    second = common.read(HERE/'finance/session_control_results.json')
    assert first['全合格'] and second['全合格'] and first['sessions']==second['sessions']
    sessions = first['sessions']
    final = deepcopy(first)
    final['configs'] += second['configs']
    assert not set(final['cases']) & set(second['cases'])
    final['cases'].update(second['cases'])
    final['diagnosis'].update(second_contribution(first,second))
    stages = [dict(name='入口品質・初期リスク・損失帯',conditions=51,result='finance/results.json'),
              dict(name='場中利益の確定と損失枠',conditions=36,result='finance/session_control_results.json')]
    completed = (
        ('portfolio/results.json','進行と反転の固定配分と場内利益保全'),
        ('thesis/finance/results.json','支持破れと相手逆進行による途中返済'),
        ('time_guard/results.json','既知の市場開始時刻における静観'),
        ('regime_price/finance/results.json','純価格6点による二市場の自動手法選択'),
    )
    for relative, name in completed:
        path = HERE/relative
        if not path.exists():
            continue
        stage = common.read(path)
        assert stage['全合格'] and stage['sessions']==sessions
        assert not set(final['cases']) & set(stage['cases'])
        final['configs'] += stage['configs']
        final['cases'].update(stage['cases'])
        final['diagnosis'].update(stage.get('diagnosis',{}))
        stages.append(dict(name=name,conditions=len(stage['configs']),result=relative))
    assessment = evaluation.assess(final['cases'],sessions,first['baseline'])
    all_stability = {}
    for ident,value in final['cases'].items():
        value['summary'] = assessment['results'][ident]['symbols']
        value['first_half'] = {symbol:evaluation.summarize(value['rows'],symbol,sessions[:16]) for symbol in SYMBOLS}
        value['second_half'] = {symbol:evaluation.summarize(value['rows'],symbol,sessions[16:]) for symbol in SYMBOLS}
        all_stability[ident] = {symbol:stability(value['rows'],symbol) for symbol in SYMBOLS}
    def score(ident: str) -> tuple:
        """
        機能: 活動を確保した条件で赤字の頻度・中央値・大勝ち依存を優先する。
        引数: ident(str)は候補ID。
        返り値: tupleは小さい順を上位とする比較値。合計円額で銘柄を混ぜない。
        """
        products = final['cases'][ident]['summary']
        active = all(v['active_sessions']>=17 and v['campaigns']>=20 for v in products.values())
        return (not active,
            max(v['losing_sessions']/len(sessions) for v in products.values()),
            sum(v['no_trade_sessions'] for v in products.values()),
            -min(all_stability[ident][s]['median_session_net']/products[s]['worst_session_loss']
                if products[s]['worst_session_loss']>0 else 0. for s in SYMBOLS),
            max(v['downside_rms'] for v in products.values()),ident)
    ranking = sorted(final['cases'],key=score)
    robust = [ident for ident in ranking if all(
        final['cases'][ident]['summary'][s]['net']>0 and
        final['cases'][ident]['summary'][s]['active_sessions']>=17 and
        final['cases'][ident]['summary'][s]['campaigns']>=20 and
        final['cases'][ident]['summary'][s]['payoff'] is not None and
        final['cases'][ident]['summary'][s]['payoff']>1 and
        all_stability[ident][s]['median_session_net']>0 and
        all_stability[ident][s]['without_top3_net']>0 for s in SYMBOLS)]
    achieved = [ident for ident in robust if all(final['cases'][ident]['summary'][s]['positive_sessions']==33 and
        final['cases'][ident]['summary'][s]['profit_share']>=.8 for s in SYMBOLS)]
    final.update(evaluation=assessment,stability=all_stability,selected=list(dict.fromkeys([*robust,*ranking]))[:3],
        target_achieved=achieved,robust_candidates=robust,stages=stages,
        account_count=len(final['configs'])*len(sessions)*2,
        選定の意味='採用ではなく安定性順の検証代表。全目標未達ならその旨を表示する。',
        評価追加='金融再生中のユーザー追加指定により、中央値・上位3除外を評価へ追加。アルゴ条件は各段階の事前固定どおり。')
    research.write(args.output_dir/'final_results.json',final)
    research.write(args.output_dir/'stability.json',dict(全合格=True,stability=all_stability,金融再生=0))
    print('条件数:',len(final['configs']),'安定採用候補:',robust,'目標達成:',achieved,'検証代表:',final['selected'])


if __name__=='__main__':
    main()
