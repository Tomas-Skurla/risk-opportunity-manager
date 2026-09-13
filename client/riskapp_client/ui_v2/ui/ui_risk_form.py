################################################################################
## Form generated from reading UI file 'risk_form.ui'
##
## Created by: Qt User Interface Compiler version 6.10.2
##
## WARNING! All changes made in this file will be lost when recompiling UI file!
################################################################################


from PySide6.QtCore import QCoreApplication, QDate, QDateTime, QMetaObject, QSize, QTime
from PySide6.QtWidgets import (
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTextEdit,
)


class Ui_Form:

    def setupUi(self, Form):
        if not Form.objectName():
            Form.setObjectName("Form")
        Form.resize(348, 603)
        self.formLayout = QFormLayout(Form)
        self.formLayout.setObjectName("formLayout")
        self.codeLabel = QLabel(Form)
        self.codeLabel.setObjectName("codeLabel")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.LabelRole, self.codeLabel)

        self.code = QLineEdit(Form)
        self.code.setObjectName("code")

        self.formLayout.setWidget(0, QFormLayout.ItemRole.FieldRole, self.code)

        self.titleLabel = QLabel(Form)
        self.titleLabel.setObjectName("titleLabel")

        self.formLayout.setWidget(1, QFormLayout.ItemRole.LabelRole, self.titleLabel)

        self.title = QLineEdit(Form)
        self.title.setObjectName("title")
        self.title.setEnabled(True)

        self.formLayout.setWidget(1, QFormLayout.ItemRole.FieldRole, self.title)

        self.categoryLabel = QLabel(Form)
        self.categoryLabel.setObjectName("categoryLabel")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.LabelRole, self.categoryLabel)

        self.category = QLineEdit(Form)
        self.category.setObjectName("category")

        self.formLayout.setWidget(2, QFormLayout.ItemRole.FieldRole, self.category)

        self.probability15Label = QLabel(Form)
        self.probability15Label.setObjectName("probability15Label")

        self.formLayout.setWidget(
            5, QFormLayout.ItemRole.LabelRole, self.probability15Label
        )

        self.p = QSpinBox(Form)
        self.p.setObjectName("p")
        self.p.setMinimum(1)
        self.p.setMaximum(5)
        self.p.setValue(3)

        self.formLayout.setWidget(5, QFormLayout.ItemRole.FieldRole, self.p)

        self.impactCost15Label = QLabel(Form)
        self.impactCost15Label.setObjectName("impactCost15Label")

        self.formLayout.setWidget(
            6, QFormLayout.ItemRole.LabelRole, self.impactCost15Label
        )

        self.impact_cost = QSpinBox(Form)
        self.impact_cost.setObjectName("impact_cost")
        self.impact_cost.setMinimum(1)
        self.impact_cost.setMaximum(5)
        self.impact_cost.setValue(3)

        self.formLayout.setWidget(6, QFormLayout.ItemRole.FieldRole, self.impact_cost)

        self.impactTime15Label = QLabel(Form)
        self.impactTime15Label.setObjectName("impactTime15Label")

        self.formLayout.setWidget(
            7, QFormLayout.ItemRole.LabelRole, self.impactTime15Label
        )

        self.impact_time = QSpinBox(Form)
        self.impact_time.setObjectName("impact_time")
        self.impact_time.setMinimum(1)
        self.impact_time.setMaximum(5)
        self.impact_time.setValue(3)

        self.formLayout.setWidget(7, QFormLayout.ItemRole.FieldRole, self.impact_time)

        self.impactScope15Label = QLabel(Form)
        self.impactScope15Label.setObjectName("impactScope15Label")

        self.formLayout.setWidget(
            8, QFormLayout.ItemRole.LabelRole, self.impactScope15Label
        )

        self.impact_scope = QSpinBox(Form)
        self.impact_scope.setObjectName("impact_scope")
        self.impact_scope.setMinimum(1)
        self.impact_scope.setMaximum(5)
        self.impact_scope.setValue(3)

        self.formLayout.setWidget(8, QFormLayout.ItemRole.FieldRole, self.impact_scope)

        self.impactQuality15Label = QLabel(Form)
        self.impactQuality15Label.setObjectName("impactQuality15Label")

        self.formLayout.setWidget(
            9, QFormLayout.ItemRole.LabelRole, self.impactQuality15Label
        )

        self.impact_quality = QSpinBox(Form)
        self.impact_quality.setObjectName("impact_quality")
        self.impact_quality.setMinimum(1)
        self.impact_quality.setMaximum(5)
        self.impact_quality.setValue(3)

        self.formLayout.setWidget(
            9, QFormLayout.ItemRole.FieldRole, self.impact_quality
        )

        self.statusLabel = QLabel(Form)
        self.statusLabel.setObjectName("statusLabel")

        self.formLayout.setWidget(3, QFormLayout.ItemRole.LabelRole, self.statusLabel)

        self.status = QComboBox(Form)
        self.status.addItem("")
        self.status.addItem("")
        self.status.addItem("")
        self.status.addItem("")
        self.status.addItem("")
        self.status.setObjectName("status")

        self.formLayout.setWidget(3, QFormLayout.ItemRole.FieldRole, self.status)

        self.ownerLabel = QLabel(Form)
        self.ownerLabel.setObjectName("ownerLabel")

        self.formLayout.setWidget(4, QFormLayout.ItemRole.LabelRole, self.ownerLabel)

        self.owner_user_id = QComboBox(Form)
        self.owner_user_id.setObjectName("owner_user_id")

        self.formLayout.setWidget(4, QFormLayout.ItemRole.FieldRole, self.owner_user_id)

        self.impactOverallMaxLabel = QLabel(Form)
        self.impactOverallMaxLabel.setObjectName("impactOverallMaxLabel")

        self.formLayout.setWidget(
            10, QFormLayout.ItemRole.LabelRole, self.impactOverallMaxLabel
        )

        self.i = QSpinBox(Form)
        self.i.setObjectName("i")
        self.i.setEnabled(False)
        self.i.setMinimum(1)
        self.i.setMaximum(5)
        self.i.setValue(3)

        self.formLayout.setWidget(10, QFormLayout.ItemRole.FieldRole, self.i)

        self.descriptionLabel = QLabel(Form)
        self.descriptionLabel.setObjectName("descriptionLabel")

        self.formLayout.setWidget(
            11, QFormLayout.ItemRole.LabelRole, self.descriptionLabel
        )

        self.description = QTextEdit(Form)
        self.description.setObjectName("description")
        self.description.setMaximumSize(QSize(16777215, 40))

        self.formLayout.setWidget(11, QFormLayout.ItemRole.FieldRole, self.description)

        self.threatLabel = QLabel(Form)
        self.threatLabel.setObjectName("threatLabel")

        self.formLayout.setWidget(12, QFormLayout.ItemRole.LabelRole, self.threatLabel)

        self.threat = QTextEdit(Form)
        self.threat.setObjectName("threat")
        self.threat.setMaximumSize(QSize(16777215, 40))

        self.formLayout.setWidget(12, QFormLayout.ItemRole.FieldRole, self.threat)

        self.triggersLabel = QLabel(Form)
        self.triggersLabel.setObjectName("triggersLabel")

        self.formLayout.setWidget(
            13, QFormLayout.ItemRole.LabelRole, self.triggersLabel
        )

        self.triggers = QTextEdit(Form)
        self.triggers.setObjectName("triggers")
        self.triggers.setMaximumSize(QSize(16777215, 40))

        self.formLayout.setWidget(13, QFormLayout.ItemRole.FieldRole, self.triggers)

        self.mitigationResponseLabel = QLabel(Form)
        self.mitigationResponseLabel.setObjectName("mitigationResponseLabel")

        self.formLayout.setWidget(
            14, QFormLayout.ItemRole.LabelRole, self.mitigationResponseLabel
        )

        self.mitigation_plan = QTextEdit(Form)
        self.mitigation_plan.setObjectName("mitigation_plan")
        self.mitigation_plan.setMaximumSize(QSize(16777215, 40))

        self.formLayout.setWidget(
            14, QFormLayout.ItemRole.FieldRole, self.mitigation_plan
        )

        self.documentURLLabel = QLabel(Form)
        self.documentURLLabel.setObjectName("documentURLLabel")

        self.formLayout.setWidget(
            15, QFormLayout.ItemRole.LabelRole, self.documentURLLabel
        )

        self.document_url = QLineEdit(Form)
        self.document_url.setObjectName("document_url")

        self.formLayout.setWidget(15, QFormLayout.ItemRole.FieldRole, self.document_url)

        self.identifiedAtLabel = QLabel(Form)
        self.identifiedAtLabel.setObjectName("identifiedAtLabel")

        self.formLayout.setWidget(
            16, QFormLayout.ItemRole.LabelRole, self.identifiedAtLabel
        )

        self.responseAtLabel = QLabel(Form)
        self.responseAtLabel.setObjectName("responseAtLabel")

        self.formLayout.setWidget(
            17, QFormLayout.ItemRole.LabelRole, self.responseAtLabel
        )

        self.occurredAtLabel = QLabel(Form)
        self.occurredAtLabel.setObjectName("occurredAtLabel")

        self.formLayout.setWidget(
            18, QFormLayout.ItemRole.LabelRole, self.occurredAtLabel
        )

        self.statusChangedAtLabel = QLabel(Form)
        self.statusChangedAtLabel.setObjectName("statusChangedAtLabel")

        self.formLayout.setWidget(
            19, QFormLayout.ItemRole.LabelRole, self.statusChangedAtLabel
        )

        self.btn = QPushButton(Form)
        self.btn.setObjectName("btn")

        self.formLayout.setWidget(23, QFormLayout.ItemRole.LabelRole, self.btn)

        self.identified_at = QDateTimeEdit(Form)
        self.identified_at.setObjectName("identified_at")
        self.identified_at.setDate(QDate(2025, 1, 1))
        self.identified_at.setMaximumDateTime(
            QDateTime(QDate(2070, 12, 31), QTime(23, 59, 59))
        )
        self.identified_at.setMaximumDate(QDate(2070, 12, 31))
        self.identified_at.setMinimumDate(QDate(1970, 1, 1))
        self.identified_at.setCalendarPopup(True)

        self.formLayout.setWidget(
            16, QFormLayout.ItemRole.FieldRole, self.identified_at
        )

        self.response_at = QDateTimeEdit(Form)
        self.response_at.setObjectName("response_at")
        self.response_at.setDate(QDate(2025, 1, 1))
        self.response_at.setMaximumDateTime(
            QDateTime(QDate(2070, 12, 31), QTime(23, 59, 59))
        )
        self.response_at.setMaximumDate(QDate(2070, 12, 31))
        self.response_at.setMinimumDate(QDate(1970, 1, 1))
        self.response_at.setCalendarPopup(True)

        self.formLayout.setWidget(17, QFormLayout.ItemRole.FieldRole, self.response_at)

        self.occurred_at = QDateTimeEdit(Form)
        self.occurred_at.setObjectName("occurred_at")
        self.occurred_at.setDate(QDate(2025, 1, 1))
        self.occurred_at.setMaximumDateTime(
            QDateTime(QDate(2070, 12, 31), QTime(23, 59, 59))
        )
        self.occurred_at.setMaximumDate(QDate(2070, 12, 31))
        self.occurred_at.setMinimumDate(QDate(1970, 1, 1))
        self.occurred_at.setCalendarPopup(True)

        self.formLayout.setWidget(18, QFormLayout.ItemRole.FieldRole, self.occurred_at)

        self.status_changed_at = QDateTimeEdit(Form)
        self.status_changed_at.setObjectName("status_changed_at")
        self.status_changed_at.setEnabled(True)
        self.status_changed_at.setReadOnly(True)
        self.status_changed_at.setDateTime(QDateTime(QDate(2025, 1, 1), QTime(0, 0, 0)))
        self.status_changed_at.setMaximumDateTime(
            QDateTime(QDate(2070, 12, 31), QTime(23, 59, 59))
        )
        self.status_changed_at.setMinimumDate(QDate(1970, 1, 1))
        self.status_changed_at.setCalendarPopup(True)

        self.formLayout.setWidget(
            19, QFormLayout.ItemRole.FieldRole, self.status_changed_at
        )

        self.retranslateUi(Form)

        QMetaObject.connectSlotsByName(Form)

    # setupUi

    def retranslateUi(self, Form):
        Form.setWindowTitle(QCoreApplication.translate("Form", "Form", None))
        self.codeLabel.setText(QCoreApplication.translate("Form", "Code", None))
        self.titleLabel.setText(QCoreApplication.translate("Form", "Title", None))
        self.categoryLabel.setText(QCoreApplication.translate("Form", "Category", None))
        self.probability15Label.setText(
            QCoreApplication.translate("Form", "Probability (1-5)", None)
        )
        self.impactCost15Label.setText(
            QCoreApplication.translate("Form", "Impact - Cost (1-5)", None)
        )
        self.impactTime15Label.setText(
            QCoreApplication.translate("Form", "Impact - Time (1-5)", None)
        )
        self.impactScope15Label.setText(
            QCoreApplication.translate("Form", "Impact - Scope (1-5)", None)
        )
        self.impactQuality15Label.setText(
            QCoreApplication.translate("Form", "Impact - Quality (1-5)", None)
        )
        self.statusLabel.setText(QCoreApplication.translate("Form", "Status", None))
        self.status.setItemText(0, QCoreApplication.translate("Form", "concept", None))
        self.status.setItemText(1, QCoreApplication.translate("Form", "active", None))
        self.status.setItemText(2, QCoreApplication.translate("Form", "closed", None))
        self.status.setItemText(3, QCoreApplication.translate("Form", "deleted", None))
        self.status.setItemText(4, QCoreApplication.translate("Form", "happened", None))

        self.ownerLabel.setText(QCoreApplication.translate("Form", "Owner", None))
        self.impactOverallMaxLabel.setText(
            QCoreApplication.translate("Form", "Impact (overall, max)", None)
        )
        self.descriptionLabel.setText(
            QCoreApplication.translate("Form", "Description", None)
        )
        self.threatLabel.setText(QCoreApplication.translate("Form", "Threat", None))
        self.triggersLabel.setText(QCoreApplication.translate("Form", "Triggers", None))
        self.mitigationResponseLabel.setText(
            QCoreApplication.translate("Form", "Mitigation/Response", None)
        )
        self.documentURLLabel.setText(
            QCoreApplication.translate("Form", "Document URL", None)
        )
        self.identifiedAtLabel.setText(
            QCoreApplication.translate("Form", "Identified at", None)
        )
        self.responseAtLabel.setText(
            QCoreApplication.translate("Form", "Response at", None)
        )
        self.occurredAtLabel.setText(
            QCoreApplication.translate("Form", "Occurred at", None)
        )
        self.statusChangedAtLabel.setText(
            QCoreApplication.translate("Form", "Status changed at", None)
        )
        self.btn.setText(QCoreApplication.translate("Form", "Save Risk", None))
        self.identified_at.setDisplayFormat(
            QCoreApplication.translate("Form", "yyyy-MM-dd HH:mm:ss", None)
        )
        self.response_at.setDisplayFormat(
            QCoreApplication.translate("Form", "yyyy-MM-dd HH:mm:ss", None)
        )
        self.occurred_at.setDisplayFormat(
            QCoreApplication.translate("Form", "yyyy-MM-dd HH:mm:ss", None)
        )
        self.status_changed_at.setDisplayFormat(
            QCoreApplication.translate("Form", "yyyy-MM-dd HH:mm:ss", None)
        )

    # retranslateUi
