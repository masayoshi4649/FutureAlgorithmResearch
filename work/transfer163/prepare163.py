"""既存Sourceの53完了場を、数量管理の部分移植用に固定する。"""
from datetime import datetime
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def read(path: Path):
    """UTF-8資料を読む。

    引数: path(Path)。返り値: dict又はlist。
    """
    return json.loads(path.read_text(encoding="utf-8-sig"))


def record(path: Path) -> dict:
    """資料の内容指紋を記録する。

    引数: path(Path)。返り値: dict。
    """
    with path.open("rb") as stream:
        digest=hashlib.file_digest(stream,"sha256").hexdigest()
    return {"path":path.relative_to(ROOT).as_posix(),"sha256":digest}


def main() -> None:
    """未来ラベルを含めない入力目録を新規保存する。

    引数: なし。返り値: None。売買再生は行わない。
    """
    source=ROOT/"work/entry160/inputs160.json"
    split_path=ROOT/"work/hedge162/inputs162.json"
    old=read(source)
    splits={s["session"]:s["split"] for s in read(split_path)["sessions"]}
    keys=("session","kind","start","us_open","force_close","end","cutoff","partial","books","candles","fingerprints")
    sessions=[]
    for scene in old["scenes"]:
        item={key:scene[key] for key in keys}
        item["split"]=splits[item["session"]]
        assert not item["partial"] and item["end"]-item["force_close"]==600
        assert all(Path(path).exists() for path in item["books"].values())
        assert all(Path(path).exists() for candles in item["candles"].values() for path in candles.values())
        sessions.append(item)
    sessions.sort(key=lambda s:s["start"])
    assert len(sessions)==53 and len({s["session"] for s in sessions})==53
    counts={key:sum(s["split"]==key for s in sessions) for key in ("train","validation","test")}
    assert counts=={"train":30,"validation":10,"test":13}
    value={"purpose":"S01/P05/D07の元Sourceを維持し、危険時の一部縮小・一度だけの復元を比較する。",
           "created_at":datetime.now().astimezone().isoformat(),"known_development":True,"financial_replays":0,
           "product":"NK225micro","max_per_side":100,"equivalent_mini_per_side":10,"point_value":10,"fees":0,
           "baseline":{"Day":"S01","NightPreUS":"P05","NightPostUS":"D07"},
           "force_close":"元Sourceの終了600秒前。米国開始前後15分の切替も元規則を維持。162の終端proxyは移植しない。",
           "sessions":sessions,"counts":counts,"sources":[record(source),record(split_path)],
           "forbidden_inputs":["先着ラベル","場末方向","元取引の未来損益","未来の最良返済時刻"]}
    with (HERE/"inputs163.json").open("x",encoding="utf-8") as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2,allow_nan=False)
    print(json.dumps({"sessions":53,"counts":counts,"new_financial_replays":0},ensure_ascii=False))


if __name__=="__main__":
    main()
