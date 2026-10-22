"""終了反映の追加ID定数一行だけを旧人工合格源へ結び付ける。"""

import ast
import hashlib
import json
from pathlib import Path


def main() -> None:
    """
    機能: 許可ID一行を除いたSOURCEが前回合格源と完全同一であることを確認する。
    引数: なし。
    返り値: None。SOURCE差分の証跡のみ保存し実台帳・市場・金融・登録は使用しない。
    """
    here=Path(__file__).resolve().parent;source=here.parent/'finalize119.py'
    payload=source.read_bytes();text=payload.decode('utf-8')
    identity='119i_相対乖離の実際の復帰確認と残差追尾の対照'
    lines=text.splitlines(keepends=True);found=[i for i,line in enumerate(lines) if line.strip()==repr(identity)+',']
    assert len(found)==1
    del lines[found[0]]
    old_sha=hashlib.sha256(''.join(lines).encode('utf-8')).hexdigest()
    assert old_sha=='7180a9c8e3e2bfc57f114edb8ee81d7324a1bc8ea3a4fdadde1e7257b70fe0bb'
    tree=ast.parse(text)
    assignment=next(v for v in tree.body if isinstance(v,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='ADDITIONAL_IDS' for t in v.targets))
    assert identity in ast.literal_eval(assignment.value)
    prior=here/'終了反映の小人工正本監査と既完了会計比較の修正確認.json';supplement=here/'終了反映の非停止正件数制約の補足.json'
    assert json.loads(prior.read_bytes())['源SHA256']==json.loads(supplement.read_bytes())['source_SHA256']==old_sha
    assert source.read_bytes()==payload
    proof={'全合格':True,'source_SHA256':hashlib.sha256(payload).hexdigest(),'変更':'ADDITIONAL_IDSへ119iを追加した一行だけ','変更前SOURCE_SHA256':old_sha,'関数及び他全bytes不変':True,'旧人工根拠':[{'path':p.name,'SHA256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in (prior,supplement)],'実台帳読取':0,'市場':0,'金融':0,'登録':0,'source変更':0}
    target=here/'終了反映の119i許可定数だけの差分拘束.json';assert not target.exists()
    target.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest(),proof['source_SHA256'])


if __name__=='__main__':main()
