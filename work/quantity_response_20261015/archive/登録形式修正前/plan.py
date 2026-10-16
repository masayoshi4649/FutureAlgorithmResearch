"""数量応答の非金融測定で使う目録と事前仕様を管理する。"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PUBLIC = ROOT / 'アルゴリズム調査/00114_公表活動と表示数量の維持後の価格応答'
TRIAL = '114_全原行の公表活動Q0到達と表示数量後の純価格先着'
CONTRACT = ROOT / 'work/e01_current_reassessment_20261015/quantity_contract/旧33の44列保存位置と新2の未読可用性.json'
JST = timezone(timedelta(hours=9))
SOURCE_NAMES = ('plan.py', 'run.py', 'engine.py', 'artificial_engine.py', 'artificial_run.py')

# ----------------------------------------


def digest(path: Path) -> str:
    """
    機能: 小さい研究ソースと出力資料の指紋を求める。
    引数: path(Path) は対象の位置。
    返り値: str はSHA256。原NPZの二重読取には使わない。
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    """
    機能: 事前固定又は小さい研究目録を読む。
    引数: path(Path) はJSONの位置。
    返り値: dict は内容。金融結果・原板は対象としない。
    """
    return json.loads(path.read_text(encoding='utf-8'))


def write(path: Path, value: dict) -> None:
    """
    機能: 自分の研究領域へ非有限値を禁止したJSONを新規保存する。
    引数: path(Path)、value(dict) は位置と内容。
    返り値: None。過去出力と原データの上書きを拒否する。
    """
    assert path.resolve().is_relative_to(HERE) and not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def sources() -> dict:
    """
    機能: 実測と人工で使う五ソースを指紋にする。
    引数: なし。
    返り値: dict[str,str] はルート相対位置とSHA256。
    """
    return {str((HERE / name).relative_to(ROOT)).replace('\\', '/'): digest(HERE / name)
            for name in SOURCE_NAMES}


def bounds(session: str) -> tuple[float, float]:
    """
    機能: 旧44列入力と同じ場内観測区間を求める。
    引数: session(str) は日付とDay又はNight。
    返り値: tuple[float,float] は開始と排他的終了のepoch秒。
    """
    date, kind = session.rsplit('_', 1)
    day = datetime.fromisoformat(date).replace(tzinfo=JST)
    if kind == 'Day':
        start, end = day + timedelta(hours=8, minutes=45), day + timedelta(hours=15, minutes=40)
    elif kind == 'Night':
        start, end = day + timedelta(hours=17), day + timedelta(days=1, hours=5, minutes=55)
    else:
        raise ValueError(session)
    return start.timestamp(), end.timestamp()

# ----------------------------------------


def prepare() -> None:
    """
    機能: 旧小目録を一読し、数量本体を開く前に66入力と観測仕様を保存する。
    引数: なし。
    返り値: None。原NPZ・原板・足・金融・APIは読まない。
    """
    assert not (HERE / '入力と観測の小固定.json').exists()
    write(HERE / '小目録の一読目的.json', dict(
        目的='旧33場66口座の既存44列NPZの位置・記録済みSHAと仕様のみを固定する。',
        小目録=1, NPZ=0, 原板=0, 金融=0, API=0))
    raw = CONTRACT.read_bytes()
    old = json.loads(raw.decode('utf-8'))
    assert old['全合格'] and len(old['sessions']) == 33 and len(old['旧保存']) == 66
    rows = []
    for item in old['旧保存']:
        packet = item['NPZ']
        path = ROOT / packet['path']
        stat = path.stat()
        assert stat.st_size == packet['bytes'] and stat.st_mtime_ns == packet['mtime_ns']
        assert path.resolve().is_relative_to(ROOT / 'work')
        rows.append(dict(session=item['session'], symbol=item['symbol'], path=packet['path'],
                         SHA256=item['目録に記録された出力SHA256'], bytes=stat.st_size,
                         mtime_ns=stat.st_mtime_ns, bounds=list(bounds(item['session']))))
    assert len({(row['session'], row['symbol']) for row in rows}) == 66
    assert {row['session'] for row in rows} == set(old['sessions'])
    value = dict(全合格=True, 金融=False, sessions=old['sessions'], inputs=rows,
                 schema=old['columns'], 原目録SHA256=hashlib.sha256(raw).hexdigest(),
                 追加二場='対象外・本文未読を維持',
                 観測T=dict(TOPIX=.5, NK225=10),
                 観測窓='旧入力と同じDay08:45以上15:40未満、Night17:00以上翌05:55未満',
                 確認するもの='同じ両気配中の公表総出来高Q0初回到達時の数量分類と、その後の両気配±1T先着',
                 未測='売買、費用回収、収益、真攻撃量、真補充、テクニカル水準、二市場同期、到達後最大値',
                 読取予定=dict(NPZ=66, 同bytesSHA検算=66, 原板=0, 足=0, 金融=0, API=0))
    write(HERE / '入力と観測の小固定.json', value)
    print(json.dumps(dict(全合格=True, 小目録=1, NPZ=0, 口座数=len(rows)), ensure_ascii=False))


def freeze() -> None:
    """
    機能: 人工・独立監査の後にソースと入力仕様を固定して試行照合案を作る。
    引数: なし。
    返り値: None。登録・実測を自動実行しない。
    """
    fixed = read(HERE / '入力と観測の小固定.json')
    assert fixed['全合格'] and len(fixed['inputs']) == 66
    audit = read(HERE / '本体初読前の人工と独立監査.json')
    assert audit['全合格'] and audit['入力本文'] == 0 and audit['source_SHA256'] == sources()
    for evidence in audit['evidence']:
        assert digest(ROOT / evidence['path']) == evidence['SHA256']
    proposal = dict(id=TRIAL, name='全原行の公表活動と数量維持後の価格応答', purpose='新仮説',
                    question='同じBBOのまま公表総量が初期反対数量Q0へ達した初回に、数量の初期比維持群と減少群で、その後の両BBO1T先着は異なるか。',
                    change='全raw・実表示Qty・公表総増差・初回公開・純将来先着。注文と損益は計算しない。',
                    repeat_reason='旧54は表示減少後回復が中心、113は票件数であり、同時数量維持と公表活動の純将来先着を測っていない。',
                    compares_to=[], evidence=[], spec=dict(
                        entry=dict(用途='非金融の観測点', type0='最初known正ΔVのLast位置proxy',
                                   type1='同BBOの初期反対Q0へ全価格公表ΔV累計が初回>=',
                                   初行差='不採用', 最初方向不明='episode中凍結し方向付き公開なし',
                                   数量未知='両最良Qty必要、片側不明でもepisode終了'),
                        management=dict(用途='売買ではない', 累積='unknownをまたがない',
                                        同一episode='各type一回', テクニカル='今回未測'),
                        exit=dict(用途='価格応答の終点', 評価='公開後の純raw順・両BBO同方向1T又は反対1Tの先着',
                                  未知='必要価格のみで打切。後続Qty/volumeの欠測では打切らない',
                                  末尾='未解決として別母数。勝敗へ補完しない'),
                        allocation='売買なし。両商品を個別集計し、各場・方向・昼夜を併記',
                        costs='売買なし。1T先着を手数料後利益と呼ばない',
                        execution='注文・金融なし。ラージBBOと自身原seqによる価格応答のみ',
                        data=dict(sessions=fixed['sessions'], inputs=fixed['inputs'], schema=fixed['schema'],
                                  追加二場='対象外・本文未読'),
                        implementation=dict(sources=sources(), Numba='新core cache=False',
                                            外部経済import='なし')))
    write(HERE / '試行計画.json', proposal)
    write(HERE / '実測前の正式固定.json', dict(全合格=True, 金融=False,
          source_SHA256=sources(), input_fixed_SHA256=digest(HERE / '入力と観測の小固定.json'),
          proposal_SHA256=digest(HERE / '試行計画.json'),
          audit_SHA256=digest(HERE / '本体初読前の人工と独立監査.json'), 自動再実行=False))
    print(json.dumps(dict(全合格=True, ソース数=len(sources()), 金融=False), ensure_ascii=False))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'freeze'))
    arguments = parser.parse_args()
    prepare() if arguments.command == 'prepare' else freeze()
