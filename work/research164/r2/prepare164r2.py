"""第一巡で確認済みの54場を、追加開発の入力として明示する。"""
import json
from datetime import datetime
from pathlib import Path
import hashlib


def main() -> None:
    """原資料を複製・変更せず、既知である旨だけ入力目録へ付記する。

    引数: なし。返り値: None。金融再生なし。
    """
    here=Path(__file__).resolve().parent
    source=here.parent/"inputs164.json"
    completed=json.loads((here.parent/"再生全完了164.json").read_text(encoding="utf-8"))
    assert completed["completed"] is True and completed["cases"] == 540
    value=json.loads(source.read_text(encoding="utf-8"))
    value["created_at"]=datetime.now().astimezone().isoformat()
    value["development_round"]=2
    value["known_after_first_round"]=True
    value["parent_manifest_sha256"]=hashlib.sha256(source.read_bytes()).hexdigest()
    value["note"]="全54場を第一巡で確認した後の追加開発。独立した未見検証ではない。"
    for scene in value["sessions"]:
        scene["previously_used"]=True
    path=here/"inputs164r2.json"
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding="utf-8")
    print("全54場を既知の追加開発として記録。原資料変更・金融再生なし。")


if __name__ == "__main__":
    main()
