"""中心保持解除からの取消を、当時入力・最初成立・次気配競合で独立に反証する。"""

import copy
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

import common
import full
import protocol_rel
from execution_checks import sample, prefix, prefix_equal
from full_artificial import ledger


def fixture(symbol, mirrored, fills, config):
    """
    機能: 黒字全返済→中心帰還→再指値予約→共同解除→次気配の競合を作る。
    引数: symbol(str)、mirrored/fills(bool)、config(dict)。
    返り値: tuple[dict,dict]の人工原板と既知信号。
    """
    record,signal = sample(symbol,'中心帰還後の次逸脱',mirrored,config)
    anchor = 4000. if symbol=='TOPIX' else 68000.
    width = signal['range_width']
    sign = -1 if mirrored else 1
    if sign == 1:
        record['bid'][22:24] = anchor-1.5*width
        record['ask'][22:24] = anchor-.5*width
    else:
        record['bid'][22:24] = anchor+.5*width
        record['ask'][22:24] = anchor+1.5*width
    if not fills:
        record['bid'][24] = record['bid'][23]
        record['ask'][24] = record['ask'][23]
    signal['mode'][23] = 0
    signal['arm_common'][23] = sign
    signal['arm_trend300'][23] = sign
    return record,signal


def main():
    """
    機能: 解除正例、最初成立の見逃し、解除未成立の負例、取消と約定の競合を検査する。
    引数: なし。
    返り値: None。新しい補足監査証跡だけを保存し、正式売買は変更しない。
    """
    import sys
    sys.path.insert(0,str(common.WORK))
    import strategy
    fixed = full.read(common.WORK/'事前固定.json')
    for relative,digest in fixed['SHA256'].items():
        assert common.sha(common.ROOT/relative)==digest,relative
    config = next(value for value in fixed['条件'] if value['id']=='KS25_REL')
    full.protocol = protocol_rel
    examples = []
    rejected = dict(当時解除未成立=0,最初の解除を飛ばす=0,同じ行の解除ラベルなし=0,
                    解除原因不一致=0,取消と成立競合で先約定を遅延=0)
    future_checks = dict(未来切断=0,未来価格変更=0,未来相手源変更=0)
    for symbol in common.SYMBOLS:
        for mirrored in (False,True):
            for fills in (False,True):
                record,signal = fixture(symbol,mirrored,fills,config)
                result = strategy.ENGINE.execute(record,signal,config)
                protocol_rel.verify(record,signal,config,result)
                full.account((record['session'],symbol),record,signal,config,ledger(result))
                cancel = result['events'][(result['events'][:,3]==3)&(result['events'][:,0]==23)]
                assert len(cancel)==1
                parent = int(cancel[0,1])
                entry = result['orders'][(result['orders'][:,2]==parent)&(result['orders'][:,7]==1)]
                effect = result['events'][(result['events'][:,1]==parent)&(result['events'][:,3]==6)]
                if fills:
                    assert len(entry)==1 and entry[0,0]==24 and not len(effect)
                    assert ((result['events'][:,1]==parent)&(result['events'][:,3]==7)&(result['events'][:,0]==24)).sum()==1
                else:
                    assert not len(entry) and len(effect)==1 and effect[0,0]==24
                for stop in (23,24,25):
                    clipped_record,clipped_signal = prefix(record,signal,stop)
                    partial = strategy.ENGINE.execute(clipped_record,clipped_signal,config,finish=False)
                    prefix_equal(result,partial,stop)
                    protocol_rel.verify(clipped_record,clipped_signal,config,partial)
                    future_checks['未来切断'] += 1
                    future_record = copy.deepcopy(record)
                    for name in ('price','bid','ask'):
                        future_record[name][stop:] *= 7
                    partial = strategy.ENGINE.execute(future_record,signal,config,finish=False)
                    prefix_equal(result,partial,stop)
                    future_checks['未来価格変更'] += 1
                    future_signal = copy.deepcopy(signal)
                    last = int(signal['mapped'][:stop].max(initial=-1))
                    future_signal['peer_mid'][last+1:] *= 7
                    future_signal['peer_source'][last+1:] += 10000
                    future_signal['peer_valid'][last+1:] = ~future_signal['peer_valid'][last+1:]
                    partial = strategy.ENGINE.execute(record,future_signal,config,finish=False)
                    prefix_equal(result,partial,stop)
                    future_checks['未来相手源変更'] += 1
                variants = []
                wrong_signal = copy.deepcopy(signal)
                wrong_signal['arm_common'][23] = 0
                wrong_signal['arm_trend300'][23] = 0
                variants.append(('当時解除未成立',wrong_signal,result))
                wrong_signal = copy.deepcopy(signal)
                wrong_signal['arm_common'][21] = -1 if mirrored else 1
                wrong_signal['arm_trend300'][21] = -1 if mirrored else 1
                wrong_signal['mode'][21] = 0
                variants.append(('最初の解除を飛ばす',wrong_signal,result))
                wrong = copy.deepcopy(result)
                wrong['events'] = wrong['events'][~((wrong['events'][:,3]==26)&(wrong['events'][:,0]==23))]
                variants.append(('同じ行の解除ラベルなし',signal,wrong))
                wrong = copy.deepcopy(result)
                wrong['events'][(wrong['events'][:,3]==26)&(wrong['events'][:,0]==23),11] = 2
                variants.append(('解除原因不一致',signal,wrong))
                if fills:
                    wrong = copy.deepcopy(result)
                    row = np.flatnonzero((wrong['orders'][:,2]==parent)&(wrong['orders'][:,7]==1))[0]
                    wrong['orders'][row,0] = 25
                    variants.append(('取消と成立競合で先約定を遅延',signal,wrong))
                for name,selected_signal,wrong in variants:
                    failed = False
                    try:
                        protocol_rel.verify(record,selected_signal,config,wrong)
                    except AssertionError:
                        failed = True
                    assert failed,(symbol,mirrored,fills,name)
                    rejected[name] += 1
                examples.append(dict(銘柄=symbol,上下反射=mirrored,取消判断行=23,
                                     次有効気配行=24,指値成立=fills,
                                     競合時の先約定を維持=fills,同じ行の入力解除とcode26を照合=True))
    diagnostic = dict(
        失敗した監査='凍結full.pyを直接実行、handle11043終了コード1',
        原因='旧protocol.pyの取消許可条件がcancel_pending又はpersistent_armだけで、新center_release契約を含まなかった。',
        条件='KS25_REL',セッション='2026-09-21_Night',銘柄='NK225',原板行=59933,親=11,
        時刻=datetime.fromtimestamp(1790006983,ZoneInfo('Asia/Tokyo')).isoformat(),
        同じ行のcode26=1,同じ行のcode3=1,
        補足の適用='center_release=Trueで非persistentの中心保持解除から未約定取消を出す2条件。全36会計を再検算する。',
        凍結済みコード変更=0,正式売買変更=0,結果変更=0)
    paths = [Path(__file__),common.HERE/'protocol_rel.py',common.HERE/'run_full_rel.py',
             common.HERE/'protocol.py',common.HERE/'full.py',common.HERE/'entry_checks.py',
             common.HERE/'execution_checks.py',common.HERE/'full_artificial.py',common.WORK/'事前固定.json']
    common.save('中心解除取消の原入力と最初成立及び先約定の補足監査.json',dict(
        全合格=True,人工正例=examples,人工故障を拒絶=rejected,新競合枝の未来不変=future_checks,
        最初の失敗と適用範囲=diagnostic,
        SHA256=common.fingerprint(paths),現在API取得=0,実注文=0))
    print('中心解除取消の8正例と36故障を、最初成立と先約定で独立確認',flush=True)


if __name__=='__main__':
    main()
