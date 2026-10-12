"""Shared UI logic for Risk and Opportunity tabs (export, refresh, CRUD)."""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from typing import Any, cast

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMessageBox,
    QTableWidget,
    QWidget,
)
from riskapp_client.services import entity_filters as filters
from riskapp_client.ui_v2.helpers.scored_entities_ui_helpers import (
    date_bounds,
    form_values_for_entity,
    local_report_lines,
    populate_scored_table,
    score_bounds,
    server_report_lines,
)
from riskapp_client.utils.normalize import norm_optional_text_fields

_OPTIONAL_TEXT_FIELDS = (
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
)
_FORM_FIELDS = (
    "impact_cost",
    "impact_time",
    "impact_scope",
    "impact_quality",
    *_OPTIONAL_TEXT_FIELDS,
)


class ScoredEntityMixin:
    """A unified mixin for Risks and Opportunities"""

    current_project_id: str | None
    _call_backend: Callable[..., Any]
    _can_mark_deleted: Callable[[], bool]
    _mk_item: Callable[..., Any]
    _select_row_by_entity_id: Callable[..., None]
    _update_sync_status: Callable[[], None]

    @staticmethod
    def _update_scored_filter_report(
        label: QLabel,
        full_count: int,
        filtered: Sequence[object],
        *,
        server_report: dict | None = None,
    ) -> None:
        """Show the server's stats when it sent them, else stats for `filtered`."""
        if server_report:
            lines = server_report_lines(server_report, len(filtered), full_count)
        elif filtered:
            lines = local_report_lines(filtered, full_count)
        else:
            lines = [f"Showing 0/{full_count}"]
        label.setText("<br>".join(lines))

    def _export_entity_csv(
        self,
        filename: str,
        cache: dict[str, Any],
        export_fn: Callable[..., Any],
    ) -> None:
        if not self.current_project_id:
            return
        path, _ = QFileDialog.getSaveFileName(
            cast(QWidget, self),
            f"Export {filename}",
            filename,
            "CSV Files (*.csv)",
        )
        if path:
            rows = list(cache.values())
            rows.sort(key=lambda x: (x.score, x.title), reverse=True)
            export_fn(path, rows)

    def _refresh_entity(
        self,
        pid: str,
        tab: Any,
        list_backend_fn: Callable[..., Any],
        report_backend_fn: Callable[..., Any] | None = None,
        select_id: str | None = None,
    ) -> dict[str, Any] | None:
        full = self._call_backend("Backend error", list_backend_fn, pid)
        if full is None:
            return None
        mn, mx = score_bounds(tab.filter_min_score, tab.filter_max_score)
        dt_from, dt_to = date_bounds(tab.filter_from, tab.filter_to)
        search = tab.filter_search.text() or ""
        status = tab.filter_status.currentText() or "(any)"
        category = tab.filter_category.text() or ""
        owner_id, owner_unassigned = self._owner_filter_value(tab.filter_owner)
        filtered = filters.filter_scored(
            full,
            filters.ScoredFilterCriteria(
                search=search,
                min_score=mn,
                max_score=mx,
                status=status,
                category_contains=category,
                owner_user_id=owner_id,
                owner_unassigned=owner_unassigned,
                identified_from=dt_from,
                identified_to=dt_to,
            ),
        )
        server_report = None
        if report_backend_fn is not None:
            try:

                server_report = report_backend_fn(
                    pid,
                    search=search or None,
                    min_score=(mn if mn > 0 else None),
                    max_score=(mx if mx < 25 else None),
                    status=None if status.strip() == "(any)" else status.strip(),
                    category=category or None,
                    owner_user_id=owner_id,
                    owner_unassigned=bool(owner_unassigned),
                    from_date=(dt_from.date().isoformat() if dt_from else None),
                    to_date=(dt_to.date().isoformat() if dt_to else None),
                )
            except AttributeError, RuntimeError:
                server_report = None
        self._update_scored_filter_report(
            tab.filter_report, len(full), filtered, server_report=server_report
        )
        cache = populate_scored_table(tab.table, filtered, mk_item=self._mk_item)
        self._select_row_by_entity_id(select_id, table=tab.table)
        return cache

    @staticmethod
    def _owner_filter_value(owner_widget: Any) -> tuple[str | None, bool]:
        """Return (owner_user_id, owner_unassigned) from the owner filter widget."""
        try:
            data = owner_widget.currentData()  # QComboBox
            if data == "__unassigned__":
                return None, True
            if data:
                return str(data), False
            return None, False
        except AttributeError, RuntimeError:
            logging.getLogger(__name__).debug(
                "Could not read owner filter widget", exc_info=True
            )
            return None, False

    def _on_entity_clicked(
        self,
        row: int,
        col: int,
        table: QTableWidget,
        cache: dict[str, Any],
        current_id: str | None,
        editor_dirty: bool,
        commit_fn: Callable[..., Any],
        form: Any,
        label_widget: QLabel,
        label_prefix: str,
    ) -> str | None:
        t_it = table.item(row, 1)
        if not t_it:
            return None
        clicked_id = str(t_it.data(Qt.ItemDataRole.UserRole))
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
        self,
        current_id: str | None,
        editor_dirty: bool,
        form: Any,
        update_backend_fn: Callable[..., Any],
        refresh_fn: Callable[..., Any] | None,
        select_id: str | None,
        *,
        base_version: int | None = None,
    ) -> bool:
        if not editor_dirty or not current_id:
            return False
        pid = self.current_project_id
        if not pid:
            return False
        payload = form.get_payload()
        if not payload.get("title"):
            return False
        if self._deleted_status_denied(payload.get("status")):
            return False
        if (
            self._call_backend(
                "Backend error",
                update_backend_fn,
                pid,
                current_id,
                base_version=base_version,
                **payload,
            )
            is None
        ):
            return False
        if refresh_fn:
            refresh_fn(select_id=select_id or current_id)
        self._update_sync_status()
        return True

    def _delete_entity(
        self,
        current_id: str | None,
        delete_backend_fn: Callable[..., Any],
        refresh_fn: Callable[[], None],
        start_new_fn: Callable[[], None],
    ) -> None:
        """Safely prompt the user and delete the entity."""
        if not current_id:
            return  # Nothing to delete
        pid = self.current_project_id
        if not pid:
            return
        yes = QMessageBox.StandardButton.Yes
        no = QMessageBox.StandardButton.No
        reply = QMessageBox.question(
            cast(QWidget, self),
            "Confirm Deletion",
            "Are you sure you want to completely delete this item? This cannot be undone.",
            yes | no,
            no,
        )
        if reply == yes:
            self._call_backend("Backend error", delete_backend_fn, pid, current_id)
            start_new_fn()
            refresh_fn()
            self._update_sync_status()

    def _deleted_status_denied(self, status: object) -> bool:
        """Warn and return True when the user may not set status=deleted."""
        if str(status or "").strip().lower() != "deleted" or self._can_mark_deleted():
            return False
        QMessageBox.warning(
            cast(QWidget, self),
            "Not allowed",
            "Only managers (or admins) can mark an item as deleted.",
        )
        return True

    def _save_entity(
        self,
        payload: dict[str, Any],
        current_id: str | None,
        update_backend_fn: Callable[..., Any],
        create_backend_fn: Callable[..., Any],
        refresh_fn: Callable[..., Any] | None,
        form: Any,
        label_widget: QLabel,
        label_prefix: str,
        extra_refreshes: list[Callable[[], None]],
        *,
        base_version: int | None = None,
    ) -> str | None:
        pid = self.current_project_id
        if not pid:
            QMessageBox.warning(
                cast(QWidget, self), "No project", "Select a project first."
            )
            return None
        data = dict(payload or {})
        title = (data.pop("title", "") or "").strip()
        values = {
            "title": title,
            "probability": int(data.pop("probability", 3) or 3),
            "impact": int(data.pop("impact", 3) or 3),
        }
        norm_optional_text_fields(data, _OPTIONAL_TEXT_FIELDS)
        if self._deleted_status_denied(data.get("status")):
            return None

        if current_id:

            updated = self._call_backend(
                "Backend error",
                update_backend_fn,
                pid,
                current_id,
                base_version=base_version,
                **values,
                **data,
            )
            if updated is None:
                return None
        else:
            created = self._call_backend(
                "Backend error", create_backend_fn, pid, **values, **data
            )
            if created is None:
                return None
            current_id = created.id
            # Keep the editor on the newly created entity.
            form.set_values(**values, **{f: data.get(f) for f in _FORM_FIELDS})
        label_widget.setText(f"{label_prefix} (editing: {title})")
        if refresh_fn:
            refresh_fn(select_id=current_id)
        for refresh in extra_refreshes:
            refresh()
        self._update_sync_status()
        return current_id
