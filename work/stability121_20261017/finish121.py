"""独立照合済み比較を案内と分類別知見へ反映し、試行状態を閉じる。"""

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from register121 import HERE,ROOT,TRIAL,read,save,sha,MANAGER

NAME='00121_三ポイント間隔と五ポイント追尾'
REPORT='三ポイント間隔と五ポイント追尾の比較.html'
CHART='2026-09-24_Dayの1分足と売買.html'


def prepend(path: Path,marker: str,fragment: str) -> dict:
    """
    機能: 既存先頭見出しの次へ一度だけ案内又は最新指定を挿入する。
    引数: path(Path)は既存文書、marker/fragment(str)は識別子と本文。
    返り値: dictは変更前後の指紋。元本文を削除しない。
    """
    raw=path.read_bytes();text=raw.decode('utf-8')
    assert marker not in text
    pos=text.index('\n')+1
    text=text[:pos]+'\n'+marker+'\n'+fragment+'\n'+text[pos:]
    path.write_bytes(text.encode('utf-8'))
    return dict(path=path.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=sha(path))


def append(path: Path,marker: str,fragment: str) -> dict:
    """
    機能: 新しい法則を出典番号アンカー付きで分類別Markdownへ追加する。
    引数: path(Path)は知見正本、marker/fragment(str)はアンカーと本文。
    返り値: dictは変更前後の指紋。
    """
    raw=path.read_bytes();assert marker.encode('utf-8') not in raw
    path.write_bytes(raw+('\n\n'+marker+'\n\n'+fragment+'\n').encode('utf-8'))
    return dict(path=path.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=sha(path))


def main() -> None:
    """
    機能: 完成金融・監査・公開比較を確認して案内と試行の完了状態を記録する。
    引数: なし。
    返り値: None。市場読取と新規金融は0。
    """
    resultpath=HERE/'三ポイント間隔と五ポイント追尾の全四十場.json'
    auditpath=HERE/'audit/result/三新条件全百二十口座の独立保存会計監査.json'
    assert sha(resultpath)=='ade79de8165fefe68d6f6be861b38f991fc650bb6b658e70329cf667b9bacd1c'
    assert sha(auditpath)=='a972422692008cabae0d1f922da5e5d81101d431e8e9c81e997b4f717afc283c'
    assert read(auditpath)['passed'] is True
    result=read(resultpath)
    assert len(result['runs'])==120 and all(r['unclosed']==0 for r in result['runs'])
    public=ROOT/'アルゴリズム調査'/NAME
    assert (public/REPORT).is_file() and (public/CHART).is_file()
    changes=[]

    # ----------------------------------------
    # 新しい作業への導線を追加し、旧公開物と旧研究内容を維持する。
    for path,prefix in [(ROOT/'README.md','アルゴリズム調査/'),(ROOT/'アルゴリズム調査/README.md','')]:
        changes.append(prepend(path,'<!--00121案内-->',
            f'最新：[00121：3pt間隔・5pt追尾と利確後再起算]({prefix}{NAME}/{REPORT})。TOPIX新3条件・全40場を比較。[9月24日の1分足と売買]({prefix}{NAME}/{CHART})。提案は8黒字32赤字で安定黒字には未達。\n<!--00121案内終了-->'))
    index=ROOT/'アルゴリズム調査/index.html';raw=index.read_bytes();text=raw.decode('utf-8')
    assert '<!--00121開始-->' not in text
    match=re.search(r'<main\b[^>]*>',text);assert match
    card=f'''\n<!--00121開始--><article class="task latest"><div class="number">作業00121・3pt間隔と5pt追尾</div><h2>利確後の次新規を＋3ptへ戻す比較</h2><p>TOPIXの新3条件と保存基準を全40場で比較。提案は8黒字32赤字。</p><a class="button" href="{NAME}/{REPORT}">比較と全40場</a> <a href="{NAME}/{CHART}">9月24日の1分足と売買</a> <a href="{NAME}/README.md">読む順序</a></article><!--00121終了-->\n'''
    text=text[:match.end()]+card+text[match.end():];index.write_bytes(text.encode('utf-8'))
    changes.append(dict(path=index.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=sha(index)))

    # ----------------------------------------
    # 金額の結論と限定された法則を、共通の分類別Markdownへ保存する。
    common=ROOT/'アルゴリズム調査/共通/知見台帳'
    changes.append(prepend(common/'README.md','<!--00121案内-->',
        f'最新は[00121：3pt間隔と5pt追尾](../../{NAME}/README.md)。TOPIXで利確幅の拡大と、利確後の新規段数再起算を分けて確認。出口と入口へ数値・適用範囲を記録しました。\n<!--00121案内終了-->'))
    source=f'**出典：** [00121_三ポイント間隔と五ポイント追尾](../../{NAME}/README.md)。[比較と全40場](../../{NAME}/{REPORT})。'
    changes.append(append(common/'出口.md','<a id="00121_一ポイント追尾を五ポイントへ広げた効果"></a>',
        '## 個別追尾を1ptから5ptへ広げると回転は減ったが、負け玉の蓄積は消えなかった\n\n'+source+'\n\n'
        '**当時条件：** TOPIXミニ片方向最大10枚。Last極値から3・4・5…ptの上下対称新規を固定し、利益玉の最高費用後純益からの戻り幅だけ1pt→5ptへ変更。戻り時点の純益が正なら次気配返済。負け玉へ独立損切りなし、全玉場内返済。旧基準の場初比から丸めた単位は全40場で1ptと確認し、その完成会計を再利用。\n\n'
        '**分母・実測：** 同じ既知40場。1ptは4黒字36赤字・合計−3,368,506円、中央値−82,405円、累計5,183枚。5ptは9黒字31赤字・−2,762,030円、中央値−61,096円、累計2,415枚。9月24日デイは−68,472円→−39,912円。5pt同場の売り側は＋219,900円へ増えた一方、買い側−259,812円で赤字が残った。\n\n'
        '**使える範囲・限界：** この幅の拡大は全運転の損失を縮めたが、場の安定黒字を達成したとはしない。出口変更により後続の新規・手数料・残在庫も変わるため、同じ固定取引の利益延長だけを測った値ではない。日経は今回未検証。未知相場の適切幅を5ptと確定するものではない。'))
    changes.append(append(common/'入口.md','<a id="00121_利確後の三ポイント再起算は逆行側の玉も増やした"></a>',
        '## 利確後の次新規を＋3ptへ戻すと、下落中の反発でも買い直しが繰り返された\n\n'+source+'\n\n'
        '**当時条件：** 新規3・6・9…pt、個別5pt利益追尾を共通とし、返済した固定段だけを再利用する対照と、実利確した方向の空き段を現在Lastから＋3pt（売りは−3pt）へ振り直す提案を比較。保有建値は不変、既新規予約は取消、同原行の同方向新規禁止。買い・売りを独立更新する。\n\n'
        '**分母・実測：** 同じTOPIX40場で段数維持は5黒字35赤字・合計−1,798,106円、再起算は8黒字32赤字・−2,531,804円。黒字場は3増えたが、合計と最悪場（−200,838円→−384,428円）は悪化した。9月24日は−56,026円→−91,002円。提案の同場は売り＋143,302円、買い−234,304円、場末の買い10枚の損失−249,820円。\n\n'
        '**具体箇所：** 09:35:50に買い3玉を合計＋1,254円利確した後、次新規を＋3ptへ再準備。09:36:34買4,083は15:20:01の4,061.5返済で−21,582円。同様に09:39:24買4,084.5、09:47:43買4,083も早い段（rank0/1）で建ち、−23,082円・−21,582円。固定枠との入口照合は方向・判断原行・約定原行・建値を用い、UID番号や段番号だけで共通玉と新規玉を取り違えない。小反発で再参加する機会が増えても、その後の大方向を正しく判定したことにはならない。\n\n'
        '**限界：** 固定段との全運転比較であり、挙げた三玉だけを取り除いた収支ではない。再起算後は後続の利確・新規も変わる。両方式とも全40場合計赤字で、再起算一般の否定や他銘柄への結論にはしない。'))
    changes.append(prepend(ROOT/'アルゴリズム調査/調査方針.md','<!--00121最新指定-->',
        '## 2026年10月17日のTOPIXの段間隔と追尾幅の明確化\n\nユーザーは1pt追尾が狭すぎると指摘し、追跡安値から3・6・9・12…ptで新規、売りは上下対称、最高益から5pt戻りかつ利益の残る玉だけ返済、利確後は次の新規段数を＋3ptから再起算する意図を明示した。00121では利確方向の未約定列だけを現在Lastから再準備し、保有建値と反対方向は維持する。固定枠再利用との違いも対照にしてTOPIX40場で検証した。既知40場の開発であり、日経は本比較では未測定。\n<!--00121最新指定終了-->'))

    # ----------------------------------------
    # この試行だけを完了へ変更し、旧試行の意味内容が不変なことを確認する。
    ledger=MANAGER.parent/'data/trials.json';oldraw=ledger.read_bytes();registry=json.loads(oldraw)
    untouched={r['id']:json.dumps(r,ensure_ascii=False,sort_keys=True) for r in registry['trials'] if r['id']!=TRIAL}
    row=next(r for r in registry['trials'] if r['id']==TRIAL)
    assert row['status']=='未実行'
    save(HERE/'試行終了前の登録行.json',row)
    record=dict(path=resultpath.relative_to(ROOT).as_posix(),sha256=sha(resultpath))
    audits=[dict(path=auditpath.relative_to(ROOT).as_posix(),sha256=sha(auditpath)),
        dict(path=(HERE/'adversary/固定段間隔と方向別再割当の独立人工.json').relative_to(ROOT).as_posix(),
             sha256=sha(HERE/'adversary/固定段間隔と方向別再割当の独立人工.json'))]
    accounting=dict(financial_accounts=120,reused_baseline_accounts=40,stored_price_inputs=40,raw_market_reads=0,
        unclosed_lots=0,previous_financial_replay=0,real_orders=0,current_API=0)
    row.update(status='検証完了',completed_result=record,completed_audits=audits,
        completed_registered_sources=read(HERE/'固定計画.json')['sources'],
        completed_fixed=dict(path=(HERE/'固定計画.json').relative_to(ROOT).as_posix(),sha256=sha(HERE/'固定計画.json')),
        completion_accounting=accounting,result='TOPIX新三条件120会計を全40場で完了。提案8黒字32赤字、合計−2,531,804円で安定黒字は未達。旧基準40会計は再利用。',
        readme=f'アルゴリズム調査/{NAME}/README.md',report=f'アルゴリズム調査/{NAME}/{REPORT}',
        completion_limitations='同じ既知40場の開発。日経は今回未検証。ラージBBO代理で実ミニ板・真受信順・待ち順位は未観測。',
        execution_attempts=[dict(status='検証完了',result=record,accounting=accounting,independent_evidence=False)])
    assert untouched=={r['id']:json.dumps(r,ensure_ascii=False,sort_keys=True) for r in registry['trials'] if r['id']!=TRIAL}
    history=MANAGER.parent/'data/history/00121_終了前の試行台帳.json'
    assert not history.exists();history.write_bytes(oldraw)
    registry['updated_at']=datetime.now(timezone.utc).isoformat()
    ledger.write_text(json.dumps(registry,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    process=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),'build'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    save(HERE/'試行終了後の閲覧同期.json',dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
    assert process.returncode==0,process.stderr[-2000:]
    save(HERE/'案内と知見及び試行終了の反映.json',dict(passed=True,changes=changes,financial_accounts=0,
        old_trials_unchanged=True,completed_trial=TRIAL,report_sha256=sha(public/REPORT),chart_sha256=sha(public/CHART)))
    print('案内・入口/出口の知見・ユーザー指定・試行完了を反映。追加金融0。',flush=True)


if __name__=='__main__':
    main()
