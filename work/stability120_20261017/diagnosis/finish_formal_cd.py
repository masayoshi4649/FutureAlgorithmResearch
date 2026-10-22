"""c/d保存診断だけをまとめ、追加金融なしで公開用の短い原因MDを閉じる。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


HERE=Path(__file__).resolve().parent/'formal_cd'
ROOT=HERE.parents[3]


def display(clock: float) -> str:
    """
    機能: 保存価格時計を日本時間の時分秒に表示する。
    引数: clock(float)はepoch秒。
    返り値: strは価格時計であり真受信時刻ではない。
    """
    return datetime.fromtimestamp(clock,ZoneInfo('Asia/Tokyo')).strftime('%H:%M:%S')


def main() -> None:
    """
    機能: c/d全小会計と最悪二場ずつの保存射影から、最終原因を日本語で記録する。
    引数: なし。
    返り値: None。原結果・NPZ・市場・新金融を追加読取しない。
    """
    HERE.mkdir(parents=True,exist_ok=True)
    base=HERE.parent
    paths=[base/'formal_c/全二十四小会計と保存b基準の比較.json',
        base/'formal_c/COST最悪二場の追加余力と反復停止及び未追尾損失の診断.json',
        base/'formal_d/Last基準二十四小会計と中値c同条件の比較.json',
        base/'formal_d/Last基準最悪二場の反復停止と実追加及び追尾未起動損失.json']
    c,ct,d,dt=[json.loads(p.read_text(encoding='utf8')) for p in paths]
    assert all(x['全合格'] for x in (c,ct,d,dt))
    assert len(c['summary'])==len(d['summary'])==24 and len(ct['scenes'])==len(dt['scenes'])==2
    assert all(p['net']<0 and p['unclosed']==0 for v in (c,d) for s in v['summary'] for p in s['profile'].values())
    for value in (c,d):
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha for p,sha in value['source_SHA256'].items())
    cm={x['method']:x for x in c['summary']};dm={x['method']:x for x in d['summary']}
    lines=['# 改善後に残った損失','',
        '小さく試し、現在の利益で追加を支えるようにすると、負け玉を場末まで抱える問題は減った。しかし、その後は追尾を始められるほど伸びる前に小損失を繰り返した。さらに新規の極値を中値から観測Lastへ直すと金額は改善したが、今回の条件では黒字手法にならなかった。','',
        '## 何を変えたか','',
        'cは各方向の初回を一枚とし、同方向の費用後清算益が追加一枚の3単位リスクを賄う場合だけ増やす。方向全玉の清算損が一枚分3単位に達したら全返済する。片方向限定、最初の次気配一回での価格上限、気配差制限を順に加えた四管理×三幅×二追尾の24条件である。','',
        'dはその同条件の新規追尾極値だけを観測Lastへ変えた24条件。cの中値をユーザーの下値・上値と同じものとして扱わないための対照で、Last価格で約定させたわけではない。買ask・売bidと注文別料、判断より後の正常原行の実約定を維持した。Lastも取得された現在値であり、完全な約定テープではない。','',
        '| 同じS2・狭追尾T1 | c TOPIX net | d TOPIX net | c 日経 net | d 日経 net |',
        '|---|---:|---:|---:|---:|']
    for tag in ('CREDIT','ONE','LIMIT','COST'):
        a=cm[tag+'_S2_T1']['profile'];b=dm[tag+'_LAST_S2_T1']['profile']
        lines.append(f"|{tag}|{a['TOPIX']['net']:,.0f}|{b['TOPIX']['net']:,.0f}|{a['NK225']['net']:,.0f}|{b['NK225']['net']:,.0f}|")
    lines.extend(['','金額は費用後円、全40場。CREDIT＝利益条件付き追加、ONE＝片方向、LIMIT＝新規価格限定、COST＝さらに気配差を一単位以内に制限。表の各設定は両商品とも40/40赤字。全三幅・二追尾へ広げたc/d各24条件にも、商品単独又は両商品共通の合計黒字候補はなかった。','',
        'b基準HEDGE_S2_T1のTOPIX−3,931,392円／日経−1,451,790円に対し、dのCOSTは−2,599,366円／−673,542円へ損失額を減らした。ただし損失の改善と採用可能な黒字は別である。','',
        '## 大きな残在庫損失が、途中の反復損失へ移った','',
        '| 段階・COSTの最悪場 | 約定玉数（初回／追加） | 方向停止回数 | 負け玉／追尾未起動の負け玉 | その損失 | 場net |',
        '|---|---:|---:|---:|---:|---:|'])
    for label,traces,method in (('c',ct,'COST_S2_T1'),('d',dt,None)):
        for scene in traces['scenes']:
            if label=='c':
                p=next(x for x in scene['policies'] if x['method']==method);row=p['row'];extra=p['credit_and_stop']
            else:row=scene['row'];extra=scene['credit_and_stop']
            loss=extra['loss_before_trail']
            lines.append(f"|{label} {scene['symbol']} {scene['session']}|{row['entries']:.0f}（{extra['initial_entries']}/{extra['add_entries']}）|{extra['stop_count']}|{loss['all_losing_count']}/{loss['count']}|{loss['net']:,.0f}|{row['net']:,.0f}|")
    lines.extend(['','全ての負け玉は、狭追尾の起動水準である費用後2単位の最高利益へ届かずに終了した。追尾が始まっていれば高率で勝てる、という条件付きの見方では初回の失敗を数え落とす。','',
        'cの日経10/16ナイトは、bの最大買い19枚・売り16枚と場末損失242,484円を、最大買い2枚・売り7枚と場末損失0円へ抑えた。それでも128負け玉の損失63,516円が57勝ち玉の利益23,946円を上回り、net−39,570円だった。悪いときの数量を抑える工夫は働いたが、新しい一枚の向きが続く根拠には足りなかった。','',
        '## 実時刻で見る初回の負けと、利益で支えた追加の負け','',
        'c・TOPIX9/30ナイトの最悪一枚は17:00:04に4,129で売り、17:00:05に4,132.5で返済して−3,582円。一度も費用後黒字にならなかった。追加例は17:29:18、既存利益+3,418円が必要3,000円を超えたため4,136.5で一枚買い増ししたが、新玉は黒字にならず17:30:20に4,133.5返済、−3,082円。追加条件を守ることと、追加後の継続を予測することは違う。','',
        'd・TOPIX10/16ナイトでは、23:10:19に4,078で一枚売り、23:14:04に4,081.5で返済して−3,582円。最高でも+418円で起動2,000円へ届かなかった。同場22:55:35の追加も、既存清算益+3,918円で必要3,000円を満たして4,089.5で買ったが、新玉は一度も黒字にならず、22:56:03に4,086.5返済で−3,082円となった。','',
        'd・日経10/15ナイトは23:06:47に64,660で一枚売り、23:08:10に64,730で返済して−722円。最高益+178円では起動400円に届かない。17:25:51の買い追加も、既存利益+678円で必要600円を満たした後、64,650→17:26:04の64,590で−622円だった。','',
        '方向停止は価格飛びと総枚数で閾値を超える。d最悪場の最大停止はTOPIX18:59:14に売り6枚−4,992円、日経23:13:47に売り4枚−988円で、そのまま実約定した。3,000円／600円は返済判断の閾値で、必ずその損失額で返せる保証ではない。','',
        'ただし次気配の悪化だけが反復損失の原因ではない。方向停止判断から実返済までの差を群全体で合計すると、c最悪場はTOPIX+6,000円・日経+1,000円、dは+5,500円・+1,700円と有利だった。既に判断前に悪化し、小さな試行を繰り返している損失を、執行の遅さだけでは説明できない。','',
        '## 今回ここまで分かったこと','',
        '観測中値の見かけの反転、巨大気配差、負け在庫の放置には、それぞれ修正する理由があった。修正後も残った中心問題は、最初の反転が費用後の追尾起動まで続かないこと、追加時の含み益がその後の新玉の予測力を作らないこと、損切り後の再試行が十分な優位を持たなかったことである。','',
        '射程は、既知40場・今回の一枚単位・数量上限・価格時計と次BBO約定模型で検証したb48＋c24＋d24の96設定に限る。追尾全般やカバー全般の不可能性を証明したものではない。とくに、逆カバーを利益玉として先に外さず組全体の回復まで残す別の管理効果を、この結果で検証済みとはしない。','',
        '原因診断はc/d各商品のCOST最悪一場に条件付けた記述で、損失玉を事後に消した新成績ではない。取消された未約定予約は個別未保存であり、実追加の保存記録と独立監査の範囲を超えて補完しない。最大含み益を当時取れた利益へ足さず、未知データで成功したとも扱わない。','',
        'cは根指定結果一読保全と監査所有2NPZ、dは指定SHAと同じ監査所有結果一読保全と所有2NPZだけを使用。bの日経同場は既所有copyを再利用した。元measurement cache・元prepared・原市場の追加読取、金融再生は0。全額は実注文料込みで、真受信時計・実小型板・注文待ち順位は未観測。'])
    md=HERE/'改善後に残った損失.md';assert not md.exists();md.write_text('\n'.join(lines)+'\n',encoding='utf8')
    for name,value in [('c',c),('d',d)]:
        assert not value['両商品net正']
    files=paths+[HERE.parent/'read_formal_d.py',HERE.parent/'trace_formal_d.py',Path(__file__),md]
    outputs=[dict(path=p.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size) for p in files]
    out=HERE/'cとLast対照dの最終原因と読取境界の完了証跡.json';assert not out.exists()
    proof=dict(全合格=True,c結果SHA256=c['結果SHA256'],d結果SHA256=d['結果SHA256'],c_source_SHA256=c['source_SHA256'],d_source_SHA256=d['source_SHA256'],
        outputs=outputs,c全小会計=1920,d全小会計=1920,c詳細cache=2,d詳細cache=2,b既所有再利用=1,
        c根指定結果原本読取=1,d同bytes監査所有結果読取=1,d元結果原本追加読取=0,
        原measurement_cache読取=0,原prepared読取=0,原市場読取=0,金融再生=0,
        診断側stdout初版='dの診断JSON保存成功後のstdoutだけNumPy int64でTypeError。初版源/Falseを保全しprintの型変換だけ訂正。NPZと金融の再実行は0。',
        留保='今回96設定の範囲だけ。別カバー保持方策は未測定。未保存の予約・価格時計の真受信・実小型約定は補完しない。')
    out.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'全合格':True,'最終MD':outputs[-1],'完了証跡':dict(path=out.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(out.read_bytes()).hexdigest())},ensure_ascii=False))


if __name__=='__main__':main()
