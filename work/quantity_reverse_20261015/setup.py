"""旧115を変更せず、買売反転だけの比較源を新しい所有域へ作る。"""

import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OLD = ROOT / 'work/quantity_execution_20261015'


def swap(text: str, before: str, after: str, count: int = 1) -> str:
    """
    機能: 意図した個数だけ存在する文字列を差し替える。
    引数: text/before/after(str)、count(int) は内容と予定箇所数。
    返り値: str は変更後。原115のファイルを上書きしない。
    """
    assert text.count(before) == count, (before, text.count(before))
    return text.replace(before, after)


def main() -> None:
    """
    機能: 反転対照を九源へ接続し、原金融と入力本文を読まず系譜を保存する。
    引数: なし。
    返り値: None。原NPZ・event本文・金融結果は0。
    """
    names = ('catalog.py', 'engine.py', 'artificial.py', 'input_contract.py', 'plan.py',
        'finance.py', 'artificial_root.py', 'metrics/metrics.py', 'metrics/artificial_metrics.py',
        'register.py', 'report.py', 'complete_trial.py')
    before = {}
    for name in names:
        source, target = OLD/name, HERE/name
        assert not target.exists()
        raw = source.read_bytes()
        before[name] = hashlib.sha256(raw).hexdigest()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    p = HERE/'catalog.py'
    s = p.read_text(encoding='utf-8')
    s = swap(s, "TRIAL_ID='115_板の短期方向性を実約定と損益へ接続する十二対照'", "TRIAL_ID='116_同じ板入口の買売方向を反転する十二対照'")
    s = swap(s, "id='QEXEC_'+entry+'_'+exit_id", "id='QREVERSE_'+entry+'_'+exit_id")
    s = swap(s, 'entry_mode=i,exit_mode=j,quantity=dict(CAP)', 'entry_mode=i,exit_mode=j,direction_multiplier=-1,quantity=dict(CAP)')
    p.write_text(s,encoding='utf-8')
    p = HERE/'engine.py'
    s = p.read_text(encoding='utf-8')
    s = swap(s, "if accepted:chosen.append((row,index,d,typ,event[j['episode']]))", "if accepted:chosen.append((row,index,d*config['direction_multiplier'],typ,event[j['episode']]))")
    p.write_text(s,encoding='utf-8')
    p = HERE/'plan.py'
    s = p.read_text(encoding='utf-8')
    s = swap(s,'00115_板の短期方向性を実約定と損益へ接続','00116_全赤字手法の売買反転を同条件で検証')
    s = swap(s,"name='板の一呼値方向を実約定と費用へ接続する十二対照'", "name='同じ板の入口を実売買だけ反転する十二対照'")
    s = swap(s,"question='約80%の一呼値先着を、次raw市場約定と各注文料を負担し2T以上の利確や追尾で収益へ変えられるか。'", "question='115の全33場赤字は、同じ入口審査後に新規の買売を反転し、出口と後続参加を再判定すれば安定した黒字になるか。'")
    s = swap(s,"change='保存114の三入口×四実出口。全量market・半分利確、場純損益停止、寄付静観を同条件で運転。'", "change='115のA/B/Cを元方向で審査し、実売買sideだけ−1。四出口・費用・枚数・約定・時刻・場停止は同じルールで新方向から再運転。'")
    s = swap(s,"repeat_reason='114は価格先着だけで金額未測。113の0/1T FAKは最初の順行を失効させたので、約定選択を市場約定で別検証する。'", "repeat_reason='ユーザーから全赤字なので売買反転してはとの指定。115の損益符号を変えるのでなく、新方向で実約定と出口・busy・場停止を再計算する新条件。'")
    s = swap(s,'compares_to=[], evidence=[]',"compares_to=['115_板の短期方向性を実約定と損益へ接続する十二対照'], evidence=[]")
    s = swap(s,"入口='A初回活動、B初期反対数量を割らずQ0活動へ到達、CはBに当時同方向側数量>=反対数量'", "入口='元proxy方向でA/B/Cを審査後、実注文方向だけ反転。保存eventsとCの元方向数量審査は書換えない'")
    s = s.replace('QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1','QREVERSE_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1')
    p.write_text(s,encoding='utf-8')
    p = HERE/'finance.py'
    s = p.read_text(encoding='utf-8').replace('QEXEC_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1','QREVERSE_C_SAME_SIDE_DEPTH_E4_HALF2_TRAIL1')
    p.write_text(s,encoding='utf-8')
    fixed = OLD/'入力と保存公開の固定.json'
    target = HERE/fixed.name
    assert not target.exists()
    raw = fixed.read_bytes()
    target.write_bytes(raw)
    proof = dict(全合格=True, 元source_SHA256=before,
        既115固定入力の同bytes再利用=dict(path=fixed.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(raw).hexdigest()),
        差分='入口審査は元d、実candidate方向だけ−1。出口と後続参加は新sideで再判定。',
        原NPZ=0, 保存event本文=0, 旧金融結果=0, 新金融=0, API=0)
    p = HERE/'旧源から反転対照を作成した系譜.json'
    assert not p.exists()
    p.write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('原115を変更せず反転対照へコピー。入力本文と金融は0。')


if __name__ == '__main__':
    main()
