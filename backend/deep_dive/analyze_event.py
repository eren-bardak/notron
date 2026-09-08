from datetime import datetime, timezone

from openai import OpenAI

from .models import EventAnalysis, ResearchBundle


def analyze_event(
    client: OpenAI,
    model: str,
    research: ResearchBundle,
) -> EventAnalysis:
    """Turn verified research into a cinematic, data-backed story."""
    prompt = """
Create a Turkish numerical data story from the verified research bundle.

Center the story on the verified development and the people or institutions
affected by it. Positive outcomes, achievements and improvements are welcome.
Explain evidenced benefits and limitations. Never invent a problem, assume
harm or exaggerate allegations to make questions sound critical.

First choose the charts, their insights and the questions. Then write the two
story fields so they prepare the reader for those exact charts and questions.
Avoid background facts that do not help interpret the later analysis.

The output must contain:
1. A concise background section of 3 to 4 sentences.
2. A concise concrete-event explanation of 2 to 3 sentences.
3. A data_story with 4 to 12 key metrics, hidden patterns, baselines,
   what to watch next and explicit limitations.
4. The strongest one or two charts using only supplied numeric_series values.
5. Exactly three event-specific questions anchored to supplied evidence, including
   two normative policy tradeoffs and one question about lived experience.
6. One data-grounded open-ended normative question about what ought to happen.
7. One cross_group_question asking people to consider the living conditions of
   a group that answered differently and name evidence that could test their
   explanation objectively.

The background and event explanation will be merged on one screen. They must
not repeat each other, and their combined reading time should stay short.

Chart selection rules:
- lollipop: when every label has one Filtresiz and one Filtreli value.
  Keep labels ordered from the smallest Filtresiz value to the largest.
  State the general direction and name any points moving against it as
  odd cases. Ask what might explain them; never invent the explanation.
- line: only when ordered=true and the x-axis is chronological.
- donut: only when part_of_whole=true and points form one meaningful whole.
- comparison: when the same metric compares two named groups.
- bars: for all other categorical comparisons.

Every chart must have exactly one clear insight and supporting source URLs.
If two charts jointly support one conclusion, the second insight may explicitly
synthesize them, but it must still state what the second chart contributes.
Copy numeric values exactly; do not calculate unsupported figures.
Mention uncertainty or comparability limits in the insight when relevant.
Build the data story around numbers, trends, baselines, denominators, outliers
and differences between groups. Surface important patterns that normal news
coverage tends to omit, but never invent a cause for them.

Question rules:
- Policy questions must cite an exact number, comparison, threshold,
  trend or outlier from the supplied research in data_anchor.
- The lived-experience question asks about the respondent’s own experience in
  a clear time period; never infer their experience from their identity.
- Tailor wording to this event. Never use a stock question such as whether the
  event is part of a larger recurring problem.
- Vary question_type across threshold, trend, outlier, tradeoff and comparison.
- Make why_it_matters explain the decision exposed by the data.
- Questions must be answerable with yes/no/unsure and must not be loaded.
- Ask one proposition per question; never combine a diagnosis with a policy choice.
- Describe competing legitimate values without stereotyping identity groups.
- A yes or no answer must have a clear, interpretable policy meaning.
- Avoid accusatory wording, assumed guilt and rhetorical questions.
- Use stable IDs q1, q2 and q3. Questions are optional for the user.
- The normative question must also reference the event's measured tradeoff,
  target, gap or trend rather than asking a generic "what should be done?".
- The cross-group question must be specific to this event, non-accusatory and
  must not assume that an identity attribute caused an answer.

Copy every key metric exactly from metric_candidates. Do not introduce a new
number in the analysis. Use data limitations to prevent false precision.
Write neutral Turkish. Never describe correlation as causation.
"""

    result = client.responses.parse(
        model=model,
        reasoning={"effort": "low"},
        input=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": research.model_dump_json()},
        ],
        text_format=EventAnalysis,
    ).output_parsed

    if result is None:
        raise RuntimeError("The analysis response could not be parsed")

    result.event_id = research.event_id
    result.generated_at = datetime.now(timezone.utc).isoformat()
    return result
