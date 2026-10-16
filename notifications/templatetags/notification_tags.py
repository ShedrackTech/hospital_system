from django import template

from notifications import services

register = template.Library()


@register.simple_tag(takes_context=True)
def unread_notifications(context):
    """{% unread_notifications as n %} gives the number of unread notifications for the signed-in user."""
    user = context.get("user")
    if user is None:
        request = context.get("request")
        user = getattr(request, "user", None)
    if user is None:
        return 0
    return services.unread_count(user)
