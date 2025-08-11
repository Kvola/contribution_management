# -*- coding: utf-8 -*-

import json
import base64
from datetime import datetime, timedelta
from odoo import http, fields, _
from odoo.http import request
from odoo.exceptions import ValidationError, UserError, AccessError
from odoo.tools import image_process
import logging

_logger = logging.getLogger(__name__)


class ActivityRegistrationController(http.Controller):
    """Contrôleur pour l'inscription aux activités via le site web"""

    @http.route('/my/cotisation/<int:cotisation_id>/payment/success', 
            type='http', auth='user', website=True)
    def payment_success_page(self, cotisation_id, **kw):
        """Page de confirmation après paiement"""
        try:
            cotisation = request.env['member.cotisation'].sudo().search([
                ('id', '=', cotisation_id),
                ('member_id', '=', request.env.user.partner_id.id)
            ])
            
            if not cotisation:
                return request.redirect('/my/cotisations?error=cotisation_not_found')
            
            values = {
                'cotisation': cotisation,
                'activity': cotisation.activity_id,
                'page_name': 'payment_success',
            }
            
            return request.render('contribution_management.payment_success_template', values)
            
        except Exception as e:
            _logger.error(f"Erreur page succès paiement: {e}")
            return request.redirect('/my/cotisations')

    @http.route(['/activities', '/activities/page/<int:page>'], 
                type='http', auth='public', website=True, sitemap=True)
    def activity_list(self, page=1, search='', group_id=None, state=None, **kw):
        """Page de liste des activités disponibles"""
        
        # Pagination améliorée
        per_page = 12
        offset = (page - 1) * per_page
        
        # Construction du domaine de recherche optimisée
        domain = [
            ('state', 'in', ['confirmed', 'ongoing']),
            ('active', '=', True)
        ]
        
        # Filtre par recherche textuelle amélioré
        if search:
            search_terms = search.strip().split()
            for term in search_terms:
                domain.append('|')
                domain.append(('name', 'ilike', term))
                domain.append(('description', 'ilike', term))
        
        # Filtre par groupe avec validation
        if group_id:
            try:
                group_id = int(group_id)
                # Vérifier que le groupe existe
                group_exists = request.env['res.partner'].sudo().search_count([
                    ('id', '=', group_id),
                    ('is_company', '=', True),
                    ('active', '=', True)
                ])
                if group_exists:
                    domain.append(('group_id', '=', group_id))
            except (ValueError, TypeError):
                pass
        
        # Filtre par état avec validation
        valid_states = ['confirmed', 'ongoing', 'completed']
        if state and state in valid_states:
            domain = [clause for clause in domain if not (isinstance(clause, tuple) and clause[0] == 'state')]
            domain.append(('state', '=', state))
        
        # Récupération des activités avec gestion d'erreur
        try:
            Activity = request.env['group.activity'].sudo()
            total_activities = Activity.search_count(domain)
            activities = Activity.search(domain, 
                                       order='date_start asc nulls last, create_date desc',
                                       limit=per_page, 
                                       offset=offset)
        except Exception as e:
            _logger.error(f"Erreur lors de la récupération des activités: {e}")
            return request.render('website.404')
        
        # Récupération des groupes pour le filtre
        groups = request.env['res.partner'].sudo().search([
            ('is_company', '=', True),
            ('active', '=', True)
        ], order='name asc')
        
        # Pagination optimisée
        total_pages = (total_activities + per_page - 1) // per_page
        pager = request.website.pager(
            url='/activities',
            total=total_activities,
            page=page,
            step=per_page,
            url_args={'search': search, 'group_id': group_id, 'state': state}
        )
        
        # Vérifier les inscriptions utilisateur de manière optimisée
        user_registrations = {}
        user = None
        if not request.env.user._is_public():
            user = request.env.user
            if user.partner_id:
                try:
                    existing_registrations = request.env['member.cotisation'].sudo().search([
                        ('member_id', '=', user.partner_id.id),
                        ('activity_id', 'in', activities.ids),
                        ('active', '=', True)
                    ])
                    user_registrations = {reg.activity_id.id: reg for reg in existing_registrations}
                except Exception as e:
                    _logger.error(f"Erreur récupération inscriptions utilisateur: {e}")
        
        values = {
            'activities': activities,
            'groups': groups,
            'search': search,
            'group_id': int(group_id) if group_id else None,
            'state': state,
            'pager': pager,
            'page': page,
            'total_activities': total_activities,
            'total_pages': total_pages,
            'user_registrations': user_registrations,
            'user': user,
            'page_name': 'activity_list',
            'current_date': fields.Datetime.now(),
        }
        
        return request.render('contribution_management.activity_list_template', values)

    @http.route('/activity/<int:activity_id>', type='http', auth='public', website=True)
    def activity_detail(self, activity_id, **kw):
        """Page de détail d'une activité avec gestion d'erreurs améliorée"""
        
        # Gestion des messages d'erreur/succès via paramètres URL
        error_message = kw.get('error', '')
        success_message = kw.get('success', '')
        
        try:
            activity = request.env['group.activity'].sudo().browse(activity_id)
            if not activity.exists() or not activity.active:
                return request.render('website.404')
            
            # Vérifier les permissions de vue avec messages clairs
            if activity.state not in ['confirmed', 'ongoing', 'completed']:
                if request.env.user._is_public():
                    return request.render('website.404')
                elif activity.state == 'draft':
                    error_message = "Cette activité n'est pas encore confirmée."
                elif activity.state == 'cancelled':
                    error_message = "Cette activité a été annulée."
        
        except (ValueError, TypeError):
            return request.render('website.404')
        except AccessError:
            return request.render('website.403')
        
        # Récupérer les informations utilisateur de manière sécurisée
        user_registration = None
        can_register = False
        registration_message = ""
        
        if not request.env.user._is_public():
            try:
                user = request.env.user
                partner = user.partner_id
                
                # Vérifier l'inscription existante
                existing_registration = request.env['member.cotisation'].sudo().search([
                    ('member_id', '=', partner.id),
                    ('activity_id', '=', activity.id),
                    ('active', '=', True)
                ], limit=1)
                
                if existing_registration:
                    user_registration = existing_registration
                else:
                    # Vérifier l'éligibilité avec gestion d'erreur
                    can_register, registration_message = self._check_registration_eligibility(activity, partner)
                    
            except Exception as e:
                _logger.error(f"Erreur vérification éligibilité utilisateur {request.env.user.id}: {e}")
                registration_message = "Erreur lors de la vérification de votre éligibilité."
        else:
            registration_message = "Vous devez vous connecter pour vous inscrire à cette activité."
        
        # Récupérer les participants avec limitation
        participants = []
        try:
            if activity.state in ['confirmed', 'ongoing', 'completed']:
                participant_cotisations = request.env['member.cotisation'].sudo().search([
                    ('activity_id', '=', activity.id),
                    ('active', '=', True),
                    ('state', '!=', 'cancelled')
                ], limit=50)  # Limitation pour performance
                participants = participant_cotisations.mapped('member_id').filtered('active')
        except Exception as e:
            _logger.error(f"Erreur récupération participants activité {activity_id}: {e}")
        
        values = {
            'activity': activity,
            'user_registration': user_registration,
            'can_register': can_register,
            'registration_message': registration_message,
            'participants': participants,
            'error_message': error_message,
            'success_message': success_message,
            'page_name': 'activity_detail',
            'current_date': fields.Datetime.now(),
        }
        
        return request.render('contribution_management.activity_detail_template', values)

    @http.route('/activity/<int:activity_id>/register', type='http', auth='user', 
                website=True, methods=['GET', 'POST'], csrf=True)
    def activity_register(self, activity_id, **post):
        """Inscription à une activité avec confirmation améliorée"""
        
        try:
            activity = request.env['group.activity'].sudo().browse(activity_id)
            if not activity.exists():
                return request.redirect('/activities?error=activity_not_found')
        except (ValueError, TypeError):
            return request.redirect('/activities?error=invalid_activity')
        except AccessError:
            return request.redirect('/activities?error=access_denied')
        
        user = request.env.user
        partner = user.partner_id
        
        # Vérification complète de l'éligibilité
        try:
            can_register, message = self._check_registration_eligibility(activity, partner)
            
            if not can_register:
                error_code = self._get_error_code(message)
                return request.redirect(f'/activity/{activity_id}?error={error_code}')
        except Exception as e:
            _logger.error(f"Erreur vérification éligibilité: {e}")
            return request.redirect(f'/activity/{activity_id}?error=eligibility_check_failed')
        
        if request.httprequest.method == 'GET':
            # Afficher le formulaire d'inscription avec informations contextuelles
            values = {
                'activity': activity,
                'partner': partner,
                'estimated_total': activity.cotisation_amount,
                'deadline_info': self._get_payment_deadline_info(activity),
                'available_spots': activity.available_spots,
                'page_name': 'activity_register',
            }
            return request.render('contribution_management.activity_register_template', values)
        
        elif request.httprequest.method == 'POST':
            # Traiter l'inscription avec transaction sécurisée
            try:
                # Double vérification avant création
                can_register, message = self._check_registration_eligibility(activity, partner)
                if not can_register:
                    raise ValidationError(message)
                
                # Validation des données avec nettoyage
                registration_data = self._validate_registration_data(post)
                
                # Créer la cotisation dans une transaction
                cotisation_vals = {
                    'member_id': partner.id,
                    'activity_id': activity.id,
                    'cotisation_type': 'activity',
                    'amount_due': activity.cotisation_amount,
                    'due_date': self._calculate_due_date(activity),
                    'currency_id': activity.currency_id.id,
                    'company_id': activity.company_id.id,
                    'description': f"Inscription à l'activité: {activity.name}",
                    'payment_notes': registration_data.get('notes', ''),
                    'state': 'pending',
                }
                
                # Utiliser une transaction pour éviter les doublons
                with request.env.cr.savepoint():
                    # Vérification finale de non-duplication
                    duplicate_check = request.env['member.cotisation'].sudo().search([
                        ('member_id', '=', partner.id),
                        ('activity_id', '=', activity.id),
                        ('active', '=', True)
                    ], limit=1)
                    
                    if duplicate_check:
                        return request.redirect(f'/activity/{activity_id}?error=already_registered')
                    
                    cotisation = request.env['member.cotisation'].sudo().create(cotisation_vals)
                    
                    # Journalisation de l'inscription
                    self._log_registration_activity(cotisation, 'created')
                
                # Actions post-création
                try:
                    # Envoyer confirmation par email
                    self._send_registration_confirmation(cotisation)
                    
                    # Notification aux administrateurs si activité presque pleine
                    if activity.available_spots <= 3:
                        self._notify_admins_activity_filling(activity)
                        
                except Exception as e:
                    _logger.error(f"Erreur notifications post-inscription: {e}")
                
                # Redirection vers confirmation avec message de succès
                return request.redirect(f'/activity/{activity_id}/registration/success?cotisation_id={cotisation.id}')
                
            except ValidationError as e:
                values = {
                    'activity': activity,
                    'partner': partner,
                    'error': str(e),
                    'form_data': post,
                    'page_name': 'activity_register',
                }
                return request.render('contribution_management.activity_register_template', values)
            
            except Exception as e:
                _logger.error(f"Erreur lors de l'inscription à l'activité {activity_id}: {e}")
                return request.redirect(f'/activity/{activity_id}?error=registration_failed')

    @http.route('/activity/<int:activity_id>/registration/success', 
                type='http', auth='user', website=True)
    def registration_success(self, activity_id, cotisation_id=None, **kw):
        """Page de confirmation d'inscription réussie"""
        
        try:
            activity = request.env['group.activity'].sudo().browse(activity_id)
            if not activity.exists():
                return request.redirect('/activities?error=activity_not_found')
            
            cotisation = None
            if cotisation_id:
                cotisation = request.env['member.cotisation'].sudo().search([
                    ('id', '=', int(cotisation_id)),
                    ('member_id', '=', request.env.user.partner_id.id),
                    ('activity_id', '=', activity.id),
                    ('active', '=', True)
                ], limit=1)
            
            # Informations pour la confirmation
            next_steps = self._get_registration_next_steps(activity, cotisation)
            payment_methods = self._get_available_payment_methods()
            
            values = {
                'activity': activity,
                'cotisation': cotisation,
                'next_steps': next_steps,
                'payment_methods': payment_methods,
                'success_message': 'Votre inscription a été confirmée avec succès !',
                'page_name': 'registration_success',
            }
            
            return request.render('contribution_management.registration_success_template', values)
            
        except Exception as e:
            _logger.error(f"Erreur page succès inscription: {e}")
            return request.redirect(f'/activity/{activity_id}')

    @http.route('/activity/<int:activity_id>/cancel_registration', 
                type='http', auth='user', website=True, methods=['POST'], csrf=True)
    def cancel_registration(self, activity_id, **post):
        """Annulation d'une inscription avec confirmation"""
        
        try:
            activity = request.env['group.activity'].sudo().browse(activity_id)
            if not activity.exists():
                return request.redirect('/activities?error=activity_not_found')
            
            partner = request.env.user.partner_id
            
            # Rechercher l'inscription
            registration = request.env['member.cotisation'].sudo().search([
                ('member_id', '=', partner.id),
                ('activity_id', '=', activity.id),
                ('active', '=', True)
            ], limit=1)
            
            if not registration:
                return request.redirect(f'/activity/{activity_id}?error=no_registration_found')
            
            # Vérifier si l'annulation est autorisée
            can_cancel, cancel_message = self._check_cancellation_eligibility(registration, activity)
            
            if not can_cancel:
                return request.redirect(f'/activity/{activity_id}?error={cancel_message}')
            
            # Effectuer l'annulation
            with request.env.cr.savepoint():
                registration.sudo().write({
                    'active': False,
                    'state': 'cancelled',
                    'cancellation_date': fields.Datetime.now(),
                    'cancellation_reason': post.get('reason', 'Annulation volontaire')
                })
                
                # Journal de l'annulation
                self._log_registration_activity(registration, 'cancelled')
            
            # Notification d'annulation
            self._send_cancellation_confirmation(registration)
            
            return request.redirect(f'/activity/{activity_id}?success=registration_cancelled')
            
        except Exception as e:
            _logger.error(f"Erreur annulation inscription: {e}")
            return request.redirect(f'/activity/{activity_id}?error=cancellation_failed')

    # === Méthodes utilitaires améliorées ===

    def _check_registration_eligibility(self, activity, partner):
        """Vérifie l'éligibilité avec messages détaillés"""
        
        # Vérifier l'état de l'activité
        if activity.state not in ['confirmed', 'ongoing']:
            state_messages = {
                'draft': "Cette activité n'est pas encore confirmée.",
                'completed': "Cette activité est terminée.",
                'cancelled': "Cette activité a été annulée."
            }
            return False, state_messages.get(activity.state, "Cette activité n'est pas disponible.")
        
        # Vérifier la date avec délai de grâce
        if not activity.allow_late_registration and activity.date_start:
            grace_period = timedelta(hours=2)  # 2h de délai de grâce
            if fields.Datetime.now() > (activity.date_start - grace_period):
                return False, "Les inscriptions sont fermées pour cette activité."
        
        # Vérifier la capacité avec comptage en temps réel
        current_count = request.env['member.cotisation'].sudo().search_count([
            ('activity_id', '=', activity.id),
            ('active', '=', True),
            ('state', '!=', 'cancelled')
        ])
        
        if activity.max_participants > 0 and current_count >= activity.max_participants:
            return False, "Cette activité est complète."
        
        # Vérifier l'inscription existante
        existing_registration = request.env['member.cotisation'].sudo().search([
            ('member_id', '=', partner.id),
            ('activity_id', '=', activity.id),
            ('active', '=', True)
        ], limit=1)
        
        if existing_registration:
            if existing_registration.state == 'cancelled':
                return False, "Votre inscription a été annulée. Contactez l'administrateur pour vous réinscrire."
            return False, "Vous êtes déjà inscrit à cette activité."
        
        # Vérifier les conflits d'horaire
        if activity.date_start and activity.date_end:
            conflicts = self._check_schedule_conflicts(partner, activity)
            if conflicts:
                conflict_names = [c.name for c in conflicts[:2]]
                return False, f"Conflit d'horaire avec: {', '.join(conflict_names)}"
        
        # Vérifier les prérequis de groupe si définis
        if hasattr(activity, 'required_group_ids') and activity.required_group_ids:
            user_groups = partner.category_id
            if not any(group in user_groups for group in activity.required_group_ids):
                return False, "Vous ne répondez pas aux critères requis pour cette activité."
        
        return True, "Vous pouvez vous inscrire à cette activité."

    def _check_schedule_conflicts(self, partner, activity):
        """Vérifie les conflits d'horaire avec d'autres activités"""
        
        if not activity.date_start or not activity.date_end:
            return []
        
        try:
            # Rechercher les activités en conflit
            conflicting_activities = request.env['group.activity'].sudo().search([
                ('id', '!=', activity.id),
                ('state', 'in', ['confirmed', 'ongoing']),
                ('date_start', '<=', activity.date_end),
                ('date_end', '>=', activity.date_start),
                ('participant_ids.member_id', '=', partner.id)
            ])
            
            return conflicting_activities
            
        except Exception as e:
            _logger.error(f"Erreur vérification conflits horaire: {e}")
            return []

    def _check_cancellation_eligibility(self, registration, activity):
        """Vérifie si une inscription peut être annulée"""
        
        # Activité déjà terminée
        if activity.state == 'completed':
            return False, "cannot_cancel_completed"
        
        # Vérifier la politique d'annulation
        if activity.date_start:
            # Calcul du délai d'annulation (ex: 24h avant)
            cancellation_deadline = activity.date_start - timedelta(hours=24)
            if fields.Datetime.now() > cancellation_deadline:
                return False, "cancellation_deadline_passed"
        
        # Vérifier si un paiement a été effectué
        if registration.amount_paid > 0:
            return False, "payment_already_made"
        
        return True, "Annulation autorisée"

    def _calculate_due_date(self, activity):
        """Calcule la date d'échéance optimale"""
        
        if activity.date_start:
            # 3 jours avant l'activité ou dans 7 jours, le plus proche
            activity_deadline = activity.date_start.date() - timedelta(days=3)
            default_deadline = fields.Date.today() + timedelta(days=7)
            return min(activity_deadline, default_deadline)
        
        return fields.Date.today() + timedelta(days=7)

    def _get_payment_deadline_info(self, activity):
        """Informations sur les délais de paiement"""
        
        due_date = self._calculate_due_date(activity)
        days_until_due = (due_date - fields.Date.today()).days
        
        return {
            'due_date': due_date,
            'days_until_due': days_until_due,
            'is_urgent': days_until_due <= 3,
            'formatted_date': due_date.strftime('%d/%m/%Y')
        }

    def _get_registration_next_steps(self, activity, cotisation):
        """Génère les prochaines étapes après inscription"""
        
        steps = []
        
        if cotisation:
            if cotisation.state == 'pending':
                steps.append({
                    'icon': 'fa-credit-card',
                    'title': 'Effectuer le paiement',
                    'description': f'Réglez la cotisation de {cotisation.amount_due} {cotisation.currency_id.symbol}',
                    'action_url': f'/my/cotisation/{cotisation.id}/payment',
                    'action_text': 'Payer maintenant',
                    'priority': 'high'
                })
            
        steps.extend([
            {
                'icon': 'fa-calendar-check-o',
                'title': 'Noter la date',
                'description': f'Activité prévue le {activity.date_start.strftime("%d/%m/%Y à %H:%M") if activity.date_start else "à définir"}',
                'priority': 'medium'
            },
            {
                'icon': 'fa-envelope',
                'title': 'Vérifier vos emails',
                'description': 'Vous recevrez des notifications importantes par email',
                'priority': 'low'
            }
        ])
        
        if activity.location:
            steps.append({
                'icon': 'fa-map-marker',
                'title': 'Localiser le lieu',
                'description': f'Rendez-vous: {activity.location}',
                'priority': 'medium'
            })
        
        return steps

    def _get_available_payment_methods(self):
        """Retourne les méthodes de paiement disponibles avec détails"""
        
        return [
            {
                'code': 'mobile_money',
                'name': 'Mobile Money',
                'description': 'Orange Money, MTN Money, etc.',
                'requires_reference': True,
                'icon': 'fa-mobile'
            },
            {
                'code': 'bank_transfer',
                'name': 'Virement bancaire',
                'description': 'Virement sur le compte de l\'association',
                'requires_reference': True,
                'icon': 'fa-bank'
            },
            {
                'code': 'cash',
                'name': 'Espèces',
                'description': 'Paiement en espèces au bureau',
                'requires_reference': False,
                'icon': 'fa-money'
            },
            {
                'code': 'check',
                'name': 'Chèque',
                'description': 'Chèque à l\'ordre de l\'association',
                'requires_reference': False,
                'icon': 'fa-file-text-o'
            }
        ]

    @http.route('/conditions-participation', type='http', auth='public', website=True)
    def conditions_participation(self, **kw):
        return request.render('contribution_management.conditions_participation_template', {})

    def _validate_registration_data(self, post):
        """Validation renforcée des données d'inscription"""
        
        data = {}
        
        # Nettoyage et validation des notes
        notes = post.get('notes', '').strip()
        if len(notes) > 500:
            raise ValidationError("Les notes ne peuvent pas dépasser 500 caractères.")
        
        # Validation contre injection
        if any(keyword in notes.lower() for keyword in ['<script', 'javascript:', 'vbscript:']):
            raise ValidationError("Contenu non autorisé dans les notes.")
        
        data['notes'] = notes
        
        # Vérification des conditions acceptées
        if not post.get('accept_conditions'):
            raise ValidationError("Vous devez accepter les conditions de participation.")
        
        return data

    def _log_registration_activity(self, cotisation, action):
        """Journalisation des actions d'inscription"""
        
        try:
            log_message = {
                'created': f"Inscription créée pour {cotisation.member_id.name}",
                'cancelled': f"Inscription annulée par {cotisation.member_id.name}",
                'modified': f"Inscription modifiée pour {cotisation.member_id.name}"
            }.get(action, f"Action {action} sur inscription")
            
            cotisation.activity_id.sudo().message_post(
                body=log_message,
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
            
        except Exception as e:
            _logger.error(f"Erreur journalisation: {e}")

    def _send_registration_confirmation(self, cotisation):
        """Envoi de confirmation amélioré avec retry"""
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                template = request.env.ref(
                    'contribution_management.email_template_registration_confirmation', 
                    raise_if_not_found=False
                )
                
                if template and cotisation.member_id.email:
                    # Contexte enrichi pour l'email
                    template_context = {
                        'activity_url': f"{request.httprequest.url_root}activity/{cotisation.activity_id.id}",
                        'payment_url': f"{request.httprequest.url_root}my/cotisation/{cotisation.id}/payment",
                        'my_activities_url': f"{request.httprequest.url_root}my/activities",
                        'deadline_info': self._get_payment_deadline_info(cotisation.activity_id)
                    }
                    
                    template.sudo().with_context(**template_context).send_mail(
                        cotisation.id, 
                        force_send=True,
                        raise_exception=True
                    )
                    return True
                    
            except Exception as e:
                _logger.warning(f"Tentative {attempt + 1} envoi confirmation échouée: {e}")
                if attempt == max_retries - 1:
                    _logger.error(f"Échec définitif envoi confirmation: {e}")
                    
        return False

    def _notify_admins_activity_filling(self, activity):
        """Notification aux admins quand activité se remplit"""
        
        try:
            admin_group = request.env.ref('contribution_management.group_cotisation_manager')
            admin_users = admin_group.users
            
            for admin in admin_users:
                if admin.email:
                    request.env['mail.activity'].sudo().create({
                        'activity_type_id': request.env.ref('mail.mail_activity_data_todo').id,
                        'summary': f'Activité "{activity.name}" bientôt complète',
                        'note': f'L\'activité "{activity.name}" n\'a plus que {activity.available_spots} '
                               f'places disponibles. Vous pouvez suivre les inscriptions depuis le backend.',
                        'res_model_id': request.env['ir.model'].sudo()._get('group.activity').id,
                        'res_id': activity.id,
                        'user_id': admin.id,
                        'date_deadline': fields.Date.today()
                    })
                    
        except Exception as e:
            _logger.error(f"Erreur notification admins: {e}")

    def _send_cancellation_confirmation(self, registration):
        """Confirmation d'annulation d'inscription"""
        
        try:
            template = request.env.ref(
                'contribution_management.email_template_registration_cancelled', 
                raise_if_not_found=False
            )
            
            if template and registration.member_id.email:
                template.sudo().send_mail(registration.id, force_send=True)
                
        except Exception as e:
            _logger.error(f"Erreur envoi confirmation annulation: {e}")

    def _get_error_code(self, message):
        """Convertit les messages d'erreur en codes pour l'URL"""
        
        error_codes = {
            "Cette activité n'est pas encore confirmée.": "not_confirmed",
            "Cette activité est terminée.": "activity_completed",
            "Cette activité a été annulée.": "activity_cancelled",
            "Les inscriptions sont fermées pour cette activité.": "registration_closed",
            "Cette activité est complète.": "activity_full",
            "Vous êtes déjà inscrit à cette activité.": "already_registered",
            "Votre inscription a été annulée. Contactez l'administrateur pour vous réinscrire.": "registration_cancelled"
        }
        
        # Recherche par mots-clés si correspondance exacte non trouvée
        for key, code in error_codes.items():
            if key.lower() in message.lower():
                return code
        
        return "general_error"

    # === Routes de paiement améliorées ===

    @http.route('/my/cotisation/<int:cotisation_id>/payment', 
                type='http', auth='user', website=True, methods=['GET', 'POST'])
    def cotisation_payment(self, cotisation_id, **post):
        """Page de paiement optimisée avec validation renforcée"""
        
        try:
            cotisation = request.env['member.cotisation'].sudo().search([
                ('id', '=', cotisation_id),
                ('member_id', '=', request.env.user.partner_id.id),
                ('active', '=', True)
            ])
            
            if not cotisation:
                return request.redirect('/my/cotisations?error=cotisation_not_found')
            
            # Vérifier si le paiement est encore nécessaire
            if cotisation.state == 'paid':
                return request.redirect(f'/my/cotisation/{cotisation_id}/payment/success?already_paid=1')
                
        except (ValueError, TypeError):
            return request.redirect('/my/cotisations?error=invalid_cotisation')
        
        if request.httprequest.method == 'GET':
            # Informations enrichies pour le formulaire
            payment_info = self._get_payment_form_context(cotisation)
            
            values = {
                'cotisation': cotisation,
                'activity': cotisation.activity_id,
                'payment_info': payment_info,
                'payment_methods': self._get_available_payment_methods(),
                'max_file_size': '5MB',
                'allowed_formats': ['JPG', 'PNG', 'PDF', 'DOC', 'DOCX'],
                'page_name': 'cotisation_payment',
            }
            return request.render('contribution_management.cotisation_payment_template', values)
        
        elif request.httprequest.method == 'POST':
            # Traitement sécurisé de la soumission
            try:
                # Validation préliminaire
                if cotisation.state == 'paid':
                    return request.redirect(f'/my/cotisation/{cotisation_id}/payment/success?already_paid=1')
                
                # Validation des données avec nettoyage
                payment_data = self._validate_payment_data(post, cotisation)
                
                # Traitement du fichier avec validation renforcée
                proof_file_data = self._process_proof_file(request.httprequest.files.get('proof_file'))
                
                if not proof_file_data:
                    raise ValidationError("Le fichier justificatif est requis.")
                
                # Création du justificatif dans une transaction
                with request.env.cr.savepoint():
                    proof_vals = {
                        'cotisation_id': cotisation.id,
                        'member_id': cotisation.member_id.id,
                        'amount': payment_data['amount'],
                        'payment_method': payment_data.get('payment_method', 'other'),  # Valeur par défaut
                        'reference': payment_data.get('reference', ''),
                        'payment_date': payment_data['payment_date'],
                        'notes': payment_data.get('notes', ''),
                        'proof_file': proof_file_data['content'],
                        'proof_filename': proof_file_data['filename'],
                        'proof_mimetype': proof_file_data['mimetype'],
                        'state': 'submitted',
                        'submitted_date': fields.Datetime.now()
                    }
                    
                    proof = request.env['cotisation.payment.proof'].sudo().create(proof_vals)
                    
                    # Mise à jour de la cotisation si paiement complet
                    if payment_data['amount'] >= cotisation.remaining_amount:
                        cotisation.sudo().write({
                            'state': 'under_review',
                            'payment_method': payment_data['payment_method']
                        })
                    
                    # Journal de l'action
                    self._log_payment_submission(proof)
                
                # Notifications asynchrones
                try:
                    self._send_proof_submission_notification(proof)
                    self._create_admin_validation_task(proof)
                except Exception as e:
                    _logger.error(f"Erreur notifications paiement: {e}")
                
                return request.redirect(f'/my/cotisation/{cotisation_id}/payment/success')
                
            except ValidationError as e:
                values = {
                    'cotisation': cotisation,
                    'activity': cotisation.activity_id,
                    'error': str(e),
                    'form_data': post,
                    'payment_methods': self._get_available_payment_methods(),
                    'page_name': 'cotisation_payment',
                }
                return request.render('contribution_management.cotisation_payment_template', values)
            
            except Exception as e:
                _logger.error(f"Erreur traitement paiement cotisation {cotisation_id}: {e}")
                values = {
                    'cotisation': cotisation,
                    'activity': cotisation.activity_id,
                    'error': "Une erreur technique est survenue. Veuillez réessayer.",
                    'form_data': post,
                    'page_name': 'cotisation_payment',
                }
                return request.render('contribution_management.cotisation_payment_template', values)

    def _get_payment_form_context(self, cotisation):
        """Contexte enrichi pour le formulaire de paiement"""
        
        return {
            'remaining_amount': cotisation.remaining_amount,
            'due_date': cotisation.due_date,
            'is_overdue': cotisation.due_date < fields.Date.today() if cotisation.due_date else False,
            'days_until_due': (cotisation.due_date - fields.Date.today()).days if cotisation.due_date else 0,
            'has_partial_payment': cotisation.amount_paid > 0,
            'payment_progress': (cotisation.amount_paid / cotisation.amount_due) * 100 if cotisation.amount_due > 0 else 0
        }

    def _process_proof_file(self, uploaded_file):
        """Traitement sécurisé du fichier justificatif"""
        
        if not uploaded_file or not uploaded_file.filename:
            return None
        
        try:
            file_content = uploaded_file.read()
            filename = uploaded_file.filename
            mimetype = uploaded_file.content_type
            
            # Validation du fichier
            self._validate_proof_file(file_content, filename, mimetype)
            
            return {
                'content': base64.b64encode(file_content),
                'filename': filename,
                'mimetype': mimetype,
                'size': len(file_content)
            }
            
        except Exception as e:
            _logger.error(f"Erreur traitement fichier: {e}")
            raise ValidationError(f"Erreur lors du traitement du fichier: {str(e)}")

    def _validate_proof_file(self, file_content, filename, mimetype=None):
        """Validation renforcée du fichier justificatif"""
        
        # Vérifier la taille (5MB max)
        max_size = 5 * 1024 * 1024
        if len(file_content) > max_size:
            raise ValidationError("Le fichier ne peut pas dépasser 5MB.")
        
        # Vérifier l'extension et le type MIME
        allowed_extensions = {
            '.jpg': ['image/jpeg'],
            '.jpeg': ['image/jpeg'],
            '.png': ['image/png'],
            '.gif': ['image/gif'],
            '.pdf': ['application/pdf'],
            '.doc': ['application/msword'],
            '.docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document']
        }
        
        file_ext = '.' + filename.lower().split('.')[-1] if '.' in filename else ''
        
        if file_ext not in allowed_extensions:
            raise ValidationError(
                "Format de fichier non autorisé. "
                "Formats acceptés: JPG, PNG, PDF, DOC, DOCX"
            )
        
        # Validation du type MIME si disponible
        if mimetype and file_ext in allowed_extensions:
            if mimetype not in allowed_extensions[file_ext]:
                raise ValidationError("Le type de fichier ne correspond pas à l'extension.")
        
        # Validation du contenu pour les images
        if file_ext in ['.jpg', '.jpeg', '.png', '.gif']:
            try:
                image_process(file_content, verify_resolution=False)
            except Exception:
                raise ValidationError("Le fichier image semble être corrompu.")
        
        # Vérification basique anti-malware (signatures connues)
        malware_signatures = [b'<script', b'javascript:', b'vbscript:']
        for signature in malware_signatures:
            if signature in file_content[:1024]:  # Check first 1KB
                raise ValidationError("Fichier détecté comme potentiellement dangereux.")

    def _validate_payment_data(self, post, cotisation):
        """Validation renforcée des données de paiement"""
        
        data = {}
        
        # Montant avec validation contre la cotisation
        try:
            amount = float(post.get('amount', 0))
            if amount <= 0:
                raise ValidationError("Le montant doit être positif.")
            
            # Vérifier que le montant ne dépasse pas ce qui est dû
            if amount > cotisation.remaining_amount * 1.1:  # 10% de tolérance
                raise ValidationError(
                    f"Le montant ne peut pas dépasser {cotisation.remaining_amount} {cotisation.currency_id.symbol}."
                )
            
            data['amount'] = amount
            
        except (ValueError, TypeError):
            raise ValidationError("Montant invalide.")
        
        # Méthode de paiement avec validation étendue
        payment_method = post.get('payment_method', '').strip()
        valid_methods = [pm['code'] for pm in self._get_available_payment_methods()]
        
        if payment_method not in valid_methods:
            raise ValidationError("Méthode de paiement invalide.")
        data['payment_method'] = payment_method
        
        # Référence avec validation selon méthode
        reference = post.get('reference', '').strip()
        methods_requiring_reference = ['mobile_money', 'bank_transfer', 'online']
        
        if payment_method in methods_requiring_reference:
            if not reference:
                method_names = {
                    'mobile_money': 'Mobile Money',
                    'bank_transfer': 'virement bancaire',
                    'online': 'paiement en ligne'
                }
                raise ValidationError(
                    f"La référence est requise pour {method_names.get(payment_method, payment_method)}."
                )
            
            # Validation format référence selon méthode
            if payment_method == 'mobile_money' and len(reference) < 8:
                raise ValidationError("La référence Mobile Money doit contenir au moins 8 caractères.")
        
        data['reference'] = reference
        
        # Date de paiement avec validation étendue
        try:
            payment_date_str = post.get('payment_date', '').strip()
            if not payment_date_str:
                raise ValidationError("La date de paiement est requise.")
            
            payment_date = fields.Date.from_string(payment_date_str)
            
            # Vérifier que la date n'est pas dans le futur
            if payment_date > fields.Date.today():
                raise ValidationError("La date de paiement ne peut pas être dans le futur.")
            
            # Vérifier que la date n'est pas trop ancienne (ex: 90 jours)
            oldest_allowed = fields.Date.today() - timedelta(days=90)
            if payment_date < oldest_allowed:
                raise ValidationError("La date de paiement ne peut pas être antérieure à 90 jours.")
            
            data['payment_date'] = payment_date
            
        except (ValueError, TypeError):
            raise ValidationError("Format de date invalide.")
        
        # Notes avec nettoyage et validation
        notes = post.get('notes', '').strip()
        if len(notes) > 1000:
            raise ValidationError("Les notes ne peuvent pas dépasser 1000 caractères.")
        
        # Validation anti-injection
        if any(keyword in notes.lower() for keyword in ['<script', 'javascript:', 'vbscript:']):
            raise ValidationError("Contenu non autorisé dans les notes.")
        
        data['notes'] = notes
        
        return data

    def _log_payment_submission(self, proof):
        """Journalisation de la soumission de preuve"""
        
        try:
            message = (
                f"Justificatif de paiement soumis par {proof.member_id.name}\n"
                f"Montant: {proof.amount} {proof.currency_id.symbol}\n"
                f"Méthode: {proof.payment_method}\n"
                f"Référence: {proof.reference or 'N/A'}"
            )
            
            proof.cotisation_id.sudo().message_post(
                body=message,
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
            
        except Exception as e:
            _logger.error(f"Erreur journalisation paiement: {e}")

    def _create_admin_validation_task(self, proof):
        """Création de tâche pour validation administrative"""
        
        try:
            admin_group = request.env.ref('contribution_management.group_cotisation_manager')
            
            # Assigner à l'admin le moins chargé
            admin_users = admin_group.users
            if admin_users:
                # Compter les tâches en attente par admin
                admin_tasks = {}
                for admin in admin_users:
                    task_count = request.env['mail.activity'].sudo().search_count([
                        ('user_id', '=', admin.id),
                        ('res_model', '=', 'cotisation.payment.proof'),
                        ('activity_type_id', '=', request.env.ref('mail.mail_activity_data_todo').id)
                    ])
                    admin_tasks[admin.id] = task_count
                
                # Sélectionner l'admin avec le moins de tâches
                assigned_admin_id = min(admin_tasks, key=admin_tasks.get)
                assigned_admin = request.env['res.users'].sudo().browse(assigned_admin_id)
                
                # Calculer la priorité basée sur l'urgence
                is_urgent = proof.cotisation_id.due_date <= fields.Date.today() + timedelta(days=2)
                
                activity_vals = {
                    'activity_type_id': request.env.ref('mail.mail_activity_data_todo').id,
                    'summary': f'Validation justificatif - {proof.member_id.name}',
                    'note': self._generate_validation_task_note(proof),
                    'res_model_id': request.env['ir.model'].sudo()._get('cotisation.payment.proof').id,
                    'res_id': proof.id,
                    'user_id': assigned_admin_id,
                    'date_deadline': fields.Date.today() + (timedelta(days=1) if is_urgent else timedelta(days=3))
                }
                
                request.env['mail.activity'].sudo().create(activity_vals)
                
        except Exception as e:
            _logger.error(f"Erreur création tâche validation: {e}")

    def _generate_validation_task_note(self, proof):
        """Génère une note détaillée pour la tâche de validation"""
        
        activity_name = proof.cotisation_id.activity_id.name if proof.cotisation_id.activity_id else "Cotisation générale"
        
        note = f"""
        <p><strong>Nouveau justificatif de paiement à valider</strong></p>
        <ul>
            <li><strong>Membre:</strong> {proof.member_id.name}</li>
            <li><strong>Activité:</strong> {activity_name}</li>
            <li><strong>Montant:</strong> {proof.amount} {proof.currency_id.symbol}</li>
            <li><strong>Méthode:</strong> {proof.payment_method}</li>
            <li><strong>Date paiement:</strong> {proof.payment_date}</li>
            <li><strong>Référence:</strong> {proof.reference or 'N/A'}</li>
        </ul>
        """
        
        if proof.notes:
            note += f"<p><strong>Notes du membre:</strong> {proof.notes}</p>"
        
        due_date = proof.cotisation_id.due_date
        if due_date and due_date <= fields.Date.today() + timedelta(days=2):
            note += "<p><span style='color: red;'><strong>⚠️ URGENT:</strong> Échéance proche !</span></p>"
        
        return note

    # === Routes AJAX améliorées ===

    @http.route('/activities/search', type='json', auth='public', website=True)
    def activities_search_json(self, search='', filters=None, limit=10, offset=0):
        """API de recherche d'activités optimisée"""
        
        try:
            filters = filters or {}
            limit = min(int(limit), 50)  # Limitation sécurisée
            offset = max(int(offset), 0)
            
            domain = [
                ('state', 'in', ['confirmed', 'ongoing']),
                ('active', '=', True)
            ]
            
            # Recherche textuelle améliorée
            if search and len(search.strip()) >= 2:
                search_terms = search.strip().split()
                for term in search_terms:
                    domain.extend(['|', ('name', 'ilike', term), ('description', 'ilike', term)])
            
            # Filtres additionnels
            if filters.get('group_id'):
                domain.append(('group_id', '=', int(filters['group_id'])))
            
            if filters.get('date_from'):
                domain.append(('date_start', '>=', filters['date_from']))
            
            if filters.get('date_to'):
                domain.append(('date_start', '<=', filters['date_to']))
            
            # Recherche avec gestion d'erreur
            activities = request.env['group.activity'].sudo().search(
                domain, 
                limit=limit, 
                offset=offset,
                order='date_start asc nulls last, name asc'
            )
            
            # Construction de la réponse optimisée
            results = []
            for activity in activities:
                # Calcul en temps réel des places disponibles
                current_registrations = request.env['member.cotisation'].sudo().search_count([
                    ('activity_id', '=', activity.id),
                    ('active', '=', True),
                    ('state', '!=', 'cancelled')
                ])
                
                available_spots = max(0, activity.max_participants - current_registrations) if activity.max_participants > 0 else None
                
                results.append({
                    'id': activity.id,
                    'name': activity.name,
                    'group_name': activity.group_id.name,
                    'group_id': activity.group_id.id,
                    'description_short': activity.description[:100] + '...' if activity.description and len(activity.description) > 100 else activity.description,
                    'date_start': activity.date_start.isoformat() if activity.date_start else None,
                    'date_end': activity.date_end.isoformat() if activity.date_end else None,
                    'location': activity.location,
                    'cotisation_amount': float(activity.cotisation_amount),
                    'currency_symbol': activity.currency_id.symbol,
                    'participant_count': current_registrations,
                    'max_participants': activity.max_participants,
                    'available_spots': available_spots,
                    'is_full': available_spots == 0 if available_spots is not None else False,
                    'state': activity.state,
                    'url': f'/activity/{activity.id}',
                    'registration_url': f'/activity/{activity.id}/register',
                    'can_register': activity.state in ['confirmed', 'ongoing'] and (available_spots is None or available_spots > 0)
                })
            
            return {
                'success': True,
                'results': results,
                'total': len(results),
                'has_more': len(results) == limit
            }
            
        except Exception as e:
            _logger.error(f"Erreur recherche JSON activités: {e}")
            return {
                'success': False,
                'error': 'Erreur lors de la recherche',
                'results': []
            }

    @http.route('/activity/<int:activity_id>/quick_register', 
                type='json', auth='user', website=True, csrf=True)
    def quick_register(self, activity_id, **post):
        """Inscription rapide via AJAX avec confirmation"""
        
        try:
            activity = request.env['group.activity'].sudo().browse(activity_id)
            if not activity.exists():
                return {'success': False, 'message': 'Activité non trouvée.'}
            
            partner = request.env.user.partner_id
            
            # Vérification d'éligibilité
            can_register, message = self._check_registration_eligibility(activity, partner)
            
            if not can_register:
                return {'success': False, 'message': message}
            
            # Création de l'inscription
            with request.env.cr.savepoint():
                cotisation_vals = {
                    'member_id': partner.id,
                    'activity_id': activity.id,
                    'cotisation_type': 'activity',
                    'amount_due': activity.cotisation_amount,
                    'due_date': self._calculate_due_date(activity),
                    'currency_id': activity.currency_id.id,
                    'company_id': activity.company_id.id,
                    'description': f"Inscription rapide à l'activité: {activity.name}",
                    'state': 'pending',
                }
                
                cotisation = request.env['member.cotisation'].sudo().create(cotisation_vals)
                
                # Log de l'action
                self._log_registration_activity(cotisation, 'created')
            
            # Notifications asynchrones
            try:
                self._send_registration_confirmation(cotisation)
            except Exception as e:
                _logger.error(f"Erreur notification inscription rapide: {e}")
            
            return {
                'success': True,
                'message': 'Inscription confirmée !',
                'cotisation_id': cotisation.id,
                'payment_url': f'/my/cotisation/{cotisation.id}/payment',
                'activity_url': f'/activity/{activity.id}',
                'amount_due': float(cotisation.amount_due),
                'currency_symbol': cotisation.currency_id.symbol
            }
            
        except ValidationError as e:
            return {'success': False, 'message': str(e)}
        except Exception as e:
            _logger.error(f"Erreur inscription rapide: {e}")
            return {'success': False, 'message': 'Erreur lors de l\'inscription. Veuillez réessayer.'}

    @http.route('/activity/<int:activity_id>/check_availability', 
                type='json', auth='public', website=True)
    def check_activity_availability(self, activity_id):
        """Vérification en temps réel de la disponibilité"""
        
        try:
            activity = request.env['group.activity'].sudo().browse(activity_id)
            if not activity.exists():
                return {'success': False, 'message': 'Activité non trouvée.'}
            
            # Comptage actuel des participants
            current_count = request.env['member.cotisation'].sudo().search_count([
                ('activity_id', '=', activity.id),
                ('active', '=', True),
                ('state', '!=', 'cancelled')
            ])
            
            available_spots = None
            if activity.max_participants > 0:
                available_spots = max(0, activity.max_participants - current_count)
            
            return {
                'success': True,
                'available': activity.state in ['confirmed', 'ongoing'],
                'participant_count': current_count,
                'max_participants': activity.max_participants,
                'available_spots': available_spots,
                'is_full': available_spots == 0 if available_spots is not None else False,
                'state': activity.state,
                'registration_open': activity.state in ['confirmed', 'ongoing'] and (available_spots is None or available_spots > 0)
            }
            
        except Exception as e:
            _logger.error(f"Erreur vérification disponibilité: {e}")
            return {'success': False, 'message': 'Erreur lors de la vérification.'}

    @http.route('/my/registration/<int:cotisation_id>/status', 
                type='json', auth='user', website=True)
    def registration_status_json(self, cotisation_id):
        """Statut détaillé d'une inscription en JSON"""
        
        try:
            cotisation = request.env['member.cotisation'].sudo().search([
                ('id', '=', cotisation_id),
                ('member_id', '=', request.env.user.partner_id.id),
                ('active', '=', True)
            ])
            
            if not cotisation:
                return {'success': False, 'message': 'Inscription non trouvée.'}
            
            # Récupérer les preuves de paiement avec détails
            proofs = request.env['cotisation.payment.proof'].sudo().search([
                ('cotisation_id', '=', cotisation.id)
            ], order='create_date desc')
            
            proof_data = []
            for proof in proofs:
                proof_data.append({
                    'id': proof.id,
                    'amount': float(proof.amount),
                    'payment_date': proof.payment_date.isoformat(),
                    'payment_method': proof.payment_method,
                    'reference': proof.reference,
                    'state': proof.state,
                    'submitted_date': proof.submitted_date.isoformat(),
                    'validation_date': proof.validation_date.isoformat() if proof.validation_date else None,
                    'validator_name': proof.validated_by.name if proof.validated_by else None,
                    'rejection_reason': proof.rejection_reason or '',
                    'validation_notes': proof.validation_notes or '',
                    'can_download': bool(proof.proof_file),
                    'filename': proof.proof_filename
                })
            
            # Informations de paiement calculées
            payment_progress = (cotisation.amount_paid / cotisation.amount_due) * 100 if cotisation.amount_due > 0 else 0
            
            return {
                'success': True,
                'cotisation': {
                    'id': cotisation.id,
                    'state': cotisation.state,
                    'amount_due': float(cotisation.amount_due),
                    'amount_paid': float(cotisation.amount_paid),
                    'remaining_amount': float(cotisation.remaining_amount),
                    'payment_progress': round(payment_progress, 1),
                    'due_date': cotisation.due_date.isoformat(),
                    'is_overdue': cotisation.due_date < fields.Date.today() if cotisation.due_date else False,
                    'payment_date': cotisation.payment_date.isoformat() if cotisation.payment_date else None,
                    'activity_name': cotisation.activity_id.name if cotisation.activity_id else '',
                    'activity_id': cotisation.activity_id.id if cotisation.activity_id else None,
                    'currency_symbol': cotisation.currency_id.symbol,
                    'payment_method': cotisation.payment_method
                },
                'proofs': proof_data,
                'next_actions': self._get_next_actions(cotisation)
            }
            
        except Exception as e:
            _logger.error(f"Erreur récupération statut inscription: {e}")
            return {'success': False, 'message': 'Erreur lors de la récupération du statut.'}

    def _get_next_actions(self, cotisation):
        """Détermine les prochaines actions recommandées"""
        
        actions = []
        
        if cotisation.state == 'pending' and cotisation.remaining_amount > 0:
            actions.append({
                'type': 'payment',
                'title': 'Effectuer le paiement',
                'description': f'Réglez {cotisation.remaining_amount} {cotisation.currency_id.symbol}',
                'url': f'/my/cotisation/{cotisation.id}/payment',
                'urgency': 'high' if cotisation.due_date <= fields.Date.today() + timedelta(days=3) else 'normal'
            })
        
        if cotisation.state == 'under_review':
            actions.append({
                'type': 'wait',
                'title': 'Attendre la validation',
                'description': 'Votre justificatif est en cours de vérification',
                'urgency': 'low'
            })
        
        if cotisation.activity_id and cotisation.activity_id.date_start:
            days_until_activity = (cotisation.activity_id.date_start.date() - fields.Date.today()).days
            
            if days_until_activity > 0:
                actions.append({
                    'type': 'prepare',
                    'title': 'Préparer l\'activité',
                    'description': f'Activité dans {days_until_activity} jour{"s" if days_until_activity > 1 else ""}',
                    'url': f'/activity/{cotisation.activity_id.id}',
                    'urgency': 'high' if days_until_activity <= 3 else 'normal'
                })
        
        return actions

    # === Routes de gestion des erreurs et pages d'aide ===

    @http.route('/activities/help', type='http', auth='public', website=True)
    def activities_help(self, **kw):
        """Page d'aide pour les inscriptions"""
        
        values = {
            'payment_methods': self._get_available_payment_methods(),
            'faq_items': self._get_registration_faq(),
            'contact_info': self._get_contact_information(),
            'page_name': 'activities_help',
        }
        
        return request.render('contribution_management.activities_help_template', values)

    def _get_registration_faq(self):
        """Questions fréquemment posées"""
        
        return [
            {
                'question': 'Comment puis-je m\'inscrire à une activité ?',
                'answer': 'Connectez-vous à votre compte, choisissez une activité et cliquez sur "S\'inscrire". Vous devrez ensuite effectuer le paiement de la cotisation.'
            },
            {
                'question': 'Quels moyens de paiement sont acceptés ?',
                'answer': 'Nous acceptons Mobile Money, virements bancaires, espèces, chèques et cartes bancaires selon les modalités de chaque activité.'
            },
            {
                'question': 'Puis-je annuler mon inscription ?',
                'answer': 'Oui, vous pouvez annuler votre inscription jusqu\'à 24h avant le début de l\'activité, sous réserve de n\'avoir pas encore effectué le paiement.'
            },
            {
                'question': 'Que se passe-t-il si l\'activité est annulée ?',
                'answer': 'En cas d\'annulation par l\'organisateur, vous serez notifié et tout paiement effectué sera remboursé.'
            },
            {
                'question': 'Comment télécharger un justificatif de paiement ?',
                'answer': 'Vous pouvez télécharger vos justificatifs depuis votre espace personnel dans la section "Mes cotisations".'
            }
        ]

    def _get_contact_information(self):
        """Informations de contact pour support"""
        
        try:
            company = request.env.company
            return {
                'email': company.email,
                'phone': company.phone,
                'address': company.partner_id.contact_address,
                'website': company.website
            }
        except Exception:
            return {}

    # === Méthodes d'optimisation et cache ===

    def _get_activity_cache_key(self, activity_id, user_id=None):
        """Génère une clé de cache pour une activité"""
        
        base_key = f"activity_{activity_id}"
        if user_id:
            base_key += f"_user_{user_id}"
        return base_key

    def _cache_activity_data(self, activity, user_data=None, ttl=300):
        """Met en cache les données d'activité (5 minutes TTL)"""
        
        try:
            cache_key = self._get_activity_cache_key(activity.id, request.env.user.id if user_data else None)
            
            cache_data = {
                'activity_info': {
                    'id': activity.id,
                    'name': activity.name,
                    'state': activity.state,
                    'participant_count': activity.participant_count,
                    'available_spots': activity.available_spots,
                    'is_full': activity.is_full
                },
                'timestamp': fields.Datetime.now().isoformat()
            }
            
            if user_data:
                cache_data['user_data'] = user_data
            
            # Utilisation du cache Redis si disponible, sinon cache en mémoire
            # Note: Implémentation dépendante de l'infrastructure
            
        except Exception as e:
            _logger.debug(f"Cache non disponible: {e}")

    # === Méthodes de notification étendues ===

    def _send_registration_confirmation(self, cotisation):
        """Envoi de confirmation avec template enrichi"""
        
        try:
            template = request.env.ref(
                'contribution_management.email_template_registration_confirmation', 
                raise_if_not_found=False
            )
            
            if not template or not cotisation.member_id.email:
                return False
            
            # Contexte enrichi pour l'email
            base_url = request.httprequest.url_root.rstrip('/')
            template_context = {
                'member_name': cotisation.member_id.name,
                'activity_name': cotisation.activity_id.name,
                'activity_date': cotisation.activity_id.date_start,
                'activity_location': cotisation.activity_id.location,
                'amount_due': cotisation.amount_due,
                'currency_symbol': cotisation.currency_id.symbol,
                'due_date': cotisation.due_date,
                'activity_url': f"{base_url}/activity/{cotisation.activity_id.id}",
                'payment_url': f"{base_url}/my/cotisation/{cotisation.id}/payment",
                'my_activities_url': f"{base_url}/my/activities",
                'group_name': cotisation.activity_id.group_id.name,
                'registration_number': cotisation.id,
                'payment_deadline_info': self._get_payment_deadline_info(cotisation.activity_id)
            }
            
            # Ajouter informations spécifiques selon l'activité
            if cotisation.activity_id.description:
                template_context['activity_description'] = cotisation.activity_id.description
            
            template.sudo().with_context(**template_context).send_mail(
                cotisation.id, 
                force_send=True,
                raise_exception=True
            )
            
            # Log de l'envoi
            cotisation.sudo().message_post(
                body=f"Email de confirmation envoyé à {cotisation.member_id.email}",
                message_type='notification'
            )
            
            return True
            
        except Exception as e:
            _logger.error(f"Erreur envoi confirmation inscription: {e}")
            return False

    def _send_proof_submission_notification(self, proof):
        """Notification enrichie de soumission de preuve"""
        
        try:
            # Notification au membre
            member_template = request.env.ref(
                'contribution_management.email_template_proof_submitted', 
                raise_if_not_found=False
            )
            
            if member_template and proof.member_id.email:
                base_url = request.httprequest.url_root.rstrip('/')
                member_context = {
                    'proof_amount': proof.amount,
                    'currency_symbol': proof.currency_id.symbol,
                    'activity_name': proof.cotisation_id.activity_id.name,
                    'submission_date': proof.submitted_date,
                    'tracking_number': f"PAY-{proof.id:06d}",
                    'status_url': f"{base_url}/my/cotisations",
                    'estimated_validation_time': '1-3 jours ouvrables'
                }
                
                member_template.sudo().with_context(**member_context).send_mail(
                    proof.id, force_send=True
                )
            
            return True
            
        except Exception as e:
            _logger.error(f"Erreur notification soumission preuve: {e}")
            return False

    # === Méthodes de reporting et statistiques ===

    @http.route('/activities/stats', type='json', auth='user', website=True)
    def activity_statistics(self, **kw):
        """Statistiques publiques des activités"""
        
        try:
            if request.env.user._is_public():
                return {'success': False, 'message': 'Accès non autorisé.'}
            
            # Statistiques de base
            total_activities = request.env['group.activity'].sudo().search_count([
                ('active', '=', True)
            ])
            
            active_activities = request.env['group.activity'].sudo().search_count([
                ('state', 'in', ['confirmed', 'ongoing']),
                ('active', '=', True)
            ])
            
            # Statistiques utilisateur
            user_registrations = request.env['member.cotisation'].sudo().search_count([
                ('member_id', '=', request.env.user.partner_id.id),
                ('active', '=', True)
            ])
            
            user_paid_registrations = request.env['member.cotisation'].sudo().search_count([
                ('member_id', '=', request.env.user.partner_id.id),
                ('state', '=', 'paid'),
                ('active', '=', True)
            ])
            
            return {
                'success': True,
                'stats': {
                    'total_activities': total_activities,
                    'active_activities': active_activities,
                    'user_registrations': user_registrations,
                    'user_paid_registrations': user_paid_registrations,
                    'payment_completion_rate': round((user_paid_registrations / user_registrations) * 100, 1) if user_registrations > 0 else 0
                }
            }
            
        except Exception as e:
            _logger.error(f"Erreur récupération statistiques: {e}")
            return {'success': False, 'message': 'Erreur lors de la récupération des statistiques.'}

    # === Méthodes de maintenance et nettoyage ===

    def _cleanup_expired_registrations(self):
        """Nettoyage des inscriptions expirées (à appeler via cron)"""
        
        try:
            # Inscriptions non payées expirées depuis plus de 30 jours
            expired_date = fields.Date.today() - timedelta(days=30)
            
            expired_cotisations = request.env['member.cotisation'].sudo().search([
                ('state', '=', 'pending'),
                ('due_date', '<', expired_date),
                ('amount_paid', '=', 0),
                ('active', '=', True)
            ])
            
            for cotisation in expired_cotisations:
                cotisation.write({
                    'active': False,
                    'state': 'expired',
                    'expiration_date': fields.Datetime.now()
                })
                
                # Libérer la place dans l'activité
                self._log_registration_activity(cotisation, 'expired')
            
            _logger.info(f"Nettoyage: {len(expired_cotisations)} inscriptions expirées archivées")
            
        except Exception as e:
            _logger.error(f"Erreur nettoyage inscriptions expirées: {e}")

    def _generate_registration_receipt(self, cotisation):
        """Génère un reçu d'inscription en PDF"""
        
        try:
            # Utiliser le moteur de rapports d'Odoo
            report = request.env.ref('contribution_management.action_report_registration_receipt')
            
            if report:
                pdf_content, _ = report.sudo()._render_qweb_pdf([cotisation.id])
                
                # Encoder en base64 pour stockage/téléchargement
                return base64.b64encode(pdf_content)
            
        except Exception as e:
            _logger.error(f"Erreur génération reçu: {e}")
            
        return None

    # === Méthodes de sécurité renforcées ===

    def _validate_user_access(self, cotisation_id):
        """Validation stricte de l'accès utilisateur"""
        
        if request.env.user._is_public():
            raise AccessError("Accès non autorisé")
        
        cotisation = request.env['member.cotisation'].sudo().browse(cotisation_id)
        
        if not cotisation.exists():
            raise ValidationError("Cotisation introuvable")
        
        if cotisation.member_id.id != request.env.user.partner_id.id:
            raise AccessError("Accès non autorisé à cette cotisation")
        
        return cotisation

    def _rate_limit_check(self, action, identifier, limit_per_hour=10):
        """Vérification de limitation de débit pour prévenir l'abus"""
        
        try:
            # Implémentation basique en mémoire (à améliorer avec Redis)
            cache_key = f"rate_limit_{action}_{identifier}"
            current_hour = datetime.now().strftime('%Y%m%d%H')
            
            # Note: Dans un environnement de production, utiliser Redis ou base de données
            # pour un cache persistant et partagé entre instances
            
            return True  # Toujours autoriser pour cette implémentation basique
            
        except Exception as e:
            _logger.error(f"Erreur vérification rate limit: {e}")
            return True  # En cas d'erreur, autoriser par défaut

    # === Améliorations pour pages existantes ===

    @http.route('/my/cotisations', type='http', auth='user', website=True)
    def my_cotisations(self, sortby='date', filterby='all', **kw):
        """Page des cotisations avec tri et filtres améliorés"""
        
        partner = request.env.user.partner_id
        
        # Options de tri
        sort_options = {
            'date': 'create_date desc',
            'amount': 'amount_due desc',
            'state': 'state asc, create_date desc',
            'activity': 'activity_id.name asc'
        }
        
        order = sort_options.get(sortby, 'create_date desc')
        
        # Construction du domaine avec filtres
        domain = [
            ('member_id', '=', partner.id),
            ('active', '=', True)
        ]
        
        # Filtres par statut
        if filterby != 'all':
            if filterby == 'pending':
                domain.append(('state', 'in', ['pending', 'partial']))
            elif filterby == 'paid':
                domain.append(('state', '=', 'paid'))
            elif filterby == 'overdue':
                domain.append(('state', '=', 'overdue'))
            elif filterby == 'activities':
                domain.append(('activity_id', '!=', False))
        
        # Récupération des données
        cotisations = request.env['member.cotisation'].sudo().search(domain, order=order)
        
        # Récupérer les preuves de paiement groupées
        proofs = request.env['cotisation.payment.proof'].sudo().search([
            ('member_id', '=', partner.id)
        ], order='create_date desc')
        
        # Statistiques personnelles
        stats = self._calculate_user_cotisation_stats(partner)
        
        values = {
            'cotisations': cotisations,
            'proofs': proofs,
            'partner': partner,
            'stats': stats,
            'sortby': sortby,
            'filterby': filterby,
            'sort_options': [
                ('date', 'Date'),
                ('amount', 'Montant'),
                ('state', 'Statut'),
                ('activity', 'Activité')
            ],
            'filter_options': [
                ('all', 'Toutes'),
                ('pending', 'En attente'),
                ('paid', 'Payées'),
                ('overdue', 'En retard'),
                ('activities', 'Activités uniquement')
            ],
            'page_name': 'my_cotisations',
        }
        
        return request.render('contribution_management.my_cotisations_template', values)

    def _calculate_user_cotisation_stats(self, partner):
        """Calcule les statistiques des cotisations utilisateur"""
        
        try:
            cotisations = request.env['member.cotisation'].sudo().search([
                ('member_id', '=', partner.id),
                ('active', '=', True)
            ])
            
            return {
                'total_cotisations': len(cotisations),
                'total_amount_due': sum(cotisations.mapped('amount_due')),
                'total_amount_paid': sum(cotisations.mapped('amount_paid')),
                'pending_count': len(cotisations.filtered(lambda c: c.state in ['pending', 'partial'])),
                'paid_count': len(cotisations.filtered(lambda c: c.state == 'paid')),
                'overdue_count': len(cotisations.filtered(lambda c: c.state == 'overdue')),
                'activities_count': len(cotisations.filtered('activity_id')),
                'currency_symbol': cotisations[0].currency_id.symbol if cotisations else '€'
            }
            
        except Exception as e:
            _logger.error(f"Erreur calcul statistiques utilisateur: {e}")
            return {}

    @http.route('/my/activities', type='http', auth='user', website=True)
    def my_activities(self, view='card', filterby='all', **kw):
        """Page des activités utilisateur avec vues multiples"""
        
        partner = request.env.user.partner_id
        
        # Construction du domaine
        domain = [
            ('member_id', '=', partner.id),
            ('activity_id', '!=', False),
            ('active', '=', True)
        ]
        
        # Filtres temporels
        if filterby == 'upcoming':
            domain.append(('activity_id.date_start', '>=', fields.Datetime.now()))
        elif filterby == 'past':
            domain.append(('activity_id.date_start', '<', fields.Datetime.now()))
        elif filterby == 'current':
            domain.extend([
                ('activity_id.date_start', '<=', fields.Datetime.now()),
                ('activity_id.date_end', '>=', fields.Datetime.now())
            ])
        
        # Récupération des données
        cotisations = request.env['member.cotisation'].sudo().search(
            domain, order='activity_id.date_start desc'
        )
        
        activities = cotisations.mapped('activity_id')
        
        # Groupement par statut pour affichage
        grouped_activities = {
            'upcoming': activities.filtered(lambda a: a.date_start and a.date_start >= fields.Datetime.now()),
            'current': activities.filtered(lambda a: a.date_start and a.date_end and 
                                         a.date_start <= fields.Datetime.now() <= a.date_end),
            'past': activities.filtered(lambda a: a.date_start and a.date_start < fields.Datetime.now())
        }
        
        values = {
            'activities': activities,
            'grouped_activities': grouped_activities,
            'cotisations': cotisations,
            'partner': partner,
            'view': view,
            'filterby': filterby,
            'view_options': [
                ('card', 'Cartes'),
                ('list', 'Liste'),
                ('calendar', 'Calendrier')
            ],
            'filter_options': [
                ('all', 'Toutes'),
                ('upcoming', 'À venir'),
                ('current', 'En cours'),
                ('past', 'Passées')
            ],
            'stats': {
                'total': len(activities),
                'upcoming': len(grouped_activities['upcoming']),
                'current': len(grouped_activities['current']),
                'past': len(grouped_activities['past'])
            },
            'page_name': 'my_activities',
        }
        
        return request.render('contribution_management.my_activities_template', values)

    # === Webhook et intégrations externes ===

    @http.route('/webhook/payment/mobile_money', type='json', auth='none', csrf=False)
    def mobile_money_webhook(self, **post):
        """Webhook pour notifications de paiement Mobile Money"""
        
        try:
            # Validation de la signature (à implémenter selon l'opérateur)
            if not self._validate_webhook_signature(post):
                return {'success': False, 'error': 'Invalid signature'}
            
            # Traitement de la notification
            transaction_ref = post.get('transaction_id')
            amount = float(post.get('amount', 0))
            status = post.get('status')
            
            if status == 'successful' and transaction_ref and amount > 0:
                # Rechercher la preuve de paiement correspondante
                proof = request.env['cotisation.payment.proof'].sudo().search([
                    ('reference', '=', transaction_ref),
                    ('payment_method', '=', 'mobile_money'),
                    ('state', 'in', ['submitted', 'under_review'])
                ], limit=1)
                
                if proof and abs(proof.amount - amount) < 0.01:  # Tolérance de 1 centime
                    # Auto-validation si montant correspond
                    proof.sudo().write({
                        'state': 'validated',
                        'validation_date': fields.Datetime.now(),
                        'validation_notes': 'Validation automatique via webhook Mobile Money',
                        'external_reference': post.get('external_ref')
                    })
                    
                    # Mettre à jour la cotisation
                    proof.cotisation_id.sudo()._update_payment_status()
                    
                    return {'success': True, 'message': 'Payment validated'}
            
            return {'success': False, 'message': 'Payment not found or invalid'}
            
        except Exception as e:
            _logger.error(f"Erreur webhook Mobile Money: {e}")
            return {'success': False, 'error': 'Processing error'}

    def _validate_webhook_signature(self, data):
        """Validation de la signature webhook (à personnaliser)"""
        
        # Implémentation dépendante du fournisseur de service
        # Exemple pour signature HMAC
        try:
            # webhook_secret = request.env['ir.config_parameter'].sudo().get_param('mobile_money.webhook_secret')
            # if not webhook_secret:
            #     return False
            
            # signature = data.get('signature')
            # expected_signature = hmac.new(
            #     webhook_secret.encode(),
            #     json.dumps(data, sort_keys=True).encode(),
            #     hashlib.sha256
            # ).hexdigest()
            
            # return signature == expected_signature
            
            return True  # Placeholder - implémenter selon le fournisseur
            
        except Exception as e:
            _logger.error(f"Erreur validation signature webhook: {e}")
            return False