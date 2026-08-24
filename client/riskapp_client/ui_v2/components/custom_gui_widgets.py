
from __future__ import annotations

from PySide6.QtCore import (  # pylint: disable=no-name-in-module
    QDateTime,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QColor, QPen  # pylint: disable=no-name-in-module
from PySide6.QtWidgets import (  # pylint: disable=no-name-in-module
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)  # pylint: disable=no-name-in-module

from riskapp_client.ui_v2.components.ui_dialog import Ui_Dialog
from riskapp_client.ui_v2.components.ui_register_dialog import Ui_RegisterDialog
from riskapp_client.ui_v2.components.ui_risk_form import Ui_Form as Ui_RiskForm


class LoginDialog(QDialog):

    wants_register: bool = False
    wants_local: bool = False

    def __init__(
        self,
        *,
        default_url: str = "http://localhost:8000",
        cached_email: str | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_Dialog()
        self.ui.setupUi(self)
        self.setWindowTitle("Connect to server")
        self.ui.url.setText(default_url)

        if cached_email:
            self.ui.email.setText(cached_email)

        btn_idx = self.ui.verticalLayout.indexOf(self.ui.buttonBox)

        self.register_btn = QPushButton("Register new account…")
        self.register_btn.setToolTip("Create a new account on the server")
        self.ui.verticalLayout.insertWidget(btn_idx, self.register_btn)

        self.local_btn = QPushButton("Work Fully Local (no account, no sync)")
        self.local_btn.setToolTip("Work offline without any account. Data stays local only.")
        self.ui.verticalLayout.insertWidget(btn_idx + 1, self.local_btn)

        self.register_btn.clicked.connect(self._on_register_clicked)
        self.local_btn.clicked.connect(self._on_local_clicked)

        self.ui.buttonBox.accepted.connect(self.accept)
        self.ui.buttonBox.rejected.connect(self.reject)

    def _on_register_clicked(self) -> None:
        self.wants_register = True
        self.done(QDialog.Accepted + 1)

    def _on_local_clicked(self) -> None:
        self.wants_local = True
        self.done(QDialog.Accepted + 2)

    def values(self) -> tuple[str, str, str]:
        return (
            self.ui.url.text().strip(),
            self.ui.email.text().strip(),
            self.ui.password.text(),
        )


class ServerDownDialog(QDialog):
    """Shown when server is unreachable. Offers offline options."""

    FULLY_LOCAL = 1
    OFFLINE_WITH_ACCOUNT = 2

    def __init__(
        self,
        error_message: str,
        *,
        has_credentials: bool = False,
        email: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Server unavailable")
        self.resize(420, 200)
        self.choice = 0

        layout = QVBoxLayout(self)

        msg = QLabel(f"Could not connect to server:\n{error_message}")
        msg.setWordWrap(True)
        layout.addWidget(msg)

        if has_credentials and email:
            sync_btn = QPushButton(f"Work Offline as {email} (will sync later)")
            sync_btn.setToolTip(
                "Work offline with your identity. Data will sync when server is available."
            )
            sync_btn.clicked.connect(self._choose_with_account)
            layout.addWidget(sync_btn)

        local_btn = QPushButton("Work Fully Local (no account, no sync)")
        local_btn.setToolTip("Work offline without any account. Data stays local only.")
        local_btn.clicked.connect(self._choose_fully_local)
        layout.addWidget(local_btn)

        quit_btn = QPushButton("Quit")
        quit_btn.clicked.connect(self.reject)
        layout.addWidget(quit_btn)

    def _choose_fully_local(self) -> None:
        self.choice = self.FULLY_LOCAL
        self.accept()

    def _choose_with_account(self) -> None:
        self.choice = self.OFFLINE_WITH_ACCOUNT
        self.accept()


class RegisterDialog(QDialog):
    """Registration dialog for creating a new account on the server."""

    def __init__(
        self, *, default_url: str = "http://localhost:8000", parent=None
    ) -> None:
        super().__init__(parent)
        self.ui = Ui_RegisterDialog()
        self.ui.setupUi(self)
        self.setWindowTitle("Register new account")
        self.ui.url.setText(default_url)
        # Override accept to run client-side validation first.
        self.ui.buttonBox.accepted.disconnect()
        self.ui.buttonBox.accepted.connect(self._validate_and_accept)
        self.ui.buttonBox.rejected.connect(self.reject)

    # ---- public API --------------------------------------------------------

    def values(self) -> tuple[str, str, str]:
        """Return (server_url, email, password)."""
        return (
            self.ui.url.text().strip(),
            self.ui.email.text().strip(),
            self.ui.password.text(),
        )

    # ---- private -----------------------------------------------------------

    def _validate_and_accept(self) -> None:
        """Run lightweight client-side checks before accepting."""
        email = self.ui.email.text().strip()
        password = self.ui.password.text()
        confirm = self.ui.confirm_password.text()

        if not email:
            QMessageBox.warning(self, "Validation", "Email is required.")
            return
        if "@" not in email:
            QMessageBox.warning(
                self, "Validation", "Please enter a valid email address."
            )
            return
        if not password:
            QMessageBox.warning(self, "Validation", "Password is required.")
            return
        if password != confirm:
            QMessageBox.warning(self, "Validation", "Passwords do not match.")
            return

        # Client-side password-policy check.
        issues = self._check_password_policy(password)
        if issues:
            QMessageBox.warning(
                self, "Password policy", "\n".join(issues)
            )
            return

        self.accept()

    @staticmethod
    def _check_password_policy(password: str) -> list[str]:
        """Mirror the server password policy for faster feedback."""
        issues: list[str] = []
        if len(password) < 12:
            issues.append("Password must be at least 12 characters.")
        if len(password) > 128:
            issues.append("Password must be at most 128 characters.")
        if not any(c.isupper() for c in password):
            issues.append("Password must include an uppercase letter.")
        if not any(c.islower() for c in password):
            issues.append("Password must include a lowercase letter.")
        if not any(c.isdigit() for c in password):
            issues.append("Password must include a digit.")
        if all(c.isalnum() for c in password):
            issues.append("Password must include a symbol.")
        return issues


class NewProjectDialog(QDialog):
    """Dialog for creating a new project."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create new project")
        self.resize(400, 200)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.name_edit = QLineEdit(self)
        self.name_edit.setPlaceholderText("Project name")
        form.addRow("Name:", self.name_edit)

        self.desc_edit = QPlainTextEdit(self)
        self.desc_edit.setPlaceholderText("Optional description")
        self.desc_edit.setMaximumHeight(80)
        form.addRow("Description:", self.desc_edit)

        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Validation", "Project name is required.")
            return
        self.accept()

    def values(self) -> tuple[str, str]:
        """Return (name, description)."""
        return (
            self.name_edit.text().strip(),
            self.desc_edit.toPlainText().strip(),
        )


class ExcelSelectionDelegate(QStyledItemDelegate):
    """Grey selection for whole selected row, and a single 'active cell' border.
    Also renders a 'row number gutter' inside the Title column.
    """

    GUTTER_W = 24
    # Title is column 1 in the scored-entity tables (Code, Title, ...)
    GUTTER_COL = 1

    def sizeHint(self, option, index):
        s = super().sizeHint(option, index)
        if index.column() == self.GUTTER_COL:
            return QSize(s.width() + self.GUTTER_W + 10, s.height())
        return s

    def paint(self, painter, option, index):
        """Paint item."""
        opt = QStyleOptionViewItem(option)
        # --- DYNAMIC THEME COLORS ---
        base_color = opt.palette.base().color()
        text_color = opt.palette.text().color()
        highlight_bg = opt.palette.highlight().color()
        grid_color = QColor(text_color)
        grid_color.setAlpha(50)
        if opt.state & QStyle.State_Selected:
            bg = highlight_bg
        elif opt.state & QStyle.State_MouseOver:
            if base_color.lightness() > 128:
                bg = base_color.darker(105)
            else:
                bg = base_color.lighter(130)
        else:
            bg = base_color
        painter.save()
        painter.fillRect(opt.rect, bg)
        painter.restore()
        if index.column() == self.GUTTER_COL:
            rect = opt.rect
            gutter = QRect(rect.left(), rect.top(), self.GUTTER_W, rect.height())
            # separator line between number and title
            painter.save()
            pen = QPen(grid_color, 1)
            pen.setCosmetic(True)
            pen.setCapStyle(Qt.FlatCap)
            painter.setPen(pen)
            x = rect.left() + self.GUTTER_W
            painter.drawLine(x, rect.top(), x, rect.bottom() - 1)
            painter.restore()
            # number (row index)
            num = str(index.row() + 1)
            painter.save()
            if opt.state & QStyle.State_Selected:
                painter.setPen(opt.palette.highlightedText().color())
            else:
                painter.setPen(text_color)
            painter.drawText(gutter.adjusted(0, 0, -1, 0), Qt.AlignCenter, num)
            painter.restore()
            # title text
            title = index.data() or ""
            pad = 8
            title_rect = rect.adjusted(self.GUTTER_W + pad, 0, -pad, 0)
            painter.save()
            if opt.state & QStyle.State_Selected:
                painter.setPen(opt.palette.highlightedText().color())
            else:
                painter.setPen(text_color)
            fm = opt.fontMetrics
            full_w = fm.horizontalAdvance(title)
            elided = fm.elidedText(title, Qt.ElideRight, max(0, title_rect.width()))
            align = Qt.AlignVCenter | (
                Qt.AlignHCenter if full_w <= title_rect.width() else Qt.AlignLeft
            )
            painter.drawText(title_rect, align, elided)
            painter.restore()
        else:
            # Bypass Qt's stubborn defaults and forcefully draw the text dead-center
            val = index.data()
            text = str(val) if val is not None else ""
            painter.save()
            if opt.state & QStyle.State_Selected:
                painter.setPen(opt.palette.highlightedText().color())
            else:
                painter.setPen(text_color)
            painter.drawText(opt.rect, Qt.AlignCenter, text)
            painter.restore()
        # active cell border
        if opt.state & QStyle.State_HasFocus:
            painter.save()
            pen = QPen(highlight_bg, 2)
            painter.setPen(pen)
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(opt.rect.adjusted(1, 1, -1, -1))
            painter.restore()
        # excel-like internal gridlines
        painter.save()
        pen = QPen(grid_color, 1)
        pen.setCosmetic(True)
        pen.setCapStyle(Qt.FlatCap)
        painter.setPen(pen)
        r = opt.rect
        model = index.model()
        last_col = model.columnCount(index.parent()) - 1
        last_row = model.rowCount(index.parent()) - 1
        if index.column() < last_col:
            x = r.right()
            y2 = r.bottom() if index.row() == last_row else (r.bottom() - 1)
            painter.drawLine(x, r.top(), x, y2)
        if index.row() < last_row:
            y = r.bottom()
            x2 = r.right() if index.column() == last_col else (r.right() - 1)
            painter.drawLine(r.left(), y, x2, y)
        painter.restore()


def setup_readonly_table(table: QTableWidget, *, excel_delegate: bool = False) -> None:
    """Apply standard readonly 'list table' behavior used across tabs.

    Call-sites import this from ``riskapp_client.ui_v2.components.custom_gui_widgets``.
    """
    table.verticalHeader().setVisible(False)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setFocusPolicy(Qt.StrongFocus)
    table.horizontalHeader().setStretchLastSection(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
    if excel_delegate:
        table.setItemDelegate(ExcelSelectionDelegate(table))


class RiskForm(QWidget):

    STATUS_CHOICES = ["concept", "active", "closed", "deleted", "happened"]

    def __init__(self, parent=None, on_submit=None) -> None:
        super().__init__(parent)
        self.on_submit = on_submit
        self._allow_deleted_status: bool = True
        self.ui = Ui_RiskForm()
        self.ui.setupUi(self)
        self.status = self.ui.status
        self.owner_user_id = self.ui.owner_user_id
        self.code = self.ui.code
        self.title = self.ui.title
        self.category = self.ui.category
        self.p = self.ui.p
        self.impact_cost = self.ui.impact_cost
        self.impact_time = self.ui.impact_time
        self.impact_scope = self.ui.impact_scope
        self.impact_quality = self.ui.impact_quality
        self.i = self.ui.i
        self.description = self.ui.description
        self.threat = self.ui.threat
        self.triggers = self.ui.triggers
        self.mitigation_plan = self.ui.mitigation_plan
        # Disable rich text rendering to avoid formatting and dark-mode color issues.
        for w in (self.description, self.threat, self.triggers, self.mitigation_plan):
            w.setAcceptRichText(False)
        self.document_url = self.ui.document_url
        self.identified_at = self.ui.identified_at
        self.response_at = self.ui.response_at
        self.occurred_at = self.ui.occurred_at
        self.status_changed_at = self.ui.status_changed_at
        self.btn = self.ui.btn
        for w in (
            self.impact_cost,
            self.impact_time,
            self.impact_scope,
            self.impact_quality,
        ):
            w.valueChanged.connect(self._recompute_overall_impact)
        self.btn.clicked.connect(self._submit)

        self.code.setToolTip("Code: A unique identifier or short reference")
        self.title.setToolTip("Title: The name or brief summary")
        self.category.setToolTip("Category: The classification or grouping")
        self.status.setToolTip("Status: The current lifecycle state")
        self.owner_user_id.setToolTip("Owner: The team member assigned to manage this")
        self.description.setToolTip("Description: A detailed explanation of this item")
        self.p.setToolTip("Probability: The likelihood of this occurring (1-5)")
        self.impact_cost.setToolTip("Cost Impact: Severity of financial impact (1-5)")
        self.impact_time.setToolTip(
            "Time Impact: Severity of schedule delay or acceleration (1-5)"
        )
        self.impact_scope.setToolTip(
            "Scope Impact: Effect on project deliverables (1-5)"
        )
        self.impact_quality.setToolTip(
            "Quality Impact: Effect on product standards (1-5)"
        )
        self.i.setToolTip(
            "Overall Impact: Automatically calculated as the maximum of Cost, Time, Scope, and Quality"
        )
        self.threat.setToolTip(
            "Threat / Root Cause: What is the driving factor behind this?"
        )
        self.triggers.setToolTip(
            "Triggers: What events or warning signs indicate this is actively happening?"
        )
        self.mitigation_plan.setToolTip(
            "Action Plan: What are the steps to mitigate this risk or exploit this opportunity?"
        )
        self.document_url.setToolTip(
            "A link to external documentation, a Jira ticket, or evidence"
        )
        self.identified_at.setToolTip("Identified At: When this was first discovered")
        self.response_at.setToolTip(
            "Response At: When mitigation or exploitation began"
        )
        self.occurred_at.setToolTip(
            "Occurred At: When the risk/opportunity actually happened"
        )
        self.status_changed_at.setToolTip(
            "Status Changed At: Auto-recorded when the status is updated"
        )
        self.status_changed_at.setEnabled(False)  # Aggressively lock the widget
        self.status.currentTextChanged.connect(self._on_status_changed)

    def track_dirty_state(self, callback) -> None:
        """Connect all input fields to a callback so the app knows when the form has unsaved changes."""
        for w in (self.code, self.title, self.category, self.document_url):
            w.textChanged.connect(lambda *_: callback())
        for w in (self.description, self.threat, self.triggers, self.mitigation_plan):
            w.textChanged.connect(callback)
        for w in (
            self.p,
            self.impact_cost,
            self.impact_time,
            self.impact_scope,
            self.impact_quality,
        ):
            w.valueChanged.connect(lambda *_: callback())
        self.status.currentTextChanged.connect(lambda *_: callback())
        self.owner_user_id.currentTextChanged.connect(lambda *_: callback())
        for w in (self.identified_at, self.response_at, self.occurred_at):
            if hasattr(w, "dateTimeChanged"):
                w.dateTimeChanged.connect(lambda *_: callback())
            elif hasattr(w, "textChanged"):
                w.textChanged.connect(lambda *_: callback())

    def set_allow_deleted_status(self, allowed: bool) -> None:
        """Enable/disable the 'deleted' lifecycle state in the dropdown.

        Server-side authorization is the real gate; this is UX-level protection
        to reduce accidental "soft delete" attempts by non-managers.
        """
        allowed = bool(allowed)
        if getattr(self, "_allow_deleted_status", True) == allowed:
            return
        self._allow_deleted_status = allowed
        current = (self.status.currentText() or "").strip()
        base = ["concept", "active", "closed", "happened"]
        choices = base + (["deleted"] if allowed else [])
        self.status.blockSignals(True)
        self.status.clear()
        self.status.addItems(choices)
        self.status.setEditable(True)
        if current:
            idx = self.status.findText(current)
            if idx >= 0:
                self.status.setCurrentIndex(idx)
            else:
                self.status.setEditText(current)
        self.status.blockSignals(False)

    def _set_date(self, widget, dt_str: str | None) -> None:
        """Helper to safely write to a QDateTimeEdit."""
        if hasattr(widget, "setDateTime"):
            widget.setSpecialValueText("Not set")  # Shows this when empty!
            if dt_str:
                widget.setDateTime(QDateTime.fromString(dt_str[:19], Qt.ISODate))
            else:
                widget.setDateTime(
                    widget.minimumDateTime()
                )  # Forces "Not set" to display
        else:
            widget.setText(dt_str or "")

    def set_editable(self, editable: bool) -> None:
        """Enable/disable editing while keeping fields readable.

        - When editable=False, text fields become read-only and selectors/spinboxes are disabled.
        - Save button is disabled.
        """
        # Save
        self.btn.setEnabled(bool(editable))
        # Line edits
        for w in (
            self.code,
            self.title,
            self.category,
            self.document_url,
            self.identified_at,
            self.response_at,
            self.occurred_at,
            # self.status_changed_at,
        ):
            w.setReadOnly(not editable)
        # Rich text
        for w in (self.description, self.threat, self.triggers, self.mitigation_plan):
            w.setReadOnly(not editable)
        # Combos
        self.status.setEnabled(bool(editable))
        self.owner_user_id.setEnabled(bool(editable))
        # Spinboxes (impact is derived/read-only already)
        self.p.setEnabled(bool(editable))
        for w in (
            self.impact_cost,
            self.impact_time,
            self.impact_scope,
            self.impact_quality,
        ):
            w.setEnabled(bool(editable))
        self.i.setEnabled(False)

    def set_members(self, members) -> None:
        """Populate owner dropdown from project members."""
        current = self._owner_value()
        self.owner_user_id.blockSignals(True)
        self.owner_user_id.clear()
        self.owner_user_id.addItem("(none)", None)
        for m in members or []:
            try:
                uid = getattr(m, "user_id", None) or (
                    m.get("user_id") if isinstance(m, dict) else None
                )
                email = getattr(m, "email", None) or (
                    m.get("email") if isinstance(m, dict) else None
                )
                role = getattr(m, "role", None) or (
                    m.get("role") if isinstance(m, dict) else None
                )
            except (AttributeError, TypeError, KeyError):
                continue
            if not uid:
                continue
            label = f"{email or uid} ({role or 'member'})"
            self.owner_user_id.addItem(label, str(uid))
        self._set_owner_value(current)
        self.owner_user_id.blockSignals(False)

    def _find_owner_index(self, user_id: str) -> int:
        for i in range(self.owner_user_id.count()):
            if str(self.owner_user_id.itemData(i) or "") == str(user_id):
                return i
        return -1

    def _set_owner_value(self, user_id: str | None) -> None:
        if not user_id:
            self.owner_user_id.setCurrentIndex(0)
            self.owner_user_id.setEditText("")
            return
        idx = self._find_owner_index(str(user_id))
        if idx >= 0:
            self.owner_user_id.setCurrentIndex(idx)
        else:
            self.owner_user_id.setEditText(str(user_id))

    def _owner_value(self) -> str | None:
        data = self.owner_user_id.currentData()
        if data:
            return str(data)
        txt = (self.owner_user_id.currentText() or "").strip()
        if not txt or txt == "(none)":
            return None
        return txt

    def _recompute_overall_impact(self) -> None:
        overall = max(
            int(self.impact_cost.value()),
            int(self.impact_time.value()),
            int(self.impact_scope.value()),
            int(self.impact_quality.value()),
        )
        self.i.setValue(overall)

    def _on_status_changed(self, text: str) -> None:
        """Automatically stamp the current date/time when the status dropdown is modified."""
        if hasattr(self.status_changed_at, "setDateTime"):
            self.status_changed_at.setDateTime(QDateTime.currentDateTime())
        else:
            from datetime import datetime

            self.status_changed_at.setText(datetime.now().strftime("%Y-%m-%dT%H:%M:%S"))

    def _read_date(self, widget) -> str | None:
        """Helper to safely read from a QDateTimeEdit to prevent sending 'Not set' to DB."""
        if hasattr(widget, "dateTime"):
            if widget.dateTime() == widget.minimumDateTime():
                return None
            return widget.dateTime().toString(Qt.ISODate)
        return widget.text().strip() or None

    def get_payload(self) -> dict:
        # no validation here (caller decides)
        self._recompute_overall_impact()
        return {
            "code": (self.code.text().strip() or None),
            "title": (self.title.text().strip() or ""),
            "category": (self.category.text().strip() or None),
            "status": (self.status.currentText().strip() or None),
            "owner_user_id": self._owner_value(),
            "probability": int(self.p.value()),
            "impact": int(self.i.value()),
            "impact_cost": int(self.impact_cost.value()),
            "impact_time": int(self.impact_time.value()),
            "impact_scope": int(self.impact_scope.value()),
            "impact_quality": int(self.impact_quality.value()),
            "description": (self.description.toPlainText().strip() or None),
            "threat": (self.threat.toPlainText().strip() or None),
            "triggers": (self.triggers.toPlainText().strip() or None),
            "mitigation_plan": (self.mitigation_plan.toPlainText().strip() or None),
            "document_url": (self.document_url.text().strip() or None),
            "identified_at": self._read_date(self.identified_at),
            "status_changed_at": self._read_date(self.status_changed_at),
            "response_at": self._read_date(self.response_at),
            "occurred_at": self._read_date(self.occurred_at),
        }

    def set_values(
        self,
        *,
        title: str = "",
        probability: int = 3,
        impact: int = 3,
        impact_cost: int | None = None,
        impact_time: int | None = None,
        impact_scope: int | None = None,
        impact_quality: int | None = None,
        code: str | None = None,
        description: str | None = None,
        category: str | None = None,
        threat: str | None = None,
        triggers: str | None = None,
        mitigation_plan: str | None = None,
        document_url: str | None = None,
        owner_user_id: str | None = None,
        status: str | None = "concept",
        identified_at: str | None = None,
        status_changed_at: str | None = None,
        response_at: str | None = None,
        occurred_at: str | None = None,
    ) -> None:
        # Block signals during programmatic set
        """Set values."""
        widgets = [
            self.code,
            self.title,
            self.category,
            self.description,
            self.threat,
            self.triggers,
            self.identified_at,
            self.response_at,
            self.occurred_at,
        ]
        for w in widgets:
            w.blockSignals(True)
        self.owner_user_id.blockSignals(True)
        self.p.blockSignals(True)
        self.i.blockSignals(True)
        self.status.blockSignals(True)
        self.code.setText(code or "")
        self.title.setText(title or "")
        self.category.setText(category or "")
        self._set_owner_value(owner_user_id)
        # status combo
        st = (status or "concept").strip() or "concept"
        idx = self.status.findText(st)
        if idx >= 0:
            self.status.setCurrentIndex(idx)
        else:
            self.status.setEditText(st)
        self.p.setValue(int(probability))
        self.impact_cost.setValue(
            int(impact_cost) if impact_cost is not None else int(impact)
        )
        self.impact_time.setValue(
            int(impact_time) if impact_time is not None else int(impact)
        )
        self.impact_scope.setValue(
            int(impact_scope) if impact_scope is not None else int(impact)
        )
        self.impact_quality.setValue(
            int(impact_quality) if impact_quality is not None else int(impact)
        )
        self._recompute_overall_impact()
        self.description.setPlainText(description or "")
        self.threat.setPlainText(threat or "")
        self.triggers.setPlainText(triggers or "")
        self.mitigation_plan.setPlainText(mitigation_plan or "")
        self.document_url.setText(document_url or "")
        self._set_date(self.identified_at, identified_at)
        self._set_date(self.status_changed_at, status_changed_at)
        self._set_date(self.response_at, response_at)
        self._set_date(self.occurred_at, occurred_at)
        for w in widgets:
            w.blockSignals(False)
        self.owner_user_id.blockSignals(False)
        self.p.blockSignals(False)
        self.i.blockSignals(False)
        self.status.blockSignals(False)

    def _submit(self) -> None:
        payload = self.get_payload()
        title = self.title.text().strip()
        if not title:
            QMessageBox.warning(self, "Validation", "Title is required.")
            return
        self.on_submit(payload)


class CrispHeader(QHeaderView):

    def __init__(self, orientation, parent=None) -> None:
        super().__init__(orientation, parent)

    def paintSection(self, painter, rect, logicalIndex) -> None:
        """Paint Section."""
        super().paintSection(painter, rect, logicalIndex)
        grid_color = QColor(self.palette().text().color())
        grid_color.setAlpha(50)
        pen = QPen(grid_color, 1)
        pen.setCosmetic(True)
        painter.save()
        painter.setPen(pen)
        if logicalIndex < self.count() - 1:
            x = rect.right()
            painter.drawLine(x, rect.top(), x, rect.bottom())
        painter.restore()
