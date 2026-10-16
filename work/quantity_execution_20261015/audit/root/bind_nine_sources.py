"""金融前の小目録と独立検査を、現在の九源へ束縛する。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[1]


def sha(path: Path) -> str:
    """
    機能: 小source・小目録・監査証跡だけを指紋化する。
    引数: path(Path)。
    返り値: str SHA256。原NPZへ使用しない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(name: str, path: Path):
    """
    機能: 自動実行部の無いsource定義を読み込む。
    引数: name(str)、path(Path)。
    返り値: module 純関数の定義。
    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def main() -> None:
    """
    機能: 新小目録一読と既存独立証跡を現九源へ接続する。
    引数: なし。
    返り値: None。正式freeze・登録・新金融は行わない。
    """
    intent = HERE / '九源束縛の小目録読取目的.json'
    assert not intent.exists()
    intent.write_text(json.dumps(dict(目的='新115小目録の33×2対応・schema・公開列・固定時刻だけを検査する。',
        小固定一読=1, 原NPZ=0, 保存eventNPZ=0, 過去114結果=0, 新金融=0, API=0),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    plan = load('九源の計画定義', BASE / 'plan.py')
    contract = load('九源の入力契約定義', BASE / 'input_contract.py')
    producer = load('生成元の純schema', HERE / '指定二源と生成元の私有複製/producer.py')
    source = plan.sources()
    assert len(source) == 9
    selected = [HERE/'入力契約と時間八部品のSOURCE_ONLY独立接続_v2.json',
                HERE/'金融ガードと一回decode及び可逆保存のSOURCE_ONLY独立接続.json',
                HERE/'各脚気配と税込注文料の独立分解及び可逆合成台帳の接続.json',
                BASE/'audit/owned/完成三源と純会計及び場境界の独立接続まとめ.json']
    details = []
    for path in selected:
        proof = json.loads(path.read_text(encoding='utf-8'))
        assert proof['全合格']
        for name, digest in proof['source_SHA256'].items():
            key = name if '/' in name else (BASE/name).relative_to(ROOT).as_posix()
            assert source[key] == digest, (path, name)
        details.append(dict(path=path.relative_to(ROOT).as_posix(), SHA256=sha(path)))
    current = json.loads((BASE/'入力と保存公開の固定.json').read_bytes())
    assert current['全合格'] and current['schema'] == producer.schema()['columns']
    sessions, inputs = current['sessions'], current['inputs']
    assert len(sessions) == len(set(sessions)) == 33 and len(inputs) == 66
    assert not {'2026-10-13_Night','2026-10-14_Day'} & set(sessions)
    pairs = [(x['raw']['session'],x['raw']['symbol']) for x in inputs]
    assert len(set(pairs)) == 66 and set(pairs) == {(s,y) for s in sessions for y in ('TOPIX','NK225')}
    assert len({x['raw']['path'] for x in inputs}) == len({x['events']['path'] for x in inputs}) == 66
    checks = 6
    jst = timezone(timedelta(hours=9))
    for item in inputs:
        raw, event = item['raw'], item['events']
        assert item['fields'] == contract.FIELDS and len(item['fields']) == 31
        assert len(raw['bounds']) == 2 and raw['bounds'][0] < raw['bounds'][1]
        assert item['time_policy'] == plan.time_policy(raw['session'],*raw['bounds'])
        a,b = [datetime.fromtimestamp(t,jst) for t in raw['bounds']]
        day,kind = raw['session'].rsplit('_',1)
        assert a.date().isoformat() == day and kind in ('Day','Night')
        if kind == 'Day':
            assert (a.hour,a.minute,b.hour,b.minute) == (8,45,15,40) and b.date() == a.date()
        else:
            assert (a.hour,a.minute,b.hour,b.minute) == (17,0,5,55) and b.date() == (a+timedelta(days=1)).date()
        assert item['raw_rows'] > 0 and event['n'] >= 0
        for info in (raw,event):
            assert not Path(info['path']).is_absolute() and '..' not in Path(info['path']).parts
            assert info['bytes'] > 0 and len(info['SHA256']) == 64
        checks += 8
    assert current['観測T'] == dict(TOPIX=.5,NK225=10.)
    assert source == plan.sources()
    result = dict(全合格=True, source_SHA256=source, 小目録独立確認数=checks+2, 新金融=0,
        原入力=0, 原NPZ=0, 保存eventNPZ=0, 過去金融=0, 原API=0,
        入力目録=dict(path=(BASE/'入力と保存公開の固定.json').relative_to(ROOT).as_posix(),SHA256=sha(BASE/'入力と保存公開の固定.json'),
                    新小目録本文読取=1, 対応='33旧場×2商品、観測raw66と保存event66。新2場は含まない。'),
        evidence=details,
        独立確認=dict(入力契約と八部品=118, 不整合拒否=28, 金融前ガードと可逆読取配線=1807,
                       ガード等拒否=17, 各脚税込料金とBBOの恒等式と合成台帳=524),
        重要境界=[
            'normal_execution_rowは未対応−1・正常index0以上のint32逆写像。元producerの純抽出へ接続し、boolと誤認しない。',
            '価格knownと両数量knownは別。新規/返済の執行正常は価格knownと両数量known正で、旧inverse正常IDを使わない。',
            '保存eventの31列canonical一致・float64・9原値と公開原行を検査。未来結果配列をdecode/返却しない。',
            '同じNPZ bytes一回でSHA照合とdecodeをする。bytesに含まれる未来配列を一切物理読取していないという意味ではない。',
            'RLEは全原行16列・NaN・順序を復元する。maskは曲線列14/15へ保存される。',
            '中値差−気配横断−税込注文料＝実収支。中値差を実際の利益へ数えず、税や遅延費をさらに二重控除しない。',
            'Day新規09:15、Night17:05、NY通常09:30前後15分をDST変換。固定33場以外の休場対応は未保証。',
            '全33場の平均netがTOP10万円床。NK円床は未指定。無取引を勝ちへ数えず、親平均と場平均を混同しない。'
        ],
        限界='正式freeze/試行照合/登録は本監査で実行0。finance.guardの合成一致・不一致拒否を確認したもので、現物登録との接続はroot終端後に別途。実データ有効性・実注文遅延・mini/micro板列順・部分約定は未測定。',
        False保全='audit/root/archive/人工JSONの銘柄識別を欠いた初版False。純素材にSymbolName/Exchangeを付け忘れ、producerで停止。sourceの不具合ではなくchecker素材だけ訂正。',
        独立源_SHA256=sha(Path(__file__)))
    output = HERE/'完成九sourceと入力境界及び金融前ガードの独立接続.json'
    assert not output.exists()
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    print(json.dumps(dict(全合格=True,確認数=checks+2,path=str(output),SHA256=sha(output)),ensure_ascii=False))


if __name__ == '__main__':
    main()
