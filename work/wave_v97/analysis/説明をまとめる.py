"""全36の正式会計と独立原因から、安定性を優先した短い説明を保存する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = HERE.parents[2]


def read(path: Path) -> dict:
    """
    機能: 完了した正式会計又は原因検査を読む。
    引数: path(Path)は日本語JSON。
    返り値: dict。保存内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 説明の根拠を現在の正式資料へ結びつける。
    引数: path(Path)は参照する資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 売買と選定を変更せず、目的未達と未測定の仮説を区別する。
    引数: なし。
    返り値: None。全31損益を伴う日本語の説明補足を保存する。
    """
    paths = [WORK / 'audit/全36全31の台帳会計と代表待機及び全原板の独立検算.json',
        WORK / 'review/3正式レビューの独立原因要旨と代理時計による活動不足の反証.json',
        WORK / 'review/全36条件全31の独立親会計と安定性及び即時旧対照一致.json',
        WORK / 'review/全36待機の同候補建値差と勝ち刈り及び固有経路の独立分解.json',
        WORK / 'review/主と事前参考及び同出口即時の最悪3場原板と待機救済及び勝ち刈りの独立反証.json',
        WORK / 'review/独立元候補分解と根別保存の全36商品突合.json',
        WORK / 'root_preflight/後15未作成の全36前16実親会計と安定順による独立参考選定.json',
        HERE / '待機の実建値差と旧勝ちの取り逃し及び新固有親.json',
        WORK / 'entry_support/全31の候補許可と現在門番及び待機不成立の独立入力診断.json',
        WORK / 'entry_support/A7の10秒gap全原本時計と保持seq及び同clock実板変化の独立診断.json',
        WORK / 'entry_support/A4四出口の同一新規一事例と返済相違の独立照合.json']
    for path in paths:
        proof = read(path)
        assert proof.get('全合格', proof.get('合格', False)), path.name
    analysis_path = HERE / '比較結果.json'
    analysis = read(analysis_path)
    summary = read(paths[1])
    assert summary['根集計SHA256'] == digest(analysis_path)
    assert analysis['primary'] == summary['主'] == 'A7_X3'
    assert analysis['selected'] == summary['前16固定参考'] == 'A0_X1'
    assert analysis['both80'] == summary['両商品金額80'] == ['A4_X0', 'A4_X1', 'A4_X2', 'A4_X3']
    assert not summary['活動充足両80']
    for relative, expected in summary['根拠SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    main_values = analysis['results']['A7_X3']['periods']['全31']
    assert main_values['TOPIX']['campaigns'] == 0
    assert main_values['NK225']['campaigns'] == 2 and main_values['NK225']['net'] == -23104.
    sparse = analysis['results']['A4_X3']['periods']['全31']
    assert all(v['campaigns'] == 1 and v['active_sessions'] == 1 for v in sparse.values())
    notes = dict(analysis['cause_notes'])
    notes.update({
        '主の取消の理由': 'TOPIX94候補のうち68件が自己代理時計の10秒超、21件がresetで取消。日経80候補では71件と4件。両市場の明確な逆方向による取消は4件・1件です。主の低損失を入口の成功とは扱いません。',
        '価格時計と観測断裂': '10秒超取消139件すべてで原本の行通番は連続でした。ただし行通番は受信正常を証明しません。今回の再生時計はCurrentPriceTime由来で真受信時計ではないため、時計の飛びをネットワーク断又は市場の反証と断定できません。真受信時計を使った待機は今回未測定です。',
        '同じ価格時計でも板が変わる': '取消139件すべてで、直前の同じ価格時刻の区間にも最良気配数量が変化していました。TOPIXの9月21日ナイトでは、価格時計17:37:28の63行に15通りの最良数量、45通りの板がありました。次行の時計17:37:54への飛びを受信停止とみなすのは不適切です。原本には真の受信時刻がなく、二市場の実際の受信順序も保証できません。',
        '成立した日経の建値': '主に残った2取引はいずれも即時入口より高く買いました。建値差が合計−64,000円、返済差が＋11,200円、同候補差は−52,800円。待つだけで有利な価格になるとは限りません。',
        '9月24日ナイトの具体例': '日経の9月25日01:15:15候補はask65360。押し待ち後01:17:05の新規判断、次の原行65730買、後の原行65660返済で−11,552円。即時の同候補は65360買から65620返済で＋41,248円でした。判断・買い・返済が同じ代理時刻でも原本の行順は異なり、0秒の同時売買とは解釈しません。',
        '両80%の少数結果': 'A4の2W順行待ちは、四出口とも各商品1取引ずつだけで金額利益割合100%。同じ新規一例を異なる返済条件で処理した結果です。30場は無取引、最大利益日を除く収支は0円です。四表示を4回の独立した成功とは数えません。',
        '旧即時の安定性': '旧の初期0.4%・通常30分A0_X0は、両商品17黒字・12赤字・2無取引。TOPIX＋440,556円、日経＋186,208円ですが、金額利益割合は55.8%・56.5%にとどまり、毎場安定する解ではありません。',
        '細い初期停止の参考': '前16の参考A0_X1はTOPIX＋265,216円、日経−43,456円、黒字15／29・13／29活動場。平均・最大赤字が減っても、黒字場が増えたとは言えません。',
        '次に確かめること': '価格更新間隔と本当の観測断裂を分け、代理時計だけで候補を消す処理と、既知の価格・源を保持又は再準備する処理を結果前に固定して比較します。押し回復や気配再進行そのものを今回で否定しません。',
        '独立検算の範囲': '全36条件・2232口座・576商品期間の注文、親会計、料金、全原板清算時価が独立計算と一致。最初の新規・返済と待機の全経路はA7_X3・A2_X3・A5_X3・A0_X1の4代表248口座で独立再生。他の32条件の最初触発全経路まで独立再生したとは言いません。'
    })
    conclusions = [
        '今回の36条件では、毎セッションの安定改善に届きませんでした。新しい待機入口は採用しません。',
        '押し待ちの主はTOPIX0取引、日経2取引で−23,104円。大半を「代理時計の10秒超」で取消しており、押し回復の有効性は十分に測れていません。',
        '両銘柄の金額利益80%を超えた4設定も、各商品1取引だけ。無取引30場を勝ちに数えず、安定収益の解とは扱いません。'
    ]
    paths += [analysis_path, Path(__file__)]
    result = dict(全合格=True, 正式全範囲独立検算完了=True, 独立原因検査完了=True,
        根集計SHA256=digest(analysis_path), 売買及び会計の変更=0,
        conclusion=conclusions, cause_notes=notes,
        根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths},
        全31既知=True, 未見場数=0, API取得=0, 実注文=0)
    (HERE / '説明補足.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 結論=conclusions), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
