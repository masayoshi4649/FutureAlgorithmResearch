"""追加ナイトの素材監査を必須前提として凍結した統合再生を起動する。"""

import hashlib
import json
from pathlib import Path
import pickle
import subprocess
import sys

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]


def sha(path: Path) -> str:
    """機能: 内容のSHA256を計算する。

    引数: path(Path)。返り値: 指紋(str)。
    """
    value=hashlib.sha256()
    with path.open('rb') as stream:
        while block:=stream.read(8388608):value.update(block)
    return value.hexdigest()


def equal(a: object,b: object) -> None:
    """機能: 監査した追加素材と実使用の統合入力を再帰的に照合する。

    引数: a/b(object)。返り値: なし(None)。
    """
    if isinstance(a,np.ndarray):np.testing.assert_array_equal(a,b)
    elif isinstance(a,dict):
        assert set(a)==set(b)
        for key in a:equal(a[key],b[key])
    elif isinstance(a,(tuple,list)):
        assert len(a)==len(b)
        for x,y in zip(a,b):equal(x,y)
    elif isinstance(a,(float,np.floating)) and np.isnan(a):
        assert isinstance(b,(float,np.floating)) and np.isnan(b)
    else:assert a==b,(type(a),type(b))


def preflight() -> dict:
    """機能: 原素材4信号の監査成功・指紋と実入力の同値を起動前に確認する。

    引数: なし。返り値: 前提証跡(dict)。新たな条件選抜は行わない。
    """
    def read(path: Path) -> dict:
        """機能: 起動前提のJSONを読む。

        引数: path(Path)。返り値: 証跡(dict)。
        """
        return json.loads(path.read_text(encoding='utf-8'))
    proof=read(HERE/'new_mid_signal_audit.json')
    assert proof['全合格'] and proof['入力信号数']==len(proof['結果'])==4
    expected={(code,'2026-09-29_Night',symbol) for code in ('B00','B01') for symbol in ('TOPIX','NK225')}
    assert {(r['id'],r['session'],r['symbol']) for r in proof['結果']}==expected
    for row in proof['結果']:
        assert all(row[k] is True for k in ('切断一致','未来変更一致','上下反射一致','同秒順一致','方向公開源品質を再生成'))
    paths={'new_mid_signal_check.py':HERE/'new_mid_signal_check.py','replay_parts.py':HERE/'replay_parts.py',
        'deterioration_signals.py':HERE.parent/'wave_v35/deterioration_signals.py',
        'new_inputs.pkl':HERE/'new_inputs.pkl','new_features_depth.pkl':HERE/'new_features_depth.pkl'}
    assert set(proof['実装SHA256'])=={'new_mid_signal_check.py','replay_parts.py','deterioration_signals.py'}
    assert set(proof['入力SHA256'])=={'new_inputs.pkl','new_features_depth.pkl'}
    for mapping in ('実装SHA256','入力SHA256'):
        for name,expected_sha in proof[mapping].items():assert sha(paths[name])==expected_sha,name
    assert read(HERE/'new_signal_audit.json')['全合格']
    extraction=read(HERE/'追加ナイト入力監査.json')
    assert extraction['全合格']
    assert set(extraction['出力SHA256'])=={(HERE/name).relative_to(ROOT).as_posix() for name in
        ('inputs.pkl','features_depth.pkl','new_inputs.pkl','new_features_depth.pkl')}
    for name,expected_sha in extraction['出力SHA256'].items():assert sha(ROOT/name)==expected_sha,name
    one=pickle.loads((HERE/'new_inputs.pkl').read_bytes());all_inputs=pickle.loads((HERE/'inputs.pkl').read_bytes())
    frames=pickle.loads((HERE/'new_features_depth.pkl').read_bytes());all_frames=pickle.loads((HERE/'features_depth.pkl').read_bytes())
    expected_keys={('2026-09-29_Night',symbol) for symbol in ('TOPIX','NK225')}
    assert len(one)==len(frames)==2 and set(one)==set(frames)==expected_keys
    for key in one:
        equal(one[key],all_inputs[key]);assert frames[key].equals(all_frames[key])
    files=list(paths.values())+[Path(__file__),HERE/'inputs.pkl',HERE/'features_depth.pkl',
        HERE/'new_mid_signal_audit.json',HERE/'new_signal_audit.json',HERE/'追加ナイト入力監査.json',HERE/'統合追試の固定.json']
    return dict(全合格=True,新素材4信号監査成功=True,実使用2入力と特徴が監査素材に一致=True,
        参照SHA256={p.relative_to(ROOT).as_posix():sha(p) for p in files},条件の追加変更=False)


def main() -> None:
    """機能: 前提を固定し別プロセスで凍結再生し、同じ前提の不変を確認する。

    引数: なし。返り値: なし(None)。新しいプロセスは画面を開かない。
    """
    proof=preflight();path=HERE/'統合追加ナイトの入力前提.json'
    if path.exists():assert json.loads(path.read_text(encoding='utf-8'))==proof
    else:path.write_text(json.dumps(proof,ensure_ascii=False,indent=2),encoding='utf-8')
    print('新素材B00/B01と実使用入力の接続を検算。追加Night統合12方式を開始。',flush=True)
    result=subprocess.run([sys.executable,'-X','utf8',str(HERE/'integrated_followup.py'),'new','--workers','2'],
        cwd=ROOT,creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode==0,result.returncode
    assert preflight()==proof
    done=HERE/'統合追加ナイトの入力前提完了.json'
    done.write_text(json.dumps(dict(全合格=True,開始前後の入力前提不変=True,
        起動前提SHA256=sha(path),完備SHA256=sha(HERE/'integration_followup/new/complete.json')),
        ensure_ascii=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
