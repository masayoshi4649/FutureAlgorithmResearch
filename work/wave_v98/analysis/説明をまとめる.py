"""正式会計と独立した原因検査から、セッション安定性を優先した説明を保存する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: 完了した正式会計又は独立検査資料を読む。
    引数: path(Path)は日本語JSONのファイル。
    返り値: dict。保存された内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 説明の根拠を正式資料と結びつける。
    引数: path(Path)は参照する資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 売買判断や会計を変更せず、測定結果と未測定の改善案を区別する。
    引数: なし。
    返り値: None。短い結論と折りたたみ用の原因説明を保存する。
    """
    fixed_path = WORK / '事前固定.json'
    analysis_path = HERE / '比較結果.json'
    audit_path = WORK / 'audit/全34全31の台帳会計と代表待機及び全原板の独立検算.json'
    summary_path = WORK / 'review/3正式レビューと追加門番診断の独立原因要旨.json'
    paths = [fixed_path, analysis_path, audit_path, summary_path,
             WORK / '前16参考代表.json',
             HERE / '時計政策の実建値差と消えた勝負及び新固有親.json',
             WORK / '公式仕様の時計項目と保存原本の区別.json']
    fixed, analysis, audit, summary = map(read, (fixed_path, analysis_path, audit_path, summary_path))
    assert analysis['全合格'] and audit['合格'] and summary['全合格']
    assert len(fixed['条件']) == len(analysis['results']) == 34 and len(fixed['全31']) == 31
    assert analysis['primary'] == summary['主'] == 'C1_A7_X3'
    assert analysis['selected'] == summary['前16固定参考'] == 'A0_X1'
    assert summary['固定SHA256'] == digest(fixed_path)
    assert summary['根集計SHA256'] == digest(analysis_path)
    assert analysis['both80'] == summary['両商品金額80'] == []
    assert summary['活動充足両80'] == []
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    for relative, expected in summary['根拠SHA256'].items():
        path = WORK / 'review' / relative
        assert digest(path) == expected, relative
        paths.append(path)
    main_values = analysis['results']['C1_A7_X3']['periods']['全31']
    assert main_values['TOPIX']['campaigns'] == 0 and main_values['TOPIX']['net'] == 0
    assert main_values['NK225']['campaigns'] == 5 and main_values['NK225']['net'] == -56160
    partial = analysis['results']['C1_A1_X1']
    top, nk = (partial['periods']['全31'][symbol] for symbol in ('TOPIX', 'NK225'))
    assert top['net'] == 247944 and nk['net'] == 34080
    assert top['without_best_day']['net'] == 24620 and nk['without_best_day']['net'] == -34912
    assert partial['stability']['全31']['TOPIX']['worst_session_loss_yen'] == 38004
    assert partial['stability']['全31']['NK225']['worst_session_loss_yen'] == 26304
    extra = summary['TOP回復門番の追加根拠']
    assert extra['押し回復成立変化点'] == 203
    assert extra['押し回復成立の異なる候補数'] == 2
    assert extra['回復とJ2の同時成立変化点'] == 0

    # ----------------------------------------
    # 根拠のある損失削減と、取引減少や未測定の期待を分けて説明する。
    notes = dict(analysis['cause_notes'])
    notes.update({
        '今回の判定': '34条件のいずれも両銘柄で金額利益80%に届かず、全31場黒字でもありません。主も事後の診断案も安定運用として採用しません。無取引は勝ちに数えません。',
        '損失額を減らせた診断案': 'C1_A1_X1は、両市場の方向が一致した候補から、両市場の買い・売り気配が各1呼値進むまで待って新規にします。初期損切り0.1%、追尾0.4%、通常30分で返済判断。TOPIX8枚・日経16枚です。TOPIX＋247,944円、日経＋34,080円ですが、黒字は活動26場中11場・23場中9場。最大赤字は38,004円・26,304円に減る一方、黒字率は即時入口より下がりました。事後診断であり、事前に選んだ代表を置き換えません。',
        '少数化との区別': 'C1_A1_X1は即時A0_X1の88親・78親から42親・35親に減っています。最大赤字の減少だけで方向判断の正答率が上がったとは言えません。日付別収支が最大の日を除くと、TOPIX＋24,620円、日経−34,912円。日経の合計黒字は大勝ちへの依存が残ります。',
        '押し待ち主の原因': 'C1_A7_X3はTOPIX0取引、日経5取引すべて赤字で−56,160円。価格時計差だけで取り消さなくした結果、旧C0と共通の2取引の建値・返済・手数料は同じまま、新しい3敗−33,056円が加わりました。価格時計差の誤解を直すことと、収益改善は別です。',
        '再準備の効果と限界': 'C3_A7_X3は新しい3敗を避け、日経−23,104円へ戻りましたが、共通2取引の建値を改善せず、TOPIXの利益機会も増えていません。負ける取引を減らした結果であり、安定して利益を生む入口の証明ではありません。',
        '具体的な新しい負け': '9月24日デイの日経は10:26:31、原本seq42045で65,950買い、10:27:18、seq42360で65,880返済し−11,552円。保有中の最高買い気配でも建値より10円低く、一度も返済可能な含み益になりませんでした。トレーリングの広さだけでは救えない入口です。',
        'TOPIXの押し回復が入れない理由': '主の保存変化点で押し回復が成立した203点は、独立した203回の機会ではなく2候補です。全点で旧の日経300秒の気配中値窓が不明となり、現在方向の再確認に失敗。148点では両気配の進行自体は成立しました。価格窓の不明を、両市場の方向が反転した証拠とは扱いません。',
        '取引価格に置き換えても無条件に入れない': '9月25日01:19:12のTOPIX回復点では、独立した300秒取引価格変化は両市場プラスでしたが、日経の気配進行は0呼値。10月6日09:13:59では取引価格窓が有効でも両市場の方向が異なりました。観測源だけを置き換えた待機戦略の全損益はまだ測っていません。',
        '時間と注文の検証限界': '再生時計はCurrentPriceTime由来で、真の受信時刻や二市場の共通受信順は保存されていません。同じ価格時計でも板は変わります。公式PUSH仕様では先物の気配時刻は非対応です。因果的な保存順で検証しましたが、実際の配信順・注文待ち時間を保証する結果ではありません。',
        '最大利益日除外の意味': '同じ日付のデイ・ナイト収支を合算し、その合計収支が最大の日付を除きます。最大の単一取引又は単一セッションだけを除く指標ではありません。',
        '独立検算の範囲': '全34条件・2108口座・544商品期間の会計、料金、全原板清算時価を独立照合。5代表310口座は最初の新規・返済、内部状態20列と観測源10列等も独立再生。補助フラグ10列まで全行独立再構築したとは言いません。原板時価の反復計算回数を独立した標本数に数えません。',
        '次に確かめること': '候補・待機幅・返済を固定し、発注時の方向再確認だけを、旧の気配中値窓と独立した取引価格窓で比較します。赤字額、黒字場数、活動数、同候補の建値差を別々に測り、取引減少だけで改善扱いしません。全31は既知の再探索です。現在API取得・実注文は0です。'
    })
    conclusions = [
        '34条件を比較しましたが、両銘柄で毎セッション安定する解は未発見です。金額利益80%にも届いていません。',
        '損失額を減らせた診断案はC1_A1_X1。TOPIX＋247,944円・日経＋34,080円、最大赤字38,004円・26,304円。ただし黒字は11／26場・9／23場で、日経は最大利益日を除くと赤字です。',
        '押し待ちの主はTOPIX0取引・日経−56,160円。TOPIXでは回復しても古い日経価格窓が不明で入口を止めていました。取引価格窓による再確認への変更は、次に検証する案です。'
    ]
    paths.append(Path(__file__))
    result = dict(全合格=True, 正式全範囲独立検算完了=True, 独立原因検査完了=True,
                  根集計SHA256=digest(analysis_path), 売買及び会計の変更=0,
                  conclusion=conclusions, cause_notes=notes,
                  根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths},
                  全31既知=True, 未見場数=0, API取得=0, 実注文=0)
    (HERE / '説明補足.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 結論=conclusions), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
