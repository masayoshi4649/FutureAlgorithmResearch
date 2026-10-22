"""最初の会計停止を隠さず、同一源の一場再診断を登録する。"""

import copy
import json
from pathlib import Path
import subprocess
import sys

import plan120 as P


def main() -> None:
    """
    機能: 金融停止を入力一場の独立再診断と分けて事前照合する。
    引数: なし。
    返り値: None。価格配列を読まず、数値パラメータを変えない。
    """
    here=P.HERE/'recovery_a'
    here.mkdir(exist_ok=False)
    meta=P.read(P.HERE/'入力目録.json')
    item=next(r for r in meta['inputs'] if r['symbol']=='NK225' and r['session']=='2026-09-21_Day')
    P.save(here/'入力目録.json',dict(inputs=[item],sessions=[item['session']]))
    fixed=P.read(P.HERE/'固定計画.json')
    sources={k:v for k,v in fixed['sources'].items() if Path(k).name in ('engine120.py','catalog120.py')}
    sources.update({(P.HERE/name).relative_to(P.ROOT).as_posix():P.digest(P.HERE/name)
        for name in ('debug120a.py','register120a.py')})
    manifest=dict(path=(here/'入力目録.json').relative_to(P.ROOT).as_posix(),sha256=P.digest(here/'入力目録.json'))
    P.save(here/'固定計画.json',dict(sources=sources,input_manifest=manifest))
    old=P.read(P.HERE/'試行計画.json')
    proposal=copy.deepcopy(old)
    proposal.update(id='120a_段階追尾の停止した一場の現金会計を独立診断',
        name='段階追尾の会計停止を同一源の一場で切分け',purpose='独立再検証',
        question='現金と完結玉損益の不一致は状態遷移か浮動計算か。源と注文条件を変えず保存して確認する。',
        change='元120はTOPIX一場48条件を保存後、最初NK一場の途中で恒等式assert停止。未保存途中件数は不明。結果を先に保存する診断driverへ変更、経済engine/catalogは不変。',
        repeat_reason='完成TOPIX48は再生せず保存引用。停止NK一場48だけを独立再診断し、差額と注文UIDを全保存する。不一致を許容して有効性合格にしない。',
        compares_to=[P.TRIAL],evidence=[dict(path=(P.HERE/'実行False.json').relative_to(P.ROOT).as_posix()),
            dict(path=(P.HERE/'audit/段階追尾全八管理の独立会計と原row因果性の人工監査_最終.json').relative_to(P.ROOT).as_posix())])
    proposal['spec']['implementation']=sources
    proposal['spec']['data']=dict(input_manifests=[manifest],sessions=[item['session']],
        入力='最初のNK一場の同一所有配列を独立診断のため一回再読。原市場0。')
    proposal['spec']['allocation']['数量']='元120と全く同じ48条件×NK一場。診断再生48で、新しい独立有効性根拠0。'
    P.save(here/'試行計画.json',proposal)
    for command,name in (('check','事前照合の全出力.json'),('register','正式登録の全出力.json')):
        process=subprocess.run([sys.executable,'-B','-X','utf8',str(P.MANAGER),command,'--proposal',str(here/'試行計画.json')],
            cwd=P.ROOT,capture_output=True,text=True,encoding='utf-8')
        P.save(here/name,dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True)
        assert process.returncode==0


if __name__=='__main__':
    main()
