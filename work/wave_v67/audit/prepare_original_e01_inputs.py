"""依頼された追加５場の元E01素材を既存抽出器で新作業だけへ保存する。"""

import gc
import hashlib
import importlib.util
import json
from pathlib import Path
import pickle
import socket
import sys
import time


HERE=Path(__file__).resolve().parent
WORK=HERE.parent
ROOT=HERE.parents[2]
SESSIONS=('2026-10-06_Night','2026-10-07_Day','2026-10-07_Night','2026-10-08_Day','2026-10-08_Night')


def sha(path):
    """機能: 読み取り元又は新出力の内容ハッシュを分割計算する。

    引数: path(Path)。返り値: SHA256文字列(str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(4*1024*1024):value.update(block)
    return value.hexdigest()


def save(path,data):
    """機能: 新作業67だけへ抽出進捗と完了証跡を保存する。

    引数: path(Path)、data(dict)。返り値: なし(None)。
    """
    assert path.resolve().is_relative_to(WORK)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    """機能: 既存再生器の抽出先を差し替え、５場を逐次抽出して元信号の因果監査を実行する。

    引数: なし。返り値: なし(None)。旧素材・App・原本は変更せず、API接続を拒否する。
    """
    sys.dont_write_bytecode=True
    source=ROOT/'work/wave_v50/update_20261001_day/replay_added_session.py'
    spec=importlib.util.spec_from_file_location('元E01追加入力67',source)
    app=importlib.util.module_from_spec(spec);sys.modules[spec.name]=app;spec.loader.exec_module(app)
    previous=app.previous;socket.socket.connect=previous.deny;socket.create_connection=previous.deny
    sources={Path(m.__file__).resolve() for m in tuple(sys.modules.values()) if getattr(m,'__file__',None)
        and Path(m.__file__).suffix=='.py' and Path(m.__file__).resolve().is_relative_to(ROOT/'work')}
    source_hash={str(p.relative_to(ROOT)):sha(p) for p in sorted(sources)}
    save(WORK/'prepared/抽出前固定.json',dict(対象=SESSIONS,既存実装SHA256=source_hash,出力根=str(WORK/'prepared'),
        手順='既存module読込、previous.HEREを場別出力先へ差替、extractとsignal_audit、元signals.pkl保存。条件変更・売買計算はしない。',API追加取得数=0))
    completed=[]
    for session in SESSIONS:
        start=time.perf_counter();target=WORK/'prepared'/session;target.mkdir(parents=True,exist_ok=True)
        previous.HERE=target;app.HERE=target
        assert not (target/'signals.pkl').exists(),'完成済み素材は上書きしない'
        print(session,'元E01素材の抽出開始',flush=True)
        inputs,features=previous.extract(session)
        signals=previous.signal_audit(inputs,features)
        signal_path=target/'signals.pkl';signal_path.write_bytes(pickle.dumps(signals,protocol=pickle.HIGHEST_PROTOCOL))
        proof=dict(対象=session,全合格=True,口座数=len(inputs),入力有効行数=sum(len(r['seq']) for r in inputs.values()),
            信号種類=list(signals),既存条件変更=False,API追加取得数=0,処理秒=time.perf_counter()-start,
            出力SHA256={str(p.relative_to(ROOT)):sha(p) for p in (target/'new_inputs.pkl',target/'new_features_depth.pkl',signal_path,target/'入力監査.json',target/'信号監査.json')})
        save(target/'抽出完了.json',proof);completed.append(proof)
        save(WORK/'prepared/抽出進捗.json',dict(完了場数=len(completed),対象場数=len(SESSIONS),場別=completed))
        print(session,'抽出・元信号因果監査完了',round(proof['処理秒'],1),'秒',flush=True)
        del inputs,features,signals;gc.collect()
    assert all(sha(ROOT/p)==v for p,v in source_hash.items())
    save(WORK/'prepared/抽出完了.json',dict(全合格=True,対象場数=len(SESSIONS),既存実装不変=True,API追加取得数=0,場別=completed,
        抽出コードSHA256=sha(Path(__file__))))


if __name__=='__main__':main()
