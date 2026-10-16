"""多数の相関した特徴をL2で抑え、過去場だけで両方向を別に学習する。"""

import numpy as np


def sigmoid(z: np.ndarray) -> np.ndarray:
    """
    機能: オーバーフローを避けてlogistic関数を計算する。
    引数: z(ndarray[float]) は線形スコア。
    返り値: ndarray[float] は0〜1の見込み値。
    """
    return np.exp(-np.logaddexp(0.,-z))


def fit(X: np.ndarray,y: np.ndarray,weight: np.ndarray,ridge: float = 10.) -> dict:
    """
    機能: 学習行だけで標準化と重み付きL2 logisticをNewton法により計算する。
    引数: X(float[N,P])、y(float[N])、weight(float[N])、ridge(float)。
    返り値: dict は有限JSONへ変換可能なモデル。外部データ・時刻・未来ラベルを参照しない。
    """
    X=np.asarray(X,np.float64);y=np.asarray(y,np.float64);weight=np.asarray(weight,np.float64)
    assert X.ndim==2 and len(X)>0 and X.shape[1]>0
    assert y.shape==weight.shape==(len(X),) and np.isfinite(X).all()
    assert np.isin(y,(0.,1.)).all() and np.isfinite(weight).all() and (weight>0).all() and ridge>0
    weights=weight/weight.sum()*len(X)
    mean=np.average(X,axis=0,weights=weights)
    variance=np.average((X-mean)**2,axis=0,weights=weights)
    active=np.flatnonzero(variance>1e-12)
    scale=np.sqrt(variance[active])
    standardized=np.clip((X[:,active]-mean[active])/scale,-8,8)
    design=np.column_stack((np.ones(len(X)),standardized))
    coefficient=np.zeros(design.shape[1])
    fraction=float(np.average(y,weights=weights))
    prior=np.clip(fraction,1e-6,1-1e-6)
    coefficient[0]=np.log(prior/(1-prior))
    penalty=np.full(len(coefficient),ridge);penalty[0]=0.
    iterations=0
    if 0<fraction<1 and len(active):
        for iteration in range(50):
            iterations=iteration+1
            linear=design@coefficient
            probability=sigmoid(linear)
            gradient=design.T@(weights*(probability-y))+penalty*coefficient
            curvature=weights*np.maximum(probability*(1-probability),1e-9)
            hessian=design.T@(curvature[:,None]*design)+np.diag(penalty)
            hessian[0,0]+=1e-9
            delta=np.linalg.solve(hessian,gradient)
            loss=float(np.dot(weights,np.logaddexp(0.,linear)-y*linear)+.5*np.dot(penalty,coefficient**2))
            step=1.
            while step>=1/1024:
                proposed=coefficient-step*delta
                new_linear=design@proposed
                new_loss=float(np.dot(weights,np.logaddexp(0.,new_linear)-y*new_linear)+.5*np.dot(penalty,proposed**2))
                if new_loss<=loss+1e-10:break
                step*=.5
            if step<1/1024:break
            coefficient=proposed
            if np.max(np.abs(step*delta))<1e-7:break
    assert np.isfinite(coefficient).all()
    return dict(input_columns=X.shape[1],active=active.tolist(),mean=mean[active].tolist(),scale=scale.tolist(),
        coefficient=coefficient.tolist(),ridge=float(ridge),iterations=iterations,training_rows=len(X),
        training_rate=fraction,clipping=8.,method='場均等weight・学習行だけの標準化・L2 logistic')


def predict(model: dict,X: np.ndarray) -> np.ndarray:
    """
    機能: 固定済み学習モデルを追加場へそのまま適用する。
    引数: model(dict)、X(float[N,P]) はモデルと当時特徴。
    返り値: ndarray[float] は見込み値。追加場の平均やラベルで再標準化しない。
    """
    X=np.asarray(X,np.float64)
    assert X.ndim==2 and X.shape[1]==model['input_columns'] and np.isfinite(X).all()
    active=np.array(model['active'],np.int64)
    z=np.clip((X[:,active]-np.array(model['mean']))/np.array(model['scale']),-8,8)
    coefficient=np.array(model['coefficient'])
    return sigmoid(coefficient[0]+z@coefficient[1:])


def publications(long: np.ndarray,short: np.ndarray,eligible: np.ndarray,threshold: float) -> np.ndarray:
    """
    機能: 高い方の見込みが閾値以上かつ差0.1以上となった状態変化だけを公開する。
    引数: long/short(float[N])、eligible(bool[N])、threshold(float)。
    返り値: ndarray[int8]。同状態持続中の毎分連射を避ける。
    """
    assert long.shape==short.shape==eligible.shape and eligible.dtype==bool
    assert np.isfinite(long).all() and np.isfinite(short).all()
    state=np.zeros(len(long),np.int8)
    state[eligible&(long>=threshold)&(long-short>=.10)]=1
    state[eligible&(short>=threshold)&(short-long>=.10)]=-1
    previous=np.r_[0,state[:-1]]
    return np.where(state!=previous,state,0).astype(np.int8)
