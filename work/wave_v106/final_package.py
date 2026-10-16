"""既知会計・現在入力停止・独立確認と目視を束ね、目標未達の成果物を固定する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import complete_trials


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00103_往復帯の回避と損失後再参加の統合検証'


def read(path: Path) -> tuple[dict, str]:
    """
    機能: 完成小JSONを読み、証跡の内容指紋を確認する。
    引数: path(Path)は会計・登録・表示検査・独立監査の位置。
    返り値: tuple[dict,str]は値とSHA256。原板、金融台帳又はAPIを利用しない。
    """
    saved = path.read_bytes()
    return json.loads(saved), hashlib.sha256(saved).hexdigest()


def main() -> None:
    """
    機能: 完成済み18試行と現在失敗の終端、最終二ページの目視を束縛する。
    引数: なし。根が1450/520幅の最終4PNGを実際に閲覧した後だけ実行する。
    返り値: None。達成判定は未達のままとし、会計及び未知成績を再生しない。
    """
    target = HERE / '今回の成果と未達の最終確認.json'
    assert not target.exists()
    trials, _ = read(ROOT / 'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data/trials.json')
    index = {r['id']: r for r in trials['trials']}
    finances = {}
    for identifier, relative in complete_trials.COMPLETED.items():
        path = HERE / relative
        data, digest = read(path)
        assert data['全合格'] and index[identifier]['completed_result']['sha256'] == digest
        assert index[identifier]['status'] == '検証済み'
        finances[identifier] = dict(path=path.relative_to(ROOT).as_posix(), SHA256=digest)
    # ----------------------------------------
    # 現在場の入力不適合は完成金融と分離する。
    current_path = HERE / 'current_session/入力不適合の終端登録.json'
    current, current_sha = read(current_path)
    assert current['全合格'] and current['現在金融'] == '未測定'
    assert index[current['登録ID']]['status'] == '未測定（入力不適合）'
    assert not (HERE / 'current_session/finance/結果.json').exists()
    capture, _ = read(HERE / 'current_capture/取得完了.json')
    assert capture['現セッション取得回数'] == 1 and capture['HTTP要求合計'] == 2
    # ----------------------------------------
    # 独立した数値・リンク・画面確認と、根の実目視を結ぶ。
    qa_path = HERE / 'price_review/current_短結論と入力失敗表示の広狭検査_v3.json'
    qa, qa_sha = read(qa_path)
    assert qa['全合格'] and len(qa['画面']) == 4
    for relative, digest in qa['資料SHA256'].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest
    viewed = []
    for screen in qa['画面']:
        path = Path(screen['画像'])
        assert hashlib.sha256(path.read_bytes()).hexdigest() == screen['PNG_SHA256']
        viewed.append(dict(path=path.relative_to(ROOT).as_posix(), SHA256=screen['PNG_SHA256'], 目視確認=True))
    review_path = HERE / 'price_review/最終公開文面の敵対的確認.json'
    review, review_sha = read(review_path)
    assert review['全合格']
    # ----------------------------------------
    # 目標と完成した検証範囲を混同せず保存する。
    summary, summary_sha = read(PUBLIC / '今回の結論の表示根拠.json')
    assert summary['現在金融'] == '未測定' and summary['既知場数'] == 33
    assert all(r['profit_share'] < .8 and r['average_payoff'] < 1 for r in summary['rows'])
    value = dict(成果物照合=True, 時刻=datetime.now(timezone(timedelta(hours=9))).isoformat(),
                 期限='2026-10-14T06:00:00+09:00', 目標達成=False,
                 未達理由='両商品で毎場の小〜中利益・金額利益80%を満たす条件は未発見。代表2つも平均損小利大未達。',
                 既知場数=33, 完成金融試行数=len(finances), 完成金融=finances,
                 現在一回取得=True, 現在金融='未測定（価格時計の日付逆行）',
                 現在停止登録=dict(path=current_path.relative_to(ROOT).as_posix(), SHA256=current_sha),
                 表示数値監査=dict(path=qa_path.relative_to(ROOT).as_posix(), SHA256=qa_sha),
                 最終文面監査=dict(path=review_path.relative_to(ROOT).as_posix(), SHA256=review_sha),
                 根の目視= viewed, 最終表示根拠SHA256=summary_sha,
                 この照合での金融再生=0, この照合でのAPI取得=0, 実注文=0,
                 保存先='00103。法則は共通の分類別Markdown、優先順位は調査方針.md、試行重複は00101。')
    target.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf8')
    print('18既知試行と現在入力停止を固定。最終4画面目視済み。目標未達。')


if __name__ == '__main__':
    main()
