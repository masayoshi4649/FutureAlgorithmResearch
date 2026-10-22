"""原時計を直さず、因果的な高水位資格だけを旧consumerの入力表示へ接続する。"""

from copy import deepcopy
from datetime import datetime
import csv
import hashlib
import json
import math
from pathlib import Path


REASONS = {1:'価格時計不明又はtimezoneなし',2:'Last非有限又は非正',4:'観測窓外',8:'採用済最大価格時計より過去'}


def validate_csv(path: Path, start: float, end: float) -> dict:
    """
    機能: 登録後の所有CSVに対し、足時計が場内かつ厳密単調であることを検査する。
    引数: path(Path)、start/end(float)は所有CSVと観測窓。
    返り値: dictは本数と最初/最後の元時計。加算・sort・除外で救済しない。
    """
    previous=-math.inf;first=None;last=None;count=0
    with path.open('r',encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream)
        assert reader.fieldnames and 'time' in reader.fieldnames, ('CSV時計列欠測',str(path))
        for index,row in enumerate(reader):
            stamp=price_clock(row['time'])
            assert math.isfinite(stamp) and start<=stamp<end, ('CSV時計場外又は不明',str(path),index,row['time'])
            assert stamp>previous, ('CSV時計重複又は逆行',str(path),index,row['time'])
            previous=stamp;first=row['time'] if first is None else first;last=row['time'];count=index+1
    assert count>0, ('CSV空',str(path))
    return dict(rows=count,first=first,last=last,window=[start,end],strictly_increasing=True,
                原時刻修正=False,sort=False,不適合時金融停止=True)


def price_clock(value: object) -> float:
    """
    機能: 元価格時計だけをepochへ変換し、不明値を推定しない。
    引数: value(object)は原CurrentPriceTime。
    返り値: floatは有限epoch又はNaN。日付変更は一切行わない。
    """
    if not isinstance(value,str) or not value:
        return math.nan
    try:
        parsed=datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return math.nan
        return parsed.timestamp()
    except (ValueError,TypeError,OverflowError,OSError):
        return math.nan


def step(raw: dict, highwater: float, start: float, end: float) -> tuple[dict,float,int]:
    """
    機能: 当行と過去高水位だけで価格資格を判定し、不適格時計を未使用表示にする。
    引数: raw(dict)、highwater/start/end(float)は原行と過去採用最大時計及び観測窓。
    返り値: tuple[dict,float,int]はconsumer表示・更新高水位・不適格理由mask。
    原Last/BBO/数量/出来高/他時計を変更せず、未来行・場末・補正日付を使わない。
    """
    stamp=price_clock(raw.get('CurrentPriceTime'))
    last=raw.get('CurrentPrice')
    last_ok=isinstance(last,(int,float)) and not isinstance(last,bool) and math.isfinite(last) and last>0
    reason=0
    if not math.isfinite(stamp):reason|=1
    if not last_ok:reason|=2
    if math.isfinite(stamp) and not start<=stamp<end:reason|=4
    if math.isfinite(stamp) and stamp<highwater:reason|=8
    output=dict(raw)
    if reason:
        output['CurrentPriceTime']=None
    else:
        highwater=stamp
    return output,highwater,reason


def transform(rows: list[dict], start: float, end: float) -> tuple[list[dict],list[int]]:
    """
    機能: 合成用に原順・行数を保持した入力表示と資格理由を作る。
    引数: rows(list[dict])、start/end(float)は原行群と観測窓。
    返り値: tuple[list[dict],list[int]]は同数の表示行と理由mask。
    """
    highwater=-math.inf
    outputs,reasons=[],[]
    for raw in rows:
        output,highwater,reason=step(raw,highwater,start,end)
        outputs.append(output);reasons.append(reason)
    return outputs,reasons


def write_view(source: Path, target: Path, expected_sha: str, start: float, end: float) -> dict:
    """
    機能: 正式登録後だけ既stage所有原本を一読し、seq保持の使用資格表示を別保存する。
    引数: source/target(Path)、expected_sha(str)、start/end(float)は所有原本と固定指紋・窓。
    返り値: dictは指紋・行数・理由件数・採否RLE。元原本及び元stageを変更しない。
    """
    assert source!=target and not target.exists()
    target.parent.mkdir(parents=True,exist_ok=True)
    highwater=-math.inf;before=hashlib.sha256();after=hashlib.sha256()
    counts={str(k):0 for k in REASONS};n=0;accepted=0;last_state=None;runs=[]
    with source.open('rb') as stream,target.open('xb') as destination:
        for seq,line in enumerate(stream):
            before.update(line);raw=json.loads(line)
            output,highwater,reason=step(raw,highwater,start,end)
            for bit in REASONS:counts[str(bit)]+=int(bool(reason&bit))
            allowed=reason==0
            if allowed:payload=line
            else:payload=(json.dumps(output,ensure_ascii=False,separators=(',',':'),allow_nan=True)+'\n').encode('utf8')
            destination.write(payload);after.update(payload)
            state=int(reason)
            if state!=last_state:runs.append([seq,state]);last_state=state
            accepted+=int(allowed);n=seq+1
    assert before.hexdigest()==expected_sha
    return dict(original_SHA256=before.hexdigest(),view_SHA256=after.hexdigest(),rows=n,accepted_rows=accepted,
        rejected_rows=n-accepted,reason_counts=counts,reason_runs=runs,sequence='原0base行を削除せず保持',
        原価格時計変更=False,日付推定=False,原本追加読取=0,staged_copy_reads=1,
        表示変更='不適格行のCurrentPriceTimeだけNone。Last/BBO/数量/出来高/他時計は原値のまま。',
        原時計資格='raw44及びW60票は未加工のstage原本から作り、既存のreset/usable/unknownを保持する。')
