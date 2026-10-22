"""数値条件を変えず、照合台帳の構造化書式だけを修正して事前登録する。"""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys

from run_update126 import HERE, ROOT, read, save, sha
from register_update126 import MANAGER, TRIAL


def main() -> None:
    """
    機能: 初回の金融前書式拒否を残し、同じ条件を台帳指定の非空構造で登録する。
    引数: なし。
    返り値: None。金融再生、閾値変更、旧結果の再計算を行わない。
    """
    fixed = read(HERE / "固定計画.json")
    proposal = read(HERE / "試行計画.json")
    original_spec = deepcopy(fixed["specs"])
    fixed["sources"][Path(__file__).relative_to(ROOT).as_posix()] = sha(Path(__file__))
    fixed["registration_format_correction"] = "初回は説明文字列と数値設定の非適用値が台帳の非空構造要件で拒否。金融0のまま記録書式だけ修正。"
    target = HERE / "固定計画_確定書式.json"
    save(target, fixed)
    formal_spec = proposal["spec"]
    for field in ("entry", "exit", "allocation", "costs", "execution"):
        assert isinstance(formal_spec[field], str) and formal_spec[field]
        formal_spec[field] = dict(説明=formal_spec[field])
    formal_spec["management"] = dict(
        固定条件参照=dict(path=target.relative_to(ROOT).as_posix(), sha256=sha(target)),
        紙上三条件=[value["id"] for value in fixed["specs"]["paper"]],
        実気配五条件=[value["id"] for value in fixed["specs"]["bbo"]],
        選定=fixed["selection"], 条件変更=False)
    formal_spec["implementation"] = fixed["sources"]
    assert fixed["specs"] == original_spec
    plan = HERE / "試行計画_確定書式.json"
    save(plan, proposal)
    table = MANAGER.parent / "data/trials.json"
    (HERE / "確定書式登録前の試行台帳.json").write_bytes(table.read_bytes())
    assert not any(row["id"] == TRIAL for row in read(table)["trials"])
    for command, name in (("check", "事前照合_確定書式の全出力.json"), ("register", "正式登録_確定書式の全出力.json")):
        process = subprocess.run([sys.executable, "-B", "-X", "utf8", str(MANAGER), command,
            "--proposal", str(plan)], cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
        save(HERE / name, dict(終了コード=process.returncode, stdout=process.stdout, stderr=process.stderr))
        print(command, process.returncode, flush=True)
        assert process.returncode == 0, process.stderr[-1200:]


if __name__ == "__main__":
    main()
