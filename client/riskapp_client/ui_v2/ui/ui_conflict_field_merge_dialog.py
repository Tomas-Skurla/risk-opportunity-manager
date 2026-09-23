# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'conflict_field_merge_dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.11.0
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################

from PySide6.QtCore import (QCoreApplication, QDate, QDateTime, QLocale,
    QMetaObject, QObject, QPoint, QRect,
    QSize, QTime, QUrl, Qt)
from PySide6.QtGui import (QBrush, QColor, QConicalGradient, QCursor,
    QFont, QFontDatabase, QGradient, QIcon,
    QImage, QKeySequence, QLinearGradient, QPainter,
    QPalette, QPixmap, QRadialGradient, QTransform)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QHBoxLayout,
    QHeaderView, QLabel, QPushButton, QSizePolicy,
    QSpacerItem, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget)

class Ui_conflict_field_merge_dialog(object):
    def setupUi(self, conflict_field_merge_dialog):
        if not conflict_field_merge_dialog.objectName():
            conflict_field_merge_dialog.setObjectName(u"conflict_field_merge_dialog")
        conflict_field_merge_dialog.resize(1000, 650)
        conflict_field_merge_dialog.setMinimumSize(QSize(850, 500))
        self.verticalLayout = QVBoxLayout(conflict_field_merge_dialog)
        self.verticalLayout.setSpacing(10)
        self.verticalLayout.setObjectName(u"verticalLayout")
        self.verticalLayout.setContentsMargins(16, 16, 16, 16)
        self.item_label = QLabel(conflict_field_merge_dialog)
        self.item_label.setObjectName(u"item_label")
        font = QFont()
        font.setPointSize(14)
        font.setBold(True)
        self.item_label.setFont(font)

        self.verticalLayout.addWidget(self.item_label)

        self.merge_intro_label = QLabel(conflict_field_merge_dialog)
        self.merge_intro_label.setObjectName(u"merge_intro_label")
        font1 = QFont()
        font1.setPointSize(10)
        self.merge_intro_label.setFont(font1)
        self.merge_intro_label.setWordWrap(True)

        self.verticalLayout.addWidget(self.merge_intro_label)

        self.version_label = QLabel(conflict_field_merge_dialog)
        self.version_label.setObjectName(u"version_label")

        self.verticalLayout.addWidget(self.version_label)

        self.field_table = QTableWidget(conflict_field_merge_dialog)
        if (self.field_table.columnCount() < 4):
            self.field_table.setColumnCount(4)
        __qtablewidgetitem = QTableWidgetItem()
        self.field_table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.field_table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.field_table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.field_table.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        self.field_table.setObjectName(u"field_table")
        self.field_table.setMinimumSize(QSize(0, 280))
        self.field_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.field_table.setAlternatingRowColors(True)
        self.field_table.setColumnCount(4)

        self.verticalLayout.addWidget(self.field_table)

        self.horizontalLayout = QHBoxLayout()
        self.horizontalLayout.setObjectName(u"horizontalLayout")
        self.horizontalSpacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.horizontalLayout.addItem(self.horizontalSpacer)

        self.cancel_btn = QPushButton(conflict_field_merge_dialog)
        self.cancel_btn.setObjectName(u"cancel_btn")
        self.cancel_btn.setMinimumSize(QSize(100, 0))

        self.horizontalLayout.addWidget(self.cancel_btn)

        self.queue_merge_btn = QPushButton(conflict_field_merge_dialog)
        self.queue_merge_btn.setObjectName(u"queue_merge_btn")
        self.queue_merge_btn.setEnabled(False)
        self.queue_merge_btn.setMinimumSize(QSize(130, 0))

        self.horizontalLayout.addWidget(self.queue_merge_btn)


        self.verticalLayout.addLayout(self.horizontalLayout)


        self.retranslateUi(conflict_field_merge_dialog)

        QMetaObject.connectSlotsByName(conflict_field_merge_dialog)
    # setupUi

    def retranslateUi(self, conflict_field_merge_dialog):
        conflict_field_merge_dialog.setWindowTitle(QCoreApplication.translate("conflict_field_merge_dialog", u"Merge conflict fields", None))
        self.item_label.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Selected item", None))
        self.merge_intro_label.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Choose which value to keep for each differing editable field.", None))
        self.version_label.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Based on the saved server version", None))
        ___qtablewidgetitem = self.field_table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Field", None))
        ___qtablewidgetitem1 = self.field_table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"My value", None))
        ___qtablewidgetitem2 = self.field_table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Server value", None))
        ___qtablewidgetitem3 = self.field_table.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Keep", None))
        self.cancel_btn.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Cancel", None))
        self.queue_merge_btn.setText(QCoreApplication.translate("conflict_field_merge_dialog", u"Queue merge", None))
    # retranslateUi

