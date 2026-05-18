#!/usr/bin/env python3
"""Merge all batch JSON files and existing kept questions into all_408_v2.json"""
import json, glob, sys, os
sys.path.insert(0, '.')

base = 'data/practice_questions'

# Load original
with open(f'{base}/all_408.json') as f:
    original = json.load(f)

# Load all batch files
batches = sorted(glob.glob(f'{base}/batch_*.json'))
new_questions = []
for bf in batches:
    with open(bf) as f:
        new_questions.extend(json.load(f))
    print(f'Loaded {bf}: {len(json.load(open(bf)))} questions')

# Merge: original + new
merged = original + new_questions
print(f'\nOriginal: {len(original)}, New: {len(new_questions)}, Merged: {len(merged)}')

# Save
out = f'{base}/all_408_v2.json'
with open(out, 'w', encoding='utf-8') as f:
    json.dump(merged, f, ensure_ascii=False, indent=2)
print(f'Saved to {out}')

# Run filter
from filter_408 import process_questions
process_questions(out, '408_review_result_v2.json')

# Show per-concept stats
with open('408_review_result_v2.json') as f:
    review = json.load(f)

import collections
concept_kept = collections.Counter()
for q in review['kept_questions']:
    concept_kept[q['concept_id']] += 1

print('\n--- Per-concept kept count (target=10) ---')
for cid in sorted(concept_kept):
    count = concept_kept[cid]
    status = '✓' if count >= 10 else f'need {10-count} more'
    print(f'  {cid}: {count} {status}')

all_concepts = set(q.get('concept_id','') for q in merged)
missing = all_concepts - set(concept_kept.keys())
for cid in sorted(missing):
    print(f'  {cid}: 0 need 10 more')
