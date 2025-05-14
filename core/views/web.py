import logging

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.generic.base import TemplateView
from django.template import RequestContext
from django.shortcuts import render

from rest_framework import status
from rest_framework.response import Response
from rest_framework.decorators import api_view
from rest_framework.reverse import reverse

from core.utils import generate_access_tokens
from core.email_utils import send_email

logger = logging.getLogger(__name__)


class IndexView(TemplateView):
    template_name = 'index.html'

    def get_context_data(self, **kwargs):
        context = super(IndexView, self).get_context_data(**kwargs)
        extra_context = {
            'documentation_url': reverse('schema-swagger-ui'),
            'api_url': reverse('schema-swagger-json', kwargs={'format': '.json'}),
        }
        context.update(extra_context)
        return context


@api_view(['POST'])
def send_tive_tracker_order_email(request):
    """
    Send email to Tive for the order specified in the request
    """

    message = request.data['message']

    subject = 'Order for new devices for %s' % message['order_recipient']
    context = {'message': message}
    template_name = 'email/coreuser/order_tive_trackers.txt'
    html_template_name = 'email/coreuser/order_tive_trackers.html'

    send_email(
        settings.TIVE_ORDER_TO_EMAIL_ADDRESS,
        subject,
        context,
        template_name,
        html_template_name,
        cc_email_address=settings.TIVE_ORDER_CC_EMAIL_ADDRESSES,
        from_address=settings.TIVE_ORDER_FROM_EMAIL_ADDRESS,
    )

    return Response({'detail': 'Order for new tive devices was placed successfully on email.'}, status=status.HTTP_200_OK)


@api_view(['POST'])
def send_tracker_turn_off_email(request):
    """
    Send email to Tive to turn off the tracker specified in the request
    """

    message = request.data['message']

    subject = 'Turn off devices'
    context = {'message': message}
    template_name = 'email/coreuser/turn_off_tive_tracker.txt'
    html_template_name = 'email/coreuser/turn_off_tive_tracker.html'

    send_email(
        settings.TIVE_TURN_OFF_EMAIL_ADDRESS,
        subject,
        context,
        template_name,
        html_template_name,
        cc_email_address=settings.TIVE_ORDER_CC_EMAIL_ADDRESSES,
        from_address=settings.TIVE_ORDER_FROM_EMAIL_ADDRESS,
    )

    return Response({'detail': 'Email to turn off device sent successfully.'}, status=status.HTTP_200_OK)


"""
ERROR TEMPLATES and views
"""


def handler404(request, exception):
    context = RequestContext(request)
    err_code = 404 + ": " + exception
    response = render(request, '404.html', {"code": err_code}, context)
    response.status_code = 404
    return response
