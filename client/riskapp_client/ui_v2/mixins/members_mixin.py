"""MainWindow mixin for project members/roles management.

Fetches members (online only), updates role state, and controls admin operations.
"""

from __future__ import annotations

import contextlib
import logging

from PySide6.QtCore import Qt  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import QMessageBox  # pylint: disable=no-name-in-module
from riskapp_client.domain.domain_models import Member


class MembersMixin:
    """MainWindow mixin: MembersMixin"""

    def _refresh_members(self) -> None:
        tab = self.members_tab
        pid = self.current_project_id
        tab.members_table.setRowCount(0)
        offline = self._detect_offline_mode() or self._is_local_project()
        if not pid:
            tab.members_hint.setText("Select a project to view members/roles.")
            self._apply_permissions()
            return
        members: list[Member] = []
        if offline:
            tab.members_hint.setText(
                "Offline mode: members/roles can be managed only when connected to the server."
            )
        else:
            tab.members_hint.setText(
                "Project members and roles (admin only for changes)."
            )
            try:
                members = self.backend.list_members(pid)  # type: ignore[attr-defined]
            except (RuntimeError, OSError) as exc:
                QMessageBox.warning(self, "Members", str(exc))
                members = []
        self._cached_members = members
        tab.members_table.setRowCount(len(members))
        for row, m in enumerate(members):
            tab.members_table.setItem(
                row, 0, self._mk_item(m.email, entity_id=str(m.user_id))
            )
            role_display = "superadmin" if m.is_superuser else str(m.role or "")
            tab.members_table.setItem(row, 1, self._mk_item(role_display))
            tab.members_table.setItem(row, 2, self._mk_item(str(m.user_id or "")))
            tab.members_table.setItem(row, 3, self._mk_item(m.created_at or ""))
        for form in (getattr(self, "risk_form", None), getattr(self, "opp_form", None)):
            if hasattr(form, "set_members"):
                with contextlib.suppress(AttributeError, TypeError):
                    form.set_members(members)
        for tab_widget in (
            getattr(self, "risks_tab", None),
            getattr(self, "opps_tab", None),
        ):
            if hasattr(tab_widget, "set_owner_filter_members"):
                with contextlib.suppress(AttributeError, TypeError):
                    tab_widget.set_owner_filter_members(members)
        tab.members_table.resizeColumnsToContents()
        tab.members_table.horizontalHeader().setStretchLastSection(True)
        role = "unknown"
        try:
            uid = self.backend.current_user_id()
        except (AttributeError, RuntimeError):
            uid = None
        if members and uid:
            for m in members:
                if str(m.user_id) == str(uid):
                    role = m.role or "viewer"
                    break
            if role != "unknown":
                self._role_by_project[pid] = role
        else:
            role = self._role_by_project.get(pid, "unknown")
        # Superadmin always gets admin, even if not in the members list.
        if role == "unknown":
            try:
                if self.backend.is_superuser():
                    role = "admin"
            except (AttributeError, RuntimeError):
                logging.getLogger(__name__).debug("Failed to resolve role for member", exc_info=True)
        self._set_role_status(role=role, offline=offline, assumed=False)
        self._apply_permissions()

    def _on_member_selected(self) -> None:
        tab = self.members_tab
        items = tab.members_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        email = tab.members_table.item(row, 0).text()
        role = tab.members_table.item(row, 1).text()
        tab.member_email.setText(email)
        idx = tab.member_role.findText(role)
        if idx >= 0:
            tab.member_role.setCurrentIndex(idx)
        else:
            tab.member_role.setEditText(role)
        # Disable controls if selected member is a superuser and current user is not.
        user_id = tab.members_table.item(row, 0).data(Qt.UserRole)
        selected_is_super = False
        for m in getattr(self, "_cached_members", []):
            if str(m.user_id) == str(user_id) and m.is_superuser:
                selected_is_super = True
                break
        current_is_super = False
        try:
            current_is_super = self.backend.is_superuser()
        except (AttributeError, RuntimeError):
            logging.getLogger(__name__).debug("Failed to check superuser status", exc_info=True)
        protected = selected_is_super and not current_is_super
        tab.member_role.setEnabled(not protected)
        tab.member_add_btn.setEnabled(not protected)
        tab.member_remove_btn.setEnabled(not protected)

    def _add_or_update_member(self) -> None:
        tab = self.members_tab
        pid = self.current_project_id
        if not pid:
            return
        email = (tab.member_email.text() or "").strip()
        role = (tab.member_role.currentText() or "").strip() or "viewer"
        if not email or "@" not in email:
            QMessageBox.warning(self, "Validation", "Please enter a valid email.")
            return
        try:
            self.backend.add_member(pid, user_email=email, role=role)  # type: ignore[attr-defined]
        except (RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Members", str(exc))
            return
        tab.member_email.setText("")
        self._refresh_members()

    def _remove_selected_member(self) -> None:
        tab = self.members_tab
        pid = self.current_project_id
        if not pid:
            return
        items = tab.members_table.selectedItems()
        if not items:
            QMessageBox.information(self, "Members", "Select a member first.")
            return
        row = items[0].row()
        email_item = tab.members_table.item(row, 0)
        user_id = email_item.data(Qt.UserRole)
        email = email_item.text()
        if not user_id:
            QMessageBox.warning(self, "Members", "Missing member user_id.")
            return
        if (
            QMessageBox.question(
                self,
                "Remove member",
                f"Remove {email} from this project?",
                QMessageBox.Yes | QMessageBox.No,
            )
            != QMessageBox.Yes
        ):
            return
        try:
            self.backend.remove_member(pid, member_user_id=str(user_id))  # type: ignore[attr-defined]
        except (RuntimeError, OSError) as exc:
            QMessageBox.warning(self, "Members", str(exc))
            return
        self._refresh_members()
