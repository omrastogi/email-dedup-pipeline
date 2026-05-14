# AI Usage

## Tool
Claude Code (Sonnet 4.x) as the primary code generator. ChatGPT used as a second reviewer for adversarial bug-finding.

## Prompting Strategy

I worked spec-down, not task-up. The full assignment was loaded into context first so the AI could plan globally, then I broke execution into units and prompted each one with its own scope and tests.

**Step 1: Plan from spec.** Dropped the entire assignment doc into Claude Code and asked for a detailed plan. Reading what the AI proposed surfaced architectural decisions I needed to make myself before any code was written.

**Step 2: Fix the plan.** First plan coupled the parser and the DB writer in one module. I rewrote that part so the parser returns dicts and ingestion calls the parser separately. Easier to test, easier to debug when the pipeline breaks.

**Step 3: Re-prompt for a unit-by-unit plan.** Once the architecture was right, I asked for a step-by-step build plan broken into modules: `parser`, `db`, `dedupe`, `notify`. Each unit got its own implementation prompt and its own pytest suite plus an `explore_<unit>.py` script for manual workflow checks.

**Step 4: Build module by module.** For each unit I prompted Claude Code to write the module and its tests, ran the tests and the explore script, then reviewed before moving to the next unit.

**Step 5: Glue and main.py last.** Only after all four modules existed and tested green did I have Claude write the orchestration layer.

### Example prompts

1. **Initial planning prompt:** "Read the attached spec. Build a detailed plan covering architecture, module breakdown, and the data flow from raw maildir to MCP send. Don't write code yet." — used to surface decisions before commitment.

2. **Architectural correction prompt:** "Decouple the DB layer from the parser. Parser should return dicts, ingestion should walk maildir and call the parser, and a separate db module handles inserts. Reasoning: I want to debug parsing failures without DB state in the way."

3. **Concrete build prompt with real-data goal:** "Let's parse the data and find duplicate examples. Finding duplicates is an important part of the project." — gave the AI a working target instead of a spec checklist, which made it implement and test against the actual maildir on the first pass instead of writing code in the abstract.

4. **Unit build prompt (parser):** "Build src/parser/parse_emails.py with a single function `parse_email_file(path, maildir_root)` returning a dict matching the mandatory + optional fields in section 3 of the spec. Use email.message_from_bytes. Handle non-standard timezone abbreviations (PST/PDT/EST/EDT/CST/CDT/MST/MDT) before passing dates to parsedate_to_datetime. Raise ValueError for missing mandatory fields."

5. **Adversarial review prompt (sent to ChatGPT):** "Here is a Python email parser. Find bugs, edge cases, and any silent failure modes. Be adversarial. Check timezone math, encoding handling, Windows path quirks." — used a different model for review so I wasn't getting Claude to mark its own homework.

## Iterations & Debugging

**Case 1: Windows file traversal silently dropped emails.** First parser pass used `Path.rglob("*")` and `Path.read_bytes()`. On Windows both quietly mishandle trailing-dot filenames like `1.` (which exist in the Enron corpus). Files were skipped without error. Fixed by switching to `os.walk` for traversal and prepending the `\\?\` extended path prefix when opening files. Lesson: AI defaults to POSIX-shaped code; cross-platform quirks only show up against real data.

**Case 2: EST offset off by 200 seconds.** The AI's tz abbreviation table had `"EST": -18200`. Correct value is `-18000` (UTC-5 = -5*3600). Manual review missed it because the number looks plausible. ChatGPT caught it during the adversarial review pass. Fix was a one-character edit. Lesson: numerical constants need a second pair of eyes, ideally a different model.

**Case 3: Parser-DB coupling in the first plan.** The AI proposed a single ingestion module that parsed and inserted in one pass. I pushed back, decoupled them, and the resulting code was significantly easier to debug because parse failures didn't leave half-written DB rows. Lesson: review the plan before approving code generation. Architectural fixes are 10x cheaper at the plan stage than the code stage.

**Case 4: 1,826 parse failures, almost all "empty To field".** First full ingestion run on the 5 mailboxes parsed 20,668 of 22,494 files. The failure log showed almost every miss was system or draft emails with no To header. Decision: keep the strict mandatory-fields check rather than relaxing it, log them as expected failures, and surface the count in stats. The corpus quality issue is real and worth recording in the parse log rather than hiding.

## What I Wrote vs What AI Wrote

Rough split: ~85% AI-generated code, ~15% manual edits and decisions.

**AI-generated (then reviewed and accepted):**
- Most module implementations and test scaffolding
- Boilerplate (dataclasses, SQL schema, CLI argparse, MCP server skeleton)
- First-draft fuzzy matching logic, Union-Find, .eml writer

**Manual contributions:**
- All architectural decisions: parser/DB decoupling, the (sender, normalized_subject) bucketing strategy for dedupe, INSERT OR IGNORE policy for Message-ID collisions, dry-run-by-default for the MCP step
- Mailbox selection (5 mailboxes spanning executive/legal/trader roles, ~22k emails)
- Every prompt and the CLAUDE.md decision log
- The two-pass review process (manual + ChatGPT cross-review)
- Bug fixes from review: Windows path traversal, EST offset, hardcoded paths
- Logic suggestions and improvements after each module landed

## Lessons Learned

**What worked well:** Spec-first planning before any code. Module-by-module build with tests and explore scripts written alongside the code, not after. Pointing the AI at real data early (the "find duplicate examples" prompt) instead of synthetic test cases. Using a second model (ChatGPT) for adversarial review caught bugs that single-model review missed every time. The model took care of Database and SQL without any issue as this part is mostly structured.

**What was harder than expected:** Numerical constants and edge cases in stdlib-adjacent code (timezone tables, Windows path prefixes, MIME encoding policies). The AI produces code that looks right on the surface but has off-by-N bugs that don't fail loudly. Adversarial review is the only way I found these reliably.

**What I'd change next time:** Run the AI's output against real corpus data even sooner. The parser passed unit tests but missed ~8% of the corpus on the first real-data run because of the Windows path issue, which no synthetic test would have caught.