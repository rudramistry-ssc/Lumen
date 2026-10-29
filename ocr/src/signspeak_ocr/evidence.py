"""Attach uncertainty to display words and render a separate agent evidence view."""
from __future__ import annotations

from .result import render_text_view


def attach_evidence(result, selection, chain, threshold):
    """Map alternative coordinates once; neither OCR pass is verified evidence."""
    for key in ('baseline_words',):
        for word in selection.get(key, []):
            word.update(chain.map_box_to_reference(tuple(word['bbox'])).to_dict())
    for attempt in selection.get('attempts', []):
        for word in attempt.get('words', []):
            word.update(chain.map_box_to_reference(tuple(word['bbox'])).to_dict())
    records = selection.get('word_evidence')
    if records is None:
        return
    words = [w for r in result['regions'] for line in r['lines'] for w in line['words']]
    for word, record in zip(words, records, strict=True):
        for alternative in record['alternatives']:
            alternative.update(chain.map_box_to_reference(tuple(alternative['bbox'])).to_dict())
        record['source'] = selection['selected']
        record['alternative_source'] = 'original' if selection['selected'] != 'original' else selection['attempts'][selection.get('comparison_attempt_index', 0)]['id']
        word['evidence'] = record
        if record['status'] != 'correlated_agreement_unverified':
            word['flags'].append(record['status'])
    by_id = {w['id']:w for w in words}
    for value in result['numeric_values']:
        word = by_id[value['word_id']]
        value['evidence'] = word['evidence']
        value['status'] = word['evidence']['status']
        value['flags'] = list(dict.fromkeys(value['flags']+word['flags']))
    for region in result['regions']:
        statuses = [w['evidence']['status'] for line in region['lines'] for w in line['words']]
        if any(s != 'correlated_agreement_unverified' for s in statuses):
            region['flags'].append('ocr_evidence_uncertain')
            region['status'] = 'uncertain'
            region['coverage'] = 'unknown'
    # Display text remains a single whole pass. Agent text never promotes a
    # changed or single-pass word to established fact. Alternatives live in JSON.
    display_view = render_text_view(result['regions'], threshold)
    agent_lines = []
    for region in result['regions']:
        agent_lines.append(f"[{region['id']} OCR evidence; correlated reads are not verification]")
        for line in region['lines']:
            agent_lines.append(' '.join(
                w['text'] if w['evidence']['status'] == 'correlated_agreement_unverified'
                else f"[uncertain {w['id']}: {w['evidence']['status']}]"
                for w in line['words']))
    uncertain = [w['id'] for w in words if w['evidence']['status'] != 'correlated_agreement_unverified']
    conflicts = selection.get('evaluation', {}).get('numeric_conflicts', [])
    result['evidence'] = {
        'verification': 'not_performed', 'display_text_source': selection['selected'],
        'uncertain_word_ids': uncertain, 'numeric_conflicts': conflicts,
        'policy': 'Uncertain display readings are hypotheses, not established facts. Consult alternative coordinates and readings; request clarification when needed.',
    }
    for conflict in conflicts:
        source_words = (selection.get('baseline_words', []) if conflict['source'] == 'original'
                        else selection['attempts'][selection.get('comparison_attempt_index', 0)].get('words', []))
        source_word = source_words[conflict['index']]
        conflict['bbox'] = source_word['bbox']
        conflict['confidence'] = source_word['confidence']
    if any(w['evidence']['status'] == 'untrustworthy' for w in words):
        agent_lines.append('[Untrustworthy OCR regions: text or values may be missing. Request a clearer image rather than inferring content.]')
    if conflicts:
        agent_lines.append('[Numeric conflicts exist; do not infer missing values. Consult evidence.numeric_conflicts and preprocessing.selection.]')
    result['display_text_view'] = display_view
    result['text_view'] = '\n'.join(agent_lines)
