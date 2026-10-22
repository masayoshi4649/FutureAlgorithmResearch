"""00131の検証済み草稿を、既存法則と重複しない位置へ追記する。"""

import hashlib
import json
from pathlib import Path
import re
import time
from urllib.parse import unquote

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
COMMON = ROOT / "アルゴリズム調査/共通/知見台帳"
DRAFTS = WORK / "knowledge_drafts"

PLACEMENT = {
    "00131_低効率は未来の回帰を意味しない": "五分の往復は現在の底打ちや天井を証明しない",
    "00131_価格時計の鮮度と現物休日を分ける": "価格時刻の停滞を板受信の中断とみなせない",
    "00131_準備時の根拠は発注時にも残るとは限らない": "公開時の根拠を後へ固定せず現在の反応を取り直す",
    "00131_事後最大順行と保護起動の設計循環": "起動幅未満の利益返しは多いが、全ての負けを出口だけで救えない",
    "00131_中値の値幅と実気配の損益を分ける": "小幅停止の回転では気配差が値動きの利益を上回る",
    "00131_片市場だけの逆行を単純撤退に使わない": "相手との不一致だけで降りると利益を逃す",
}

ASYNC = """
<a id="00131_片市場だけの逆行を単純撤退に使わない"></a>

## 相手が進んで自分だけ逆行する状態にも、回復する勝ちが含まれた

**出典：** [00131_時間帯と値動き状態を切り替える全場参加](../../00131_時間帯と値動き状態を切り替える全場参加/README.md)。比較元は[00129_チャートと板からの失敗機構再検証](../../00129_チャートと板からの失敗機構再検証/README.md)の日中DV07／DV05。

**当時条件と終点：** 実新規時の自己・相手価格を基準に「自市場が0.25初期ATR以上逆行し、相手市場は0.25初期ATR以上順行」を監視する。元の最終返済判断までを対象とし、未知・不正気配・15秒超の原行間隔では持続時計をリセットした。判定は価格時計上のもので、実受信時刻による同時性の証明ではない。

| 商品と条件 | 該当する旧親／全旧親 | 該当群の旧最終勝ち／負け | 旧最終収支合計 |
| --- | ---: | ---: | ---: |
| TOPIX・瞬間成立 | 8／44 | 3／5 | ＋32,160円 |
| TOPIX・60秒持続 | 1／44 | 0／1 | −42,918円 |
| TOPIX・120秒持続 | 1／44 | 0／1 | −42,918円 |
| 日経・瞬間成立 | 11／50 | 7／4 | ＋100,080円 |
| 日経・60秒持続 | 2／50 | 1／1 | ＋23,560円 |
| 日経・120秒持続 | 0／50 | 0／0 | 0円 |

**拾う失敗と消す勝ち：** TOPIX10月13日09:51:25売り4,100.5→12:29:12返済4,109は−42,918円。11:59:55には自己0.355ATR逆行・相手0.800ATR順行が60秒続いており、両市場の逆行を要求する既存撤退では拾えない。一方、日経10月19日10:10:36買い64,620も、10:56:32には自己0.302ATR逆行・相手0.423ATR順行が60秒続いたが、15:35の64,990返済まで保持した旧結果は＋36,780円だった。

**判断と限界：** 表は全22日中・94親の保存経路の分類であり、途中撤退を実行した新運転の収支でも、失敗を予測できた率でもない。TOPIXの120秒条件は1親だけで一般則の根拠に不足する。短期の非同期を単純に失敗扱いする改修は採用しなかった。日中の残存赤字の解消は未確認。

**根拠：** [全94親の時刻と分類](../../../work/regime131_20261020/day_diagnosis/旧日中の自己失敗と相手進行の全94親分類.json)、[具体経路と不採用理由](../../../work/regime131_20261020/day_diagnosis/旧核の片市場失敗を撤退条件にしなかった理由.md)。
"""


def sha(value: bytes) -> str:
    """
    機能: 内容の指紋を返す。
    引数: value(bytes)は対象内容。
    返り値: strはSHA256。
    """
    return hashlib.sha256(value).hexdigest()


def add_block(text: str, block: str) -> tuple[str, dict]:
    """
    機能: 同じ法則の中へ追加測定を追記し、固有法則だけ末尾へ置く。
    引数: text(str)は既存本文、block(str)は草稿本文。
    返り値: tuple[str,dict]は変更後本文と追記記録。
    """
    anchor = re.search(r'<a id="([^"]+)"></a>', block).group(1)
    assert anchor not in text, f"重複アンカー: {anchor}"
    eol = "\r\n" if "\r\n" in text else "\n"
    heading = PLACEMENT.get(anchor)
    if heading:
        marker = "## " + heading
        start = text.index(marker)
        next_heading = re.search(r"(?m)^## ", text[start + len(marker):])
        end = start + len(marker) + next_heading.start() if next_heading else len(text)
        between = text[start + len(marker):end]
        next_anchor = re.search(r'(?m)^<a id=', between)
        if next_anchor:
            end = start + len(marker) + next_anchor.start()
        block = block.replace("\n## ", "\n### 00131の追加検証：", 1)
    else:
        end = len(text)
    addition = eol * 2 + block.strip().replace("\n", eol) + eol * 2
    updated = text[:end] + addition + text[end:]
    assert updated[:end] + updated[end + len(addition):] == text
    return updated, dict(anchor=anchor, existing_law=heading, addition=addition)


def check_links(path: Path, text: str) -> list[dict]:
    """
    機能: Markdownの相対出典リンクが実在するかを調べる。
    引数: path(Path)は追記先、text(str)は対象本文。
    返り値: list[dict]は内部リンクの検査結果。外部URLは取得しない。
    """
    results = []
    for raw in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
        target = raw.strip().strip("<>")
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target) or target.startswith("#"):
            continue
        relative, _, fragment = unquote(target).partition("#")
        file = (path.parent / relative).resolve()
        results.append(dict(link=raw, path=str(file.relative_to(ROOT)),
            exists=file.is_file(), fragment=fragment))
    return results


def main() -> None:
    """
    機能: 7草稿と非同期反例を共通4本文へ統合し、リンクと変更範囲を記録する。
    引数: なし。
    返り値: None。金融源・登録済み資料・案内ファイルは変更しない。
    """
    records = []
    protected = [COMMON / "README.md", ROOT / "README.md",
        ROOT / "アルゴリズム調査/index.html",
        ROOT / "アルゴリズム調査/00131_時間帯と値動き状態を切り替える全場参加/README.md"]
    before_protected = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in protected}
    for name in ("入口.md", "継続.md", "出口.md", "売買の工夫.md"):
        draft = DRAFTS / name
        source = draft.read_bytes()
        body = re.sub(r"<!--.*?-->", "", source.decode("utf-8"), flags=re.S).strip()
        chunks = ["<a id=" + b for b in body.split("<a id=")[1:]]
        if name == "継続.md":
            chunks.append(ASYNC.strip())
        target = COMMON / name
        old = target.read_bytes()
        text = old.decode("utf-8")
        additions = []
        for block in chunks:
            text, addition = add_block(text, block)
            links = check_links(target, addition["addition"])
            assert links and all(x["exists"] for x in links), links
            addition["links"] = links
            additions.append(addition)
        old_ids = re.findall(r'<a id="([^"]+)"', old.decode("utf-8"))
        new_ids = re.findall(r'<a id="([^"]+)"', text)
        assert len(new_ids) == len(set(new_ids)), target
        assert set(old_ids).issubset(new_ids)
        new_bytes = text.encode("utf-8")
        target.write_bytes(new_bytes)
        all_links = check_links(target, text)
        records.append(dict(path=str(target.relative_to(ROOT)), before_sha256=sha(old),
            after_sha256=sha(new_bytes), draft_sha256=sha(source),
            additions=[{k: v for k, v in item.items() if k != "addition"} for item in additions],
            all_relative_links=len(all_links),
            existing_missing_links=[x for x in all_links if not x["exists"]],
            original_content_preserved=True))
    unchanged = {str(p.relative_to(ROOT)): sha(p.read_bytes()) == before_protected[str(p.relative_to(ROOT))]
        for p in protected}
    assert all(unchanged.values())
    proof = dict(passed=True, financial_replays=0, added_laws=8, draft_laws=7,
        records=records, protected_files_unchanged=unchanged,
        policy="既存法則内の追補6項目・独立項目2件。事後分類と新運転を区別。案内・金融源・登録資料は変更しない。",
        script_sha256=sha(Path(__file__).read_bytes()))
    output = HERE / f"共通知見統合と内部リンク確認_{time.time_ns()}.json"
    output.write_text(json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.as_posix(), flush=True)
    for record in records:
        print(record["path"], len(record["additions"]), "追記",
            record["all_relative_links"], "内部リンク",
            len(record["existing_missing_links"]), "既存不明リンク", flush=True)


if __name__ == "__main__":
    main()
