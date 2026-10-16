"""全34の正式会計と独立した原板調査から、毎セッションの安定性を短く説明する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: 完了した正式会計又は独立検査資料を読む。
    引数: path(Path)は日本語JSON。
    返り値: dict。保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 説明の根拠を現在の正式資料へ結びつける。
    引数: path(Path)は参照資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 売買、選定、会計を変更せず、確認できた改善不足と未測定の仮説を分ける。
    引数: なし。
    返り値: None。短い結論と折りたたみ内の具体的原因を保存する。
    """
    fixed_path, analysis_path = WORK / '事前固定.json', HERE / '比較結果.json'
    audit_path = WORK / 'audit/全34全31の台帳会計と代表待機及び全原板の独立検算.json'
    review_paths = [WORK / 'review' / name for name in (
        '全34条件全31の独立親会計と安定性及びL0旧対照一致.json',
        '全34現在支持の同候補建値差と勝ち刈り及び固有経路の独立分解.json',
        '主と参考及び現在支持対照の最悪3場原板と源及び再準備の独立反証.json')]
    fixed, analysis, audit = map(read, (fixed_path, analysis_path, audit_path))
    assert analysis['全合格'] and audit['合格']
    assert len(fixed['条件']) == len(analysis['results']) == 34 and len(fixed['全31']) == 31
    assert analysis['primary'] == 'L1_C1_A7_X3' and analysis['selected'] == 'A0_X1'
    assert analysis['both80'] == analysis['活動充足の両80'] == []
    assert analysis['両商品で全場黒字'] == []
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for path in review_paths:
        proof = read(path)
        assert proof['全合格'] and proof['条件数'] == 34
        assert proof['主'] == analysis['primary']
        assert proof['固定SHA256'] == digest(fixed_path)
        assert proof['根集計SHA256'] == digest(analysis_path)
    main_values = analysis['results'][analysis['primary']]['periods']['全31']
    assert main_values['TOPIX']['net'] == -29336 and main_values['TOPIX']['campaigns'] == 2
    assert main_values['NK225']['net'] == -96320 and main_values['NK225']['campaigns'] == 10
    assert main_values['NK225']['winning_campaigns'] == 1
    old = analysis['results']['L0_C1_A1_X1']
    new = analysis['results']['L1_C1_A1_X1']
    assert old['periods']['全31']['NK225']['net'] == 34080
    assert new['periods']['全31']['NK225']['net'] == -16736
    assert old['stability']['全31']['TOPIX']['worst_session_loss_yen'] == 38004
    assert new['stability']['全31']['TOPIX']['worst_session_loss_yen'] == 73336
    prices_path = HERE / '現在支持源の実建値差と消えた勝負及び新固有親.json'
    prices = read(prices_path)
    assert prices['全合格'] and len(prices['source_comparison']) == 16
    assert len(prices['policy_comparison']) == 24

    # ----------------------------------------
    # 損失を避けられなかった具体的な入口と、損失額・黒字率の違いを説明する。
    notes = dict(analysis['cause_notes'])
    notes.update({
        '今回の判定': '全34条件に両商品金額利益80%又は全場黒字の解はありません。独立取引価格による現在方向支持への変更を、安定運用として採用しません。全31は既知の再探索で、無取引を勝ちに数えません。',
        '押し待ち主の結果': 'TOPIXは2親1勝1敗で利益7,332円・損失36,668円・収支−29,336円。日経は10親1勝9敗で利益6,048円・損失102,368円・収支−96,320円。日経は取引した8セッションすべて赤字ですが、10決済親すべてが負けたわけではありません。',
        '待っても安く買えていない具体例': '9月24日ナイトのTOPIXは9月25日01:15:15、原本seq113387の候補ask4,063.5から、原本価格時計上296秒後の01:20:11、seq115995で4,079.5の発注判断、seq115996で4,080買い。支持格子は01:20:10で候補から295秒ですが、真の受信経過ではありません。候補より実建値が16.5pt高くなりました。01:23:55、seq117736で4,075.5返済し−36,668円。局所peak4,084から4,076.5へ7.5pt押し、判断まで3pt回復しても、実建値からの最大順行は1.5ptで初期幅4.5pt未満でした。局所回復と元候補から有利な価格で入ることは同じではありません。',
        '価格追随だけでは説明できない負け': '日経は9月28日09:42:05、元候補と同値の66,660で買った取引も−11,552円。最大順行100円では、利益床の開始に必要な初期幅2倍の140円へ届きませんでした。候補価格への上限だけで全ての損失が消えるとは言えません。',
        '主の新しい取引': '旧の現在支持と共通の日経5親は、建値・返済・費用差が0円。追加5親の利益6,048円、損失46,208円で−40,160円が加わりました。TOPIXの追加2親も−29,336円。観測できるようになった取引が利益を生むとは限りません。',
        '気配再進行入口の比較': 'L1_C1_A1_X1はTOPIX＋245,940円、日経−16,736円。旧L0_C1_A1_X1は＋247,944円、＋34,080円でした。新確認でTOPIXの活動黒字は11／26から12／26へ増えましたが、最大赤字は38,004円から73,336円へ拡大。日経も最大赤字26,304円から39,456円へ拡大し、毎場の損失削減という目的を達成していません。',
        '新確認で日経が悪化した内訳': 'L1_C1_A1_X1は旧の利益10,848円を1親取り逃し、新しい9親の収支−39,968円が加わり、旧から−50,816円悪化しました。同じ候補で建値が改善したのか、旧の勝ちを消したのか、新しい負けを増やしたのかを分離しています。',
        '最小下方偏差でも安定とは限らない': '全31を見た事後診断の下方偏差最小は旧確認のL0_C3_A1_X1。TOPIX＋98,632円・日経＋14,496円ですが、活動黒字8／20場・7／17場、無取引11場・14場。最大利益日を除くと両銘柄とも赤字です。低い損失の振れだけで採用しません。',
        '再準備への作用': 'L0とL1ではC3の再準備経路がTOPIX14候補・日経25候補で異なりました。現在支持の変更は最終発注行だけでなく、局所極値を作り直す段階にも作用します。元候補、元TTL、硬い反対取消は保持しています。',
        '独立検算の範囲': '全34条件2108口座・544商品期間の会計、料金、全原板清算時価、支持59と実支持2列の指紋を独立照合。入口出口の最初触発と旧内部20・観測10等は5代表310口座。補助10フラグの全行独立再構築と呼びません。反復計算した原板行数を独立した市場標本数へ数えません。',
        '最大利益日除外の意味': '日付ラベル別にデイ・ナイトを合算し、合計収支が最大の日付を除きます。最大の単一取引又は単一セッションだけを除く指標ではありません。',
        '次に確かめること': '局所の回復だけで入らず、元候補からどれだけ不利な価格まで追うかを制限する案を検討します。発注判断価格の制限と、実際の約定価格を指値で制限する方法は別の変更です。活動不足、見送る旧利益、注文後の価格変化も測る必要があり、成績はまだ未測定です。'}
    )
    conclusions = [
        '今回も、両銘柄で毎セッション安定する解は未発見です。34条件に金額利益80%を満たすものはありません。',
        '現在方向を取引価格で再確認しても、押し待ち主はTOPIX−29,336円・日経−96,320円。回復を待ちながら元候補より高く買う例があり、入口の改善になりませんでした。',
        '気配再進行案でも、TOPIXの最大赤字38,004円→73,336円、日経26,304円→39,456円と悪化。黒字率・赤字額・取引数を分けて比較し、新しい確認方法は採用しません。']
    paths = [fixed_path, analysis_path, audit_path, prices_path, Path(__file__),
             WORK / '前16参考代表.json', WORK / '公式仕様の時計項目と保存原本の区別.json'] + review_paths
    result = dict(全合格=True, 正式全範囲独立検算完了=True, 独立原因検査完了=True,
                  根集計SHA256=digest(analysis_path), 売買及び会計の変更=0,
                  conclusion=conclusions, cause_notes=notes,
                  根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths},
                  全31既知=True, 未見場数=0, API取得=0, 実注文=0)
    (HERE / '説明補足.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 結論=conclusions), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
