"""初巡の損失診断を受けた主担当6対照を別試行として固定する。"""

import importlib.util
import json
import zipfile
from datetime import datetime, timedelta, timezone
from register150 import HERE, ROOT, PREVIOUS, digest, reference


def main():
    """近隣効率・浅い押戻り・実入口時の再確認を登録する。

    引数: なし。返り値: None。初巡の実装・結果を変更しない。
    """
    out = HERE / "round2"
    out.mkdir(exist_ok=True)
    receipt = out / "登録受領.json"
    assert not receipt.exists()
    configurations = json.loads((HERE / "configs_round2_150.json").read_text(encoding="utf-8-sig"))
    assert [c["id"] for c in configurations] == [f"B{i:02d}" for i in range(1, 7)]
    plan = json.loads((HERE / "再生計画150.json").read_text(encoding="utf-8"))
    plan.update(id="150_第二巡_主担当の近隣しきい値と浅い押戻り",
        name="主担当の効率近隣値・浅い押戻りと発注直前の効率再確認6条件",
        question="主担当効率の緩和に近隣で再現性があるか。浅い押戻りと組合せても良いか。準備後に効率が低下したまま入る損失を、実入口の再確認で減らせるか",
        change="B01効率.20、B02効率.30、B03効率.25と戻り.40R、B04さらに反発.125R。B05はA01に発注直前効率.25再確認、B06はB03に同再確認。追加・独立担当の閾値を緩めず主担当に限定。",
        repeat_reason="初巡A01は主担当効率.35→.25で前半−27.3万から−10.2万円へ改善したが、A16追加担当の緩和は損失を増やした。10/21のA01売り入口は効率.095に低下しても古い準備から入って−4万円。入口前の再確認と近隣値を別対照で検証する。既知結果を受けた開発であり未見検証ではない。",
        compares_to=["150_D07米国前の閾値緩和と開始前リセット"])
    plan["spec"]["entry"] = {"method": "前半主担当だけ変更。効率再確認を加えるB05/B06は、発注直前の当時公開済み効率が閾値未満ならその行では新規しない。準備の保持/解除は元どおり。", "configurations": [dict(c, owners=c.get("owners") or "全担当") for c in configurations]}
    plan["spec"]["management"] = {"method": "全条件で追加/独立担当と通常の出口・枚数・再参加はA00へ固定。US15分前全返済、指標保持と新Portfolioの後半はS04と同一。準備時の効率と入口時の効率を分ける。"}
    plan["spec"]["exit"] = {"method": "D07の元出口を固定。US15分前に全返済判断し次正常原行で約定、未解消なら後半開始禁止。途中末尾精算なし。"}
    plan["spec"]["allocation"] = {"product": "NK225mini", "cap": 10, "point_value": 100, "method": "主担当5・追加3・独立2、追加初回2枚。前半補完Z04なし。"}
    plan["spec"]["data"]["development_result"] = reference(HERE / "first_report150.json")
    engine = HERE / "engine_go_round2"
    sources = sorted(p for p in engine.rglob("*") if p.is_file() and (p.suffix in (".go", ".toml") or p.name in ("go.mod", "go.sum")))
    sources += [HERE / "configs_round2_150.json", HERE / "engine追加仕様150.md"]
    frozen = out / "再生前実装.zip"
    with zipfile.ZipFile(frozen, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sources:
            archive.write(path, path.relative_to(HERE).as_posix())
    plan["spec"]["implementation"] = {frozen.relative_to(ROOT).as_posix(): digest(frozen)}
    plan_path = out / "計画.json"
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    # ----------------------------------------
    manager_path = ROOT / "アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/manage.py"
    spec = importlib.util.spec_from_file_location("研究150第二巡の管理", manager_path)
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    check = manager.analyzer().analyze(plan, [])
    assert check["proposal_complete"], check
    print("第二巡6条件を凍結。既存試行と照合・登録します。", flush=True)
    record = manager.store_trial(plan)
    (out / "照合.json").write_text(json.dumps(record["preflight"], ensure_ascii=False, indent=2), encoding="utf-8")
    receipt.write_text(json.dumps({"id": plan["id"], "registered": True, "returncode": 0,
        "created_at": datetime.now(timezone(timedelta(hours=9))).isoformat(), "plan": reference(plan_path),
        "implementation": reference(frozen), "inputs": reference(PREVIOUS / "data/原資料一覧149.json"),
        "previous_result": reference(HERE / "first_report150.json"), "sources": [reference(p) for p in sources]}, ensure_ascii=False, indent=2), encoding="utf-8")
    print("第二巡登録完了。指紋確認後に再生できます。", flush=True)


if __name__ == "__main__":
    main()
