"""正式会計と独立監査後に、安定性の結論だけを短い日本語へ変換する。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]


def read(path: Path) -> dict:
    """
    機能: 完結した正式会計と独立証跡を読む。
    引数: path(Path)は日本語JSON。
    返り値: dict。保存された値。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 説明が参照した正式資料を内容で固定する。
    引数: path(Path)は対象資料。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 赤字平均・最大と活動黒字率の比較を短文化し、会計値を変更せず保存する。
    引数: なし。
    返り値: None。未完の会計又は独立検査は説明の生成前に拒否する。
    """
    paths = [WORK / 'audit/全34全31の台帳会計と代表待機及び全原板の独立検算.json',
             WORK / 'review/全34条件全31の独立親会計と安定性及びNoCap旧620対照一致.json',
             WORK / 'review/全34判断価格上限と支持源及び即時の同候補建値差と固有経路の独立分解.json',
             WORK / 'review/主とP0及び前16参考と事後RMS上位の最悪3場原板と判断約定上限の独立反証.json',
             WORK / 'engine_review/全34の元候補別価格上限拒否と実約定超過及び二原板事例の原因.json',
             HERE / '判断価格上限の実建値差と消えた勝負及び新固有親.json']
    for path in paths:
        proof = read(path)
        assert proof.get('全合格', proof.get('合格', False)), path
        for relative, expected in proof.get('SHA256', {}).items():
            assert digest(ROOT / relative) == expected, relative
    result_path = HERE / '比較結果.json'
    result = read(result_path)
    assert result['全合格'] and result['条件数'] == 34 and len(result['sessions']) == 31
    primary, control = result['primary'], 'P0_L1_C1_A1_X1'
    assert primary == 'P1_L1_C1_A1_X1'
    description = []
    comparisons = {}
    for symbol, name in (('TOPIX', 'TOPIX'), ('NK225', '日経')):
        old = result['results'][control]['stability']['全31'][symbol]
        new = result['results'][primary]['stability']['全31'][symbol]
        old_money = result['results'][control]['periods']['全31'][symbol]
        new_money = result['results'][primary]['periods']['全31'][symbol]
        comparisons[symbol] = dict(旧=old, 新=new, 旧金額=old_money, 新金額=new_money)
        description.append(f'{name}：最大赤字 {old["worst_session_loss_yen"]:,.0f}→{new["worst_session_loss_yen"]:,.0f}円、'
            f'黒字 {old_money["positive_sessions"]}/{old["active_sessions"]}→{new_money["positive_sessions"]}/{new["active_sessions"]}活動場。')
    target = result['活動充足の両80']
    assert target == [], '有効候補があれば不採用の定型文を使わず再評価する'
    conclusion = ['価格制限だけでは毎セッションの安定性を改善できず、今回の改修は採用しません。金額利益割合80%に達した両商品共通の有効候補は0件です。',
                  '事前主の1W制限では、最大赤字と活動黒字率は無制限と同じです。'+' '.join(description),
                  '日経の1取引は安く入れましたが、損切り価格も下がり損失は同額。半Wへ狭めても両商品の最大赤字は減りませんでした。全31場の損益を以下に掲載します。']
    notes = dict(result['cause_notes'])
    notes['待機幅'] = 'Wは始値約0.1%を最低2呼値へ切上げ。A7の局所押し回復に使う半Wは呼値へ切上げるが、元候補からの価格上限K×Wは数学値のまま。この二つを混同しない。'
    notes['診断の範囲'] = '全34×62口座の親会計と全原板時価を独立検算。最初の触発・潜在状態と上限20列の全経路再生は事前に指定した代表。全34の全触発を独立再生したとは呼ばない。判断内と実約定超過は別に保存。'
    notes['主の実経路'] = '10/12デイの日経：候補69110、旧は69190買い→69120返済、新は69180買い→69110返済。入口は10pt改善したが初期停止70ptのままなので、両方−11,552円。利益・損失・収支と件数が同じでも、全注文や途中の時価曲線が同じではない。'
    notes['損失の内訳'] = '主の最悪3赤字場を原板照合。TOPIXの赤字5親中3親、日経7親中6親は、保有中に料金込み黒字へ一度も届かなかった。残りTOPIX2親・日経1親は黒字を返して損失となった。これは事後の原因分類で、新規時の見送り判定へ将来の最大順行を使っていない。'
    notes['防げた例と残る例'] = '9/24ナイトTOPIXの遅い4080買い−36,668円は全有限上限で回避。ただし同じ候補の早いA1は4066買い→4079返済で＋103,332円。9/28日経は候補と同値66660買いでも66590返済−11,552円が残り、候補価格との距離だけでは方向の継続を判定できない。'
    notes['安定性の事後上位'] = 'P05_L0_C1_A1_X1は、TOPIXで旧の勝ち47,332円を逃し、回避した旧の損失は668円。日経は旧損失20,256円を回避したが、両商品とも最大利益日を除く収支は赤字。TOPIXの黒字場は11/26から10/24へ減り、取引縮小を安定成功とは扱わない。'
    paths += [result_path, WORK / '事前固定.json', WORK / '前16参考代表.json', Path(__file__)]
    value = dict(全合格=True, 正式全範囲独立検算完了=True, 独立原因検査完了=True,
                 根集計SHA256=digest(result_path), 売買及び会計の変更=0,
                 conclusion=conclusion, cause_notes=notes, 主と無制限の安定性比較=comparisons,
                 根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in paths},
                 全31既知=True, 未見確認場数=0, API取得=0, 実注文=0)
    (HERE / '説明補足.json').write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, conclusion=conclusion), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
