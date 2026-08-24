"""MainWindow mixin for project selection and sync controls.

Loads projects, refreshes all tabs when the project changes, and runs sync.
"""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import Qt  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QDialog,
    QListWidgetItem,
    QMessageBox,
)
from riskapp_client.ui_v2.components.custom_gui_widgets import NewProjectDialog

_PROJECT_NAME_ROLE = int(Qt.UserRole) + 1


class ProjectsSyncMixin:
    """MainWindow mixin: ProjectsSyncMixin"""

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

    def _refresh_all_views(self, *, select_id: str | None = None) -> None:
        """Refresh all project-scoped tabs from the backend/local store."""
        self._refresh_risks(select_id=select_id)
        for fn in (
            self._refresh_action_risk_combo,
            self._refresh_actions,
            self._refresh_matrix,
            self._refresh_top_history,
            self._refresh_assessments,
            self._refresh_opportunities,
            self._refresh_action_opp_combo,
            self._refresh_members,
            self._update_sync_status,
            self._refresh_helpdesk,
        ):
            fn()

    def _load_projects(self, *, select_project_id: str | None = None) -> None:
        self.project_list.clear()
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
            item.setData(Qt.UserRole, p.id)
            item.setData(_PROJECT_NAME_ROLE, p.name)
            self.project_list.addItem(item)
        if self.project_list.count() <= 0:
            return
        if select_project_id:
            for i in range(self.project_list.count()):
                it = self.project_list.item(i)
                if str(it.data(Qt.UserRole)) == str(select_project_id):
                    self.project_list.setCurrentRow(i)
                    return
        self.project_list.setCurrentRow(0)

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
        self.current_project_id = items[0].data(Qt.UserRole)
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
        dlg = NewProjectDialog(parent=self)
        if dlg.exec() != QDialog.Accepted:
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
                self, "Duplicate name",
                f"A project named \"{name}\" already exists.\n"
                "Please choose a different name.",
            )
            return
        try:
            project = self.backend.create_project(name=name, description=description)
        except (RuntimeError, OSError, ValueError) as exc:
            QMessageBox.critical(self, "Create project", str(exc))
            return
        self._load_projects(select_project_id=project.id)

    def _delete_current_project(self) -> None:
        pid = self.current_project_id
        if not pid:
            QMessageBox.information(self, "Delete project", "No project selected.")
            return
        items = self.project_list.selectedItems()
        name = items[0].text() if items else pid
        reply = QMessageBox.warning(
            self,
            "Delete project",
            f"Permanently delete project \"{name}\" and ALL its data?\n\n"
            "This cannot be undone. Only superadmins can do this.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return
        try:
            self.backend.delete_project(pid)
        except (RuntimeError, OSError) as exc:
            QMessageBox.critical(self, "Delete project", str(exc))
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

    def _update_sync_status(self) -> None:
        pid = self.current_project_id
        if self._is_unsyncable_local_project(pid):
            self.sync_btn.setEnabled(False)
            self.sync_status.setText("Sync: local-only project, cannot be synced")
            return
        pending = 0
        blocked = 0
        can_sync = False
        if hasattr(self.backend, "pending_count"):
            try:
                pending = self.backend.pending_count(pid)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                pending = 0
        if hasattr(self.backend, "blocked_count"):
            try:
                blocked = self.backend.blocked_count(pid)  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                blocked = 0
        if hasattr(self.backend, "can_sync"):
            try:
                can_sync = bool(self.backend.can_sync())  # type: ignore[attr-defined]
            except (AttributeError, RuntimeError):
                can_sync = False
        self.sync_btn.setEnabled(bool(pid) and can_sync)
        mode = "ONLINE" if can_sync else "OFFLINE"
        extra = f" · blocked: {blocked}" if blocked else ""
        self.sync_status.setText(f"{mode} · pending changes: {pending}{extra}")

    def _sync_now(self) -> None:
        pid = self.current_project_id
        if not pid:
            return
        if not hasattr(self.backend, "sync_project"):
            QMessageBox.information(self, "Sync", "This backend does not support sync.")
            return
        summary = self._call_backend("Sync failed", self.backend.sync_project, pid)  # type: ignore[attr-defined]
        if summary is None:
            self._update_sync_status()
            return
        # If the sync promoted a local-only project to a server project,
        # reload project list and keep the user on the migrated project.
        migrated_to = summary.get("project_id_migrated_to")
        if migrated_to:
            self._load_projects(select_project_id=str(migrated_to))
            self.current_project_id = str(migrated_to)
        # refresh UI from local store after sync
        self._refresh_all_views(select_id=self.current_risk_id)
        blocked_details = self._format_blocked_sync_details(summary)
        QMessageBox.information(
            self,
            "Sync complete",
            f"Pushed: {summary.get('pushed')}\n"
            f"Conflicts rebased: {summary.get('conflicts')}\n"
            f"Errors blocked: {summary.get('errors')}\n"
            f"Still blocked: {summary.get('blocked', 0)}\n"
            f"Pulled risks: {summary.get('pulled_risks')}"
            f"{blocked_details}",
        )
