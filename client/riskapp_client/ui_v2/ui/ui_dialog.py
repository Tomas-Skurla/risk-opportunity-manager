################################################################################
## Form generated from reading UI file 'dialog.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################


from PySide6.QtCore import QCoreApplication, QMetaObject, Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class Ui_Dialog:

    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName("Dialog")
        Dialog.resize(400, 300)
        self.verticalLayout = QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")
        self.formLayout = QFormLayout()
        self.formLayout.setObjectName("formLayout")
        self.serverURLLabel = QLabel(Dialog)
        self.serverURLLabel.setObjectName("serverURLLabel")

        self.formLayout.setWidget(
            0, QFormLayout.ItemRole.LabelRole, self.serverURLLabel
        )

        self.url = QLineEdit(Dialog)
        self.url.setObjectName("url")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.url)

        self.emailLabel = QLabel(Dialog)
        self.emailLabel.setObjectName("emailLabel")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.emailLabel)

        self.email = QLineEdit(Dialog)
        self.email.setObjectName("email")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.email)

        self.passwordLabel = QLabel(Dialog)
        self.passwordLabel.setObjectName("passwordLabel")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.passwordLabel)

        self.password = QLineEdit(Dialog)
        self.password.setObjectName("password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)

        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.password)

        self.verticalLayout.addLayout(self.formLayout)

        self.buttonBox = QDialogButtonBox(Dialog)
        self.buttonBox.setObjectName("buttonBox")
        self.buttonBox.setOrientation(Qt.Orientation.Horizontal)
        self.buttonBox.setStandardButtons(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )

        self.verticalLayout.addWidget(self.buttonBox)

        self.retranslateUi(Dialog)
        self.buttonBox.accepted.connect(Dialog.accept)
        self.buttonBox.rejected.connect(Dialog.reject)

        QMetaObject.connectSlotsByName(Dialog)

    # setupUi

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(QCoreApplication.translate("Dialog", "Dialog", None))
        self.serverURLLabel.setText(
            QCoreApplication.translate("Dialog", "Server URL", None)
        )
        self.url.setText(
            QCoreApplication.translate("Dialog", "http://localhost:8000", None)
        )
        self.emailLabel.setText(QCoreApplication.translate("Dialog", "Email", None))
        self.passwordLabel.setText(
            QCoreApplication.translate("Dialog", "Password", None)
        )

    # retranslateUi
