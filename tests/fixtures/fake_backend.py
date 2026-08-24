"""In-memory backend used by tests and demos."""

from __future__ import annotations

import uuid

from riskapp_client.domain.domain_models import (
    Assessment,
    Opportunity,
    Project,
    Risk,
)


class FakeBackend:

    def __init__(self) -> None:
        p1 = Project(id=str(uuid.uuid4()), name="MPR Project", description="Fake data")
        p2 = Project(
            id=str(uuid.uuid4()), name="Demo Project", description="More fake data"
        )
        self.projects: list[Project] = [p1, p2]
        self.risks: dict[str, list[Risk]] = {
            p1.id: [
                Risk(
                    id=str(uuid.uuid4()),
                    project_id=p1.id,
                    title="Critical outage",
                    probability=5,
                    impact=5,
                ),
                Risk(
                    id=str(uuid.uuid4()),
                    project_id=p1.id,
                    title="Supplier delay",
                    probability=4,
                    impact=5,
                ),
                Risk(
                    id=str(uuid.uuid4()),
                    project_id=p1.id,
                    title="Scope creep",
                    probability=3,
                    impact=4,
                ),
            ],
            p2.id: [
                Risk(
                    id=str(uuid.uuid4()),
                    project_id=p2.id,
                    title="Minor bug",
                    probability=2,
                    impact=2,
                ),
            ],
        }
        self.opportunities: dict[str, list[Opportunity]] = {
            p1.id: [
                Opportunity(
                    id=str(uuid.uuid4()),
                    project_id=p1.id,
                    title="Automation savings",
                    probability=3,
                    impact=4,
                ),
                Opportunity(
                    id=str(uuid.uuid4()),
                    project_id=p1.id,
                    title="Early delivery bonus",
                    probability=2,
                    impact=5,
                ),
            ],
            p2.id: [
                Opportunity(
                    id=str(uuid.uuid4()),
                    project_id=p2.id,
                    title="Reuse components",
                    probability=4,
                    impact=3,
                ),
            ],
        }

        # Minimal in-memory assessments store.
        self._assessments: dict[tuple[str, str], list[Assessment]] = {}

    def _sorted_scored(
        self, items: list[Risk] | list[Opportunity]
    ) -> list[Risk] | list[Opportunity]:
        return sorted(items, key=lambda item: (item.score, item.title), reverse=True)

    def _create_scored(
        self,
        project_id: str,
        store: dict[str, list[Risk]] | dict[str, list[Opportunity]],
        model_cls: type[Risk] | type[Opportunity],
        *,
        title: str,
        probability: int,
        impact: int,
    ) -> Risk | Opportunity:
        item = model_cls(
            id=str(uuid.uuid4()),
            project_id=project_id,
            title=title,
            probability=probability,
            impact=impact,
        )
        store.setdefault(project_id, []).append(item)
        return item

    def _update_scored(
        self,
        entity_id: str,
        store: dict[str, list[Risk]] | dict[str, list[Opportunity]],
        model_cls: type[Risk] | type[Opportunity],
        *,
        title: str,
        probability: int,
        impact: int,
        missing_message: str,
    ) -> Risk | Opportunity:
        for items in store.values():
            for index, item in enumerate(items):
                if item.id == entity_id:
                    items[index] = model_cls(
                        id=item.id,
                        project_id=item.project_id,
                        title=title,
                        probability=probability,
                        impact=impact,
                    )
                    return items[index]
        raise KeyError(missing_message)

    def list_projects(self) -> list[Project]:
        return list(self.projects)

    def list_risks(self, project_id: str) -> list[Risk]:
        return list(self._sorted_scored(self.risks.get(project_id, [])))

    def create_risk(
        self, project_id: str, title: str, probability: int, impact: int
    ) -> Risk:
        return self._create_scored(
            project_id,
            self.risks,
            Risk,
            title=title,
            probability=probability,
            impact=impact,
        )

    def update_risk(
        self, risk_id: str, title: str, probability: int, impact: int
    ) -> Risk:
        return self._update_scored(
            risk_id,
            self.risks,
            Risk,
            title=title,
            probability=probability,
            impact=impact,
            missing_message="risk not found",
        )

    def list_opportunities(self, project_id: str) -> list[Opportunity]:
        return list(self._sorted_scored(self.opportunities.get(project_id, [])))

    def create_opportunity(
        self, project_id: str, title: str, probability: int, impact: int
    ) -> Opportunity:
        return self._create_scored(
            project_id,
            self.opportunities,
            Opportunity,
            title=title,
            probability=probability,
            impact=impact,
        )

    def update_opportunity(
        self, opportunity_id: str, title: str, probability: int, impact: int
    ) -> Opportunity:
        return self._update_scored(
            opportunity_id,
            self.opportunities,
            Opportunity,
            title=title,
            probability=probability,
            impact=impact,
            missing_message="opportunity not found",
        )

    def list_assessments(
        self, project_id: str, item_type: str, item_id: str
    ) -> list[Assessment]:
        _ = item_type  # unused; items share UUID space here
        return list(self._assessments.get((project_id, item_id), []))

    def upsert_my_assessment(
        self,
        project_id: str,
        item_type: str,
        item_id: str,
        probability: int,
        impact: int,
        notes: str | None = None,
    ) -> Assessment:
        """Upsert the current user's assessment for a given item."""
        assessor = "demo-user"
        aid = str(uuid.uuid5(uuid.NAMESPACE_URL, f"assessment:{item_id}:{assessor}"))
        a = Assessment(
            id=aid,
            item_id=item_id,
            assessor_user_id=assessor,
            probability=int(probability),
            impact=int(impact),
            notes=(notes or ""),
            version=1,
            is_deleted=False,
            updated_at="",
        )
        self._assessments[(project_id, item_id)] = [a]
        return a
