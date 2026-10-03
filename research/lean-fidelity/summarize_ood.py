"""Summarize locked OOD predictions; no fitting or threshold selection."""
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

HERE=Path(__file__).parent
RUN='run-20261003T192204Z'

def metrics(rows, temperature, threshold):
    y=np.array([r['label'] for r in rows])
    z=np.array([r['logit'] for r in rows])
    p=1/(1+np.exp(-z/temperature))
    pred=z>=0
    accepted=p>=threshold
    tp=int(((y==1)&pred).sum());tn=int(((y==0)&~pred).sum())
    fp=int(((y==0)&pred).sum());fn=int(((y==1)&~pred).sum())
    n=len(rows);naccept=int(accepted.sum());wrong=int(((y==0)&accepted).sum())
    return dict(n=n,groups=len({r['group'] for r in rows}),positive=int(y.sum()),
        correct=tp+tn,accuracy=(tp+tn)/n,majority_accuracy=max(y.sum(),n-y.sum())/n,
        balanced_accuracy=(tp/(tp+fn)+tn/(tn+fp))/2 if tp+fn and tn+fp else None,
        tp=tp,tn=tn,fp=fp,fn=fn,temperature=temperature,gate_threshold=threshold,
        coverage=naccept/n,accepted=naccept,wrong_accepted=wrong,
        accepted_error=wrong/naccept if naccept else None,
        faithful_recall=int(((y==1)&accepted).sum())/int(y.sum()) if y.sum() else None,
        brier=float(np.mean((p-y)**2)))

def main():
    audit=json.loads((HERE/'artifacts'/RUN/'ood_audit.json').read_text())
    calibration=json.loads((HERE/'reports/full-run-result.json').read_text())['calibration']
    before=audit['predictions']['unfine_tuned'];after=audit['predictions']['fine_tuned']
    assert all(a['id']==b['id'] and a['label']==b['label'] for a,b in zip(before,after)) and len(before)==len(after)
    result={k:v for k,v in audit.items() if k!='predictions'}
    result['calibration']=calibration
    result['gate_note']='Baseline uses its uncalibrated 0.5 classifier threshold; fine-tuned uses frozen ID calibration. Gate operating points are not matched coverage. Main accuracy uses logit >= 0 for both.'
    result['results']=[]
    datasets=list(dict.fromkeys(r['dataset'] for r in before))
    for dataset in datasets:
        for variant,rows in audit['predictions'].items():
            trained=variant=='fine_tuned'
            result['results'].append(dict(dataset=dataset,model=variant,**metrics(
                [r for r in rows if r['dataset']==dataset],
                calibration['temperature'] if trained else 1,
                calibration['accept_threshold'] if trained else .5)))
    result['critic_source_breakdown']=[]
    for source in sorted({r['source'] for r in before if r['dataset']=='CriticLeanBench'}):
        for variant,rows in audit['predictions'].items():
            part=[r for r in rows if r['dataset']=='CriticLeanBench' and r['source']==source]
            result['critic_source_breakdown'].append(dict(source=source,model=variant,
                n=len(part),correct=sum(r['label']==r['predicted'] for r in part),
                accuracy=sum(r['label']==r['predicted'] for r in part)/len(part)))
    # Paired problem-group bootstrap: preserve all candidates of each sampled group.
    pairs=[(a,b) for a,b in zip(before,after) if a['dataset']=='CriticLeanBench']
    groups=list(dict.fromkeys(a['group'] for a,b in pairs))
    sums=np.array([[sum((int(b['predicted']==b['label'])-int(a['predicted']==a['label'])) for a,b in pairs if a['group']==g),sum(a['group']==g for a,b in pairs)] for g in groups])
    rng=np.random.default_rng(42)
    boot=sums[rng.integers(0,len(groups),size=(2000,len(groups)))].sum(axis=1)
    result['critic_accuracy_delta']=dict(delta=float(sums[:,0].sum()/sums[:,1].sum()),
        paired_group_bootstrap_95_ci=np.quantile(boot[:,0]/boot[:,1],[.025,.975]).tolist(),
        groups=len(groups),replicates=2000,seed=42,
        note='Sampling uncertainty only; excludes label uncertainty and training-seed variance.')
    result['app_url']='https://modal.com/apps/arin06/main/ap-On0lGR9m6ovXIR1GsZdAiS'
    (HERE/'reports/ood-comparison.json').write_text(json.dumps(result,indent=2)+'\n')
    # Persist lightweight per-example evidence without redistributing benchmark text.
    (HERE/'reports/ood-predictions.json').write_text(json.dumps(audit['predictions'],indent=2)+'\n')
    labels=['CriticLeanBench\n450 examples','Formal Conjectures*\n6 probes','Tao Analysis I*\n8 probes','Equational Theories*\n8 probes','Lean Machine Learning*\n8 probes']
    fig,ax=plt.subplots(figsize=(11,5.4))
    x=np.arange(len(datasets));width=.36
    for variant,offset,color,label in [('unfine_tuned',-width/2,'#99AAB5','Initial random-head classifier'),('fine_tuned',width/2,'#287A9F','Fine-tuned classifier')]:
        vals=[next(r['accuracy'] for r in result['results'] if r['dataset']==d and r['model']==variant)*100 for d in datasets]
        bars=ax.bar(x+offset,vals,width,color=color,label=label)
        ax.bar_label(bars,fmt='%.1f%%',padding=3,fontsize=9)
    ax.set(xticks=x,xticklabels=labels,ylabel='Accuracy at threshold 0.5 (%)',ylim=(0,125),title='External fidelity evaluation: initialization vs. fine-tuning')
    ax.set_yticks(range(0,101,20));ax.legend(loc='upper right',frameon=False)
    ax.spines[['top','right']].set_visible(False)
    fig.text(.08,.025,'* Small agent-authored contrast probes, not independent labeled benchmarks. No OOD tuning.',fontsize=9)
    fig.tight_layout(rect=(0,.06,1,1))
    for ext in ('png','pdf'):fig.savefig(HERE/f'reports/ood-accuracy.{ext}',dpi=180)
    fig,ax=plt.subplots(figsize=(7,4.5))
    for variant,color,label in [('unfine_tuned','#99AAB5','Initial random head'),('fine_tuned','#287A9F','Fine-tuned')]:
        part=[r for r in audit['predictions'][variant] if r['dataset']=='CriticLeanBench']
        z=np.array([r['logit'] for r in part]);y=np.array([r['label'] for r in part])
        # Keep tied scores together: each point corresponds to a realizable threshold.
        order=np.argsort(-z);ends=np.r_[np.flatnonzero(np.diff(z[order])!=0),len(z)-1]
        counts=ends+1
        errors=np.cumsum(1-y[order])[ends]
        ax.plot(counts/len(y)*100,errors/counts*100,color=color,label=label)
        op=next(r for r in result['results'] if r['dataset']=='CriticLeanBench' and r['model']==variant)
        if op['accepted']:ax.scatter(op['coverage']*100,op['accepted_error']*100,color=color,s=45,zorder=3)
    ax.set(xlabel='Acceptance coverage (%)',ylabel='Incorrect among accepted (%)',
        title='CriticLeanBench: descriptive risk–coverage curves',xlim=(0,100),ylim=(-1,101))
    ax.legend(frameon=False);ax.spines[['top','right']].set_visible(False)
    fig.text(.09,.025,'Dots: existing operating points. No OOD threshold selection; no uncertainty bands.',fontsize=8)
    fig.tight_layout(rect=(0,.06,1,1))
    for ext in ('png','pdf'):fig.savefig(HERE/f'reports/ood-risk-coverage.{ext}',dpi=180)
    print(json.dumps(result['results'],indent=2))
    print(json.dumps(result['critic_accuracy_delta'],indent=2))

if __name__=='__main__':main()
