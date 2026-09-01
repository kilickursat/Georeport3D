"""Remove CAD title-block artefacts from recovered drawing text.

OCR of an engineering drawing reads the whole sheet, including the title block and
the plotting footer. On a real geotechnical report that yielded, on every sheet, the
authoring system's file path, the plot timestamp, and the drafter's username - text
that is not about the ground, that pollutes routing, and that should not flow into
prompts, logs, or a public repository.

What is stripped here is deliberately narrow. The payload of these sheets looks
structurally similar to the noise: `T-201`, `TS-202`, `B-3` are borehole
identifiers, `20+00` is a station, `417.20` is an elevation. A pattern loose enough
to catch every artefact would take those with it, and losing a borehole identifier
is far worse than keeping a drawing number. So only unambiguous machine-generated
tokens are removed: URIs, filesystem paths, and plot timestamps.

Operator names are the known gap. `ksheffy` appeared on every sheet of the report
this was measured against, but a bare username is indistinguishable from a
geological abbreviation by pattern alone. It needs a redaction pass with an actual
identifier list at the evidence boundary, not a guess here.
"""

from __future__ import annotations

import re
from typing import Final

_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    # ProjectWise and other scheme URIs: pw://pwhdruscen01:HDR_US_Central_01/...
    ("uri", re.compile(r"\b[a-z][a-z0-9+.\-]*://\S+", re.IGNORECASE)),
    # Windows paths: C:\pwworking\cen1ro101\d0894629\CBD2-GC2-1000.200
    ("windows_path", re.compile(r"\b[A-Za-z]:\\[^\s|]+")),
    # Deep POSIX paths. Three or more segments, so a lone ratio or fraction is safe.
    ("posix_path", re.compile(r"(?:/[\w.\-]+){3,}/?")),
    # CAD plot stamps: 18-FEB-2020 09:56
    (
        "plot_timestamp",
        re.compile(r"\b\d{1,2}-[A-Za-z]{3}-\d{4}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?\b"),
    ),
)

_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"[ \t]{2,}")


def strip_noise(text: str) -> str:
    """Remove machine-generated title-block tokens, leaving the drawing's own text."""
    if not text:
        return ""
    for _, pattern in _PATTERNS:
        text = pattern.sub(" ", text)
    return _WHITESPACE.sub(" ", text).strip()


def noise_report(text: str) -> dict[str, int]:
    """Count what each pattern would remove, for auditing a document's noise."""
    return {name: len(pattern.findall(text)) for name, pattern in _PATTERNS}
