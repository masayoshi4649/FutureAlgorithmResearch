"""入力十分性だけで合意した主鮮度30秒を追加し、既存10秒同期を保持する。"""

import copy
import json
import pickle

import core
import prepare


def main() -> None:
    """機能: 鮮度30秒の主同期索引を別名で作り、指定根拠と指紋を記録する。

    引数: なし。返り値: なし(None)。既存10秒の索引・仕様内容を変更しない。
    """
    old_path=prepare.HERE/'sync.pkl'
    original_hash=prepare.digest(old_path)
    original=json.loads((prepare.HERE/'同期入力仕様.json').read_text(encoding='utf8'))
    ready,features=prepare.load_material()
    sync={s:core.session_sync(ready,features,s,max_age=30.) for s in original['sessions']}
    new_path=prepare.HERE/'sync_fresh30.pkl'
    new_path.write_bytes(pickle.dumps(sync,protocol=5))
    assert prepare.digest(old_path)==original_hash
    spec=copy.deepcopy(original)
    spec['max_cutoff_age_seconds']=30
    spec['鮮度']='主はcutoffからの古さ30秒以内。実古さはcutoff古さ+delay。無効又はreset先頭の救済なし。'
    spec['coverage']=[]
    for session,value in sync.items():
        for delay in prepare.DELAYS:
            spec['coverage'].append(dict(session=session,delay=delay,grid_count=len(value['grid']),
                TOPIX=int((value['indices'][delay]['TOPIX']>=0).sum()),NK225=int((value['indices'][delay]['NK225']>=0).sum()),
                both=int(value['both_available'][delay].sum()),both_fraction=float(value['both_available'][delay].mean())))
    spec.update(sync_file='work/wave_v75/inputs/sync_fresh30.pkl',sync_SHA256=prepare.digest(new_path),
        主仕様=True,旧10秒ファイル='work/wave_v75/inputs/sync.pkl',旧10秒SHA256=original_hash,
        選択根拠='損益を実行・閲覧する前に入力十分性だけで固定。基準遅延5秒・過去300秒双方端点かつ区間resetなしは10秒鮮度2619/66560、30秒8744/66560。',
        関数呼出し='core.asof_indices(...,max_age=30.)／core.session_sync(...,max_age=30.)。省略時10秒なので主算法は必ず指定する。',
        旧同期変更=False)
    prepare.save_json('同期入力仕様_fresh30.json',spec)
    print('主鮮度30秒の別名同期を生成、旧10秒指紋を保持',flush=True)


if __name__=='__main__':
    main()
