"""保存済み非金融観測の分母と限界を、小さい日本語資料へ整理する。"""

from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path


HERE=Path(__file__).resolve().parent


def stamp(value: float | None) -> str | None:
    """
    機能: 保存価格代理時計を日本時間の表示へ変換する。
    引数: value(float|None)はepoch秒又は不明。
    返り値: str|Noneは代理時計の表示。受信時刻へ読み替えない。
    """
    return datetime.fromtimestamp(value,timezone(timedelta(hours=9))).isoformat() if value is not None else None


def main() -> None:
    """
    機能: 当時観測と事後待機観測を分離した小結だけを保存する。
    引数: なし。
    返り値: None。巨大入力・原本・API・金融は読まず、完成JSONのみを読む。
    """
    source=HERE/'R反発判断の原値と出来高可用性.json';saved=source.read_bytes();j=json.loads(saved)
    assert j['全合格']
    table=[];examples=[]
    for identifier in j['ids']:
        for symbol in ('TOPIX','NK225'):
            a=j['aggregate'][identifier][symbol]['受付内'];n=a['判断候補数'];c=a['件数'];w=a['公開後待機観測']
            table.append(dict(条件=identifier,商品=symbol,受付内候補=n,
                原Last前後既知=c['last_pair_known'],出来高差usable既知=c['volume_delta_usable'],
                当行出来高増=c['volume_increased'],当行出来高増割合=100*c['volume_increased']/n,
                出来高増かつ反発方向へLast変化=a['群'].get('出来高増・現在値が反発方向へ変化',0),
                出来高増かつLast同価格=a['群'].get('出来高増・現在値が同価格',0),
                出来高時計同値でも正増=a['出来高時計同値でも出来高増'],
                公開後候補待機数=w['受付内待機候補数'],BBO到達候補=w['最初BBO到達候補数'],
                BBOより前のLast一呼値通過と正出来高増=w['BBO到達群でBBOより前の通過'],
                BBO同原行の通過=w['BBO到達同原行の通過'],
                観測当行pointer=f'/aggregate/{identifier}/{symbol}/受付内',
                観測待機pointer=f'/aggregate/{identifier}/{symbol}/受付内/公開後待機観測'))
            rows=j['observations'][identifier][symbol]
            selected=[r for r in rows if r['reception'] and r['pending_observation']['終点種別']=='最初BBO到達'
                and r['pending_observation']['終点より前のLast一呼値通過と出来高増']]
            if selected:
                r=selected[0];p=r['pending_observation'];first=p['最初の通過原行'];end=p['終点原行']
                examples.append(dict(条件=identifier,商品=symbol,場=r['session'],方向='買い' if r['side']==1 else '売り',
                    公開代理時刻=stamp(r['current']['price_time_s']),公開原seq=r['current']['raw_seq'],固定指値=r['declared_limit'],
                    先のLast通過代理時刻=stamp(first['price_time_s']),先の原seq=first['raw_seq'],先のLast=first['last'],先の累計出来高=first['volume'],
                    BBO到達代理時刻=stamp(end['price_time_s']),BBO到達原seq=end['raw_seq'],BBO到達Last=end['last'],BBO到達累計出来高=end['volume'],
                    BBO到達bid=end['bid'],BBO到達ask=end['ask'],
                    注意='同価格時計の中でも原seqは前後する。この先行観測がmini/microのnative指値を約定させた証明ではない。'))
    result=dict(全合格=True,目的='取引成立の新しい情報が当時R反発候補にあるか。新政策の有効性は未測定。',
        条件別観測=table,具体的な原seq差=examples,
        結論=['原CurrentPriceと公表累計出来高は保存原行NPZにあり、対象R候補の全件で前後Last及びusable累計差は既知だった。',
            'M2受付内で同原行の正出来高増はTOP55/286(19.2%)、NK24/278(8.6%)。約定値も反発方向へ変化したのは15/286(5.2%)、7/278(2.5%)。',
            '出来高時計同値の正増はM2TOP27/NK6、M1TOP50/NK21。この保存入力では時計停滞を出来高停止へ代用できない。',
            'Lastが同価格でも出来高は増え得るため、Last変化必須は同価格で起きた売買も除く。出来高増なしの単一原行から前の反発が虚偽だったとは言えない。',
            'FirstLastTouch＋正増による因果的な価格通過モデルを作る素材はある。ただしnative指値の先着成立・queue順位・mini/micro板・真の約定主体は未確認。'],
        当時特徴と事後観測の境界='候補当行の有無は当時特徴。候補後Last通過/BBO到達は事後の観測差であり、入口へ戻さず利益ラベルにもしていない。',
        制限=['M1/M2の候補は同じ相場を共有し重複する。2群を独立金融標本として足さない。',
            '受付内候補は保有/共有休止等で不採用だったものも含み、実未約定注文や決済数とは違う。',
            '原seqはファイル内順序、CurrentPriceTimeとTradingVolumeTimeは別時計。全8,492,131原行に受信時刻保存はない。',
            '累計出来高増とLast対直前BBOは攻撃側の代理だけ。取消、約定全体、同一注文の補充を同定しない。',
            '現在ナイト未読。source/registry/取得器/旧inputに変更なし。'],
        入力読取=j['保存入力読取'],原本読取=0,API取得=0,金融再生=0,金融結果読取=0,
        source=dict(path=source.relative_to(HERE.parents[2]).as_posix(),SHA256=hashlib.sha256(saved).hexdigest()),
        事前固定SHA256=j['事前固定SHA256'])
    target=HERE/'約定更新代理の可用性と指値観測差の小結.json';assert not target.exists()
    target.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8',newline='\n')
    print(hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=='__main__':main()
