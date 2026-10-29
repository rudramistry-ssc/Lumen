"""Recognition and uncertainty metrics for the synthetic evaluation tool."""
import re

def align(a,b):
    d=[[0]*(len(b)+1) for _ in range(len(a)+1)]
    for i in range(len(a)+1):d[i][0]=i
    for j in range(len(b)+1):d[0][j]=j
    for i in range(1,len(a)+1):
        for j in range(1,len(b)+1):d[i][j]=min(d[i-1][j]+1,d[i][j-1]+1,d[i-1][j-1]+(a[i-1]!=b[j-1]))
    edits=[];i,j=len(a),len(b)
    while i or j:
        if i and j and d[i][j]==d[i-1][j-1]+(a[i-1]!=b[j-1]):
            edits.append(('equal' if a[i-1]==b[j-1] else 'substitute',i-1,j-1));i-=1;j-=1
        elif i and d[i][j]==d[i-1][j]+1:edits.append(('delete',i-1,None));i-=1
        else:edits.append(('insert',None,j-1));j-=1
    return d[-1][-1],list(reversed(edits))

def metrics(item,r):
    from signspeak_ocr.selection import overlap
    words=[w for region in r['regions'] for line in region['lines'] for w in line['words']]
    truth=item['text'].split();actual=[w['text'] for w in words]
    char_err,_=align(' '.join(truth),' '.join(actual));word_err,edits=align(truth,actual)
    numeric=lambda s:any(c.isdigit() for c in s)
    conflicts=r.get('evidence',{}).get('numeric_conflicts',[]);selection=(r.get('preprocessing') or {}).get('selection',{})
    conflict_boxes=[]
    for conflict in conflicts:
        if 'bbox' in conflict:
            conflict_boxes.append(conflict['bbox']);continue
        source=selection.get('baseline_words',[]) if conflict['source']=='original' else next((a.get('words',[]) for a in selection.get('attempts',[]) if 'words' in a),[])
        if conflict['index']<len(source):conflict_boxes.append(source[conflict['index']]['bbox'])
    num_errors=silent=omissions=0;details=[]
    for op,i,j in edits:
        if op=='delete':omissions+=1
        if op!='equal' and ((i is not None and numeric(truth[i])) or (j is not None and numeric(actual[j]))):
            num_errors+=1
            if j is not None:
                flags=words[j]['flags'];flagged=bool(set(flags)&{'low_confidence','confidence_unavailable','numeric_disagreement','alternative_reading_unverified','untrustworthy'})
            else:
                flagged=bool(item.get('words') and any(overlap(item['words'][i]['bbox'],b)>=.5 for b in conflict_boxes))
            silent+=not flagged
            details.append({'operation':op,'expected':truth[i] if i is not None else None,'actual':actual[j] if j is not None else None,'flagged':flagged})
    # Numeric literals are scored separately from digit-containing word edits:
    # "125g" versus "125 g" is a tokenization error, not a changed number.
    token_numeric_errors, token_silent = num_errors, silent
    pattern = re.compile(r"[-+]?\d+(?:[.,:]\d+)*")
    ref_nums = [(m.group(),i) for i,t in enumerate(truth) for m in pattern.finditer(t)]
    out_nums = [(m.group(),j) for j,t in enumerate(actual) for m in pattern.finditer(t)]
    _, num_edits = align([x[0] for x in ref_nums],[x[0] for x in out_nums])
    num_errors=silent=0;literal_details=[]
    for op,i,j in num_edits:
        if op=='equal': continue
        num_errors+=1
        if j is not None:
            flags=words[out_nums[j][1]]['flags']
            flagged=bool(set(flags)&{'low_confidence','confidence_unavailable','numeric_disagreement','alternative_reading_unverified','untrustworthy'})
        else:
            ref_i=ref_nums[i][1]
            flagged=bool(item.get('words') and any(overlap(item['words'][ref_i]['bbox'],b)>=.5 for b in conflict_boxes))
        silent+=not flagged
        literal_details.append({'operation':op,'expected':ref_nums[i][0] if i is not None else None,'actual':out_nums[j][0] if j is not None else None,'flagged':flagged})
    unit_pattern=re.compile(r'(?<![A-Za-z])(?:mg|kg|g|mL|km|C|%)(?![A-Za-z])')
    unit_errors,_=align(unit_pattern.findall(' '.join(truth)),unit_pattern.findall(' '.join(actual)))
    # Location-aware number comparison distinguishes reordered columns from
    # changed values. Match equal literals first, then substitutions/omissions.
    available=set(range(len(out_nums))); unmatched=[];spatial_errors=spatial_silent=0
    truth_geometry=item.get('words',[])
    for literal,ref_i in ref_nums:
        matches=[j for j in available if out_nums[j][0]==literal and
                 overlap(truth_geometry[ref_i]['bbox'],words[out_nums[j][1]]['bbox'])>=.5]
        if matches:available.remove(min(matches))
        else:unmatched.append((literal,ref_i))
    spatial_details=[]
    for literal,ref_i in unmatched:
        matches=[j for j in available if overlap(truth_geometry[ref_i]['bbox'],words[out_nums[j][1]]['bbox'])>=.5]
        spatial_errors+=1
        if matches:
            j=min(matches);available.remove(j);source=words[out_nums[j][1]]
            flagged=bool(set(source['flags'])&{'low_confidence','confidence_unavailable','numeric_disagreement','alternative_reading_unverified','untrustworthy'})
            actual_literal=out_nums[j][0]
        else:
            flagged=any(overlap(truth_geometry[ref_i]['bbox'],box)>=.5 for box in conflict_boxes)
            actual_literal=None
        spatial_silent+=not flagged
        spatial_details.append({'expected':literal,'actual':actual_literal,'flagged':flagged,'bbox':truth_geometry[ref_i]['bbox']})
    for j in available:
        spatial_errors+=1;source=words[out_nums[j][1]]
        flagged=bool(set(source['flags'])&{'low_confidence','confidence_unavailable','numeric_disagreement','alternative_reading_unverified','untrustworthy'})
        spatial_silent+=not flagged
        spatial_details.append({'expected':None,'actual':out_nums[j][0],'flagged':flagged,'bbox':source['bbox']})
    matched=[]; used=set(); withheld=[]; false_flags=0
    for out_i,word in enumerate(words):
        candidates=[i for i,truth_word in enumerate(truth_geometry) if i not in used and
                    truth_word['text']==word['text'] and overlap(truth_word['bbox'],word['bbox'])>=.5]
        if candidates:
            ref_i=max(candidates,key=lambda i:overlap(truth_geometry[i]['bbox'],word['bbox']))
            used.add(ref_i);matched.append(ref_i)
            if word['flags']:false_flags+=1
            if word.get('evidence') and word['evidence']['status']!='correlated_agreement_unverified':withheld.append(ref_i)
    pairs=len(matched)*(len(matched)-1)//2
    concordant=sum(matched[i]<matched[j] for i in range(len(matched)) for j in range(i+1,len(matched)))
    cross_pairs=cross_correct=0
    for i in range(len(matched)):
        for j in range(i+1,len(matched)):
            a,b=truth_geometry[matched[i]].get('column',0),truth_geometry[matched[j]].get('column',0)
            if a!=b:cross_pairs+=1;cross_correct+=a<b
    conf=[w['confidence'] for w in words if w['confidence'] is not None]
    return {'recognized_truth_ids':matched,'correct_words':len(matched),'correct_withheld_ids':withheld,'correct_withheld':len(withheld),'correct_flagged':false_flags,
            'reading_order_pair_accuracy':concordant/pairs if pairs else None,'cross_column_pairs':cross_pairs,'cross_column_pair_accuracy':cross_correct/cross_pairs if cross_pairs else None,
            'cer':char_err/max(1,len(' '.join(truth))),'wer':word_err/max(1,len(truth)),
            'character_edits':char_err,'reference_characters':len(' '.join(truth)),
            'word_edits':word_err,'reference_words':len(truth),'omitted_words':omissions,
            'spatial_numeric_errors':spatial_errors,'spatial_silent_numeric_errors':spatial_silent,'spatial_numeric_details':spatial_details,
            'numeric_errors':num_errors,'silent_numeric_errors':silent,'reference_numeric_tokens':len(ref_nums), 'numeric_token_format_errors':token_numeric_errors, 'unit_errors':unit_errors,
            'mean_confidence':sum(conf)/max(1,len(conf)),'uncertain_words':sum(bool(w['flags']) for w in words),
            'numeric_conflicts':len(conflicts),'numeric_error_details':literal_details, 'numeric_token_error_details':details,
            'ms':r['timings_ms']['total'],'process_rss_mb':r['resources']['process_peak_rss_mb'],
            'child_rss_mb':r['resources']['children_peak_rss_mb'],'display':r['text'],
            'selected':selection.get('selected','original'),'reason':next((a.get('reason') for a in selection.get('attempts',[])),selection.get('reason'))}
