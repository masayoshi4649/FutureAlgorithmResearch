"""四段階の完成した実会計版を保全し、短い結論と全場表を公開する。"""

import hashlib
import html
import json
from pathlib import Path
import shutil


HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
NAME='00120_段階トレーリング新規と利益玉の部分回転'
PUBLIC=ROOT/'アルゴリズム調査'/NAME
MAIN='段階トレーリングの結論と全セッション損益.html'


def digest(payload: bytes) -> str:
    """
    機能: コピーする実成果の指紋を照合する。
    引数: payload(bytes)は既に読んだ完成成果。
    返り値: strはSHA256。
    """
    return hashlib.sha256(payload).hexdigest()


def esc(value) -> str:
    """
    機能: 文字列やIDを安全にHTMLへ表示する。
    引数: value(任意型)は表示値。
    返り値: strはHTMLエスケープ済み文字列。
    """
    return html.escape(str(value))


def money(value: float) -> str:
    """
    機能: 円額を符号付きで読みやすく整える。
    引数: value(float)は保存済み金額。
    返り値: strは円表記。再金融計算を行わない。
    """
    return f'{value:+,.0f}' if value else '0'


def main() -> None:
    """
    機能: 四実表示と独立監査の完成後だけ、成果を別作業へ公開する。
    引数: なし。根の公開根拠目録に固定したb/c/d/e指紋だけを採用する。
    返り値: None。合成・途中停止・未実行を正式成績へ加えない。
    """
    manifest=json.loads((HERE/'公開根拠目録.json').read_text(encoding='utf-8'))
    assert manifest['root_checked'] is True and len(manifest['phases'])==4
    assert [(p['source'],p['policies']) for p in manifest['phases']]==[
        ('private/public',48),('private_c/public',24),('private_d/public',24),('private_e/public',18)]
    assert len({p['directory'] for p in manifest['phases']})==4
    bundles=[]
    candidates=[]
    for phase in manifest['phases']:
        source=HERE/phase['source']
        proof_bytes=(source/'生成証跡.json').read_bytes()
        proof=json.loads(proof_bytes)
        assert proof['passed'] and proof['fixture'] is False
        assert proof['result_sha256']==phase['result_sha256']
        assert proof['policies']==phase['policies'] and proof['symbol_sessions']==phase['policies']*80
        contents={}
        for name,sha in proof['artifacts'].items():
            payload=(source/name).read_bytes()
            assert digest(payload)==sha
            contents[name]=payload
        contents['生成証跡.json']=proof_bytes
        reports=[name for name in contents if name.endswith('.html')]
        assert len(reports)==1
        data=json.loads(contents['data.json'])
        assert len(data['sessions'])==40 and len(set(data['sessions']))==40
        if bundles:
            assert data['sessions']==bundles[0][1]['sessions']
        assert len(data['cases'])==phase['policies']
        assert all(m['terminal_unclosed_lots']==0 for c in data['cases'].values()
            for m in c['metrics'].values())
        for audit in phase['audits']:
            assert digest((ROOT/audit['path']).read_bytes())==audit['sha256']
        phase.update(report=reports[0],files={k:digest(v) for k,v in contents.items()})
        bundles.append((phase,data,contents))
        for ranked in data['common_ranking']:
            candidates.append(dict(**ranked,phase=phase['directory'],case=data['cases'][ranked['id']]))
    assert len(candidates)==114
    diagnoses=[]
    for item in manifest['loss_diagnoses']:
        payload=(ROOT/item['path']).read_bytes()
        assert digest(payload)==item['sha256']
        if item.get('link_rewrites'):
            source=payload.decode('utf-8')
            for before,after in item['link_rewrites'].items():
                assert source.count(before)==1
                source=source.replace(before,after)
            payload=source.encode('utf-8')
        item['published_sha256']=digest(payload)
        diagnoses.append((item['destination'],payload))
    candidates.sort(key=lambda r:(not r['qualified'],-r['min_black'],
        -r['min_normalized_median'] if r['min_normalized_median'] is not None else float('inf'),
        r['max_worst_to_mean_black'] if r['max_worst_to_mean_black'] is not None else float('inf'),r['id']))
    featured=candidates[0]
    eligible=sum(r['qualified'] for r in candidates)
    both=sum(all(v['net']>0 for v in r['case']['metrics'].values()) for r in candidates)
    every=sum(all(v['all_positive'] for v in r['case']['metrics'].values()) for r in candidates)
    if every:
        conclusion='既知40場で両商品とも全場黒字の候補が得られました。未知の期間での安定性は未確認です。'
    elif eligible:
        conclusion='両商品で合計・中央値・利益上位3場除外後が黒字の候補が残りました。毎セッション黒字の完成解ではありません。'
    elif both:
        conclusion='両商品合計黒字の条件はありましたが、各場の安定性を確認できた候補は残りませんでした。'
    else:
        conclusion='提案型と修正型の114条件では、日経・TOPIXの両方で合計黒字になる手法は見つかりませんでした。'
    assert not PUBLIC.exists()
    PUBLIC.mkdir()
    links=[]
    for phase,data,contents in bundles:
        target=PUBLIC/phase['directory']
        target.mkdir()
        for name,payload in contents.items():
            (target/name).write_bytes(payload)
        links.append(f'<li><a href="{esc(phase["directory"])}/{esc(phase["report"])}">{esc(phase["title"])}</a>（{phase["policies"]}条件・両商品全40場）</li>')
    # ----------------------------------------
    # 在庫の図と診断は暗色の確定版だけを公開し、白図の旧版は作業領域に保全する。
    diag=HERE/'diagnosis/formal_b'
    chart='最悪場の確定損益と全玉清算時価及び長短枚数_暗色.png'
    for name in (chart,chart.replace('.png','.svg')):
        shutil.copyfile(diag/name,PUBLIC/name)
    shutil.copyfile(diag/'利益玉を回しても不利な在庫が少なくならなかった原因.md',PUBLIC/'損失の具体例.md')
    for name,payload in diagnoses:
        (PUBLIC/name).write_bytes(payload)
    comparison=[]
    wanted=((0,'HEDGE_S2_T1'),(1,'CREDIT_S2_T1'),(1,'COST_S2_T1'),(2,'COST_LAST_S2_T1'),
            (3,'KEEP_S2_T1'),(3,'RESCUE_S2_T1'),(3,'ROTATE_S2_T1'))
    for phase_index,identity in wanted:
        case=bundles[phase_index][1]['cases'][identity]
        values=[]
        for symbol in ('TOPIX','NK225'):
            m=case['metrics'][symbol]
            values.extend((money(m['net']),f"{m['black']}／{m['red']}／{m['inactive']}",money(m['worst'])))
        comparison.append('<tr><th>'+esc(identity)+'</th>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
    page='''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>段階トレーリングの結論と全セッション損益</title><style>
body{background:#0b1120;color:#e1eaf7;font:16px/1.7 system-ui,sans-serif;margin:0}main{max-width:1180px;margin:auto;padding:25px 18px}h1{font-size:27px}h2{font-size:21px;margin-top:27px}a{color:#9bd1ff}.note{padding:15px;background:#1b263b;border-left:4px solid #e9bb67}strong{color:#ffd184}.muted{color:#b1bfd2;font-size:14px}.wrap{overflow-x:auto;border:1px solid #34445b}table{width:100%;border-collapse:collapse;white-space:nowrap;font-size:14px}td,th{padding:9px 11px;border-bottom:1px solid #34445b;text-align:right}th:first-child{text-align:left}thead,tfoot{background:#1c2b44}img{max-width:100%;height:auto}code{overflow-wrap:anywhere}summary{cursor:pointer;color:#9bd1ff}@media(max-width:600px){main{padding:18px 11px}h1{font-size:23px}}
</style></head><body><!--
[コンポーネント概要]
mainは短い結論、四段階の比較、参考一政策の全場表です。
.wrapは表内だけを横スクロールする領域です。利益・損失は一枚玉の実費用後で集計します。
画像は暗色版の全玉清算時価と確定損益です。無取引・未清算・合成は黒字へ加えません。
--><main><h1>段階トレーリングの結論と全セッション損益</h1>'''
    page+='<p class="note"><strong>'+esc(conclusion)+'</strong></p>'
    page+='<p>ご提案の「下値＋3・4・5…で段階買い／上値−同幅で段階売り、利益玉だけ追尾返済して空き枠を再利用」を中心に検証しました。比較上限はTOPIXミニ片方向10枚、日経マイクロ20枚。手数料を含み、全玉を場内で返済します。</p>'
    page+='<p><b>入口の意味：</b>安値3990→3993で1枚目、3994で2枚目。1枚目を残して安値が3980へ更新されれば、2枚目は3984で発火します。売りは上下を逆にします。この2経路と売り鏡像は人工で確認済みです。数字は発火線で、実約定は後続の売買気配です。</p>'
    page+='<ol><li><b>最初の個別回転：</b>両建て・個別利確・枠再利用と、その部品を変えた48条件。</li><li><b>少枚数を条件にする修正：</b>初回1枚、含み純益で追加を許可、方向別合計損失で返済。片方向限定・新規価格上限・広気配回避を順次追加した24条件。</li><li><b>追尾の基準を再点検：</b>新規の中値極値を最終約定値へ変えた24条件。数量・出口・費用は同じ。</li><li><b>追加のご説明を直接検証：</b>カバーを残すKEEP、上限で逆玉を一枚減らすRESCUE、上昇で買増・反落で利益買い返済と売増を上下対称に繰り返すROTATEの18条件。利益玉の個別回転と組全体回収を分けました。</li></ol>'
    page+='<p class="muted">追加判断の信用は当時の含み益で、将来損失の保証ではありません。方向別3単位は返済判断の線で、次気配の値飛びにより実損失は超過します。最後の18条件にはこの方向別停止を置いていません。114条件は同じ40場の開発比較です。</p>'
    page+='<h2>同じ中間幅・狭い追尾での修正結果</h2><div class="wrap"><table><thead><tr><th>手法ID</th><th>TOPIX収支円</th><th>黒／赤／無</th><th>最悪円</th><th>日経収支円</th><th>黒／赤／無</th><th>最悪円</th></tr></thead><tbody>'+''.join(comparison)+'</tbody></table></div>'
    page+='<h2>何が損失になったか</h2><p>最初の48条件の基準型では、利益玉を先に外すと負け在庫が残りました。TOPIXの10月14日ナイトは84玉の利確で＋164,612円でも、場末の負け10玉で−612,820円。各注文が1枚でも、不利方向の合計が少枚数とは限りません。</p>'
    page+='<p>また、気配の中値が下がって売りが発火しても、最終約定値は上がっていた実例がありました。小試行、方向合計停止、広気配の制限、最終約定値基準を分けた理由です。</p><details><summary>利益と残在庫が分かれる図を見る</summary><img src="'+esc(chart)+'" alt="確定利益が増える一方、買い在庫が10枚残り全玉時価が沈む推移"><p><a href="損失の具体例.md">赤字上位場の時刻・価格・残玉と各修正の診断</a></p></details>'
    page+='<p>小さく入り方向別に損切りする修正では、初回の反発が利確開始幅まで届かない失敗を繰り返しました。TOPIXの9月30日ナイトは方向別停止76回、日経の10月16日ナイトは100回。両場の負け玉は全て利益追尾の開始幅へ届いていません。<a href="改善後に残った損失.md">修正後の実時刻と反復損失</a>に整理しました。</p>'
    page+='<p>ご指摘の「逆側で追い越す」は、反対側の実保有枚数が元側より多く残る場合に働きます。等枚数なら共通価格の変化は相殺されますが、気配差の拡縮による時価変化は残ります。<a href="逆側カバーと上下回転の診断.md">最新の上下回転・カバー保持の実測</a>では、追い越した後、利確でカバーを外した後、上限へ達した後を分けて確認しています。</p>'
    page+='<h2>全条件の説明と全セッション損益</h2><ul>'+''.join(links)+'</ul>'
    case=featured['case']
    page+='<h2>参考代表の全40場：'+esc(featured['id'])+'</h2><p>'+esc(case['spec']['description'])+'</p>'
    summary=[]
    for symbol,label in (('TOPIX','TOPIXミニ'),('NK225','日経マイクロ')):
        m=case['metrics'][symbol]
        summary.append(f"{label}：{m['black']}/40場黒字、合計{money(m['net'])}円")
    page+='<p><strong>'+esc(' ／ '.join(summary))+'</strong></p>'
    page+='<p class="muted">同じ固定条件を両商品へ適用した事後比較の代表です。比較資格は合計・中央値・上位3黒字場除外後の黒字、未返済0。資格あり'+str(eligible)+'/114、両商品合計黒字'+str(both)+'/114。各場の結果を見て手法を切り替えるアルゴリズムではありません。</p>'
    by={(r['session'],r['symbol']):r for r in case['rows']}
    scenes=bundles[0][1]['sessions']
    table=[]
    for scene in scenes:
        values=[]
        for symbol in ('TOPIX','NK225'):
            row=by[scene,symbol]
            values.extend((f"{row['profit']:,.0f}",f"{row['loss']:,.0f}",money(row['net'])))
        table.append('<tr data-session="'+esc(scene)+'"><th>'+esc(scene)+'</th>'+''.join('<td>'+esc(v)+'</td>' for v in values)+'</tr>')
    footer=[]
    for symbol in ('TOPIX','NK225'):
        m=case['metrics'][symbol]
        footer.extend((f"{m['profit']:,.0f}",f"{m['loss']:,.0f}",money(m['net'])))
    page+='<div class="wrap"><table><thead><tr><th rowspan="2">セッション</th><th colspan="3">TOPIXミニ</th><th colspan="3">日経マイクロ</th></tr><tr>'+2*'<th>利益円</th><th>損失円</th><th>収支円</th>'+'</tr></thead><tbody>'+''.join(table)+'</tbody><tfoot><tr><th>全40場</th>'+''.join('<td>'+esc(v)+'</td>' for v in footer)+'</tr></tfoot></table></div>'
    page+='<p class="muted">利益・損失は完結一枚玉の両注文手数料を含む正負の合計で、料を再度差し引きません。2026年9月21日デイ〜10月16日ナイト。ラージBBOによる小型商品の代理約定で、実小型板・真受信順・待ち順位は未観測です。</p>'
    page+='<p><a href="README.md">資料と検証条件</a> ／ <a href="損失の具体例.md">損失の具体例</a> ／ <a href="../../work/stability120_20261017/中断と修正版の扱い.md">初回停止と修正版の扱い</a></p></main></body></html>'
    (PUBLIC/MAIN).write_text(page,encoding='utf-8')
    (PUBLIC/'README.md').write_text('# 段階トレーリング新規と利益玉の部分回転\n\n最初に['+MAIN+']('+MAIN+')を開いてください。\n\n'+conclusion+'\n\n読む順序：\n\n1. 最初のHTMLの結論と同条件の修正比較。\n2. [最新の上下対称回転・カバー保持18条件](04_上下対称回転とカバー保持/上下対称の利益回転とカバー保持の全セッション損益.html)で、説明・両商品全40場・全期間合計。\n3. [最新の具体的な追越と残在庫](逆側カバーと上下回転の診断.md)。\n4. 先行96条件は各段階のHTMLと[初期の損失](損失の具体例.md)・[中間修正の損失](改善後に残った損失.md)へ分けて保存。中間診断の「未検証」は当時の段階を表します。\n\n全て同じ既知40場の開発で、独立した114標本ではありません。比較上限はTOPIXミニ10枚／日経マイクロ20枚、全玉場内返済。各新規・返済は一枚ずつ別注文で料を円未満切捨て、買ask・売bidの次正常原行約定。元bookや過去研究は変更していません。実注文・現在API取得0。\n\n最新の機械的な実装は[engine120e1.py](../../work/stability120_20261017/recovery_e1/engine120e1.py)、固定条件は[catalog120e1.py](../../work/stability120_20261017/recovery_e1/catalog120e1.py)。発火行で架空約定せず、初回一枚後に上下の未約定極値を別々に追います。\n\n初回120は会計不一致で停止し、120aは実データ前に中止。境界検査付き120b以降の完成会計だけを正式成績へ採用。[初回の修正記録](../../work/stability120_20261017/中断と修正版の扱い.md)。eも金融前に中止し、経済源同bytesのe1だけを最新18条件として測定しました。[非空実行前検査の修正](../../work/stability120_20261017/e金融前中止とe1同条件の扱い.md)。\n',encoding='utf-8')
    manifest.update(conclusion=conclusion,qualification_count=eligible,both_net_positive=both,
        all40_positive=every,featured=dict(id=featured['id'],phase=featured['phase']),
        public=PUBLIC.relative_to(ROOT).as_posix(),main_sha256=digest((PUBLIC/MAIN).read_bytes()))
    (PUBLIC/'公開目録.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(public=PUBLIC.as_posix(),conclusion=conclusion,featured=featured['id']),ensure_ascii=False))


if __name__=='__main__':
    main()
