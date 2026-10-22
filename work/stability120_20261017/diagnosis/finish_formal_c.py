"""cの限定診断を、初回小試行と利益余力の限界を分けて保存する。"""

import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent/'formal_c'
ROOT=HERE.parents[3]


def main() -> None:
    """
    機能: 所有小集計だけから四管理と最悪二場の原因を日本語で閉じる。
    引数: なし。
    返り値: None。元結果・NPZ・市場・金融・dを追加読取しない。
    """
    small=json.loads((HERE/'全二十四小会計と保存b基準の比較.json').read_text(encoding='utf8'))
    detail=json.loads((HERE/'COST最悪二場の追加余力と反復停止及び未追尾損失の診断.json').read_text(encoding='utf8'))
    assert small['全合格'] and detail['全合格'] and len(detail['scenes'])==2
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==s for p,s in small['source_SHA256'].items())
    lines=['# 小試行と利益条件付き追加でも残った反復損失','',
        'cは最初を一枚にし、同方向の現清算利益が追加一枚の3単位リスクを賄うときだけ増やした。方向別の清算損が一枚分3単位へ達したら全返済する。bで残った大きな場末在庫損失は減ったが、全24条件に両商品で合計黒字の候補はなかった。以下は既知40場の原因対照で、将来成績ではない。','',
        '## 同じ幅S2・狭追尾T1の全40場','',
        '| 運用 | TOPIX net | 日経 net | TOPIX場末損失 | 日経場末損失 |',
        '|---|---:|---:|---:|---:|']
    baseline=small['baseline_b']['profile']
    lines.append(f"|b・HEDGE|{baseline['TOPIX']['net']:,.0f}|{baseline['NK225']['net']:,.0f}|{baseline['TOPIX']['forced_loss']:,.0f}|{baseline['NK225']['forced_loss']:,.0f}|")
    for row in small['summary']:
        if row['method'].endswith('_S2_T1'):
            a=row['profile']['TOPIX'];b=row['profile']['NK225']
            lines.append(f"|{row['method']}|{a['net']:,.0f}|{b['net']:,.0f}|{a['forced_loss']:,.0f}|{b['forced_loss']:,.0f}|")
    lines.extend(['','金額は円、注文料込み。CREDIT＝利益条件付き追加、ONE＝片方向、LIMIT＝最初の次気配で価格上限、COST＝さらに判断時と到来時の気配差を一単位以内に制限する。四管理のS2_T1は両商品とも40/40赤字だった。COSTでbより損失額を減らしても、利益の根拠ができたとは言わない。','',
        '## COSTの赤字最悪一場ずつ','',
        '| 場 | net | 初回／追加約定 | 方向停止回数 | 負け玉数／追尾未起動の負け玉 | 利益追尾前に終わった損失 |',
        '|---|---:|---:|---:|---:|---:|'])
    for scene in detail['scenes']:
        p=next(x for x in scene['policies'] if x['method']=='COST_S2_T1');e=p['credit_and_stop'];l=e['loss_before_trail']
        lines.append(f"|{scene['symbol']} {scene['session']}|{p['row']['net']:,.0f}|{e['initial_entries']}/{e['add_entries']}|{e['stop_count']}|{l['all_losing_count']}/{l['count']}|{l['net']:,.0f}|")
    lines.extend(['','両場とも負け玉の全てが、狭追尾の発動線である費用後2単位の最高利益へ届かず終了した。一度も費用後黒字にならなかった負けはTOPIX67玉・−166,994円、日経66玉・−31,952円。残りも追尾発動まで届かない小さい順行であり、利益追尾の幅だけでは初回の失敗を解決しない。','',
        'TOPIXは17:00:04に4,129で一枚売り、次の17:00:05に4,132.5で返済し−3,582円。初期清算費用1,082円、保有中最高清算損益−582円で一度も黒字ではなかった。通常の3,000円停止は判断の閾値であり、次に返せる気配をその金額へ固定する上限ではない。','',
        '日経の最大損失一枚は翌00:38:18に64,750で買い、00:42:26に64,680で返済、−722円。初期費用122円で入り、一度+78円になったが追尾起動400円へ届かなかった。巨大spreadで開始できなかっただけ、という説明ではない。','',
        '## 追加時に利益があっても、その後の新しい玉は守られない','',
        'TOPIX17:29:18、既存一枚の清算純益+3,418円で、追加に必要な3,000円を上回ったため4,136.5で一枚追加。新しい玉自身は最高でも−582円のまま、17:30:20に4,133.5で返済して−3,082円だった。日経19:07:00も既存利益+678円に対し必要600円を満たし、65,380で売り追加したが、19:11:52に65,440で返済し−622円だった。こちらの新玉最高益は+78円。','',
        '保存された実追加では、判断当時の必要利益の下限と整合した。取消された未約定予約は個別に保存されていないため、診断で完全な予約台帳を補完しない。全予約を含む実装の資格検査は独立人工・全会計監査へ委譲する。追加当時の利益は損失を吸収する余地であり、追加後も同じ方向が続く予測そのものではない。','',
        '最大の方向停止はTOPIX翌00:50:04に買い5枚を清算評価−6,410円で返済し、実約定も同額。日経22:48:35は売り6枚−1,032円で停止し、実約定も同額だった。3単位の3,000円／600円を超えたのは、離散的なBBOでまとめた全玉がその評価に達したためで、停止線の架空約定を置かない。','',
        '最悪二場の停止判断→実約定差を全方向停止で合計すると、TOPIXは+6,000円、日経は+1,000円とむしろ有利だった。次気配悪化だけが繰返し損失の原因ではない。停止後の同方向再参加も続き、方向停止76回／100回の合計netは−240,872円／−63,282円。利益を使う条件と、次の反転・継続を当てる条件は別だった。','',
        '## 何が改善し、何が残ったか','',
        'bの日経10/16ナイトはnet−116,368円、買い最大19枚・売り最大16枚、場末損失242,484円だった。同じ場のCOSTは最大買い2枚・売り7枚、net−39,570円で場末損失0円まで抑えた。しかし128負け玉の損失63,516円と57勝ち玉の利益23,946円になり、途中の小損失が利益を上回った。','',
        'TOPIX9/30ナイトはbの保存小会計−136,086円に対しCOST−156,816円で、場末の尾を抑えれば必ず合計も改善するわけではない。こちらはb既読六場外なので、bの新しいcacheや親時刻は読まず、場収支の比較だけとしている。','',
        'COST二場のLast不変なのに中値が発注方向へ動いた新規は132/138玉、178/185玉。Lastが同方向へ動いた玉にも損失があるので、この分類だけを事後に除いた改善額は算出しない。ユーザーの下値・上値と中値極値の違いは、続くLast基準の同条件対照で別に確かめる。','',
        '根指定c完成結果を一読保全し、119が保全した同bytesのc二NPZだけを各一読。bは既所有の日経同場一NPZを再利用し、元measurement・元prepared・原市場の追加読取と金融再生は0。判断時計は価格時計で、真受信や実小型板を証明しない。未測定の新しい入口・再参加規則を成功した手法として扱わない。'])
    md=HERE/'小試行と利益条件付き追加でも追尾前の損失を繰り返した原因.md'
    assert not md.exists();md.write_text('\n'.join(lines)+'\n',encoding='utf8')
    files=[HERE.parent/name for name in ('read_formal_c.py','trace_formal_c.py','finish_formal_c.py')]
    files += [HERE/name for name in ('正式cの一読保全と最悪二場の診断を読む計画.json',
        '正式cのCOST最悪二場を各一読する目録.json','監査所有c二copyとb既所有一場を再利用する目録.json',
        '全二十四小会計と保存b基準の比較.json','COST最悪二場の追加余力と反復停止及び未追尾損失の診断.json',md.name)]
    outputs=[dict(path=p.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size) for p in files]
    out=HERE/'正式cの追加余力と反復損失診断の完了証跡.json';assert not out.exists()
    proof=dict(全合格=True,結果SHA256=small['結果SHA256'],source_SHA256=small['source_SHA256'],outputs=outputs,
        全小会計=1920,条件=24,詳細場=2,詳細運用=4,c結果原本読取=1,c監査所有NPZ読取=2,b既所有NPZ再使用=1,
        原measurement_cache読取=0,原prepared読取=0,原市場読取=0,金融再生=0,d結果読取=0,
        留保='追加判断時の利益は次の継続優位を証明しない。未保存取消予約を補完せず、最大含み益を救済利益にしない。')
    out.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'全合格':True,'MD':outputs[-1],'完了証跡SHA256':hashlib.sha256(out.read_bytes()).hexdigest()},ensure_ascii=False))


if __name__=='__main__':main()
