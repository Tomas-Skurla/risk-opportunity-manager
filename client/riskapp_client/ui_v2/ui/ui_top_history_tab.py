################################################################################
## Form generated from reading UI file 'top_history_tab.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################


from PySide6.QtCore import QCoreApplication, QMetaObject, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpacerItem,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class Ui_Form:

    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName("Form")
        Form.resize(660, 489)
        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName("verticalLayout")
        self.splitter = QSplitter(Form)
        self.splitter.setObjectName("splitter")
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self.table_card = QFrame(self.splitter)
        self.table_card.setObjectName("table_card")
        self.table_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.table_card.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_2 = QVBoxLayout(self.table_card)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.top_table = QTableWidget(self.table_card)
        if self.top_table.columnCount() < 6:
            self.top_table.setColumnCount(6)
        __qtablewidgetitem = QTableWidgetItem()
        self.top_table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.top_table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.top_table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.top_table.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.top_table.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.top_table.setHorizontalHeaderItem(5, __qtablewidgetitem5)
        self.top_table.setObjectName("top_table")
        self.top_table.horizontalHeader().setCascadingSectionResizes(True)

        self.verticalLayout_2.addWidget(self.top_table)

        self.splitter.addWidget(self.table_card)
        self.editor_card = QFrame(self.splitter)
        self.editor_card.setObjectName("editor_card")
        self.editor_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.editor_card.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_3 = QVBoxLayout(self.editor_card)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.snapshot_btn = QPushButton(self.editor_card)
        self.snapshot_btn.setObjectName("snapshot_btn")

        self.horizontalLayout.addWidget(self.snapshot_btn)

        self.auto_snapshot_chk = QCheckBox(self.editor_card)
        self.auto_snapshot_chk.setObjectName("auto_snapshot_chk")

        self.horizontalLayout.addWidget(self.auto_snapshot_chk)

        self.label = QLabel(self.editor_card)
        self.label.setObjectName("label")

        self.horizontalLayout.addWidget(self.label)

        self.auto_snapshot_days = QSpinBox(self.editor_card)
        self.auto_snapshot_days.setObjectName("auto_snapshot_days")
        self.auto_snapshot_days.setMinimum(1)
        self.auto_snapshot_days.setMaximum(365)

        self.horizontalLayout.addWidget(self.auto_snapshot_days)

        self.label_2 = QLabel(self.editor_card)
        self.label_2.setObjectName("label_2")

        self.horizontalLayout.addWidget(self.label_2)

        self.label_3 = QLabel(self.editor_card)
        self.label_3.setObjectName("label_3")

        self.horizontalLayout.addWidget(self.label_3)

        self.auto_snapshot_kind = QComboBox(self.editor_card)
        self.auto_snapshot_kind.addItem("")
        self.auto_snapshot_kind.addItem("")
        self.auto_snapshot_kind.addItem("")
        self.auto_snapshot_kind.setObjectName("auto_snapshot_kind")

        self.horizontalLayout.addWidget(self.auto_snapshot_kind)

        self.horizontalSpacer = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.verticalLayout_3.addLayout(self.horizontalLayout)

        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.label_4 = QLabel(self.editor_card)
        self.label_4.setObjectName("label_4")

        self.horizontalLayout_2.addWidget(self.label_4)

        self.top_kind = QComboBox(self.editor_card)
        self.top_kind.addItem("")
        self.top_kind.addItem("")
        self.top_kind.setObjectName("top_kind")

        self.horizontalLayout_2.addWidget(self.top_kind)

        self.label_5 = QLabel(self.editor_card)
        self.label_5.setObjectName("label_5")

        self.horizontalLayout_2.addWidget(self.label_5)

        self.top_limit = QSpinBox(self.editor_card)
        self.top_limit.setObjectName("top_limit")
        self.top_limit.setMinimum(1)
        self.top_limit.setMaximum(100)
        self.top_limit.setValue(10)

        self.horizontalLayout_2.addWidget(self.top_limit)

        self.label_6 = QLabel(self.editor_card)
        self.label_6.setObjectName("label_6")

        self.horizontalLayout_2.addWidget(self.label_6)

        self.top_period = QComboBox(self.editor_card)
        self.top_period.addItem("")
        self.top_period.addItem("")
        self.top_period.addItem("")
        self.top_period.addItem("")
        self.top_period.setObjectName("top_period")

        self.horizontalLayout_2.addWidget(self.top_period)

        self.label_7 = QLabel(self.editor_card)
        self.label_7.setObjectName("label_7")

        self.horizontalLayout_2.addWidget(self.label_7)

        self.top_from = QDateTimeEdit(self.editor_card)
        self.top_from.setObjectName("top_from")
        self.top_from.setCalendarPopup(True)

        self.horizontalLayout_2.addWidget(self.top_from)

        self.label_8 = QLabel(self.editor_card)
        self.label_8.setObjectName("label_8")

        self.horizontalLayout_2.addWidget(self.label_8)

        self.top_to = QDateTimeEdit(self.editor_card)
        self.top_to.setObjectName("top_to")
        self.top_to.setCalendarPopup(True)

        self.horizontalLayout_2.addWidget(self.top_to)

        self.refresh_top_btn = QPushButton(self.editor_card)
        self.refresh_top_btn.setObjectName("refresh_top_btn")

        self.horizontalLayout_2.addWidget(self.refresh_top_btn)

        self.horizontalSpacer_3 = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_2.addItem(self.horizontalSpacer_3)

        self.verticalLayout_3.addLayout(self.horizontalLayout_2)

        self.top_report = QLabel(self.editor_card)
        self.top_report.setObjectName("top_report")

        self.verticalLayout_3.addWidget(self.top_report)

        self.verticalSpacer = QSpacerItem(
            20, 152, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )

        self.verticalLayout_3.addItem(self.verticalSpacer)

        self.splitter.addWidget(self.editor_card)

        self.verticalLayout.addWidget(self.splitter)

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)

    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", "Form", None))
        ___qtablewidgetitem = self.top_table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(
            QCoreApplication.translate("Form", "Captured", None)
        )
        ___qtablewidgetitem1 = self.top_table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("Form", "Rank", None))
        ___qtablewidgetitem2 = self.top_table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("Form", "Title", None))
        ___qtablewidgetitem3 = self.top_table.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("Form", "P", None))
        ___qtablewidgetitem4 = self.top_table.horizontalHeaderItem(4)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("Form", "I", None))
        ___qtablewidgetitem5 = self.top_table.horizontalHeaderItem(5)
        ___qtablewidgetitem5.setText(QCoreApplication.translate("Form", "Score", None))
        self.snapshot_btn.setText(
            QCoreApplication.translate("Form", "Take snapshot now", None)
        )
        self.auto_snapshot_chk.setText(
            QCoreApplication.translate("Form", "Auto snapshot", None)
        )
        self.label.setText(QCoreApplication.translate("Form", "Every", None))
        self.label_2.setText(QCoreApplication.translate("Form", "day(s)", None))
        self.label_3.setText(QCoreApplication.translate("Form", "Kind", None))
        self.auto_snapshot_kind.setItemText(
            0, QCoreApplication.translate("Form", "Risks", None)
        )
        self.auto_snapshot_kind.setItemText(
            1, QCoreApplication.translate("Form", "Opportunities", None)
        )
        self.auto_snapshot_kind.setItemText(
            2, QCoreApplication.translate("Form", "Both", None)
        )

        self.label_4.setText(QCoreApplication.translate("Form", "Kind", None))
        self.top_kind.setItemText(0, QCoreApplication.translate("Form", "Risk", None))
        self.top_kind.setItemText(
            1, QCoreApplication.translate("Form", "Opportunities", None)
        )

        self.label_5.setText(QCoreApplication.translate("Form", "Top N", None))
        self.label_6.setText(QCoreApplication.translate("Form", "Period", None))
        self.top_period.setItemText(0, QCoreApplication.translate("Form", "All", None))
        self.top_period.setItemText(
            1, QCoreApplication.translate("Form", "Last 7 days", None)
        )
        self.top_period.setItemText(
            2, QCoreApplication.translate("Form", "Last 30 days", None)
        )
        self.top_period.setItemText(
            3, QCoreApplication.translate("Form", "Custom", None)
        )

        self.label_7.setText(QCoreApplication.translate("Form", "From", None))
        self.top_from.setDisplayFormat(
            QCoreApplication.translate("Form", "yyyy-MM-dd HH:mm", None)
        )
        self.label_8.setText(QCoreApplication.translate("Form", "To", None))
        self.top_to.setDisplayFormat(
            QCoreApplication.translate("Form", "yyyy-MM-dd HH:mm", None)
        )
        self.refresh_top_btn.setText(
            QCoreApplication.translate("Form", "Refresh history", None)
        )
        self.top_report.setText("")

    # retranslateUi
