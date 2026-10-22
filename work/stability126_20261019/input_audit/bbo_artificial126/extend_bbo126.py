"""次原行BBO人工へ、真の末尾切断・部分利確保全・固定アンカーを追加する。"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import time

import numpy as np

import check_bbo126 as test


HERE=Path(__file__).resolve().parent


def execute() -> None:
    """
    機能: 人工経路の真の切断と実現済み損益・初回固定ATRの扱いを独立に確認する。
    引数: なし。
    返り値: None。市場資料・金融再生は行わない。
    """
    configs={v['id']:v for v in test.catalog()}
    for qty in (5,10):
        base=test.mechanism_cases(qty)['A']
        for config in configs.values():
            full=test.run(base,config)
            cut=10;short=deepcopy(base)
            for field in ('seq','time_s','last','atr'):short[0][field]=short[0][field][:cut]
            for field in short[1]:short[1][field]=short[1][field][:cut]
            short=list(short);short[2]=short[2][:cut]
            short[3]['orders']=short[3]['orders'][short[3]['orders'][:,0]<cut]
            prefix=test.run(tuple(short),config)
            test.same('真の未来尾切断で過去曲線不変_'+str(qty)+'_'+config['id'],full['curve'][:cut],prefix['curve'])
            test.same('真の未来尾切断で過去注文不変_'+str(qty)+'_'+config['id'],full['orders'][full['orders'][:,0]<cut],prefix['orders'])
        # ----------------------------------------
        # 紙上通知値段をどれだけ変えても、実新規建値と実予算は当行BBOが基準。
        actual=test.fixture([110,110,110,105,106,108,109],[(0,1,5,1)],qty)
        first=test.run(actual,configs['E01'])
        modified=deepcopy(actual);modified[3]['orders'][:,5]=[-100000000.,100000000.]
        changed=test.run(modified,configs['E01'])
        for field in ('orders','trades','curve','stats'):
            test.same('紙上通知価格を実建値へ混入しない_'+str(qty)+'_'+field,first[field],changed[field])
        partial=test.mechanism_cases(qty)['P']
        partial[3]['orders'][1,4]=qty-qty//2
        partial[3]['orders']=np.vstack([partial[3]['orders'],[4,3,0,-1,qty//2,114.5,7,0]])
        partial[3]['orders']=partial[3]['orders'][np.argsort(partial[3]['orders'][:,0],kind='stable')]
        result=test.run(partial,configs['P01'])
        test.same('実現済み部分利確を含む利益床の返済行_'+str(qty),result['orders'][:,0],np.array([2.,5.,7.]))
        test.same('部分利確後も利益床は残数量を正しく清算_'+str(qty),result['orders'][:,4],np.array([qty,qty//2,qty-qty//2]))
        expected=7.*(qty//2)+5.*(qty-qty//2)
        test.check('部分利確の二重計上無し_'+str(qty),result['stats'][0]==expected)
        # ----------------------------------------
        # 初回の場riskと再参加アンカーATRを後続の大ATRで差し替えない。
        loss=test.mechanism_cases(qty)['L'];loss[3]['cycles'][1:,5]=1000.
        lr=test.run(loss,configs['L01']);stops=lr['execution_events'][lr['execution_events'][:,1]==10.]
        test.check('場riskは初回ATR4を後続ATR1000へ変えない_'+str(qty),len(stops)>0 and stops[0,6]==qty*4.)
        anchor=test.mechanism_cases(qty)['A'];anchor[2][9:,2:4]=400.
        ar=test.run(anchor,configs['A01']);releases=ar['execution_events'][ar['execution_events'][:,1]==14.]
        test.check('再参加進行は固定アンカーATR4を保持_'+str(qty),len(releases)>0 and releases[0,0]==9.)
        unknown=test.mechanism_cases(qty)['A'];unknown[2][6:,11]=0.
        ur=test.run(unknown,configs['A01'])
        test.check('相手欠測時は再参加アンカーを推測しない_'+str(qty),not np.isin(ur['execution_events'][:,1],[13.,14.]).any())
        test.same('欠測の再参加拒否は実新規の不足として残す_'+str(qty),ur['orders'][ur['orders'][:,7]==1.,0],np.array([2.]))
        tied=test.fixture([100]*7,[(0,1,5,1)],qty)
        tied[0]['time_s'][2]=tied[0]['time_s'][1];tied[1]['time_s'][2]=tied[1]['time_s'][1]
        tr=test.run(tied,configs['E01'])
        test.check('同価格時計でも後続原行だけで約定_'+str(qty),tr['orders'][0,0]==2. and tr['orders'][0,1]==1.)
    source={p.relative_to(test.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (test.BBO/'core126.py',test.BBO/'bbo_order_kernel126.py',test.BBO/'policy_bbo126.py',test.ENGINE/'policy126.py',Path(__file__),HERE/'check_bbo126.py')}
    result=dict(passed=True,checks=test.CHECKS,count=len(test.CHECKS),cases=test.CASES,
                case_count=len(test.CASES),sources=source,
                prior_proof_sha256=hashlib.sha256((HERE/'次正常原行と実会計及び三部品の独立純人工.json').read_bytes()).hexdigest(),
                market_reads=0,financial_replays=0,API=0,real_orders=0)
    target=HERE/'未来尾切断と部分利確及び固定ATRの追加独立純人工.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(passed=True,count=len(test.CHECKS),cases=len(test.CASES)),ensure_ascii=False))


if __name__=='__main__':
    try:execute()
    except Exception as error:
        path=HERE/('追加純人工停止_'+str(time.time_ns())+'.json')
        path.write_text(json.dumps(dict(passed=False,error=repr(error),checks=test.CHECKS,cases=test.CASES,
            market_reads=0,financial_replays=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        raise
