# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class BatchCotisationLinkWizard(models.TransientModel):
    """Assistant pour lier plusieurs échéances aux cotisations en lot"""

    _name = "batch.cotisation.link.wizard"
    _description = "Configuration en lot des liens cotisations"

    member_id = fields.Many2one(
        "res.partner", string="Membre", required=True, readonly=True
    )

    installment_ids = fields.Many2many(
        "member.payment.installment", string="Échéances", required=True
    )

    available_cotisations = fields.Many2many(
        "member.cotisation",
        "batch_wizard_cotisation_rel",
        string="Cotisations disponibles",
        compute="_compute_available_cotisations",
    )

    selected_cotisations = fields.Many2many(
        "member.cotisation", "batch_wizard_selected_rel", string="Cotisations à lier"
    )

    allocation_method = fields.Selection(
        [
            ("auto", "Répartition automatique"),
            ("oldest_first", "Plus anciennes d'abord"),
            ("amount_priority", "Par montant (plus élevé d'abord)"),
            ("manual", "Répartition manuelle"),
        ],
        string="Méthode de répartition",
        required=True,
        default="auto",
    )

    link_strategy = fields.Selection(
        [
            ("all_to_all", "Toutes les échéances → Toutes les cotisations"),
            ("one_to_one", "Une échéance → Une cotisation"),
            ("custom", "Configuration personnalisée"),
        ],
        string="Stratégie de liaison",
        default="all_to_all",
        required=True,
    )

    auto_allocate = fields.Boolean(
        string="Allocation automatique future",
        default=True,
        help="Les futures échéances du membre utiliseront cette configuration",
    )

    # Statistiques
    total_installments_amount = fields.Monetary(
        string="Total échéances",
        compute="_compute_totals",
        currency_field="currency_id",
    )

    total_cotisations_due = fields.Monetary(
        string="Total cotisations dues",
        compute="_compute_totals",
        currency_field="currency_id",
    )

    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id
    )

    @api.depends("member_id")
    def _compute_available_cotisations(self):
        """Calcule les cotisations disponibles pour ce membre"""
        for wizard in self:
            if wizard.member_id:
                cotisations = self.env["member.cotisation"].search(
                    [
                        ("member_id", "=", wizard.member_id.id),
                        ("state", "in", ["pending", "partial", "overdue"]),
                    ]
                )
                wizard.available_cotisations = [(6, 0, cotisations.ids)]
            else:
                wizard.available_cotisations = [(5, 0, 0)]

    @api.depends("installment_ids", "selected_cotisations")
    def _compute_totals(self):
        """Calcule les totaux"""
        for wizard in self:
            wizard.total_installments_amount = sum(
                wizard.installment_ids.mapped("amount")
            )
            wizard.total_cotisations_due = sum(
                (c.amount_due - c.amount_paid) for c in wizard.selected_cotisations
            )

    def action_auto_select_cotisations(self):
        """Sélectionne automatiquement toutes les cotisations non payées"""
        self.selected_cotisations = [(6, 0, self.available_cotisations.ids)]

    def action_apply_links(self):
        """Applique la configuration de liens"""
        self.ensure_one()

        if not self.selected_cotisations:
            raise UserError("Veuillez sélectionner au moins une cotisation.")

        links_created = 0

        if self.link_strategy == "all_to_all":
            # Lier toutes les échéances à toutes les cotisations
            for installment in self.installment_ids:
                installment.write(
                    {
                        "cotisation_ids": [(6, 0, self.selected_cotisations.ids)],
                        "allocation_method": self.allocation_method,
                        "auto_allocate": self.auto_allocate,
                    }
                )
                links_created += len(self.selected_cotisations)

        elif self.link_strategy == "one_to_one":
            # Lier une échéance à une cotisation (par ordre)
            installments = self.installment_ids.sorted("sequence")
            cotisations = self.selected_cotisations.sorted("due_date")

            for i, installment in enumerate(installments):
                if i < len(cotisations):
                    installment.write(
                        {
                            "cotisation_ids": [(6, 0, [cotisations[i].id])],
                            "allocation_method": self.allocation_method,
                            "auto_allocate": self.auto_allocate,
                        }
                    )
                    links_created += 1

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Liens configurés",
                "message": f"{links_created} liens échéance-cotisation configurés avec succès.",
                "type": "success",
            },
        }


class CotisationImpactPreviewWizard(models.TransientModel):
    """Assistant pour prévisualiser l'impact détaillé sur les cotisations"""

    _name = "cotisation.impact.preview.wizard"
    _description = "Aperçu impact cotisations"

    member_id = fields.Many2one(
        "res.partner", string="Membre", required=True, readonly=True
    )

    installment_ids = fields.Many2many(
        "member.payment.installment", string="Échéances", readonly=True
    )

    payment_amount = fields.Monetary(
        string="Montant à payer", currency_field="currency_id", readonly=True
    )

    allocation_method = fields.Selection(
        [
            ("auto", "Répartition automatique"),
            ("oldest_first", "Plus anciennes d'abord"),
            ("amount_priority", "Par montant (plus élevé d'abord)"),
        ],
        string="Méthode",
        readonly=True,
    )

    impact_lines = fields.One2many(
        "cotisation.impact.line",
        "wizard_id",
        string="Détail de l'impact",
        compute="_compute_impact_lines",
    )

    total_impact = fields.Monetary(
        string="Impact total",
        compute="_compute_total_impact",
        currency_field="currency_id",
    )

    currency_id = fields.Many2one(
        "res.currency", default=lambda self: self.env.company.currency_id, readonly=True
    )

    @api.depends("installment_ids", "member_id", "allocation_method")
    def _compute_impact_lines(self):
        """Calcule les lignes d'impact détaillées"""
        for wizard in self:
            lines = []

            # Obtenir toutes les cotisations non payées
            unpaid_cotisations = self.env["member.cotisation"].search(
                [
                    ("member_id", "=", wizard.member_id.id),
                    ("state", "in", ["pending", "partial", "overdue"]),
                ]
            )

            # Pour chaque échéance, simuler l'impact
            for installment in wizard.installment_ids:
                payment_amount = installment.remaining_amount or 0
                impacted_cotisations = self._simulate_detailed_impact(
                    unpaid_cotisations, payment_amount, wizard.allocation_method
                )

                for cotisation_data in impacted_cotisations:
                    lines.append(
                        (
                            0,
                            0,
                            {
                                "installment_id": installment.id,
                                "cotisation_id": cotisation_data["cotisation_id"],
                                "cotisation_name": cotisation_data["cotisation_name"],
                                "cotisation_due": cotisation_data["cotisation_due"],
                                "impact_amount": cotisation_data["impact_amount"],
                                "remaining_after": cotisation_data["remaining_after"],
                            },
                        )
                    )

            wizard.impact_lines = lines

    def _simulate_detailed_impact(self, cotisations, payment_amount, method):
        """Simule l'impact détaillé sur les cotisations"""
        # Trier les cotisations selon la méthode
        if method == "oldest_first":
            sorted_cotisations = cotisations.sorted(
                lambda c: c.due_date or fields.Date.today()
            )
        elif method == "amount_priority":
            sorted_cotisations = cotisations.sorted(
                lambda c: -(c.amount_due - c.amount_paid)
            )
        else:  # auto
            def sort_key(cotisation):
                priority = 0
                if cotisation.state == "overdue":
                    priority += 1000
                elif cotisation.state == "partial":
                    priority += 500
                if cotisation.due_date:
                    days_overdue = (fields.Date.today() - cotisation.due_date).days
                    if days_overdue > 0:
                        priority += days_overdue
                return -priority

            sorted_cotisations = sorted(cotisations, key=sort_key)

        # Simuler la répartition
        results = []
        remaining_payment = payment_amount

        for cotisation in sorted_cotisations:
            if remaining_payment <= 0:
                break

            cotisation_remaining = cotisation.amount_due - cotisation.amount_paid
            if cotisation_remaining > 0:
                impact = min(remaining_payment, cotisation_remaining)
                results.append(
                    {
                        "cotisation_id": cotisation.id,
                        "cotisation_name": cotisation.name,
                        "cotisation_due": cotisation_remaining,
                        "impact_amount": impact,
                        "remaining_after": cotisation_remaining - impact,
                    }
                )
                remaining_payment -= impact

        return results

    @api.depends("impact_lines")
    def _compute_total_impact(self):
        """Calcule l'impact total"""
        for wizard in self:
            wizard.total_impact = sum(wizard.impact_lines.mapped("impact_amount"))


class CotisationImpactLine(models.TransientModel):
    """Ligne de détail d'impact sur cotisation"""

    _name = "cotisation.impact.line"
    _description = "Ligne impact cotisation"

    wizard_id = fields.Many2one(
        "cotisation.impact.preview.wizard", required=True, ondelete="cascade"
    )

    installment_id = fields.Many2one(
        "member.payment.installment", string="Échéance", readonly=True
    )

    cotisation_id = fields.Many2one(
        "member.cotisation", string="Cotisation", readonly=True
    )

    cotisation_name = fields.Char(string="Nom cotisation", readonly=True)

    cotisation_due = fields.Monetary(
        string="Montant dû", currency_field="currency_id", readonly=True
    )

    impact_amount = fields.Monetary(
        string="Impact", currency_field="currency_id", readonly=True
    )

    remaining_after = fields.Monetary(
        string="Restant après", currency_field="currency_id", readonly=True
    )

    currency_id = fields.Many2one(
        "res.currency", related="wizard_id.currency_id", readonly=True
    )


class QuickPaymentWizard(models.TransientModel):
    """Assistant de paiement rapide pour améliorer l'expérience utilisateur"""

    _name = "quick.payment.wizard"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Assistant de paiement rapide"

    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        required=True,
        domain=[("is_company", "=", False)],
    )

    # Champs pour gérer les deux contextes
    context_type = fields.Selection([
        ('cotisation', 'Cotisations'),
        ('installment', 'Échéances'),
        ('mixed', 'Mixte')
    ], string="Type de contexte", default='cotisation')

    cotisation_ids = fields.Many2many(
        "member.cotisation",
        string="Cotisations à payer",
        domain=[("state", "in", ["pending", "partial", "overdue"])],
    )

    installment_ids = fields.Many2many(
        "member.payment.installment",
        string="Échéances à payer",
        domain=[("state", "in", ["pending", "partial"])],
    )

    payment_method = fields.Selection(
        [
            ("cash", "Espèces"),
            ("bank_transfer", "Virement bancaire"),
            ("card", "Carte bancaire"),
            ("mobile", "Paiement mobile"),
            ("check", "Chèque"),
            ("installment", "Écheance"),
            ("other", "Autre"),
        ],
        string="Méthode de paiement",
        default="cash",
        required=True,
    )

    payment_date = fields.Date(
        string="Date de paiement", default=fields.Date.today, required=True
    )

    payment_reference = fields.Char(
        string="Référence de paiement", help="Numéro de transaction, chèque, etc."
    )

    notes = fields.Text(string="Notes")

    # Champs calculés pour l'affichage
    total_amount_due = fields.Monetary(
        string="Montant total dû",
        compute="_compute_payment_totals",
        currency_field="currency_id",
    )

    total_amount_to_pay = fields.Monetary(
        string="Montant à payer",
        compute="_compute_payment_totals",
        currency_field="currency_id",
    )

    currency_id = fields.Many2one(
        "res.currency",
        string="Devise",
        default=lambda self: self.env.company.currency_id,
    )

    # Options de paiement
    pay_all = fields.Boolean(
        string="Payer intégralement", default=True
    )

    partial_payment = fields.Boolean(string="Paiement partiel", default=False)

    custom_amount = fields.Monetary(
        string="Montant personnalisé",
        currency_field="currency_id",
        help="Montant à répartir",
    )

    # Statistiques pour affichage
    overdue_count = fields.Integer(
        string="En retard", compute="_compute_payment_stats"
    )

    pending_count = fields.Integer(
        string="En attente", compute="_compute_payment_stats"
    )

    partial_count = fields.Integer(
        string="Partielles", compute="_compute_payment_stats"
    )

    # Nouvelles options pour la gestion des liens
    impact_cotisations = fields.Boolean(
        string="Impacter les cotisations",
        default=True,
        help="Les paiements d'échéances impacteront automatiquement les cotisations",
    )

    cotisation_allocation_method = fields.Selection(
        [
            ("auto", "Répartition automatique"),
            ("oldest_first", "Plus anciennes d'abord"),
            ("amount_priority", "Par montant (plus élevé d'abord)"),
            ("manual", "Sélection manuelle"),
        ],
        string="Méthode de répartition cotisations",
        default="auto",
        help="Comment répartir les paiements d'échéances sur les cotisations",
    )

    # Aperçu de l'impact sur les cotisations
    cotisation_impact_preview = fields.Html(
        string="Impact sur cotisations", compute="_compute_cotisation_impact_preview"
    )

    @api.depends(
        "context_type",
        "installment_ids",
        "impact_cotisations",
        "cotisation_allocation_method",
    )
    def _compute_cotisation_impact_preview(self):
        """Calcule l'aperçu de l'impact sur les cotisations"""
        for wizard in self:
            if not wizard.impact_cotisations or wizard.context_type not in [
                "installment",
                "mixed",
            ]:
                wizard.cotisation_impact_preview = ""
                continue

            if not wizard.installment_ids:
                wizard.cotisation_impact_preview = ""
                continue

            preview_html = "<div class='o_cotisation_impact_preview'>"
            preview_html += "<h5>🔄 Impact sur les cotisations</h5>"

            # Simuler l'impact pour chaque échéance
            total_impact = 0
            cotisations_impacted = set()

            preview_html += "<table class='table table-sm'>"
            preview_html += "<thead><tr><th>Échéance</th><th>Montant</th><th>Cotisations impactées</th></tr></thead>"
            preview_html += "<tbody>"

            for installment in wizard.installment_ids[:3]:  # Limiter l'aperçu
                payment_amount = (
                    installment.remaining_amount or 0
                    if wizard.pay_all
                    else min(
                        installment.remaining_amount or 0,
                        wizard.custom_amount / len(wizard.installment_ids) if wizard.installment_ids else 0,
                    )
                )

                # Simuler quelles cotisations seraient impactées
                impacted_cotisations = wizard._simulate_cotisation_impact(
                    installment, payment_amount
                )

                cotisations_impacted.update([c["id"] for c in impacted_cotisations])
                total_impact += payment_amount

                preview_html += f"<tr>"
                preview_html += f"<td>Échéance {installment.sequence or 'N/A'}</td>"
                preview_html += f"<td>{payment_amount:.2f}</td>"
                preview_html += f"<td>{len(impacted_cotisations)} cotisation(s)</td>"
                preview_html += f"</tr>"

            if len(wizard.installment_ids) > 3:
                preview_html += f"<tr><td colspan='3'><em>... et {len(wizard.installment_ids) - 3} autres échéances</em></td></tr>"

            preview_html += "</tbody></table>"

            preview_html += f"<div class='alert alert-info'>"
            preview_html += f"<strong>Total:</strong> {total_impact:.2f} {wizard.currency_id.symbol} sur {len(cotisations_impacted)} cotisations distinctes"
            preview_html += f"</div>"

            preview_html += "</div>"
            wizard.cotisation_impact_preview = preview_html

    def _simulate_cotisation_impact(self, installment, payment_amount):
        """Simule quelles cotisations seraient impactées par un paiement d'échéance"""
        if not self.member_id or payment_amount <= 0:
            return []

        # Simuler la logique de sélection automatique des cotisations
        unpaid_cotisations = self.env["member.cotisation"].search(
            [
                ("member_id", "=", self.member_id.id),
                ("state", "in", ["pending", "partial", "overdue"]),
            ]
        )

        # Appliquer la méthode de tri
        if self.cotisation_allocation_method == "oldest_first":
            sorted_cotisations = unpaid_cotisations.sorted(
                lambda c: c.due_date or fields.Date.today()
            )
        elif self.cotisation_allocation_method == "amount_priority":
            sorted_cotisations = unpaid_cotisations.sorted(
                lambda c: -(c.amount_due - c.amount_paid)
            )
        else:  # auto
            def sort_key(cotisation):
                priority = 0
                if cotisation.state == "overdue":
                    priority += 1000
                elif cotisation.state == "partial":
                    priority += 500
                if cotisation.due_date:
                    days_overdue = (fields.Date.today() - cotisation.due_date).days
                    if days_overdue > 0:
                        priority += days_overdue
                return -priority

            sorted_cotisations = sorted(unpaid_cotisations, key=sort_key)

        # Simuler la répartition
        impacted = []
        remaining = payment_amount

        for cotisation in sorted_cotisations:
            if remaining <= 0:
                break

            cotisation_remaining = cotisation.amount_due - cotisation.amount_paid
            if cotisation_remaining > 0:
                impact_amount = min(remaining, cotisation_remaining)
                impacted.append(
                    {
                        "id": cotisation.id,
                        "name": cotisation.name,
                        "amount": impact_amount,
                    }
                )
                remaining -= impact_amount

        return impacted

    def _process_installment_payment(self, installment, amount):
        """Traite le paiement d'une échéance"""
        # Cette méthode doit être implémentée selon votre logique métier
        # Exemple de base :
        installment.write({
            'amount_paid': (installment.amount_paid or 0) + amount,
        })
        if hasattr(installment, '_update_state'):
            installment._update_state()

        # Si impact sur cotisations activé, configurer l'échéance
        if self.impact_cotisations:
            # Configurer la méthode d'allocation
            installment.write(
                {
                    "allocation_method": self.cotisation_allocation_method,
                    "auto_allocate": True,
                }
            )

            # Déclencher la répartition sur les cotisations
            if hasattr(installment, '_allocate_payment_to_cotisations'):
                installment._allocate_payment_to_cotisations(amount)

    def action_configure_cotisation_links(self):
        """Action pour configurer les liens avec les cotisations"""
        if self.context_type not in ["installment", "mixed"]:
            raise UserError("Cette action n'est disponible que pour les échéances.")

        return {
            "name": "Configuration des liens cotisations",
            "type": "ir.actions.act_window",
            "res_model": "batch.cotisation.link.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_member_id": self.member_id.id,
                "default_installment_ids": [(6, 0, self.installment_ids.ids)],
                "default_allocation_method": self.cotisation_allocation_method,
            },
        }

    def action_preview_detailed_impact(self):
        """Action pour voir un aperçu détaillé de l'impact"""
        return {
            "name": "Aperçu détaillé de l'impact",
            "type": "ir.actions.act_window",
            "res_model": "cotisation.impact.preview.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_member_id": self.member_id.id,
                "default_installment_ids": [(6, 0, self.installment_ids.ids)],
                "default_payment_amount": (
                    self.custom_amount
                    if self.partial_payment
                    else self.total_amount_to_pay
                ),
                "default_allocation_method": self.cotisation_allocation_method,
            },
        }

    @api.depends("cotisation_ids", "installment_ids", "context_type")
    def _compute_payment_totals(self):
        """Calcule les totaux de paiement"""
        for wizard in self:
            total_due = 0.0
            total_remaining = 0.0

            if wizard.context_type in ['cotisation', 'mixed']:
                for cotisation in wizard.cotisation_ids:
                    total_due += cotisation.amount_due or 0.0
                    total_remaining += (cotisation.amount_due - cotisation.amount_paid) or 0.0

            if wizard.context_type in ['installment', 'mixed']:
                for installment in wizard.installment_ids:
                    total_due += installment.amount or 0.0
                    total_remaining += ((installment.amount or 0.0) - (installment.amount_paid or 0.0))

            wizard.total_amount_due = total_due
            wizard.total_amount_to_pay = total_remaining

    @api.depends("cotisation_ids", "installment_ids", "context_type")
    def _compute_payment_stats(self):
        """Calcule les statistiques des paiements"""
        for wizard in self:
            overdue = pending = partial = 0

            if wizard.context_type in ['cotisation', 'mixed']:
                overdue += len(wizard.cotisation_ids.filtered(lambda c: c.state == "overdue"))
                pending += len(wizard.cotisation_ids.filtered(lambda c: c.state == "pending"))
                partial += len(wizard.cotisation_ids.filtered(lambda c: c.state == "partial"))

            if wizard.context_type in ['installment', 'mixed']:
                overdue += len(wizard.installment_ids.filtered(lambda i: i.state == "overdue"))
                pending += len(wizard.installment_ids.filtered(lambda i: i.state == "pending"))
                partial += len(wizard.installment_ids.filtered(lambda i: i.state == "partial"))

            wizard.overdue_count = overdue
            wizard.pending_count = pending
            wizard.partial_count = partial

    @api.onchange("partial_payment")
    def _onchange_partial_payment(self):
        """Met à jour les options quand on change le mode de paiement"""
        if self.partial_payment:
            self.pay_all = False
            if not self.custom_amount:
                self.custom_amount = self.total_amount_to_pay
        else:
            self.pay_all = True
            self.custom_amount = 0.0

    @api.onchange("pay_all")
    def _onchange_pay_all(self):
        """Met à jour les options selon le mode de paiement complet"""
        if self.pay_all:
            self.partial_payment = False
            self.custom_amount = 0.0

    def action_process_payment(self):
        """Traite le paiement"""
        self.ensure_one()

        if not self.cotisation_ids and not self.installment_ids:
            raise UserError("Aucun élément sélectionné pour le paiement.")

        if self.partial_payment and self.custom_amount <= 0:
            raise UserError("Le montant personnalisé doit être supérieur à 0.")

        try:
            payments_created = []

            # Traiter les cotisations
            if self.cotisation_ids:
                payments_created.extend(self._process_cotisation_payments())

            # Traiter les échéances
            if self.installment_ids:
                payments_created.extend(self._process_installment_payments())

            # Mise à jour des statistiques du membre
            if hasattr(self.member_id, '_compute_payment_status'):
                self.member_id._compute_payment_status()

            # Création du message de suivi
            self._create_payment_message(payments_created)

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Paiement enregistré",
                    "message": f"Paiement de {len(payments_created)} élément(s) enregistré avec succès.",
                    "type": "success",
                    "sticky": False,
                },
            }

        except Exception as e:
            _logger.error(f"Erreur lors du traitement du paiement: {e}")
            raise UserError(f"Erreur lors du traitement du paiement: {e}")

    def _process_cotisation_payments(self):
        """Traite les paiements de cotisations"""
        payments_created = []

        if self.pay_all:
            # Paiement intégral de toutes les cotisations
            for cotisation in self.cotisation_ids:
                remaining = cotisation.amount_due - cotisation.amount_paid
                if remaining > 0:
                    payment = self._create_payment_record(cotisation, remaining)
                    payments_created.append(payment)
                    if hasattr(cotisation, '_update_payment_status'):
                        cotisation._update_payment_status()
        elif self.partial_payment:
            # Répartition du montant personnalisé
            payments_created.extend(self._process_partial_cotisation_payment())

        return payments_created

    def _process_installment_payments(self):
        """Traite les paiements d'échéances"""
        payments_created = []

        if self.pay_all:
            for installment in self.installment_ids:
                remaining = (installment.amount or 0.0) - (installment.amount_paid or 0.0)
                if remaining > 0:
                    self._process_installment_payment(installment, remaining)
                    payments_created.append({'installment': installment, 'amount': remaining})
        elif self.partial_payment:
            # Répartition proportionnelle
            total_remaining = sum((i.amount or 0) - (i.amount_paid or 0) for i in self.installment_ids)
            if total_remaining > 0:
                for installment in self.installment_ids:
                    remaining = (installment.amount or 0) - (installment.amount_paid or 0)
                    if remaining > 0:
                        proportion = remaining / total_remaining
                        payment_amount = self.custom_amount * proportion
                        if payment_amount > 0:
                            self._process_installment_payment(installment, payment_amount)
                            payments_created.append({'installment': installment, 'amount': payment_amount})

        return payments_created

    def _process_partial_cotisation_payment(self):
        """Traite un paiement partiel en répartissant le montant"""
        payments_created = []
        remaining_amount = self.custom_amount

        # Trier les cotisations par priorité (retard d'abord)
        cotisations_sorted = self.cotisation_ids.sorted(
            key=lambda c: (
                c.state == "overdue" and -getattr(c, 'days_overdue', 0) or 0,
                c.state == "partial" and -(c.amount_due - c.amount_paid) or 0,
                c.due_date or fields.Date.today(),
            )
        )

        for cotisation in cotisations_sorted:
            if remaining_amount <= 0:
                break

            remaining = cotisation.amount_due - cotisation.amount_paid
            if remaining > 0:
                payment_amount = min(remaining, remaining_amount)
                payment = self._create_payment_record(cotisation, payment_amount)
                payments_created.append(payment)
                remaining_amount -= payment_amount
                if hasattr(cotisation, '_update_payment_status'):
                    cotisation._update_payment_status()

        return payments_created

    def _create_payment_record(self, cotisation, amount):
        """Crée un enregistrement de paiement"""
        payment_vals = {
            "cotisation_id": cotisation.id,
            "member_id": self.member_id.id,
            "amount": amount,
            "payment_date": self.payment_date,
            "payment_method": self.payment_method,
            "reference": self.payment_reference or f"PAY-{cotisation.display_name}",
            "notes": self.notes,
            "currency_id": self.currency_id.id,
        }

        # Créer l'enregistrement de paiement
        payment = self.env["cotisation.payment"].create(payment_vals)

        # Mettre à jour la cotisation
        new_paid_amount = cotisation.amount_paid + amount
        cotisation.write(
            {
                "amount_paid": new_paid_amount,
                "payment_date": (
                    self.payment_date
                    if new_paid_amount >= cotisation.amount_due
                    else cotisation.payment_date
                ),
            }
        )

        return payment

    def _create_payment_message(self, payments):
        """Crée un message de suivi pour le paiement"""
        if not payments:
            return

        # Calculer le total selon le type de paiements
        total_paid = 0
        for payment in payments:
            if hasattr(payment, 'amount'):
                total_paid += payment.amount
            elif isinstance(payment, dict) and 'amount' in payment:
                total_paid += payment['amount']

        message_body = f"""
        <p><strong>Paiement enregistré</strong></p>
        <ul>
            <li>Montant total: {total_paid:.2f} {self.currency_id.symbol}</li>
            <li>Méthode: {dict(self._fields['payment_method'].selection)[self.payment_method]}</li>
            <li>Date: {self.payment_date}</li>
            <li>Éléments payés: {len(payments)}</li>
        </ul>
        """

        if self.payment_reference:
            message_body += f"<p>Référence: {self.payment_reference}</p>"

        if self.notes:
            message_body += f"<p>Notes: {self.notes}</p>"

        self.member_id.message_post(
            body=message_body,
            subject="Paiement enregistré",
            message_type="notification",
        )

    def action_cancel(self):
        """Annule l'assistant de paiement"""
        return {"type": "ir.actions.act_window_close"}

    def action_view_member_cotisations(self):
        """Ouvre la vue des cotisations du membre"""
        return {
            "name": f"Cotisations de {self.member_id.name}",
            "type": "ir.actions.act_window",
            "res_model": "member.cotisation",
            "view_mode": "tree,form",
            "domain": [("member_id", "=", self.member_id.id)],
            "context": {"default_member_id": self.member_id.id},
            "target": "current",
        }


class InstallmentAllocationWizard(models.TransientModel):
    """Assistant pour configurer la répartition des échéances sur cotisations"""

    _name = "installment.allocation.wizard"
    _description = "Configuration de répartition échéance"

    installment_id = fields.Many2one(
        "member.payment.installment", string="Échéance", required=True, readonly=True
    )

    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        related="installment_id.member_id",
        readonly=True,
    )

    available_cotisations = fields.Many2many(
        "member.cotisation",
        "wizard_cotisation_rel",
        string="Cotisations disponibles",
        domain="[('member_id', '=', member_id), ('state', 'in', ['pending', 'partial', 'overdue'])]",
    )

    selected_cotisations = fields.Many2many(
        "member.cotisation",
        "wizard_selected_cotisation_rel",
        string="Cotisations sélectionnées",
    )

    allocation_method = fields.Selection(
        [
            ("auto", "Répartition automatique"),
            ("manual", "Répartition manuelle"),
            ("oldest_first", "Plus anciennes d'abord"),
            ("amount_priority", "Par montant (plus élevé d'abord)"),
        ],
        string="Méthode de répartition",
        required=True,
        default="auto",
    )

    auto_allocate = fields.Boolean(
        string="Toujours répartir automatiquement",
        default=True,
        help="Pour les futurs paiements de cette échéance",
    )

    def cleanup_allocation_wizards(self):
        """Cleanup wizards older than 24 hours"""
        from datetime import datetime, timedelta
        cutoff_date = datetime.now() - timedelta(days=1)

        models_to_clean = [
            'installment.allocation.wizard',
            'manual.allocation.wizard',
            'batch.cotisation.link.wizard',
            'cotisation.impact.preview.wizard',
            'member.allocation.config.wizard'
        ]

        for model_name in models_to_clean:
            if model_name in self.env:
                records = self.env[model_name].search([
                    ('create_date', '<', cutoff_date.strftime('%Y-%m-%d %H:%M:%S'))
                ])
                if records:
                    records.unlink()
                    _logger.info(f"Nettoyage: {len(records)} enregistrements supprimés du modèle {model_name}")

    @api.onchange("member_id")
    def _onchange_member_id(self):
        """Met à jour les cotisations disponibles"""
        if self.member_id:
            cotisations = self.env["member.cotisation"].search(
                [
                    ("member_id", "=", self.member_id.id),
                    ("state", "in", ["pending", "partial", "overdue"]),
                ]
            )
            self.available_cotisations = [(6, 0, cotisations.ids)]

    def action_configure(self):
        """Applique la configuration"""
        self.ensure_one()

        # Mettre à jour l'échéance
        self.installment_id.write(
            {
                "cotisation_ids": [(6, 0, self.selected_cotisations.ids)],
                "allocation_method": self.allocation_method,
                "auto_allocate": self.auto_allocate,
            }
        )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Configuration sauvegardée",
                "message": f"La répartition a été configurée pour {len(self.selected_cotisations)} cotisations.",
                "type": "success",
            },
        }

    def action_auto_select_all(self):
        """Sélectionne automatiquement toutes les cotisations non payées"""
        if self.available_cotisations:
            self.selected_cotisations = [(6, 0, self.available_cotisations.ids)]


class ManualAllocationWizard(models.TransientModel):
    """Assistant pour répartition manuelle d'un montant sur les cotisations"""

    _name = "manual.allocation.wizard"
    _description = "Répartition manuelle sur cotisations"

    installment_id = fields.Many2one(
        "member.payment.installment", string="Échéance", required=True, readonly=True
    )

    available_amount = fields.Monetary(
        string="Montant disponible", currency_field="currency_id", readonly=True
    )

    allocation_line_ids = fields.One2many(
        "manual.allocation.line", "wizard_id", string="Répartition"
    )

    total_allocated = fields.Monetary(
        string="Total réparti",
        compute="_compute_total_allocated",
        currency_field="currency_id",
    )

    remaining_amount = fields.Monetary(
        string="Montant restant",
        compute="_compute_remaining_amount",
        currency_field="currency_id",
    )

    currency_id = fields.Many2one(
        "res.currency", related="installment_id.currency_id", readonly=True
    )

    @api.depends("allocation_line_ids.amount")
    def _compute_total_allocated(self):
        """Calcule le total réparti"""
        for wizard in self:
            wizard.total_allocated = sum(wizard.allocation_line_ids.mapped("amount"))

    @api.depends("total_allocated", "available_amount")
    def _compute_remaining_amount(self):
        """Calcule le montant restant"""
        for wizard in self:
            wizard.remaining_amount = wizard.available_amount - wizard.total_allocated

    @api.onchange("installment_id")
    def _onchange_installment_id(self):
        """Charge les cotisations liées"""
        if self.installment_id and hasattr(self.installment_id, 'cotisation_ids') and self.installment_id.cotisation_ids:
            lines = []
            for cotisation in self.installment_id.cotisation_ids:
                remaining = cotisation.amount_due - cotisation.amount_paid
                if remaining > 0:
                    suggested_amount = min(remaining, self.available_amount)
                    lines.append(
                        (
                            0,
                            0,
                            {
                                "cotisation_id": cotisation.id,
                                "cotisation_remaining": remaining,
                                "amount": suggested_amount,
                            },
                        )
                    )
            self.allocation_line_ids = lines

    def action_apply_allocation(self):
        """Applique la répartition manuelle"""
        self.ensure_one()

        if self.total_allocated > self.available_amount:
            raise UserError("Le montant total réparti dépasse le montant disponible.")

        # Créer les paiements selon la répartition manuelle
        for line in self.allocation_line_ids.filtered(lambda l: l.amount > 0):
            if hasattr(self.installment_id, '_create_cotisation_payment'):
                self.installment_id._create_cotisation_payment(
                    line.cotisation_id, line.amount
                )

        # Mettre à jour les détails de répartition
        details = [
            f"• {line.cotisation_id.display_name}: {line.amount:.2f} {self.currency_id.symbol}"
            for line in self.allocation_line_ids
            if line.amount > 0
        ]

        if hasattr(self.installment_id, 'allocation_details'):
            self.installment_id.allocation_details = (
                f"Répartition manuelle du {datetime.now().strftime('%d/%m/%Y %H:%M')}:\n"
                + "\n".join(details)
            )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": "Répartition appliquée",
                "message": f"Montant de {self.total_allocated:.2f} {self.currency_id.symbol} réparti sur {len([l for l in self.allocation_line_ids if l.amount > 0])} cotisations.",
                "type": "success",
            },
        }


class ManualAllocationLine(models.TransientModel):
    """Ligne de répartition manuelle"""

    _name = "manual.allocation.line"
    _description = "Ligne de répartition manuelle"

    wizard_id = fields.Many2one(
        "manual.allocation.wizard",
        string="Assistant",
        required=True,
        ondelete="cascade",
    )

    cotisation_id = fields.Many2one(
        "member.cotisation", string="Cotisation", required=True
    )

    cotisation_remaining = fields.Monetary(
        string="Montant dû", currency_field="currency_id", readonly=True
    )

    amount = fields.Monetary(string="Montant à allouer", currency_field="currency_id")

    currency_id = fields.Many2one(
        "res.currency", related="wizard_id.currency_id", readonly=True
    )

    @api.onchange("amount")
    def _onchange_amount(self):
        """Valide le montant saisi"""
        if self.amount > self.cotisation_remaining:
            self.amount = self.cotisation_remaining
            return {
                "warning": {
                    "title": "Montant ajusté",
                    "message": f"Le montant a été ajusté au maximum possible: {self.cotisation_remaining:.2f}",
                }
            }


class CotisationPayment(models.Model):
    """Modèle pour enregistrer les paiements de cotisations"""

    _name = "cotisation.payment"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _description = "Paiement de cotisation"
    _order = "payment_date desc, id desc"

    name = fields.Char(
        string="Référence",
        required=True,
        default=lambda self: self.env["ir.sequence"].next_by_code("cotisation.payment")
        or "PAY-NEW",
    )

    cotisation_id = fields.Many2one(
        "member.cotisation", string="Cotisation", required=True, ondelete="cascade"
    )

    member_id = fields.Many2one(
        "res.partner",
        string="Membre",
        required=True,
        domain=[("is_company", "=", False)],
    )

    amount = fields.Monetary(
        string="Montant payé", required=True, currency_field="currency_id"
    )

    payment_date = fields.Date(
        string="Date de paiement", required=True, default=fields.Date.today
    )

    payment_method = fields.Selection(
        [
            ("cash", "Espèces"),
            ("bank_transfer", "Virement bancaire"),
            ("card", "Carte bancaire"),
            ("mobile", "Paiement mobile"),
            ("check", "Chèque"),
            ("installment", "Écheance"),
            ("other", "Autre"),
        ],
        string="Méthode de paiement",
        required=True,
    )

    reference = fields.Char(
        string="Référence externe", help="Numéro de transaction, chèque, etc."
    )

    notes = fields.Text(string="Notes")

    currency_id = fields.Many2one(
        "res.currency",
        string="Devise",
        default=lambda self: self.env.company.currency_id,
        required=True,
    )

    state = fields.Selection(
        [("draft", "Brouillon"), ("confirmed", "Confirmé"), ("cancelled", "Annulé")],
        string="État",
        default="confirmed",
    )

    # Champs relationnels pour faciliter les rapports
    group_id = fields.Many2one(
        "res.partner", string="Groupe", related="cotisation_id.group_id", store=True
    )

    activity_id = fields.Many2one(
        "group.activity",
        string="Activité",
        related="cotisation_id.activity_id",
        store=True,
    )

    monthly_cotisation_id = fields.Many2one(
        "monthly.cotisation",
        string="Cotisation mensuelle",
        related="cotisation_id.monthly_cotisation_id",
        store=True,
    )

    installment_id = fields.Many2one(
        "member.payment.installment",
        string="Échéance source",
        help="Échéance qui a généré ce paiement",
    )

    is_from_installment = fields.Boolean(
        string="Paiement via échéance",
        compute="_compute_is_from_installment",
        store=True,
    )

    @api.depends("installment_id")
    def _compute_is_from_installment(self):
        """Détermine si le paiement vient d'une échéance"""
        for payment in self:
            payment.is_from_installment = bool(payment.installment_id)

    def action_new_payment(self):
        """Open new payment form"""
        return {
            "type": "ir.actions.act_window",
            "name": "Nouveau paiement",
            "res_model": "cotisation.payment",
            "view_mode": "form",
            "view_type": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_view_all_payments(self):
        """Open payments list view"""
        return {
            "type": "ir.actions.act_window",
            "name": "Tous les paiements",
            "res_model": "cotisation.payment",
            "view_mode": "tree,kanban,form",
            "view_type": "form",
            "target": "current",
            "domain": [],
            "context": self.env.context,
        }

    def action_payment_reminders(self):
        """Open payment reminders wizard"""
        return {
            "type": "ir.actions.act_window",
            "name": "Rappels de paiement",
            "res_model": "payment.reminder.wizard",
            "view_mode": "form",
            "view_type": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_export_report(self):
        """Export payment report"""
        return {
            "type": "ir.actions.report",
            "report_name": "contribution_management.payment_report",
            "report_type": "qweb-pdf",
            "context": self.env.context,
        }

    @api.model
    def create(self, vals):
        """Override create pour générer la référence automatiquement"""
        if not vals.get("name") or vals["name"] == "PAY-NEW":
            vals["name"] = (
                self.env["ir.sequence"].next_by_code("cotisation.payment") or "PAY-NEW"
            )
        return super().create(vals)

    def action_confirm(self):
        """Confirme le paiement"""
        self.ensure_one()
        self.state = "confirmed"

        # Mettre à jour la cotisation
        if self.cotisation_id and hasattr(self.cotisation_id, '_update_payment_status'):
            self.cotisation_id._update_payment_status()

    def action_cancel(self):
        """Annule le paiement"""
        self.ensure_one()
        if self.state == "confirmed":
            # Reverser le paiement sur la cotisation
            new_amount_paid = max(0, self.cotisation_id.amount_paid - self.amount)
            self.cotisation_id.write({"amount_paid": new_amount_paid})
            if hasattr(self.cotisation_id, '_update_payment_status'):
                self.cotisation_id._update_payment_status()

        self.state = "cancelled"

    def unlink(self):
        """Override unlink pour mettre à jour les cotisations"""
        cotisations_to_update = self.mapped("cotisation_id")

        # Reverser les montants avant suppression
        for payment in self.filtered(lambda p: p.state == "confirmed"):
            cotisation = payment.cotisation_id
            new_amount_paid = max(0, cotisation.amount_paid - payment.amount)
            cotisation.write({"amount_paid": new_amount_paid})

        result = super().unlink()

        # Mettre à jour les statuts des cotisations
        if hasattr(cotisations_to_update, '_update_payment_status'):
            cotisations_to_update._update_payment_status()

        return result


class MemberCotisationPaymentUpdate(models.Model):
    """Extension du modèle member.cotisation pour la gestion des paiements"""

    _inherit = "member.cotisation"

    payment_ids = fields.One2many(
        "cotisation.payment", "cotisation_id", string="Paiements"
    )

    payments_count = fields.Integer(
        string="Nombre de paiements", compute="_compute_payments_count"
    )

    @api.depends("payment_ids")
    def _compute_payments_count(self):
        """Calcule le nombre de paiements"""
        for cotisation in self:
            cotisation.payments_count = len(
                cotisation.payment_ids.filtered(lambda p: p.state == "confirmed")
            )

    def _update_payment_status(self):
        """Met à jour le statut de paiement de la cotisation"""
        for cotisation in self:
            confirmed_payments = cotisation.payment_ids.filtered(
                lambda p: p.state == "confirmed"
            )
            total_paid = sum(confirmed_payments.mapped("amount"))

            cotisation.amount_paid = total_paid

            # Déterminer le nouvel état
            if total_paid <= 0:
                new_state = (
                    "overdue"
                    if cotisation.due_date and cotisation.due_date < fields.Date.today()
                    else "pending"
                )
            elif total_paid >= cotisation.amount_due:
                new_state = "paid"
                if not cotisation.payment_date:
                    cotisation.payment_date = fields.Date.today()
            else:
                new_state = "partial"

            cotisation.state = new_state

    def action_view_payments(self):
        """Action pour voir les paiements de la cotisation"""
        self.ensure_one()
        return {
            "name": f"Paiements - {self.name}",
            "type": "ir.actions.act_window",
            "res_model": "cotisation.payment",
            "view_mode": "tree,form",
            "domain": [("cotisation_id", "=", self.id)],
            "context": {
                "default_cotisation_id": self.id,
                "default_member_id": self.member_id.id,
            },
        }

    def action_quick_payment(self):
        """Action pour paiement rapide"""
        self.ensure_one()
        return {
            "name": "Paiement rapide",
            "type": "ir.actions.act_window",
            "res_model": "quick.payment.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_member_id": self.member_id.id,
                "default_cotisation_ids": [(6, 0, [self.id])],
                "default_context_type": "cotisation",
                "quick_mode": True,
            },
        }