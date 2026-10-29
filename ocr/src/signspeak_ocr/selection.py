"""Compare spatial evidence without treating either correlated read as truth."""
from __future__ import annotations

import math
from .tsv import TsvDocument


def _confidence(word):
    value = word.confidence
    return value if value is not None and math.isfinite(value) and 0 <= value <= 100 else 0.0


def overlap(a, b):
    """Intersection over the smaller box, tolerant of split/join OCR tokens."""
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = lambda box: max(0, box[2]-box[0]) * max(0, box[3]-box[1])
    return intersection / max(1, min(area(a), area(b)))


def compare_words(baseline, candidate):
    # A word can overlap several tokens after a segmentation change. Retain all
    # alternatives rather than inventing a one-to-one field/value relationship.
    return [[j for j, other in enumerate(candidate) if overlap(word.bbox, other.bbox) >= .5]
            for word in baseline]


def supports_reading(old, new):
    if new.text == old.text or _confidence(new) >= _confidence(old)+10:
        return True
    # Conflicting digit-like OCR is handled as numerical uncertainty, not a veto.
    if any(c.isdigit() for c in old.text+new.text):
        return True
    fragment=old.text.strip('.,:;!?').casefold()
    expanded=new.text.strip('.,:;!?').casefold()
    return (len(fragment)>=3 and len(expanded)>len(fragment) and fragment in expanded
            and _confidence(new)>=80
            and max(0,min(old.bbox[2],new.bbox[2])-max(old.bbox[0],new.bbox[0]))/max(1,old.bbox[2]-old.bbox[0])>=.9
            and abs((old.bbox[1]+old.bbox[3]-new.bbox[1]-new.bbox[3])/2)<=.25*max(old.bbox[3]-old.bbox[1],new.bbox[3]-new.bbox[1])
            and new.bbox[2]-new.bbox[0] >= (old.bbox[2]-old.bbox[0])+max(2,.1*(old.bbox[3]-old.bbox[1])))


def evaluate_candidate(baseline: TsvDocument, candidate: TsvDocument) -> dict:
    old, new = list(baseline.iter_words()), list(candidate.iter_words())
    old_links = compare_words(old, new)
    new_links = compare_words(new, old)
    def stats(words):
        confidences = [_confidence(w) for w in words]
        return {'words': len(words), 'mean': sum(confidences)/max(1,len(words)),
                'low_fraction': sum(c < 60 for c in confidences)/max(1,len(words)),
                'characters': sum(sum(c.isalnum() for c in w.text) for w in words)}
    before, after = stats(old), stats(new)
    # Missing strong baseline text is a loss signal, not an absolute veto on
    # conflicting text. A substantially stronger overlapping read can replace it.
    lost = [i for i,w in enumerate(old) if _confidence(w) >= 80 and not old_links[i]]
    weakened = [i for i,w in enumerate(old) if _confidence(w) >= 80 and old_links[i]
                and not any(c.isdigit() for c in w.text)
                and not any(supports_reading(w, new[j])
                            for j in old_links[i])]
    char_ratio = after['characters'] / max(1, before['characters'])
    coverage = sum(bool(links) for links in old_links)/max(1,len(old))
    # Two distinct acceptance routes: repairs with confidence + uncertainty
    # improvement, or substantial recovered text with preserved spatial coverage.
    strong = after['mean'] >= 80 and after['low_fraction'] <= .2
    repair = after['mean'] >= before['mean']+5 and after['low_fraction'] < before['low_fraction']
    recovery = char_ratio >= 1.3 and coverage >= .85 and strong
    empty_recovery = not old and len(new) >= 3 and after['mean'] >= 90 and after['low_fraction'] == 0
    if not new or candidate.malformed_rows:
        selected, reason = False, 'candidate_empty_or_malformed'
    elif lost or weakened:
        selected, reason = False, 'supported_text_loss_or_weaker_replacement'
    elif old and (coverage < .85 or char_ratio < .9):
        selected, reason = False, 'spatial_coverage_loss'
    elif (strong and repair) or recovery or empty_recovery:
        selected, reason = True, 'multiple_quality_signals'
    else:
        selected, reason = False, 'insufficient_support'
    numeric_conflicts = []
    for side, words, others, links in [('original',old,new,old_links),('candidate',new,old,new_links)]:
        for i,w in enumerate(words):
            neighbors = [others[j] for j in links[i]]
            # Numeric text, punctuation and adjacent units remain literal. Shared
            # digit agreement is not independent verification.
            numeric = any(c.isdigit() for c in w.text) or any(any(c.isdigit() for c in v.text) for v in neighbors)
            same = len(neighbors) == 1 and neighbors[0].text == w.text
            if numeric and not same:
                numeric_conflicts.append({'source': side, 'index': i, 'text': w.text,
                                          'alternatives': [v.text for v in neighbors]})
    return {'accepted': selected, 'reason': reason, 'baseline_metrics': before,
            'candidate_metrics': after, 'baseline_coverage': coverage,
            'character_ratio': char_ratio, 'numeric_conflicts': numeric_conflicts,
            'original_links': old_links, 'candidate_links': new_links}


def select_candidate(baseline: TsvDocument, candidate: TsvDocument) -> tuple[bool, str]:
    decision = evaluate_candidate(baseline, candidate)
    return decision['accepted'], decision['reason']


def word_evidence(baseline, candidate, selected_candidate, decision):
    selected, other = (candidate,baseline) if selected_candidate else (baseline,candidate)
    words, others = list(selected.iter_words()), list(other.iter_words())
    links = decision['candidate_links' if selected_candidate else 'original_links']
    records = []
    for i, word in enumerate(words):
        alternatives = [others[j] for j in links[i]]
        same = len(alternatives) == 1 and alternatives[0].text == word.text
        numeric = any(c.isdigit() for c in word.text) or any(any(c.isdigit() for c in a.text) for a in alternatives)
        if numeric and not same:
            status = 'numeric_disagreement'
        elif same and min(_confidence(word), _confidence(alternatives[0])) >= 60:
            status = 'correlated_agreement_unverified'
        elif _confidence(word) < 60 and all(_confidence(a) < 60 for a in alternatives):
            status = 'untrustworthy'
        else:
            status = 'alternative_reading_unverified'
        records.append({'status':status, 'alternatives':[
            {'text':a.text,'confidence':a.confidence,'bbox':list(a.bbox)} for a in alternatives]})
    return records
