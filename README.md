# Research Logger — local prototype

A new way to organize research projects aided by LLMs.

A local browser notebook for research repositories with reviewable Markdown drafts. It reads explicit questions, experiment summaries, statuses, and relationships from Markdown using only Python’s standard library. For `binding_affinity_v2` without structured entries, it shows a curated E00 example.

## Run

Clone your research repository with your usual GitHub setup if you do not have it locally. Then, from this directory, run:

```sh
python3 notebook.py --repo /path/to/binding_affinity_v2
```

The command opens `http://127.0.0.1:8000/`. Select a question, then an experiment to see its summary, linked evidence, figures, and recorded connections. Experiments connected to other questions are navigable from the details panel. Press **Refresh from files** after changing local files. Use **Add project** to connect a GitHub URL and switch projects in the selector. Stop the server with Ctrl-C. Use `--port 8001` for a different port or `--no-browser` to open the URL yourself. Python 3.9 or newer is required.

## Evidence and limits

- The app reads the existing clone and does not change it or write to GitHub. Files and figures must exist locally. Git-ignored run artifacts require a separate local copy.
- Links point to the local clone's HEAD SHA when Git can determine it; otherwise they point to `main`. Uncommitted local changes may differ from the linked GitHub revision. Evidence panels link to the source instead of reproducing long Markdown.
- Refresh rereads Markdown, statuses, references and figures. `graph.json` is the hand-reviewed fallback for binding_affinity_v2 when no structured entries are found; its summaries and statuses do not update automatically.
- The project energy conversions and the limits on interpreting them are documented in the source. A figure preview is not evidence that its underlying run artifacts are present.
- The top project selector opens one local repository at a time. Add project clones a GitHub repository into `.local/repositories/`; the server must have network access and Git credentials for private repositories. The notebook does not pull updates automatically, resolve cross-repository edges, or write to the source repository or GitHub without a reviewed, explicit sync action. For unstructured projects it lists verbatim question headings as candidates for human review, but does not classify the project, produce summaries, or restructure its files. Those are subsequent milestones; the present version deliberately requires no LLM or network connection to run.

## Markdown conventions

- `README.md`: motivation, main research questions, and an index. Recognized question headings use `## Q01 — Question text`.
- `TODO.md`: questions and experiments as checkboxes, for example `- [ ] Q01 — Question text` or `- [x] E00 — Baseline`. A question checkbox sets its status; an experiment checkbox supplies a fallback status when the experiment file has none.
- One concise `experiments/E00.md`, `experiments/E01.md`, etc. per experiment. IDs are scoped to each repository. Existing logs and detailed methods remain evidence, linked from the experiment rather than duplicated.

An experiment entry looks like this (illustrative schema, not an existing file):

```markdown
# E01 — Short experiment title

- **Status:** in progress
- **Question:** Q01 — the question being investigated
- **Depends on:** E00 — why the earlier experiment is needed
- **Follow-up:** E02 — what this result motivated (only when documented)
- **Evidence:** [Detailed log](../BASELINE-RESULTS.md), [figure](../outputs/affinity-distributions.png)

**What and why:** One or two sentences.

**Result:** One or two sentences, including a key limitation; use “not yet available” if incomplete.

**Next:** One concrete action or “none”.
```

The parser reads one leading local ID per reference. Separate multiple references in the same field with semicolons, for example `**Question:** Q01 — reproduction; Q02 — generalization`. Experiment status takes precedence over its TODO checkbox; conflicting completion states produce a warning. Missing status is unknown. Relationships should be explicit and typed: `investigates` a question, `depends on` a prerequisite, `follows up` another experiment, or `compares with` another experiment. A dependency is not automatically a causal result. Cross-repository references such as `pradhansmriti/binding_affinity_v2#E00` are flagged as unresolved in this prototype, rather than linked to a similarly named local experiment. Unclear links should be marked proposed until reviewed.

The fallback graph is a curated E00 walkthrough, not separate E00–E04 experiments. Its displayed statuses and links are manually entered in `graph.json`. Any agent-proposed change to repository files requires approval.

Run verification with `python3 -m unittest discover -s tests -v`.

### Sub-experiments and checks

An experiment Markdown file may contain `##` sections. In each section, use the same `**Status:**`, `**What and why:**`, `**Result:**`, `**Next:**`, and `**Evidence:**` fields. Sections are grouped as Completed or Open within the parent experiment. Completed sections show the result, linked figure previews, and evidence; if no figure is linked, the notebook says so. All statuses other than `complete`, including missing status, appear under Open. Section status does not change the parent experiment's status.

Number sections with headings such as `## E00.1 — Descriptor verification`. When a question has one linked experiment whose sections all use this numbering, the notebook shows the experiment overview on the question and the numbered sections directly beneath it. These section IDs are display labels; relationships to individual sections are not yet parsed.

## Editing, comments, and GitHub sync

Select a question or experiment and choose **Edit Markdown** or **Add comment**. Changes are saved as local drafts under `.local/drafts/`; comments are recorded in `research-notebook/COMMENTS.md` when synchronized. They are Markdown notes, not GitHub issue or pull-request comments.

Choose **Review & sync drafts** to inspect the diff. The approval button pushes a new `research-notebook/…` branch and opens a GitHub compare link; it does not merge or push to the current branch. A clean match between each edited file, the local HEAD, and its original draft base is required, and GitHub's current branch must match local HEAD. Conflicts stop sync and retain drafts. Git network access, push permission, and a configured Git author identity are required. A draft is not shown in the tree until applied and merged or otherwise brought into the local checkout.

## Organization proposals

Use **Propose organization** on an unstructured project to prepare local drafts. The offline prototype copies explicit question headings ending in `?`, and creates experiment entries only for headings explicitly marked `Experiment:` nested under a question. Status and results remain unknown. It preserves existing Markdown, does not overwrite existing structured questions or outstanding drafts, and does not decide whether a project is research. Review the diff before approving a GitHub branch. This conservative extractor is not an LLM; it cannot infer missing questions, summaries, experiment relationships, or scientific conclusions.
