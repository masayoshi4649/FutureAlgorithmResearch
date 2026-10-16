"""97の正式結果と公開成果を保持し、98の未実行課題を区別して残す。"""

import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(path: Path) -> dict:
    """
    機能: 正式な固定、会計又は検査資料を読む。
    引数: path(Path)はJSON資料。
    返り値: dict。保存済みの内容。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def digest(path: Path) -> str:
    """
    機能: 公開後に売買及び入力が変わっていないことを検査する。
    引数: path(Path)は資料又は依存ファイル。
    返り値: str。SHA256。
    """
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main() -> None:
    """
    機能: 公開後の全依存を検査し、未達と次の入力課題を保存する。
    引数: なし。
    返り値: None。97の結果を変更せず、98の売買結果を捏造しない。
    """
    fixed_path = HERE / '事前固定.json'
    fixed = read(fixed_path)
    for relative, expected in fixed['SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    publication_path = HERE / 'report/公開結果.json'
    publication = read(publication_path)
    for relative, expected in publication['公開SHA256'].items():
        assert digest(ROOT / relative) == expected, relative
    proof_paths = [HERE / relative for relative in (
        'audit/全36全31の台帳会計と代表待機及び全原板の独立検算.json',
        'review/3正式レビューの独立原因要旨と代理時計による活動不足の反証.json',
        'entry_support/全31の候補許可と現在門番及び待機不成立の独立入力診断.json',
        'entry_support/A7の10秒gap全原本時計と保持seq及び同clock実板変化の独立診断.json',
        'entry_support/A4四出口の同一新規一事例と返済相違の独立照合.json',
        'report/表示の独立検査.json', 'report/根担当の目視確認.json')]
    for path in proof_paths:
        saved = read(path)
        assert saved.get('全合格', saved.get('合格', False)), path.name
    comparison = read(HERE / 'analysis/比較結果.json')
    assert len(fixed['条件']) == len(comparison['results']) == 36
    assert len(fixed['全31']) == 31
    result = dict(
        全合格=True,
        段階='97正式再生・独立検算・原因調査・画面検査・公開まで完了。探索目標は未達で継続。',
        公開資料=publication['公開資料'],
        固定依存検査数=len(fixed['SHA256']),
        公開後検査数=len(publication['公開SHA256']),
        条件数=36, 全セッション数=31, 商品数=2, 会計口座数=2232,
        独立新規返済及び待機全経路='A7_X3、A2_X3、A5_X3、A0_X1の4代表248口座。残り32は全会計・清算時価の独立検算。',
        主='A7_X3', 参考='A0_X1',
        安定性の改善を採用=False,
        理由='主はTOPIX0取引・日経2取引全負け。80%表示のA4は同一新規一例の別出口であり、各商品30無取引場を勝ちに数えない。',
        入力原因='139取消に使うCurrentPriceTimeの飛びは真受信間隔ではない。同じ時計でも板が変わる。保存行seqは一銘柄内の前後であり、通信正常や二市場の共通受信順を保証しない。',
        次の未実行課題=[
            '価格時計の飛びと実原板欠測を分ける。単に10秒閾値を延長する最適化にしない。',
            '取消・保持・別基準での再準備を結果前に有限条件として固定する。TTL及び候補競合、場内返済は保つ。',
            '自己seqと価格時計、未知相手、reset、同clockの板変化と次正常BBOを人工正負入力で独立検証する。',
            '共通受信時計が無い限りペア再生の公開順仮定を明示し、ライブの因果順まで証明したと呼ばない。',
            '各場の赤字額・赤字頻度・悪い側の商品・最大利益日を除く収支を優先し、活動減少と入口建値改善を分離する。',
        ],
        次段売買結果=0, 次段採用済条件=0, 現在API取得=0, 実注文=0,
        全31既知=True, 未見確認場数=0,
        根拠SHA256={str(path.relative_to(ROOT)): digest(path) for path in proof_paths+[fixed_path, publication_path, HERE / 'analysis/比較結果.json']},
    )
    out = HERE / '97正式終端と98入力時計の未実行引継ぎ.json'
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 固定依存検査数=result['固定依存検査数'], 公開後検査数=result['公開後検査数'], 探索目標='未達で継続'), ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
