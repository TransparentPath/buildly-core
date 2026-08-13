from urllib.parse import urljoin

from django.conf import settings
from django.utils import timezone
from datetime import timedelta

from core.email_utils import send_email
from core.jwt_utils import create_invitation_token


def _role_display(user_role):
    """Mirrors the display-name derivation `perform_invite` used inline."""
    role_lower = (user_role or '').lower()
    if 'admins' in role_lower:
        return 'Administrator'
    if role_lower == 'users' or role_lower.endswith('users'):
        return 'User'
    return user_role[:-1] if user_role and user_role[-1].lower() == 's' else user_role


def issue_invitation_email(invitation, *, is_reinvite):
    """
    Mint a token for an existing Invitation row and send the mail. Nothing
    else -- no Organization creation, no unit-of-measure posts. It takes an
    Invitation instance, whose `organization` FK is already resolved, so it
    is structurally unable to create an Organization; it never receives
    `serializer.validated_data`, so the UoM block is unreachable from here
    by construction.
    """
    invitation.expires_at = timezone.now() + timedelta(hours=settings.INVITATION_EXPIRE_HOURS)
    invitation.save(update_fields=['expires_at'])

    token = create_invitation_token(
        invitation.email, invitation.organization, invitation.user_role, invitation.token_jti,
    )

    # Built from settings.FRONTEND_URL + settings.REGISTRATION_URL_PATH
    # directly, as `perform_invite` already does -- this keeps the helper
    # clear of `self.request.build_absolute_uri` coupling.
    reg_location = urljoin(settings.FRONTEND_URL, settings.REGISTRATION_URL_PATH)
    invitation_link = f'{reg_location}?token={token}'

    support_addresses = [address for address in settings.SUPPORT_EMAIL_ADDRESS if address]

    invitee_context = {
        'organization_name': invitation.organization.name,
        'role': _role_display(invitation.user_role),
        'invitation_link': invitation_link,
        'expiry_hours': settings.INVITATION_EXPIRE_HOURS,
        'is_reinvite': is_reinvite,
    }
    subject = f"You're invited to join {invitation.organization.name} on Transparent Path"
    send_email(
        invitation.email,
        subject,
        invitee_context,
        'email/coreuser/invitation.txt',
        'email/coreuser/invitation.html',
        cc_email_address=support_addresses,
    )

    # Recipient 2 -- the administrator who sent the original invitation.
    # If `invited_by` is NULL (their account was deleted; SET_NULL), skip
    # this recipient and still send to the invitee and support.
    if is_reinvite and invitation.invited_by_id and invitation.invited_by.email:
        admin_context = {
            'email': invitation.email,
            'organization_name': invitation.organization.name,
            'reinvite_count': invitation.reinvite_count,
            'expires_at': invitation.expires_at,
        }
        admin_subject = f"Invitation re-sent to {invitation.email} for {invitation.organization.name}"
        send_email(
            invitation.invited_by.email,
            admin_subject,
            admin_context,
            'email/coreuser/invitation_reissued_admin.txt',
            'email/coreuser/invitation_reissued_admin.html',
            cc_email_address=support_addresses,
        )

    return invitation_link
