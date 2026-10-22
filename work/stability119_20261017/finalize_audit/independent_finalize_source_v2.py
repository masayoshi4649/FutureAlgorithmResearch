"""終了反映部品を小人工正本だけで確認する。実台帳・金融・登録には触れない。"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
FINALIZER = WORK / 'finalize119.py'
MANAGER = ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py'


def module(path: Path, name: str) -> object:
    """
    機能: 実行入口を起動せず指定Python源の関数だけを接続する。
    引数: path(Path)、name(str)は源と一意名。
    返り値: objectは接続したmodule。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def write(path: Path, value: object) -> bytes:
    """
    機能: 人工所有域へ有限JSONを保存する。
    引数: path(Path)、value(object)は保存先と人工値。
    返り値: bytesは保存したUTF-8。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode('utf-8')
    path.write_bytes(data)
    return data


def main() -> None:
    """
    機能: 終了反映の保全・deep拒否・既完了比較を人工四正本で確認する。
    引数: なし。
    返り値: None。人工証跡のみ保存し、原台帳・市場・金融・登録は使用しない。
    """
    target_source = FINALIZER.read_bytes()
    finalizer = module(FINALIZER, '_independent_finalizer119')
    manager = module(MANAGER, '_independent_manager119')
    checks = []
    def checked(name: str, condition: bool) -> None:
        """
        機能: 人工検査の意味と判定を保存する。
        引数: name(str)、condition(bool)は検査名と判定。
        返り値: None。不合格はその場で停止する。
        """
        assert condition, name
        checks.append(name)

    with tempfile.TemporaryDirectory(dir=HERE) as temporary:
        root = Path(temporary).resolve()
        work = root/'work'; public = root/'public'; data = root/'data'
        for folder in (work, public, data): folder.mkdir()
        for name in ('README.md', 'report.html'): (public/name).write_text('人工', encoding='utf-8')
        source = work/'source.py'; source.write_text('x = 1\n', encoding='utf-8')
        sources = {'work/source.py': hashlib.sha256(source.read_bytes()).hexdigest()}
        manifest_source = work/'inputs.json'; write(manifest_source, {'人工入力': True})
        identity = '119h_少額E01の時計逆行行除外による入力停止修正'
        spec = {'data': {'input_manifests': [{'path': 'work/inputs.json', 'sha256': hashlib.sha256(manifest_source.read_bytes()).hexdigest()}], 'sessions': ['人工場']}, 'implementation': sources}
        proposal = {'id': identity, 'spec': spec}
        write(work/'proposal.json', proposal); write(work/'fixed.json', {'sources': sources})
        write(work/'result.json', {'人工結果': True}); write(work/'audit.json', {'人工監査': True})
        definition = {'result':'result.json', 'proposal':'proposal.json', 'fixed':'fixed.json', 'source_key':'sources', 'accounting':{'raw_reads':0,'financial_accounts':14,'reused_financial_accounts':66}, 'text':'人工終了'}
        record = {'id':identity, 'definition':definition, 'result':{'path':'work/result.json','sha256':hashlib.sha256((work/'result.json').read_bytes()).hexdigest()}, 'audits':[{'path':'work/audit.json','sha256':hashlib.sha256((work/'audit.json').read_bytes()).hexdigest()}], 'readme':'public/README.md','report':'public/report.html'}
        completion = {'全合格':True, '根による完成確認':True, 'trials':[record]}
        completion_path = work/'completion.json'; write(completion_path, completion)
        previous_attempts = [{'status':'過去停止','内容':'消さない'}]
        objects = {'rules.json':{'rules':[]}, 'knowledge.json':{'findings':[]}, 'trials.json':{'updated_at':'人工初期','trials':[{'id':identity,'title':'人工試行','spec':spec,'status':'未実行','execution_attempts':copy.deepcopy(previous_attempts)}], 'repetition_audit':[]}, 'studies.json':{'studies':[]}}
        for name, value in objects.items(): write(data/name,value)
        old_bytes = (data/'trials.json').read_bytes()
        finalizer.ROOT, finalizer.HERE, finalizer.PUBLIC = root, work, public
        manager.ROOT, manager.DATA = root, data
        finalizer.manager_module = lambda: manager
        manager.rebuild(deep=True)

        # ----------------------------------------
        # 未完了からの反映では旧正本・履歴・ビューを保持する。
        first = finalizer.finalize(completion_path)
        updated = json.loads((data/'trials.json').read_bytes())
        current_row = updated['trials'][0]
        checked('初回だけ正本を更新', first['台帳更新']==1)
        checked('旧原bytesをhistoryへ保全', (root/first['旧台帳保全']).read_bytes()==old_bytes)
        checked('過去execution_attemptsの接頭を保持', current_row['execution_attempts'][:1]==previous_attempts)
        checked('h14新口座と66引用を保持', current_row['completion_accounting']==definition['accounting'])
        checked('deepとview同期', (data/'view-data.js').read_text(encoding='utf-8')==manager.bundle(manager.load(deep=True)))
        first_bytes = (data/'trials.json').read_bytes()
        repeated = finalizer.finalize(completion_path)
        checked('同一完了の再反映では書込0', repeated['既登録同値'] is True and repeated['台帳更新']==0 and (data/'trials.json').read_bytes()==first_bytes)

        # ----------------------------------------
        # 指紋変更と既定三試行の上書きは正本更新前に拒否する。
        old_definition_rejected = False
        try: finalizer.target_definitions([{'id':finalizer.TARGETS[0]['id'],'definition':definition}])
        except AssertionError: old_definition_rejected = True
        checked('既定三試行の定義上書き拒否', old_definition_rejected)
        source.write_text('x = 2\n',encoding='utf-8')
        source_rejected = False
        try: finalizer.finalize(completion_path)
        except AssertionError: source_rejected = True
        checked('源変更をdeep以前にも拒否', source_rejected and (data/'trials.json').read_bytes()==first_bytes)
        source.write_text('x = 1\n',encoding='utf-8')
        old_manifest_bytes = manifest_source.read_bytes(); write(manifest_source, {'人工入力':False})
        input_rejected = False
        try: finalizer.finalize(completion_path)
        except AssertionError: input_rejected = True
        checked('入力目録変更をdeepで拒否', input_rejected and (data/'trials.json').read_bytes()==first_bytes)
        manifest_source.write_bytes(old_manifest_bytes)
        stopped = copy.deepcopy(record); stopped['id']='119f_少額E01の商品別固定設定を追加七場へ適用'
        stopped['definition']['accounting']={'raw_reads':42,'financial_accounts':0,'input_preparation_failed':True}
        checked('f42読取金融0は停止扱い', finalizer.target_definitions([stopped])[0]['stopped'] is True)

        # ----------------------------------------
        # 既完了の比較対象から会計由来が抜けていないかを反証する。
        changed = copy.deepcopy(completion)
        changed['trials'][0]['definition']['accounting']['別の読取説明']='既反映内容と不一致'
        write(completion_path,changed)
        mismatch_rejected = False
        try: finalizer.finalize(completion_path)
        except AssertionError: mismatch_rejected = True
        checked('既完了の異なる会計由来を拒否', mismatch_rejected and (data/'trials.json').read_bytes()==first_bytes)
        write(completion_path, completion)
        write(work/'fixed.json', {'sources':sources, '別の固定記録':True})
        fixed_rejected = False
        try: finalizer.finalize(completion_path)
        except AssertionError: fixed_rejected = True
        checked('既完了の異なる固定記録を拒否', fixed_rejected and (data/'trials.json').read_bytes()==first_bytes)

    proof = {'全検査成立':True,'確認':checks,'問題候補':None,'源SHA256':hashlib.sha256(target_source).hexdigest(),'源終了SHA256':hashlib.sha256(FINALIZER.read_bytes()).hexdigest(),'実正本読取':0,'市場読取':0,'金融':0,'登録':0,'実源変更':0}
    assert proof['源SHA256']==proof['源終了SHA256']
    path = HERE/'終了反映の小人工正本監査と既完了会計比較の修正確認.json'
    assert not path.exists()
    write(path,proof)
    print(json.dumps({'確認数':len(checks),'問題候補':proof['問題候補'],'証跡SHA256':hashlib.sha256(path.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=='__main__': main()
