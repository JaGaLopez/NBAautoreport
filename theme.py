"""The app's visual language in one place: colors, type, spacing, and the CSS
overrides that push Streamlit's defaults where this report needs them.

Everything the app paints by hand is defined here rather than inline at the
call site, so a color or a size is changed once and every surface follows.
Three layers, in order:

  1. Tokens      - the raw values, named by role.
  2. PAGE_CSS    - the global override sheet, built from those tokens.
  3. Primitives  - the small render helpers (insight, section_label, bubbles,
                   tech_note) that are pure presentation and nothing else.

The app runs on Streamlit's dark theme. There is no .streamlit/config.toml
pinning it, so the surface tokens below record the values the hand-rolled CSS
assumes: switching the app to light would need them re-derived.
"""

import streamlit as st
from st_aggrid.shared import JsCode


# ---------------------------------------------------------------------------
# Color
# ---------------------------------------------------------------------------

# Streamlit's own dark-theme surface and body text. The Details toggle repaints
# itself in these two so the switch reads as white-on-dark instead of the
# default red.
SURFACE_APP = "#0e1117"
TEXT_PRIMARY = "#fafafa"

# The vertical rule between the two team columns, and the team-code labels on
# the efficiency scatter. Same gray, both roles: quiet lines beside the content.
RULE = "#cccccc"
CHART_LABEL = RULE

# Card tables. These are drawn as plain HTML rather than st.dataframe, which
# paints into a canvas and goes soft whenever the browser's pixel ratio changes
# under it (a zoom, or a window moved to a display with a different ratio). The
# values track Streamlit's own dark dataframe so the swap is not visible.
TABLE_BORDER = "rgba(250, 250, 250, 0.1)"
TABLE_HEADER_TEXT = "rgba(250, 250, 250, 0.6)"
# Opaque on purpose. The header is sticky, so a translucent fill would let the
# rows scrolling beneath it show through and collide with the column names.
# This is SURFACE_APP lifted 3% toward white, the tint it used to carry.
TABLE_HEADER_BG = "#15181e"

# Delta pills. Lifted from Streamlit's st.metric so the hand-rolled bubbles in
# bubbles() match the arrows st.metric draws on the neighboring cards.
DELTA_GOOD = "rgb(9, 171, 59)"
DELTA_BAD = "rgb(255, 43, 43)"
DELTA_GOOD_BG = "rgba(9, 171, 59, 0.2)"
DELTA_BAD_BG = "rgba(255, 43, 43, 0.2)"

# Percentile heatmap, best to worst. Each step is (floor, background, text);
# a value at or above the floor takes that row, and anything under the last
# floor falls through to PERCENTILE_WORST. The light middle bands carry black
# text, the saturated ends carry white.
PERCENTILE_RAMP = (
    (80, "#27ae60", "white"),   # strong
    (60, "#a8e6cf", "black"),   # above average
    (40, "#e8e8e8", "black"),   # middle
    (20, "#ffb3b3", "black"),   # below average
)
PERCENTILE_WORST = ("#e74c3c", "white")

# Charts.
CHART_SELECTED = "#ff4b4b"    # the highlighted team on the efficiency scatter
CHART_TEAM = "#1f77b4"        # the selected team's net rating line
CHART_LEAGUE = "#e74c3c"      # the league average line, same red as PERCENTILE_WORST
CHART_TREND = "#5dade2"       # dashed line of best fit
CHART_GUIDE = "#888888"       # dashed league-average crosshairs
CHART_SCHEME = "blueorange"   # diverging ramp for net rating


# ---------------------------------------------------------------------------
# Type
# ---------------------------------------------------------------------------

# The report reads top-down: page title, section heading, panel label, then the
# body. Panel labels sit at 1.25rem, and the headings above them are scaled by
# roughly the same factor to hold that hierarchy.
FONT_PAGE_TITLE = "3rem"       # h1
FONT_SECTION = "1.9rem"        # h3
FONT_PANEL_LABEL = "1.25rem"   # section_label, and the st.metric label
FONT_METRIC_VALUE = "1.6rem"   # smaller than Streamlit's 2.25rem: the value
                               # line carries the "vs. League Avg" comparison
FONT_SELECT_LABEL = "1.15rem"
FONT_SELECT_INPUT = "1.1rem"
FONT_BODY = "0.9rem"           # insight()
FONT_TABLE = "0.875rem"        # simple_table()
FONT_PILL = "0.875rem"         # bubbles()
FONT_CHART_LABEL = 10          # Altair takes px, not rem

WEIGHT_EMPHASIS = "600"        # panel labels, metric labels, selector labels


# ---------------------------------------------------------------------------
# Spacing and shape
# ---------------------------------------------------------------------------

PAGE_PAD_TOP = "2rem"
COLUMN_RULE_WIDTH = "2px"
COLUMN_RULE_PAD = "2rem"       # gutter between the rule and the right column

# Margins are written as full shorthand because each of these sits in a
# different relationship to what precedes it: bubbles pull up under the metric
# they annotate, insights sit under their heading, labels lead their panel.
MARGIN_BODY = "0.25rem 0 0.5rem 0"
MARGIN_PANEL_LABEL = "0 0 0.4rem 0"
MARGIN_PILL_ROW = "-0.5rem 0 0.5rem 0"

TABLE_CELL_PAD = "0.5rem 0.75rem"
TABLE_RADIUS = "0.25rem"

PILL_PAD = "0.15rem 0.6rem"
PILL_RADIUS = "0.5rem"
PILL_GAP = "0.5rem"

# Chart geometry. Widths are always "container"; only the heights are fixed,
# and the bottom padding leaves room for the axis title under each.
CHART_HEIGHT_SCATTER = 460
CHART_PAD_SCATTER = {"bottom": 20}
CHART_HEIGHT_LINE = 400
CHART_PAD_LINE = {"bottom": 30}
CHART_POINT_SIZE = 170
CHART_POINT_OPACITY = 0.85


# ---------------------------------------------------------------------------
# Generated style sheets
# ---------------------------------------------------------------------------

PAGE_CSS = f"""
<style>
    .block-container {{ padding-top: {PAGE_PAD_TOP}; }}
    [data-testid="stVerticalBlock"] > [data-testid="stHorizontalBlock"] > div:nth-child(2) {{
        border-left: {COLUMN_RULE_WIDTH} solid {RULE};
        padding-left: {COLUMN_RULE_PAD};
    }}
    /* Narrative cards: the stat's name is the headline, so scale the metric
       label up and the value down. */
    [data-testid="stMetricLabel"] p {{ font-size: {FONT_PANEL_LABEL}; font-weight: {WEIGHT_EMPHASIS}; }}
    /* Details toggle: white track with a dark knob when on, instead of the
       default red. first-of-type picks the switch itself; the label text sits
       in a sibling div that must keep its own background. */
    [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type {{
        background-color: {TEXT_PRIMARY} !important;
    }}
    [data-testid="stCheckbox"] label[data-selected="true"] > div:first-of-type > div {{
        background-color: {SURFACE_APP} !important;
    }}
    [data-testid="stMetricValue"] {{ font-size: {FONT_METRIC_VALUE}; }}
    .block-container h1 {{ font-size: {FONT_PAGE_TITLE}; }}
    .block-container h3 {{ font-size: {FONT_SECTION}; }}
    [data-testid="stSelectbox"] label p {{ font-size: {FONT_SELECT_LABEL}; font-weight: {WEIGHT_EMPHASIS}; }}
    /* The chosen value sits in the combobox input; the surrounding widget
       renders through a template element that plain CSS cannot reach into. */
    [data-testid="stSelectbox"] input {{ font-size: {FONT_SELECT_INPUT}; }}
    /* Card tables. Left aligned throughout: these are display-only, so nothing
       reads better right aligned, and one shared edge is easier to scan. The
       header sticks so it survives a table given a max-height. */
    .card-table {{
        overflow: auto;
        border: 1px solid {TABLE_BORDER};
        border-radius: {TABLE_RADIUS};
        margin-bottom: 1rem;
    }}
    .card-table table {{ width: 100%; border-collapse: collapse; font-size: {FONT_TABLE}; }}
    .card-table th, .card-table td {{
        text-align: left;
        padding: {TABLE_CELL_PAD};
        border-bottom: 1px solid {TABLE_BORDER};
        white-space: nowrap;
    }}
    .card-table th {{
        position: sticky;
        top: 0;
        background: {TABLE_HEADER_BG};
        color: {TABLE_HEADER_TEXT};
        font-weight: {WEIGHT_EMPHASIS};
    }}
    .card-table tbody tr:last-child td {{ border-bottom: none; }}
</style>
"""

# AG Grid aligns headers with flexbox and cells with text-align, so centering
# takes both rules.
GRID_CSS = {
    ".ag-header-cell-label": {"justify-content": "center"},
    ".ag-cell": {"text-align": "center"},
    # AG Grid's own selection tint is suppressed. Each grid keeps its own
    # selection, so the table clicked last would stay lit while the other showed
    # a different team. The shared team is named in the panel labels instead
    # ("Players: ...", "Narrative: ..."), which cannot go stale.
    #
    # It is deliberately not painted from Python either: any per-team grid
    # option, pre_selected or context alike, changes the component's arguments,
    # which remounts it and makes the next click report an empty selection.
    # That is what made picks on the first table land one behind.
    ".ag-row-selected::before": {"background-color": "transparent !important"},
}


def _percentile_js():
    """Build the percentile cell styler from PERCENTILE_RAMP.

    Generated rather than hand-written so the heatmap has exactly one source of
    truth; AG Grid takes the styler as a JS function, not as data.
    """
    branches = "\n".join(
        f"    if (val >= {floor}) return {{backgroundColor: '{bg}', color: '{fg}'}};"
        for floor, bg, fg in PERCENTILE_RAMP
    )
    worst_bg, worst_fg = PERCENTILE_WORST
    return f"""
function(params) {{
    if (params.colDef.field === 'Metric') return null;
    if (!params.data || params.data.Metric !== 'Percentile') return null;
    var val = parseFloat(params.value);
    if (isNaN(val)) return null;
{branches}
    return {{backgroundColor: '{worst_bg}', color: '{worst_fg}'}};
}}
"""


PERCENTILE_STYLE = JsCode(_percentile_js())


def inject():
    """Apply PAGE_CSS. Called once, right after st.set_page_config."""
    st.markdown(PAGE_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

def tech_note(text):
    """A technical blurb: what the metric means and how to read it.

    Gray, so the definitions sit back from the observations about the team.
    """
    st.caption(text)


def insight(text):
    """An observation about this particular team, in body white.

    These carry the actual news on the card, so they read at full weight while
    the tech_note definitions stay gray behind them.
    """
    st.markdown(
        f"<p style='font-size:{FONT_BODY}; margin:{MARGIN_BODY};'>{text}</p>",
        unsafe_allow_html=True,
    )


def section_label(text):
    """The name of a panel: Per Game Stats, Narratives, and so on.

    White and larger than st.caption, which greys them down to the same weight
    as the explanatory notes inside the cards. These name what you are looking
    at, so they sit above that.
    """
    st.markdown(
        f"<p style='font-size:{FONT_PANEL_LABEL}; font-weight:{WEIGHT_EMPHASIS}; "
        f"margin:{MARGIN_PANEL_LABEL};'>{text}</p>",
        unsafe_allow_html=True,
    )


def bubbles(items):
    """Render delta-style pills: [(text, good_or_bad), ...].

    st.metric only takes one delta, and it picks the arrow direction from the
    sign of the string, so "Streaky" can't point down without literally showing
    a minus. Rendering the pills directly gives both the second bubble and the
    arrow that actually matches the meaning.
    """
    spans = []
    for text, good in items:
        color = DELTA_GOOD if good else DELTA_BAD
        background = DELTA_GOOD_BG if good else DELTA_BAD_BG
        arrow = "&#8593;" if good else "&#8595;"
        spans.append(
            f"<span style='color:{color}; background-color:{background}; "
            f"font-size:{FONT_PILL}; padding:{PILL_PAD}; border-radius:{PILL_RADIUS}; "
            f"margin-right:{PILL_GAP}; white-space:nowrap; display:inline-block;'>"
            f"{arrow} {text}</span>"
        )
    st.markdown(
        f"<div style='margin:{MARGIN_PILL_ROW};'>{''.join(spans)}</div>",
        unsafe_allow_html=True,
    )
