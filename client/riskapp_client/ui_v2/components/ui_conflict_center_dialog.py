# -*- coding: utf-8 -*-

################################################################################
## Form generated from reading UI file 'conflict_center_dialog.ui'
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
from PySide6.QtWidgets import (QAbstractButton, QAbstractItemView, QApplication, QDialog,
    QDialogButtonBox, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QPlainTextEdit, QPushButton, QSizePolicy,
    QSpacerItem, QTableWidget, QTableWidgetItem, QVBoxLayout,
    QWidget)

class Ui_ConflictCenterDialog(object):
    def setupUi(self, conflict_center_dialog):
        if not conflict_center_dialog.objectName():
            conflict_center_dialog.setObjectName(u"conflict_center_dialog")
        conflict_center_dialog.resize(900, 680)
        conflict_center_dialog.setMinimumSize(QSize(800, 620))
        self.main_layout = QVBoxLayout(conflict_center_dialog)
        self.main_layout.setSpacing(10)
        self.main_layout.setObjectName(u"main_layout")
        self.main_layout.setContentsMargins(10, 10, 10, 10)
        self.intro_label = QLabel(conflict_center_dialog)
        self.intro_label.setObjectName(u"intro_label")
        self.intro_label.setWordWrap(True)

        self.main_layout.addWidget(self.intro_label)

        self.conflict_table = QTableWidget(conflict_center_dialog)
        if (self.conflict_table.columnCount() < 6):
            self.conflict_table.setColumnCount(6)
        __qtablewidgetitem = QTableWidgetItem()
        self.conflict_table.setHorizontalHeaderItem(0, __qtablewidgetitem)
        __qtablewidgetitem1 = QTableWidgetItem()
        self.conflict_table.setHorizontalHeaderItem(1, __qtablewidgetitem1)
        __qtablewidgetitem2 = QTableWidgetItem()
        self.conflict_table.setHorizontalHeaderItem(2, __qtablewidgetitem2)
        __qtablewidgetitem3 = QTableWidgetItem()
        self.conflict_table.setHorizontalHeaderItem(3, __qtablewidgetitem3)
        __qtablewidgetitem4 = QTableWidgetItem()
        self.conflict_table.setHorizontalHeaderItem(4, __qtablewidgetitem4)
        __qtablewidgetitem5 = QTableWidgetItem()
        self.conflict_table.setHorizontalHeaderItem(5, __qtablewidgetitem5)
        self.conflict_table.setObjectName(u"conflict_table")
        self.conflict_table.setMinimumSize(QSize(0, 200))
        self.conflict_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.conflict_table.setAlternatingRowColors(True)
        self.conflict_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.conflict_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.conflict_table.setSortingEnabled(False)
        self.conflict_table.horizontalHeader().setStretchLastSection(True)
        self.conflict_table.verticalHeader().setVisible(False)

        self.main_layout.addWidget(self.conflict_table)

        self.comparison_layout = QHBoxLayout()
        self.comparison_layout.setSpacing(10)
        self.comparison_layout.setObjectName(u"comparison_layout")
        self.local_group = QGroupBox(conflict_center_dialog)
        self.local_group.setObjectName(u"local_group")
        sizePolicy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        sizePolicy.setHorizontalStretch(1)
        sizePolicy.setVerticalStretch(0)
        sizePolicy.setHeightForWidth(self.local_group.sizePolicy().hasHeightForWidth())
        self.local_group.setSizePolicy(sizePolicy)
        self.verticalLayout_2 = QVBoxLayout(self.local_group)
        self.verticalLayout_2.setObjectName(u"verticalLayout_2")
        self.local_copy = QPlainTextEdit(self.local_group)
        self.local_copy.setObjectName(u"local_copy")
        self.local_copy.setMinimumSize(QSize(300, 255))
        font = QFont()
        font.setFamilies([u"Consolas"])
        self.local_copy.setFont(font)
        self.local_copy.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.local_copy.setReadOnly(True)

        self.verticalLayout_2.addWidget(self.local_copy)


        self.comparison_layout.addWidget(self.local_group)

        self.server_group = QGroupBox(conflict_center_dialog)
        self.server_group.setObjectName(u"server_group")
        sizePolicy.setHeightForWidth(self.server_group.sizePolicy().hasHeightForWidth())
        self.server_group.setSizePolicy(sizePolicy)
        self.verticalLayout_3 = QVBoxLayout(self.server_group)
        self.verticalLayout_3.setObjectName(u"verticalLayout_3")
        self.server_copy = QPlainTextEdit(self.server_group)
        self.server_copy.setObjectName(u"server_copy")
        self.server_copy.setMinimumSize(QSize(300, 255))
        self.server_copy.setFont(font)
        self.server_copy.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.server_copy.setReadOnly(True)

        self.verticalLayout_3.addWidget(self.server_copy)


        self.comparison_layout.addWidget(self.server_group)

        self.comparison_layout.setStretch(0, 1)
        self.comparison_layout.setStretch(1, 1)

        self.main_layout.addLayout(self.comparison_layout)

        self.actions_layout = QHBoxLayout()
        self.actions_layout.setSpacing(8)
        self.actions_layout.setObjectName(u"actions_layout")
        self.keep_mine_btn = QPushButton(conflict_center_dialog)
        self.keep_mine_btn.setObjectName(u"keep_mine_btn")
        self.keep_mine_btn.setEnabled(False)
        self.keep_mine_btn.setMinimumSize(QSize(110, 0))

        self.actions_layout.addWidget(self.keep_mine_btn)

        self.use_server_btn = QPushButton(conflict_center_dialog)
        self.use_server_btn.setObjectName(u"use_server_btn")
        self.use_server_btn.setEnabled(False)
        self.use_server_btn.setMinimumSize(QSize(110, 0))

        self.actions_layout.addWidget(self.use_server_btn)

        self.later_btn = QPushButton(conflict_center_dialog)
        self.later_btn.setObjectName(u"later_btn")
        self.later_btn.setMinimumSize(QSize(90, 0))

        self.actions_layout.addWidget(self.later_btn)

        self.actions_spacer = QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)

        self.actions_layout.addItem(self.actions_spacer)

        self.conflict_close_buttons = QDialogButtonBox(conflict_center_dialog)
        self.conflict_close_buttons.setObjectName(u"conflict_close_buttons")
        self.conflict_close_buttons.setMinimumSize(QSize(90, 0))
        self.conflict_close_buttons.setStandardButtons(QDialogButtonBox.StandardButton.Close)
        self.conflict_close_buttons.setCenterButtons(False)

        self.actions_layout.addWidget(self.conflict_close_buttons)


        self.main_layout.addLayout(self.actions_layout)

        self.main_layout.setStretch(1, 3)
        self.main_layout.setStretch(2, 4)
        QWidget.setTabOrder(self.conflict_table, self.local_copy)
        QWidget.setTabOrder(self.local_copy, self.server_copy)
        QWidget.setTabOrder(self.server_copy, self.keep_mine_btn)
        QWidget.setTabOrder(self.keep_mine_btn, self.use_server_btn)
        QWidget.setTabOrder(self.use_server_btn, self.later_btn)

        self.retranslateUi(conflict_center_dialog)
        self.conflict_close_buttons.rejected.connect(conflict_center_dialog.reject)

        QMetaObject.connectSlotsByName(conflict_center_dialog)
    # setupUi

    def retranslateUi(self, conflict_center_dialog):
        conflict_center_dialog.setWindowTitle(QCoreApplication.translate("ConflictCenterDialog", u"Synchronization conflicts", None))
#if QT_CONFIG(accessibility)
        conflict_center_dialog.setAccessibleName("")
#endif // QT_CONFIG(accessibility)
        self.intro_label.setText(QCoreApplication.translate("ConflictCenterDialog", u"These items changed both locally and on the server. Select one, compare the copies, then choose which version should win.", None))
        ___qtablewidgetitem = self.conflict_table.horizontalHeaderItem(0)
        ___qtablewidgetitem.setText(QCoreApplication.translate("ConflictCenterDialog", u"Type", None))
        ___qtablewidgetitem1 = self.conflict_table.horizontalHeaderItem(1)
        ___qtablewidgetitem1.setText(QCoreApplication.translate("ConflictCenterDialog", u"Item", None))
        ___qtablewidgetitem2 = self.conflict_table.horizontalHeaderItem(2)
        ___qtablewidgetitem2.setText(QCoreApplication.translate("ConflictCenterDialog", u"Operation", None))
        ___qtablewidgetitem3 = self.conflict_table.horizontalHeaderItem(3)
        ___qtablewidgetitem3.setText(QCoreApplication.translate("ConflictCenterDialog", u"Reason", None))
        ___qtablewidgetitem4 = self.conflict_table.horizontalHeaderItem(4)
        ___qtablewidgetitem4.setText(QCoreApplication.translate("ConflictCenterDialog", u"Server version", None))
        ___qtablewidgetitem5 = self.conflict_table.horizontalHeaderItem(5)
        ___qtablewidgetitem5.setText(QCoreApplication.translate("ConflictCenterDialog", u"Server updated", None))
#if QT_CONFIG(tooltip)
        self.conflict_table.setToolTip(QCoreApplication.translate("ConflictCenterDialog", u"Select a conflict to compare the local and server copies", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.conflict_table.setAccessibleName(QCoreApplication.translate("ConflictCenterDialog", u"Unresolved synchronization conflicts", None))
#endif // QT_CONFIG(accessibility)
        self.local_group.setTitle(QCoreApplication.translate("ConflictCenterDialog", u"Local copy", None))
#if QT_CONFIG(accessibility)
        self.local_copy.setAccessibleName(QCoreApplication.translate("ConflictCenterDialog", u"Local record data", None))
#endif // QT_CONFIG(accessibility)
        self.local_copy.setPlaceholderText(QCoreApplication.translate("ConflictCenterDialog", u"Select a conflict to view the local copy.", None))
        self.server_group.setTitle(QCoreApplication.translate("ConflictCenterDialog", u"Server copy", None))
#if QT_CONFIG(accessibility)
        self.server_copy.setAccessibleName(QCoreApplication.translate("ConflictCenterDialog", u"Server record data", None))
#endif // QT_CONFIG(accessibility)
        self.server_copy.setPlaceholderText(QCoreApplication.translate("ConflictCenterDialog", u"Select a conflict to view the server copy.", None))
#if QT_CONFIG(tooltip)
        self.keep_mine_btn.setToolTip(QCoreApplication.translate("ConflictCenterDialog", u"Queue your local copy again against the latest known server version", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.keep_mine_btn.setAccessibleName(QCoreApplication.translate("ConflictCenterDialog", u"Keep my local version", None))
#endif // QT_CONFIG(accessibility)
        self.keep_mine_btn.setText(QCoreApplication.translate("ConflictCenterDialog", u"Keep mine", None))
#if QT_CONFIG(tooltip)
        self.use_server_btn.setToolTip(QCoreApplication.translate("ConflictCenterDialog", u"Discard this queued local write and replace it with the saved server copy", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.use_server_btn.setAccessibleName(QCoreApplication.translate("ConflictCenterDialog", u"Use the server version", None))
#endif // QT_CONFIG(accessibility)
        self.use_server_btn.setText(QCoreApplication.translate("ConflictCenterDialog", u"Use server", None))
#if QT_CONFIG(tooltip)
        self.later_btn.setToolTip(QCoreApplication.translate("ConflictCenterDialog", u"Leave every unresolved conflict blocked", None))
#endif // QT_CONFIG(tooltip)
#if QT_CONFIG(accessibility)
        self.later_btn.setAccessibleName(QCoreApplication.translate("ConflictCenterDialog", u"Decide later", None))
#endif // QT_CONFIG(accessibility)
        self.later_btn.setText(QCoreApplication.translate("ConflictCenterDialog", u"Later", None))
    # retranslateUi

