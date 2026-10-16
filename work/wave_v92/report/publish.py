"""独立会計と補足監査の完了後に00088の案内を更新する。"""

import hashlib
import json
from pathlib import Path
import re
import shutil

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]
RESEARCH = ROOT / 'アルゴリズム調査'
FOLDER = '00088_回復確認と中心帰還による再参加'
OUT = RESEARCH / FOLDER
MAIN = OUT / '回復確認と再参加の説明と全セッション損益.html'


def read(path: Path) -> dict:
    """
    機能: 保存された日本語の監査資料を読む。
    引数: path(Path)。読み込むJSONの位置。
    返り値: dict。保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path: Path) -> str:
    """
    機能: 資料の内容をSHA256で照合できるようにする。
    引数: path(Path)。対象ファイル。
    返り値: str。SHA256の16進文字列。
    """
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def check_hashes(values: dict) -> None:
    """
    機能: 監査が対象にしたファイルと現在のファイルの一致を確認する。
    引数: values(dict[str,str])。ルートからの相対位置と指紋。
    返り値: None。不一致の場合はAssertionError。
    """
    for relative, expected in values.items():
        assert sha(ROOT / relative) == expected, relative


def main() -> None:
    """
    機能: 全口座監査・凍結・目視の成功後、最新の案内だけを更新する。
    引数: なし。
    返り値: None。生データ、売買、旧作業の内容は変更しない。
    """
    fixed_path = WORK / '事前固定.json'
    fixed = read(fixed_path)
    assert fixed['全31既知'] and len(fixed['条件']) == 36
    assert fixed['主'] == 'R_B25_C_ESTOP'
    assert sha(fixed_path) == '3c08910d3f3b4ec83b90f31dd4a32a6d51aba9054a75ae9d7e4ac1dacac77cc5'
    check_hashes(fixed['SHA256'])
    account_path = WORK / 'analysis/比較結果.json'
    account = read(account_path)
    assert account['全合格'] and account['条件数'] == 36 and account['全31既知']
    assert account['新未見確認場数'] == 0
    assert sum(len(value['rows']) for value in account['results'].values()) == 2232
    assert not account['both80'] and not account['両商品で全場黒字']
    audit_path = WORK / 'audit/全36条件全31場の回復と中心帰還及び全原板清算会計の独立検算.json'
    audit = read(audit_path)
    assert audit['全合格'] and audit['検査件数']['口座'] == 2232
    assert audit['検査件数']['商品期間集計'] == 576
    assert audit['独立監査の補足']['売買実装変更'] == 0
    check_hashes(audit['SHA256'])
    cancel_proof_path = WORK / 'audit/中心解除取消の原入力と最初成立及び先約定の補足監査.json'
    cancel_proof = read(cancel_proof_path)
    assert cancel_proof['全合格'] and len(cancel_proof['人工正例']) == 8
    assert sum(cancel_proof['人工故障を拒絶'].values()) == 36
    assert set(cancel_proof['新競合枝の未来不変'].values()) == {24}
    check_hashes(cancel_proof['SHA256'])
    reviewed_path = WORK / 'review/全36と主の反証及び部品追加価値の敵対的結論.json'
    reviewed = read(reviewed_path)
    assert reviewed['全合格'] and reviewed['口座'] == 2232
    assert reviewed['根集計SHA256'] == sha(account_path)
    mixing_path = WORK / 'review/固定配分の同時損失と源別相関.json'
    mixing = read(mixing_path)
    assert mixing['全合格'] and mixing['根集計SHA256'] == sha(account_path)
    assert len(mixing['行']) == 4 and mixing['新しい売買計算'] == 0
    display = read(HERE / '表示の独立検査.json')
    generated = read(HERE / '生成結果.json')
    assert display['全合格'] and display['目視確認']
    assert display['保存会計口座数'] == 2232
    assert display['HTML_SHA256'] == generated['HTML_SHA256'] == sha(MAIN)
    assert len(display['画面']) == 5 and all(view['全合格'] for view in display['画面'])
    check_hashes(generated['使用資料SHA256'])
    supplement = read(WORK / 'analysis/説明補足.json')
    assert supplement['根集計SHA256'] == sha(account_path)
    check_hashes(supplement['根拠SHA256'])
    # ----------------------------------------
    # 過去の成果と、最新の案内の変更を分けて照合する。
    old_folders = [RESEARCH / '00087_待機基準の保持と二市場反対による返済',
                   RESEARCH / '00086_二市場の状態で追従と指値反発を配分']
    prior = {str(path.relative_to(ROOT)): sha(path)
             for folder in old_folders for path in folder.rglob('*') if path.is_file()}
    old_main = old_folders[0] / '待機基準と反対返済の改善と全セッション損益.html'
    assert sha(old_main) == '6a512241c3672244b63be56d9835ab33b58bfda0ce73a2f26f4caa6e865097b9'
    shutil.copyfile(account_path, OUT / '公開会計.json')
    assert sha(OUT / '公開会計.json') == sha(account_path)
    guide = '''# 00088 回復確認と中心帰還による再参加

最初に **[回復確認と再参加の説明と全セッション損益.html](回復確認と再参加の説明と全セッション損益.html)** を開いてください。36条件を切り替えて、TOPIXミニ片方向10枚・日経マイクロ片方向20枚以内の全31場の利益・損失・収支・決済枚数を確認できます。

読む順序は結論→比較→全セッション表です。詳しい条件・原因は折り畳みを開いてください。[公開会計](公開会計.json)が表の原数値です。

今回は「下がっただけで買わず、両市場の回復を確認して入る」「利確後に中心へ戻るまで同じ小波へ入り直さない」を分けて検証しました。極値を割ったら返済する理論主はTOPIX−1,393,584円・日経−56,600円で不採用。損切りを早めても勝ちを失い、追加の入り直しが損失を増やしました。

回復確認は同じ成行の確認なしに対し、日経で729,680円改善しましたが、TOPIXでは14,148円悪化。両銘柄に共通する優位とは確認できませんでした。

前16場で固定した参考R_B25_C_W15はTOPIX+1,432,380円・日経+44,320円。日経は後15場で−65,400円、最大利益日除外で−97,920円のため、共通の安定候補とは評価していません。金額利益80%を両銘柄で達成した条件は0でした。

追従8：回復反発2を同時運転したM_RB25_CはTOPIX+185,276円・日経+230,392円。追従8単独へ加えるとTOPIXは255,280円悪化、日経は44,184円改善し、両銘柄で最大下落が増えました。同上限の追従10単独との比較では最大下落は両銘柄で減りましたが、収支も減りました。配分の効果と、追加した反発自体の有用性を区別しています。

具体例：10月9日デイの日経10:04:51に68,520で買い。観測安値68,445の1呼値下を損切り線にした結果、損失距離85ptが従来の70ptより広くなりました。両方の回復を待つ間に戻り過ぎるため、「極値停止は必ず狭い」という前提は誤りです。

全31場は既知データです。前16・後15は条件比較の分割で、未知データでの成功と扱いません。ラージ板の判断後の次有効気配を使った代理約定、手数料込み、全保有玉を清算気配で評価し、全場を場内で返済しました。追加5秒劣化は含めていません。実ミニ／マイクロ板、全数量の約定・待ち順位、真の受信時計は未検証です。

再現・検証資料：

- [事前固定](../../work/wave_v92/事前固定.json)・[実行](../../work/wave_v92/research.py)・[前16場の参考固定](../../work/wave_v92/前16参考代表.json)。
- [全2,232口座の独立検算](../../work/wave_v92/audit/全36条件全31場の回復と中心帰還及び全原板清算会計の独立検算.json)。既存の中心解除取消に対する監査の許可条件漏れは、凍結コードを変えず独立の補足で検査しています。
- [同一新規と再参加の分解](../../work/wave_v92/review/全条件全31の独立親会計と同一新規及び再参加経路分解.json)・[赤字上位3場の原板時刻](../../work/wave_v92/review/主と事前参考の赤字上位3場及び回復中心の具体原板.json)。
- [敵対的結論](../../work/wave_v92/review/全36と主の反証及び部品追加価値の敵対的結論.json)・[結果後の次段仮説](../../work/wave_v92/review/結果後の次段仮説と今回変更しない範囲.json)。次段は未検証で、今回の条件を後から変えていません。
- [固定配分の相関と同時損失](../../work/wave_v92/review/固定配分の同時損失と源別相関.json)。低相関と赤字回避は別に評価しています。

現在API取得0回・実注文0回。00087・00086を保持し、目標への調査は継続中です。
'''
    (OUT / 'README.md').write_text(guide, encoding='utf-8')
    # ----------------------------------------
    # 新しい案内を登録し、以前の作業へのリンクを残す。
    root_readme = ROOT / 'README.md'
    source = root_readme.read_text(encoding='utf-8')
    new_line = (f'最新の調査は **[00088：回復確認と中心帰還による再参加]'
                f'(アルゴリズム調査/{FOLDER}/{MAIN.name})** です。36条件・全31既知場を比較。'
                f'[読む順序](アルゴリズム調査/{FOLDER}/README.md)も参照してください。'
                '両銘柄の安定収益と利益80%への調査は継続中です。')
    source, count = re.subn(r'^最新の調査は .*$', lambda match: new_line, source, count=1, flags=re.M)
    assert count == 1
    root_readme.write_text(source, encoding='utf-8')
    research_readme = RESEARCH / 'README.md'
    source = research_readme.read_text(encoding='utf-8')
    if '<!--00088案内開始-->' not in source:
        block = (f'<!--00088案内開始-->\n**最新は00088の[{MAIN.name}]({FOLDER}/{MAIN.name})。'
                 '回復確認・極値停止・中心帰還・固定配分の36条件、全31既知場。**\n\n'
                 f'[読む順序]({FOLDER}/README.md) · [公開会計]({FOLDER}/公開会計.json)。'
                 '両銘柄共通の安定性と利益80%は未達です。\n<!--00088案内終了-->\n\n')
        assert '<!--00087案内開始-->' in source
        source = source.replace('**最新は00087の', '**00087の', 1)
        source = source.replace('<!--00087案内開始-->', block + '<!--00087案内開始-->', 1)
    research_readme.write_text(source, encoding='utf-8')
    index = RESEARCH / 'index.html'
    source = index.read_text(encoding='utf-8')
    if '<!--00088開始-->' not in source:
        source = source.replace('class="task latest"', 'class="task"')
        source = source.replace(' <span class="badge">最新</span>', '')
        article = (f'<!--00088開始--><article class="task latest"><div class="number">作業00088 '
                   '<span class="badge">最新</span></div><h2>回復確認と中心帰還による再参加</h2>'
                   '<p>入口・極値停止・再参加・固定配分の36条件を全31既知場で比較。'
                   '主案は不採用。両銘柄共通の安定収益と金額利益80%は未達です。</p>'
                   f'<a class="button" href="{FOLDER}/{MAIN.name}">説明と全場損益</a> '
                   f'<a href="{FOLDER}/README.md">読む順序</a></article><!--00088終了-->\n')
        assert '<!--00087開始-->' in source
        source = source.replace('<!--00087開始-->', article + '<!--00087開始-->', 1)
    source, count = re.subn(r'<p class="lead">最新0008[78]：.*?</p>',
                            '<p class="lead">最新00088：回復確認と再参加の36条件。全31既知場の損益と、利益を失う原因を掲載します。</p>',
                            source, count=1)
    assert count == 1
    index.write_text(source, encoding='utf-8')
    assert prior == {str(path.relative_to(ROOT)): sha(path)
                     for folder in old_folders for path in folder.rglob('*') if path.is_file()}
    outputs = [MAIN, OUT / 'README.md', OUT / '公開会計.json', root_readme, research_readme, index]
    proof = dict(全合格=True, HTML_SHA256=sha(MAIN), 全口座=2232, 商品期間集計=576,
                 全31既知=True, 新未見確認場数=0, 根担当五画面目視確認=True,
                 旧00087と00086全成果不変=True, 旧成果指紋=prior,
                 公開指紋={str(path.relative_to(ROOT)): sha(path) for path in outputs},
                 監査SHA256=sha(audit_path), 取消補足監査SHA256=sha(cancel_proof_path),
                 配分診断SHA256=sha(mixing_path),
                 条件及び参考の差替え=False, API取得=0, 実注文=0)
    (HERE / '公開結果.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: value for key, value in proof.items() if key != '旧成果指紋'}, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
