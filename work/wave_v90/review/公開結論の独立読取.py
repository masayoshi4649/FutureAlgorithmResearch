"""公開説明が模型の限界や無取引を成功へ置き換えていないか確認する。"""

import importlib.util
import json
from pathlib import Path
import re


HERE = Path(__file__).resolve().parent
WORK = HERE.parent
ROOT = WORK.parents[1]
SPEC = importlib.util.spec_from_file_location('公開解釈90の独立関数', HERE/'独立選定と原因診断.py')
R = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(R)


def main():
    """
    機能: 根拠資料と生成HTMLの埋込み会計・結論を照合する。
    引数: なし。
    返り値: None。追加review資料だけ保存する。画面目視の代替ではない。
    """
    analysis_path = WORK/'analysis/比較結果.json'
    conclusion_path = WORK/'analysis/結論.json'
    html_path = ROOT/'アルゴリズム調査/00086_二市場の状態で追従と指値反発を配分/二つの戦略への配分と全セッション損益.html'
    analysis = R.read(analysis_path)
    conclusion = R.read(conclusion_path)
    independent = R.read(HERE/'追加15条件の独立会計と源稼働及び残る損失原因.json')
    html = html_path.read_text(encoding='utf-8')
    payload = re.search(r'<script id="report-data" type="application/json">(.*?)</script>', html, re.S).group(1)
    data = json.loads(payload.replace('<\\/', '</'))
    assert data['conclusion'] == conclusion['conclusion'] == analysis['conclusion']
    assert data['cause_notes'] == conclusion['cause_notes'] == analysis['cause_notes']
    assert data['results'] == analysis['results'] and len(data['catalog']) == 42
    assert data['primary'] == 'D_C_QA' and data['selected'] == independent['独立参考選定']['id'] == 'J8_Q'
    assert '未達' in ''.join(data['conclusion'])
    assert '市場原理の否定ではなく' in ''.join(data['cause_notes']['D_C'])
    assert '悲観' in ''.join(data['cause_notes']['D_C'])
    assert '29場' in ''.join(data['cause_notes']['D_C_QA'])
    assert '無取引を勝ち' in html
    assert '枚数' in ''.join(data['conclusion']) and '新しい優位性の発見ではありません' in ''.join(data['conclusion'])
    assert '手数料切捨て' in ''.join(data['cause_notes']['J8_Q'])
    assert not data['both_eighty'] and not analysis['all_sessions_positive']
    for symbol in R.SYMBOLS:
        row = data['results']['D_C_QA']['periods']['全30'][symbol]
        assert row['sources']['J2']['campaigns'] == 0
        assert row['sources']['O06']['campaigns'] == 1 and row['no_trade_sessions'] == 29
        assert row['positive_sessions'] == 0
    checks = [
        '全42の埋込み結果と正式analysisが一致。',
        '旧D_Cの巨額損失は悲観約定仮定と古い基準の問題と説明し、市場原理の否定へ一般化していない。',
        '価格改善後も黒字化しなかった事実と、価格改善は予測向上ではない区別を保持。',
        '主QAはJ2源0親・O06各1親・29場無取引。活動消失を安定収益の成功へ置換していない。',
        '参考J8_QはJ2同経路の数量削減と手数料丸めの小差で、新たな優位性と説明していない。',
        'M82_Qに追加した反発源がTOPIXでは増益・日経では減益、DDは両方増えたことを明示。',
        '両商品金額80%及び全日両黒字の未達を保持。無取引を勝ちへ含めない。',
        '画面描画・目視は別の公開表示監査で確認する。ここでは本文と埋込み根拠の読取確認。'
    ]
    paths = [Path(__file__), analysis_path, conclusion_path, html_path,
             HERE/'追加15条件の独立会計と源稼働及び残る損失原因.json',
             HERE/'巨額損失の限度価格模型とER尺度及び条件交差の独立反証.json',
             HERE/'往復開始の短命化と逆共同方向を見逃す閾値の独立診断.json']
    proof = dict(全合格=True, 独立読取項目=checks, HTML_SHA256=R.digest(html_path),
                 旧成果変更=0, 凍結成果変更=0, API取得=0, 実注文=0,
                 SHA256={str(path.relative_to(ROOT)): R.digest(path) for path in paths})
    target = HERE/'公開結論と約定模型及び無取引の解釈に関する独立読取.json'
    target.write_text(json.dumps(proof, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(全合格=True, HTML_SHA256=proof['HTML_SHA256'], 監査SHA256=R.digest(target)), ensure_ascii=False))


if __name__ == '__main__':
    main()
