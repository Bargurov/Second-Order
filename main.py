from datetime import datetime

from analyze_event import analyze_event, is_mock
from classify import classify_persistence, classify_stage
from market_check import market_check as run_market_check
from db import init_db, load_recent_events, save_event


def _view_recent() -> None:
    events = load_recent_events(10)
    if not events:
        print("No events saved yet.")
        return
    print(f"\n{len(events)} most recent event(s):\n")
    for e in events:
        print(f"  [{e['timestamp']}]  {e['headline']}")
        print(f"    Stage: {e['stage']}  |  Persistence: {e['persistence']}  |  Confidence: {e['confidence']}")
        print()


def main() -> None:
    init_db()

    print("Second Order")
    print("---------------------")
    print("1) Analyze new headline")
    print("2) View recent events")
    choice = input("\nChoice: ").strip()

    if choice == "2":
        _view_recent()
        return

    if choice != "1":
        print("Invalid choice.")
        return

    headline = input("\nPaste a headline: ").strip()

    if not headline:
        print("No headline provided.")
        return

    if len(headline) > 500:
        headline = headline[:500]
        print("Warning: headline truncated to 500 characters.")

    # Optional event date for anchored market validation
    date_input = input("Event date (YYYY-MM-DD, or Enter to skip): ").strip()
    event_date = None
    if date_input:
        try:
            datetime.strptime(date_input, "%Y-%m-%d")
            event_date = date_input
        except ValueError:
            print("Invalid date format — skipping event date.")

    # Step 1: classify
    stage = classify_stage(headline)
    persistence = classify_persistence(headline)
    timestamp = datetime.now().isoformat(timespec="seconds")

    print(f"\nStage:       {stage}")
    print(f"Persistence: {persistence}")

    # Step 2: analyze
    analysis = analyze_event(headline, stage, persistence)
    print(f"\nWhat changed: {analysis['what_changed']}")
    print(f"Mechanism:    {analysis['mechanism_summary']}")
    print(f"Beneficiaries:{', '.join(analysis['beneficiaries'])}")
    print(f"Losers:       {', '.join(analysis['losers'])}")
    print(f"Watch (↑):    {', '.join(analysis['beneficiary_tickers'])}")
    print(f"Watch (↓):    {', '.join(analysis['loser_tickers'])}")
    print(f"Confidence:   {analysis['confidence']}")

    # Step 3: market check
    market = run_market_check(analysis["beneficiary_tickers"], analysis["loser_tickers"], event_date=event_date)
    print(f"\nMarket:   {market['note']}")

    # Step 4: check for mock output before saving
    if is_mock(analysis):
        print("\n⚠  This is a mock/fallback result — not saved.")
        print("  Set ANTHROPIC_API_KEY in your .env file to get real analysis.")
        return

    # Step 5: optional research note
    notes = input("\nAdd a research note? (press Enter to skip): ").strip()

    # Step 6: save
    event = {
        "timestamp":          timestamp,
        "headline":           headline,
        "stage":              stage,
        "persistence":        persistence,
        "what_changed":       analysis["what_changed"],
        "mechanism_summary":  analysis["mechanism_summary"],
        "beneficiaries":      analysis["beneficiaries"],
        "losers":             analysis["losers"],
        "assets_to_watch":    analysis["assets_to_watch"],
        "confidence":         analysis["confidence"],
        "market_note":        market["note"],
        "market_tickers":     market["tickers"],
        "event_date":         event_date,
        "notes":              notes,
    }
    try:
        save_event(event)
    except Exception as e:
        print(f"\n⚠  Could not save event: {e}")
        print("  Analysis completed — but the result was not persisted.")


if __name__ == "__main__":
    main()
