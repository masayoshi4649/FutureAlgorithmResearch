"""保存CSVの時刻を直さず、旧観測窓の外側にある合法末尾だけを表示から外す。"""

import csv
import hashlib
from io import StringIO
import math
from pathlib import Path

import clock_adapter as clock


def view(payload: bytes, start: float, end: float) -> tuple[bytes,dict]:
    """
    機能: 原CSVを検証し、旧[start,end)内の足だけを同順序・同値で表示する。
    引数: payload(bytes)は原bytes、start/end(float)は旧観測窓のepoch秒。
    返り値: tuple[bytes,dict]はconsumer表示と除外原row・元time等の診断。
        全原行でTZ付き有限時計・開始以降・厳密昇順を要求する。
        旧窓終端から実セッション終端までの5分以内だけを合法末尾とする。
    """
    reader=csv.DictReader(StringIO(payload.decode('utf-8-sig'),newline=''),strict=True)
    fields=reader.fieldnames
    assert fields and 'time' in fields and len(fields)==len(set(fields)), 'CSV時刻列又は重複列'
    previous=-math.inf;kept=[];excluded=[];count=0
    for index,row in enumerate(reader):
        assert None not in row and all(v is not None for v in row.values()), ('CSV列数不一致',index)
        stamp=clock.price_clock(row['time'])
        assert math.isfinite(stamp) and stamp>=start, ('CSV時計不明又は開始前',index,row['time'])
        assert stamp>previous, ('CSV時計重複又は逆行',index,row['time'])
        assert stamp<=end+300., ('実セッション終了を越すCSV',index,row['time'])
        previous=stamp;count=index+1
        if stamp<end:kept.append(row)
        else:excluded.append(dict(original_row=index,time=row['time'],epoch=stamp,reason='旧観測窓終端以上の合法末尾'))
    assert kept, '旧観測窓内のCSVが空'
    output=StringIO(newline='');writer=csv.DictWriter(output,fieldnames=fields,lineterminator='\n')
    writer.writeheader();writer.writerows(kept)
    encoded=output.getvalue().encode('utf8')
    return encoded,dict(original_rows=count,kept_rows=len(kept),excluded_rows=len(excluded),excluded=excluded,
        original_sha256=hashlib.sha256(payload).hexdigest(),view_sha256=hashlib.sha256(encoded).hexdigest(),
        first=kept[0]['time'],last=kept[-1]['time'],window=[start,end],tail_latest=end+300.,
        原時計修正=False,sort=False,前開始又は不正時計拒否=True)


def write(payload: bytes,target: Path,expected_sha: str,start: float,end: float) -> dict:
    """
    機能: 原bytes指紋を照合してから、別の所有位置へ窓内表示だけを保存する。
    引数: payload(bytes)、target(Path)、expected_sha(str)、start/end(float)は原内容と保存先・指紋・窓。
    返り値: dictは除外原row・元timeと同一性。元原本は変更しない。
    """
    assert hashlib.sha256(payload).hexdigest()==expected_sha and not target.exists()
    encoded,diagnosis=view(payload,start,end)
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(encoded)
    return diagnosis
