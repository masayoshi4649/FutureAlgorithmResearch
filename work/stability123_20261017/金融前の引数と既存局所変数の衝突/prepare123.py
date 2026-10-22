"""旧源を変更せず、最初の参加距離と段間隔だけを独立変数にする。"""

import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main() -> None:
    """
    機能: 検証済み状態機械の第一段だけを引数化し、代理会計をそのまま接続する。
    引数: なし。
    返り値: None。人工確認と金融再生は行わない。
    """
    corepath=ROOT/'work/stability121_20261017/engine121.py'
    raw=corepath.read_bytes();assert hashlib.sha256(raw).hexdigest()=='915e0dc1dea2af979a9b54647117bf4aa9217b171592c59520589b48adf61ee2'
    text=raw.decode('utf-8').replace('\r\n','\n')
    changes=[
        ('observed_tick,unit,mode,trail,spacing,reset_after_profit,','observed_tick,unit,initial,mode,trail,spacing,reset_after_profit,'),
        ('observed_tick/unit/trail/spacing/場内時刻(float)', 'observed_tick/unit/initial/trail/spacing/場内時刻(float)'),
        ('and unit>0. and trail>0.', 'and unit>0. and initial>0. and trail>0.'),
        ('line=anchor[s,j]+side*(3.+level[s,j]*spacing)*step','line=anchor[s,j]+side*(initial+level[s,j]*spacing)*step'),
    ]
    for before,after in changes:
        assert text.count(before)==1,(before,text.count(before));text=text.replace(before,after,1)
    core=HERE/'core123.py';assert not core.exists();core.write_bytes(text.encode('utf-8'))
    wrapperpath=ROOT/'work/stability122_20261017/engine122.py'
    rawwrapper=wrapperpath.read_bytes();assert hashlib.sha256(rawwrapper).hexdigest()=='eee2be83739b0609b69fcec7987e16152a2268fb4829bad799c25e7580e62451'
    wrapper=rawwrapper.decode('utf-8').replace('\r\n','\n')
    begin=wrapper.index("HERE=Path(__file__)")
    end=wrapper.index('\nPROXY_COLUMNS=')
    wrapper=wrapper[:begin]+'import core123 as BASE\n'+wrapper[end:]
    edits=[('def evaluate(quotes: dict,setting: dict,kind: str) -> tuple:',
        'def evaluate(quotes: dict,setting: dict,kind: str,initial: float,spacing: float) -> tuple:'),
        ('kind(str)はEARLY又はCLOSE_PROXY。','kind(str)はEARLY又はCLOSE_PROXY、initial/spacing(float)は初回距離と間隔pt。'),
        ('**config,unit=1.,mode=2,trail=float(\'inf\'),spacing=3.,reset_after_profit=False)',
         '**config,unit=1.,initial=initial,mode=2,trail=float(\'inf\'),spacing=spacing,reset_after_profit=False)')]
    for before,after in edits:
        assert wrapper.count(before)==1,(before,wrapper.count(before));wrapper=wrapper.replace(before,after,1)
    target=HERE/'engine123.py';assert not target.exists();target.write_bytes(wrapper.encode('utf-8'))
    proof=dict(core_source=corepath.relative_to(ROOT).as_posix(),core_source_sha256=hashlib.sha256(raw).hexdigest(),
        core_sha256=hashlib.sha256(core.read_bytes()).hexdigest(),core_changes=changes,
        wrapper_source=wrapperpath.relative_to(ROOT).as_posix(),wrapper_source_sha256=hashlib.sha256(rawwrapper).hexdigest(),
        engine_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),wrapper_changes=edits,financial_accounts=0)
    (HERE/'初回距離だけを引数化した源の差分.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in proof.items() if k.endswith('sha256')},ensure_ascii=False))


if __name__=='__main__':
    main()
