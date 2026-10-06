"""Shared editorial policy for newly generated event questions."""

CONTESTED_QUESTION_RULES = """
Choose the sharpest genuine disagreement that THIS event's sourced evidence
can support. Make it specific, consequential and debatable, not a bland moral
consensus question. Consider competing interpretations or conditional outcomes
and select the one with the strongest evidenced tension. Do not invent a dispute
or demand an even vote split. A settled fact is not a matter of opinion.

Questions must be NON-NORMATIVE: ask what an action means, what explains a
documented tension, or which consequence is more plausible. Never ask what
people SHOULD do, which goal deserves priority, whether something is morally
right, or which policy the reader supports. Avoid 'ne yapılmalı?', 'hangisi
öncelikli olmalı?', 'doğru mu?' and disguised 'A mı, B mi tercih edilmeli?'
questions. A controversial topic alone does not make a question substantive.

Offer two distinct, defensible interpretations/outlooks with parallel, neutral
labels and a third uncertainty or mixed/context-dependent answer. If two effects
can coexist, do not pretend they are mutually exclusive: ask about the dominant
effect under the same stated condition, and allow a mixed/uncertain answer.
Each label must answer the exact question and remain at most 24 characters.
Evidence anchors must state what is known and what remains uncertain.

For example, ONLY if the supplied evidence supports both readings:
'Üsküdar’daki oy dengesi kalıcı destek mi, geçici uzlaşma mı?'
with 'Kalıcı destek / Geçici uzlaşma / Henüz belli değil' asks about an
interpretation. 'Üsküdar’da hız mı, uzlaşma mı öncelikli olmalı?' asks for
a value preference and must be rejected. Examples are style only, never evidence.

Keep premises factual and allegations attributed. Do not invent guilt, motives,
causes, costs, benefits or forecasts to make a question provocative. Do not create
false balance against established evidence or predict answers from identities.
If there is no supported disagreement, fail editorial review rather than force
a polarizing question. Keep the factual news summary and headline neutral.

For compatibility, tradeoff_present/balanced_tradeoff describe a real tension
between supported interpretations or outcomes, not a request to rank values.
Set non_normative=true only when the question asks for no ought/should judgment.
Set substantive_disagreement=true only when both readings are defensible from
the event's evidence and their difference matters. Explain the tension and its
evidence limits in the review reason or tradeoff_basis.
"""
