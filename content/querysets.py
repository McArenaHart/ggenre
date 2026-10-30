"""Read-side counts without fetching every viewer or multiplying vote/view joins."""
from django.db.models import Count, IntegerField, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from .models import Content, Vote


def with_content_stats(queryset):
    viewers = (
        Content.viewers.through.objects.filter(content_id=OuterRef("pk"))
        .order_by().values("content_id").annotate(total=Count("pk")).values("total")
    )
    votes = (
        Vote.objects.filter(content_id=OuterRef("pk"))
        .order_by().values("content_id").annotate(total=Count("pk")).values("total")
    )
    return queryset.annotate(
        _view_count=Coalesce(Subquery(viewers[:1], output_field=IntegerField()), Value(0)),
        _vote_count=Coalesce(Subquery(votes[:1], output_field=IntegerField()), Value(0)),
    )
