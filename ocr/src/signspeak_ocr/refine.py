"""Budgeted photometric, small-text and column retries; baseline remains available."""
from __future__ import annotations
from collections import Counter
from dataclasses import replace
import time
import numpy as np

from .preprocess import candidate_kind,make_candidate
from .selection import evaluate_candidate,word_evidence,compare_words
from .tesseract import run_tesseract_tsv
from .tsv import parse_tsv
from .layout import analyze_layout,order_columns
from .targeted import targeted_read


def _words(document):
    return [{'text':w.text,'confidence':w.confidence,'bbox':list(w.bbox)} for w in document.iter_words()]


def refine(image,quality,document,run,config,info):
    options=config.preprocessing
    record={'selected':'original','attempts':[], 'baseline_text':'\n'.join(l.text for l in document.iter_lines())}
    warnings=[]
    if not options.enabled:
        record['reason']='disabled';return document,run,record,warnings
    if image.width*image.height>options.max_pixels:
        record['reason']='pixel_budget';return document,run,record,warnings
    started=time.perf_counter();deadline=started+options.extra_seconds
    original,original_run=document,run
    record['baseline_command']=run.command;record['baseline_words']=_words(original)
    working=image;calls=0;comparison=None;hypotheses=[]

    def consider(candidate,candidate_run,attempt,allow_order=False):
        nonlocal document,run,comparison
        record['attempts'].append(attempt)
        if max(len(_words(original)),len(_words(candidate)))>1500:
            attempt.update(selected=False,reason='comparison_word_budget');return
        decision=evaluate_candidate(document,candidate)
        accepted=decision['accepted']
        if allow_order and Counter(w.text for w in document.iter_words())==Counter(w.text for w in candidate.iter_words()):
            accepted=True;decision['reason']='lossless_column_order'
        if time.perf_counter()>deadline:accepted=False;decision['reason']='time_budget'
        attempt.update(selected=accepted,reason=decision['reason'],evaluation=decision,words=_words(candidate),
                       text='\n'.join(l.text for l in candidate.iter_lines()))
        if accepted:
            document,run=candidate,candidate_run;record['selected']=attempt['id']
        hypotheses.append((candidate,candidate_run,len(record['attempts'])-1))
        # Evidence always compares original to the selected display or last rejected
        # alternative; numerical conflicts cannot disappear after a later retry.
        comparison=(candidate,accepted,len(record['attempts'])-1)

    kind=candidate_kind(quality)
    if kind is not None and calls<options.max_extra_calls:
        attempt={'id':kind,'operations':['grayscale',kind]};t=time.perf_counter()
        try:
            working=make_candidate(image,kind)
            remaining=deadline-time.perf_counter()
            if remaining<=0:raise TimeoutError('time_budget')
            calls+=1
            candidate_run=run_tesseract_tsv(working,replace(config.tesseract,timeout_seconds=min(config.tesseract.timeout_seconds,remaining)),info)
            consider(parse_tsv(candidate_run.tsv),candidate_run,{**attempt,'command':candidate_run.command})
        except Exception as error:
            record['attempts'].append({**attempt,'selected':False,'reason':'candidate_failed','error':f'{type(error).__name__}: {error}'})
            warnings.append('preprocessing_candidate_failed_baseline_retained')
        finally:
            record['attempts'][-1]['duration_ms']=round((time.perf_counter()-t)*1000,1)

    if time.perf_counter()<deadline:
        try:
            layout=analyze_layout(working);record['layout']=layout
            heights=[w.bbox[3]-w.bbox[1] for w in document.iter_words()]
            glyph=layout['median_glyph_height']
            small=bool(glyph is not None and 5<=glyph<=12 and layout.get('text_rows',0)>=1
                   and (not heights or np.median(heights)<18))
            scale=min(options.max_scale,max(1.0,24/glyph)) if small else 1.0
            record['small_text_trigger']={'triggered':small,'glyph_height':glyph,'word_height':float(np.median(heights)) if heights else None,'requested_scale':scale}
            crops=layout['columns'] or [(0,0,image.width,image.height)]
            if (layout['columns'] or scale>1) and calls+len(crops)<=options.max_extra_calls:
                t=time.perf_counter();attempt={'id':('columns' if layout['columns'] else 'small_text')+(f'_scale_{scale:.2f}' if scale>1 else ''),
                                             'operations':[kind or 'original','crop' if layout['columns'] else 'full_image','upscale' if scale>1 else 'identity']}
                # Reserve every crop call before entering so failures cannot bypass budgets.
                remaining_calls=options.max_extra_calls-calls;calls+=len(crops)
                candidate,candidate_run,details=targeted_read(working,layout,scale,config,info,deadline,remaining_calls)
                consider(candidate,candidate_run,{**attempt,**details},allow_order=bool(layout['columns']))
                record['attempts'][-1]['duration_ms']=round((time.perf_counter()-t)*1000,1)
                # An empty original cannot corroborate recovered text. Two bounded
                # settings may support a display hypothesis, but never verify it.
                if small and not list(original.iter_words()) and len(hypotheses)>=2 and record['selected']=='original':
                    first,first_run,first_index=hypotheses[0]
                    second,_,_=hypotheses[-1]
                    a,b=list(first.iter_words()),list(second.iter_words())
                    links=compare_words(a,b)
                    agreement=sum(any(a[i].text==b[j].text for j in js) for i,js in enumerate(links))/max(1,len(a))
                    metrics=evaluate_candidate(original,first)['candidate_metrics']
                    if len(a)>=3 and agreement>=.7 and metrics['mean']>=80 and metrics['low_fraction']<=.2 and time.perf_counter()<deadline:
                        document,run=first,first_run;record['selected']=record['attempts'][first_index]['id']
                        record['attempts'][first_index].update(selected=True,reason='small_text_correlated_support',support_fraction=agreement)
                        record['small_text_support']={'fraction':agreement,'independent_verification':False}
            if layout['columns'] and time.perf_counter()<deadline:
                ordered=order_columns(document,layout['columns'])
                if [w.text for w in ordered.iter_words()]!=[w.text for w in document.iter_words()]:
                    consider(ordered,run,{'id':record['selected']+'+column_order','operations':['lossless_column_assignment'],'calls':0},allow_order=True)
                cut=layout['columns'][0][2]
                owners=[int((w.bbox[0]+w.bbox[2])/2>=cut) for w in document.iter_words()]
                if owners==sorted(owners):
                    record['reading_order']={'source':'wide_gutter_columns','confidence':'heuristic','columns':layout['columns']}
        except Exception as error:
            warnings.append('targeted_retry_failed_existing_reading_retained')
            record['attempts'].append({'id':'targeted_retry','selected':False,'reason':'targeted_failed','error':f'{type(error).__name__}: {error}'})
    record['extra_calls']=calls
    # Compare a selected retry with the original read, or preserve the strongest
    # rejected reading if no retry replaced the original.
    if record['selected']!='original':
        candidate=document;selected=True
        index=next(i for i,a in reversed(list(enumerate(record['attempts']))) if a.get('id')==record['selected'])
    elif comparison is not None:
        candidate,selected,index=comparison
    else:
        record['reason']='no_diagnostic_trigger' if kind is None else 'no_usable_candidate'
        return document,run,record,warnings
    for i,attempt in enumerate(record['attempts']):
        attempt['selected'] = record['selected']!='original' and i==index
    record['decision_reason']=record['attempts'][index].get('reason')
    decision=evaluate_candidate(original,candidate)
    decision['pairwise_accepted']=decision['accepted']
    decision['accepted']=record['selected']!='original'
    decision['reason']=record['decision_reason']
    record['evaluation']=decision;record['comparison_attempt_index']=index
    record['word_evidence']=word_evidence(original,candidate,selected,decision)
    if decision['numeric_conflicts']:warnings.append('preprocessing_numeric_disagreement_requires_review')
    return document,run,record,warnings
