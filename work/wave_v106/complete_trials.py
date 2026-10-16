"""完成会計を試行履歴へ結び、同じ仕様の再実行を防ぐ。売買は再生しない。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'
COMPLETED = {
    '106_往復帯と初期リスク及び再参加の全33対照':'finance/results.json',
    '106_第二段階_場中利益と損失予算の36対照':'finance/session_control_results.json',
    '106_第三段階_進行と進行失敗の固定配分及び小利益終了':'portfolio/results.json',
    '106_E01比較の金額残差許容統一と再開':'e01_reference/結果.json',
    '106_支持破れと相手逆進行の途中返済12対照':'thesis/finance/results.json',
    '106_第五段階_C系と進行失敗の既知開場静観12対照':'time_guard/results.json',
    '106_E01の指値参照値を当時気配へ揃える三対照':'e01_anchor/結果.json',
    '106_E01の小利益目標とUID別場内停止12対照':'e01_daily/finance/結果.json',
    '106_E01待機指値の純価格逆方向取消と小利益停止12対照':'e01_pending_price/finance/結果.json',
    '106_第六段階_旧基準参照ID修正後の純価格26再開':'regime_price/finance/results.json',
    '106_純価格レンジ境界反発と二市場AUTO24対照':'range_price/finance/results.json',
    '106_直近位相によるR入口と方向別待機取消18対照':'local_phase/finance/results.json',
    '106_取引更新代理の入口範囲R_C_BOTH36対照':'trade_gate/finance/results.json',
    '106_E01公開時の取引更新代理と二執行24対照':'e01_trade_gate/finance/結果.json',
    '106_E01取引更新60秒二入口の小利益損失予算18対照':'e01_trade_budget/finance/結果.json',
    '106_E01保有中の逆票と4呼値損失の同時退出6対照':'e01_trade_exit/finance/結果.json',
    '106_E01取引更新二入口の一呼値料金差引目標6対照':'e01_tick_net_goal/finance/結果.json',
    '106_E01最初の実建玉の一呼値常設指値と接触後成行12対照':'e01_resting_takeprofit/finance/結果.json',
    '106_E01既知二票以上の逆票見送り二出口対照':'e01_known_veto/finance/結果.json',
    '106_E01公開時の予定リスク数量と絶対円P1P2_L2四対照':'e01_risk_sizing/finance/結果.json',
    '106_E01予定リスク数量の初回受理目標アンカーP1P2四対照':'e01_size_goal_anchor/finance/結果.json',
    '106_E01予定数量の初回受理損失アンカーP1P2四対照':'e01_size_loss_anchor/finance/結果.json',
}


def main() -> None:
    """
    機能: 合格済み結果の指紋と限界を、登録した同じ試行へ追記する。
    引数: なし。対応IDと完成結果は固定辞書に記録する。
    返り値: None。元台帳を指紋付き履歴へ保持し、状態だけを更新する。
    """
    path = DATA/'trials.json'
    previous = path.read_bytes()
    table = json.loads(previous.decode('utf-8-sig'))
    trials = {row['id']:row for row in table['trials']}
    assert set(COMPLETED).issubset(trials)
    changed = []
    for ident,relative in COMPLETED.items():
        result_path = HERE/relative
        result_bytes = result_path.read_bytes()
        result = json.loads(result_bytes.decode('utf-8-sig'))
        assert result['全合格'] is True
        evidence = dict(path=result_path.relative_to(ROOT).as_posix(),label='完成会計・既知33場',
                        sha256=hashlib.sha256(result_bytes).hexdigest())
        row = trials[ident]
        if row.get('completed_result')==evidence:
            continue
        row['status'] = '検証済み'
        row['completed_result'] = evidence
        row['result'] = '全33場の会計・因果注文検査を完了。両銘柄の全場安定と金額利益80%は未達。保存結果を再利用する。'
        if ident == '106_E01公開時の予定リスク数量と絶対円P1P2_L2四対照':
            row['result'] = '全33場264口座の会計検査を完了。VETO_P2は両商品の最大赤字を平均黒字1場で補えるが、金額利益65%以上と赤字場20%以下は未達。両商品黒字0/4、最新三基準合格0/4。保存結果を再利用する。'
        elif ident == '106_E01予定リスク数量の初回受理目標アンカーP1P2四対照':
            row['result'] = '全33場264口座の会計検査を完了。日経CONFIRM_P1/P2は金額利益65%以上と赤字場20%以下を達成するが、最大赤字1,444円を平均黒字270.5円/402.5円で補えない。TOPIXは全4条件赤字。両商品黒字0/4、最新三基準合格0/4。保存結果を再利用する。'
        elif ident == '106_E01予定数量の初回受理損失アンカーP1P2四対照':
            row['result'] = '全33場264口座を検査。新規数量選択予算を維持して損失停止線だけ初回qへ比例した4条件は両商品とも合計赤字、最新三基準同時合格0/4。日経CONFIRM_P1は最大赤字1,444円→666円だが赤字2場→17場、収支+3,386円→−5,214円。保存GU132を再利用、新GU再計算0。保存結果を再利用する。'
        row.setdefault('evidence',[]).append(evidence)
        row['completion_limitations'] = '条件は既知33場での探索。比較口座は同じ価格経路を共有し独立標本ではない。未知確認0、実注文0。受信時計未保存のため価格時計が代理。'
        changed.append(ident)
    if not changed:
        print('完了登録は既存と同じ。追加更新0。')
        return
    # ----------------------------------------
    # 登録前の履歴を保持し、同一ファイルの一時領域から原子的に更新する。
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    backup = DATA/'history'/('trials_'+hashlib.sha256(previous).hexdigest()+'.json')
    backup.parent.mkdir(exist_ok=True)
    if not backup.exists():
        backup.write_bytes(previous)
    temporary = DATA/'trials_completion.tmp'
    temporary.write_text(json.dumps(table,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    temporary.replace(path)
    proof = dict(全合格=True,完了ID=changed,元台帳SHA256=hashlib.sha256(previous).hexdigest(),
                 更新台帳SHA256=hashlib.sha256(path.read_bytes()).hexdigest(),新金融再生=0)
    (HERE/'試行完了の登録.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('完成した',len(changed),'試行の状態と保存会計を登録。新金融再生0。')


if __name__=='__main__':
    main()
