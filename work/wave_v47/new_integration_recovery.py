"""旧照合入力の初期化漏れだけを補完し、固定済み12方式を全件完了させる。"""

from concurrent.futures import ProcessPoolExecutor,as_completed
from pathlib import Path

import integrated_followup as original
import launch_new_integration as prerequisite

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
read=original.replay.previous.read
save=original.replay.save
sha=original.replay.previous.digest
verify=original.replay.previous.verify


def initialize() -> None:
    """機能: 元校正の辞書も正式な旧初期化で用意した後、追加素材を準備する。

    引数: なし。返り値: なし(None)。変更は参照辞書の初期化だけで経済関数は共通。
    """
    original.integration.initialize()
    original.initialize('new')
    for symbol in ('TOPIX','NK225'):
        key=('2026-09-29_Day',symbol)
        assert key in original.integration.reference.INPUTS
        assert len(original.integration.reference.INPUTS[key]['last'])==len(original.INPUTS[key]['last'])


def freeze() -> dict:
    """機能: 不完了原因と既完了9成果を保存し、全12の補完条件を固定する。

    引数: なし。返り値: 修正工程固定(dict)。元固定・元再生コードは変更しない。
    """
    path=HERE/'統合追加ナイトの初期化修正.json'
    if path.exists():
        fixed=read(path);verify(fixed['参照SHA256']);return fixed
    baseline=read(HERE/'統合追試の固定.json');verify(baseline['参照SHA256'])
    assert baseline['追加ナイト']==original.catalog('new')
    assert read(HERE/'exit_integration_complete.json')['全合格']
    assert read(HERE/'integration_followup/clock/complete.json')['全合格']
    old_calibration=read(HERE/'統合追加ナイトの照合元固定.json');verify(old_calibration)
    evidence=prerequisite.preflight()
    assert evidence==read(HERE/'統合追加ナイトの入力前提.json')
    previous={}
    for spec in baseline['追加ナイト']:
        completed=HERE/'integration_followup/new/completed'/(spec['id']+'.json')
        if completed.exists():
            record=read(completed);assert record['全合格']
            verify(record['出力SHA256']);previous[spec['id']]=record['出力SHA256']
    assert set(previous)=={s['id'] for s in baseline['追加ナイト'] if s['quantity_id']!='A0'} and len(previous)==9
    references=dict(baseline['参照SHA256']);references.update(old_calibration);references.update(evidence['参照SHA256'])
    for item in (Path(__file__),Path(prerequisite.__file__),HERE/'統合追試の固定.json',
        HERE/'統合追加ナイトの入力前提.json',HERE/'統合追加ナイトの照合元固定.json'):
        references[item.relative_to(ROOT).as_posix()]=sha(item)
    fixed=dict(原因='元校正用integration.reference.INPUTS未初期化。A0品質ゼロ列の長さ取得でKeyError、全体未完了。',
        修正='正式なintegration.initializeの後、元initialize(new)を呼ぶ。元evaluate/inspect/売買・信号・パラメータは不変更。',
        全再生=baseline['追加ナイト'],成功済9成果=previous,参照SHA256=references,
        新損益による条件変更=False,API追加取得数=0)
    save(path,fixed);return fixed


def main() -> None:
    """機能: 固定12方式を補完初期化で再生し、旧9不変と全完備を確認する。

    引数: なし。返り値: なし(None)。途中成功分だけを公表しない。
    """
    fixed=freeze();specs=fixed['全再生'];done=[]
    with ProcessPoolExecutor(max_workers=2,initializer=initialize) as pool:
        tasks={pool.submit(original.evaluate,s,'new'):s['id'] for s in specs}
        for i,future in enumerate(as_completed(tasks),1):
            done.append(future.result());print(f'追加ナイト補完 {i}/12 {tasks[future]} 全監査完了',flush=True)
    assert len(done)==12 and {d['id'] for d in done}=={s['id'] for s in specs}
    outputs={}
    for record in done:
        assert record['全合格'] and record['入力数']==record['因果検査数']==record['旧照合数']==2
        assert record['固定SHA256']==sha(HERE/'統合追試の固定.json')
        verify(record['出力SHA256']);outputs.update(record['出力SHA256'])
    for identifier,files in fixed['成功済9成果'].items():
        verify(files)
        assert next(d for d in done if d['id']==identifier)['出力SHA256']==files
    verify(fixed['参照SHA256'])
    assert prerequisite.preflight()==read(HERE/'統合追加ナイトの入力前提.json')
    save(HERE/'integration_followup/new/complete.json',dict(全合格=True,条件数=12,入力数=24,完了=done,
        出力SHA256=outputs,固定SHA256=sha(HERE/'統合追試の固定.json'),初期化修正SHA256=sha(HERE/'統合追加ナイトの初期化修正.json'),
        成功済9条件の全経済成果不変=True,全24旧校正35指紋と10入力品質一致=True))
    save(HERE/'統合追加ナイトの入力前提完了.json',dict(全合格=True,開始前後の入力前提不変=True,
        起動前提SHA256=sha(HERE/'統合追加ナイトの入力前提.json'),完備SHA256=sha(HERE/'integration_followup/new/complete.json'),
        初期化補完の別固定=sha(HERE/'統合追加ナイトの初期化修正.json')))
    print('全12条件完備。既成功9方式は4成果ずつバイト不変、追加A0も全検査合格。',flush=True)


if __name__=='__main__':main()
