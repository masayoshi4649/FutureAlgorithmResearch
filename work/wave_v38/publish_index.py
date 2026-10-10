"""完了した比較・損益・売買図への入口を一つにまとめる。"""

import re
import report_adaptive as report


def main() -> None:
    """機能: 検算完了後に読む順序と最新リンクを更新する。

    引数: なし。返り値: なし (None)。完備前の採用宣言はしない。
    """
    runner=report.runner;here=runner.HERE;out=report.OUT;title=report.TITLE
    proof=runner.read(here/'経済完備監査.json');assert proof['経済検証完了']
    assert proof['実装状態契約合格'] is False
    verdict=runner.read(here/'独立判定.json')
    for name in (title+'.html','全条件損益.html','５分足と売買.html'):assert (out/name).exists()
    conclusion=('基礎候補は残りました。' if verdict['基礎候補'] else '主案は基礎候補未達でした。')
    conclusion+=('復元方式の使い分けにも利益を増やす効果がありました。' if verdict['分岐の利益付加価値'] else '復元方式の使い分けが固定方式を上回る証拠は不足しました。')
    readme=f'''# {title}

最初に [{title}]({title}.html) を見てください。{conclusion}

読む順序：

1. [比較と結論]({title}.html) — 主案・固定回復・固定時計・逆分岐・元方式。
2. [全974条件の損益](全条件損益.html) — 手法説明、各週・各セッションの利益／損失／収支、勝ち／負け／同値決済枚数。
3. [5分足と売買](５分足と売買.html) — 固定6方式×26市場セッション、エントリー・返済・減量・復元・選択理由。
4. [判定の全内訳](../../work/wave_v38/独立判定.json) — 基礎候補・14感度・使い分けの価値を別判定。
5. [経済完備監査](../../work/wave_v38/経済完備監査.json) — 全25,324入力会計、3,918入力因果、7,792波区間の独立確認。
6. [状態不具合](../../work/wave_v38/状態残存の契約違反と経済影響.md) — 取消済み予約表示の12行残存。経済検証と実装状態契約の未合格を分離。

全13セッションは既知で、後半7も未知ではありません。旧8候補は前回309から選んだ条件です。初回はTOPIXミニ5枚／NKマイクロ10枚、片方向上限10／20枚。先物価格で換算し、費用0・指定価格約定・場内全返済です。延べ決済枚数は同時保有数ではありません。

## 再現

作業ルートから以下の順序です。実行は既存保存データだけを使用します。

```powershell
$env:PYTHONIOENCODING='utf-8'
python work/wave_v38/adaptive_runner.py --workers 8
python work/wave_v38/adaptive_cash_revision_guard.py
python work/wave_v38/adaptive_runner.py --supplementary --workers 8
python work/wave_v38/adaptive_accounting_diagnostic.py --workers 8
python work/wave_v38/adaptive_accounting_diagnostic.py --supplementary --workers 8
python work/wave_v38/adaptive_causality_audit.py --workers 4
python work/wave_v38/adaptive_causality_audit.py --supplementary --workers 4
python work/wave_v38/adaptive_wave_audit.py --workers 4
python work/wave_v38/adaptive_wave_audit.py --supplementary --workers 4
python work/wave_v38/assess_results.py
python work/wave_v38/economic_completion_guard.py
python work/wave_v38/report_adaptive.py
```

## 初回会計検査の限定補正

初回再生は、1秒遅延の15:35:01返済を旧会計が15:35:00で残玉ありと誤検知して中断しました。売買・損益算術・入力・採否を変えず、会計の場末2検査領域だけを固定契約へ合わせました。全974を再計算し、旧158条件の790資料と全台帳・経済値が一致しました。

- [障害の限定再現](../../work/wave_v38/adaptive_cash_revision_failure_v1.json)
- [独立した場末境界の確認](../../work/wave_v38/adaptive_close_boundary_review.md)
- [旧資料の保存と比較規則](../../work/wave_v38/adaptive_cash_revision_plan.json)
- [新旧158条件の一致](../../work/wave_v38/adaptive_cash_revision_results.json)
- [次の独立仮説候補](../../work/wave_v38/次の独立仮説候補.md) — 設計時点の資料。板残差は後続00034で検証し、今回の判定へは混ぜていません。
- [一次文献との接続](../../work/wave_v38/次の独立仮説_文献確認.md)

## 状態契約は未合格

注文遅延15秒の1条件で、全返済予約が減量予約を取り消しても、状態表示だけが12行残る不具合を検出しました。原監査はこれを不合格にして停止し、205条件は全検査に合格しました。監査の期待値を残存表示へ合わせず、別の診断版で全注文・会計の検算と状態違反の記録を分離しています。

元の実装・損益・固定条件は保存し、現版を完全合格や実運用可能とは扱っていません。未採用の修正版候補は、810人工入力で状態以外の全出力が同値ですが、全実相場の修正版再生は未実施です。

- [全範囲診断の主集約](../../work/wave_v38/adaptive_accounting_diagnostic.json)
- [補助768条件の集約](../../work/wave_v38/supplementary/adaptive_accounting_diagnostic.json)
- [原版失敗と成功205条件の保存](../../work/wave_v38/adaptive_accounting_failed_run.json)
- [今回の到達点](../../work/wave_v38/今回の到達点.md)
'''
    (out/'README.md').write_text(readme,encoding='utf-8')
    path=out.parent/'index.html';text=path.read_text(encoding='utf-8')
    text=re.sub(r'<!--00033開始-->.*?<!--00033終了-->','',text,flags=re.S)
    text=text.replace('task latest','task')
    text=re.sub(r' <span class="badge">最新[^<]*</span>','',text)
    text=re.sub(r'<p class="lead">.*?</p>','<p class="lead">最新00033：974条件の経済検算完了、状態実装は未合格。'+conclusion+'</p>',text,count=1)
    block=f'''<!--00033開始--><article class="task latest"><div class="number">作業00033 <span class="badge">最新・経済検算完了</span></div><h2>{title}</h2><p>{conclusion} 状態実装の不具合は未合格として記録。</p><a class="button" href="{out.name}/{title}.html">比較と結論 →</a><a class="button" href="{out.name}/全条件損益.html">各週・各セッションの損益 →</a><p><a href="{out.name}/５分足と売買.html">5分足と売買</a> ／ <a href="{out.name}/README.md">資料案内</a></p></article><!--00033終了-->'''
    path.write_text(text.replace('</header>','</header>'+block,1),encoding='utf-8')
    path=out.parent/'README.md';text=path.read_text(encoding='utf-8')
    text=re.sub(r'\*\*最新は.*?\*\*',f'**最新は00033の[{title}]({out.name}/{title}.html)（974条件の経済検算完了、状態実装は未合格）。**',text,count=1)
    text=re.sub(r'^\| `00033_.*\n','',text,flags=re.M).replace('`（最新）','`')
    row=f'\n| `{out.name}`（最新） | {conclusion} | [比較と結論]({out.name}/{title}.html) | [全損益]({out.name}/全条件損益.html)・[売買図]({out.name}/５分足と売買.html)・[資料案内]({out.name}/README.md) |'
    path.write_text(text.replace('| --- | --- | --- | --- |','| --- | --- | --- | --- |'+row,1),encoding='utf-8')
    print('最新00033の入口と読む順序を更新。')


if __name__=='__main__':main()
