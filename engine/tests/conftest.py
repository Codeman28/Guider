import os

import pytest

# Tests never read the real user's app settings or saved API keys.
os.environ["KEM_SETTINGS"] = os.path.join(os.path.dirname(__file__), "_no_settings.json")
os.environ["KEM_SECRETS"] = os.path.join(os.path.dirname(__file__), "_no_secrets.bin")

from kem_engine.models import Rect
from kem_engine.uia.element import Element


def el(eid, name, ct, rect=(0, 0, 10, 10), aid="", patterns=(), root=100, enabled=True, access_key=""):
    l, t, r, b = rect
    return Element(eid=eid, name=name, control_type=ct, automation_id=aid,
                   rect=Rect(left=l, top=t, right=r, bottom=b), root_hwnd=root,
                   patterns=frozenset(patterns), enabled=enabled, access_key=access_key)


@pytest.fixture
def make_el():
    return el


@pytest.fixture
def insert_ribbon():
    """Shapes measured on M365 build 20326 (Phase 0/1 explore dumps), coordinates simplified."""
    return [
        el(1, "Home", "TabItem", (80, 60, 140, 100), "TabHome", ["SelectionItem"]),
        el(2, "Insert", "TabItem", (145, 60, 210, 100), "TabInsert", ["SelectionItem"], access_key="Alt, N"),
        el(3, "Tables", "Group", (10, 105, 330, 220)),
        el(4, "PivotTable", "SplitButton", (15, 110, 80, 200), "InsertPivotTableDropdown", ["ExpandCollapse"]),
        el(5, "PivotTable", "Button", (15, 110, 80, 160), "", ["Invoke"]),
        el(6, "Recommended PivotTables", "Button", (85, 110, 170, 200), "PivotTableSuggestion", ["Invoke"]),
        el(7, "Charts", "Group", (400, 105, 900, 220)),
        el(8, "PivotChart", "SplitButton", (800, 110, 870, 200)),
        el(9, "PivotChart", "Button", (800, 110, 870, 160), "PivotChartInsert", ["Invoke"]),
    ]
