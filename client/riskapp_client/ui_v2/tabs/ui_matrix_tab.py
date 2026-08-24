################################################################################
## Form generated from reading UI file 'matrix_tab.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################


from PySide6.QtCore import QCoreApplication, QMetaObject
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QSizePolicy,
    QSpacerItem,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)


class Ui_Form:

    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName("Form")
        Form.resize(400, 411)
        self.verticalLayout = QVBoxLayout(Form)
        self.verticalLayout.setObjectName("verticalLayout")
        self.label = QLabel(Form)
        self.label.setObjectName("label")

        self.verticalLayout.addWidget(self.label)

        self.kind_combo = QComboBox(Form)
        self.kind_combo.addItem("")
        self.kind_combo.addItem("")
        self.kind_combo.addItem("")
        self.kind_combo.setObjectName("kind_combo")

        self.verticalLayout.addWidget(self.kind_combo)

        self.risks_label = QLabel(Form)
        self.risks_label.setObjectName("risks_label")

        self.verticalLayout.addWidget(self.risks_label)

        self.risks_matrix_table = QTableWidget(Form)
        if self.risks_matrix_table.columnCount() < 5:
            self.risks_matrix_table.setColumnCount(5)
        __qtablewidgetitem = QTableWidgetItem()
        self.risks_matrix_table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.risks_matrix_table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.risks_matrix_table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.risks_matrix_table.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.risks_matrix_table.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        if self.risks_matrix_table.rowCount() < 5:
            self.risks_matrix_table.setRowCount(5)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.risks_matrix_table.setVerticalHeaderItem(0, __qtablewidgetitem5)
        __qtablewidgetitem6 = QTableWidgetItem()
        self.risks_matrix_table.setVerticalHeaderItem(1, __qtablewidgetitem6)
        __qtablewidgetitem7 = QTableWidgetItem()
        self.risks_matrix_table.setVerticalHeaderItem(2, __qtablewidgetitem7)
        __qtablewidgetitem8 = QTableWidgetItem()
        self.risks_matrix_table.setVerticalHeaderItem(3, __qtablewidgetitem8)
        __qtablewidgetitem9 = QTableWidgetItem()
        self.risks_matrix_table.setVerticalHeaderItem(4, __qtablewidgetitem9)
        self.risks_matrix_table.setObjectName("risks_matrix_table")

        self.verticalLayout.addWidget(self.risks_matrix_table)

        self.opps_label = QLabel(Form)
        self.opps_label.setObjectName("opps_label")

        self.verticalLayout.addWidget(self.opps_label)

        self.opps_matrix_table = QTableWidget(Form)
        if self.opps_matrix_table.columnCount() < 5:
            self.opps_matrix_table.setColumnCount(5)
        __qtablewidgetitem10 = QTableWidgetItem()
        self.opps_matrix_table.setHorizontalHeaderItem(0, __qtablewidgetitem10)
        __qtablewidgetitem11 = QTableWidgetItem()
        self.opps_matrix_table.setHorizontalHeaderItem(1, __qtablewidgetitem11)
        __qtablewidgetitem12 = QTableWidgetItem()
        self.opps_matrix_table.setHorizontalHeaderItem(2, __qtablewidgetitem12)
        __qtablewidgetitem13 = QTableWidgetItem()
        self.opps_matrix_table.setHorizontalHeaderItem(3, __qtablewidgetitem13)
        __qtablewidgetitem14 = QTableWidgetItem()
        self.opps_matrix_table.setHorizontalHeaderItem(4, __qtablewidgetitem14)
        if self.opps_matrix_table.rowCount() < 5:
            self.opps_matrix_table.setRowCount(5)
        __qtablewidgetitem15 = QTableWidgetItem()
        self.opps_matrix_table.setVerticalHeaderItem(0, __qtablewidgetitem15)
        __qtablewidgetitem16 = QTableWidgetItem()
        self.opps_matrix_table.setVerticalHeaderItem(1, __qtablewidgetitem16)
        __qtablewidgetitem17 = QTableWidgetItem()
        self.opps_matrix_table.setVerticalHeaderItem(2, __qtablewidgetitem17)
        __qtablewidgetitem18 = QTableWidgetItem()
        self.opps_matrix_table.setVerticalHeaderItem(3, __qtablewidgetitem18)
        __qtablewidgetitem19 = QTableWidgetItem()
        self.opps_matrix_table.setVerticalHeaderItem(4, __qtablewidgetitem19)
        self.opps_matrix_table.setObjectName("opps_matrix_table")

        self.verticalLayout.addWidget(self.opps_matrix_table)

        self.verticalSpacer = QSpacerItem(
            20, 4, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding
        )

        self.verticalLayout.addItem(self.verticalSpacer)

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)

    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", "Form", None))
        self.label.setText(
            QCoreApplication.translate(
                "Form", "Matrix (counts per Probability x Impact)", None
            )
        )
        self.kind_combo.setItemText(
            0, QCoreApplication.translate("Form", "Risks", None)
        )
        self.kind_combo.setItemText(
            1, QCoreApplication.translate("Form", "Opportunities", None)
        )
        self.kind_combo.setItemText(2, QCoreApplication.translate("Form", "Both", None))

        self.risks_label.setText(QCoreApplication.translate("Form", "Risks", None))
        ___qtablewidgetitem = self.risks_matrix_table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("Form", "I1", None))
        ___qtablewidgetitem1 = self.risks_matrix_table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("Form", "I2", None))
        ___qtablewidgetitem2 = self.risks_matrix_table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("Form", "I3", None))
        ___qtablewidgetitem3 = self.risks_matrix_table.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("Form", "I4", None))
        ___qtablewidgetitem4 = self.risks_matrix_table.horizontalHeaderItem(4)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("Form", "I5", None))
        ___qtablewidgetitem5 = self.risks_matrix_table.verticalHeaderItem(0)
        ___qtablewidgetitem5.setText(QCoreApplication.translate("Form", "P1", None))
        ___qtablewidgetitem6 = self.risks_matrix_table.verticalHeaderItem(1)
        ___qtablewidgetitem6.setText(QCoreApplication.translate("Form", "P2", None))
        ___qtablewidgetitem7 = self.risks_matrix_table.verticalHeaderItem(2)
        ___qtablewidgetitem7.setText(QCoreApplication.translate("Form", "P3", None))
        ___qtablewidgetitem8 = self.risks_matrix_table.verticalHeaderItem(3)
        ___qtablewidgetitem8.setText(QCoreApplication.translate("Form", "P4", None))
        ___qtablewidgetitem9 = self.risks_matrix_table.verticalHeaderItem(4)
        ___qtablewidgetitem9.setText(QCoreApplication.translate("Form", "P5", None))
        self.opps_label.setText(
            QCoreApplication.translate("Form", "Opportunities", None)
        )
        ___qtablewidgetitem10 = self.opps_matrix_table.horizontalHeaderItem(0)
        ___qtablewidgetitem10.setText(QCoreApplication.translate("Form", "I1", None))
        ___qtablewidgetitem11 = self.opps_matrix_table.horizontalHeaderItem(1)
        ___qtablewidgetitem11.setText(QCoreApplication.translate("Form", "I2", None))
        ___qtablewidgetitem12 = self.opps_matrix_table.horizontalHeaderItem(2)
        ___qtablewidgetitem12.setText(QCoreApplication.translate("Form", "I3", None))
        ___qtablewidgetitem13 = self.opps_matrix_table.horizontalHeaderItem(3)
        ___qtablewidgetitem13.setText(QCoreApplication.translate("Form", "I4", None))
        ___qtablewidgetitem14 = self.opps_matrix_table.horizontalHeaderItem(4)
        ___qtablewidgetitem14.setText(QCoreApplication.translate("Form", "I5", None))
        ___qtablewidgetitem15 = self.opps_matrix_table.verticalHeaderItem(0)
        ___qtablewidgetitem15.setText(QCoreApplication.translate("Form", "P1", None))
        ___qtablewidgetitem16 = self.opps_matrix_table.verticalHeaderItem(1)
        ___qtablewidgetitem16.setText(QCoreApplication.translate("Form", "P2", None))
        ___qtablewidgetitem17 = self.opps_matrix_table.verticalHeaderItem(2)
        ___qtablewidgetitem17.setText(QCoreApplication.translate("Form", "P3", None))
        ___qtablewidgetitem18 = self.opps_matrix_table.verticalHeaderItem(3)
        ___qtablewidgetitem18.setText(QCoreApplication.translate("Form", "P4", None))
        ___qtablewidgetitem19 = self.opps_matrix_table.verticalHeaderItem(4)
        ___qtablewidgetitem19.setText(QCoreApplication.translate("Form", "P5", None))

    # retranslateUi
