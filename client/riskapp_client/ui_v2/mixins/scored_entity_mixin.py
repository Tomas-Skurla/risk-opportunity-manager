"""Shared UI logic for Risk and Opportunity tabs (export, refresh, CRUD)."""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QMessageBox
from riskapp_client.ui_v2.mixins.scored_entities_ui_helpers import (
    date_bounds,
    form_values_for_entity,
    populate_scored_table,
    score_bounds,
)
from riskapp_client.utils.normalize import norm_optional_text_fields


class ScoredEntityMixin:
    """A unified mixin for Risks and Opportunities"""

    def _export_entity_csv(self, filename: str, cache: dict, export_fn) -> None:
        if not self.current_project_id:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, f"Export {filename}", filename, "CSV Files (*.csv)"
        )
        if path:
            rows = list(cache.values())
            rows.sort(key=lambda x: (x.score, x.title), reverse=True)
            export_fn(path, rows)

    def _refresh_entity(
        self,
        pid: str,
        list_backend_fn,
        filter_fn,
        criteria_cls,
        report_widget,
        table_widget,
        filters_dict,
        mk_item_fn,
        report_backend_fn=None,
        select_id: str | None = None,
    ) -> dict | None:
        full = self._call_backend("Backend error", list_backend_fn, pid)
        if full is None:
            return None
        mn, mx = score_bounds(filters_dict["min_score"], filters_dict["max_score"])
        dt_from, dt_to = date_bounds(filters_dict["from_date"], filters_dict["to_date"])
        criteria = criteria_cls(
            search=(filters_dict["search"].text() or ""),
            min_score=mn,
            max_score=mx,
            status=(filters_dict["status"].currentText() or "(any)"),
            category_contains=(filters_dict["category"].text() or ""),
            owner_user_id=self._owner_filter_value(filters_dict["owner"])[0],
            owner_unassigned=self._owner_filter_value(filters_dict["owner"])[1],
            identified_from=dt_from,
            identified_to=dt_to,
        )
        filtered = filter_fn(full, criteria)
        server_report = None
        if report_backend_fn is not None:
            try:
                status = (filters_dict["status"].currentText() or "(any)").strip()
                status_q = None if status == "(any)" else status
                owner_id, owner_unassigned = self._owner_filter_value(
                    filters_dict["owner"]
                )
                server_report = report_backend_fn(
                    pid,
                    search=(filters_dict["search"].text() or "") or None,
                    min_score=(mn if mn > 0 else None),
                    max_score=(mx if mx < 25 else None),
                    status=status_q,
                    category=(filters_dict["category"].text() or "") or None,
                    owner_user_id=owner_id,
                    owner_unassigned=bool(owner_unassigned),
                    from_date=(dt_from.date().isoformat() if dt_from else None),
                    to_date=(dt_to.date().isoformat() if dt_to else None),
                )
            except (AttributeError, RuntimeError):
                server_report = None
        self._update_scored_filter_report(
            report_widget, len(full), list(filtered), server_report=server_report
        )
        cache = populate_scored_table(table_widget, list(filtered), mk_item=mk_item_fn)
        self._select_row_by_entity_id(select_id, table=table_widget)
        return cache

    @staticmethod
    def _owner_filter_value(owner_widget):
        """Return (owner_user_id, owner_unassigned) from the owner filter widget."""
        try:
            data = owner_widget.currentData()  # QComboBox
            if data == "__unassigned__":
                return None, True
            if data:
                return str(data), False
            return None, False
        except (AttributeError, RuntimeError):
            # Back-compat if widget is a QLineEdit.
            try:
                text = (owner_widget.text() or "").strip()
                return (text or None), False
            except (AttributeError, RuntimeError):
                logging.getLogger(__name__).debug("Could not read owner filter widget", exc_info=True)
                return None, False

    def _on_entity_clicked(
        self,
        row: int,
        col: int,
        table,
        cache,
        current_id,
        editor_dirty,
        commit_fn,
        form,
        label_widget,
        label_prefix,
    ) -> str | None:
        t_it = table.item(row, 1)
        if not t_it:
            return None
        clicked_id = str(t_it.data(Qt.UserRole))
        if not clicked_id:
            return None
        if editor_dirty and current_id and current_id != clicked_id:
            commit_fn(refresh=True, select_id=clicked_id)
            row = table.currentRow()
            col = max(0, table.currentColumn())
        table.setCurrentCell(row, col)
        if not self.current_project_id:
            return None
        ent = cache.get(clicked_id)
        if not ent:
            return None
        form.set_values(**form_values_for_entity(ent))
        label_widget.setText(f"{label_prefix} (editing: {ent.title})")
        return ent.id

    def _commit_entity_editor_changes(
        self, current_id, editor_dirty, form, update_backend_fn, refresh_fn, select_id
    ) -> bool:
        if not editor_dirty or not current_id:
            return False
        pid = self.current_project_id
        if not pid:
            return False
        payload = form.get_payload()
        if not payload.get("title"):
            return False
        st = str(payload.get("status") or "").strip().lower()
        if st == "deleted" and hasattr(self, "_can_mark_deleted"):
            try:
                if not self._can_mark_deleted():  # type: ignore[attr-defined]
                    QMessageBox.warning(
                        self,
                        "Not allowed",
                        "Only managers (or admins) can mark an item as deleted.",
                    )
                    return False
            except (AttributeError, RuntimeError, ValueError):
                logging.getLogger(__name__).debug("Editor commit failed", exc_info=True)
                return False
        if (
            self._call_backend(
                "Backend error", update_backend_fn, pid, current_id, **payload
            )
            is None
        ):
            return False
        if refresh_fn:
            refresh_fn(select_id=select_id or current_id)
        return True

    def _delete_entity(
        self, current_id: str | None, delete_backend_fn, refresh_fn, start_new_fn
    ) -> None:
        """Safely prompt the user and delete the entity."""
        if not current_id:
            return  # Nothing to delete
        pid = self.current_project_id
        if not pid:
            return
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to completely delete this item? This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._call_backend("Backend error", delete_backend_fn, pid, current_id)
            start_new_fn()
            refresh_fn()

    def _save_entity(
        self,
        payload,
        current_id,
        update_backend_fn,
        create_backend_fn,
        refresh_fn,
        form,
        label_widget,
        label_prefix,
        extra_refreshes,
    ) -> str | None:
        pid = self.current_project_id
        if not pid:
            QMessageBox.warning(self, "No project", "Select a project first.")
            return None
        data = dict(payload or {})
        title = (data.pop("title", "") or "").strip()
        p = int(data.pop("probability", 3) or 3)
        i = int(data.pop("impact", 3) or 3)
        norm_optional_text_fields(
            data,
            [
                "code",
                "description",
                "category",
                "threat",
                "triggers",
                "mitigation_plan",
                "document_url",
                "owner_user_id",
                "status",
                "identified_at",
                "status_changed_at",
                "response_at",
                "occurred_at",
            ],
        )
        st = str(data.get("status") or "").strip().lower()
        if st == "deleted" and hasattr(self, "_can_mark_deleted"):
            try:
                if not self._can_mark_deleted():  # type: ignore[attr-defined]
                    QMessageBox.warning(
                        self,
                        "Not allowed",
                        "Only managers (or admins) can mark an item as deleted.",
                    )
                    return None
            except (AttributeError, RuntimeError):
                logging.getLogger(__name__).debug("Deletion permission check failed", exc_info=True)
                return None
        if current_id:
            if (
                self._call_backend(
                    "Backend error",
                    update_backend_fn,
                    pid,
                    current_id,
                    title=title,
                    probability=p,
                    impact=i,
                    **data,
                )
                is None
            ):
                return None
            label_widget.setText(f"{label_prefix} (editing: {title})")
        else:
            ent = self._call_backend(
                "Backend error",
                create_backend_fn,
                pid,
                title=title,
                probability=p,
                impact=i,
                **data,
            )
            if ent is None:
                return None
            current_id = ent.id
            # Keep the editor on the newly created entity.
            form.set_values(
                title=title,
                probability=p,
                impact=i,
                impact_cost=data.get("impact_cost"),
                impact_time=data.get("impact_time"),
                impact_scope=data.get("impact_scope"),
                impact_quality=data.get("impact_quality"),
                code=data.get("code"),
                description=data.get("description"),
                category=data.get("category"),
                threat=data.get("threat"),
                triggers=data.get("triggers"),
                mitigation_plan=data.get("mitigation_plan"),
                document_url=data.get("document_url"),
                owner_user_id=data.get("owner_user_id"),
                status=data.get("status"),
                identified_at=data.get("identified_at"),
                status_changed_at=data.get("status_changed_at"),
                response_at=data.get("response_at"),
                occurred_at=data.get("occurred_at"),
            )
            label_widget.setText(f"{label_prefix} (editing: {title})")
        if refresh_fn:
            refresh_fn(select_id=current_id)
        for ref in extra_refreshes:
            ref()
        return current_id
