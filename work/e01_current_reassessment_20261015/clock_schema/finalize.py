"""頭部射影と小仕様源を、不存在主張の範囲を限定した証跡へ結ぶ。"""

import hashlib
import json
from pathlib import Path
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTROLLER = Path('S:/GitHub/masayoshi4649/kabus-controller')


def digest(path: Path) -> str:
    """
    機能: 既作成の時計射影又は小仕様sourceだけを指紋へ結ぶ。
    引数: path(Path)は所有時計資料又は限定docs/source。
    返り値: strはSHA256。元book/NPZ/金融本文には使わない。
    """
    assert path.resolve().is_relative_to(HERE.resolve()) or path.resolve().is_relative_to((CONTROLLER/'docs').resolve()) or path.resolve() == (ROOT/'work/wave_v103/input/core.py').resolve()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    """
    機能: 頭部読取の実計数とcontroller説明を別資料へ結んで完成する。
    引数: なし。既作成時計射影と説明sourceだけを読む。
    返り値: None。元book追加読取0、共通知見/public編集0。
    """
    observation = HERE/'三十三場六十六先頭のキーと時計候補.json'
    value = json.loads(observation.read_text(encoding='utf-8'))
    assert value['全合格'] and value['読取']['元bookファイルopen'] == value['読取']['原先頭JSON行'] == 66
    docs = {name: digest(CONTROLLER/'docs'/name) for name in ('future-history.md', '08-future-orders.md', 'kabus-controller-openapi.yaml', 'kabu_STATION_API.yaml')}
    sources = {'reader.py': digest(HERE/'reader.py'), '旧NPZ生成源': digest(ROOT/'work/wave_v103/input/core.py')}
    result = dict(全合格=True, 頭部射影SHA256=digest(observation),
        結論MD_SHA256=digest(HERE/'元JSONLとNPZ及びcontrollerの時計の区別.md'), source_SHA256=sources, controller_docs_SHA256=docs,
        上流公式=dict(URL='https://kabucom.github.io/kabusapi/ptal/push.html', 自分で閲覧日='2026-10-15', 現在APIではない=True),
        観測範囲='33場二商品・66先頭だけ。原JSONL全行であらゆる受信時計がないとは断言しない。',
        観測=dict(先頭時計キー種類=6, 頭部受信時計候補キー=0, 頭部共通seq候補キー=0, 頭部BidAsk専用時計=0),
        旧NPZ範囲訂正='受信時計を値として保存しない。received_at_presentは3名の存在確認のみで、他名の受信時計の網羅検査ではない。',
        注意='出来高clock>現値clockの一条件だけで未来情報と断定しない。別clockのmaxを受信時計に合成しない。reason番号の定義はsourceごとに照合。',
        読取= value['読取'], この段の追加原book読取=0, 価格数量保存=0, 価格数量出力=0, 価格数量統計=0,
        金融=0, NPZ=0, 大cache=0, API=0, 公開=0, 共通知見編集=0)
    target = HERE/'頭部と仕様に限定した時計確認の完成.json'
    assert not target.exists()
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(全合格=True, 完成SHA256=digest(target), 頭部射影SHA256=result['頭部射影SHA256'],
        結論MD_SHA256=result['結論MD_SHA256'], 元book頭部66open=True, 追加原book=0, 金融=0, API=0), ensure_ascii=False))


if __name__ == '__main__':
    main()
