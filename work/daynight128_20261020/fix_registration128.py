"""第一巡の登録書式だけを訂正し、失敗出力を保存する。"""

import subprocess
import sys
from common128 import HERE, ROOT, read, save, reference


def main():
    """
    機能: 根拠を位置文字列から位置と指紋の辞書へ訂正して登録する。
    引数: なし。
    返り値: None。固定した条件・入力・数値源は変更しない。
    """
    folder=HERE/"round1"
    old=folder/"登録.json"
    assert read(old)["returncode"] == 1
    archived=folder/"登録_目録書式拒否.json"
    assert not archived.exists()
    old.rename(archived)
    proposal=read(folder/"試行計画.json")
    proposal["evidence"]=[reference(folder/"固定計画.json")]
    proposal["spec"]["data"]["input_manifests"]=proposal["spec"]["data"].pop("input_references")
    proposal["spec"]["data"]["sessions"]=[p["session"] for p in read(HERE/"入力準備.json")["packets"]]
    path=folder/"試行計画_目録確定.json"
    save(path,proposal)
    manager=ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    for command,name in (("check","照合_目録確定.json"),("register","登録.json")):
        p=subprocess.run([sys.executable,"-B","-X","utf8",str(manager),command,"--proposal",str(path)],
            cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        save(folder/name,dict(returncode=p.returncode,stdout=p.stdout,stderr=p.stderr))
        print(command,p.returncode,flush=True)
        assert p.returncode == 0,p.stderr[-1000:]


if __name__=="__main__":
    main()
