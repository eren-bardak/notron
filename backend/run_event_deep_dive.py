import argparse
import os

from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client

from deep_dive.analyze_event import analyze_event
from deep_dive.research_event import load_event, research_event
from deep_dive.save_analysis import save_analysis


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--event-id", type=int, required=True)
    args = parser.parse_args()

    load_dotenv()
    model = os.getenv("OPENAI_DEEP_DIVE_MODEL", "gpt-5.4-mini")
    db = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_KEY"])
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    event_payload = load_event(db, args.event_id)
    research = research_event(client, model, args.event_id, event_payload)
    if not research.numeric_series:
        db.table("events").update(
            {
                "enough_data": False,
                "numeric_data": [],
                "problem_supported": research.problem_supported,
                "central_problem": research.central_problem,
            }
        ).eq("id", args.event_id).execute()
        reason = "no numeric data"
        print(f"Deep dive skipped | event={args.event_id} | {reason}")
        return
    analysis = analyze_event(client, model, research)
    save_analysis(db, research, analysis)

    print(f"Deep dive ready | event={args.event_id} | charts={len(analysis.charts)}")


if __name__ == "__main__":
    main()
