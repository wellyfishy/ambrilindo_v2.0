from django.urls import path
from .views import *

urlpatterns = [
    path('', auth, name="auth"),
    path('logout', logoutfunc, name="logout"),
    path('admin-dashboard/<int:event_pk>', admin_dashboard, name="admin-dashboard"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>', admin_bagan_detail, name="admin-bagan-detail"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/control-panel/<int:detailbagan_pk>', control_panel, name="control-panel"),
    path('admin-atlet/<int:event_pk>', admin_atlet, name="admin-atlet"),
    path('admin-tatami/<int:event_pk>', admin_tatami, name="admin-tatami"),
]
