################################################################################
## Form generated from reading UI file 'assessments_tab.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################


from PySide6.QtCore import QCoreApplication, QMetaObject, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
        Form.resize(675, 300)
        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QLabel(Form)
        self.label.setObjectName("label")

        self.verticalLayout.addWidget(self.label)

        self.splitter = QSplitter(Form)
        self.splitter.setObjectName("splitter")
        self.splitter.setOrientation(Qt.Orientation.Vertical)
        self.table_card = QFrame(self.splitter)
        self.table_card.setObjectName("table_card")
        self.table_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.table_card.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_2 = QVBoxLayout(self.table_card)
        self.verticalLayout_2.setObjectName("verticalLayout_2")
        self.assessments_table = QTableWidget(self.table_card)
        if self.assessments_table.columnCount() < 6:
            self.assessments_table.setColumnCount(6)
        __qtablewidgetitem = QTableWidgetItem()
        self.assessments_table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.assessments_table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.assessments_table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.assessments_table.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.assessments_table.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.assessments_table.setHorizontalHeaderItem(5, __qtablewidgetitem5)
        self.assessments_table.setObjectName("assessments_table")
        self.assessments_table.horizontalHeader().setCascadingSectionResizes(True)

        self.verticalLayout_2.addWidget(self.assessments_table)

        self.splitter.addWidget(self.table_card)
        self.editor_card = QFrame(self.splitter)
        self.editor_card.setObjectName("editor_card")
        self.editor_card.setFrameShape(QFrame.Shape.StyledPanel)
        self.editor_card.setFrameShadow(QFrame.Shadow.Raised)
        self.verticalLayout_3 = QVBoxLayout(self.editor_card)
        self.verticalLayout_3.setObjectName("verticalLayout_3")
        self.target_label = QLabel(self.editor_card)
        self.target_label.setObjectName("target_label")

        self.verticalLayout_3.addWidget(self.target_label)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName("horizontalLayout")
        self.label_2 = QLabel(self.editor_card)
        self.label_2.setObjectName("label_2")

        self.horizontalLayout.addWidget(self.label_2)

        self.assess_p = QSpinBox(self.editor_card)
        self.assess_p.setObjectName("assess_p")
        self.assess_p.setMinimum(1)
        self.assess_p.setMaximum(5)
        self.assess_p.setValue(3)

        self.horizontalLayout.addWidget(self.assess_p)

        self.label_3 = QLabel(self.editor_card)
        self.label_3.setObjectName("label_3")

        self.horizontalLayout.addWidget(self.label_3)

        self.assess_i = QSpinBox(self.editor_card)
        self.assess_i.setObjectName("assess_i")
        self.assess_i.setMinimum(1)
        self.assess_i.setMaximum(5)
        self.assess_i.setValue(3)

        self.horizontalLayout.addWidget(self.assess_i)

        self.label_4 = QLabel(self.editor_card)
        self.label_4.setObjectName("label_4")

        self.horizontalLayout.addWidget(self.label_4)

        self.assess_notes = QLineEdit(self.editor_card)
        self.assess_notes.setObjectName("assess_notes")

        self.horizontalLayout.addWidget(self.assess_notes)

        self.assess_save_btn = QPushButton(self.editor_card)
        self.assess_save_btn.setObjectName("assess_save_btn")

        self.horizontalLayout.addWidget(self.assess_save_btn)

        self.horizontalSpacer = QSpacerItem(
            40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum
        )

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.verticalLayout_3.addLayout(self.horizontalLayout)

        self.splitter.addWidget(self.editor_card)

        self.verticalLayout.addWidget(self.splitter)

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)

    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", "Form", None))
        self.label.setText(
            QCoreApplication.translate(
                "Form", "Assessments (per-user P/I + notes)", None
            )
        )
        ___qtablewidgetitem = self.assessments_table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(
            QCoreApplication.translate("Form", "Assessor", None)
        )
        ___qtablewidgetitem1 = self.assessments_table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("Form", "P", None))
        ___qtablewidgetitem2 = self.assessments_table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("Form", "I", None))
        ___qtablewidgetitem3 = self.assessments_table.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("Form", "Score", None))
        ___qtablewidgetitem4 = self.assessments_table.horizontalHeaderItem(4)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("Form", "Notes", None))
        ___qtablewidgetitem5 = self.assessments_table.horizontalHeaderItem(5)
        ___qtablewidgetitem5.setText(
            QCoreApplication.translate("Form", "Updated", None)
        )
        self.target_label.setText(
            QCoreApplication.translate("Form", "Target: (none)", None)
        )
        self.label_2.setText(QCoreApplication.translate("Form", "P", None))
        self.label_3.setText(QCoreApplication.translate("Form", "I", None))
        self.label_4.setText(QCoreApplication.translate("Form", "Notes", None))
        self.assess_notes.setPlaceholderText(
            QCoreApplication.translate("Form", "Notes....", None)
        )
        self.assess_save_btn.setText(
            QCoreApplication.translate("Form", "Save my assessment", None)
        )

    # retranslateUi
