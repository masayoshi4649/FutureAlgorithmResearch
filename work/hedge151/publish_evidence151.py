"""研究151の読者向け根拠を公開領域へ配置する。"""

import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / "アルゴリズム調査/00151_損切りなし両建てと利益玉トレーリング"


def main():
    """完成した診断・監査・図をコピーし、文書リンクの実在を確認する。

    引数: なし。返り値: None。元会計・売買実装・公開主READMEは変更しない。
    """
    target = PUBLIC / "根拠"
    target.mkdir(parents=True, exist_ok=True)
    copies = {
        "engine仕様151.md": "engine仕様151.md",
        "engine_利益回転と残在庫の具体診断151.md": "具体売買と利益回転の診断.md",
        "engine_保存会計の具体診断151.json": "engine_保存会計の具体診断151.json",
        "P05_同一入口の出口帰属151.json": "P05_同一入口の出口帰属151.json",
        "再参加_損失と改善151.png": "再参加_損失と改善151.png",
        "同一入口_利益開始幅の比較151.png": "同一入口_利益開始幅の比較151.png",
        "audit/結果監査.md": "結果監査.md",
        "audit/最終会計の独立確認.json": "最終会計の独立確認.json",
        "audit/P05の改善を同じ入口で独立確認.json": "P05の改善を同じ入口で独立確認.json",
        "audit/金融前の独立実装監査.md": "金融前の独立実装監査.md",
        "audit/金融前の独立実装監査.json": "金融前の独立実装監査.json",
        "audit/人工監査の最終元指紋.json": "人工監査の最終元指紋.json",
        "audit/独立人工試験_test.go": "独立人工試験_test.go",
        "audit/既試行との差分と損益の恒等式.md": "既試行との差分と損益の恒等式.md",
        "audit/試行前の反証と人工試験案.md": "試行前の反証と人工試験案.md",
        "audit/新規通知の網羅性と採番の確認.md": "新規通知の網羅性と採番の確認.md",
        "audit/保存通知と判断添字の独立照合.json": "保存通知と判断添字の独立照合.json",
        "xlsx_checks/保存xlsxの独立検算.json": "保存xlsxの独立検算.json",
        "xlsx_checks/Excel計算との照合.json": "Excel計算との照合.json",
    }
    for source, destination in copies.items():
        shutil.copy2(HERE / source, target / destination)
    # ----------------------------------------
    # 実行源はworkの正本へ案内し、公開コピーを別の実行器と誤解させない。
    for path in target.glob("*.md"):
        content = path.read_text(encoding="utf-8")
        content = re.sub(r"\]\(([^()]+\.py)\)", lambda m: "](../../../work/hedge151/audit/" + Path(m[1]).name + ")", content)
        path.write_text(content, encoding="utf-8")
    links = []
    for path in PUBLIC.rglob("*.md"):
        for raw in re.findall(r"\]\(([^)]+)\)", path.read_text(encoding="utf-8")):
            if raw.startswith(("http:", "https:", "#")):
                continue
            resolved = (path.parent / unquote(raw.split("#")[0].strip("<>"))).resolve()
            assert resolved.exists(), (str(path), raw)
            links.append({"document": str(path.relative_to(ROOT)), "link": raw})
    outputs = [{"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()} for path in PUBLIC.rglob("*") if path.is_file()]
    result = {"passed": True, "links_checked": len(links), "links": links, "outputs": outputs,
              "figures_visually_checked": ["再参加_損失と改善151.png", "同一入口_利益開始幅の比較151.png"],
              "workbook_root_visual_checks": ["比較_左.jpg", "日経_P05_左.jpg", "日経_N03_右.jpg"]}
    (HERE / "公開資料照合151.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"passed": True, "links_checked": len(links), "files": len(outputs)}))


if __name__ == "__main__":
    main()
