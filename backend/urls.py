from django.urls import path
from .views import *

urlpatterns = [
    path('', auth, name="auth"),
    path('jury-panel/<int:tatami_pk>', jury_panel, name="jury-panel"),
    path('scoring-board/<int:tatami_pk>', scoring_board, name="scoring-board"),
    path('logout', logoutfunc, name="logout"),
    path('admin-dashboard/<int:event_pk>', admin_dashboard, name="admin-dashboard"),
    path('admin-dashboard/<int:event_pk>/tambah-bagan/<int:nomor_tanding_pk>', tambah_bagan, name="tambah-bagan"),
    path('admin-dashboard/<int:event_pk>/tambah-bagan/<int:nomor_tanding_pk>/referchange', tambah_bagan_referchange, name="tambah-bagan-referchange"),
    path('admin-dashboard/<int:event_pk>/tambah-bagan/<int:nomor_tanding_pk>/round-robin', tambah_bagan_round_robin, name="tambah-bagan-round-robin"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>', admin_bagan_detail, name="admin-bagan-detail"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/round-robin', admin_bagan_detail_round_robin, name="admin-bagan-detail-round-robin"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/edit', edit_admin_bagan_detail, name="edit-admin-bagan-detail"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/hapus', hapus_admin_bagan_detail, name="hapus-admin-bagan-detail"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/edit/<int:detailbagan_pk>', admin_edit_detail_bagan, name="edit-detail-bagan"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/control-panel/<int:detailbagan_pk>', control_panel, name="control-panel"),
    path('admin-atlet/<int:event_pk>', admin_atlet, name="admin-atlet"),
    path('admin-nomor-tanding/<int:event_pk>', admin_nomor_tanding, name="admin-nomor-tanding"),
    path('admin-tatami/<int:event_pk>', admin_tatami, name="admin-tatami"),
    path('admin-utusan/<int:event_pk>', admin_utusan, name="admin-utusan"),
    path('admin-perguruan/<int:event_pk>', admin_perguruan, name="admin-perguruan"),
    path('admin-rekapan/<int:event_pk>', admin_rekapan, name="admin-rekapan"),
    path('scoring-board/<int:tatami_pk>/message-retriever', message_retriever, name="message-retriever"),
    path('jury-panel/<int:tatami_pk>/message-retriever', message_retriever_jury, name="message-retriever-jury"),
    path('cp/<int:tatami_pk>/message-retriever', message_retriever_control, name="message-retriever-control"),
    path('control-panel/<int:detailbagan_pk>/message-retriever', message_retriever_admin, name="message-retriever-admin"),
]
