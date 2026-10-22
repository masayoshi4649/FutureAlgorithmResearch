"""利確なし比較を案内と知見に残し、通常返済と終端代理を区別して完了する。"""

from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from register122 import HERE,ROOT,MANAGER,TRIAL,read,save,sha

sys.path.insert(0,str(HERE.parent/'stability121_20261017'))
from finish121 import prepend,append

NAME='00122_途中利確なしと引け一括精算'
REPORT='途中利確なしと引け一括の比較.html'


def main() -> None:
    """
    機能: 独立照合済み80会計を案内・分類別知見・試行状態へ反映する。
    引数: なし。
    返り値: None。新しい市場読取・金融再生は行わない。
    """
    resultpath=HERE/'途中利確なしと引け一括の全四十場.json'
    auditpath=HERE/'audit/result/八十通常及び代理終端会計の独立監査.json'
    assert sha(resultpath)=='ea3632b2e7bf2e9eb3e73addfede7f87deda0069efb30e4a3fd2647550dbab72'
    assert sha(auditpath)=='91702da0011b1283746812e9487eeac45264346c3aa4e791ba8203d345829913'
    assert read(auditpath)['passed'] is True
    result=read(resultpath);fixed=read(HERE/'固定計画.json')
    assert len(result['runs'])==80 and all(r['unclosed']==0 for r in result['runs'])
    for path,value in fixed['sources'].items():assert sha(ROOT/path)==value,path
    public=ROOT/'アルゴリズム調査'/NAME
    assert (public/REPORT).is_file()
    save(public/'再現用参照.json',dict(result=str(resultpath.relative_to(ROOT)),sha256=sha(resultpath),
        audit=str(auditpath.relative_to(ROOT)),audit_sha256=sha(auditpath),financial_replay=0))
    text='''# 途中利確なしと引け一括精算

最初に[比較と全40セッションの損益](途中利確なしと引け一括の比較.html)を開いてください。

TOPIXミニ片方向最大10枚。追跡安値から3・6・9…pt反発で一枚ずつ買い、売りは上下対称。途中の利確・損切りを全て行わず、Day15:45／Night06:00に一括精算する仮定です。新規締切は比較元と同じ15:00／05:20に固定しました。利確が無いので途中の段数再起算もありません。

**ユーザーの指定に従い、終値が無い場は引け前6分以内の最後の有効BBOを終値代用にしています。全40場で実際の参照値は引け301〜359秒前です。実引けの約定記録ではありません。**

9月24日デイは＋91,188円。売り9枚＋276,262円に対し買い7枚−185,074円でした。15:39:58のbid4058.5／ask4059.0を使用し、往復手数料は16枚で1,312円。同じ玉をLast4056で評価した参考収支は＋100,688円です。

全40場では11黒字29赤字・合計−1,031,046円。旧5pt追尾・再起算の−2,531,804円から改善しましたが、安定黒字には未達です。途中利確なしで15:20／05:40に通常返済する対照は14黒字26赤字・−573,046円。同じ保有玉を終端Lastで評価した感応度は14黒字26赤字・−287,546円で、別戦略の成績へ数えません。

早期返済と引け代理の収支差−458,000円は、Lastの変化＋69,500円と、返済側BBO対Lastの乖離変化−527,500円に分解できました。後者には気配幅の変化−315,500円と中値対Lastの乖離変化−212,000円を含み、全てを手数料や単純な逆行のせいにはしません。

新二条件80会計を事前登録し、全注文・全玉・費用・時価・DD・上限と終端代理を独立照合。旧基準40会計は再利用しています。全て同じ既知40場の開発です。日経は今回は未検証。資料範囲確認だけ9月24日元板末尾2MiBを読み、金融工程の元板読取・現在API・実注文は0です。

実装：[終了会計](../../work/stability122_20261017/engine122.py)、[固定計画](../../work/stability122_20261017/固定計画.json)、[独立80会計監査](../../work/stability122_20261017/audit/result/八十通常及び代理終端会計の独立監査.json)。
'''
    assert not (public/'README.md').exists();(public/'README.md').write_bytes(text.encode('utf-8'))
    changes=[]

    # ----------------------------------------
    # 最新比較の入口だけを追加し、過去研究の表示と金融結果を上書きしない。
    for path,prefix in [(ROOT/'README.md','アルゴリズム調査/'),(ROOT/'アルゴリズム調査/README.md','')]:
        changes.append(prepend(path,'<!--00122案内-->',
            f'最新：[00122：途中利確なしと引け一括精算]({prefix}{NAME}/{REPORT})。TOPIXは9月24日＋91,188円、全40場11黒字29赤字。15:45／06:00の直前6分BBOを終値代用した比較です。\n<!--00122案内終了-->'))
    index=ROOT/'アルゴリズム調査/index.html';raw=index.read_bytes();body=raw.decode('utf-8')
    assert '<!--00122開始-->' not in body
    match=re.search(r'<main\b[^>]*>',body);assert match
    card=f'''\n<!--00122開始--><article class="task latest"><div class="number">作業00122・途中利確なし</div><h2>全玉を引けまで保持する比較</h2><p>TOPIXは9月24日＋91,188円、全40場11黒字29赤字。引け前6分BBOの終値代用を明記しています。</p><a class="button" href="{NAME}/{REPORT}">比較と全40場</a> <a href="{NAME}/README.md">読む順序</a></article><!--00122終了-->\n'''
    body=body[:match.end()]+card+body[match.end():];index.write_bytes(body.encode('utf-8'))
    changes.append(dict(path=index.relative_to(ROOT).as_posix(),before_sha256=hashlib.sha256(raw).hexdigest(),after_sha256=sha(index)))

    # ----------------------------------------
    # 出口の効果と、異なる終端価格を混同しない計測上の知見を分類して残す。
    common=ROOT/'アルゴリズム調査/共通/知見台帳'
    changes.append(prepend(common/'README.md','<!--00122案内-->',
        f'最新は[00122：途中利確なしと引け一括](../../{NAME}/README.md)。売りカバーを残した一場の改善と全40場の成績、引け前6分の代理価格の扱いを出口・売買の工夫へ記録しました。\n<!--00122案内終了-->'))
    source=f'**出典：** [00122_途中利確なしと引け一括精算](../../{NAME}/README.md)。[比較と全40場](../../{NAME}/{REPORT})。'
    changes.append(append(common/'出口.md','<a id="00122_利益玉を引けまで残すと一場は救えたが全場黒字ではない"></a>',
        '## 利益玉を引けまで残すと9月24日は黒字になったが、全40場では赤字が残った\n\n'+source+'\n\n'
        '**当時条件：** TOPIXミニ片方向10枚、動くLast極値から3・6・9…ptの上下対称新規。新規締切15:00／05:20は共通とし、途中返済を完全停止。通常15:20／05:40返済と、予定15:45／06:00の引け前6分以内BBOによる代理精算を比較。旧5pt追尾・利確後再起算は完成結果を再利用。\n\n'
        '**分母・実測：** 同じ40場で旧型8黒字32赤字・−2,531,804円。途中利確なしの早返済は14黒字26赤字・−573,046円、引け代理は11黒字29赤字・−1,031,046円。新規は両終了法で全列同値、累計各653枚。引け代理の9月24日は売り9枚＋276,262円、買い7枚−185,074円で＋91,188円（旧−91,002円）。早返済同場＋85,188円との差＋6,000円は、同じ玉をさらに保持した終端価格差である。\n\n'
        '**終端差の会計分解：** 同じ653入口・手数料各53,546円で引け代理−早返済は−458,000円。Last移動による差は＋69,500円、返済側BBO対Lastの乖離変化は−527,500円（気配幅拡縮−315,500円、中値対Lastの乖離変化−212,000円）。これは保存価格の算術分解で、気配変化の市場要因や実際の約定可能性を同定したものではない。\n\n'
        '**使える範囲・限界：** 勝ちカバーを早く外す損失は一場で改善したが、保持し続けるだけで全場安定黒字にはならなかった。代理は全40場で実引け301〜359秒前の気配を使うユーザー許可の仮定。実引け約定・残り数分のDDを証明しない。日経は今回未検証。'))
    changes.append(append(common/'売買の工夫.md','<a id="00122_引け代理は予定時刻と参照時計を分ける"></a>',
        '## 引け代理は予定時刻と参照原行を分け、同じ価格時計の別気配を統合しない\n\n'+source+'\n\n'
        '**条件・分母：** ユーザーが引け終値不明時は直前6分を許可。TOPIX40場の正常受理原行についてT−360秒以上T以下の最後のBBOを代理終了会計へ使用し、途中の新規判断へ逆流させない。全40場は窓内にあり、引け同時刻0/40、参照は301〜359秒前。通常の次原行返済と専用proxy_lots台帳を分け、予定Tと参照原行・価格時計を両方保存した。\n\n'
        '**具体例：** 9月24日デイの保存入力最終は15:39:58、Last4056・bid4058.5／ask4059.0。元板末尾には同じ価格時計の別原行で4062／4062もある。正常入力の代理気配へ後者を差し替えない。BBO代理の全玉収支＋91,188円に対し、同じ玉をLastで評価した参考は＋100,688円。\n\n'
        '**価格感応度：** 同じ40玉群の全BBO代理合計−1,031,046円、全Last終端評価の参考合計−287,546円。両者を追加の独立戦略・約定実績へ数えない。価格時計はBBO全体の受信時刻ではなく、代理の許可で真受信順・実ミニ板・引け約定が観測済みになるものでもない。窓外の場合は未測定とし最終値へ置換しない。'))
    changes.append(prepend(ROOT/'アルゴリズム調査/調査方針.md','<!--00122最新指定-->',
        '## 2026年10月17日の途中利確廃止と引け一括精算\n\nユーザーは途中利確を全廃しDay15:45／Night06:00に一括精算する比較を指定。終値不明なら直前6分以内の値でよいと明示した。00122では同じ新規条件・締切を維持し、引け前6分以内の最終正常BBOを終値代理とする会計を通常次原行約定から分ける。予定精算時刻と参照原行・価格時計を併記し、実引け約定と呼ばない。\n<!--00122最新指定終了-->'))

    # ----------------------------------------
    # この登録だけを完了へ進め、旧試行と旧表示の意味内容を維持する。
    ledger=MANAGER.parent/'data/trials.json';oldraw=ledger.read_bytes();data=json.loads(oldraw)
    old={r['id']:json.dumps(r,ensure_ascii=False,sort_keys=True) for r in data['trials'] if r['id']!=TRIAL}
    row=next(r for r in data['trials'] if r['id']==TRIAL);assert row['status']=='未実行'
    save(HERE/'試行終了前の登録行.json',row)
    ref=dict(path=resultpath.relative_to(ROOT).as_posix(),sha256=sha(resultpath))
    accounting=dict(financial_accounts=80,normal_accounts=40,proxy_accounts=40,reused_baseline_accounts=40,
        raw_market_reads_during_financial=0,coverage_raw_tail_reads=1,unclosed_after_proxy=0,
        previous_financial_replay=0,real_orders=0,current_API=0)
    row.update(status='検証完了',completed_result=ref,
        completed_audits=[dict(path=auditpath.relative_to(ROOT).as_posix(),sha256=sha(auditpath))],
        completed_registered_sources=fixed['sources'],completed_fixed=dict(path=(HERE/'固定計画.json').relative_to(ROOT).as_posix(),sha256=sha(HERE/'固定計画.json')),
        completion_accounting=accounting,result='途中利確なし二終端80会計を完成。引け代理40場は11黒字29赤字・−1,031,046円。9月24日は＋91,188円へ改善。全場安定黒字には未達。',
        readme=f'アルゴリズム調査/{NAME}/README.md',report=f'アルゴリズム調査/{NAME}/{REPORT}',
        completion_limitations='全40引けが終値代理で実引け約定ではない。同じ既知40場。日経未検証。Last終端評価は同じ玉の感応度で追加戦略の独立成績へ数えない。',
        execution_attempts=[dict(status='検証完了',result=ref,accounting=accounting,independent_evidence=False)])
    assert old=={r['id']:json.dumps(r,ensure_ascii=False,sort_keys=True) for r in data['trials'] if r['id']!=TRIAL}
    history=MANAGER.parent/'data/history/00122_終了前の試行台帳.json';assert not history.exists();history.write_bytes(oldraw)
    data['updated_at']=datetime.now(timezone.utc).isoformat()
    ledger.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    process=subprocess.run([sys.executable,'-B','-X','utf8',str(MANAGER),'build'],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
    save(HERE/'試行終了後の閲覧同期.json',dict(終了コード=process.returncode,stdout=process.stdout,stderr=process.stderr))
    assert process.returncode==0,process.stderr[-1000:]
    save(HERE/'案内と分類別知見及び試行終了.json',dict(passed=True,changes=changes,old_trials_unchanged=True,
        completed_trial=TRIAL,report_sha256=sha(public/REPORT),new_financial_replay=0))
    print('通常返済と引け代理を区別して、案内・知見・試行完了を反映。',flush=True)


if __name__=='__main__':
    main()
