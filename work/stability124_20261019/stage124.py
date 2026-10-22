"""追加一セッションの六原本を数値解釈せず一読複写する。"""

import hashlib
from common124 import HERE,ROOT,SCENE,read,save


def main() -> None:
    """
    機能: 原本をreadonlyで一回複写し、指紋・サイズと不変を保存する。
    引数: なし。対象は両先物の10月19日デイ、bookと二CSVだけ。
    返り値: None。金融・価格抽出・現在APIは実行しない。
    """
    plans=[]
    for symbol in ('TOPIX','NK225'):
        for kind,ext in [('book','.jsonl'),('candle_1min','.csv'),('candle_5min','.csv')]:
            origin=ROOT/kind/symbol/(SCENE+ext);stat=origin.stat()
            target=HERE/'inputs'/kind/symbol/(SCENE+ext)
            assert not target.exists()
            plans.append(dict(session=SCENE,symbol=symbol,kind=kind,path=origin.relative_to(ROOT).as_posix(),
                staged_path=target.relative_to(ROOT).as_posix(),bytes=stat.st_size,mtime_ns=stat.st_mtime_ns))
    save(HERE/'追加原本のstat計画.json',dict(inputs=plans,financial_accounts=0,numerical_reads=0))

    # ----------------------------------------
    # 各原本は一つのstreamだけで指紋を採り、原本へ書き込まない。
    items=[]
    for item in plans:
        origin=ROOT/item['path'];target=ROOT/item['staged_path'];target.parent.mkdir(parents=True,exist_ok=True)
        hasher=hashlib.sha256();size=0
        with origin.open('rb') as source,target.open('xb') as output:
            while block:=source.read(8388608):
                hasher.update(block);size+=len(block);output.write(block)
        after=origin.stat()
        assert (after.st_size,after.st_mtime_ns)==(item['bytes'],item['mtime_ns']) and size==item['bytes']
        items.append(dict(item,sha256=hasher.hexdigest()))
        print(item['kind'],item['symbol'],'複写完了',flush=True)
    save(HERE/'追加原本入力目録.json',dict(passed=True,sessions=[SCENE],inputs=items,
        original_reads=6,numerical_reads=0,financial_accounts=0,API=0,real_orders=0))


if __name__=='__main__':
    main()
