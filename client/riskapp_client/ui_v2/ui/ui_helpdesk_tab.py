
from PySide6.QtCore import QCoreApplication, QMetaObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class Ui_HelpDeskTab:

    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName("HelpDeskTab")
        Form.resize(700, 500)

        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName("verticalLayout")

        # --- Hint label ---
        self.helpdesk_hint = QLabel(Form)
        self.helpdesk_hint.setObjectName("helpdesk_hint")
        self.verticalLayout.addWidget(self.helpdesk_hint)

        # --- Filter row ---
        self.filter_layout = QHBoxLayout()
        self.filter_layout.setObjectName("filter_layout")

        self.filter_status_label = QLabel(Form)
        self.filter_status_label.setObjectName("filter_status_label")
        self.filter_layout.addWidget(self.filter_status_label)

        self.filter_status = QComboBox(Form)
        self.filter_status.setObjectName("filter_status")
        self.filter_layout.addWidget(self.filter_status)

        self.filter_priority_label = QLabel(Form)
        self.filter_priority_label.setObjectName("filter_priority_label")
        self.filter_layout.addWidget(self.filter_priority_label)

        self.filter_priority = QComboBox(Form)
        self.filter_priority.setObjectName("filter_priority")
        self.filter_layout.addWidget(self.filter_priority)

        self.filter_layout.addStretch()

        self.refresh_btn = QPushButton(Form)
        self.refresh_btn.setObjectName("refresh_btn")
        self.filter_layout.addWidget(self.refresh_btn)

        self.verticalLayout.addLayout(self.filter_layout)

        # --- Tickets table ---
        self.tickets_table = QTableWidget(Form)
        if self.tickets_table.columnCount() < 7:
            self.tickets_table.setColumnCount(7)
        headers = ["Title", "Category", "Priority", "Status", "Reporter", "Created", "ID"]
        for i, h in enumerate(headers):
            item = QTableWidgetItem()
            item.setText(h)
            self.tickets_table.setHorizontalHeaderItem(i, item)
        self.tickets_table.setObjectName("tickets_table")
        self.verticalLayout.addWidget(self.tickets_table)

        # --- Editor group box ---
        self.editor_group = QGroupBox(Form)
        self.editor_group.setObjectName("editor_group")
        self.editor_form = QFormLayout(self.editor_group)
        self.editor_form.setObjectName("editor_form")

        self.ticket_title = QLineEdit(self.editor_group)
        self.ticket_title.setObjectName("ticket_title")
        self.editor_form.addRow("Title:", self.ticket_title)

        self.ticket_category = QComboBox(self.editor_group)
        self.ticket_category.setObjectName("ticket_category")
        self.editor_form.addRow("Category:", self.ticket_category)

        self.ticket_priority = QComboBox(self.editor_group)
        self.ticket_priority.setObjectName("ticket_priority")
        self.editor_form.addRow("Priority:", self.ticket_priority)

        self.ticket_status = QComboBox(self.editor_group)
        self.ticket_status.setObjectName("ticket_status")
        self.editor_form.addRow("Status:", self.ticket_status)

        self.ticket_description = QPlainTextEdit(self.editor_group)
        self.ticket_description.setObjectName("ticket_description")
        self.ticket_description.setMaximumHeight(100)
        self.editor_form.addRow("Description:", self.ticket_description)

        self.verticalLayout.addWidget(self.editor_group)

        # --- Action buttons ---
        self.btn_layout = QHBoxLayout()
        self.btn_layout.setObjectName("btn_layout")

        self.new_btn = QPushButton(Form)
        self.new_btn.setObjectName("new_btn")
        self.btn_layout.addWidget(self.new_btn)

        self.save_btn = QPushButton(Form)
        self.save_btn.setObjectName("save_btn")
        self.btn_layout.addWidget(self.save_btn)

        self.delete_btn = QPushButton(Form)
        self.delete_btn.setObjectName("delete_btn")
        self.btn_layout.addWidget(self.delete_btn)

        self.btn_layout.addStretch()

        self.verticalLayout.addLayout(self.btn_layout)

        self.retranslateUi(Form)
        QMetaObject.connectSlotsByName(Form)

    def retranslateUi(self, Form):
        Form.setWindowTitle(
            QCoreApplication.translate("HelpDeskTab", "Help Desk", None)
        )
        self.helpdesk_hint.setText(
            QCoreApplication.translate(
                "HelpDeskTab",
                "Help Desk: submit and track support tickets for this project.",
                None,
            )
        )
        self.filter_status_label.setText(
            QCoreApplication.translate("HelpDeskTab", "Status:", None)
        )
        self.filter_priority_label.setText(
            QCoreApplication.translate("HelpDeskTab", "Priority:", None)
        )
        self.refresh_btn.setText(
            QCoreApplication.translate("HelpDeskTab", "Refresh", None)
        )
        self.editor_group.setTitle(
            QCoreApplication.translate("HelpDeskTab", "Ticket details", None)
        )
        self.new_btn.setText(
            QCoreApplication.translate("HelpDeskTab", "New ticket", None)
        )
        self.save_btn.setText(
            QCoreApplication.translate("HelpDeskTab", "Save", None)
        )
        self.delete_btn.setText(
            QCoreApplication.translate("HelpDeskTab", "Delete", None)
        )
