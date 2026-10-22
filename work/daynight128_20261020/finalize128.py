"""登録済み五巡を検証済みに更新し、計画と結果の指紋を接続する。"""

import hashlib
import json
import subprocess
import sys
from common128 import HERE, ROOT, read, reference, save


def main():
    """
    機能: 五巡だけの実施状態と証拠を追記し、台帳の深い指紋検証を実施する。
    引数: なし。
    返り値: None。数値源・入力・金融会計を変更しない。
    """
    manager=ROOT/"アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    path=manager.parent/"data/trials.json"
    original=path.read_bytes()
    old_hash=hashlib.sha256(original).hexdigest()
    history=path.parent/"history"/("trials_"+old_hash+".json")
    if not history.exists():
        history.write_bytes(original)
    table=json.loads(original.decode("utf-8"))
    changed=[]
    counts=[]
    for n in range(1,6):
        id=f"128_round{n}_昼夜分離と損失原因による独立改善"
        row=next(r for r in table["trials"] if r["id"]==id)
        assert row["status"]=="未実行",row["status"]
        audit=read(HERE/f"audit/round{n}_全注文と全行会計の独立照合.json")
        data=read(HERE/f"round{n}/全条件の会計.json")
        assert audit["passed"] and data["passed"] and audit["accounts"]==len(data["rows"])
        row["status"]="検証完了・全体の安定性未達"
        row["result"]="日中D17は第一候補へ改善。夜間はTOPIX向けN36が参考候補、両商品共通N27は採用保留。詳しくは00128の公開結果。"
        row["evidence"] += [reference(HERE/f"round{n}/全条件の会計.json"),
            reference(HERE/f"round{n}/前後半と方向別の比較.json"),
            reference(HERE/f"audit/round{n}_全注文と全行会計の独立照合.json"),
            reference(HERE/"採用候補と公開記録.json")]
        changed.append(id)
        counts.append(dict(round=n,conditions=len(data["configs"]),accounts=len(data["rows"]),
            replays=data["financial_replays"],reused=data["aliases"]))
    temporary=path.with_suffix(".json.128tmp")
    temporary.write_text(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    temporary.replace(path)
    save(HERE/"試行完了の変更記録.json",dict(passed=True,changed=changed,before_sha256=old_hash,
        after=reference(path),counts=counts,financial_replays=0,achieved=False,
        limit="日中の改良と夜間新造は実装・五巡検証済み。全体の安定性という目的は未達。"))
    # ----------------------------------------
    # 台帳の表示用データは正本から生成する。既知の数値源も指紋照合する。
    for command in ("build","verify"):
        process=subprocess.run([sys.executable,"-B","-X","utf8",str(manager),command,"--deep"],
            cwd=ROOT,capture_output=True,text=True,encoding="utf-8")
        save(HERE/("最終台帳_"+command+".json"),dict(returncode=process.returncode,
            stdout=process.stdout,stderr=process.stderr))
        print(command,process.returncode,flush=True)
        assert process.returncode==0,process.stderr[-2000:]


if __name__=="__main__":
    main()
