"""Every template a cue can ORDER the model to use must show its params.

Measured 2026-09-06 on Maths 12 Ch8: of 17 turns where the model named a
template, 15 rendered NOTHING. The board was blank and no fallback ran.

    conic_figure() got an unexpected keyword argument 'conic_type'
    conic_figure() got an unexpected keyword argument 'curve'
    number_line()  got an unexpected keyword argument 'points'
    number_line()  got an unexpected keyword argument 'min'

The cause is exact, and the control is in the same data: the ONE template
whose parameters the prompt documented -- labeled_axes_plot -- was the one
whose parameter NAMES the model got right; it only mis-shaped a nested
value. The model can fill a schema it has been shown and invents one
otherwise. Six of fourteen cued templates were never described.

This is not a maths problem. projectile_scene is on that list.

So: the cue table and the prompt are two halves of one contract, edited in
different files by different people, and nothing tied them together. This
ties them.
"""
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def _cued_templates() -> set[str]:
    src = (_ROOT / "app" / "drona" / "tutor.py").read_text(encoding="utf-8")
    block = src[src.index("_DIAGRAM_CUES"):src.index("_WIDGET_CUES")]
    return set(re.findall(r'"([a-z_]+)"\)\s*,', block))


def _documented_templates() -> set[str]:
    """Names on a prompt bullet that also spells out parameters.

    A bullet, not a mention: the trigger rows further down name templates in
    prose and are exactly what misled a hand audit of this into reporting
    conic_figure as documented when it was not.
    """
    prompt = (_ROOT / "prompts" / "tutor.md").read_text(encoding="utf-8")
    found = set()
    for line in prompt.split("\n"):
        m = re.match(r"\s*\*\s+`([a-z_]+)`\s+—", line)
        if m and line.count("`") >= 4:
            found.add(m.group(1))
    return found


def test_every_cued_template_documents_its_params():
    cued, documented = _cued_templates(), _documented_templates()
    missing = sorted(cued - documented)
    assert not missing, (
        "these templates can be ordered by a _DIAGRAM_CUES row but their params "
        f"are never shown to the model, so it will invent names and the board "
        f"will render nothing: {missing}. Add a bullet to prompts/tutor.md with "
        "the real parameter names, read off the function signature."
    )


def test_the_check_can_actually_fail():
    """A guard that cannot fail is not a guard.

    The parser above is regex over prose. If a prompt edit broke the bullet
    format, `documented` would silently empty and this suite would still pass
    on `cued - {} == cued` being... non-empty. It would FAIL, correctly. But
    the inverse rots quietly: if `_cued_templates` stopped matching, `cued`
    empties and the real test passes vacuously. Pin both ends.
    """
    assert len(_cued_templates()) >= 10, "cue-table parser matched almost nothing"
    assert len(_documented_templates()) >= 10, "prompt parser matched almost nothing"
