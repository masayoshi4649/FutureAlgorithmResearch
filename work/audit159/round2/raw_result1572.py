"""第2巡の保存支持を、売買条件を動かさず正常過去端から独立再計算する。"""

import math
import numpy as np


def window1572(market: dict,index: int,horizon: float,normalize: bool) -> dict:
    """現在と許容15秒内の最後の正常過去端から価格比又は換算速度を計算する。

    引数: market(dict)、index(int)、horizon(float)、normalize(bool)。返り値: dictは窓の観測値。
    """
    result={"Known":False,"CurrentAt":0.,"EndpointAt":0.,"Elapsed":0.,"Delay":0.,"RawReturn":0.,"Value":0.,"IntermediateBad":0}
    if index<0:return result
    at=float(market["time"][index]);result["CurrentAt"]=at
    if not market["valid"][index] or not math.isfinite(market["mid"][index]) or market["mid"][index]<=0:return result
    j=int(np.searchsorted(market["time"],at-horizon,side="right"))-1
    while j>=0 and not market["valid"][j]:j-=1
    # ----------------------------------------
    # 保存器は各市場の最新時計から340秒だけ保持するため、失効済み端のメタデータも残さない。
    oldest=int(np.searchsorted(market["time"],at-340,side="left"))
    if j<oldest:return result
    result.update(EndpointAt=float(market["time"][j]),Elapsed=float(at-market["time"][j]),Delay=float(at-horizon-market["time"][j]),IntermediateBad=int(market["bad"][index]-market["bad"][j]))
    if result["Delay"]>15 or result["Elapsed"]<=0:return result
    past=float(market["mid"][j])
    if past<=0 or not math.isfinite(past):return result
    value=10000*(market["mid"][index]/past-1)
    if not math.isfinite(value):return result
    result.update(RawReturn=float(value),Value=float(value*(horizon/result["Elapsed"] if normalize else 1)),Known=True)
    return result


def support_at1572(own: dict,peer: dict,index: int,side: int) -> dict:
    """自己価格を必須、相手とOFIを個別の補助として支持を構成する。

    引数: own/peer(dict)、index/side(int)。返り値: dictは保存JSONと同名の数値・既知フラグ。
    """
    at=float(own["time"][index]);components={"OwnKnown":False,"PeerKnown":False,"OFIKnown":False,"Windows":{}}
    result={k:0. for k in ("OwnAt","PeerAt","Own5","Own15","Own120","Own300","Peer120","OFI30","M","T","Opp")}
    result.update(Known=False,OwnAt=at,components=components)
    if not own["valid"][index]:return result
    components["OwnKnown"]=True
    for key,seconds in (("Own5",5),("Own15",15),("Own120",120),("Own300",300)):
        w=window1572(own,index,seconds,seconds<=15);components["Windows"][key.lower()]=w
        if w["Known"]:result[key]=w["Value"]
        else:components["OwnKnown"]=False
    j=int(np.searchsorted(peer["time"],at,side="left"))-1
    if j>=0:
        result["PeerAt"]=float(peer["time"][j])
        if at-peer["time"][j]<=15:
            w=window1572(peer,j,120,False);components["Windows"]["peer120"]=w;components["PeerKnown"]=w["Known"]
            if w["Known"]:result["Peer120"]=w["Value"]
    k=int(np.searchsorted(own["time"],at-30,side="left"))-1
    if own["ofi_valid"][index] and k>=0 and own["bad"][index]==own["bad"][k] and own["count"][index]-own["count"][k]>=2:
        value=(own["sum"][index]-own["sum"][k])/(own["count"][index]-own["count"][k])
        if math.isfinite(value):result["OFI30"]=float(value);components["OFIKnown"]=True
    if not components["OwnKnown"]:return result
    clip=lambda value:max(-1,min(1,value))
    result["M"]=max(0,.45*clip(side*result["Own120"]/8)+.35*clip(side*result["Own300"]/16)+.20*clip(side*result["Peer120"]/8))
    short=.45*clip(side*result["Own15"]/3)+.35*clip(side*result["Own5"]/1.5)+.20*clip(side*result["OFI30"]/.05)
    result.update(T=max(0,short),Opp=max(0,-short),Known=True)
    return result
