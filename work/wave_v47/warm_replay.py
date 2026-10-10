"""暖機した入口だけを差し替え、既存と同じ経済再生へ接続する。"""

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import replay_parts as replay
import warm_component_signals as warm

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def main() -> None:
    """機能: 12暖機入口×3管理の全36条件を旧13場で比較する。

    引数: なし。返り値: なし(None)。追加ナイトは対象に含めない。
    """
    source=replay.previous.read(HERE/'warm_signals_fixed.json')
    assert source['全合格'] and source['条件']==warm.catalog()
    for name,sha in source['参照SHA256'].items():assert replay.previous.digest(ROOT/name)==sha,name
    for spec in source['条件']:
        original=HERE/'warm_entries'/(spec['id']+'.npz')
        expected=source['入口保存列SHA256'][original.relative_to(ROOT).as_posix()]
        assert replay.previous.digest(original)==expected
        target=HERE/'component_entries'/original.name
        if target.exists():assert target.read_bytes()==original.read_bytes()
        else:target.write_bytes(original.read_bytes())
    fixed=dict(暖機信号固定SHA256=replay.previous.digest(HERE/'warm_signals_fixed.json'),
        条件=source['条件'],管理条件=list(replay.BASE_IDS),条件数=36,旧入力数=26,新Night使用=False,
        経済実装SHA256=replay.previous.digest(Path(replay.__file__)),
        評価='初期化する完全対応条件との差。主倍率3点が全13/後7両銘柄の黒字・1枚平均勝敗比>1・上位利益2組除外黒字を同時に満たすか。',
        注記='信号は過去場の確定終値で暖機。ATR・20分待機・保有の場内返済・出口を維持。')
    path=HERE/'暖機経済比較の固定.json'
    if path.exists():assert replay.previous.read(path)==fixed
    else:replay.save(path,fixed)
    with ProcessPoolExecutor(max_workers=3,initializer=replay.initialize,initargs=('entry',)) as pool:
        tasks={pool.submit(replay.run_entry,s):s['id'] for s in source['条件']}
        completed=[]
        for i,future in enumerate(as_completed(tasks),1):
            completed.append(future.result());print(f'暖機 {i}/12 {tasks[future]} 完了',flush=True)
    replay.save(HERE/'warm_complete.json',dict(全合格=True,条件数=36,入力会計数=936,
        固定SHA256=replay.previous.digest(path),完了=completed,新Night使用=False))


if __name__=='__main__':main()
