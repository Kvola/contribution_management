# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
import logging
from datetime import datetime, timedelta, date
from dateutil.relativedelta import relativedelta

_logger = logging.getLogger(__name__)


class MemberPaymentInstallment(models.Model):
    """Échéance d'un plan de paiement"""

    _name = "member.payment.installment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Échéance plan de paiement"
    _order = "due_date, sequence"

    name = fields.Char(string="Nom")
    payment_plan_id = fields.Many2one(
        "member.payment.plan",
        string="Plan de paiement",
        ondelete="cascade",
        required=True,
    )
    sequence = fields.Integer(string="Numéro", default=1)
    due_date = fields.Date(string="Date d'échéance", required=True, default=lambda self: fields.Date.today() + timedelta(days=7))
    amount = fields.Monetary(
        string="Montant dû", currency_field="currency_id", required=True
    )
    amount_paid = fields.Monetary(
        string="Montant payé", currency_field="currency_id", default=0.0
    )

    state = fields.Selection(
        [
            ("pending", "En attente"),
            ("partial", "Partiel"),
            ("paid", "Payé"),
            ("overdue", "En retard"),
            ("cancelled", "Annulé"),
        ],
        string="État",
        default="pending",
        required=True,
    )

    payment_date = fields.Date(string="Date de paiement")
    notes = fields.Text(string="Notes")

    # Relations avec protection contre les erreurs
    currency_id = fields.Many2one(
        "res.currency",
        string="Devise",
        compute="_compute_currency_id",
        store=True,
        readonly=True,
    )
    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        compute="_compute_member_id",
        store=True,
        readonly=True,
    )

    # Champs calculés
    remaining_amount = fields.Monetary(
        string="Montant restant",
        compute="_compute_remaining_amount",
        currency_field="currency_id",
        store=True,
    )

    days_overdue = fields.Integer(
        string="Jours de retard", compute="_compute_days_overdue", store=True
    )

    # Relation avec les cotisations
    cotisation_ids = fields.Many2many(
        "member.cotisation",
        "installment_cotisation_rel",
        "installment_id",
        "cotisation_id",
        string="Cotisations liées",
        help="Cotisations qui seront payées par cette échéance",
    )

    cotisation_count = fields.Integer(
        string="Nombre de cotisations", compute="_compute_cotisation_count", store=True
    )

    # Mode de répartition
    allocation_method = fields.Selection(
        [
            ("auto", "Répartition automatique"),
            ("manual", "Répartition manuelle"),
            ("oldest_first", "Plus anciennes d'abord"),
            ("amount_priority", "Par montant (plus élevé d'abord)"),
        ],
        string="Méthode de répartition",
        default="auto",
        help="Comment répartir le paiement sur les cotisations",
    )

    # Suivi de l'allocation
    allocation_details = fields.Text(
        string="Détails de répartition",
        help="Détail de comment le paiement a été réparti",
    )

    auto_allocate = fields.Boolean(
        string="Répartition automatique",
        default=True,
        help="Répartir automatiquement sur les cotisations non payées",
    )

    def update_allocation_configs(self):
        """Update allocation configurations automatically"""
        from datetime import datetime, timedelta

        installments_without_config = self.search(
            [
                ("state", "in", ["pending", "partial"]),
                ("allocation_method", "=", False),
                (
                    "create_date",
                    ">=",
                    (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),
                ),
            ]
        )

        default_method = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("contribution_management.default_allocation_method", "auto")
        )

        default_auto_allocate = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("contribution_management.default_auto_allocate", "True")
            == "True"
        )

        for installment in installments_without_config:
            installment.write(
                {
                    "allocation_method": default_method,
                    "auto_allocate": default_auto_allocate,
                }
            )

            if default_auto_allocate:
                installment._auto_select_cotisations()

        if installments_without_config:
            _logger.info(
                f"Configuration automatique appliquée à {len(installments_without_config)} échéances"
            )

    def send_weekly_allocation_report(self):
        """Send weekly allocation report"""
        from datetime import datetime, timedelta

        last_week = datetime.now() - timedelta(days=7)

        recent_allocations = self.search(
            [
                ("write_date", ">=", last_week.strftime("%Y-%m-%d")),
                ("allocation_details", "!=", False),
            ]
        )

        new_configs = self.search(
            [
                ("create_date", ">=", last_week.strftime("%Y-%m-%d")),
                ("cotisation_count", ">", 0),
            ]
        )

        if recent_allocations or new_configs:
            managers = self.env["res.users"].search(
                [
                    (
                        "groups_id",
                        "in",
                        [
                            self.env.ref(
                                "contribution_management.group_installment_allocation_manager"
                            ).id
                        ],
                    )
                ]
            )
            subject = f"Rapport hebdomadaire - Allocations échéances-cotisations"
            body = f"""
                Rapport de la semaine du {last_week.strftime('%d/%m/%Y')} au {datetime.now().strftime('%d/%m/%Y')}

                📊 Statistiques :
                - {len(recent_allocations)} allocations effectuées
                - {len(new_configs)} nouvelles configurations
                - {sum(recent_allocations.mapped('amount_paid'))} montant total alloué
                """
            for manager in managers:
                if manager.email:
                    self.env["mail.mail"].create(
                        {
                            "subject": subject,
                            "body_html": body.replace("\n", "<br />"),
                            "email_to": manager.email,
                            "auto_delete": True,
                        }
                    ).send()

    @api.depends("cotisation_ids")
    def _compute_cotisation_count(self):
        """Calcule le nombre de cotisations liées"""
        for installment in self:
            installment.cotisation_count = len(installment.cotisation_ids)

    # def action_mark_paid(self):
    #     """Override pour impacter les cotisations lors du paiement"""
    #     result = super().action_mark_paid()

    #     # Répartir le montant sur les cotisations
    #     self._allocate_payment_to_cotisations(self.amount)

    #     return result

    # def action_partial_payment(self, amount):
    #     """Override pour impacter les cotisations lors du paiement partiel"""
    #     result = super().action_partial_payment(amount)

    #     # Répartir le montant partiel sur les cotisations
    #     self._allocate_payment_to_cotisations(amount)

    #     return result

    def _allocate_payment_to_cotisations(self, payment_amount):
        """Répartit le paiement sur les cotisations liées"""
        if not self.cotisation_ids or payment_amount <= 0:
            return

        # Si répartition automatique activée, ajouter les cotisations non payées
        if self.auto_allocate:
            self._auto_select_cotisations()

        allocation_details = []
        remaining_amount = payment_amount

        # Obtenir les cotisations triées selon la méthode
        sorted_cotisations = self._get_sorted_cotisations()

        for cotisation in sorted_cotisations:
            if remaining_amount <= 0:
                break

            # Calculer le montant à allouer à cette cotisation
            cotisation_remaining = cotisation.amount_due - cotisation.amount_paid

            if cotisation_remaining > 0:
                amount_to_allocate = min(remaining_amount, cotisation_remaining)

                # Créer le paiement de cotisation
                self._create_cotisation_payment(cotisation, amount_to_allocate)

                allocation_details.append(
                    f"• {cotisation.display_name}: {amount_to_allocate:.2f} {self.currency_id.symbol}"
                )

                remaining_amount -= amount_to_allocate

        # Enregistrer les détails de répartition
        self.allocation_details = (
            f"Répartition du {datetime.now().strftime('%d/%m/%Y %H:%M')}:\n"
            + "\n".join(allocation_details)
        )

        if remaining_amount > 0:
            self.allocation_details += f"\n⚠️ Montant non réparti: {remaining_amount:.2f} {self.currency_id.symbol}"

        # Message de suivi
        self._post_allocation_message(
            payment_amount - remaining_amount, allocation_details
        )

    def _auto_select_cotisations(self):
        """Sélectionne automatiquement les cotisations non payées du membre"""
        if not self.member_id:
            return

        # Rechercher les cotisations non payées du membre
        unpaid_cotisations = self.env["member.cotisation"].search(
            [
                ("member_id", "=", self.member_id.id),
                ("state", "in", ["pending", "partial", "overdue"]),
                ("id", "not in", self.cotisation_ids.ids),  # Exclure celles déjà liées
            ]
        )

        # Ajouter les cotisations trouvées
        if unpaid_cotisations:
            self.cotisation_ids = [(4, cot_id) for cot_id in unpaid_cotisations.ids]

    def _get_sorted_cotisations(self):
        """Retourne les cotisations triées selon la méthode choisie"""
        cotisations = self.cotisation_ids.filtered(
            lambda c: c.state in ["pending", "partial", "overdue"]
        )

        if self.allocation_method == "oldest_first":
            return cotisations.sorted(lambda c: c.due_date or fields.Date.today())

        elif self.allocation_method == "amount_priority":
            return cotisations.sorted(lambda c: -(c.amount_due - c.amount_paid))

        elif self.allocation_method == "manual":
            return cotisations  # Ordre manuel défini par l'utilisateur

        else:  # auto
            # Tri par priorité : retard d'abord, puis par date d'échéance
            def sort_key(cotisation):
                priority = 0
                if cotisation.state == "overdue":
                    priority += 1000
                elif cotisation.state == "partial":
                    priority += 500

                # Ajouter les jours de retard
                if cotisation.due_date:
                    days_overdue = (fields.Date.today() - cotisation.due_date).days
                    if days_overdue > 0:
                        priority += days_overdue

                return -priority  # Tri décroissant

            return sorted(cotisations, key=sort_key)

    def _create_cotisation_payment(self, cotisation, amount):
        """Crée un paiement pour la cotisation"""
        payment_vals = {
            "name": f"PAY-{self.name}-{cotisation.id}",
            "cotisation_id": cotisation.id,
            "member_id": self.member_id.id,
            "amount": amount,
            "payment_date": fields.Date.today(),
            "payment_method": "installment",  # Méthode spécifique pour les échéances
            "reference": f"Échéance {self.sequence} - Plan {self.payment_plan_id.name}",
            "notes": f"Paiement via échéance {self.name}",
            "currency_id": self.currency_id.id,
            "installment_id": self.id,  # Lien vers l'échéance
        }

        payment = self.env["cotisation.payment"].create(payment_vals)

        # Mettre à jour la cotisation
        new_amount_paid = cotisation.amount_paid + amount
        cotisation.write(
            {
                "amount_paid": new_amount_paid,
                "payment_date": (
                    fields.Date.today()
                    if new_amount_paid >= cotisation.amount_due
                    else cotisation.payment_date
                ),
            }
        )

        # Mettre à jour le statut de la cotisation
        cotisation._update_payment_status()

        return payment

    def _post_allocation_message(self, allocated_amount, allocation_details):
        """Poste un message de suivi de l'allocation"""
        if not allocation_details:
            return

        message_body = f"""
        <div class="o_installment_allocation">
            <h4>💰 Échéance payée - Impact sur cotisations</h4>
            <p><strong>Échéance:</strong> {self.name} ({self.amount:.2f} {self.currency_id.symbol})</p>
            <p><strong>Montant réparti:</strong> {allocated_amount:.2f} {self.currency_id.symbol}</p>
            <h5>📋 Répartition:</h5>
            <ul>
                {''.join(f'<li>{detail[2:]}</li>' for detail in allocation_details)}
            </ul>
        </div>
        """

        self.message_post(
            body=message_body,
            subject="Paiement d'échéance - Répartition cotisations",
            message_type="notification",
        )

        # Aussi poster sur le membre
        if self.member_id:
            self.member_id.message_post(
                body=message_body,
                subject=f"Paiement échéance {self.name}",
                message_type="notification",
            )

    def action_view_linked_cotisations(self):
        """Action pour voir les cotisations liées"""
        return {
            "name": f"Cotisations liées - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "member.cotisation",
            "view_mode": "tree,form",
            "domain": [("id", "in", self.cotisation_ids.ids)],
            "context": {"default_member_id": self.member_id.id},
        }

    def action_configure_allocation(self):
        """Action pour configurer la répartition"""
        return {
            "name": "Configuration de répartition",
            "type": "ir.actions.act_window",
            "res_model": "installment.allocation.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_installment_id": self.id,
                "default_member_id": self.member_id.id,
            },
        }

    def action_manual_allocation(self):
        """Action pour répartition manuelle"""
        return {
            "name": "Répartition manuelle",
            "type": "ir.actions.act_window",
            "res_model": "manual.allocation.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_installment_id": self.id,
                "default_available_amount": self.amount_paid,
            },
        }

    @api.depends("payment_plan_id", "payment_plan_id.currency_id")
    def _compute_currency_id(self):
        """Calcule la devise à partir du plan de paiement"""
        for installment in self:
            if installment.payment_plan_id and installment.payment_plan_id.currency_id:
                installment.currency_id = installment.payment_plan_id.currency_id
            else:
                installment.currency_id = self.env.company.currency_id

    @api.depends("payment_plan_id", "payment_plan_id.member_id")
    def _compute_member_id(self):
        """Calcule le membre à partir du plan de paiement"""
        for installment in self:
            if installment.payment_plan_id and installment.payment_plan_id.member_id:
                installment.member_id = installment.payment_plan_id.member_id
            else:
                installment.member_id = False

    @api.depends("amount", "amount_paid")
    def _compute_remaining_amount(self):
        """Calcule le montant restant à payer"""
        for installment in self:
            installment.remaining_amount = installment.amount - installment.amount_paid

    @api.depends("due_date", "state")
    def _compute_days_overdue(self):
        """Calcule le nombre de jours de retard"""
        today = fields.Date.today()
        for installment in self:
            if (installment.state in ["pending", "partial"] and installment.due_date < today):
                installment.days_overdue = (today - installment.due_date).days
            else:
                installment.days_overdue = 0

    @api.model_create_multi
    def create(self, vals_list):
        """Surcharge create pour s'assurer de la cohérence des données"""
        for vals in vals_list:
            # S'assurer que payment_plan_id est bien défini
            if not vals.get("payment_plan_id"):
                raise UserError(
                    "Un plan de paiement doit être spécifié pour chaque échéance."
                )

        return super().create(vals_list)

    def write(self, vals):
        """Surcharge write pour validation"""
        # Empêcher la modification des échéances payées
        if "amount_paid" in vals or "state" in vals:
            for installment in self:
                if installment.state == "paid" and not self.env.user.has_group(
                    "base.group_system"
                ):
                    raise UserError("Impossible de modifier une échéance déjà payée.")

        result = super().write(vals)

        # Recalculer les statistiques du plan parent si nécessaire
        if any(field in vals for field in ["state", "amount_paid"]):
            plans = self.mapped("payment_plan_id")
            if plans:
                plans._compute_stats()

        return result

    @api.model
    def _cron_update_installment_status(self):
        """Met à jour automatiquement le statut des échéances"""
        today = fields.Date.today()

        # Marquer comme en retard les échéances non payées dépassées
        overdue_installments = self.search(
            [("state", "=", "pending"), ("due_date", "<", today)]
        )

        if overdue_installments:
            overdue_installments.write({"state": "overdue"})
            _logger.info(
                f"Marqué {len(overdue_installments)} échéances comme en retard"
            )

        # Vérifier si des plans sont terminés
        plans_to_check = overdue_installments.mapped("payment_plan_id")
        for plan in plans_to_check:
            if plan.exists() and all(i.state == "paid" for i in plan.installment_ids):
                plan.action_complete()

    def action_mark_paid(self):
        """Marque l'échéance comme payée"""
        self.ensure_one()

        if self.state == "paid":
            raise UserError("Cette échéance est déjà marquée comme payée.")

        self.write(
            {
                "amount_paid": self.amount,
                "payment_date": fields.Date.today(),
                "state": "paid",
            }
        )

        # Vérifier si le plan est terminé
        if self.payment_plan_id.exists():
            paid_installments = self.payment_plan_id.installment_ids.filtered(
                lambda x: x.state == "paid"
            )
            if len(paid_installments) == len(self.payment_plan_id.installment_ids):
                self.payment_plan_id.action_complete()
        
        self._allocate_payment_to_cotisations(self.amount)

        return True

    def action_partial_payment(self, amount):
        """Enregistre un paiement partiel"""
        self.ensure_one()

        if amount <= 0:
            raise UserError("Le montant du paiement doit être positif.")

        if amount > self.remaining_amount:
            raise UserError(
                "Le montant du paiement ne peut pas dépasser le montant restant dû."
            )

        new_amount_paid = self.amount_paid + amount
        new_state = "paid" if new_amount_paid >= self.amount else "partial"

        self.write(
            {
                "amount_paid": new_amount_paid,
                "state": new_state,
                "payment_date": (
                    fields.Date.today() if new_state == "paid" else self.payment_date
                ),
            }
        )
        # Répartir le montant partiel sur les cotisations
        self._allocate_payment_to_cotisations(amount)
        return True

    def action_cancel(self):
        """Annule l'échéance"""
        self.ensure_one()

        if self.state == "paid":
            raise UserError("Impossible d'annuler une échéance déjà payée.")

        self.write({"state": "cancelled"})
        return True

    @api.constrains("amount", "amount_paid")
    def _check_amounts(self):
        """Vérifie la cohérence des montants"""
        for installment in self:
            if installment.amount <= 0:
                raise ValidationError("Le montant dû doit être positif.")

            if installment.amount_paid < 0:
                raise ValidationError("Le montant payé ne peut pas être négatif.")

            if installment.amount_paid > installment.amount:
                raise ValidationError(
                    "Le montant payé ne peut pas dépasser le montant dû."
                )

    @api.constrains("due_date")
    def _check_due_date(self):
        """Vérifie que la date d'échéance est cohérente"""
        for installment in self:
            if installment.due_date and installment.payment_plan_id:
                plan = installment.payment_plan_id
                if plan.start_date and installment.due_date < plan.start_date:
                    raise ValidationError(
                        "La date d'échéance ne peut pas être antérieure à la date de début du plan."
                    )

    def name_get(self):
        """Personnalise l'affichage du nom"""
        result = []
        for installment in self:
            name = f"Échéance {installment.sequence} - {installment.due_date}"
            if installment.member_id:
                name = f"{installment.member_id.name} - {name}"
            result.append((installment.id, name))
        return result
