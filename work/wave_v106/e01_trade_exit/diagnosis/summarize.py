"""保存小結果だけから安定性と具体検査対象を結果後の診断として固定する。"""

import argparse
from collections import Counter
import hashlib
from pathlib import Path

import numpy as np

import tools

FIELDS=('収支変化','避けた基準損失','失った基準利益','共通入口の出口変化','新たな入口の収支')


def stability(rows: list[dict]) -> dict:
    """
    機能: 保存場損益を活動場と全場に区別し、前後期間と平均勝負比をまとめる。
    引数: rows(list[dict])は同一商品の時系列33場。
    返り値: dictは場を分母とする実測。親勝率や金額利益割合と混同しない。
    """
    active=[r for r in rows if r['親数']>0]
    wins=[r['収支'] for r in active if r['収支']>0]
    losses=[-r['収支'] for r in active if r['収支']<0]
    meanwin=float(np.mean(wins)) if wins else None
    meanloss=float(np.mean(losses)) if losses else None
    return dict(全場=len(rows),活動場=len(active),黒字場=len(wins),赤字場=len(losses),
        無取引場=len(rows)-len(active),活動黒字率=len(wins)/len(active) if active else None,
        分母='決済親が1つ以上あるセッション。零収支活動場も分母へ含む。',
        前16収支=sum(r['収支'] for r in rows[:16]),後17収支=sum(r['収支'] for r in rows[16:]),
        平均黒字場=meanwin,平均赤字場損失=meanloss,
        平均場損益比=meanwin/meanloss if meanwin is not None and meanloss else None,
        この平均幅での黒字率損益分岐=meanloss/(meanloss+meanwin) if meanwin is not None and meanloss else None)


def main() -> None:
    """
    機能: 金融完了後の小JSONから6政策と固定された二対照を診断し、次のsubsetを先登録する。
    引数: CLI --root-finance-completed(bool)は根の完了通知を受けた明示指定。
    返り値: None。新金融・台帳・特徴cacheは読まず、選抜小JSONだけを保存する。
    """
    parser=argparse.ArgumentParser();parser.add_argument('--root-finance-completed',action='store_true')
    assert parser.parse_args().root_finance_completed
    result,resultsha=tools.read(tools.SOURCE/'finance/結果.json')
    fixed,fixedsha=tools.read(tools.SOURCE/'金融前の固定.json')
    meta,metasha=tools.read(tools.SOURCE/'全33場の保有中取引更新票.json')
    assert result['全合格'] and result['source開始終端一致'] and result['source_SHA256']==fixed['source_SHA256']
    assert result['sessions']==fixed['sessions']==meta['sessions'] and result['新政策会計']==396
    rows=[];targets=[]
    for config in result['configs']:
        case=result['results'][config['id']]
        for symbol in ('TOPIX','NK225'):
            sr=sorted((r for r in case['rows'] if r['symbol']==symbol),key=lambda r:result['sessions'].index(r['session']))
            info=dict(id=config['id'],mode=config['mode'],window=config['window_seconds'],symbol=symbol,
                **case['symbols'][symbol],場安定性=stability(sr),二対照5寄与=result['diagnosis'][config['id']],
                制御頻度=dict(Counter(d['control'].get('種別','発動なし') for d in result['各場寄与'][config['id']]['P1L8'] if d['symbol']==symbol)))
            info['二対照5寄与']={b:d[symbol] for b,d in result['diagnosis'][config['id']].items()}
            rows.append(info)
    for symbol in ('TOPIX','NK225'):
        for mode in ('CONFIRM','VETO'):
            candidates=[]
            old=fixed['bindings'][mode]['P1L8']
            oldrows={r['session']:r for r in old['rows'] if r['symbol']==symbol}
            for config in result['configs']:
                if config['mode']!=mode:continue
                id=config['id']
                for diff in result['各場寄与'][id]['P1L8']:
                    if diff['symbol']!=symbol:continue
                    candidates.append(dict(id=id,mode=mode,symbol=symbol,session=diff['session'],
                        base_net=oldrows[diff['session']]['収支'],diff=diff))
            improved=[c for c in candidates if c['base_net']<0 and c['diff']['収支変化']>0]
            turned=[dict(**c,parent=p['parent'],parent_change=p['new_net']-p['base_net'],turned=p)
                for c in candidates for p in c['diff']['元勝ち親が赤字化']]
            missed=[c for c in candidates if c['diff']['失った基準利益']>0]
            for kind,pool,key,reverse in (
                ('旧赤字場を軽減した最大例',improved,lambda c:c['diff']['収支変化'],True),
                ('旧勝ち親を赤字化した最大例',turned,lambda c:c['parent_change'],False),
                ('旧勝ち親が消えた利益喪失最大例',missed,lambda c:c['diff']['失った基準利益'],True)):
                chosen=sorted(pool,key=key,reverse=reverse)[0] if pool else None
                targets.append(dict(種類=kind,symbol=symbol,mode=mode,選抜=chosen,
                    親の決め方='既知turned親を固定。その他は選抜済み場内の同一親比較を行い、その場の最大共通親改善又は最大消失利益を補足。場・窓の選び直しなし。'))
    summary=dict(全合格=True,正式出典='00103',根拠={'金融結果':dict(path=(tools.SOURCE/'finance/結果.json').relative_to(tools.ROOT).as_posix(),sha256=resultsha),
        '固定':dict(sha256=fixedsha),'特徴目録':dict(sha256=metasha)},手法商品12行=rows,
        両商品同時黒字条件数=sum(all(result['results'][c['id']]['symbols'][s]['収支']>0 for s in ('TOPIX','NK225')) for c in result['configs']),
        両商品上位3除外黒字条件数=sum(all(result['results'][c['id']]['symbols'][s]['上位3利益場除外収支']>0 for s in ('TOPIX','NK225')) for c in result['configs']),
        新金融=0,金融台帳読取=0,特徴cache読取=0,原NPZ=0,API=0,
        限界=['各場利益目標/損失停止政策の比較。逆票だけの途中退出は未測定。',
            '黒字場率の分母は活動場、金額利益割合は完結親総利益/(総利益+総損失)。',
            '5寄与は停止による後続入口消失も含む場全体の実経済。単親の改善とは別。'])
    sha=tools.write('全6の安定性と二対照5寄与の小結.json',summary)
    plan=dict(全合格=True,金融結果SHA256=resultsha,小結SHA256=sha,選抜=targets,
        選定範囲='2商品×2入口mode。各mode内の3窓と33場から最大の実測診断例を選ぶ。政策の採用/閾値最適化はしない。',
        読取予定='選抜された場cache各1読、当該新政策/P1L8/P1L4実台帳各1読。全396台帳再読なし。',
        新金融=0,原NPZ=0,API=0)
    plan_sha=tools.write('具体例の読取前選抜計画.json',plan)
    print(sha,plan_sha,flush=True)
    for r in rows:
        print(r['id'],r['symbol'],r['収支'],'黒/赤/無',r['黒字場'],r['赤字場'],r['無取引場'],
            '上位3除外',r['上位3利益場除外収支'],'中央値',r['中央値'],'利益割合',r['利益割合'],flush=True)


if __name__=='__main__':main()
