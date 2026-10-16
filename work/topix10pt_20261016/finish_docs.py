"""追加した条件別診断を案内・共通知見・公開目録へ接続する。"""

import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote


def digest(path: Path) -> str:
    """
    機能: 保存物の同一性を検査するためにSHA256を計算する。
    引数: path(Path) は既存ファイルのパス。
    返り値: str。ファイル全体のSHA256の16進表現。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_links(text: str, directory: Path) -> int:
    """
    機能: 今回記述したMarkdownのローカルリンク先の存在を確認する。
    引数: text(str) は本文、directory(Path) は相対参照の基準ディレクトリ。
    返り値: int。確認したローカルリンクの数。
    """
    count = 0
    for target in re.findall(r'\]\(([^)]+)\)', text):
        if target.startswith(('https://', 'http://', '#')):
            continue
        assert (directory / unquote(target.split('#', 1)[0])).resolve().is_file(), target
        count += 1
    return count


def main() -> None:
    """
    機能: 既存文書を保全し、条件別診断の限界を共通知見と公開案内へ記録する。
    引数: なし。完成済み00118の文書・保存証跡だけを使う。
    返り値: None。HTML・公開採点・実測結果・凍結実装を変更しない。
    """
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    public = root / 'アルゴリズム調査/00118_TOPIX十ポイントの予兆と多尺度方向予測'
    manifest_path = here / '四十四条件と全三十七場の公開射影.json'
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    assert hashlib.sha256(manifest_bytes).hexdigest() == '9b2dd49f0906ad48317817ca9856d1cf903be0e6050c8982e3b1af035a5c50b0'
    for item in manifest['outputs']:
        assert digest(root / item['path']) == item['SHA256']
    extra = public / 'S03の値幅と方向の条件別診断.md'
    assert digest(extra) == '2588fd7fd6565bc1998589f0aaddfca20214d4264018a119d4ee08cc3efac88a'
    extra_text = extra.read_text(encoding='utf-8')
    assert 'close[t]−close[t−20]' in extra_text and '約20％ポイント' in extra_text
    context = here / 's03_context/S03既158予兆の四分類と因果二対照の集計.json'
    assert digest(context) == '389a755bb72407839bb106c13451720e50e6a7932d1029bda574326354fef0f4'
    assert json.loads((here / 'public_view/根の最終画像目視と独立表示検査の接続.json').read_bytes())['全合格']

    # ----------------------------------------
    # HTMLは最終表示検査のまま固定し、今回の診断は別Markdownへ案内する。
    readme = '''# TOPIX十ポイントの予兆

最初に [十ポイント方向予兆の候補と全セッション結果.html](十ポイント方向予兆の候補と全セッション結果.html) を開いてください。保存37場・44条件を検証しましたが、全期間で安定して当たる予兆はまだ確認できていません。これは方向予測のレポートです。

読む順：

1. HTML冒頭のS03。収束後の短期EMA整列と高安帯離脱で、最近10場は順10pt／逆10ptが24/40、全37場は76/158。全44条件を見た後の事後候補です。
2. 同じHTMLの正式選択3候補と全37セッション表。前21場で学習、次6場で3候補を選択し、後6場と追加4場で確認しました。正式候補の優位は維持できませんでした。全場表は44条件を切り替えられます。
3. [S03の平易な条件と到達前経路](事後に残った予兆候補S03.md)、[S03の値幅と方向の条件別診断](S03の値幅と方向の条件別診断.md)。後者の四分類でも、早期と後期の的中率の差を説明できませんでした。
4. [公開採点JSON](十ポイント予兆の公開採点.json)、[正式計画](../../work/topix10pt_20261016/試行計画.json)、[正式固定](../../work/topix10pt_20261016/正式固定.json)、[入力契約](../../work/topix10pt_20261016/入力契約の事前メタデータ.json)。

[仮説・文献参考](../../work/direction_review_20261016/research118/十ポイント方向予測の十六仮説と過去試行との差.md) は16系統の助言資料です。正式な32規則／学習12条件とは異なり、今回未実装の案も含みます。[入力の生成元と留保](../../work/topix10pt_20261016/価格現在値と気配の生成元の確認.md)、[実装と一回実測](../../work/topix10pt_20261016/run.py)、[表示生成](../../work/topix10pt_20261016/report.py)も保存しています。

観測Lastの先着であり、完全な約定テープ・実注文・手数料後利益ではありません。未決と無信号を成功に数えません。過去既知の後6場、追加4場とも完全未見の証明はありません。条件別診断は同じ158予兆の事後分類で、条件を追加した新売買手法の成績ではありません。

私有の[完成元結果](../../work/topix10pt_20261016/measurement/十ポイント予兆の結果.json)のSHA256：`b4eefa5f31e36c645fe9c54d2ed715ec074b556524cb024364bd10386121dcf2`。正式source10本・実測結果・公開採点・正式選択・最終版HTMLを変更せず、このREADMEに条件別診断へのリンクを追加しました。
'''
    knowledge = '''

<a id="00118_収束予兆の期間差は過去値幅だけでは説明できなかった"></a>

## 過去の値幅と既存方向だけでは、収束予兆の期間差を説明できなかった

**出典：** [00118_TOPIX十ポイントの予兆と多尺度方向予測](../../00118_TOPIX十ポイントの予兆と多尺度方向予測/README.md)。[四条件の診断と全内訳](../../00118_TOPIX十ポイントの予兆と多尺度方向予測/S03の値幅と方向の条件別診断.md)。

**当時判定できる条件：** 既S03方向をdとし、Aは確定20本高安幅≧10pt、Bは確定60本幅≧20pt、Cはd×(現在確定終値−20分前終値)≧2.5pt、Dはd×(公開現在値−セッション最初valid足始値)≧2.5pt。A/B/Cは必要な連続履歴がなければ未知。四条件を別々に三群分類し、AND探索は行わない。

**分母・終点：** TOPIX全37場の既158予兆を同じ±10pt終端で再同定。保存37出力を各一読し、元の各場・買売・三逆行幅・固定方向と完全照合した。順10pt対逆10ptの学習21場は35/89、後16場は41/69。未決を含む各群の既予兆数を分母とする。

**結果：** 学習側の群内順先率を固定し、後期の群比率だけに替えた算術はA38.82%、B40.09%、C39.24%、D39.33%。実際の後期59.42%との差を分類比率だけでは説明できなかった。別枠10場のCはtrue9/15・false15/25でともに60%。Aもtrue7/13よりfalse17/27が高く、単純に過去幅や既存方向を強くすればよい形ではなかった。

**対照と限界：** 同時点の非零既知方向だけで比較した別枠10場は、S03対始値比方向が24/40対19/40、20分差方向が24/39対18/39。学習側では35/88対36/88、33/84対33/84で、後期だけ良い差は残った。四分類で理由を特定できなかったことを、全テクニカルの否定にしない。これは既予兆の事後理解であり、分類を入口へ加えて再参加まで再計算した戦略の実績でも、因果効果の同定でもない。
'''
    ledger_path = root / 'アルゴリズム調査/共通/知見台帳/入口.md'
    ledger_bytes = ledger_path.read_bytes()
    assert '00118_収束予兆の期間差は過去値幅だけでは説明できなかった' not in ledger_bytes.decode('utf-8')
    links = check_links(readme, public) + check_links(extra_text, public) + check_links(knowledge, ledger_path.parent)
    archive = here / 'report_archive/条件別診断の文書追補前'
    archive.mkdir(parents=True, exist_ok=False)
    for path, raw in [(public / 'README.md', (public / 'README.md').read_bytes()), (manifest_path, manifest_bytes), (ledger_path, ledger_bytes)]:
        (archive / path.name).write_bytes(raw)
    (public / 'README.md').write_text(readme, encoding='utf-8')
    ledger_path.write_text(ledger_bytes.decode('utf-8') + knowledge, encoding='utf-8')

    # ----------------------------------------
    # 採点・選択の数値と最終HTMLを固定したまま、文書の目録だけ更新する。
    for item in manifest['outputs']:
        if Path(item['path']).name == 'README.md':
            item['SHA256'] = digest(public / 'README.md')
    manifest['outputs'].append(dict(path=extra.relative_to(root).as_posix(), SHA256=digest(extra)))
    manifest['診断文書追補'] = dict(
        前公開目録SHA256=hashlib.sha256(manifest_bytes).hexdigest(),
        前版保全=archive.relative_to(root).as_posix(),
        新診断集計=dict(path=context.relative_to(root).as_posix(), SHA256=digest(context)),
        HTML_JSON_正式選択不変=True,
        留保='既158予兆の事後理解。四分類は原因を説明できず、新売買条件の成績でも独立検証追加でもない。',
    )
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    for item in manifest['outputs']:
        assert digest(root / item['path']) == item['SHA256']
    assert digest(public / '十ポイント方向予兆の候補と全セッション結果.html') == 'bcb4ae475fc94583928dda86b60ee230c7ab42f95cf437ed53c4f103480545f0'
    assert digest(public / '十ポイント予兆の公開採点.json') == 'd2236e18866d94ce1872f3b0aca079297f3af8a98c770565727b91016471e3c2'
    proof = dict(全合格=True, ローカルリンク確認=links, HTML_JSON_正式選択不変=True,
        追記知見='00118_収束予兆の期間差は過去値幅だけでは説明できなかった',
        公開目録SHA256=digest(manifest_path), 診断MD_SHA256=digest(extra),
        原入力=0, 元結果=0, 再測定=0, 新金融=0, API=0)
    (here / '条件別診断の文書接続と共通知見追記の検査.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('条件別診断と共通知見を接続。HTML・採点・選択は不変、全リンクを確認しました。')


if __name__ == '__main__':
    main()
