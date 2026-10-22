"""保存済みの限定診断だけから、原因メモ・在庫図・完了証跡を作る。"""

from datetime import datetime
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np


HERE = Path(__file__).resolve().parent/'formal_b'
ROOT = HERE.parents[3]


def figure(small: dict) -> tuple[Path,Path,str]:
    """
    機能: 基準赤字六場で最悪の一場の、保存約一分曲線だけを描く。
    引数: small(dict)は全小会計と詳細六場の選択。
    返り値: tuple[Path,Path,str]はPNG、SVG、選択キー。新金融や原cacheへ接続しない。
    """
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    fonts=[Path('C:/Windows/Fonts/meiryo.ttc'),Path('C:/Windows/Fonts/msgothic.ttc')]
    font=next((x for x in fonts if x.is_file()),None)
    assert font is not None,'日本語フォントが必要です'
    prop=font_manager.FontProperties(fname=str(font))
    plt.rcParams['font.family']=prop.get_name()
    plt.rcParams['axes.unicode_minus']=False
    selected=min(small['selected'],key=lambda x:(x['net'],x['symbol'],x['session']))
    key=selected['symbol']+'__'+selected['session']
    with np.load(HERE/'基準六場の保存曲線だけの射影.npz',allow_pickle=False) as saved:
        curve=saved[key].copy()
    # ----------------------------------------
    # 同じ末尾サンプルの重複だけを除き、未保存区間の極値は補間しない。
    keep=np.r_[True,np.diff(curve[:,0])!=0]
    curve=curve[keep]
    times=[datetime.fromtimestamp(t,ZoneInfo('Asia/Tokyo')) for t in curve[:,1]]
    fig,axes=plt.subplots(2,1,figsize=(11,6.7),sharex=True,gridspec_kw={'height_ratios':[2.2,1]})
    axes[0].plot(times,curve[:,4]/1000,color='#17814d',label='確定純損益')
    axes[0].plot(times,curve[:,2]/1000,color='#c13d43',label='全玉清算時価（返済料込み）')
    axes[0].fill_between(times,curve[:,2]/1000,curve[:,4]/1000,color='#cf6767',alpha=.13,label='残玉の清算損益との差')
    axes[0].axhline(0,color='#7c8794',linewidth=.8);axes[0].set_ylabel('千円');axes[0].legend(loc='upper left',fontsize=9)
    axes[0].set_title(selected['symbol']+' '+selected['session']+'  HEDGE_S2_T1\n利益を確定しても負け在庫は残った',fontsize=12)
    axes[1].step(times,curve[:,5],where='post',label='買い保有枚数',color='#1974b8')
    axes[1].step(times,curve[:,6],where='post',label='売り保有枚数',color='#cb8c23')
    axes[1].set_ylabel('枚');axes[1].legend(loc='upper left',fontsize=9)
    axes[1].xaxis.set_major_formatter(mdates.DateFormatter('%m/%d %H:%M',tz=ZoneInfo('Asia/Tokyo')))
    for ax in axes:ax.grid(alpha=.2)
    fig.text(.065,.012,'保存曲線は約1分間隔。全原行の極値・DD時刻とは異なる。価格時計模型で、実受信・実小型板は未検証。',fontsize=8)
    fig.tight_layout(rect=(0,.035,1,1))
    png=HERE/'最悪場の確定損益と全玉清算時価及び長短枚数.png'
    svg=png.with_suffix('.svg')
    assert not png.exists() and not svg.exists()
    fig.savefig(png,dpi=150);fig.savefig(svg);plt.close(fig)
    return png,svg,key


def main() -> None:
    """
    機能: 正式bだけの診断を平易な日本語と限定証跡に閉じる。
    引数: なし。
    返り値: None。市場・元結果・原cache・金融を読み直さない。
    """
    small=json.loads((HERE/'全四十八小会計の独立集計と詳細六場.json').read_text(encoding='utf8'))
    detail=json.loads((HERE/'基準赤字六場の利益回転と残損失及び中値Lastの診断.json').read_text(encoding='utf8'))
    assert small['全合格'] and detail['全合格'] and len(detail['scenes'])==6
    assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==s for p,s in small['source_SHA256'].items())
    png,svg,key=figure(small)
    baseline=next(x for x in small['summary'] if x['method']=='HEDGE_S2_T1')
    lines=['# 利益玉を回した後に残った損失', '',
        '正式な120bの48条件は、TOPIX・日経それぞれ単独でも合計黒字が0件だった。元120は会計不一致で停止、120aは登録だけで未実行なので、有効性の成績に含めていない。以下は同じ既知40場での原因記述であり、新しい改善手法の成績ではない。','',
        '## 一枚ずつ建てても、不利な在庫が少なくなるとは限らなかった','',
        '基準HEDGE_S2_T1は、利益になった一枚を追尾して外す一方、含み損玉には価格の損切りがなく場末まで残す。再利用枠は利益を外した側に生まれ、負け玉が残る側も別の空き枠で追加できる。SOURCEでは複数段が同じ原行で発火する場合もあり、初回や追加に利用可能利益の制限はない。全40場の買い・売り最大枚数は、TOPIXが両方10枚、日経が両方20枚へ達した。','',
        '| 商品 | 確定利益 | 確定損失 | net | 場末返済の損失 | 黒／赤／無取引 |',
        '|---|---:|---:|---:|---:|---:|']
    for symbol,p in baseline['profile'].items():
        lines.append(f"|{symbol}|{p['profit']:,.0f}|{p['loss']:,.0f}|{p['net']:,.0f}|{p['forced_loss']:,.0f}|{p['black']}/{p['red']}/{p['no_trade']}|")
    lines.extend(['','金額は全て円、利益・損失は実際の両注文料を含む。各玉一枚の全返済なので「部分利確」は在庫群の一部という意味であり、一枚を半枚にしてはいない。','',
        '| 基準の赤字上位場 | 利確理由1のnet | 場末損失額／負けUID数 | 場末判断の買／売 | 最終net |',
        '|---|---:|---:|---:|---:|'])
    for scene in detail['scenes']:
        b=scene['policies'][0];p=b['row'];snap=b['snapshots']['場末判断'];forced=b['reasons'].get('9',{})
        loss_uid=sum(x['net']<0 for x in snap['held'])
        lines.append(f"|{scene['symbol']} {scene['session']}|{p['trail_net']:,.0f}|{p['forced_loss']:,.0f}／{loss_uid}|{snap['long']:.0f}/{snap['short']:.0f}|{p['net']:,.0f}|")
    lines.extend(['','TOPIX10/14ナイトは84玉の利確net+164,612円を確保した後も、05:40:01に買い10枚・売り2枚が残り、損失10玉は612,820円。利益玉2枚+2,836円も返して、最終−445,372円となった。日経同場も場末の買い17玉で−289,074円を失い、それ以前の利確net+88,726円を上回った。勝ち玉の回数と、全玉返済後の収支は別だった。','',
        '![最悪場の実現益と全在庫](最悪場の確定損益と全玉清算時価及び長短枚数.png)','',
        '図は保存約一分曲線で、全原行の最大DDの発生時刻を保証するものではない。診断では保存実注文から全採用quote上の在庫と清算時価を別途復元し、各場の全原行最大DDと最小資産、保存曲線に一致した。','',
        '## 中値の追尾はLastの反転確認と同じではなかった','',
        '選んだ赤字6場の基準1296完結玉のうち、判断直前からLast不変なのに中値だけが発注方向へ動いた玉は1225玉。これは赤字上位場に条件付けた事後分類で、全40場の信号正答率や、Last不変のとき必ず悪いという法則ではない。勝ち玉にも同じ分類が多い。','',
        '具体的にはTOPIX10/2ナイト21:29:50、前の採用中値4,138から4,124.5へ下がり売りが発火した。しかしLastは4,137から4,139.5へ上がり、次の原行ではLast4,140のままbid4,110／ask4,139.5だった。売り一枚は4,110で約定し、初期清算コストは気配差29.5pt＋往復料＝29,582円。単位1pt＝1,000円の約29.6倍だった。場末4,157.5買い返済のnet−47,582円は、同時点Last方向−17,500円、新規のLast対bid差−30,000円、料−82円に分かれる。Lastで売れた仮想成績ではない。','',
        '一方、TOPIX10/16ナイトの最大損失玉は18:27:56、通常のbid4,101／ask4,101.5で一枚買い。初期費用582円でも、その後黒字にならず場末4,032.5返済で−69,082円になった。日経10/16ナイトも17:53:13買65,750→05:40:13売63,750で−20,022円、うちLast方向変化−19,900円。気配差を制限するだけで全ての負けを防げる説明ではない。','',
        '中値の発火を実売買更新の確認と呼ばず、判断時の幅・注文価格上限・初期清算費用を別に記録する。観測LastとBBOの不一致は保存価格代理の事実であり、真の取引主体や実小型板の約定可能性を断定しない。','',
        '## 管理を変えると場末損失は減っても、途中の別の負けへ移った','',
        '| 同じS2_T1の運用 | TOPIX全40net | 日経全40net | TOPIX場末損失 | 日経場末損失 |',
        '|---|---:|---:|---:|---:|'])
    for x in small['summary']:
        if x['method'].endswith('_S2_T1'):
            a=x['profile']['TOPIX'];b=x['profile']['NK225']
            lines.append(f"|{x['method']}|{a['net']:,.0f}|{b['net']:,.0f}|{a['forced_loss']:,.0f}|{b['forced_loss']:,.0f}|")
    lines.extend(['','NET・FLIP・HARDは場末に残す損失を減らしたが、途中で返して再参加する回数や損失が増え、全40の合計は基準より悪化した。HARDのTOPIXは完結3,956→14,124玉、日経6,495→20,071玉へ増えた。損失を早く実現しただけでは、次の反発・反落が費用を超える優位になるとは限らない。','',
        'ONCEはTOPIX10/16ナイトを+43,360円へ変えたが、日経同場は基準−116,368円に対し−125,058円へ悪化した。ALLSIDEもTOPIX同場を改善した一方、10/2ナイトでは−269,914→−399,918円へ悪化した。一場を直したことを全場の解決としない。','',
        '基準と各対照の同場差は、同じ方向・段・判断原行・約定原行・建値が一致する共通入口の退出差、新たに生じた玉、消えた玉へ分解して一致した。UID連番の一致や、旧負け玉だけの削除で成績を作っていない。FIXEDは全48小会計の参考で、今回の詳細七運用へ追加してcacheを読み広げてはいない。','',
        '## 次の原因対照で確かめること','',
        '最初だけ小さくし、現保有の費用後利益で追加リスクを賄える場合だけ増やす案は、「不利な玉でも全段を使える」という今回の構造に対応する。方向別全玉の清算損でまとめて退出する案は、利益玉を外した後の負け在庫を放置する構造に対応する。ただしまだ新手法の成功を意味しない。','',
        '追加予約のリスクを同じ利益で何度も支えないこと、利益玉返済で信用余力が減ること、最初の一枚でも巨大spreadと次気配飛びは負担することを別に固定する必要がある。新規FAK上限と気配差制限の対照には実例上の理由があるが、狭い初期気配でも長い逆行は残り、利確・損切り・次の入り直しまで評価する必要がある。','',
        '正式b結果は指定SHAで一読保全。詳細は独立監査119が保全済みの同bytes六NPZを各一読しただけで、元measurement cache・元prepared・原市場の追加読取と金融再生は0。停止120と未実行120aを別履歴に保ち、今回の分類・図・会計復元を新しい有効性標本に数えない。'])
    md=HERE/'利益玉を回しても不利な在庫が少なくならなかった原因.md'
    assert not md.exists();md.write_text('\n'.join(lines)+'\n',encoding='utf8')
    files=[HERE.parent/name for name in ('read_formal_b.py','trace_formal_b.py','finish_formal_b.py')]
    files += [HERE/name for name in ('正式b完成結果へ切り替える追加読取計画.json','正式b基準赤字六場の保存NPZを各一読する計画.json',
        '独立監査済み同bytes所有六cacheを再利用する追加目録.json','全四十八小会計の独立集計と詳細六場.json',
        '基準赤字六場の利益回転と残損失及び中値Lastの診断.json','基準六場の保存曲線だけの射影.npz')]
    files += [md,png,svg]
    outputs=[dict(path=p.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size) for p in files]
    proof=dict(全合格=True,結果SHA256=small['結果SHA256'],source_SHA256=small['source_SHA256'],outputs=outputs,
        全48条件=True,小会計行=3840,詳細場数=6,詳細政策数=7,両商品net正候補=small['両商品合計正かつ未清算なし'],
        元結果読取=1,元結果追加読取=0,監査119の既所有NPZ各一読=6,元measurement_cache読取=0,原prepared読取=0,原市場読取=0,金融再生=0,
        図=dict(選択key=key,保存曲線='約1分と終端、末尾原行重複だけを除去。',根目視=False,担当目視=False),
        留保='基準赤字上位に条件付けた原因。改善案の救済利益/未測定の退出/未知有効性は算出しない。停止版と未実行版は成績外。')
    out=HERE/'正式bの利益回転と残在庫損失診断の完了証跡.json'
    assert not out.exists();out.write_text(json.dumps(proof,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    print(json.dumps({'全合格':True,'MD':outputs[-3],'PNG':outputs[-2],'証跡':dict(path=out.relative_to(ROOT).as_posix(),SHA256=hashlib.sha256(out.read_bytes()).hexdigest())},ensure_ascii=False))


if __name__=='__main__':
    main()
