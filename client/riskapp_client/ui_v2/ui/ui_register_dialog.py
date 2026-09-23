"""UI form definition for the registration dialog."""

from PySide6.QtCore import QCoreApplication, QMetaObject, Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)


class Ui_RegisterDialog:

    def setupUi(self, Dialog):
        if not Dialog.objectName():
            Dialog.setObjectName("RegisterDialog")
        Dialog.resize(420, 340)

        self.verticalLayout = QVBoxLayout(Dialog)
        self.verticalLayout.setObjectName("verticalLayout")

        self.formLayout = QFormLayout()
        self.formLayout.setObjectName("formLayout")

        # --- Server URL ---
        self.serverURLLabel = QLabel(Dialog)
        self.serverURLLabel.setObjectName("serverURLLabel")
        self.formLayout.setWidget(
            0, QFormLayout.ItemRole.LabelRole, self.serverURLLabel
        )

        self.url = QLineEdit(Dialog)
        self.url.setObjectName("url")
        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.url)

        # --- Email ---
        self.emailLabel = QLabel(Dialog)
        self.emailLabel.setObjectName("emailLabel")
        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.emailLabel)

        self.email = QLineEdit(Dialog)
        self.email.setObjectName("email")
        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.email)

        # --- Password ---
        self.passwordLabel = QLabel(Dialog)
        self.passwordLabel.setObjectName("passwordLabel")
        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.passwordLabel)

        self.password = QLineEdit(Dialog)
        self.password.setObjectName("password")
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.password)

        # --- Confirm Password ---
        self.confirmPasswordLabel = QLabel(Dialog)
        self.confirmPasswordLabel.setObjectName("confirmPasswordLabel")
        self.formLayout.setWidget(
            3, QFormLayout.ItemRole.LabelRole, self.confirmPasswordLabel
        )

        self.confirm_password = QLineEdit(Dialog)
        self.confirm_password.setObjectName("confirm_password")
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.formLayout.setWidget(
            3, QFormLayout.ItemRole.FieldRole, self.confirm_password
        )

        self.verticalLayout.addLayout(self.formLayout)

        # --- Password hint ---
        self.password_hint = QLabel(Dialog)
        self.password_hint.setObjectName("password_hint")
        self.password_hint.setWordWrap(True)
        self.password_hint.setStyleSheet("color: grey; font-size: 11px;")
        self.verticalLayout.addWidget(self.password_hint)

        # --- Buttons ---
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

    def retranslateUi(self, Dialog):
        Dialog.setWindowTitle(
            QCoreApplication.translate("RegisterDialog", "Register new account", None)
        )
        self.serverURLLabel.setText(
            QCoreApplication.translate("RegisterDialog", "Server URL", None)
        )
        self.url.setText(
            QCoreApplication.translate(
                "RegisterDialog", "http://localhost:8000", None
            )
        )
        self.emailLabel.setText(
            QCoreApplication.translate("RegisterDialog", "Email", None)
        )
        self.passwordLabel.setText(
            QCoreApplication.translate("RegisterDialog", "Password", None)
        )
        self.confirmPasswordLabel.setText(
            QCoreApplication.translate("RegisterDialog", "Confirm password", None)
        )
        self.password_hint.setText(
            QCoreApplication.translate(
                "RegisterDialog",
                "Min. 12 characters, must include uppercase, lowercase, digit, and symbol.",
                None,
            )
        )
