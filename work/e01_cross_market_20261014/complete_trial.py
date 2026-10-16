"""完成した十六対照だけを共通試行履歴へ結び、再生の重複を防ぐ。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
TRIAL = '104_E01同入口の出口尺度十対照と票強度及び価格応答六対照'
DATA = ROOT/'アルゴリズム調査/00101_共通知見台帳と試行重複の確認/試行照合/data'


def read(path: Path) -> tuple[dict, bytes]:
    """
    機能: 完成小会計と登録台帳を読み、同じバイト列を指紋・履歴へ用いる。
    引数: path(Path) はJSON資料の位置。
    返り値: tuple[dict,bytes] は内容と原バイト列。金融と大型入力を読まない。
    """
    saved = path.read_bytes()
    return json.loads(saved.decode('utf-8-sig')), saved


def main() -> None:
    """
    機能: 検査済み16条件の保存結果を、事前登録した同じ試行へ追記する。
    引数: なし。今回の正式結果・計画・登録IDだけを扱う。
    返り値: None。前台帳を保持し、差がある時だけ原子的に更新する。
    """
    result_path = HERE/'engine/finance/結果.json'
    result, result_bytes = read(result_path)
    fixed, _ = read(HERE/'engine/金融事前固定.json')
    plan, _ = read(HERE/'engine/試行計画.json')
    path = DATA/'trials.json'
    table, previous = read(path)
    assert result['全合格'] and result['source開始終端一致']
    assert len(result['configs']) == 16 and result['会計口座数'] == 1056
    assert result['configs'] == fixed['configs'] == plan['spec']['entry']['conditions']
    assert result['source_SHA256'] == fixed['source_SHA256'] == plan['spec']['implementation']
    matches = [r for r in table['trials'] if r['id'] == TRIAL]
    assert len(matches) == 1 and matches[0]['spec'] == plan['spec']
    row = matches[0]
    evidence = dict(path=result_path.relative_to(ROOT).as_posix(),
        label='同じ既知33場の正式16条件・1056口座', sha256=hashlib.sha256(result_bytes).hexdigest())
    if row.get('completed_result') == evidence:
        print('同じ完成結果の登録済み。追加更新0。')
        return
    assert row['status'] == '未実行'
    row['status'] = '検証済み'
    row['completed_result'] = evidence
    row['result'] = ('旧入口の出口十対照はTOPIX全条件赤字。方向票を0.75へ厳格化したB03のみ両商品三基準に合格。'
        'TOPIX+7342円・7黒字26無取引、日経+2592円・8黒字25無取引。全場の継続黒字は未達。'
        '同じ価格経路を用いた探索であり、将来の損小利大を保証しない。保存結果を再利用する。')
    row.setdefault('evidence', []).append(evidence)
    row['completion_limitations'] = ('16条件は同じ33場を共有する。B03を含む選択は既知データでの事後比較。'
        '無取引は勝ちに含めない。価格時計模型・ラージ気配代理で、実ミニ/マイクロ板と実受信先後は未保証。'
        '今回のAPI・現在入力・実注文・ライブApp変更は0。')

    # ----------------------------------------
    # 共通台帳の変更前を保存し、同じ領域の一時ファイルから差し替える。
    table['updated_at'] = datetime.now(timezone(timedelta(hours=9))).isoformat()
    old_hash = hashlib.sha256(previous).hexdigest()
    history = DATA/'history'/('trials_'+old_hash+'.json')
    history.parent.mkdir(exist_ok=True)
    if not history.exists():
        history.write_bytes(previous)
    temporary = DATA/'trials_104_completion.tmp'
    temporary.write_text(json.dumps(table, ensure_ascii=False, indent=2, allow_nan=False)+'\n',
        encoding='utf-8', newline='\n')
    temporary.replace(path)
    proof = dict(全合格=True, 完了ID=TRIAL, 元台帳SHA256=old_hash,
        更新台帳SHA256=hashlib.sha256(path.read_bytes()).hexdigest(), 完成結果=evidence,
        金融再生=0, API=0, 大型入力読取=0)
    (HERE/'試行完了の登録.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2)+'\n',
        encoding='utf-8', newline='\n')
    print('今回の完成16条件を登録。金融再生0。')


if __name__ == '__main__':
    main()
