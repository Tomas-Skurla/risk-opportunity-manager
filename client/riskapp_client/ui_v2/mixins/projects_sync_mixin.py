"""MainWindow mixin for project selection and sync controls.

Loads projects, refreshes all tabs when the project changes, and runs sync.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import Qt  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QWidget,
)
from riskapp_client.domain.domain_models import Project
from riskapp_client.ui_v2.components.conflict_center_dialog import (
    ConflictCenterDialog,
)
from riskapp_client.ui_v2.components.custom_gui_widgets import NewProjectDialog

if TYPE_CHECKING:
    from riskapp_client.ui_v2.components.custom_gui_widgets import RiskForm

_PROJECT_NAME_ROLE = int(Qt.ItemDataRole.UserRole) + 1


class ProjectsSyncMixin:
    """MainWindow mixin: ProjectsSyncMixin"""

    backend: Any
    conflicts_btn: QPushButton
    current_assessment_item_id: str | None
    current_assessment_item_type: str
    current_opportunity_id: str | None
    current_project_id: str | None
    current_risk_id: str | None
    editor_label: QLabel
    project_list: QListWidget
    risk_form: RiskForm
    risks_table: QTableWidget
    sync_btn: QPushButton
    sync_status: QLabel
    _risks_col_widths: dict[str, list[int]]
    _call_backend: Callable[..., Any]
    _commit_editor_changes: Callable[..., Any]
    _commit_opp_editor_changes: Callable[..., Any]
    _detect_offline_mode: Callable[[], bool]
    _refresh_action_opp_combo: Callable[..., Any]
    _refresh_action_risk_combo: Callable[..., Any]
    _refresh_actions: Callable[..., Any]
    _refresh_assessments: Callable[..., Any]
    _refresh_helpdesk: Callable[..., Any]
    _refresh_matrix: Callable[..., Any]
    _refresh_members: Callable[..., Any]
    _refresh_opportunities: Callable[..., Any]
    _refresh_risks: Callable[..., Any]
    _refresh_top_history: Callable[..., Any]
    _start_background_job: Callable[..., bool]
    _start_new_action: Callable[..., Any]

    def _format_blocked_sync_details(self, summary: dict[str, object]) -> str:
        """Format unresolved blocked sync items for display in the popup."""
        items = summary.get("blocked_details") or []
        if not isinstance(items, list) or not items:
            return ""
        lines = ["", "Blocked items:"]
        for item in items:
            if not isinstance(item, dict):
                continue
            entity = str(item.get("entity") or "item").capitalize()
            title = str(item.get("title") or item.get("entity_id") or "(unknown)")
            op = str(item.get("op") or "unknown")
            reason = str(item.get("reason") or "Blocked by sync error")
            server_version = item.get("server_version")
            line = f"{entity} '{title}' · {op} · {reason}"
            if server_version is not None:
                line += f" (server version: {server_version})"
            lines.append(line)
        return "\n".join(lines)

    def _refresh_all_views(
        self,
        *,
        select_id: str | None = None,
        include_remote: bool = True,
    ) -> None:
        """Refresh all project-scoped tabs from the backend/local store."""
        self._refresh_risks(
            select_id=select_id,
            use_remote_report=include_remote,
        )
        for fn in (
            self._refresh_action_risk_combo,
            self._refresh_actions,
            self._refresh_matrix,
            self._refresh_assessments,
        ):
            fn()
        self._refresh_opportunities(use_remote_report=include_remote)
        self._refresh_action_opp_combo()
        if include_remote:
            self._refresh_top_history()
            self._refresh_members()
        self._update_sync_status()
        self._refresh_helpdesk()

    def _load_projects(
        self,
        *,
        select_project_id: str | None = None,
        projects: Iterable[Project] | None = None,
        notify_selection: bool = True,
    ) -> None:
        self.project_list.clear()
        if projects is None:
            projects = self._call_backend("Backend error", self.backend.list_projects)
        if projects is None:
            return
        # Build a uid→email map for resolving project owners.
        owner_map: dict[str, str] = {}
        try:
            # Ensure user_id is cached in meta (first call populates it).
            self.backend.current_user_id()
            my_email = self.backend.store.get_meta("last_email") or ""
            my_uid = self.backend.store.get_meta("user_id") or ""
            if my_uid and my_email:
                owner_map[my_uid] = my_email
            for m in getattr(self, "_cached_members", []):
                owner_map[str(m.user_id)] = m.email
        except (AttributeError, KeyError, RuntimeError):
            logging.getLogger(__name__).debug("Failed to build owner map for projects", exc_info=True)

        for p in projects:
            display_name = p.name
            if str(p.id).startswith("local-"):
                if p.created_by:
                    display_name = f"{p.name}  (offline, will sync)"
                else:
                    display_name = f"{p.name}  (local only)"
            else:
                # Resolve the owner email for server projects.
                owner_email = owner_map.get(p.created_by, "")
                if not owner_email and "@" in (p.created_by or ""):
                    owner_email = p.created_by
                if owner_email:
                    display_name = f"{p.name}  ({owner_email})"
            item = QListWidgetItem(display_name)
            item.setData(Qt.ItemDataRole.UserRole, p.id)
            item.setData(_PROJECT_NAME_ROLE, p.name)
            self.project_list.addItem(item)
        if self.project_list.count() <= 0:
            return

        def select_row(row: int) -> None:
            if notify_selection:
                self.project_list.setCurrentRow(row)
                return
            previously_blocked = self.project_list.blockSignals(True)
            try:
                self.project_list.setCurrentRow(row)
            finally:
                self.project_list.blockSignals(previously_blocked)

        if select_project_id:
            for i in range(self.project_list.count()):
                it = self.project_list.item(i)
                if str(it.data(Qt.ItemDataRole.UserRole)) == str(select_project_id):
                    select_row(i)
                    return
        select_row(0)

    def _on_project_selected(self) -> None:
        with contextlib.suppress(AttributeError, RuntimeError):
            self._commit_editor_changes(refresh=False)
        with contextlib.suppress(AttributeError, RuntimeError):
            self._commit_opp_editor_changes(refresh=False)
        items = self.project_list.selectedItems()
        if not items:
            return
        if self.current_project_id:
            self._risks_col_widths[self.current_project_id] = [
                self.risks_table.columnWidth(c)
                for c in range(self.risks_table.columnCount())
            ]
        self.current_project_id = items[0].data(Qt.ItemDataRole.UserRole)
        self.current_risk_id = None
        self.current_opportunity_id = None
        self.current_assessment_item_id = None
        self.current_assessment_item_type = "risk"
        self.editor_label.setText("Editor (new risk)")
        self.risk_form.set_values(title="", probability=3, impact=3)
        # Show sync status for local projects when online.
        if str(self.current_project_id).startswith("local-") and not self._detect_offline_mode():
            # Distinguish anonymous local projects from syncable ones.
            if self._is_unsyncable_local_project(self.current_project_id):
                self.sync_status.setText("Sync: local-only project, cannot be synced")
                self.sync_btn.setEnabled(False)
            else:
                self.sync_status.setText("Sync: offline project, click Sync Now to upload")
        self._refresh_all_views()
        self._start_new_action()

    def _create_new_project(self) -> None:
        parent = cast(QWidget, self)
        dlg = NewProjectDialog(parent=parent)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        name, description = dlg.values()
        # Avoid duplicate names in the sidebar.
        existing_names = set()
        for i in range(self.project_list.count()):
            it = self.project_list.item(i)
            # Display labels include ownership/sync annotations; compare the
            # undecorated name stored alongside the project ID.
            raw = it.data(_PROJECT_NAME_ROLE)
            existing_names.add(
                str(raw if raw is not None else it.text() or "").strip().lower()
            )
        if name.strip().lower() in existing_names:
            QMessageBox.warning(
                parent,
                "Duplicate name",
                f"A project named \"{name}\" already exists.\n"
                "Please choose a different name.",
            )
            return
        try:
            project = self.backend.create_project(name=name, description=description)
        except (RuntimeError, OSError, ValueError) as exc:
            QMessageBox.critical(parent, "Create project", str(exc))
            return
        self._load_projects(select_project_id=project.id)

    def _delete_current_project(self) -> None:
        parent = cast(QWidget, self)
        pid = self.current_project_id
        if not pid:
            QMessageBox.information(
                parent,
                "Delete project",
                "No project selected.",
            )
            return
        items = self.project_list.selectedItems()
        name = items[0].text() if items else pid
        yes = QMessageBox.StandardButton.Yes
        no = QMessageBox.StandardButton.No
        reply = QMessageBox.warning(
            parent,
            "Delete project",
            f"Permanently delete project \"{name}\" and ALL its data?\n\n"
            "This cannot be undone. Only superadmins can do this.",
            yes | no,
            no,
        )
        if reply != yes:
            return
        try:
            self.backend.delete_project(pid)
        except (RuntimeError, OSError) as exc:
            QMessageBox.critical(parent, "Delete project", str(exc))
            return
        self.current_project_id = None
        self._load_projects()

    def _is_unsyncable_local_project(self, project_id: object) -> bool:
        if not str(project_id or "").startswith("local-"):
            return False
        try:
            project = self.backend.store.get_project(str(project_id))
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug(
                "Failed to inspect local project sync state", exc_info=True
            )
            return False
        return bool(project is not None and not project.created_by)

    @staticmethod
    def _format_last_sync_time(value: object) -> str:
        raw = str(value or "").strip()
        if not raw or raw.startswith("1970-01-01"):
            return "never"
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return "unknown"
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        else:
            parsed = parsed.astimezone(UTC)
        return parsed.strftime("%Y-%m-%d %H:%M UTC")

    def _update_sync_status(self) -> None:
        pid = self.current_project_id
        if self._is_unsyncable_local_project(pid):
            self.sync_btn.setEnabled(False)
            self.sync_status.setText("Sync: local-only project, cannot be synced")
            if hasattr(self, "conflicts_btn"):
                self.conflicts_btn.setText("Conflicts (0)")
                self.conflicts_btn.setEnabled(False)
            return
        pending = 0
        deferred = 0
        conflicts = 0
        errors = 0
        last_sync: object = None
        can_sync = False
        if hasattr(self.backend, "pending_count"):
            try:
                pending = self.backend.pending_count(pid)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                pending = 0
        if hasattr(self.backend, "conflict_count"):
            try:
                conflicts = self.backend.conflict_count(pid)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                conflicts = 0
        if hasattr(self.backend, "deferred_count"):
            try:
                deferred = self.backend.deferred_count(pid)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                deferred = 0
        if hasattr(self.backend, "error_count"):
            try:
                errors = self.backend.error_count(pid)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                errors = 0
        if hasattr(self.backend, "last_sync_time"):
            try:
                last_sync = self.backend.last_sync_time(pid)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                last_sync = None
        if hasattr(self.backend, "can_sync"):
            try:
                can_sync = bool(self.backend.can_sync())  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                can_sync = False
        self.sync_btn.setEnabled(bool(pid) and can_sync)
        mode = "ONLINE" if can_sync else "OFFLINE"
        formatted_last_sync = self._format_last_sync_time(last_sync)
        self.sync_status.setText(
            f"{mode} · queued: {pending} · retrying: {deferred} "
            f"· conflicts: {conflicts} "
            f"· errors: {errors} · last sync: {formatted_last_sync}"
        )
        if hasattr(self, "conflicts_btn"):
            self.conflicts_btn.setText(f"Conflicts ({conflicts})")
            self.conflicts_btn.setEnabled(bool(pid) and conflicts > 0)

    def _open_conflict_center(self) -> None:
        parent = cast(QWidget, self)
        pid = self.current_project_id
        if not pid:
            QMessageBox.information(
                parent,
                "Synchronization conflicts",
                "No project selected.",
            )
            return
        if not hasattr(self.backend, "conflict_details") or not hasattr(
            self.backend, "resolve_conflict"
        ):
            QMessageBox.information(
                parent,
                "Synchronization conflicts",
                "This backend does not support interactive conflict resolution.",
            )
            return
        conflicts = self._call_backend(
            "Could not load conflicts",
            self.backend.conflict_details,  # type: ignore[attr-defined]
            pid,
        )
        if conflicts is None:
            self._update_sync_status()
            return
        if not isinstance(conflicts, list) or not conflicts:
            QMessageBox.information(
                parent,
                "Synchronization conflicts",
                "There are no unresolved conflicts for this project.",
            )
            self._update_sync_status()
            return

        dialog = ConflictCenterDialog(
            conflicts,
            self.backend.resolve_conflict,  # type: ignore[attr-defined]
            parent=parent,
        )
        dialog.conflict_resolved.connect(
            lambda _change_id, _resolution: self._update_sync_status()
        )
        dialog.exec()
        self._refresh_all_views(select_id=self.current_risk_id)

    def _sync_now(self) -> None:
        parent = cast(QWidget, self)
        pid = self.current_project_id
        if not pid:
            return
        if not hasattr(self.backend, "sync_project"):
            QMessageBox.information(
                parent,
                "Sync",
                "This backend does not support sync.",
            )
            return
        if not self._start_background_job(
            "sync",
            {"project_id": str(pid)},
            on_success=self._sync_succeeded,
            on_failure=self._sync_failed,
            on_cancelled=self._sync_cancelled,
        ):
            QMessageBox.information(
                parent,
                "Synchronization",
                "Another background operation is already running.",
            )

    def _sync_succeeded(self, result: object) -> None:
        if not isinstance(result, dict):
            self._sync_failed("Synchronization returned an invalid result")
            return
        summary = dict(result)
        # If the sync promoted a local-only project to a server project,
        # reload project list and keep the user on the migrated project.
        migrated_to = summary.get("project_id_migrated_to")
        if migrated_to:
            visible_projects = summary.pop("_visible_projects", None)
            if isinstance(visible_projects, list):
                self._load_projects(
                    select_project_id=str(migrated_to),
                    projects=visible_projects,
                    notify_selection=False,
                )
            else:
                selected = self.project_list.selectedItems()
                if selected:
                    selected[0].setData(
                        Qt.ItemDataRole.UserRole,
                        str(migrated_to),
                    )
                    raw_name = selected[0].data(_PROJECT_NAME_ROLE)
                    if raw_name:
                        selected[0].setText(str(raw_name))
            self.current_project_id = str(migrated_to)
        # Refresh from the local SQLite connection only. Pull already populated
        # it; issuing reports/history/member requests here would put blocking
        # network calls straight back onto the GUI thread.
        self._refresh_all_views(
            select_id=self.current_risk_id,
            include_remote=False,
        )
        blocked_details = self._format_blocked_sync_details(summary)
        state = str(summary.get("state") or "complete")
        sync_error = summary.get("sync_error")
        error_detail = ""
        if isinstance(sync_error, dict):
            error_detail = f"\n\n{sync_error.get('detail') or sync_error.get('reason')}"
        message = (
            f"Pushed: {summary.get('pushed')}\n"
            f"Conflicts blocked: {summary.get('conflicts')}\n"
            f"Errors blocked: {summary.get('errors')}\n"
            f"Retries scheduled: {summary.get('deferred', 0)}\n"
            f"Still blocked: {summary.get('blocked', 0)}\n"
            f"Pulled risks: {summary.get('pulled_risks')}"
            f"{blocked_details}{error_detail}"
        )
        if state == "complete":
            QMessageBox.information(
                cast(QWidget, self),
                "Sync complete",
                message,
            )
            return
        QMessageBox.warning(
            cast(QWidget, self),
            "Sync needs attention" if state != "retry_wait" else "Sync retry scheduled",
            message,
        )

    def _sync_failed(self, message: str) -> None:
        QMessageBox.critical(cast(QWidget, self), "Sync failed", message)
        self._update_sync_status()

    def _sync_cancelled(self) -> None:
        QMessageBox.information(
            cast(QWidget, self),
            "Synchronization cancelled",
            "Synchronization stopped safely. Changes already acknowledged by "
            "the server remain acknowledged; remaining work will be retried.",
        )
        self._update_sync_status()
