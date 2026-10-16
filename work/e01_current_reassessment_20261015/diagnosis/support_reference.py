"""既保存の支持返済判断を初期線と比べる事後射影。別出口の利益は作らない。"""

import json
from pathlib import Path

import run

HERE=Path(__file__).resolve().parent
OUTPUT=HERE/'初期支持線と更新支持線の判断時比較.json'


def classify(parent: dict) -> str:
    """
    機能: reason143の当行BBOで、初期線も失っていたかを算術比較する。
    引数: parent(dict) は既保存の実親診断。
    返り値: str は初期線喪失又は初期線未喪失。先の回復・救済損益を推定しない。
    """
    assert parent['exits'][0]['reason']==143
    point=parent['exits'][0]['判断'];assert point['normal']
    line=parent['initial_support_line'];side=parent['side'];active=point['support_line']
    assert active is not None and (active>=line if side==1 else active<=line)
    assert (point['ask']<=active if side==1 else point['bid']>=active)
    lost=(point['ask']<=line if side==1 else point['bid']>=line)
    return '初期線も喪失' if lost else '更新線を喪失・初期線は未喪失'


def main() -> None:
    """
    機能: 一読目的射影の全支持返済を分類し、仮説の対象分母を保存する。
    引数: なし。
    返り値: None。元金融・台帳・cache・API・金融再実行は行わない。
    """
    assert not OUTPUT.exists()
    source=run.sources();p=json.loads(run.PROJECTION.read_text(encoding='utf-8'))
    assert p['source_SHA256']==source
    results={}
    for cid,case in p['cases'].items():
        results[cid]={}
        for symbol in run.CAP:
            parents=[v for v in case['parents'] if v['symbol']==symbol and v['exits'][0]['reason']==143]
            groups={label:[v for v in parents if classify(v)==label] for label in ('初期線も喪失','更新線を喪失・初期線は未喪失')}
            results[cid][symbol]={label:dict(**run.totals(vv),support_updated_parents=sum(bool(v['support_events']) for v in vv)) for label,vv in groups.items()}
    assert source==run.sources()
    run.write(OUTPUT,dict(全合格=True,出典結果SHA256=run.EXPECTED_SHA,元射影SHA256=run.sha(run.PROJECTION),
        source_SHA256=source,診断sourceSHA256=run.sha(Path(__file__)),results=results,
        留保='初期線が当行未喪失でも、以後保有する対照の損益・親数・場停止・後参加は未測。更新を外した場合の利益ではない。',
        元金融追加読=0,元台帳=0,cache=0,原板=0,API=0,新金融=0))
    print(json.dumps(dict(全合格=True,SHA256=run.sha(OUTPUT),main=results[run.MAIN]),ensure_ascii=False))


if __name__=='__main__':
    main()
