# -*- coding: utf-8 -*-

import base64
import logging
import mimetypes
from datetime import datetime, date
from typing import Dict, List, Tuple, Any, Optional

from odoo import http, fields, _, api
from odoo.http import request
from odoo.exceptions import ValidationError, UserError, AccessDenied
from odoo.tools import html_escape
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager

_logger = logging.getLogger(__name__)


class CotisationPaymentController(CustomerPortal):
    """
    Contrôleur pour la gestion des paiements de cotisations en ligne.
    
    Améliorations pour Odoo 17:
    - Meilleure gestion des tokens CSRF
    - Optimisation des requêtes ORM
    - Gestion améliorée des erreurs
    - Validation renforcée des données
    - Support complet Bootstrap 5
    """

    # ================================
    # CONSTANTES ET CONFIGURATION
    # ================================
    
    ALLOWED_FILE_TYPES = [
        'image/jpeg', 'image/png', 'image/gif', 'image/bmp', 'image/webp',
        'application/pdf',
        'application/msword',
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'application/vnd.ms-excel',
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    ]
    
    MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    ITEMS_PER_PAGE = 20

    PAYMENT_METHODS = [
        ('mobile_money', 'Mobile Money'),
        ('bank_transfer', 'Virement bancaire'),
        ('cash', 'Espèces'),
        ('check', 'Chèque'),
        ('card', 'Carte bancaire'),
        ('other', 'Autre')
    ]

    COTISATION_STATES = [
        ('pending', 'En attente'),
        ('partial', 'Partiellement payé'),
        ('paid', 'Payé'),
        ('overdue', 'En retard'),
        ('cancelled', 'Annulé')
    ]

    COTISATION_TYPES = [
        ('monthly', 'Cotisation mensuelle'),
        ('activity', 'Cotisation d\'activité'),
        ('special', 'Cotisation spéciale'),
        ('membership', 'Cotisation d\'adhésion')
    ]

    # ================================
    # MÉTHODES DE PRÉPARATION DES VALEURS
    # ================================

    def _prepare_portal_layout_values(self):
        """Prépare les valeurs pour le layout du portail."""
        values = super()._prepare_portal_layout_values()
        
        if not request.env.user._is_public():
            partner = request.env.user.partner_id
            cotisations_count = request.env['member.cotisation'].search_count([
                ('member_id', '=', partner.id),
                ('active', '=', True)
            ])
            values['cotisations_count'] = cotisations_count
        
        return values

    def _prepare_searchbar_config(self):
        """Prépare la configuration des barres de recherche et filtres."""
        searchbar_sortings = {
            'date': {'label': _('Date d\'échéance'), 'order': 'due_date desc'},
            'name': {'label': _('Description'), 'order': 'description, display_name'},
            'amount': {'label': _('Montant'), 'order': 'amount_due desc'},
            'state': {'label': _('Statut'), 'order': 'state'},
        }
        
        searchbar_filters = {
            'all': {'label': _('Toutes'), 'domain': []},
            'pending': {'label': _('En attente'), 'domain': [('state', '=', 'pending')]},
            'partial': {'label': _('Partielles'), 'domain': [('state', '=', 'partial')]},
            'paid': {'label': _('Payées'), 'domain': [('state', '=', 'paid')]},
            'overdue': {'label': _('En retard'), 'domain': [('state', '=', 'overdue')]},
            'monthly': {'label': _('Mensuelles'), 'domain': [('cotisation_type', '=', 'monthly')]},
            'activity': {'label': _('Activités'), 'domain': [('cotisation_type', '=', 'activity')]},
        }

        searchbar_inputs = {
            'content': {'input': 'content', 'label': _('Recherche dans le contenu')},
            'description': {'input': 'description', 'label': _('Description')},
            'reference': {'input': 'reference', 'label': _('Référence')},
        }

        return searchbar_sortings, searchbar_filters, searchbar_inputs

    # ================================
    # ROUTES PRINCIPALES
    # ================================

    @http.route('/my/cotisations', type='http', auth='user', website=True, csrf=False)
    def my_cotisations_list(self, page=1, date_begin=None, date_end=None, sortby=None, 
                           filterby=None, search=None, search_in='content', **kwargs):
        """
        Affiche la liste des cotisations du membre connecté avec filtres et pagination.
        """
        try:
            partner = self._get_current_partner()
            
            # Configuration des options de tri et filtres
            searchbar_sortings, searchbar_filters, searchbar_inputs = self._prepare_searchbar_config()
            
            # Valeurs par défaut
            sortby = sortby or 'date'
            filterby = filterby or 'all'
            
            # Validation des paramètres
            if sortby not in searchbar_sortings:
                sortby = 'date'
            if filterby not in searchbar_filters:
                filterby = 'all'

            order = searchbar_sortings[sortby]['order']

            # Construction du domaine de recherche
            domain = self._build_cotisations_domain(
                partner.id, filterby, searchbar_filters, 
                date_begin, date_end, search, search_in
            )

            # Pagination
            cotisations_count = request.env['member.cotisation'].search_count(domain)
            pager = portal_pager(
                url="/my/cotisations",
                url_args={
                    'date_begin': date_begin, 'date_end': date_end, 
                    'sortby': sortby, 'filterby': filterby, 
                    'search': search, 'search_in': search_in
                },
                total=cotisations_count,
                page=page,
                step=self.ITEMS_PER_PAGE
            )

            # Récupération des cotisations avec préchargement des relations
            cotisations = request.env['member.cotisation'].search(
                domain, 
                order=order, 
                limit=self.ITEMS_PER_PAGE, 
                offset=pager['offset']
            )

            # Préchargement des données pour optimiser les performances
            if cotisations:
                cotisations.read(['id', 'display_name', 'description', 'state', 'amount_due', 
                               'amount_paid', 'remaining_amount', 'due_date', 'cotisation_type'])

            # Calcul des statistiques
            statistics = self._calculate_cotisations_statistics(partner.id)
            
            # Messages de statut
            success_message = self._get_success_message(kwargs.get('success'))
            error_message = kwargs.get('error')
            
            values = {
                **statistics,
                'cotisations': cotisations,
                'cotisations_count': cotisations_count,
                'partner': partner,
                'page_name': 'cotisations',
                'pager': pager,
                'searchbar_sortings': searchbar_sortings,
                'searchbar_filters': searchbar_filters,
                'searchbar_inputs': searchbar_inputs,
                'sortby': sortby,
                'filterby': filterby,
                'search': search,
                'search_in': search_in,
                'date_begin': date_begin,
                'date_end': date_end,
                'default_url': '/my/cotisations',
                'success_message': success_message,
                'error_message': error_message,
                'current_date': fields.Date.today(),
                'currency_id': request.env.company.currency_id,
            }
            
            return request.render('contribution_management.my_cotisations_list', values)
            
        except AccessDenied:
            return request.render('contribution_management.cotisation_access_denied')
        except Exception as e:
            _logger.error(f"Erreur dans my_cotisations_list: {e}", exc_info=True)
            return request.render('contribution_management.404_custom')

    @http.route('/my/cotisation/<int:cotisation_id>', type='http', auth='user', website=True, csrf=False)
    def cotisation_detail(self, cotisation_id: int, access_token=None, **kwargs):
        """
        Affiche le détail d'une cotisation avec formulaire de paiement.
        """
        try:
            partner = self._get_current_partner()
            cotisation = self._get_cotisation_with_access_check(cotisation_id, partner.id, access_token)
            
            # Récupération des données associées
            payment_proofs = self._get_payment_proofs(cotisation_id)
            payment_history = self._get_payment_history(cotisation_id)
            
            # Messages de statut
            success_message = self._get_success_message(kwargs.get('success'))
            error_message = kwargs.get('error')
            
            values = {
                'cotisation': cotisation,
                'can_pay': self._can_pay_cotisation(cotisation),
                'payment_proofs': payment_proofs,
                'payment_history': payment_history,
                'payment_methods': self.PAYMENT_METHODS,
                'partner': partner,
                'page_name': 'cotisation_detail',
                'success_message': success_message,
                'error_message': error_message,
                'access_token': cotisation.access_token if hasattr(cotisation, 'access_token') else None,
                'bootstrap_formatting': True,
                'current_date': fields.Date.today(),
            }
            
            return request.render('contribution_management.cotisation_detail', values)
            
        except AccessDenied:
            return request.render('contribution_management.cotisation_not_found')
        except Exception as e:
            _logger.error(f"Erreur dans cotisation_detail: {e}", exc_info=True)
            return request.render('contribution_management.404_custom')

    # NOUVELLE ROUTE: Page de paiement séparée (GET)
    @http.route('/my/cotisation/<int:cotisation_id>/pay', 
                type='http', auth='user', website=True, methods=['GET'], csrf=False)
    def cotisation_payment_form(self, cotisation_id: int, access_token=None, **kwargs):
        """
        Affiche le formulaire de paiement pour une cotisation.
        """
        try:
            partner = self._get_current_partner()
            cotisation = self._get_cotisation_with_access_check(cotisation_id, partner.id, access_token)
            
            # Vérifier si la cotisation peut être payée
            if not self._can_pay_cotisation(cotisation):
                return request.redirect(f'/my/cotisation/{cotisation_id}?error=' + 
                                      _('Cette cotisation ne peut plus recevoir de paiements.'))
            
            # Messages de statut
            success_message = self._get_success_message(kwargs.get('success'))
            error_message = kwargs.get('error')
            
            values = {
                'cotisation': cotisation,
                'payment_methods': self.PAYMENT_METHODS,
                'partner': partner,
                'page_name': 'payment_form',
                'success_message': success_message,
                'error_message': error_message,
                'access_token': access_token,
                'max_file_size': self.MAX_FILE_SIZE // (1024 * 1024),  # En MB
                'allowed_file_types': ', '.join([t.split('/')[-1].upper() for t in self.ALLOWED_FILE_TYPES]),
                'current_date': fields.Date.today(),
            }
            
            return request.render('contribution_management.cotisation_payment_form', values)
            
        except AccessDenied:
            return request.render('contribution_management.cotisation_not_found')
        except Exception as e:
            _logger.error(f"Erreur dans cotisation_payment_form: {e}", exc_info=True)
            return request.render('contribution_management.404_custom')

    # ROUTE MODIFIÉE: Soumission de paiement (POST)
    @http.route('/my/cotisation/<int:cotisation_id>/submit_payment', 
                type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def submit_payment(self, cotisation_id: int, access_token=None, **post):
        """
        Traite la soumission d'un justificatif de paiement.
        """
        try:
            partner = self._get_current_partner()
            cotisation = self._get_cotisation_with_access_check(cotisation_id, partner.id, access_token)
            
            # Validation de l'état de la cotisation
            if not self._can_pay_cotisation(cotisation):
                return self._redirect_with_error(cotisation_id, 
                    _('Cette cotisation ne peut plus recevoir de paiements.'))
            
            # Validation et traitement des données
            payment_data = self._validate_payment_data(post, cotisation)
            proof_file_data = None
            
            # Traitement du fichier justificatif (optionnel selon configuration)
            if 'proof_file' in request.httprequest.files:
                proof_file_data = self._process_proof_file(
                    request.httprequest.files.get('proof_file')
                )
            
            # Création du justificatif dans une transaction
            with request.env.cr.savepoint():
                payment_proof = self._create_payment_proof(
                    cotisation, partner, payment_data, proof_file_data
                )
                
                # Mise à jour de la cotisation si nécessaire
                self._update_cotisation_after_payment(cotisation, payment_data['amount'])
            
            # Notifications asynchrones
            self._notify_payment_submission(cotisation, payment_proof)
            
            _logger.info(
                f"Justificatif soumis - Cotisation: {cotisation.display_name}, "
                f"Montant: {payment_data['amount']}, Membre: {partner.name}"
            )
            
            return self._redirect_with_success(cotisation_id, 'payment_submitted')
            
        except (ValidationError, UserError) as e:
            _logger.warning(f"Validation error in submit_payment: {e}")
            return self._redirect_with_error(cotisation_id, str(e))
        except Exception as e:
            _logger.error(f"Erreur dans submit_payment: {e}", exc_info=True)
            return self._redirect_with_error(cotisation_id, 
                _('Une erreur est survenue lors de la soumission. Veuillez réessayer.'))

    @http.route('/my/cotisation/proof/<int:proof_id>/download', 
                type='http', auth='user', csrf=False)
    def download_proof(self, proof_id: int, access_token=None, **kwargs):
        """
        Permet le téléchargement d'un justificatif de paiement.
        """
        try:
            partner = self._get_current_partner()
            proof = self._get_proof_with_access_check(proof_id, partner.id)
            
            return self._create_file_response(proof)
            
        except AccessDenied:
            return request.not_found()
        except Exception as e:
            _logger.error(f"Erreur dans download_proof: {e}", exc_info=True)
            return request.not_found()

    @http.route('/my/cotisations/history', type='http', auth='user', website=True, csrf=False)
    def cotisations_history(self, page=1, sortby=None, filterby=None, **kwargs):
        """
        Affiche l'historique des paiements du membre avec pagination.
        """
        try:
            partner = self._get_current_partner()
            
            # Configuration des options de tri
            searchbar_sortings = {
                'date': {'label': _('Date de soumission'), 'order': 'create_date desc'},
                'amount': {'label': _('Montant'), 'order': 'amount desc'},
                'state': {'label': _('Statut'), 'order': 'state'},
            }
            
            # Configuration des filtres
            searchbar_filters = {
                'all': {'label': _('Tous'), 'domain': []},
                'submitted': {'label': _('Soumis'), 'domain': [('state', '=', 'submitted')]},
                'validated': {'label': _('Validés'), 'domain': [('state', '=', 'validated')]},
                'rejected': {'label': _('Rejetés'), 'domain': [('state', '=', 'rejected')]},
            }

            # Valeurs par défaut
            sortby = sortby or 'date'
            filterby = filterby or 'all'
            
            # Validation des paramètres
            if sortby not in searchbar_sortings:
                sortby = 'date'
            if filterby not in searchbar_filters:
                filterby = 'all'

            order = searchbar_sortings[sortby]['order']

            # Construction du domaine
            domain = [('member_id', '=', partner.id)]
            domain += searchbar_filters[filterby]['domain']

            # Pagination
            payment_proofs_count = request.env['cotisation.payment.proof'].search_count(domain)
            pager = portal_pager(
                url="/my/cotisations/history",
                url_args={'sortby': sortby, 'filterby': filterby},
                total=payment_proofs_count,
                page=page,
                step=self.ITEMS_PER_PAGE
            )

            # Récupération des justificatifs
            payment_proofs = request.env['cotisation.payment.proof'].search(
                domain, order=order, limit=self.ITEMS_PER_PAGE, offset=pager['offset']
            )

            # Calcul des statistiques
            statistics = self._calculate_payment_statistics(partner.id)
            
            values = {
                **statistics,
                'payment_proofs': payment_proofs,
                'partner': partner,
                'page_name': 'payment_history',
                'pager': pager,
                'searchbar_sortings': searchbar_sortings,
                'searchbar_filters': searchbar_filters,
                'sortby': sortby,
                'filterby': filterby,
                'default_url': '/my/cotisations/history',
            }
            
            return request.render('contribution_management.payment_history', values)
            
        except AccessDenied:
            return request.render('contribution_management.cotisation_access_denied')
        except Exception as e:
            _logger.error(f"Erreur dans cotisations_history: {e}", exc_info=True)
            return request.render('contribution_management.404_custom')

    @http.route('/cotisations/public/group/<int:group_id>', 
                type='http', auth='public', website=True, csrf=False)
    def public_group_cotisations(self, group_id: int, **kwargs):
        """
        Affiche les cotisations publiques d'un groupe (si autorisé).
        """
        try:
            group = self._get_public_group(group_id)
            monthly_cotisations = self._get_group_monthly_cotisations(group_id)
            group_stats = self._calculate_group_statistics(group_id)
            
            values = {
                'group': group,
                'monthly_cotisations': monthly_cotisations,
                'group_stats': group_stats,
                'page_name': 'public_cotisations',
            }
            
            return request.render('contribution_management.public_group_cotisations', values)
            
        except AccessDenied:
            return request.render('contribution_management.public_access_denied')
        except Exception as e:
            _logger.error(f"Erreur dans public_group_cotisations: {e}", exc_info=True)
            return request.not_found()

    # ================================
    # ROUTES AJAX / API
    # ================================

    @http.route(['/my/cotisations/history', '/my/cotisations/history/page/<int:page>'], 
                type='http', auth="user", website=True)
    def portal_payment_history(self, page=1, **kw):
        """Historique des paiements"""
        
        partner = request.env.user.partner_id
        PaymentProofSudo = request.env['contribution.payment.proof'].sudo()

        # Récupérer tous les justificatifs de paiement de l'utilisateur
        domain = [('cotisation_id.member_id', '=', partner.id)]
        
        payment_proofs_count = PaymentProofSudo.search_count(domain)

        # Pagination
        pager = portal_pager(
            url="/my/cotisations/history",
            total=payment_proofs_count,
            page=page,
            step=self._items_per_page
        )

        payment_proofs = PaymentProofSudo.search(
            domain, 
            order='create_date desc',
            limit=self._items_per_page, 
            offset=pager['offset']
        )

        # Statistiques
        total_submitted = len(payment_proofs)
        validated_payments = len(payment_proofs.filtered(lambda p: p.state == 'validated'))
        pending_payments = len(payment_proofs.filtered(lambda p: p.state == 'pending'))
        rejected_payments = len(payment_proofs.filtered(lambda p: p.state == 'rejected'))

        values = {
            'payment_proofs': payment_proofs,
            'page_name': 'payment_history',
            'pager': pager,
            'default_url': '/my/cotisations/history',
            'total_submitted': total_submitted,
            'validated_payments': validated_payments,
            'pending_payments': pending_payments,
            'rejected_payments': rejected_payments,
        }

        return request.render("contribution_management.payment_history", values)

    @http.route('/my/cotisation/<int:cotisation_id>/status', 
                type='json', auth='user', methods=['POST'], csrf=True)
    def get_cotisation_status(self, cotisation_id: int, **kwargs):
        """
        API pour récupérer le statut d'une cotisation (AJAX).
        """
        try:
            partner = self._get_current_partner()
            cotisation = self._get_cotisation_with_access_check(cotisation_id, partner.id)
            
            return {
                'success': True,
                'data': {
                    'state': cotisation.state,
                    'remaining_amount': float(cotisation.remaining_amount),
                    'amount_paid': float(cotisation.amount_paid),
                    'can_pay': self._can_pay_cotisation(cotisation),
                    'payment_count': len(cotisation.payment_proof_ids) if hasattr(cotisation, 'payment_proof_ids') else 0,
                }
            }
        except Exception as e:
            return {'success': False, 'error': str(e)}

    @http.route(['/my/cotisation/<int:cotisation_id>'], type='http', auth="user", website=True)
    def portal_cotisation_page(self, cotisation_id, access_token=None, **kw):
        """Page de détail d'une cotisation"""
        
        try:
            cotisation_sudo = self._document_check_access('contribution.member', 
                                                         cotisation_id, access_token)
        except (AccessError, MissingError):
            return request.redirect('/my')

        # Vérifier que la cotisation appartient bien à l'utilisateur
        if cotisation_sudo.member_id.id != request.env.user.partner_id.id:
            return request.render("contribution_management.cotisation_access_denied")

        values = self._cotisation_get_page_view_values(cotisation_sudo, access_token, **kw)
        return request.render("contribution_management.cotisation_detail", values)

    @http.route(['/my/cotisations', '/my/cotisations/page/<int:page>'], 
                type='http', auth="user", website=True)
    def portal_my_cotisations(self, page=1, date_begin=None, date_end=None, 
                             sortby=None, filterby=None, search=None, search_in='content', **kw):
        """Page principale des cotisations"""
        
        partner = request.env.user.partner_id
        CotisationSudo = request.env['contribution.member'].sudo()

        # Domaine de base
        domain = [('member_id', '=', partner.id)]

        # Recherche
        if search and search_in:
            search_domain = []
            if search_in in ('content', 'all'):
                search_domain = ['|', ('description', 'ilike', search), 
                               ('display_name', 'ilike', search)]
            domain += search_domain

        # Filtres
        if filterby:
            if filterby == 'pending':
                domain += [('state', '=', 'pending')]
            elif filterby == 'paid':
                domain += [('state', '=', 'paid')]
            elif filterby == 'partial':
                domain += [('state', '=', 'partial')]
            elif filterby == 'overdue':
                domain += [('state', '=', 'overdue')]
            elif filterby == 'monthly':
                domain += [('cotisation_type', '=', 'monthly')]
            elif filterby == 'activity':
                domain += [('cotisation_type', '=', 'activity')]

        # Filtres par date
        if date_begin and date_end:
            domain += [('due_date', '>=', date_begin), ('due_date', '<=', date_end)]
        elif date_begin:
            domain += [('due_date', '>=', date_begin)]
        elif date_end:
            domain += [('due_date', '<=', date_end)]

        # Options de tri
        searchbar_sortings = {
            'date': {'label': _('Date d\'échéance'), 'order': 'due_date desc'},
            'name': {'label': _('Description'), 'order': 'description'},
            'amount': {'label': _('Montant'), 'order': 'amount_due desc'},
            'state': {'label': _('Statut'), 'order': 'state'},
        }

        if not sortby:
            sortby = 'date'
        order = searchbar_sortings[sortby]['order']

        # Comptage total
        cotisations_count = CotisationSudo.search_count(domain)

        # Pagination
        pager = portal_pager(
            url="/my/cotisations",
            url_args={'date_begin': date_begin, 'date_end': date_end, 
                     'sortby': sortby, 'filterby': filterby, 'search_in': search_in, 'search': search},
            total=cotisations_count,
            page=page,
            step=self._items_per_page
        )

        # Récupération des cotisations
        cotisations = CotisationSudo.search(domain, order=order, 
                                          limit=self._items_per_page, 
                                          offset=pager['offset'])

        # Statistiques du tableau de bord
        dashboard_stats = self._get_dashboard_statistics(partner.id)

        # Barres de recherche et filtres
        searchbar_filters = {
            'all': {'label': _('Toutes'), 'domain': []},
            'pending': {'label': _('En attente'), 'domain': [('state', '=', 'pending')]},
            'paid': {'label': _('Payées'), 'domain': [('state', '=', 'paid')]},
            'partial': {'label': _('Partielles'), 'domain': [('state', '=', 'partial')]},
            'overdue': {'label': _('En retard'), 'domain': [('state', '=', 'overdue')]},
            'monthly': {'label': _('Mensuelles'), 'domain': [('cotisation_type', '=', 'monthly')]},
            'activity': {'label': _('Activités'), 'domain': [('cotisation_type', '=', 'activity')]},
        }

        searchbar_inputs = {
            'content': {'input': 'content', 'label': _('Rechercher dans le contenu')},
            'all': {'input': 'all', 'label': _('Rechercher dans tout')},
        }

        # Préparation des valeurs
        values = {
            'date': date_begin,
            'cotisations': cotisations,
            'page_name': 'cotisation',
            'pager': pager,
            'archive_groups': [],
            'default_url': '/my/cotisations',
            'searchbar_sortings': searchbar_sortings,
            'searchbar_filters': OrderedDict(sorted(searchbar_filters.items())),
            'searchbar_inputs': searchbar_inputs,
            'search_in': search_in,
            'search': search,
            'sortby': sortby,
            'filterby': filterby,
            'cotisations_count': cotisations_count,
            'current_date': fields.Date.today(),
            
            # AJOUT DES STATISTIQUES DU TABLEAU DE BORD
            **dashboard_stats
        }

        return request.render("contribution_management.my_cotisations_list", values)

    # ================================
    # MÉTHODES UTILITAIRES - ACCÈS
    # ================================

    def _prepare_home_portal_values(self, counters):
        """Ajouter le compteur de cotisations sur la page d'accueil du portail"""
        values = super()._prepare_home_portal_values(counters)
        if 'cotisation_count' in counters:
            partner = request.env.user.partner_id
            cotisations = request.env['contribution.member'].search([
                ('member_id', '=', partner.id)
            ])
            values['cotisation_count'] = len(cotisations)
        return values

    def _get_dashboard_statistics(self, partner_id):
        """Calculer les statistiques pour le tableau de bord"""
        # Récupérer les cotisations du partenaire
        cotisations = request.env['contribution.member'].search([
            ('member_id', '=', partner_id)
        ])

        # Calculs de base
        total_cotisations = len(cotisations)
        paid_cotisations = len(cotisations.filtered(lambda c: c.state == 'paid'))
        pending_cotisations = len(cotisations.filtered(lambda c: c.state in ['pending', 'partial', 'overdue']))

        # Calcul du montant total dû (somme des montants restants)
        total_amount_due = sum(cotisations.mapped('remaining_amount'))

        # Récupération de la devise (prendre la première trouvée ou devise par défaut)
        currency_id = cotisations[0].currency_id if cotisations else request.env.company.currency_id

        return {
            'total_cotisations': total_cotisations,
            'paid_cotisations': paid_cotisations,
            'pending_cotisations': pending_cotisations,
            'total_amount_due': total_amount_due,
            'currency_id': currency_id,
        }

    def _cotisation_get_page_view_values(self, cotisation, access_token, **kwargs):
        """Préparer les valeurs pour la vue détail d'une cotisation"""
        values = {
            'cotisation': cotisation,
            'user': request.env.user,
            'can_pay': cotisation.state in ['pending', 'partial', 'overdue'] and cotisation.remaining_amount > 0,
        }
        
        # Ajouter l'historique des paiements validés pour cette cotisation
        payment_history = request.env['contribution.payment.proof'].search([
            ('cotisation_id', '=', cotisation.id),
            ('state', '=', 'validated')
        ], order='validation_date desc')
        
        values['payment_history'] = payment_history
        
        return self._get_page_view_values(
            cotisation, access_token, values,
            'my_cotisations_history', False, **kwargs
        )

    def _get_current_partner(self):
        """Récupère le partenaire actuel avec vérifications."""
        if request.env.user._is_public():
            raise AccessDenied(_("Authentification requise"))
            
        current_user = request.env.user
        partner = current_user.partner_id
        
        if not partner or partner.is_company:
            raise AccessDenied(_("Accès refusé pour ce type d'utilisateur"))
        
        return partner

    def _get_cotisation_with_access_check(self, cotisation_id: int, partner_id: int, access_token=None):
        """Récupère une cotisation avec vérification d'accès."""
        cotisation = request.env['member.cotisation'].sudo().browse(cotisation_id)
        
        if not cotisation.exists():
            raise AccessDenied(_("Cotisation introuvable"))
        
        # Vérification de l'accès par membre ou token
        has_access = cotisation.member_id.id == partner_id
        
        if access_token and hasattr(cotisation, 'access_token'):
            has_access = has_access or (cotisation.access_token == access_token)
        
        if not has_access:
            raise AccessDenied(_("Accès refusé à cette cotisation"))
        
        return cotisation

    def _get_proof_with_access_check(self, proof_id: int, partner_id: int):
        """Récupère un justificatif avec vérification d'accès."""
        proof = request.env['cotisation.payment.proof'].sudo().browse(proof_id)
        
        if not proof.exists():
            raise AccessDenied(_("Justificatif introuvable"))
            
        if proof.member_id.id != partner_id:
            raise AccessDenied(_("Accès refusé à ce justificatif"))
        
        if not proof.proof_file:
            raise AccessDenied(_("Aucun fichier disponible"))
        
        return proof

    def _get_public_group(self, group_id: int):
        """Récupère un groupe pour l'affichage public."""
        group = request.env['res.partner'].sudo().browse(group_id)
        
        if not group.exists() or not group.is_company:
            raise AccessDenied(_("Groupe introuvable"))
        
        if not getattr(group, 'allow_public_cotisation_view', False):
            raise AccessDenied(_("Consultation publique non autorisée pour ce groupe"))
        
        return group

    # ================================
    # MÉTHODES UTILITAIRES - DOMAINES
    # ================================

    def _build_cotisations_domain(self, partner_id, filterby, searchbar_filters, 
                                date_begin, date_end, search, search_in):
        """Construit le domaine de recherche pour les cotisations."""
        # Domaine de base
        domain = [
            ('member_id', '=', partner_id),
            ('active', '=', True)
        ]

        # Application des filtres
        if filterby in searchbar_filters:
            domain += searchbar_filters[filterby]['domain']

        # Filtre par date
        if date_begin and date_end:
            try:
                date_begin = fields.Date.to_date(date_begin)
                date_end = fields.Date.to_date(date_end)
                domain += [('due_date', '>=', date_begin), ('due_date', '<=', date_end)]
            except ValueError:
                _logger.warning(f"Invalid date format: begin={date_begin}, end={date_end}")

        # Recherche
        if search and search_in:
            search_domain = []
            if search_in in ('content', 'description'):
                search_domain = [('description', 'ilike', search)]
            elif search_in == 'reference':
                search_domain = [('name', 'ilike', search)]
            domain += search_domain

        return domain

    # ================================
    # MÉTHODES UTILITAIRES - DONNÉES
    # ================================

    def _get_payment_proofs(self, cotisation_id: int):
        """Récupère les justificatifs de paiement d'une cotisation."""
        return request.env['cotisation.payment.proof'].search([
            ('cotisation_id', '=', cotisation_id)
        ], order='create_date desc')

    def _get_payment_history(self, cotisation_id: int):
        """Récupère l'historique des paiements validés d'une cotisation."""
        return request.env['cotisation.payment.proof'].search([
            ('cotisation_id', '=', cotisation_id),
            ('state', '=', 'validated')
        ], order='validation_date desc')

    def _get_group_monthly_cotisations(self, group_id: int):
        """Récupère les cotisations mensuelles d'un groupe."""
        return request.env['monthly.cotisation'].search([
            ('group_id', '=', group_id),
            ('state', '=', 'active')
        ], order='year desc, month desc', limit=12)

    def _get_success_message(self, success_key):
        """Retourne le message de succès approprié selon la clé."""
        messages = {
            'payment_submitted': _('Votre justificatif de paiement a été soumis avec succès. Il sera validé sous peu par notre équipe.'),
            'payment_updated': _('Votre paiement a été mis à jour avec succès.'),
            'payment_cancelled': _('Votre paiement a été annulé.'),
        }
        return messages.get(success_key)

    # ================================
    # MÉTHODES UTILITAIRES - CALCULS
    # ================================

    def _calculate_cotisations_statistics(self, partner_id):
        """Calcule les statistiques des cotisations pour un membre."""
        # Optimisation: une seule requête pour toutes les stats
        stats = request.env['member.cotisation'].read_group(
            domain=[('member_id', '=', partner_id), ('active', '=', True)],
            fields=['state', 'amount_due', 'amount_paid', 'remaining_amount'],
            groupby=['state']
        )
        
        result = {
            'total_cotisations': 0,
            'paid_cotisations': 0,
            'pending_cotisations': 0,
            'overdue_cotisations': 0,
            'partial_cotisations': 0,
            'total_amount_due': 0.0,
            'total_amount_paid': 0.0,
        }
        
        for stat in stats:
            state = stat['state']
            count = stat['state_count']
            
            result['total_cotisations'] += count
            
            if state == 'paid':
                result['paid_cotisations'] = count
            elif state == 'overdue':
                result['overdue_cotisations'] = count
            elif state == 'partial':
                result['partial_cotisations'] = count
            elif state == 'pending':
                result['pending_cotisations'] = count
            
            result['total_amount_due'] += stat.get('amount_due', 0) or 0
            result['total_amount_paid'] += stat.get('amount_paid', 0) or 0
        
        # Regrouper les cotisations en attente (pending + partial)
        result['pending_cotisations'] += result['partial_cotisations']
        
        return result

    def _calculate_payment_statistics(self, partner_id):
        """Calcule les statistiques des justificatifs pour un membre."""
        stats = request.env['cotisation.payment.proof'].read_group(
            domain=[('member_id', '=', partner_id)],
            fields=['state', 'amount'],
            groupby=['state']
        )
        
        result = {
            'total_submitted': 0,
            'validated_payments': 0,
            'rejected_payments': 0,
            'pending_payments': 0,
            'total_amount_submitted': 0.0,
        }
        
        for stat in stats:
            state = stat['state']
            count = stat['state_count']
            
            result['total_submitted'] += count
            result['total_amount_submitted'] += stat.get('amount', 0) or 0
            
            if state == 'validated':
                result['validated_payments'] = count
            elif state == 'rejected':
                result['rejected_payments'] = count
            elif state == 'submitted':
                result['pending_payments'] = count
        
        return result

    def _calculate_group_statistics(self, group_id: int):
        """Calcule les statistiques publiques d'un groupe."""
        members_count = request.env['res.partner'].search_count([
            ('parent_id', '=', group_id),
            ('is_company', '=', False)
        ])
        
        active_cotisations = request.env['member.cotisation'].search_count([
            ('group_id', '=', group_id),
            ('active', '=', True),
            ('state', 'in', ['pending', 'partial', 'paid'])
        ])
        
        return {
            'members_count': members_count,
            'active_cotisations': active_cotisations,
        }

    def _can_pay_cotisation(self, cotisation):
        """Vérifie si une cotisation peut être payée."""
        return (
            cotisation.active and
            cotisation.state in ['pending', 'partial', 'overdue'] and 
            cotisation.remaining_amount > 0
        )

    def _update_cotisation_after_payment(self, cotisation, amount):
        """Met à jour le statut de la cotisation après un paiement."""
        pass

    # ================================
    # MÉTHODES UTILITAIRES - VALIDATION
    # ================================

    def _validate_payment_data(self, post: Dict[str, Any], cotisation):
        """Valide et nettoie les données de paiement."""
        # Validation du montant
        try:
            amount = float(post.get('amount', 0))
        except (ValueError, TypeError):
            raise ValidationError(_("Le montant doit être un nombre valide"))
        
        if amount <= 0:
            raise ValidationError(_("Le montant doit être positif"))
        
        if amount > cotisation.remaining_amount * 1.1:  # Tolérance 10%
            raise ValidationError(
                _("Le montant ne peut pas dépasser le montant restant de plus de 10%")
            )
        
        # Validation de la méthode de paiement
        payment_method = post.get('payment_method', '').strip()
        if not payment_method:
            raise ValidationError(_("La méthode de paiement est requise"))
        
        allowed_methods = [method[0] for method in self.PAYMENT_METHODS]
        if payment_method not in allowed_methods:
            raise ValidationError(_("Méthode de paiement non autorisée"))
        
        # Validation des autres champs
        reference = post.get('reference', '').strip()
        if len(reference) > 100:
            raise ValidationError(_("La référence ne doit pas dépasser 100 caractères"))
        
        payment_date = post.get('payment_date', '').strip()
        if payment_date:
            try:
                payment_date = fields.Date.to_date(payment_date)
                if payment_date > date.today():
                    raise ValidationError(_("La date de paiement ne peut pas être dans le futur"))
            except ValueError:
                raise ValidationError(_("Format de date invalide"))
        
        return {
            'amount': amount,
            'payment_method': payment_method,
            'reference': reference,
            'payment_date': payment_date or fields.Date.today(),
            'notes': post.get('notes', '').strip(),
        }

    def _process_proof_file(self, file):
        """Traite et valide le fichier justificatif."""
        if not file or not file.filename:
            return None
            
        # Validation du type de fichier
        file_type = mimetypes.guess_type(file.filename)[0]
        if file_type not in self.ALLOWED_FILE_TYPES:
            raise ValidationError(_(
                "Type de fichier non autorisé. Types acceptés: %s"
            ) % ', '.join([t.split('/')[-1] for t in self.ALLOWED_FILE_TYPES]))
        
        # Validation de la taille
        file.seek(0, 2)  # Aller à la fin du fichier
        file_size = file.tell()
        file.seek(0)  # Retour au début
        
        if file_size > self.MAX_FILE_SIZE:
            raise ValidationError(_(
                "La taille du fichier ne doit pas dépasser %sMB"
            ) % (self.MAX_FILE_SIZE // (1024 * 1024)))
        
        if file_size == 0:
            raise ValidationError(_("Le fichier ne peut pas être vide"))
        
        # Lecture du contenu
        try:
            file_content = base64.b64encode(file.read())
        except Exception as e:
            raise ValidationError(_("Erreur lors de la lecture du fichier: %s") % str(e))
        
        return {
            'file_name': file.filename,
            'file_type': file_type,
            'file_content': file_content,
            'file_size': file_size,
        }

    # ================================
    # MÉTHODES UTILITAIRES - CRÉATION
    # ================================

    def _create_payment_proof(self, cotisation, partner, payment_data, proof_file_data=None):
        """Crée un enregistrement de justificatif de paiement."""
        proof_vals = {
            'cotisation_id': cotisation.id,
            'member_id': partner.id,
            'amount': payment_data['amount'],
            'payment_method': payment_data['payment_method'],
            'reference': payment_data['reference'],
            'payment_date': payment_data['payment_date'],
            'notes': payment_data['notes'],
            'state': 'submitted',
        }
        
        if proof_file_data:
            proof_vals.update({
                'proof_file': proof_file_data['file_content'],
                'proof_filename': proof_file_data['file_name'],
                'proof_mimetype': proof_file_data['file_type'],
            })
        
        return request.env['cotisation.payment.proof'].create(proof_vals)

    # ================================
    # MÉTHODES UTILITAIRES - RÉPONSES
    # ================================

    def _create_file_response(self, proof):
        """Crée une réponse HTTP pour télécharger un fichier."""
        try:
            file_content = base64.b64decode(proof.proof_file)
            
            # Nettoyage du nom de fichier pour éviter les problèmes de sécurité
            safe_filename = proof.proof_filename
            if not safe_filename:
                safe_filename = f"justificatif_{proof.id}.pdf"
            
            # Suppression des caractères dangereux du nom de fichier
            import re
            safe_filename = re.sub(r'[^\w\-_\.]', '_', safe_filename)
            
            headers = [
                ('Content-Type', proof.proof_mimetype or 'application/octet-stream'),
                ('Content-Disposition', f'attachment; filename="{safe_filename}"'),
                ('Content-Length', len(file_content)),
                ('Cache-Control', 'no-cache, no-store, must-revalidate'),
                ('Pragma', 'no-cache'),
                ('Expires', '0'),
            ]
            
            return request.make_response(file_content, headers)
            
        except Exception as e:
            _logger.error(f"Erreur lors de la création de la réponse fichier: {e}")
            raise AccessDenied(_("Erreur lors du téléchargement du fichier"))

    def _redirect_with_success(self, cotisation_id, success_key):
        """Redirige vers la page de détail avec un message de succès."""
        return request.redirect(
            f'/my/cotisation/{cotisation_id}?success={success_key}'
        )

    def _redirect_with_error(self, cotisation_id, error_message):
        """Redirige vers la page de détail avec un message d'erreur."""
        # Échapper le message d'erreur pour éviter XSS
        escaped_error = html_escape(str(error_message))
        return request.redirect(
            f'/my/cotisation/{cotisation_id}?error={escaped_error}'
        )

    # ================================
    # MÉTHODES UTILITAIRES - NOTIFICATIONS
    # ================================

    def _notify_payment_submission(self, cotisation, payment_proof):
        """Envoie les notifications après soumission d'un paiement."""
        try:
            # Notification au membre (asynchrone)
            self._send_member_notification(payment_proof)
            
            # Notification aux administrateurs (asynchrone)
            self._send_admin_notification(payment_proof)
            
        except Exception as e:
            # Les notifications ne doivent pas bloquer le processus principal
            _logger.warning(f"Erreur lors de l'envoi des notifications: {e}")

    def _send_member_notification(self, payment_proof):
        """Envoie une notification au membre."""
        try:
            template_member = request.env.ref(
                'contribution_management.email_template_payment_submitted_member',
                raise_if_not_found=False
            )
            if template_member and hasattr(template_member, 'with_delay'):
                template_member.with_delay().send_mail(
                    payment_proof.id, 
                    force_send=True,
                    raise_exception=False
                )
            elif template_member:
                template_member.send_mail(
                    payment_proof.id, 
                    force_send=True,
                    raise_exception=False
                )
        except Exception as e:
            _logger.warning(f"Erreur notification membre: {e}")

    def _send_admin_notification(self, payment_proof):
        """Envoie une notification aux administrateurs."""
        try:
            template_admin = request.env.ref(
                'contribution_management.email_template_payment_submitted_admin',
                raise_if_not_found=False
            )
            if template_admin:
                # Récupération des utilisateurs admin
                admin_group = request.env.ref('base.group_system', raise_if_not_found=False)
                if admin_group:
                    admin_users = admin_group.users.filtered(lambda u: u.partner_id.email)
                    for user in admin_users[:5]:  # Limite à 5 admins
                        template_context = template_admin.with_context(
                            email_to=user.partner_id.email
                        )
                        if hasattr(template_context, 'with_delay'):
                            template_context.with_delay().send_mail(
                                payment_proof.id, 
                                force_send=True,
                                raise_exception=False
                            )
                        else:
                            template_context.send_mail(
                                payment_proof.id, 
                                force_send=True,
                                raise_exception=False
                            )
        except Exception as e:
            _logger.warning(f"Erreur notification admin: {e}")

    # ================================
    # MÉTHODES UTILITAIRES - CACHE ET PERFORMANCE
    # ================================

    @api.model
    def _get_cached_statistics(self, partner_id, cache_key):
        """
        Récupère les statistiques depuis le cache ou les calcule.
        
        Args:
            partner_id: ID du partenaire
            cache_key: Clé de cache
            
        Returns:
            Dictionnaire des statistiques
        """
        # Implémentation simple sans cache pour l'instant
        # Peut être étendue avec un système de cache Redis/Memcached
        if cache_key == 'cotisations':
            return self._calculate_cotisations_statistics(partner_id)
        elif cache_key == 'payments':
            return self._calculate_payment_statistics(partner_id)
        
        return {}

    # ================================
    # MÉTHODES UTILITAIRES - SÉCURITÉ
    # ================================

    def _check_rate_limit(self, partner_id, action_type):
        """
        Vérifie les limites de taux pour éviter les abus.
        
        Args:
            partner_id: ID du partenaire
            action_type: Type d'action (payment_submission, file_download, etc.)
            
        Returns:
            bool: True si l'action est autorisée
        """
        # Implémentation basique - peut être étendue
        # avec un système de rate limiting plus sophistiqué
        
        if action_type == 'payment_submission':
            # Maximum 10 soumissions par heure
            recent_submissions = request.env['cotisation.payment.proof'].search_count([
                ('member_id', '=', partner_id),
                ('create_date', '>=', fields.Datetime.now() - fields.Datetime.delta(hours=1))
            ])
            return recent_submissions < 10
        
        return True

    def _sanitize_input(self, value, max_length=None):
        """
        Nettoie les entrées utilisateur pour éviter les injections.
        
        Args:
            value: Valeur à nettoyer
            max_length: Longueur maximale
            
        Returns:
            Valeur nettoyée
        """
        if not value:
            return ''
        
        # Conversion en string et suppression des espaces
        clean_value = str(value).strip()
        
        # Limitation de la longueur
        if max_length and len(clean_value) > max_length:
            clean_value = clean_value[:max_length]
        
        # Échappement HTML basique
        clean_value = html_escape(clean_value)
        
        return clean_value

    # ================================
    # MÉTHODES UTILITAIRES - LOGGING ET DEBUG
    # ================================

    def _log_user_action(self, action, partner_id, details=None):
        """
        Enregistre les actions utilisateur pour audit.
        
        Args:
            action: Type d'action
            partner_id: ID du partenaire
            details: Détails supplémentaires
        """
        try:
            log_data = {
                'action': action,
                'partner_id': partner_id,
                'user_id': request.env.user.id,
                'ip_address': request.httprequest.remote_addr,
                'user_agent': request.httprequest.headers.get('User-Agent', ''),
                'timestamp': fields.Datetime.now(),
            }
            
            if details:
                log_data.update(details)
            
            _logger.info(f"User Action: {action} by partner {partner_id}", extra=log_data)
            
        except Exception as e:
            _logger.error(f"Erreur lors du logging: {e}")

    # ================================
    # MÉTHODES UTILITAIRES - HELPERS
    # ================================

    def _format_currency(self, amount, currency=None):
        """
        Formate un montant en devise.
        
        Args:
            amount: Montant à formater
            currency: Devise (optionnel)
            
        Returns:
            String formaté
        """
        if currency is None:
            currency = request.env.company.currency_id
        
        return currency.format(amount)

    def _get_user_timezone(self):
        """
        Récupère le fuseau horaire de l'utilisateur.
        
        Returns:
            String du fuseau horaire
        """
        return request.env.user.tz or 'UTC'

    def _convert_to_user_timezone(self, dt):
        """
        Convertit une datetime vers le fuseau horaire de l'utilisateur.
        
        Args:
            dt: Datetime à convertir
            
        Returns:
            Datetime convertie
        """
        if not dt:
            return dt
            
        user_tz = self._get_user_timezone()
        return fields.Datetime.context_timestamp(request.env.user, dt)

    def _paginate_records(self, records, page, items_per_page):
        """
        Pagine une liste d'enregistrements.
        
        Args:
            records: Liste des enregistrements
            page: Numéro de page
            items_per_page: Éléments par page
            
        Returns:
            Tuple (records_page, total_pages, has_next, has_prev)
        """
        total_count = len(records)
        total_pages = (total_count + items_per_page - 1) // items_per_page
        
        start_index = (page - 1) * items_per_page
        end_index = start_index + items_per_page
        
        records_page = records[start_index:end_index]
        
        return (
            records_page,
            total_pages,
            page < total_pages,  # has_next
            page > 1  # has_prev
        )