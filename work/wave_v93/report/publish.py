"""全口座・配分・説明・表示を照合して00089の最新案内を公開する。"""

import hashlib
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
RESEARCH = ROOT / 'アルゴリズム調査'
FOLDER = '00089_予定リスクと中心利確及び失敗後再参加'
OUT = RESEARCH / FOLDER
MAIN = OUT / '予定リスクと再参加の説明と全セッション損益.html'


def read(path: Path) -> dict:
    """
    機能: 保存済みの日本語JSON資料を読む。
    引数: path(Path)。資料の位置。
    返り値: dict。読み込んだ資料。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: ファイルの内容を指紋で照合する。
    引数: path(Path)。対象の位置。
    返り値: str。SHA256の16進文字列。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def check_hashes(values: dict) -> None:
    """
    機能: 資料が参照した内容と現在の内容が同じか検査する。
    引数: values(dict[str,str])。ルート相対位置と指紋。
    返り値: None。不一致の場合はAssertionError。
    """
    for relative, expected in values.items():
        assert sha(ROOT / relative) == expected, relative


def main() -> None:
    """
    機能: 凍結・会計・源別独立性・立会内清算・画面の合格後に案内を更新する。
    引数: なし。
    返り値: None。旧成果及び売買会計は変更しない。
    """
    fixed_path = WORK / '事前固定.json'
    fixed = read(fixed_path)
    assert fixed['全31既知'] and len(fixed['条件']) == 16 and fixed['主'] == 'C11'
    assert fixed['新しい未見確認場数'] == 0
    assert sha(fixed_path) == '0be0e591484b73796b44cd96a43ab1a098ec784936cca73dede26648ef1732a3'
    assert len(fixed['SHA256']) == 105
    check_hashes(fixed['SHA256'])
    account_path = WORK / 'analysis/比較結果.json'
    assert sha(account_path) == 'eec4d357703e4d74c0d626bd413ff944bb4ad7bf9c0968543c706df2f3eb38b1'
    account = read(account_path)
    assert account['全合格'] and account['条件数'] == 16 and account['全31既知']
    assert account['新未見確認場数'] == 0
    assert sum(len(value['rows']) for value in account['results'].values()) == 992
    assert not account['both80'] and not account['両商品で全場黒字']
    audit_path = WORK / 'audit/全16条件全31場の予定距離と失敗再参加及び全原板清算会計の独立検算.json'
    assert sha(audit_path) == 'b043b544ad7cec015ff3677ee076ff1b81c18a2168a7494175b6ebf982196ba1'
    audit = read(audit_path)
    assert audit['全合格'] and audit['検査件数']['口座'] == 992
    assert audit['検査件数']['商品期間集計'] == 256
    assert audit['検査件数']['注文'] == 3796
    assert audit['検査件数']['決済親'] == 1898
    check_hashes(audit['SHA256'])
    projection_path = WORK / 'audit/独立配分の同数量単独と全31源別注文及び全原板時価の完全一致.json'
    projection = read(projection_path)
    assert projection['全合格'] and len(projection['検査']) == 124
    assert all(row['全原板源時価一致'] for row in projection['検査'])
    check_hashes(projection['SHA256'])
    boundary_path = WORK / 'audit/全992口座の立会内約定と運用区切りの独立補足.json'
    boundary = read(boundary_path)
    assert boundary['全合格'] and boundary['口座数'] == 992
    assert boundary['全注文数'] == 3796 and boundary['運用区切り以降約定'] == 21
    assert boundary['継続取引末以降約定'] == boundary['立会末以降約定'] == 0
    assert boundary['立会開始以前約定'] == 0
    check_hashes(boundary['SHA256'])
    selection_path = WORK / 'audit/後15正式損益未参照の前16参考代表の注文会計による独立再選定.json'
    selection = read(selection_path)
    assert selection['全合格'] and selection['参考代表'] == 'S00'
    assert selection['選定に後15正式損益使用'] == selection['当段階後15損益閲覧'] == 0
    check_hashes(selection['SHA256'])
    supplement_path = WORK / 'analysis/説明補足.json'
    supplement = read(supplement_path)
    assert sha(supplement_path) == 'bf161a63bf05717355e5782a0b5602a11aecabd8623b5f6c0c9f847e5a60df70'
    assert supplement['根集計SHA256'] == sha(account_path)
    assert len(supplement['根拠SHA256']) == 7 and supplement['売買及び会計の変更'] == 0
    check_hashes(supplement['根拠SHA256'])
    display = read(HERE / '表示の独立検査.json')
    generated = read(HERE / '生成結果.json')
    assert display['全合格'] and display['目視確認']
    assert display['保存会計口座数'] == 992
    assert display['HTML_SHA256'] == generated['HTML_SHA256'] == sha(MAIN)
    assert len(display['画面']) == 5 and all(view['全合格'] for view in display['画面'])
    check_hashes(generated['使用資料SHA256'])
    root_visual = read(HERE / '根担当の五画面目視.json')
    assert root_visual['全合格'] and root_visual['HTML_SHA256'] == sha(MAIN)
    assert len(root_visual['確認画像SHA256']) == 5
    check_hashes(root_visual['確認画像SHA256'])
    # ----------------------------------------
    # 旧作業は保持し、新しい公開会計と読み順だけを加える。
    old_folders = [RESEARCH / '00088_回復確認と中心帰還による再参加',
                   RESEARCH / '00087_待機基準の保持と二市場反対による返済']
    prior = {str(path.relative_to(ROOT)): sha(path)
             for folder in old_folders for path in folder.rglob('*') if path.is_file()}
    assert sha(old_folders[0] / '回復確認と再参加の説明と全セッション損益.html') == '7aebc0f9b398b1937dfaf7e9897cf787130801a3a77ce2591bf7b8edfafbbfd1'
    assert sha(old_folders[1] / '待機基準と反対返済の改善と全セッション損益.html') == '6a512241c3672244b63be56d9835ab33b58bfda0ce73a2f26f4caa6e865097b9'
    shutil.copyfile(account_path, OUT / '公開会計.json')
    assert sha(OUT / '公開会計.json') == sha(account_path)
    guide = '''# 00089 予定リスクと中心利確及び失敗後再参加

最初に **[予定リスクと再参加の説明と全セッション損益.html](予定リスクと再参加の説明と全セッション損益.html)** を開いてください。16条件を切り替え、TOPIXミニ片方向10枚・日経マイクロ片方向20枚以内の全31場の利益・損失・収支・決済枚数を確認できます。

読む順序は結論→手法比較→全セッション表です。具体的な入口・出口・原因は折り畳みにあります。[公開会計](公開会計.json)は変更していない正式集計です。

今回は「予定利幅と損切り距離を比べる」「古い中心で利確する」「損切り後は両市場の中心帰還を待つ」「追従8：反発2を同時運転する」を分けて検証しました。結果を見る前に固定した主C11はTOPIX−219,196円・日経−18,640円で不採用。活動は11場・6場で、無取引20場・25場を勝ちには含めません。両銘柄で金額利益80%を達成した条件は0です。

損失の原因には二つありました。中心へ戻る前に狭い極値停止に掛かることと、現在の長い計算窓が不明でも古い往復判断で新規することです。C11ではTOPIX8/11親・日経6/6親が後で場内に中心へ戻りましたが、返済までに中心へ到達したのは0親・1親でした。現在不明を「往復継続」「中立」「強い一方向」とは断定できません。

同じ実新規を旧1幅停止だけで清算した事後の単親診断はTOPIX−49,196円・日経+23,360円でした。この診断は以後の新規・枚数枠・再参加を再生していないため、新アルゴリズムの損益ではありません。広い停止だけで両銘柄が安定するとは確認していません。

前16場で固定した参考S00はTOPIX+440,556円・日経+186,208円。金額利益割合は55.81%・56.49%、取引のあった29場中黒字17場ずつでした。比較上の参考であり、全日安定や目標到達の解ではありません。

固定配分S03はTOPIX+396,730円・日経+182,480円。追従S00へ反発を加えると−43,826円・−3,728円、最大下落は+20,664円・差0でした。同じ上限の追従10枚・20枚単独より最大下落は小さいものの、追従枚数を減らした効果と分ける必要があります。追従の赤字を合計黒字へ救った場は両銘柄とも0でした。

全31場は既知データです。前16・後15は比較の分割であり、未知データの成功ではありません。判断後の次有効ラージ気配による代理約定、手数料込み、全玉の気配清算で検算しました。追加5秒劣化は含めていません。全3,796注文は連続立会終了前ですが、データ途切れ後の返済21件は保守的な運用区切りを越えました。区切り内約定を保証する結果ではありません。[JPXの立会時間](https://www.jpx.co.jp/derivatives/rules/trading-hours/)も参照しています。実ミニ・マイクロ板での全枚数約定、待ち順位、真の受信時計は未検証です。

再現資料：

- [事前固定](../../work/wave_v93/事前固定.json)・[実行](../../work/wave_v93/research.py)・[前16場の参考固定](../../work/wave_v93/前16参考代表.json)。
- [全992口座の独立会計](../../work/wave_v93/audit/全16条件全31場の予定距離と失敗再参加及び全原板清算会計の独立検算.json)・[配分源別の完全一致](../../work/wave_v93/audit/独立配分の同数量単独と全31源別注文及び全原板時価の完全一致.json)・[立会内清算](../../work/wave_v93/audit/全992口座の立会内約定と運用区切りの独立補足.json)。
- [同一判断と再参加の分解](../../work/wave_v93/review/全16条件全31の独立親会計と同一判断及び再参加経路分解.json)・[最悪3場と原板](../../work/wave_v93/review/主と前16参考及び配分の最悪3場と原板及び敵対的結論.json)。
- [中心未達と早い停止の事後診断](../../work/wave_v93/review/中心未達と早い極値停止を分けた全受理親の事後反証.json)・[長い窓不明と現在板正常の切り分け](../../work/wave_v93/review/入口時の長い窓不明と現在板正常を分けた原因旗.json)・[敵対的結論](../../work/wave_v93/review/全16部品と中心停止及び配分の敵対的結論.json)。

次に、価格の正常性と深い板・数量の正常性を分けて判定できるか調べます。これは未実装・未検証です。現在API取得0回・実注文0回。00088・00087を保持し、目標への調査を継続しています。
'''
    (OUT / 'README.md').write_text(guide, encoding='utf-8')
    # ----------------------------------------
    # 最新導線は新作業へ向け、旧導線も引き続き残す。
    root_readme = ROOT / 'README.md'
    source = root_readme.read_text(encoding='utf-8')
    new_line = (f'最新の調査は **[00089：予定リスクと中心利確及び失敗後再参加]'
                f'(アルゴリズム調査/{FOLDER}/{MAIN.name})** です。16条件・全31既知場を比較。'
                f'[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。'
                '両銘柄の安定収益と利益80%への調査は継続中です。')
    source, count = re.subn(r'^最新の調査は .*$', lambda match: new_line, source, count=1, flags=re.M)
    assert count == 1
    root_readme.write_text(source, encoding='utf-8')
    research_readme = RESEARCH / 'README.md'
    source = research_readme.read_text(encoding='utf-8')
    if '<!--00089案内開始-->' not in source:
        block = (f'<!--00089案内開始-->\n**最新は00089の[{MAIN.name}]({FOLDER}/{MAIN.name})。'
                 '予定距離・中心利確・失敗後再参加・固定配分の16条件、全31既知場。**\n\n'
                 f'[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。'
                 '両銘柄共通の安定性と利益80%は未達です。\n<!--00089案内終了-->\n\n')
        assert '<!--00088案内開始-->' in source
        source = source.replace('**最新は00088の', '**00088の', 1)
        source = source.replace('<!--00088案内開始-->', block + '<!--00088案内開始-->', 1)
    research_readme.write_text(source, encoding='utf-8')
    index = RESEARCH / 'index.html'
    source = index.read_text(encoding='utf-8')
    if '<!--00089開始-->' not in source:
        source = source.replace('class="task latest"', 'class="task"')
        source = source.replace(' <span class="badge">最新</span>', '')
        article = (f'<!--00089開始--><article class="task latest"><div class="number">作業00089 '
                   '<span class="badge">最新</span></div><h2>予定リスクと中心利確及び失敗後再参加</h2>'
                   '<p>予定距離・中心利確・失敗後再参加・固定配分の16条件を全31既知場で比較。'
                   '狭い停止と現在判定不明を区別し、全場損益を掲載。利益80%は未達です。</p>'
                   f'<a class="button" href="{FOLDER}/{MAIN.name}">説明と全場損益</a> '
                   f'<a href="{FOLDER}/README.md">読む順序</a></article><!--00089終了-->\n')
        assert '<!--00088開始-->' in source
        source = source.replace('<!--00088開始-->', article + '<!--00088開始-->', 1)
    source, count = re.subn(r'<p class="lead">最新0008[89]：.*?</p>',
                            '<p class="lead">最新00089：予定距離と再参加の16条件。全31既知場の損益、配分と損失原因を掲載します。</p>',
                            source, count=1)
    assert count == 1
    index.write_text(source, encoding='utf-8')
    assert prior == {str(path.relative_to(ROOT)): sha(path)
                     for folder in old_folders for path in folder.rglob('*') if path.is_file()}
    outputs = [MAIN, OUT / 'README.md', OUT / '公開会計.json', root_readme, research_readme, index]
    proof = dict(全合格=True, HTML_SHA256=sha(MAIN), 全口座=992, 商品期間集計=256,
                 全31既知=True, 新未見確認場数=0, 根担当五画面目視確認=True,
                 旧00088と00087全成果不変=True, 旧成果指紋=prior,
                 公開指紋={str(path.relative_to(ROOT)): sha(path) for path in outputs},
                 監査SHA256=sha(audit_path), 源別独立SHA256=sha(projection_path),
                 立会内清算SHA256=sha(boundary_path), 説明補足SHA256=sha(supplement_path),
                 条件及び参考の差替え=False, API取得=0, 実注文=0)
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key != '旧成果指紋'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
