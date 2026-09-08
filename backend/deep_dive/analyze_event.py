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
5. Exactly three short event-specific questions: one emotional reaction, one
   normative priority choice, and ONLY ONE challenging quantified question.
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
- Set schema_version=2. IDs q1/q2/q3, types reaction/priority/metric in that order.
- q1: a simple first reaction to this specific development, ideally 4–8 words.
  Three concrete reactions, e.g. "Umut verdi", "Kaygı verdi", "Etkilemedi";
  tailor labels to the event. They must be mutually distinguishable, not loaded.
- q2: a short normative choice of priority: "Önce hangi adım?" tied to this event.
  Offer two legitimate, concrete actions and a third "Kararsızım" choice.
  Do not ask yes/no. Never assume wrongdoing or imply one choice is morally best.
- q3: the ONLY difficult question, about interpreting one exact supplied number,
  comparison or tradeoff. At most 100 characters, one proposition.
  Put the exact source-backed figure, unit and period in data_anchor (max 180 chars).
  No invented numeric target or unsupported benchmark. Offer three concise labels
  matching the interpretation, such as "Yeterli", "Yetersiz", "Veri yetmiyor".
- q1 and q2 data_anchor must be empty; keep all questions <=100 characters.
- choice_labels has internal slots yes/no/unsure; these are storage keys, NOT
  required meanings. Each visible Turkish label is at most 24 characters.
- State what each answer means without stereotyping any identity group.
- why_it_matters: one short sentence. Do not invent causes, guilt or shared experience.
- Keep normative_question and cross_group_question to one short optional prompt.

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

    if [q.question_type for q in result.binary_questions] != ["reaction", "priority", "metric"]:
        raise ValueError("Expected two simple reactions and exactly one quantified question")
    if not result.binary_questions[2].data_anchor.strip():
        raise ValueError("The quantified question requires its evidence anchor")
    for question in result.binary_questions:
        if len(set(question.choice_labels.model_dump().values())) != 3:
            raise ValueError("Each question needs three distinct reactions")
    for question in result.binary_questions[:2]:
        question.data_anchor = ""
    result.event_id = research.event_id
    result.generated_at = datetime.now(timezone.utc).isoformat()
    return result
