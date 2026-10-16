"""黒字改善場と失った勝ちだけを少量の保存台帳から補完する。"""

import hashlib

import tools
import detail

TARGETS={'TOPIX':['2026-09-25_Night','2026-10-12_Night','2026-10-02_Night','2026-10-09_Night'],
         'NK225':['2026-09-23_Day','2026-10-02_Night']}


def run() -> None:
    """
    機能: 最初の全数診断で省いた黒字場の旧親例を目的固定して少量補完する。
    引数: なし。
    返り値: None。追加は新cache5/台帳12のみ、金融・原NPZは読まない。
    """
    root,sha=tools.read(tools.SOURCE/'finance/結果.json');assert root['全合格']
    cfg=next(c for c in root['configs'] if c['id']==detail.PRIMARY)
    meta,_=tools.read(tools.SOURCE/'全33場のE01取引更新準備.json')
    old={i['session']+'|'+i['symbol']:i for i in root['new_D0_P1L8']['ledgers']}
    fresh={i['session']+'|'+i['symbol']:i for i in root['results'][detail.PRIMARY]['ledgers']}
    tools.write('改善場と消えた勝ちの補完読取前固定.json',dict(対象=TARGETS,
        理由='初回全24診断の最悪3場は赤字場に限ったため、黒字改善場の避けた旧損失と黒字場で消えた旧勝ちを補完。',
        予定読取=dict(新cache=5,台帳=12,新金融=0,原NPZ=0,API=0),
        source_SHA256={p.relative_to(tools.ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in tools.HERE.glob('*.py')}))
    result={s:{} for s in TARGETS};cache_count=ledger_count=0
    for session in sorted(set(sum(TARGETS.values(),[]))):
        packet=detail.checked(meta['cache'][session]);cache_count+=1
        for symbol,scenes in TARGETS.items():
            if session not in scenes:continue
            key=session+'|'+symbol;before=detail.checked(old[key]);after=detail.checked(fresh[key]);ledger_count+=2
            delta=tools.contribution(before,after)
            result[symbol][session]=detail.scene(before,after,packet['accounts'][symbol],cfg,delta)
    assert cache_count==5 and ledger_count==12
    print(tools.write('改善場と消えた勝ちの原行価格の補完.json',dict(全合格=True,条件=detail.PRIMARY,results=result,
        新cache追加読取=cache_count,台帳追加読取=ledger_count,全数再読=0,新金融=0,原NPZ=0,API=0,
        source=dict(path='work/wave_v106/e01_trade_gate/finance/結果.json',sha256=sha))),flush=True)


if __name__=='__main__':run()
