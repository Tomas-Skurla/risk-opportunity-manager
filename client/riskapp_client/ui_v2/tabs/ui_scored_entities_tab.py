################################################################################
## Form generated from reading UI file 'scored_entities_tab.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################


from PySide6.QtCore import QCoreApplication, QMetaObject, QRect, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpacerItem,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from riskapp_client.ui_v2.components.custom_gui_widgets import RiskForm


class Ui_Form:

    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName("Form")
        Form.resize(670, 421)
        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName("verticalLayout")
        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.Search = QLabel(Form)
        self.Search.setObjectName("Search")

        self.horizontalLayout.addWidget(self.Search)

        self.filter_search = QLineEdit(Form)
        self.filter_search.setObjectName("filter_search")

        self.horizontalLayout.addWidget(self.filter_search)

        self.label = QLabel(Form)
        self.label.setObjectName("label")

        self.horizontalLayout.addWidget(self.label)

        self.filter_min_score = QSpinBox(Form)
        self.filter_min_score.setObjectName("filter_min_score")

        self.horizontalLayout.addWidget(self.filter_min_score)

        self.label_2 = QLabel(Form)
        self.label_2.setObjectName("label_2")

        self.horizontalLayout.addWidget(self.label_2)

        self.filter_max_score = QSpinBox(Form)
        self.filter_max_score.setObjectName("filter_max_score")

        self.horizontalLayout.addWidget(self.filter_max_score)

        self.label_3 = QLabel(Form)
        self.label_3.setObjectName("label_3")

        self.horizontalLayout.addWidget(self.label_3)

        self.filter_status = QComboBox(Form)
        self.filter_status.setObjectName("filter_status")

        self.horizontalLayout.addWidget(self.filter_status)

        self.filter_category = QLineEdit(Form)
        self.filter_category.setObjectName("filter_category")

        self.horizontalLayout.addWidget(self.filter_category)

        self.filter_owner = QComboBox(Form)
        self.filter_owner.setObjectName("filter_owner")

        self.horizontalLayout.addWidget(self.filter_owner)

        self.filter_from = QLineEdit(Form)
        self.filter_from.setObjectName("filter_from")

        self.horizontalLayout.addWidget(self.filter_from)

        self.filter_to = QLineEdit(Form)
        self.filter_to.setObjectName("filter_to")

        self.horizontalLayout.addWidget(self.filter_to)

        self.export_btn = QPushButton(Form)
        self.export_btn.setObjectName("export_btn")

        self.horizontalLayout.addWidget(self.export_btn)

        self.clear_btn = QPushButton(Form)
        self.clear_btn.setObjectName("clear_btn")

        self.horizontalLayout.addWidget(self.clear_btn)

        self.horizontalSpacer = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.filter_report = QLabel(Form)
        self.filter_report.setObjectName("filter_report")

        self.horizontalLayout.addWidget(self.filter_report)

        self.verticalLayout.addLayout(self.horizontalLayout)

        self.splitter = QSplitter(Form)
        self.splitter.setObjectName("splitter")
        self.splitter.setOrientation(Qt.Orientation.Horizontal)
        self.editor_card = QFrame(self.splitter)
        self.editor_card.setObjectName("editor_card")
        sizePolicy = QSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.editor_card.sizePolicy().hasHeightForWidth())
        self.editor_card.setSizePolicy(sizePolicy)
        self.editor_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.editor_card.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_3 = QVBoxLayout(self.editor_card)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.horizontalLayout_2 = QHBoxLayout()
        self.horizontalLayout_2.setObjectName("horizontalLayout_2")
        self.editor_label = QLabel(self.editor_card)
        self.editor_label.setObjectName("editor_label")

        self.horizontalLayout_2.addWidget(self.editor_label)

        self.horizontalSpacer_2 = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout_2.addItem(self.horizontalSpacer_2)

        self.new_btn = QPushButton(self.editor_card)
        self.new_btn.setObjectName("new_btn")

        self.horizontalLayout_2.addWidget(self.new_btn)

        self.delete_btn = QPushButton(self.editor_card)
        self.delete_btn.setObjectName("delete_btn")
        self.delete_btn.setStyleSheet("color: red;")

        self.horizontalLayout_2.addWidget(self.delete_btn)

        self.verticalLayout_3.addLayout(self.horizontalLayout_2)

        self.scrollArea = QScrollArea(self.editor_card)
        self.scrollArea.setObjectName("scrollArea")
        self.scrollArea.setWidgetResizable(True)
        self.form = RiskForm()
        self.form.setObjectName("form")
        self.form.setGeometry(QRect(0, 0, 266, 341))
        self.scrollArea.setWidget(self.form)

        self.verticalLayout_3.addWidget(self.scrollArea)

        self.splitter.addWidget(self.editor_card)
        self.table_card = QFrame(self.splitter)
        self.table_card.setObjectName("table_card")
        sizePolicy1 = QSizePolicy(
            QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred
        )
        sizePolicy1.setHorizontalStretch(2)
        sizePolicy1.setVerticalStretch(0)
        sizePolicy1.setHeightForWidth(self.table_card.sizePolicy().hasHeightForWidth())
        self.table_card.setSizePolicy(sizePolicy1)
        self.table_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.table_card.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_2 = QVBoxLayout(self.table_card)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.table = QTableWidget(self.table_card)
        if self.table.columnCount() < 8:
            self.table.setColumnCount(8)
        __qtablewidgetitem = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(5, __qtablewidgetitem5)
        __qtablewidgetitem6 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(6, __qtablewidgetitem6)
        __qtablewidgetitem7 = QTableWidgetItem()
        self.table.setHorizontalHeaderItem(7, __qtablewidgetitem7)
        self.table.setObjectName("table")
        sizePolicy2 = QSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        sizePolicy2.setHorizontalStretch(0)
        sizePolicy2.setVerticalStretch(0)
        sizePolicy2.setHeightForWidth(self.table.sizePolicy().hasHeightForWidth())
        self.table.setSizePolicy(sizePolicy2)
        self.table.horizontalHeader().setCascadingSectionResizes(True)

        self.verticalLayout_2.addWidget(self.table)

        self.splitter.addWidget(self.table_card)

        self.verticalLayout.addWidget(self.splitter)

        self.verticalLayout.setStretch(1, 1)

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)

    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", "Form", None))
        self.Search.setText(QCoreApplication.translate("Form", "Search", None))
        self.label.setText(QCoreApplication.translate("Form", "Min", None))
        self.label_2.setText(QCoreApplication.translate("Form", "Max", None))
        self.label_3.setText(QCoreApplication.translate("Form", "Status", None))
        self.export_btn.setText(QCoreApplication.translate("Form", "Export CSV", None))
        self.clear_btn.setText(QCoreApplication.translate("Form", "Clear", None))
        self.filter_report.setText("")
        self.editor_label.setText(QCoreApplication.translate("Form", "Editor", None))
        self.new_btn.setText(QCoreApplication.translate("Form", "New", None))
        self.delete_btn.setText(QCoreApplication.translate("Form", "Delete", None))
        ___qtablewidgetitem = self.table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("Form", "Code", None))
        ___qtablewidgetitem1 = self.table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("Form", "Title", None))
        ___qtablewidgetitem2 = self.table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(
            QCoreApplication.translate("Form", "Category", None)
        )
        ___qtablewidgetitem3 = self.table.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("Form", "Status", None))
        ___qtablewidgetitem4 = self.table.horizontalHeaderItem(4)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("Form", "Owner", None))
        ___qtablewidgetitem5 = self.table.horizontalHeaderItem(5)
        ___qtablewidgetitem5.setText(QCoreApplication.translate("Form", "P", None))
        ___qtablewidgetitem6 = self.table.horizontalHeaderItem(6)
        ___qtablewidgetitem6.setText(QCoreApplication.translate("Form", "I", None))
        ___qtablewidgetitem7 = self.table.horizontalHeaderItem(7)
        ___qtablewidgetitem7.setText(QCoreApplication.translate("Form", "Score", None))

    # retranslateUi
