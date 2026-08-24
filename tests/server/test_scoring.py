from __future__ import annotations


def test_recalculate_item_scores_uses_max_impact_dimension() -> None:
    """recalculate_item_scores picks the max impact dimension and computes prob*impact"""
    from riskapp_server.core.scoring import recalculate_item_scores

    class Obj:
        probability = 3
        impact = 1
        impact_cost = 2
        impact_time = 5
        impact_scope = None
        impact_quality = 4
        score = 0

    o = Obj()
    recalculate_item_scores(o)

    assert o.impact == 5
    assert o.score == 15


def test_recalculate_item_scores_no_dims_keeps_impact() -> None:
    """recalculate_item_scores keeps the existing impact when no dimensions are set"""
    from riskapp_server.core.scoring import recalculate_item_scores

    class Obj:
        probability = 2
        impact = 4
        impact_cost = None
        impact_time = None
        impact_scope = None
        impact_quality = None
        score = 0

    o = Obj()
    recalculate_item_scores(o)

    assert o.impact == 4
    assert o.score == 8
