"""既存結果の参加頻度を監査し、無取引による評価の歪みを明示する。"""
import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path


def activity(rows):
    """
    機能: 参加頻度と取引した場を分母にした赤字率を計算する。
    引数: rows(list[dict])は同一銘柄・手法・昼夜の保存済み場結果。
    返り値: dictは回数・場数・価格時計基準保有率。新規売買判断はしない。
    """
    full=[r for r in rows if r['complete']]
    active=sum(r['entry_count']>0 for r in full)
    entries=sum(r['entry_count'] for r in full)
    seconds=sum((7 if r['session'].endswith('_Day') else 13)*3600 for r in full)
    holding=sum(r['total_episode_hold_seconds'] for r in full)
    return {'sessions':len(full),'entries':entries,'active':active,'no_trade':len(full)-active,
            'holding_seconds':holding,'holding_percent':100*holding/seconds if seconds else 0,
            'entries_per_session':entries/len(full) if full else 0,
            'negative':sum(r['realized_yen']<0 for r in full),'net':sum(r['realized_yen'] for r in full)}


def update_reports():
    """
    機能: 元集計を変更せず、監査資料・概要冒頭・全候補一覧を更新する。
    引数: なし。入力はR170_001のsummary.jsonと固定選定。
    返り値: dictは固定4枠と表示範囲の監査値。
    """
    here=Path(__file__).resolve().parent;root=here.parents[1]
    study=root/'アルゴリズム調査/00170_複数時間足のテクニカルと指標出口'
    original=here/'summary.json';selection=here/'rootselection.json'
    sealed=json.loads((study/'選定固定.json').read_text(encoding='utf-8'))
    assert hashlib.sha256(original.read_bytes()).hexdigest()==sealed['source_sha256']
    assert hashlib.sha256(selection.read_bytes()).hexdigest()==sealed['selection_sha256']
    data=json.loads(original.read_text(encoding='utf-8'));fixed=json.loads(selection.read_text(encoding='utf-8'))
    groups=defaultdict(list)
    for r in data['results']:groups[(r['symbol'],r['config_id'],r['session'].split('_')[1])].append(r)
    metrics={key:activity(rows) for key,rows in groups.items()};selected=[]
    for g in fixed['selected']:
        m=metrics[(g['symbol'],g['method_id'],g['kind'])]
        selected.append({**g,'activity':m})
    labels={'NK225':'日経','TOPIX':'TOPIX'};kinds={'Day':'日中','Night':'夜間'}
    table=['| 対象 | 手法 | 新規回数 | 取引した場 / 全場 | 無取引場 | 保有時間率 | 赤字場 / 取引した場 |',
           '|---|---|---:|---:|---:|---:|---:|']
    for g in selected:
        m=g['activity']
        table.append(f"| {labels[g['symbol']]}{kinds[g['kind']]} | {g['method_id']} | {m['entries']} | {m['active']} / {m['sessions']} | {m['no_trade']} | {m['holding_percent']:.2f}% | {m['negative']} / {m['active']} |")
    intro=['**訂正：提示した4枠は参加頻度が不足しており、求められた運用候補の提示になっていなかった。**',
           '固定4枠の全114場中、売買したのは47場、無取引67場。各新規はmini10枚固定で、以下は枚数ではなく新規の回数。','',*table,'',
           '保有時間率は予定場時間（日中7時間・夜間13時間）に対する、価格時計上の1枚以上保有した区間の割合。新しい合格基準ではなく活動実態の説明。無取引を含む全場の赤字率だけでは評価しない。',
           '[参加頻度と選定の問題を詳しく確認](取引頻度の監査.md)。元の売買条件・ID・損益・前半固定の選定記録は変更していない。','']
    lines=['# 取引頻度の監査と前回提示の訂正','',*intro,'## なぜこの提示になったか','',
           '順位式は「無取引が一場でもあれば1点」で、2場の無取引も15場の無取引も同じ扱いだった。その後に、無取引の0円を含む赤字場率・収支中央値などを比べた。取引回数や取引した場数の裏付けを採点していなかったため、ほとんど入らない候補を相対上位へ残した。最優先の他の不備数も関係するため、赤字率だけを唯一の原因とはしない。',
           '日経日中の検討期間は17場で5新規・3取引場しかなく、TOPIX日中は17場で3新規・2取引場だった。後半で候補を替えなかったこと自体は維持すべきだが、前半の選定段階で実用候補と呼べる参加頻度かを確認できていなかった。','',
           '## 入口が少ない構造','',
           '- F09は、長期トレンドが上下どちらでもない・ADX20未満・前の1分足がBBの2σ外・今回の足で帯内へ回復・終値の反発を同時に要求する。F03も、レンジ条件とADX非上昇の最中のRSI30上抜けだけで発火する。後から支持が整っても交差し直さなければ入らない。',
           '- 毎場約60～65分の指標準備を要する。ただし活発なF01/F05/F11にも同程度の準備があり、低頻度の差を準備待ちだけでは説明できない。',
           '- 新規は確定1分足の時点だけ。原板更新ごとの判断は返済に限定し、同方向の追加もない。返済後は新たな交差等を待つ。個々の条件の除外件数は今回計測していないため、どの条件が何割を減らしたかまでは断定しない。','',
           '## 72条件とViewer表示対象は異なる','',
           '72条件全体には毎場売買しているものもある。全候補の新規は延べ43,050回だが、重複する仮想候補を足した数であり、一つの運用の活動量ではない。Viewerへ出したのは固定4枠と出口対照だけの285場資料で、そのうち177場資料（62.1%）が無取引だった。',
           '取引を増やしただけの候補を有望とするのも誤りである。以下の事前定義された3系列では毎場取引しているが、収支は赤字だった。後半で勝つものを選び直した表ではない。','',
           '| 比較系列 | 対象 | 新規回数 | 取引した場 / 全場 | 保有時間率 | 収支 |','|---|---|---:|---:|---:|---:|']
    for cid in ['F01A_I','F05A_I','F11A_I']:
        for symbol in ['NK225','TOPIX']:
            for kind in ['Day','Night']:
                m=metrics[(symbol,cid,kind)]
                lines.append(f"| {cid} | {labels[symbol]}{kinds[kind]} | {m['entries']} | {m['active']} / {m['sessions']} | {m['holding_percent']:.2f}% | {m['net']:+,.0f} |")
    lines.extend(['','## 今回修正したこと','',
                  '損益表の全288区分に、取引した場数・無取引場数・保有時間率・取引した場を分母にした赤字場数を追加した。元の損益と固定候補は変えず、提示の不備を明示する。研究の再集計だけで、新しい売買アルゴリズムを改善したことにはしない。',
                  '次の探索では、活動の裏付けがある候補の損失区間を調べ、方向を見定める条件と実際に入る条件を分ける。条件を同時に積んで入口を消すことや、無取引の増加を安定化と扱うことを避ける。新しい売買条件には新IDを与え、後半を見た変更を独立検証と称さない。','',
                  '根拠：固定計画・候補選定・summary.jsonの保存結果。新しい金融再生は行っていない。手数料0、ラージのBBOでmini10枚を評価する共通モデル。',''])
    (study/'取引頻度の監査.md').write_text('\n'.join(lines),encoding='utf-8')
    path=study/'README.md';text=path.read_text(encoding='utf-8')
    begin='<!--参加頻度の監査開始-->';end='<!--参加頻度の監査終了-->'
    if begin in text:
        a=text.index(begin);b=text.index(end,a)+len(end)
        text=text[:a]+text[b:].lstrip('\n')
    title,body=text.split('\n',1)
    path.write_text(title+'\n\n'+begin+'\n'+'\n'.join(intro)+'\n'+end+'\n\n'+body.lstrip('\n'),encoding='utf-8')
    # ----------------------------------------
    # 損益の列を保持し、活動量の列だけを全候補一覧へ追加します。
    path=study/'全候補と損益.md';rows=[];checked=0
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('| 候補・明細'):
            line='|'+'|'.join(line.split('|')[1:10])+'| 取引場 / 全場 | 無取引場 | 保有時間率 | 赤字場 / 取引場 |'
        elif line.startswith('|---'):
            line='|'+'|'.join(line.split('|')[1:10])+'|---:|---:|---:|---:|'
        elif line.startswith('| [F'):
            cells=line.split('|')[1:10];cid=cells[0].strip().split(']')[0][1:]
            symbol='NK225' if cells[1].strip()=='日経' else 'TOPIX'
            kind='Day' if cells[2].strip()=='日中' else 'Night';m=metrics[(symbol,cid,kind)]
            assert int(cells[8].strip().replace(',',''))==m['entries']
            line='|'+'|'.join(cells)+f"| {m['active']} / {m['sessions']} | {m['no_trade']} | {m['holding_percent']:.2f}% | {m['negative']} / {m['active']} |";checked+=1
        rows.append(line)
    assert checked==288
    path.write_text('\n'.join(rows)+'\n',encoding='utf-8')
    shutil.copyfile(here/'activity_audit.py',study/'資料/検証補助/activity_audit.py')
    obj={'固定4候補':selected,'一覧更新区分数':checked,'再生':'なし','元集計指紋':'一致'}
    return obj


if __name__=='__main__':
    report=update_reports()
    print(json.dumps({'固定4新規合計':sum(g['activity']['entries'] for g in report['固定4候補']),'取引場合計':sum(g['activity']['active'] for g in report['固定4候補']),'一覧更新区分数':report['一覧更新区分数']},ensure_ascii=False))
