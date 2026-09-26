from django.urls import path
from .views import *

urlpatterns = [
    path('', auth, name="auth"),
    path('get-current-atlets/<int:tatami_pk>', get_current_atlets, name="get-current-atlets"),
    path('jury-panel/<int:tatami_pk>', jury_panel, name="jury-panel"),
    path('coach-supervisor/<int:tatami_pk>', coach_supervisor, name="coach-supervisor"),
    path('scoring-board/<int:tatami_pk>', scoring_board, name="scoring-board"),
    path('logout', logoutfunc, name="logout"),
    path('admin-dashboard/<int:event_pk>', admin_dashboard, name="admin-dashboard"),
    path('admin-control/<int:tatami_pk>', admin_control, name="admin-control"),
    path('admin-dashboard/<int:event_pk>/tambah-bagan/<int:nomor_tanding_pk>', tambah_bagan, name="tambah-bagan"),
    path('admin-dashboard/<int:event_pk>/tambah-bagan/<int:nomor_tanding_pk>/referchange', tambah_bagan_referchange, name="tambah-bagan-referchange"),
    path('admin-dashboard/<int:event_pk>/tambah-bagan/<int:nomor_tanding_pk>/round-robin', tambah_bagan_round_robin, name="tambah-bagan-round-robin"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>', admin_bagan_detail, name="admin-bagan-detail"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/round-robin', admin_bagan_detail_round_robin, name="admin-bagan-detail-round-robin"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/edit', edit_admin_bagan_detail, name="edit-admin-bagan-detail"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/hapus', hapus_admin_bagan_detail, name="hapus-admin-bagan-detail"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/edit/<int:detailbagan_pk>', admin_edit_detail_bagan, name="edit-detail-bagan"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/control-panel/<int:detailbagan_pk>/tatami/<int:tatami_pk>/', control_panel, name="control-panel"),
    path('admin-dashboard/<int:event_pk>/bagan-detail/<int:bagan_pk>/control-panel/<int:detailbagan_pk>/tatami/<int:tatami_pk>/team', control_panel_team, name="control-panel-team"),

    # Atlet Modules
    path('admin-atlet/<int:event_pk>', admin_atlet, name="admin-atlet"),
    path('atlet/edit-ajax/', edit_atlet_ajax, name='edit-atlet-ajax'),
    path('atlet/<int:atlet_pk>/nik/', get_atlet_nik, name='get-atlet-nik'),

    path('admin-nomor-tanding/<int:event_pk>', admin_nomor_tanding, name="admin-nomor-tanding"),
    path('roster-counter/<int:event_pk>', roster_counter, name="roster-counter"),
    path('admin-tatami/<int:event_pk>', admin_tatami, name="admin-tatami"),
    path('admin-wasit/<int:event_pk>', admin_wasit, name="admin-wasit"),
    path('admin-dashboard/<int:event_pk>/wasit', admin_wasit, name="admin-wasit-alt"),
    path('admin-dashboard/<int:event_pk>/tatami-manager', admin_tatami_manager, name="tatami-manager"),
    path('tatami-manager/', tatami_manager_entry, name="tatami-manager-entry"),
    path('tatami-manager/<int:event_pk>', admin_tatami_manager, name="tatami-manager-direct"),
    path('admin-utusan/<int:event_pk>', admin_utusan, name="admin-utusan"),
    path('admin-perguruan/<int:event_pk>', admin_perguruan, name="admin-perguruan"),
    path('admin-rekapan/<int:event_pk>', admin_rekapan, name="admin-rekapan"),
    path('summary/<int:event_pk>', summary, name="summary"),
    path('scoring-board/<int:tatami_pk>/message-retriever', message_retriever, name="message-retriever"),
    path('admin-control/<int:tatami_pk>/message-retriever', message_retriever_control, name="message-retriever-control"),
    path('jury-panel/<int:tatami_pk>/message-retriever', message_retriever_jury, name="message-retriever-jury"),
    path('control-panel/<int:tatami_pk>/message-retriever', message_retriever_admin, name="message-retriever-admin"),
    path('coach-supervisor/<int:tatami_pk>/message-retriever', message_retriever_coach_supervisor, name="message-retriever-coach-supervisor"),
    path('lo-kata/', lo_kata_entry, name="lo-kata-entry"),
    path('lo-kata/<int:tatami_pk>', lo_kata_view, name="lo-kata"),
    path('lo-kata/<int:tatami_pk>/message-retriever', message_retriever_lo, name="message-retriever-lo"),

    path('admin-dashboard/<int:event_pk>/control-panel/tatami/<int:tatami_pk>/', control_panel_fest, name="control-panel-fest"),

    # Roster Maker
    path('event/<int:event_pk>/timetable/', timetable_editor, name='timetable-editor'),
    path('event/<int:event_pk>/timetable/save/', timetable_save, name='timetable-save'),
    path('event/<int:event_pk>/timetable/add-tatami/', add_tatami, name='timetable-add-tatami'),
    path('event/<int:event_pk>/timetable/delete-tatami/<int:tatami_pk>/', delete_tatami, name='timetable-delete-tatami'),
    path('event/<int:event_pk>/timetable/add-day/', add_day, name='timetable-add-day'),
    path('event/<int:event_pk>/timetable/delete-day/<int:day_pk>/', delete_day, name='timetable-delete-day'),
    path('event/<int:event_pk>/timetable/kop-surat/', kop_surat_get, name='timetable-kop-surat-get'),
    path('event/<int:event_pk>/timetable/kop-surat/save/', kop_surat_save, name='timetable-kop-surat-save'),
    path('event/<int:event_pk>/timetable/keterangan/save/', keterangan_save, name='timetable-keterangan-save'),

    path('event/<int:event_pk>/timetable/bulk-print/<int:day_pk>/<int:tatami_pk>/', bulk_print_bagan, name='timetable-bulk-print'),
    path('event/<int:event_pk>/timetable/call-sheet/<int:day_pk>/<int:tatami_pk>/', timetable_call_sheet, name='timetable-call-sheet'),
    path('event/<int:event_pk>/timetable/booklet/<int:day_pk>/<int:tatami_pk>/', timetable_tatami_booklet, name='timetable-tatami-booklet'),
    path('event/<int:event_pk>/summary-booklet/', summary_booklet, name='summary-booklet'),

    # API
    path('api/notify-running/<int:detailbagan_pk>/', notify_bagan_running, name='notify-bagan-running'),
    path('api/send-result/<int:detailbagan_pk>/', send_bagan_result, name='send-bagan-result'),
    path('api/sync-queue/status/', sync_queue_status, name='sync-queue-status'),
    path('api/sync-queue/retry/', sync_queue_retry, name='sync-queue-retry'),
    path('api/sync-target/set/', set_sync_target_view, name='set-sync-target'),
    path('api/sync/fetch-hosted-events/', api_fetch_hosted_events, name='api-fetch-hosted-events'),

    # Sync Monitor Dashboard
    path('admin-dashboard/<int:event_pk>/sync-monitor/', sync_monitor_view, name='sync-monitor'),
    path('admin-dashboard/<int:event_pk>/sync-monitor/action/', sync_queue_action_api, name='sync-monitor-action'),
]
