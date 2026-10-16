"""元の30秒支持を再現し、両市場の参照順だけを新領域へ保存する。"""
from pathlib import Path
import importlib.util
import json
import pickle
import sys
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'prepared'
sys.dont_write_bytecode=True


def module(name,path):
    """
    機能: 読取実装を固有名で読み込む。
    引数: name(str)、path(Path)。
    返り値: module。
    """
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);sys.modules[name]=result;spec.loader.exec_module(result)
    return result


old=module('wave87_prepare85',ROOT/'work/wave_v85/prepare.py')
signals=module('wave87_round3_signals',HERE/'signals.py')


def prepare():
    """
    機能: 全60口座の公開短期支持を旧式と独立照合して保存する。
    引数: なし。
    返り値: dict の指紋・因果監査。売買損益を計算しない。
    """
    OUT.mkdir(parents=True,exist_ok=True)
    assert not (OUT/'支持準備の照合.json').exists(),'完成済み準備を上書きしません'
    inputs,_,input_hash=old.load_inputs(verify=True)
    original=old.read(ROOT/'work/wave_v85/prepared/入力準備の完了.json')
    comparator=module('wave87_entry47',ROOT/'work/wave_v47/component_signals.py')
    import numba
    numba.config.CACHE_DIR=str(HERE/'cache')
    models={};hashes={};checks=[]
    for pair in original['入力対応']:
        path=(ROOT/pair['inputs']).with_name('new_features_depth.pkl')
        hashes[str(path.relative_to(ROOT))]=old.sha(path)
        frames=pickle.loads(path.read_bytes())
        for key,frame in frames.items():
            if key not in inputs: continue
            model=signals.event_model(inputs[key],frame)
            expected=comparator.short_model(inputs[key],frame,1.)
            for name,field in (('release','time_s'),('seq','seq'),('value','short')):
                np.testing.assert_array_equal(model[name],expected[field])
            models[key]=model
            checks.append(dict(session=key[0],symbol=key[1],公開イベント数=len(model['seq']),旧30秒値完全一致=True))
        comparator.clear_cache()
    assert set(models)==set(inputs)
    expanded={}
    for key,r in inputs.items():
        peer=(key[0],'TOPIX' if key[1]=='NK225' else 'NK225')
        expanded[key]=signals.expand(r,models[key],models[peer])
    path=OUT/'short.pkl'
    path.write_bytes(pickle.dumps(dict(events=models,expanded=expanded),protocol=5))
    sources={str(p.relative_to(ROOT)):old.sha(p) for p in (HERE/'signals.py',HERE/'prepare.py',Path(comparator.__file__),Path(comparator.HIERARCHY.__file__),Path(comparator.HIERARCHY.LEGACY.__file__))}
    proof=dict(全合格=True,売買損益未計算=True,入力SHA256=input_hash,公開特徴SHA256=hashes,
        実装SHA256=sources,出力SHA256=old.sha(path),全30=original['全30'],口座=checks,
        意味='元の公開イベント時刻における30秒中値差/当時ATRを完全再現。終端元行/時刻と公開行/時刻を分離。自己は公開seqまで、相手は自己現在時刻より厳密過去の公開イベントだけを使う。追加の秒単位鮮度閾値なし。')
    (OUT/'支持準備の照合.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return proof


def load(verify=True):
    """
    機能: 準備済み短期支持を指紋確認して読む。
    引数: verify(bool)。
    返り値: tuple[dict,dict] の展開配列と準備証拠。
    """
    proof=old.read(OUT/'支持準備の照合.json')
    if verify:
        assert old.sha(OUT/'short.pkl')==proof['出力SHA256']
        old.check_mapping(proof['公開特徴SHA256'])
    return pickle.loads((OUT/'short.pkl').read_bytes())['expanded'],proof


if __name__=='__main__':
    proof=prepare()
    print('全口座',len(proof['口座']),'旧支持値一致・損益未計算')
