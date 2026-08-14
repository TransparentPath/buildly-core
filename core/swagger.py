from drf_yasg.openapi import Schema, Parameter, IN_QUERY


TOKEN_QUERY_PARAM = Parameter('token', IN_QUERY, type='string', required=True)

DETAIL_RESPONSE = {
    200: Schema(type='object', properties={'detail': Schema(type='string')})
}

SUCCESS_RESPONSE = {
    200: Schema(type='object', properties={'success': Schema(type='boolean')})
}

COREUSER_INVITE_RESPONSE = {
    200: Schema(
        type='object',
        properties={
            'detail': Schema(type='string'),
            'invitations': Schema(type='array', items=Schema(type='string')),
        },
    )
}

COREUSER_INVITE_CHECK_RESPONSE = {
    200: Schema(
        type='object',
        properties={
            'email': Schema(type='string'),
            'organization_name': Schema(type='string'),
            'user_role': Schema(type='string'),
            'expires_at': Schema(type='string', format='date-time'),
        },
    ),
    401: Schema(
        type='object',
        properties={
            'detail': Schema(type='string'),
            'reason': Schema(
                type='string',
                enum=[
                    'invalid',
                    'no_record',
                    'already_registered',
                    'superseded',
                    'expired',
                    'expired_window_closed',
                ],
            ),
            'expires_at': Schema(type='string', format='date-time'),
            'request_window_closes_at': Schema(type='string', format='date-time'),
            'can_request_new': Schema(type='boolean'),
        },
    ),
}

COREUSER_INVITE_RESEND_RESPONSE = {
    200: Schema(
        type='object',
        properties={
            'detail': Schema(type='string'),
            'reason': Schema(
                type='string',
                enum=['sent', 'cooldown', 'cap_reached', 'not_renewable'],
            ),
            'retry_after_seconds': Schema(type='integer'),
        },
    )
}

COREUSER_RESETPASS_RESPONSE = {
    200: Schema(
        type='object',
        properties={'detail': Schema(type='string'), 'count': Schema(type='number')},
    )
}
