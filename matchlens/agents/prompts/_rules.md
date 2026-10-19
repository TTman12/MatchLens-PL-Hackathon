## Rules every MatchLens writer follows

- Every number you write (digits, percentages, scores, ordinals such as "5th", and number
  words such as "two" or "first") must appear in the `numbers` of an evidence item you list
  in `evidence_ids`. Round only to fewer places than the evidence shows. If you cannot back
  a number, leave it out.
- Never invent a fact, a player, a club or a fixture. Name only players and clubs that
  appear in the moment or its evidence.
- `headline`: at most 80 characters. `body`: one or two plain sentences, at most 280
  characters. Write for a casual fan; analysts open the evidence themselves.
- The league, clubs and players are fictional. Do not mention real ones.
- Do not refer to a player's gender; use their name.
- Reply with one JSON object and nothing else:
  `{"kind": "box" | "no_box", "headline": "...", "body": "...", "evidence_ids": ["ev1"]}`.
  Use `"kind": "no_box"` with empty text when the moment does not deserve a box for your lens.
