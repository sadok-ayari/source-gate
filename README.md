# evidence-ledger

A deterministic gate for any document that makes claims.

Every paragraph, list item and table row in a brief is treated as one claim. A claim passes only when it cites a source that is declared, dated, and reachable. Anything else blocks.

```
$ python3 ledger.py check examples/brief.md --sources examples/sources.json

evidence-ledger  ·  examples/brief.md
5 claims  ·  3 sources declared

    L9  UNKNOWN_SOURCE cites S4, which is not declared in the sources file
   L13  UNCITED        paragraph makes a claim with no source token: "Implementation is on track and the client is satisfied."
   L15  UNCITED        paragraph makes a claim with no source token: "The programme is the most ambitious of its kind in the region."
    --  ORPHAN_SOURCE  S3 is declared but never cited

FAIL: 3 blocking, 1 warning
```

## Why this exists

Language models made the drafting step cheap. They did not make the attribution step cheap, and attribution is what a ministry, a donor or an auditor actually reads. A paragraph that cannot name its source is a liability with good grammar.

The usual fix is a stronger prompt, which is a probabilistic answer to a deterministic problem. This is the deterministic part: no model runs in the gate, so any reviewer can reproduce the result, and a passing brief means the same thing on every machine.

It is also the cheapest way to keep generated text honest at volume. Draft with whatever model you like; the gate does not care where the sentences came from, only whether they can be defended.

## What it checks

| Code | Severity | Meaning |
|---|---|---|
| `UNCITED` | blocking | A claim unit carries no source token |
| `UNKNOWN_SOURCE` | blocking | A citation points at a source that is not declared |
| `NO_URL` | blocking | The cited source has no url in the sources file |
| `NO_DATE` | blocking | The cited source has no usable date (`YYYY-MM-DD`) |
| `STALE` | warning | The cited source is older than the staleness threshold |
| `ORPHAN_SOURCE` | warning | A source is declared and never cited |

Exit code is `0` on pass and `1` when anything blocks, so it drops straight into CI, a pre-commit hook, or a delivery checklist.

## Usage

```bash
python3 ledger.py check BRIEF.md --sources sources.json
python3 ledger.py check BRIEF.md --sources sources.json --max-age-months 12
python3 ledger.py check BRIEF.md --sources sources.json --json
python3 ledger.py check BRIEF.md --sources sources.json --quiet
```

No dependencies. Python 3.10 or later, standard library only.

## Format

Cite with `[S1]` or `[S1, S2]` anywhere in the claim unit. Bracketed tokens inside fenced code blocks are ignored, and headings are not claims.

```json
{
  "sources": {
    "S1": {
      "title": "Programme Annual Report 2025",
      "publisher": "Implementing agency",
      "url": "https://example.org/annual-report-2025",
      "date": "2026-03-31"
    }
  }
}
```

## In CI

```yaml
- name: Claim gate
  run: python3 ledger.py check briefs/monthly.md --sources briefs/sources.json
```

A failing gate blocks the merge. That is the whole idea: the document cannot reach a counterpart unfunded by evidence.

## What it is not

It does not judge whether a claim is true, well-evidenced, or correctly worded. A cited source can still be the wrong source. The gate removes the excuse that nothing was checked, not the need for judgement.

## Tests

```bash
python3 -m unittest -v
```

Thirteen tests covering parsing (paragraphs, list items, table rows, fenced code, multi-token citations) and the gate (each code, each severity, exit codes, JSON output).

## Licence

MIT.
