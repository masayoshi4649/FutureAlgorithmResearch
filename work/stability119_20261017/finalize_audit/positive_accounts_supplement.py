"""非停止試行の会計件数0拒否を人工パスだけで確認する。"""

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile


def main() -> None:
    """
    機能: 既修正12確認に対し、非停止試行の正件数制約だけを追加検査する。
    引数: なし。
    返り値: None。人工証跡を保存し、実台帳・市場・金融・登録は使用しない。
    """
    here=Path(__file__).resolve().parent
    source=here.parent/'finalize119.py'
    payload=source.read_bytes()
    spec=importlib.util.spec_from_file_location('_finalize_positive_only',source)
    value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value)
    with tempfile.TemporaryDirectory(dir=here) as folder:
        root=Path(folder).resolve();value.ROOT=root;value.HERE=root
        for name in ('result','proposal','fixed'): (root/name).write_text('人工',encoding='utf-8')
        row={'id':'119d_広い共同進行と離脱及び遅行追随を同時点で逆建て','definition':{'result':'result','proposal':'proposal','fixed':'fixed','source_key':'sources','accounting':{'raw_reads':0,'financial_accounts':1},'text':'人工'}}
        assert value.target_definitions([row])[0]['accounting']['financial_accounts']==1
        zero=copy.deepcopy(row);zero['definition']['accounting']['financial_accounts']=0
        rejected=False
        try:value.target_definitions([zero])
        except AssertionError:rejected=True
        assert rejected
    previous=here/'終了反映の小人工正本監査と既完了会計比較の修正確認.json'
    prior=json.loads(previous.read_bytes())
    assert prior['源SHA256']==hashlib.sha256(payload).hexdigest()==hashlib.sha256(source.read_bytes()).hexdigest()
    proof={'全合格':True,'追加確認':['非停止1口座は許可','非停止0口座は拒否'],'委譲した12確認':{'path':previous.name,'SHA256':hashlib.sha256(previous.read_bytes()).hexdigest()},'source_SHA256':hashlib.sha256(payload).hexdigest(),'実台帳読取':0,'市場':0,'金融':0,'登録':0}
    target=here/'終了反映の非停止正件数制約の補足.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
