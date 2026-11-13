"""A single-file HTML report on a build, for a human rather than a machine.

Everything in here is already written to disk somewhere — the manifest, the risk
report, the dataset itself. What is missing is a way to *look* at it. Comparing
a report before and after de-identification is the one check nobody can
automate, because the question is "did this stay clinically useful", and today
it means opening two files in two windows and reading across. A terminal is bad
at this and always will be.

So this is a static artefact in the same spirit as the manifest: no server, no
state, no key handling, one file that opens offline and keeps working when the
tool that made it is gone.

**And it contains patient data, which the manifest does not.** The before/after
comparison is the whole point of the page, and the "before" half is an
unredacted clinical report. That makes this the only output of `commissura`
that must never leave the organisation, and the difference has to be impossible
to miss:

* it is **never written inside the dataset directory**, and :func:`write_report`
  refuses rather than warning — a file there would be digested into the
  manifest's own integrity list and shipped with the release;
* the page says what it holds in its first screenful, not in a footnote;
* the operator names the file, because there is no safe default location for
  something that must not be filed with the dataset.

Nothing here is reusable as a template system and it should not become one. It
is plain string assembly with escaping, because a report that needs a build step
is a report nobody regenerates.
"""

from __future__ import annotations

import html
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from commissura import layout
from commissura.build.writer import BuildSummary
from commissura.read.corpus import RawCorpus, read_exact

DEFAULT_COMPARISONS: Final = 5
"""How many before/after pairs to show unless asked otherwise.

A few is the point. Thirty would make a file nobody scrolls and would embed
thirty unredacted reports where five make the same case.
"""

_STYLE: Final = """
:root { color-scheme: light dark; }
* { box-sizing: border-box; }
body {
  margin: 0; padding: 2rem 1rem; font: 15px/1.6 system-ui, sans-serif;
  background: #fbfbfa; color: #1a1a19; max-width: 72rem; margin-inline: auto;
}
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.1rem; margin: 2.5rem 0 .75rem; padding-bottom: .3rem;
     border-bottom: 1px solid #ddd; }
h3 { font-size: .95rem; margin: 1.5rem 0 .4rem; font-weight: 600; }
.sub { color: #666; margin: 0 0 1.5rem; }
.warn {
  border: 2px solid #a3301c; background: #fdf2f0; color: #6b1f12;
  padding: 1rem 1.25rem; border-radius: 6px; margin: 1.5rem 0;
}
.warn strong { display: block; font-size: 1.05rem; margin-bottom: .35rem; }
table { border-collapse: collapse; width: 100%; margin: .5rem 0 1rem; font-size: 14px; }
th, td { text-align: left; padding: .35rem .6rem; border-bottom: 1px solid #e5e5e3; }
th { font-weight: 600; color: #444; background: #f3f3f1; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(13rem, 1fr)); gap: .75rem; }
.card { background: #fff; border: 1px solid #e5e5e3; border-radius: 6px; padding: .7rem .9rem; }
.card .k { color: #666; font-size: 13px; }
.card .v { font-size: 1.25rem; font-variant-numeric: tabular-nums; }
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; margin-bottom: 1.5rem; }
pre {
  margin: 0; padding: .8rem; background: #fff; border: 1px solid #e5e5e3;
  border-radius: 6px; font: 12.5px/1.5 ui-monospace, monospace;
  white-space: pre-wrap; overflow-wrap: anywhere;
}
pre.before { border-left: 3px solid #a3301c; }
pre.after { border-left: 3px solid #2f6f4f; }
.tag { font: 12px ui-monospace, monospace; padding: .1rem .35rem;
       border-radius: 3px; background: #eee; }
.removed { background: #f6e3e0; } .replaced { background: #e9eef7; }
.kept { background: #e4efe8; }
ul.risks { margin: .5rem 0; padding-left: 1.2rem; }
ul.risks li { margin-bottom: .35rem; }
footer { margin-top: 3rem; color: #888; font-size: 13px; }
@media (max-width: 55rem) { .pair { grid-template-columns: 1fr; } }
@media (prefers-color-scheme: dark) {
  body { background: #16161a; color: #e8e8e6; }
  h2 { border-color: #333; }
  th { background: #22222a; color: #bbb; }
  th, td { border-color: #2c2c33; }
  .card, pre { background: #1d1d23; border-color: #2c2c33; }
  .warn { background: #2a1512; border-color: #c0432c; color: #f3c9c0; }
  .tag { background: #2c2c33; }
  .removed { background: #3a1f1b; } .replaced { background: #1d2738; }
  .kept { background: #1c2e23; }
}
"""


@dataclass(frozen=True, slots=True)
class Comparison:
    """One report, before and after."""

    source: str
    output: str
    before: str
    after: str


def _esc(value: object) -> str:
    """Escape a value for HTML text content *and* for an attribute.

    ``quote=True`` is what makes it safe in an attribute as well as in text, and
    both uses exist here. Two ``class="tag {...}"`` interpolations once skipped
    it, which was the one place in this project where input reaches a format a
    browser interprets without passing through here: a disposition reading
    ``removed" onmouseover="alert(1)`` closed the attribute and attached an
    event handler. Every interpolation goes through this function, with no
    exception for a value that "cannot" contain a quote — the manifest is read
    from disk, and somebody with write access to a share is exactly the threat
    ``manifest_hmac`` exists for.

    Args:
        value: Anything; it is rendered with :func:`str` first.

    Returns:
        The escaped text.
    """
    return html.escape(str(value), quote=True)


def _tool_version(manifest: dict[str, object]) -> str:
    """Return the version of commissura the manifest records.

    Args:
        manifest: The manifest payload, as read from disk.

    Returns:
        The version, or an empty string when the manifest records none. A
        manifest this tool wrote always does; one that has been edited by hand
        may not, and the report is not the place to raise about it.
    """
    versions = manifest.get("tool_versions")
    if not isinstance(versions, dict):
        return ""
    found = versions.get("commissura", "")
    return found if isinstance(found, str) else ""


def _cards(pairs: list[tuple[str, object]]) -> str:
    """Render a row of headline numbers."""
    cells = "".join(
        f'<div class="card"><div class="k">{_esc(k)}</div><div class="v">{_esc(v)}</div></div>'
        for k, v in pairs
    )
    return f'<div class="grid">{cells}</div>'


def _table(headers: list[str], rows: list[list[str]], numeric: set[int] = frozenset()) -> str:  # type: ignore[assignment]
    """Render a table, with the given column indices right-aligned."""
    head = "".join(
        f'<th class="num">{_esc(h)}</th>' if i in numeric else f"<th>{_esc(h)}</th>"
        for i, h in enumerate(headers)
    )
    body = ""
    for row in rows:
        cells = "".join(
            f'<td class="num">{cell}</td>' if i in numeric else f"<td>{cell}</td>"
            for i, cell in enumerate(row)
        )
        body += f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def gather_comparisons(
    corpus: RawCorpus, summary: BuildSummary, limit: int = DEFAULT_COMPARISONS
) -> list[Comparison]:
    """Read the first few reports in both their forms.

    Args:
        corpus: The corpus built from, for the originals.
        summary: The build, for the source-to-output pairing.
        limit: How many to read.

    Returns:
        The comparisons that could be read. A pair whose files have since moved
        is skipped rather than raising: this is a convenience artefact, and
        failing to build a dataset because a report could not be re-read for a
        picture of it would be the wrong order of priorities.
    """
    found: list[Comparison] = []
    for pair in summary.report_pairs:
        if len(found) >= limit:
            break
        source = corpus.root / pair.source
        output = summary.root / pair.output
        if not (source.is_file() and output.is_file()):
            continue
        found.append(
            Comparison(
                source=pair.source,
                output=pair.output,
                before=read_exact(source),
                after=read_exact(output),
            )
        )
    return found


def _redaction_rows(summary: BuildSummary) -> list[list[str]]:
    """Count what the scrubber substituted, per category, across every document."""
    documents: Counter[str] = Counter()
    occurrences: Counter[str] = Counter()
    for report in summary.scrub_reports:
        for category, count in report.categories().items():
            documents[category] += 1
            occurrences[category] += count
    return [
        [
            f'<span class="tag">{_esc(category)}</span>',
            str(documents[category]),
            str(occurrences[category]),
        ]
        for category in sorted(occurrences)
    ]


def _field_rows(manifest: dict[str, object]) -> str:
    """Render the manifest's observed field table, one section per modality."""
    modalities = manifest.get("modalities")
    if not isinstance(modalities, list):
        return "<p>This manifest records no field table.</p>"

    sections = ""
    for entry in modalities:
        if not isinstance(entry, dict):
            continue
        name = entry.get("modality", "?")
        observed = entry.get("fields_observed", {})
        rows = []
        for item in entry.get("fields", []):
            if not isinstance(item, dict):
                continue
            disposition = str(item.get("disposition", ""))
            label = _esc(item.get("field", ""))
            if item.get("name"):
                label += f' <span class="k">{_esc(item["name"])}</span>'
            rows.append(
                [
                    label,
                    f'<span class="tag {_esc(disposition)}">{_esc(disposition)}</span>',
                    str(item.get("files_present", 0)),
                    _esc(item.get("note", "")),
                ]
            )
        counts = ", ".join(f"{k} {v}" for k, v in observed.items()) if observed else ""
        sections += (
            f'<h3>{_esc(name)} <span class="k">· {_esc(entry.get("key_kind", ""))}'
            f" · {_esc(entry.get('files_read', 0))} files · {_esc(counts)}</span></h3>"
            + _table(["field", "disposition", "files", "note"], rows, numeric={2})
        )
        body = entry.get("body")
        if isinstance(body, list) and body:
            body_rows = [
                [
                    f'<span class="tag">{_esc(row.get("category", ""))}</span>',
                    f'<span class="tag {_esc(row.get("disposition", ""))}">'
                    f"{_esc(row.get('disposition', ''))}</span>",
                    str(row.get("documents_affected", 0)),
                    str(row.get("occurrences", 0)),
                    _esc(row.get("marker", "")),
                ]
                for row in body
                if isinstance(row, dict)
            ]
            sections += '<h3>prose body <span class="k">· not fields</span></h3>' + _table(
                ["category", "disposition", "documents", "occurrences", "marker"],
                body_rows,
                numeric={2, 3},
            )
    return sections


def render(
    *,
    corpus: RawCorpus,
    summary: BuildSummary,
    manifest: dict[str, object],
    risk: dict[str, object],
    comparisons: list[Comparison],
) -> str:
    """Build the whole page as one HTML string.

    Args:
        corpus: The corpus built from.
        summary: What the build produced.
        manifest: The manifest payload.
        risk: The risk report payload.
        comparisons: Reports to show side by side.

    Returns:
        A complete HTML document.
    """
    source = manifest.get("source", {})
    source = source if isinstance(source, dict) else {}
    profile = manifest.get("profile", {})
    profile = profile if isinstance(profile, dict) else {}

    pairs_html = ""
    for item in comparisons:
        pairs_html += (
            f'<h3>{_esc(item.source)} <span class="k">&rarr; {_esc(item.output)}</span></h3>'
            f'<div class="pair"><pre class="before">{_esc(item.before)}</pre>'
            f'<pre class="after">{_esc(item.after)}</pre></div>'
        )
    if not comparisons:
        pairs_html = "<p>No report could be read in both forms.</p>"

    below = risk.get("combinations_below_threshold")
    below = below if isinstance(below, list) else []
    quasi = risk.get("quasi_identifiers")
    quasi_names = ", ".join(str(name) for name in quasi) if isinstance(quasi, list) else ""
    k_rows = [
        [
            ", ".join(f"{_esc(k)}={_esc(v)}" for k, v in entry.get("values", {}).items()),
            str(entry.get("k", "")),
        ]
        for entry in below[:40]
        if isinstance(entry, dict)
    ]

    risks = summary.residual_risks()
    risk_items = "".join(f"<li>{_esc(item)}</li>" for item in risks)

    missing = summary.missing_for_conformance
    conformance = (
        "all mandatory properties supplied"
        if not missing
        else "missing: " + ", ".join(_esc(item) for item in missing)
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>commissura build report</title>
<style>{_STYLE}</style></head><body>

<h1>commissura build report</h1>
<p class="sub">Dataset <code>{_esc(summary.root.name)}</code> ·
built from <code>{_esc(source.get("root_name", "?"))}</code> ·
generated {_esc(manifest.get("generated_at", ""))}</p>

<div class="warn"><strong>This file contains patient data. Do not release it.</strong>
The comparisons below show clinical reports <em>before</em> de-identification,
which is the point of the page and makes it the one output of this tool that
must stay inside your organisation. The dataset itself, the manifest and the
risk report carry no identifiers; this does. It is deliberately written outside
the dataset directory so it cannot be shipped with it by accident.</div>

<h2>What was built</h2>
{
        _cards(
            [
                ("subjects", summary.subject_count),
                ("sessions", summary.session_count),
                ("files written", summary.file_count),
                ("free-text redactions", summary.redaction_count),
                ("linkage issues", summary.linkage_issues),
                ("records dropped", len(summary.dropped)),
            ]
        )
    }
<p class="sub">Key fingerprint <code>{_esc(manifest.get("key_fingerprint", "?"))}</code> ·
de-identification rules {_esc(manifest.get("deidentification_rule_version", "?"))} ·
{_esc(profile.get("name", "?"))} {_esc(profile.get("release", ""))},
{_esc(profile.get("tier", ""))} tier · {conformance}</p>

<h2>Before and after</h2>
<p class="sub">The check nobody can automate: did the clinical content survive?
A scrubber that removed the medicine would protect a useless dataset.</p>
{pairs_html}

<h2>Free-text redactions by category</h2>
{_table(["category", "documents", "occurrences"], _redaction_rows(summary), numeric={1, 2})}

<h2>What became of every field</h2>
<p class="sub">Observed from this run, not declared. A field the input carried
and the dataset does not is reported whether or not anybody anticipated it.</p>
{_field_rows(manifest)}

<h2>Residual risk</h2>
<p class="sub">What the method cannot reach, listed rather than scored. A score
invites a reader to treat de-identification as solved above some threshold.</p>
{f'<ul class="risks">{risk_items}</ul>' if risks else "<p>Nothing reported.</p>"}

<h2>Re-identification risk over participant attributes</h2>
<p class="sub">k-anonymity over {_esc(quasi_names)}
· {_esc(risk.get("participants", "?"))} participants · minimum k
{_esc(risk.get("minimum_k", "?"))} · {len(below)} combination(s) below
{_esc(risk.get("threshold", "?"))}. This is a measurement, not a certificate:
this tool pseudonymises and does not anonymise.</p>
{_table(["combination", "k"], k_rows, numeric={1})}

<footer>Generated by commissura
{_esc(_tool_version(manifest))}.
Static artefact: no server, no state, no key. Safe to open offline, unsafe to
send anywhere.</footer>
</body></html>
"""


def write_report(
    path: Path,
    *,
    corpus: RawCorpus,
    summary: BuildSummary,
    manifest: dict[str, object],
    risk: dict[str, object],
    comparisons: int = DEFAULT_COMPARISONS,
    destination: Path | None = None,
) -> Path:
    """Write the HTML report, refusing to put it inside the dataset.

    Args:
        path: Where to write it.
        corpus: The corpus built from.
        summary: What the build produced. ``summary.root`` is the tree the files
            were written to, which during a staged build is not where they will
            end up.
        manifest: The manifest payload.
        risk: The risk report payload.
        comparisons: How many before/after pairs to include.
        destination: Where the dataset will be published, when that differs
            from ``summary.root``. Both are refused.

    Returns:
        The path written.

    Raises:
        ValueError: If the path is inside either tree. Refused rather than
            warned about: a file there would be digested into the manifest's
            integrity list and released with the dataset, and the page holds
            unredacted reports. The obvious thing to type is
            ``--report ./dataset/report.html``, which is exactly the mistake.
    """
    resolved = path.resolve()
    # Both trees, and this is not belt-and-braces. Builds are staged, so during
    # one `summary.root` is a directory beside the destination that will *become*
    # the dataset -- a file written into it is published with everything else.
    # Checking only `summary.root` would have let `--report ./dataset/x.html`
    # through from the moment staging was introduced, which is what happened: the
    # test for this guard caught it the same afternoon.
    forbidden = [summary.root.resolve()]
    if destination is not None:
        forbidden.append(destination.resolve())
    for tree in forbidden:
        if resolved == tree or tree in resolved.parents:
            raise ValueError(
                f"refusing to write {resolved} inside the dataset at {tree}. "
                "This report contains unredacted reports; a file inside the dataset "
                "is digested into the manifest and shipped with the release. Put it "
                "somewhere that does not travel."
            )

    document = render(
        corpus=corpus,
        summary=summary,
        manifest=manifest,
        risk=risk,
        comparisons=gather_comparisons(corpus, summary, comparisons),
    )
    resolved.parent.mkdir(parents=True, exist_ok=True)
    with resolved.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(document)
    return resolved


__all__ = [
    "DEFAULT_COMPARISONS",
    "Comparison",
    "gather_comparisons",
    "layout",
    "render",
    "write_report",
]
