from django.urls import path
from . import views

urlpatterns = [
    path("trades", views.trades),
    path("trades/<uuid:trade_id>", views.trade_detail),
    path("trades/<uuid:trade_id>/amendments", views.amendments),
    path("trades/<uuid:trade_id>/cancellations", views.cancellations),
    path("portfolios", views.portfolios),
    path("portfolios/<slug:portfolio_id>/positions", views.positions),
    path("portfolios/<slug:portfolio_id>/breaches", views.breaches),
    path("portfolios/<slug:portfolio_id>/limits", views.limits),
]
