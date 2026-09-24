from .sync_service import pull_athletes_from_hosted, push_bagan_to_hosted, force_sync_results_to_hosted, get_sync_config, set_sync_config, get_event_mapping, set_event_mapping, fetch_hosted_events
from django.shortcuts import render, redirect, get_object_or_404 # type: ignore
from django.template.loader import render_to_string # type: ignore
from django.contrib.auth import authenticate, login, logout # type: ignore
from django.contrib import messages # type: ignore
from .models import * # type: ignore
import openpyxl # type: ignore
from django.db.models import Count, Q # type: ignore
from django.db import transaction # type: ignore
import random # type: ignore
from channels.layers import get_channel_layer # type: ignore
from asgiref.sync import async_to_sync # type: ignore
from django.views.decorators.csrf import csrf_exempt # type: ignore
from django.http import JsonResponse, HttpResponse # type: ignore
from collections import defaultdict # type: ignore
from itertools import groupby # type: ignore
import json # type: ignore
import re
from django.views.decorators.http import require_POST # type: ignore
from .utils import send_to_hosted, send_to_hosted_async, get_kode_realtime 
from openpyxl import Workbook # type: ignore
from openpyxl.styles import Font # type: ignore
from collections import Counter
import re

import io
from django.conf import settings # type: ignore
from playwright.sync_api import sync_playwright # type: ignore

from pypdf import PdfWriter, PdfReader # type: ignore
from django.urls import reverse # type: ignore

import sys
import asyncio
import concurrent.futures


def auth(request):
    if request.GET.get('logout'):
        logout(request)
        request.session.flush()
        return redirect('auth')

    if request.user.is_authenticated:
        role = getattr(request.user, 'role', None)
        if role:
            if role.role_type in ('admin', 'admin_tatami'):
                return redirect('admin-dashboard', event_pk=role.event_id)
            elif role.role_type == 'jury':
                return redirect('jury-panel', tatami_pk=role.tatami_id)
        # authenticated but no valid role somehow — safest is to log them out and let them log back in
        logout(request)
        return redirect('auth')
    
    events = Event.objects.all().order_by('-pk')

    if request.method == 'POST':
        username = request.POST.get('username', '')
        password = request.POST.get('password', '')
        event_pk = request.POST.get('event_pk')

        user = authenticate(request, username=username, password=password)

        if user is not None:
            event = get_object_or_404(Event, pk=event_pk)
            role = getattr(user, 'role', None)

            if not role:
                messages.error(request, "Akun ini tidak memiliki peran yang valid.")
                return redirect('auth')

            if role.role_type == 'admin':
                login(request, user)
                return redirect('admin-dashboard', event_pk=event.pk)

            elif role.role_type == 'admin_tatami':
                if role.event_id != event.pk:
                    messages.error(request, "Anda tidak terdaftar sebagai Admin Tatami untuk event ini.")
                    return redirect('auth')
                login(request, user)
                return redirect('admin-dashboard', event_pk=event.pk)

            elif role.role_type == 'jury':
                if role.event_id != event.pk:
                    messages.error(request, "Anda tidak terdaftar sebagai Juri untuk event ini.")
                    return redirect('auth')
                login(request, user)
                return redirect('jury-panel', tatami_pk=role.tatami_id)

            else:
                messages.error(request, "Peran akun tidak dikenali.")
                return redirect('auth')

        # --- Shared view-only access, no User account ---
        if username.startswith('c') and len(username) > 1 and username[1:].isdigit():
            new_username = username[1:]
            tatami = Tatami.objects.filter(event__pk=new_username, tatami_number=password).first()
            if tatami:
                request.session['view_only_role'] = 'coach_sup'
                request.session['view_only_tatami_pk'] = tatami.pk
                return redirect('coach-supervisor', tatami_pk=tatami.pk)
        elif username.startswith('lo'):
            new_username = username[2:]
            if new_username.startswith('-') or new_username.startswith('_'):
                new_username = new_username[1:]
            if not new_username and event_pk:
                new_username = event_pk
            if new_username and str(new_username).isdigit() and password:
                tatami = Tatami.objects.filter(event__pk=new_username, tatami_number=password).first()
                if tatami:
                    request.session['view_only_role'] = 'lo_kata'
                    request.session['view_only_tatami_pk'] = tatami.pk
                    return redirect('lo-kata', tatami_pk=tatami.pk)
        elif username.isdigit() and password:
            tatami = Tatami.objects.filter(event__pk=username, tatami_number=password).first()
            if tatami:
                request.session['view_only_role'] = 'admin_control'
                request.session['view_only_tatami_pk'] = tatami.pk
                return redirect('admin-control', tatami_pk=tatami.pk)
        elif username.lower().startswith('tm') or username.lower() in ('tatamimanager', 'tatami-manager', 'wasit'):
            new_username = username[2:] if username.lower().startswith('tm') else ''
            if new_username.startswith('-') or new_username.startswith('_'):
                new_username = new_username[1:]
            if not new_username and event_pk:
                new_username = event_pk

            target_event = None
            if new_username and str(new_username).isdigit():
                target_event = Event.objects.filter(pk=new_username).first()
            elif event_pk:
                target_event = Event.objects.filter(pk=event_pk).first()

            if target_event:
                request.session['view_only_role'] = 'tatami_manager'
                request.session['view_only_event_pk'] = target_event.pk

                tatami_target = None
                if password and str(password).strip().isdigit():
                    tatami_target = Tatami.objects.filter(event=target_event, tatami_number=int(password.strip())).first()

                if tatami_target:
                    request.session['view_only_tatami_pk'] = tatami_target.pk
                    return redirect(f"{reverse('tatami-manager', args=[target_event.pk])}?tatami={tatami_target.pk}")
                return redirect('tatami-manager', event_pk=target_event.pk)

        messages.error(request, "Username atau password salah!")
        return redirect('auth')

    context = {'events': events}
    return render(request, 'auth/auth.html', context)

def admin_control(request, tatami_pk):
    tatami = Tatami.objects.get(pk=tatami_pk)
    event = tatami.event
    context = {
        'tatami': tatami,
        'on': 'control',
        'event': event,
    }
    return render(request, 'jury/admin-control.html', context)

def jury_panel(request, tatami_pk):
    jury = Jury.objects.get(user=request.user)
    detail_bagan = jury.tatami.detail_bagan
    tatami = Tatami.objects.get(pk=tatami_pk)

    context = {
        'jury': jury,
        'detail_bagan': detail_bagan,
        'tatami': tatami,
    }
    return render(request, 'jury/jury-panel.html', context)

def coach_supervisor(request, tatami_pk):
    tatami = get_object_or_404(
        Tatami.objects.select_related(
            'event',
            'detail_bagan__bagan__nomor_tanding',
            'detail_bagan__atlet1__perguruan',
            'detail_bagan__atlet1__utusan',
            'detail_bagan__atlet2__perguruan',
            'detail_bagan__atlet2__utusan',
        ),
        pk=tatami_pk
    )
    detail_bagan = tatami.detail_bagan
    bagan = detail_bagan.bagan if detail_bagan else None

    context = {
        'tatami': tatami,
        'detail_bagan': detail_bagan,
        'bagan': bagan,
    }
    return render(request, 'jury/coach-supervisor.html', context)

@csrf_exempt
def message_retriever_jury(request, tatami_pk):
    if request.method == 'POST':
        action = request.POST.get('action')
        details = request.POST.get('details')

        group_name = f"juryroom_{tatami_pk}"
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "broadcast_command",
                "message": action,
                "details": details,
            }
        )

        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def message_retriever_admin(request, tatami_pk):
    if request.method == 'POST':
        action = request.POST.get('action')
        details = request.POST.get('details')

        group_name = f"control_{tatami_pk}"
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "broadcast_command",
                "message": action,
                "details": details,
            }
        )

        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def message_retriever_control(request, tatami_pk):
    if request.method == 'POST':
        action = request.POST.get('action')
        details = request.POST.get('details')

        group_name = f"admin_control_{tatami_pk}"
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "broadcast_command",
                "message": action,
                "details": details,
            }
        )

        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

@csrf_exempt
def message_retriever_coach_supervisor(request, tatami_pk):
    if request.method == 'POST':
        action = request.POST.get('action')
        details = request.POST.get('details')

        group_name = f"coachroom_{tatami_pk}"
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "broadcast_command",
                "message": action,
                "details": details,
            }
        )

        if action == 'coach-supervisor':
            side = 'aka'
            val = '1'
            try:
                parsed = json.loads(details) if isinstance(details, str) else details
                if isinstance(parsed, (list, tuple)) and len(parsed) >= 2:
                    side = str(parsed[0]).lower()
                    val = str(parsed[1])
            except Exception:
                pass
            async_to_sync(channel_layer.group_send)(
                f"control_{tatami_pk}",
                {"type": "broadcast_command", "message": "coach-supervisor", "details": [side, val]}
            )
            async_to_sync(channel_layer.group_send)(
                f"admin_control_{tatami_pk}",
                {"type": "broadcast_command", "message": "coach-supervisor", "details": [side, val]}
            )
            async_to_sync(channel_layer.group_send)(
                f"scoring_{tatami_pk}",
                {"type": "broadcast_command", "message": "coach-supervisor", "details": [side, val]}
            )
            async_to_sync(channel_layer.group_send)(
                f"scoring_{tatami_pk}",
                {"type": "broadcast_command", "message": "vr", "details": f"{side}-request-{val}"}
            )
        elif action == 'coach-supervisor-cancel':
            side = 'aka'
            try:
                parsed = json.loads(details) if isinstance(details, str) else details
                side = str(parsed).lower() if isinstance(parsed, str) else str(parsed[0]).lower()
            except Exception:
                pass
            async_to_sync(channel_layer.group_send)(
                f"control_{tatami_pk}",
                {"type": "broadcast_command", "message": "coach-supervisor-cancel", "details": side}
            )
            async_to_sync(channel_layer.group_send)(
                f"admin_control_{tatami_pk}",
                {"type": "broadcast_command", "message": "coach-supervisor-cancel", "details": side}
            )
            async_to_sync(channel_layer.group_send)(
                f"scoring_{tatami_pk}",
                {"type": "broadcast_command", "message": "coach-supervisor-cancel", "details": side}
            )

        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

OFFICIAL_KATA_LIST = [
    "Blank", "Anan", "Anan Dai", "Ananko", "Aoyagi", "Bassai", "Bassai Dai", "Bassai Sho",
    "Chatanyara Kusanku", "Chibana No Kushanku", "Chinte", "Chinto", "Enpi", "Fukyugata Ichi",
    "Fukvugata Ni", "Gankaku", "Garyu", "Gekisai (Geksai) 1", "Gekisai (Geksai) 2", "Gojushiho",
    "Gojushiho Dai", "Gojushiho Sho", "Hakucho", "Hangetsu", "Haufa (Haffa)", "Heian Shodan",
    "Heian Nidan", "Heian Sandan", "Heian Yondan", "Heian Godan", "Heiku", "Ishimine Bassai",
    "Itosu Rohai Shodan", "Itosu Rohai Nidan", "Itosu Rohai Sandan", "Jiin", "Jion", "Jitte",
    "Juroku", "Kanchin", "Kanku Dai", "Kanku Sho", "Kanshu", "Kishimoto No Kushanku",
    "Kousoukun", "Kousoukun Dai", "Kousoukun Sho", "Kururunfa", "Kusanku", "Kyan No Chinto",
    "Kyan No Wanshu", "Matsukaze", "Matsumura Bassai", "Matsumura Rohai", "Meikyo", "Myojo",
    "Naifanchin Shodan", "Naifanchin Nidan", "Naifanchin Sandan", "Naihanchi", "Nijushiho",
    "Nipaipo", "Niseishi", "Ohan", "Ohan Dai", "Oyadomari No Passai", "Pachu", "Paiku",
    "Papuren", "Passai", "Pinan Shodan", "Pinan Nidan", "Pinan Sandan", "Pinan Yondan",
    "Pinan Godan", "Rohai", "Saifa", "Sanchin", "Sansai", "Sanseiru", "Sanseni", "Seichin",
    "Seienchin (Seiyunchin)", "Seipai", "Seiryu", "Seishan", "Seisan (Sesan)", "Shiho Kousoukun",
    "Shinpa", "Shinsei", "Shisochin", "Sochin", "Suparinpei", "Tekki Shodan", "Tekki Nidan",
    "Tekki Sandan", "Tensho", "Tomari Bassai", "Unshu", "Unsu", "Useishi", "Wankan", "Wanshu"
]

@csrf_exempt
def message_retriever_lo(request, tatami_pk):
    if request.method == 'GET':
        action = request.GET.get('action')
        if action == 'get_match_detail':
            detailbagan_pk = request.GET.get('detailbagan_pk')
            match_obj = DetailBagan.objects.filter(pk=detailbagan_pk).select_related(
                'bagan__nomor_tanding', 'atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami'
            ).first()
            if not match_obj:
                return JsonResponse({'status': 'error', 'message': 'Partai tidak ditemukan.'}, status=404)

            from .utils import get_athlete_kata_records, check_is_final
            kata_history_aka = get_athlete_kata_records(match_obj.atlet1, match_obj) if match_obj.atlet1 else {}
            kata_history_ao = get_athlete_kata_records(match_obj.atlet2, match_obj) if match_obj.atlet2 else {}
            is_final = check_is_final(match_obj)
            active_tatami = Tatami.objects.filter(detail_bagan=match_obj).first()

            return JsonResponse({
                'status': 'success',
                'match_pk': match_obj.pk,
                'urutan': match_obj.urutan,
                'round': match_obj.round,
                'category_name': str(match_obj.bagan.nomor_tanding) if match_obj.bagan and match_obj.bagan.nomor_tanding else (match_obj.bagan.nama_bagan if match_obj.bagan else ''),
                'atlet1': {
                    'id': match_obj.atlet1.pk if match_obj.atlet1 else None,
                    'nama': match_obj.atlet1.nama_atlet if match_obj.atlet1 else 'BYE',
                    'perguruan': match_obj.atlet1.perguruan.nama_perguruan if (match_obj.atlet1 and match_obj.atlet1.perguruan) else '-',
                    'utusan': match_obj.atlet1.utusan.nama_utusan if (match_obj.atlet1 and match_obj.atlet1.utusan) else '-',
                    'logo': match_obj.atlet1.utusan.logo.url if (match_obj.atlet1 and match_obj.atlet1.utusan and match_obj.atlet1.utusan.logo) else None,
                },
                'atlet2': {
                    'id': match_obj.atlet2.pk if match_obj.atlet2 else None,
                    'nama': match_obj.atlet2.nama_atlet if match_obj.atlet2 else 'BYE',
                    'perguruan': match_obj.atlet2.perguruan.nama_perguruan if (match_obj.atlet2 and match_obj.atlet2.perguruan) else '-',
                    'utusan': match_obj.atlet2.utusan.nama_utusan if (match_obj.atlet2 and match_obj.atlet2.utusan) else '-',
                    'logo': match_obj.atlet2.utusan.logo.url if (match_obj.atlet2 and match_obj.atlet2.utusan and match_obj.atlet2.utusan.logo) else None,
                },
                'kata1': match_obj.kata1 or '0 - Blank',
                'kata2': match_obj.kata2 or '0 - Blank',
                'kata_history_aka': kata_history_aka,
                'kata_history_ao': kata_history_ao,
                'is_final': is_final,
                'selesai': match_obj.selesai,
                'pemenang': match_obj.pemenang,
                'active_tatami_number': active_tatami.tatami_number if active_tatami else None,
                'is_active_on_current_tatami': bool(active_tatami and str(active_tatami.pk) == str(tatami_pk)),
            })
        return JsonResponse({'error': 'Invalid action'}, status=400)

    if request.method == 'POST':
        action = request.POST.get('action')
        channel_layer = get_channel_layer()

        if action == 'save_match_kata':
            detailbagan_pk = request.POST.get('detailbagan_pk')
            kata1 = request.POST.get('kata1')
            kata2 = request.POST.get('kata2')
            push_live = request.POST.get('push_live') in ('1', 'true', 'True')

            match_obj = DetailBagan.objects.filter(pk=detailbagan_pk).select_related(
                'atlet1', 'atlet2', 'bagan__nomor_tanding'
            ).first()
            if not match_obj:
                return JsonResponse({'status': 'error', 'message': 'Partai tidak ditemukan.'}, status=404)

            update_fields = []
            if kata1 is not None:
                match_obj.kata1 = kata1
                update_fields.append('kata1')
            if kata2 is not None:
                match_obj.kata2 = kata2
                update_fields.append('kata2')
            if update_fields:
                match_obj.save(update_fields=update_fields)

            has_k1 = bool(match_obj.kata1 and match_obj.kata1 != '0 - Blank' and match_obj.kata1.strip())
            has_k2 = bool(match_obj.kata2 and match_obj.kata2 != '0 - Blank' and match_obj.kata2.strip())
            is_complete = has_k1 and has_k2

            tatami = Tatami.objects.filter(pk=tatami_pk).first()
            active_tatamis = list(Tatami.objects.filter(detail_bagan=match_obj))
            target_tatami_pks = set(t.pk for t in active_tatamis)
            if tatami and tatami.detail_bagan_id == match_obj.pk:
                target_tatami_pks.add(tatami.pk)

            # If match is active on any arena, broadcast immediately to scoring board, control panel, etc.
            for tpk in target_tatami_pks:
                for grp in [f"scoring_{tpk}", f"control_{tpk}", f"admin_control_{tpk}", f"juryroom_{tpk}"]:
                    if match_obj.kata1:
                        async_to_sync(channel_layer.group_send)(
                            grp,
                            {
                                "type": "broadcast_command",
                                "message": "aka-kata-kirim",
                                "details": match_obj.kata1,
                            }
                        )
                    if match_obj.kata2:
                        async_to_sync(channel_layer.group_send)(
                            grp,
                            {
                                "type": "broadcast_command",
                                "message": "ao-kata-kirim",
                                "details": match_obj.kata2,
                            }
                        )

            # Broadcast update to LO kata clients
            for grp in [f"lokata_{tatami_pk}", "lokata_all"]:
                try:
                    async_to_sync(channel_layer.group_send)(
                        grp,
                        {
                            "type": "broadcast_command",
                            "message": "match_kata_updated",
                            "details": {
                                "match_pk": match_obj.pk,
                                "kata1": match_obj.kata1,
                                "kata2": match_obj.kata2,
                                "has_kata1": has_k1,
                                "has_kata2": has_k2,
                                "is_kata_complete": is_complete,
                            }
                        }
                    )
                except Exception:
                    pass

            return JsonResponse({
                'status': 'success',
                'message': f"Kata partai #{match_obj.urutan} berhasil disimpan.",
                'match_pk': match_obj.pk,
                'kata1': match_obj.kata1,
                'kata2': match_obj.kata2,
                'has_kata1': has_k1,
                'has_kata2': has_k2,
                'is_kata_complete': is_complete,
                'pushed_live': bool(target_tatami_pks),
            })

        # Legacy LO single-athlete submission handler
        details = request.POST.get('details')
        atlet = request.POST.get('atlet')

        if not atlet:
            if action == 'aka-kata-kirim':
                atlet = 'aka'
            elif action == 'ao-kata-kirim':
                atlet = 'ao'

        tatami = Tatami.objects.filter(pk=tatami_pk).select_related(
            'detail_bagan__bagan__nomor_tanding',
            'detail_bagan__atlet1',
            'detail_bagan__atlet2',
        ).first()
        kata_history_aka = {}
        kata_history_ao = {}
        if tatami and tatami.detail_bagan and details:
            db = tatami.detail_bagan
            if atlet == 'aka':
                db.kata1 = details
                db.save(update_fields=['kata1'])
            elif atlet == 'ao':
                db.kata2 = details
                db.save(update_fields=['kata2'])

            from .utils import get_athlete_kata_records
            kata_history_aka = get_athlete_kata_records(db.atlet1, db)
            kata_history_ao = get_athlete_kata_records(db.atlet2, db)

        cmd = action or ('aka-kata-kirim' if atlet == 'aka' else 'ao-kata-kirim')

        for grp in [f"scoring_{tatami_pk}", f"control_{tatami_pk}", f"admin_control_{tatami_pk}", f"juryroom_{tatami_pk}"]:
            async_to_sync(channel_layer.group_send)(
                grp,
                {
                    "type": "broadcast_command",
                    "message": cmd,
                    "details": details,
                }
            )

        async_to_sync(channel_layer.group_send)(
            f"lokata_{tatami_pk}",
            {
                "type": "broadcast_command",
                "message": "kata_updated",
                "details": {
                    "atlet": atlet,
                    "kata": details,
                    "command": cmd,
                    "kata_history_aka": kata_history_aka,
                    "kata_history_ao": kata_history_ao,
                }
            }
        )

        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid method'}, status=405)


def lo_kata_entry(request):
    if request.method == 'POST':
        username = request.POST.get('username', '').strip().lower()
        password = request.POST.get('password', '').strip()
        event_pk = request.POST.get('event_pk')

        target_event_pk = event_pk
        if not target_event_pk:
            if username.startswith('lo'):
                u = username[2:]
                if u.startswith('-') or u.startswith('_'):
                    u = u[1:]
                target_event_pk = u
            else:
                target_event_pk = username

        tatami = Tatami.objects.filter(event__pk=target_event_pk, tatami_number=password).first()
        if tatami:
            request.session['view_only_role'] = 'lo_kata'
            request.session['view_only_tatami_pk'] = tatami.pk
            return redirect('lo-kata', tatami_pk=tatami.pk)
        else:
            messages.error(request, "Tatami tidak ditemukan! Periksa Event ID dan Nomor Tatami.")
            return redirect('lo-kata-entry')

    # If switch is explicitly requested
    if request.GET.get('switch'):
        request.session.pop('view_only_role', None)
        request.session.pop('view_only_tatami_pk', None)

    # If already set in session, go to tatami page
    if request.session.get('view_only_role') == 'lo_kata' and request.session.get('view_only_tatami_pk'):
        tatami_pk = request.session['view_only_tatami_pk']
        if Tatami.objects.filter(pk=tatami_pk).exists():
            return redirect('lo-kata', tatami_pk=tatami_pk)

    events = Event.objects.all().order_by('-pk')
    return render(request, 'lo/kata-login.html', {'events': events})


def lo_kata_view(request, tatami_pk):
    tatami = get_object_or_404(
        Tatami.objects.select_related(
            'event',
            'detail_bagan__bagan__nomor_tanding',
            'detail_bagan__atlet1__perguruan',
            'detail_bagan__atlet1__utusan',
            'detail_bagan__atlet2__perguruan',
            'detail_bagan__atlet2__utusan',
        ),
        pk=tatami_pk
    )
    request.session['view_only_role'] = 'lo_kata'
    request.session['view_only_tatami_pk'] = tatami.pk

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.GET.get('ajax') == '1'
    if is_ajax and request.GET.get('action') == 'get_match_detail':
        detailbagan_pk = request.GET.get('detailbagan_pk')
        match_obj = DetailBagan.objects.filter(pk=detailbagan_pk, bagan__event=tatami.event).select_related(
            'bagan__nomor_tanding', 'atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami'
        ).first()
        if not match_obj:
            return JsonResponse({'status': 'error', 'message': 'Partai tidak ditemukan.'}, status=404)

        from .utils import get_athlete_kata_records, check_is_final
        kata_history_aka = get_athlete_kata_records(match_obj.atlet1, match_obj) if match_obj.atlet1 else {}
        kata_history_ao = get_athlete_kata_records(match_obj.atlet2, match_obj) if match_obj.atlet2 else {}
        is_final = check_is_final(match_obj)
        active_tatami = Tatami.objects.filter(detail_bagan=match_obj).first() if not match_obj.selesai else None
        if active_tatami and active_tatami.detail_bagan and active_tatami.detail_bagan.selesai:
            active_tatami = None

        return JsonResponse({
            'status': 'success',
            'match_pk': match_obj.pk,
            'urutan': match_obj.urutan,
            'round': match_obj.round,
            'category_name': str(match_obj.bagan.nomor_tanding) if match_obj.bagan and match_obj.bagan.nomor_tanding else (match_obj.bagan.nama_bagan if match_obj.bagan else ''),
            'atlet1': {
                'id': match_obj.atlet1.pk if match_obj.atlet1 else None,
                'nama': match_obj.atlet1.nama_atlet if match_obj.atlet1 else 'BYE',
                'perguruan': match_obj.atlet1.perguruan.nama_perguruan if (match_obj.atlet1 and match_obj.atlet1.perguruan) else '-',
                'utusan': match_obj.atlet1.utusan.nama_utusan if (match_obj.atlet1 and match_obj.atlet1.utusan) else '-',
                'logo': match_obj.atlet1.utusan.logo.url if (match_obj.atlet1 and match_obj.atlet1.utusan and match_obj.atlet1.utusan.logo) else None,
            },
            'atlet2': {
                'id': match_obj.atlet2.pk if match_obj.atlet2 else None,
                'nama': match_obj.atlet2.nama_atlet if match_obj.atlet2 else 'BYE',
                'perguruan': match_obj.atlet2.perguruan.nama_perguruan if (match_obj.atlet2 and match_obj.atlet2.perguruan) else '-',
                'utusan': match_obj.atlet2.utusan.nama_utusan if (match_obj.atlet2 and match_obj.atlet2.utusan) else '-',
                'logo': match_obj.atlet2.utusan.logo.url if (match_obj.atlet2 and match_obj.atlet2.utusan and match_obj.atlet2.utusan.logo) else None,
            },
            'kata1': match_obj.kata1 or '0 - Blank',
            'kata2': match_obj.kata2 or '0 - Blank',
            'kata_history_aka': kata_history_aka,
            'kata_history_ao': kata_history_ao,
            'is_final': is_final,
            'selesai': match_obj.selesai,
            'pemenang': match_obj.pemenang,
            'active_tatami_number': active_tatami.tatami_number if (active_tatami and not match_obj.selesai) else None,
            'is_active_on_current_tatami': bool(active_tatami and active_tatami.pk == tatami.pk and not match_obj.selesai),
        })

    all_tatamis = list(Tatami.objects.filter(event=tatami.event).select_related('detail_bagan').order_by('tatami_number'))
    all_bagans = list(Bagan.objects.filter(event=tatami.event).select_related('nomor_tanding').order_by('kode', 'nama_bagan'))

    bagan_pk = request.GET.get('bagan')
    selected_bagan = None
    if bagan_pk:
        selected_bagan = next((b for b in all_bagans if str(b.pk) == str(bagan_pk)), None)
    if not selected_bagan and tatami.detail_bagan and tatami.detail_bagan.bagan:
        selected_bagan = tatami.detail_bagan.bagan
    if not selected_bagan:
        selected_bagan = next((b for b in all_bagans if b.tipe_tanding == '1'), None) or (all_bagans[0] if all_bagans else None)

    detail_bagans_round_1 = []
    detail_bagans_round_2 = []
    detail_bagans_round_3 = []
    detail_bagans_round_4 = []
    detail_bagan_round_5 = None
    referchange = False

    active_tatami_map = {
        t.detail_bagan_id: t for t in all_tatamis 
        if t.detail_bagan_id and t.detail_bagan and not t.detail_bagan.selesai
    }

    def annotate_kata_match(m):
        m.active_on_tatami = active_tatami_map.get(m.pk) if not m.selesai else None
        m.has_kata1 = bool(m.kata1 and m.kata1 != '0 - Blank' and m.kata1.strip())
        m.has_kata2 = bool(m.kata2 and m.kata2 != '0 - Blank' and m.kata2.strip())
        m.is_kata_complete = m.has_kata1 and m.has_kata2
        return m

    if selected_bagan:
        referchange = 'REFERCHANGE' in selected_bagan.nama_bagan.upper()
        detail_bagans_round_1 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=1)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .order_by('urutan')
        )
        detail_bagans_round_2 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=2)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .order_by('urutan')
        )
        detail_bagans_round_3 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=3)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .order_by('urutan')
        )
        detail_bagans_round_4 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=4)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .order_by('urutan')
        )
        detail_bagan_round_5 = (
            DetailBagan.objects.filter(bagan=selected_bagan, round=5)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .first()
        )

        all_matches = detail_bagans_round_1 + detail_bagans_round_2 + detail_bagans_round_3 + detail_bagans_round_4
        for m in all_matches:
            annotate_kata_match(m)
        if detail_bagan_round_5:
            annotate_kata_match(detail_bagan_round_5)
    else:
        all_matches = []

    total_matches = len(all_matches)
    ready_matches = sum(1 for m in all_matches if m.is_kata_complete)
    partial_matches = sum(1 for m in all_matches if (m.has_kata1 or m.has_kata2) and not m.is_kata_complete)
    pending_matches = sum(1 for m in all_matches if not m.has_kata1 and not m.has_kata2)
    finished_matches = sum(1 for m in all_matches if m.selesai)

    indexed_katas = [f"{idx} - {name}" for idx, name in enumerate(OFFICIAL_KATA_LIST)]

    context = {
        'tatami': tatami,
        'event': tatami.event,
        'all_tatamis': all_tatamis,
        'all_bagans': all_bagans,
        'selected_bagan': selected_bagan,
        'detail_bagans_round_1': detail_bagans_round_1,
        'detail_bagans_round_2': detail_bagans_round_2,
        'detail_bagans_round_3': detail_bagans_round_3,
        'detail_bagans_round_4': detail_bagans_round_4,
        'detail_bagan_round_5': detail_bagan_round_5,
        'referchange': referchange,
        'kata_list': indexed_katas,
        'kata_list_json': json.dumps(indexed_katas),
        'metrics': {
            'total_matches': total_matches,
            'ready_matches': ready_matches,
            'partial_matches': partial_matches,
            'pending_matches': pending_matches,
            'finished_matches': finished_matches,
            'total_bagan': len(all_bagans),
            'total_tatami': len(all_tatamis),
        }
    }
    return render(request, 'lo/kata.html', context)

def get_current_atlets(request, tatami_pk):
    tatami = Tatami.objects.get(pk=tatami_pk)
    detail_bagan = tatami.detail_bagan
    data = {
        'tatami': tatami.pk,
        'detail_bagan': detail_bagan.pk,
        'atlet1_nama': detail_bagan.atlet1.nama_atlet,
        'atlet1_perguruan': detail_bagan.atlet1.perguruan,
        'atlet1_utusan': detail_bagan.atlet1.utusan,
        'atlet1_vr': detail_bagan.vr1,
        'atlet2_nama': detail_bagan.atlet2.nama_atlet,
        'atlet2_perguruan': detail_bagan.atlet2.perguruan,
        'atlet2_utusan': detail_bagan.atlet2.utusan,
        'atlet2_vr': detail_bagan.vr2,
    }

    return JsonResponse(data)

def logoutfunc(request):
    logout(request)
    return redirect('auth')


# ==========================================================
# ADMIN DASHBOARD ACTION HANDLERS
# ==========================================================

def _handle_export_bagan(request, event):
    bagan_pks = request.POST.getlist('bagan_pk')

    if 'semua' in bagan_pks:
        bagan_pks = list(Bagan.objects.filter(event=event).values_list('pk', flat=True))

    if not bagan_pks:
        messages.error(request, "Pilih minimal satu bagan untuk diekspor ke Excel.")
        return redirect('admin-dashboard', event_pk=event.pk)

    wb = Workbook()
    ws = wb.active
    ws.title = 'Bagan Export'

    headers = [
        'Kode', 'Nama Bagan', 'Nama Nomor Tanding', 'Bagan PK', 'Detail PK',
        'Round', 'Urutan', 'Atlet 1', 'Perguruan 1', 'Perwakilan 1',
        'Atlet 2', 'Perguruan 2', 'Perwakilan 2', 'Tipe Tanding', 'Pool',
        'VR 1', 'VR 2', 'Score 1', 'Score 2', 'Status Selesai', 'Pemenang', 'Kode Realtime'
    ]
    ws.append(headers)

    for cell in ws[1]:
        cell.font = Font(bold=True)

    for bagan_pk in bagan_pks:
        bagan = Bagan.objects.filter(pk=bagan_pk).select_related('nomor_tanding').first()
        if not bagan:
            continue
        dbs = DetailBagan.objects.filter(bagan=bagan).select_related(
            'atlet1__perguruan', 'atlet1__utusan',
            'atlet2__perguruan', 'atlet2__utusan'
        ).order_by('round', 'urutan')
        for db in dbs:
            nama1 = db.atlet1.nama_atlet if db.atlet1 else None
            perguruan1 = db.atlet1.perguruan.nama_perguruan if (db.atlet1 and db.atlet1.perguruan) else None
            perwakilan1 = db.atlet1.utusan.nama_utusan if (db.atlet1 and db.atlet1.utusan) else None
            nama2 = db.atlet2.nama_atlet if db.atlet2 else None
            perguruan2 = db.atlet2.perguruan.nama_perguruan if (db.atlet2 and db.atlet2.perguruan) else None
            perwakilan2 = db.atlet2.utusan.nama_utusan if (db.atlet2 and db.atlet2.utusan) else None
            nt_nama = bagan.nomor_tanding.nama_nomor_tanding if bagan.nomor_tanding else ""
            ws.append([
                bagan.kode,
                bagan.nama_bagan,
                nt_nama,
                bagan.pk,
                db.pk,
                db.round,
                db.urutan,
                nama1,
                perguruan1,
                perwakilan1,
                nama2,
                perguruan2,
                perwakilan2,
                bagan.tipe_tanding,
                bagan.pool,
                db.vr1,
                db.vr2,
                db.score1,
                db.score2,
                db.selesai,
                db.pemenang,
                get_kode_realtime(db),
            ])

    for col_cells in ws.columns:
        length = max(len(str(cell.value)) if cell.value is not None else 0 for cell in col_cells)
        ws.column_dimensions[col_cells[0].column_letter].width = length + 2

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="bagan_export_{event.pk}.xlsx"'
    wb.save(response)
    return response


def _get_sync_redirect(request, event):
    redirect_url = request.POST.get('redirect_url')
    if redirect_url:
        return redirect(redirect_url)
    referer = request.META.get('HTTP_REFERER')
    if referer:
        return redirect(referer)
    return redirect('sync-monitor', event_pk=event.pk)


def _handle_set_event_mapping(request, event):
    hosted_event_id = request.POST.get('hosted_event_id')
    hosted_event_name = (request.POST.get('hosted_event_name') or '').strip()
    if not hosted_event_id:
        messages.error(request, "Pilih salah satu event dari server web.")
        return _get_sync_redirect(request, event)

    success, msg = set_event_mapping(event.pk, hosted_event_id, hosted_event_name)
    if success:
        messages.success(request, msg)
        local_name = (event.nama_event or '').strip()
        if local_name.lower() != hosted_event_name.lower():
            messages.warning(
                request,
                f"Perhatian: Nama event di lokal ('{local_name}') berbeda dengan nama di web ('{hosted_event_name}'). "
                f"Sinkronisasi data akan dihubungkan ke '{hosted_event_name}' (ID {hosted_event_id})."
            )
    else:
        messages.error(request, msg)
    return _get_sync_redirect(request, event)


def _handle_pull_atlet(request, event):
    success, msg = pull_athletes_from_hosted(event.pk)
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return _get_sync_redirect(request, event)


def _handle_push_bagan(request, event):
    bagan_pks = request.POST.getlist('bagan_pk')
    if not bagan_pks:
        messages.error(request, "Pilih minimal satu bagan untuk dikirim ke web server.")
        return _get_sync_redirect(request, event)
    success, msg = push_bagan_to_hosted(event.pk, bagan_pks=bagan_pks)
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return _get_sync_redirect(request, event)


def _handle_force_sync_results(request, event):
    success, msg = force_sync_results_to_hosted(event.pk)
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return _get_sync_redirect(request, event)


def _handle_bob_bagan(request, event):
    bagan_pks = request.POST.getlist('bagan_pk')
    tipe_shuffle = request.POST.get('shuffle_type')
    nama_bob = request.POST.get('nama_bob')

    if not nama_bob:
        messages.error(request, "Nama kategori Best of the Best wajib diisi.")
        return redirect('admin-dashboard', event_pk=event.pk)

    bagan_list = list(Bagan.objects.filter(pk__in=bagan_pks))
    atlets_temp_all = [b.juara_1 for b in bagan_list if b.juara_1]

    if not atlets_temp_all:
        messages.error(request, "Tidak ada juara 1 pada bagan yang dipilih.")
        return redirect('admin-dashboard', event_pk=event.pk)

    group_field = 'utusan' if tipe_shuffle == 'kontingen' else 'perguruan'

    nomor_tanding, created = NomorTanding.objects.get_or_create(
        event=event,
        nama_nomor_tanding=nama_bob,
        defaults={'is_bob': True}
    )
    if not created and not nomor_tanding.is_bob:
        nomor_tanding.is_bob = True
        nomor_tanding.save(update_fields=['is_bob'])

    bob_atlets = []
    for atlet in atlets_temp_all:
        new_atlet, _ = Atlet.objects.update_or_create(
            event=event,
            nama_atlet=atlet.nama_atlet,
            nomor_tanding=nomor_tanding,
            utusan=atlet.utusan,
            defaults={
                'kode_atlet': atlet.kode_atlet,
                'nik': atlet.nik,
                'perguruan': atlet.perguruan,
            }
        )
        bob_atlets.append(new_atlet)

    atlets_temp_all = bob_atlets

    group_counts_counter = Counter(
        getattr(atlet, f'{group_field}_id') for atlet in atlets_temp_all
    )
    group_counts = sorted(group_counts_counter.items(), key=lambda x: -x[1])

    def shuffle_same_counts(counts):
        result = []
        for _, g in groupby(counts, key=lambda x: x[1]):
            block = list(g)
            if len(block) > 1:
                random.shuffle(block)
            result.extend(block)
        return result

    group_counts = shuffle_same_counts(group_counts)

    total_bob = len(atlets_temp_all)
    if 0 < total_bob < 17:
        perulangan = 1
    elif 16 < total_bob < 33:
        perulangan = 2
    elif 32 < total_bob < 49:
        perulangan = 3
    elif 48 < total_bob < 65:
        perulangan = 4
    else:
        perulangan = 1

    if perulangan > 1 and perulangan % 2 != 0:
        perulangan += 1

    POOL_LETTERS = ['A', 'B', 'C', 'D']
    if perulangan > 1:
        pool_atlets = split_athletes_into_pools(atlets_temp_all, perulangan, group_field=group_field)
    else:
        pool_atlets = [atlets_temp_all]

    if perulangan > 1:
        final_bagan, _, _ = build_full_bracket(
            event, nomor_tanding, f'{nama_bob} - Final', pool=0,
            atlets_temp=[], group_field=group_field
        )
        final_bagan.tipe_tanding = '2'  # BOB is always Kumite
        final_bagan.is_bob = True
        final_bagan.save(update_fields=['tipe_tanding', 'is_bob'])

    pool_round5_dbs = []
    for i in range(1, perulangan + 1):
        nama_bagan = f'{nama_bob} - Pool {POOL_LETTERS[i-1]}' if perulangan > 1 else nama_bob
        atlets_temp = pool_atlets[i-1] if perulangan > 1 else atlets_temp_all

        bagan, round_5, _ = build_full_bracket(
            event, nomor_tanding, nama_bagan, i,
            atlets_temp=atlets_temp, group_field=group_field
        )
        bagan.tipe_tanding = '2'
        bagan.is_bob = True
        bagan.save(update_fields=['tipe_tanding', 'is_bob'])
        pool_round5_dbs.append(round_5)

    messages.success(request, f"Bagan '{nama_bob}' berhasil dibuat.")
    return redirect('admin-dashboard', event_pk=event.pk)


def _handle_drawing_bagan(request, event):
    nomor_tanding_pks = request.POST.getlist('nomor_tanding_pk')
    tipe_shuffle = request.POST.get('shuffle_type')
    vr_nomor_tanding_pks = set(request.POST.getlist('vr_nomor_tanding_pks'))
    if not nomor_tanding_pks:
        messages.error(request, "Pilih minimal satu nomor tanding untuk dilakukan drawing.")
        return redirect('admin-dashboard', event_pk=event.pk)

    # Hanya nomor tanding tournament yang di-drawing (abaikan festival dan BOB)
    if 'semua' in nomor_tanding_pks:
        nomor_tanding_list = list(
            NomorTanding.objects.filter(event=event)
            .exclude(nama_nomor_tanding__icontains='festival')
            .exclude(is_bob=True)
        )
    else:
        nomor_tanding_list = list(
            NomorTanding.objects.filter(pk__in=nomor_tanding_pks)
            .exclude(nama_nomor_tanding__icontains='festival')
            .exclude(is_bob=True)
        )

    if not nomor_tanding_list:
        messages.warning(request, "Tidak ada nomor tanding kategori tournament yang dipilih untuk drawing (kategori festival diabaikan).")
        return redirect('admin-dashboard', event_pk=event.pk)

    nomor_tanding_list.sort(key=sort_key)
    
    bagan_created_count = 0
    if tipe_shuffle in ['perguruan', 'kontingen']:
        group_field = 'perguruan' if tipe_shuffle == 'perguruan' else 'utusan'
        total_collisions = 0

        with transaction.atomic():
            for nomor_tanding in nomor_tanding_list:
                if 'festival' in (nomor_tanding.nama_nomor_tanding or '').lower() or nomor_tanding.is_bob:
                    continue

                # Sinkronkan status VR dari pilihan modal drawing
                is_kumite = 'kumite' in (nomor_tanding.nama_nomor_tanding or '').lower()
                should_have_vr = is_kumite and (str(nomor_tanding.pk) in vr_nomor_tanding_pks)
                if nomor_tanding.has_vr != should_have_vr:
                    nomor_tanding.has_vr = should_have_vr
                    nomor_tanding.save(update_fields=['has_vr'])
                atlets_temp_all = list(Atlet.objects.filter(nomor_tanding=nomor_tanding))
                if not atlets_temp_all:
                    continue

                total_atlets = len(atlets_temp_all)
                if 0 < total_atlets < 17:
                    perulangan = 1
                elif 16 < total_atlets < 33:
                    perulangan = 2
                elif 32 < total_atlets < 49:
                    perulangan = 3
                elif 48 < total_atlets < 65:
                    perulangan = 4
                else:
                    perulangan = 1

                if perulangan > 1 and perulangan % 2 != 0:
                    perulangan += 1

                if perulangan == 1:
                    nama_bagan = nomor_tanding.nama_nomor_tanding
                    _, _, collisions = build_full_bracket(
                        event, nomor_tanding, nama_bagan, 1,
                        atlets_temp=atlets_temp_all, group_field=group_field
                    )
                    total_collisions += collisions
                    bagan_created_count += 1
                else:
                    pools_atlets = split_athletes_into_pools(atlets_temp_all, perulangan, group_field=group_field)

                    nt_name = nomor_tanding.nama_nomor_tanding or ''
                    if 'KATA' in nt_name:
                        final_tipe = '1'
                    elif 'KUMITE' in nt_name:
                        final_tipe = '2'
                    else:
                        final_tipe = None

                    final_bagan, _, _ = build_full_bracket(
                        event, nomor_tanding, f'{nomor_tanding.nama_nomor_tanding} - Final', pool=0,
                        atlets_temp=[], group_field=group_field
                    )
                    if final_tipe:
                        final_bagan.tipe_tanding = final_tipe
                        final_bagan.save(update_fields=['tipe_tanding'])
                    bagan_created_count += 1

                    POOL_LETTERS = ['A', 'B', 'C', 'D']
                    for i in range(1, perulangan + 1):
                        nama_bagan = f'{nomor_tanding.nama_nomor_tanding} - Pool {POOL_LETTERS[i - 1]}'
                        atlets_pool = pools_atlets[i - 1]
                        _, _, collisions = build_full_bracket(
                            event, nomor_tanding, nama_bagan, i,
                            atlets_temp=atlets_pool, group_field=group_field
                        )
                        total_collisions += collisions
                        bagan_created_count += 1

        if bagan_created_count > 0:
            messages.success(request, f"Berhasil membuat {bagan_created_count} bagan pertandingan tournament (kategori festival diabaikan).")
            if total_collisions > 0:
                messages.warning(
                    request,
                    f"Perhatian: {total_collisions} atlet se-perguruan/kontingen tidak bisa dipisah di babak 1. "
                    f"Pertimbangkan untuk menghapus dan drawing ulang jika diperlukan."
                )
        else:
            messages.warning(request, "Tidak ada bagan yang dibuat. Pastikan terdapat atlet yang terdaftar pada nomor tanding yang dipilih.")

    return redirect('admin-dashboard', event_pk=event.pk)


def _handle_tambah_bagan(request, event):
    nomor_tanding_pk = request.POST.get('nomor_tanding_pk')
    tipe = request.POST.get('tipe')
    if not nomor_tanding_pk:
        messages.error(request, "Pilih nomor tanding terlebih dahulu.")
        return redirect('admin-dashboard', event_pk=event.pk)
    if tipe == 'normal':
        return redirect('tambah-bagan', event_pk=event.pk, nomor_tanding_pk=nomor_tanding_pk)
    elif tipe == 'referchange':
        return redirect('tambah-bagan-referchange', event_pk=event_pk, nomor_tanding_pk=nomor_tanding_pk)
    elif tipe == 'round_robin':
        return redirect('tambah-bagan-round-robin', event_pk=event_pk, nomor_tanding_pk=nomor_tanding_pk)
    return redirect('admin-dashboard', event_pk=event.pk)


def _handle_hapus_semua_bagan(request, event):
    bagans_qs = Bagan.objects.filter(event=event)
    count = bagans_qs.count()
    if count > 0:
        with transaction.atomic():
            Tatami.objects.filter(event=event).update(detail_bagan=None)
            bagans_qs.delete()
        messages.success(request, f"Berhasil menghapus seluruh bagan pertandingan ({count} bagan) pada event ini.")
    else:
        messages.warning(request, "Tidak ada bagan yang perlu dihapus.")
    return redirect('admin-dashboard', event_pk=event.pk)


def admin_dashboard(request, event_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    role = getattr(request.user, 'role', None)
    if not role:
        messages.error(request, "Akun Anda tidak memiliki peran yang valid.")
        return redirect('auth')
    nomor_tandings = NomorTanding.objects.filter(event=event).annotate(jumlat_atlet=Count('atlet'))
    
    active_tatamis = Tatami.objects.filter(event=event, detail_bagan__isnull=False).select_related('detail_bagan__bagan')
    active_bagan_tatami = {
        t.detail_bagan.bagan_id: t.tatami_number
        for t in active_tatamis if t.detail_bagan and t.detail_bagan.bagan_id
    }

    bagans = (
        Bagan.objects.filter(event=event)
        .select_related('nomor_tanding', 'juara_1', 'juara_2', 'juara_3a', 'juara_3b')
        .annotate(
            total_matches=Count('detailbagan', distinct=True),
            finished_matches=Count('detailbagan', filter=Q(detailbagan__selesai=True), distinct=True),
        )
        .order_by('-kode')
    )
    
    if request.method == 'POST':
        submit_type = request.POST.get('submit_type')
        handlers = {
            'export_bagan': _handle_export_bagan,
            'set_event_mapping': _handle_set_event_mapping,
            'pull_atlet': _handle_pull_atlet,
            'push_bagan': _handle_push_bagan,
            'force_sync_results': _handle_force_sync_results,
            'bob_bagan': _handle_bob_bagan,
            'drawing_bagan': _handle_drawing_bagan,
            'tambah_bagan': _handle_tambah_bagan,
            'hapus_semua_bagan': _handle_hapus_semua_bagan,
        }
        handler = handlers.get(submit_type)
        if handler:
            return handler(request, event)
        else:
            messages.warning(request, f"Aksi tidak dikenal: {submit_type}")
            return redirect('admin-dashboard', event_pk=event_pk)
            
    event_mapping = get_event_mapping(event.pk)
    if event_mapping and event_mapping.get('hosted_event_name'):
        event_mapping['is_mismatch'] = (event.nama_event or '').strip().lower() != event_mapping.get('hosted_event_name', '').strip().lower()

    hosted_events = []

    for b in bagans:
        b.active_tatami = active_bagan_tatami.get(b.pk)

    context = {
        'on': 'utama',
        'event': event,
        'role': role,
        'nomor_tandings': nomor_tandings,
        'bagans': bagans,
        'event_mapping': event_mapping,
        'hosted_events': hosted_events,
    }

    return render(request, 'admin/dashboard.html', context)

def admin_bagan_detail_round_robin(request, event_pk, bagan_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = Bagan.objects.get(pk=bagan_pk)

    all_atlets = Atlet.objects.filter(nomor_tanding=bagan.nomor_tanding).order_by('pk')
    details = DetailBagan.objects.filter(bagan=bagan)

    match_lookup = {}
    for d in details:
        pk1, pk2 = sorted([d.atlet1.pk, d.atlet2.pk])
        match_lookup[f"{pk1}-{pk2}"] = d

    table_rows = []
    for row in all_atlets:
        row_matches = []
        for col in all_atlets:
            pk1, pk2 = sorted([row.pk, col.pk])
            row_matches.append(match_lookup[f"{pk1}-{pk2}"])
        table_rows.append((row, row_matches))

    results = []
    for row_atlet, matches in table_rows:
        menang = kalah = draw = 0
        
        for match in matches:
            # Skip self matches
            if match.atlet1 == match.atlet2:
                continue
            
            if match.pemenang == '1':
                if match.atlet1 == row_atlet:
                    menang += 1
                elif match.atlet2 == row_atlet:
                    kalah += 1
            elif match.pemenang == '2':
                if match.atlet2 == row_atlet:
                    menang += 1
                elif match.atlet1 == row_atlet:
                    kalah += 1
            elif match.pemenang == '3':
                draw += 1  # Each draw counts as 1 here; you can handle 0.5 in total
            
        total = menang * 1 + draw * 0.5
        results.append({
            "atlet": row_atlet,
            "menang": menang,
            "kalah": kalah,
            "draw": draw,
            "total": total
        })

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        "results": results,
        'bagan': bagan,
        "all_atlets": all_atlets,
        "match_lookup": match_lookup,
        "table_rows": table_rows,
    }
    return render(request, 'admin/round-robin.html', context)

def roster_counter(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagans = Bagan.objects.filter(event=event).order_by('nama_bagan')

    for bagan in bagans:
        dbs = DetailBagan.objects.filter(bagan=bagan)
        bagan.count = 0
        for db in dbs:
            if db.atlet1:
                bagan.count += 1
            if db.atlet2:
                bagan.count += 1

    context = {
        'on': 'roster-counter',
        'event': event,
        'admin_tatami': admin_tatami,
        'bagans': bagans,
    }

    return render(request, 'admin/roster-counter.html', context)
def summary(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()

    bagans = (
        Bagan.objects.filter(event=event)
        .exclude(is_bob=True)
        .exclude(nomor_tanding__is_bob=True)
        .select_related(
            'nomor_tanding',
            'juara_1__perguruan', 'juara_1__utusan',
            'juara_2__perguruan', 'juara_2__utusan',
            'juara_3a__perguruan', 'juara_3a__utusan',
            'juara_3b__perguruan', 'juara_3b__utusan',
        )
        .order_by('kode', 'nama_bagan')
    )

    all_utusans = list(Utusan.objects.filter(event=event).order_by('nama_utusan'))
    utusan_medals = {u.pk: {'gold': 0, 'silver': 0, 'bronze': 0, 'total': 0, 'winners': []} for u in all_utusans}

    all_perguruans = list(Perguruan.objects.filter(event=event).order_by('nama_perguruan'))
    perguruan_medals = {p.pk: {'gold': 0, 'silver': 0, 'bronze': 0, 'total': 0, 'winners': []} for p in all_perguruans}

    total_gold = 0
    total_silver = 0
    total_bronze = 0
    total_bagan = len(bagans)
    finished_bagan = 0
    all_winners = []

    for bagan in bagans:
        is_finished = False

        if bagan.juara_1:
            is_finished = True
            total_gold += 1
            u = bagan.juara_1.utusan
            p = bagan.juara_1.perguruan
            winner_info = {
                'juara': '1',
                'juara_label': 'Juara 1 (Emas)',
                'badge_class': 'badge-gold',
                'medal_icon': '🥇',
                'atlet_nama': bagan.juara_1.nama_atlet,
                'utusan_nama': u.nama_utusan if u else '-',
                'perguruan_nama': p.nama_perguruan if p else '-',
                'bagan_nama': bagan.nama_bagan,
                'bagan_kode': bagan.kode or '',
                'bagan_pk': bagan.pk,
            }
            all_winners.append(winner_info)
            if u and u.pk in utusan_medals:
                utusan_medals[u.pk]['gold'] += 1
                utusan_medals[u.pk]['total'] += 1
                utusan_medals[u.pk]['winners'].append(winner_info)
            if p and p.pk in perguruan_medals:
                perguruan_medals[p.pk]['gold'] += 1
                perguruan_medals[p.pk]['total'] += 1
                perguruan_medals[p.pk]['winners'].append(winner_info)

        if bagan.juara_2:
            total_silver += 1
            u = bagan.juara_2.utusan
            p = bagan.juara_2.perguruan
            winner_info = {
                'juara': '2',
                'juara_label': 'Juara 2 (Perak)',
                'badge_class': 'badge-silver',
                'medal_icon': '🥈',
                'atlet_nama': bagan.juara_2.nama_atlet,
                'utusan_nama': u.nama_utusan if u else '-',
                'perguruan_nama': p.nama_perguruan if p else '-',
                'bagan_nama': bagan.nama_bagan,
                'bagan_kode': bagan.kode or '',
                'bagan_pk': bagan.pk,
            }
            all_winners.append(winner_info)
            if u and u.pk in utusan_medals:
                utusan_medals[u.pk]['silver'] += 1
                utusan_medals[u.pk]['total'] += 1
                utusan_medals[u.pk]['winners'].append(winner_info)
            if p and p.pk in perguruan_medals:
                perguruan_medals[p.pk]['silver'] += 1
                perguruan_medals[p.pk]['total'] += 1
                perguruan_medals[p.pk]['winners'].append(winner_info)

        if bagan.juara_3a:
            total_bronze += 1
            u = bagan.juara_3a.utusan
            p = bagan.juara_3a.perguruan
            winner_info = {
                'juara': '3a',
                'juara_label': 'Juara 3 Bersama (Perunggu)',
                'badge_class': 'badge-bronze',
                'medal_icon': '🥉',
                'atlet_nama': bagan.juara_3a.nama_atlet,
                'utusan_nama': u.nama_utusan if u else '-',
                'perguruan_nama': p.nama_perguruan if p else '-',
                'bagan_nama': bagan.nama_bagan,
                'bagan_kode': bagan.kode or '',
                'bagan_pk': bagan.pk,
            }
            all_winners.append(winner_info)
            if u and u.pk in utusan_medals:
                utusan_medals[u.pk]['bronze'] += 1
                utusan_medals[u.pk]['total'] += 1
                utusan_medals[u.pk]['winners'].append(winner_info)
            if p and p.pk in perguruan_medals:
                perguruan_medals[p.pk]['bronze'] += 1
                perguruan_medals[p.pk]['total'] += 1
                perguruan_medals[p.pk]['winners'].append(winner_info)

        if bagan.juara_3b:
            total_bronze += 1
            u = bagan.juara_3b.utusan
            p = bagan.juara_3b.perguruan
            winner_info = {
                'juara': '3b',
                'juara_label': 'Juara 3 Bersama (Perunggu)',
                'badge_class': 'badge-bronze',
                'medal_icon': '🥉',
                'atlet_nama': bagan.juara_3b.nama_atlet,
                'utusan_nama': u.nama_utusan if u else '-',
                'perguruan_nama': p.nama_perguruan if p else '-',
                'bagan_nama': bagan.nama_bagan,
                'bagan_kode': bagan.kode or '',
                'bagan_pk': bagan.pk,
            }
            all_winners.append(winner_info)
            if u and u.pk in utusan_medals:
                utusan_medals[u.pk]['bronze'] += 1
                utusan_medals[u.pk]['total'] += 1
                utusan_medals[u.pk]['winners'].append(winner_info)
            if p and p.pk in perguruan_medals:
                perguruan_medals[p.pk]['bronze'] += 1
                perguruan_medals[p.pk]['total'] += 1
                perguruan_medals[p.pk]['winners'].append(winner_info)

        if is_finished:
            finished_bagan += 1

    utusan_standings = []
    for u in all_utusans:
        m = utusan_medals[u.pk]
        utusan_standings.append({
            'pk': u.pk,
            'nama': u.nama_utusan,
            'gold': m['gold'],
            'silver': m['silver'],
            'bronze': m['bronze'],
            'total': m['total'],
            'winners': m['winners'],
        })

    utusan_standings.sort(key=lambda x: (-x['gold'], -x['silver'], -x['bronze'], x['nama'].lower()))
    for idx, item in enumerate(utusan_standings, 1):
        item['rank'] = idx

    perguruan_standings = []
    for p in all_perguruans:
        m = perguruan_medals[p.pk]
        perguruan_standings.append({
            'pk': p.pk,
            'nama': p.nama_perguruan,
            'gold': m['gold'],
            'silver': m['silver'],
            'bronze': m['bronze'],
            'total': m['total'],
            'winners': m['winners'],
        })

    perguruan_standings.sort(key=lambda x: (-x['gold'], -x['silver'], -x['bronze'], x['nama'].lower()))
    for idx, item in enumerate(perguruan_standings, 1):
        item['rank'] = idx

    top_3_utusan = [u for u in utusan_standings if u['total'] > 0][:3]
    top_3_perguruan = [p for p in perguruan_standings if p['total'] > 0][:3]
    total_medals = total_gold + total_silver + total_bronze

    context = {
        'on': 'summary',
        'event': event,
        'admin_tatami': admin_tatami,
        'utusan_standings': utusan_standings,
        'perguruan_standings': perguruan_standings,
        'top_3_utusan': top_3_utusan,
        'top_3_perguruan': top_3_perguruan,
        'all_winners': all_winners,
        'total_bagan': total_bagan,
        'finished_bagan': finished_bagan,
        'pending_bagan': max(0, total_bagan - finished_bagan),
        'total_gold': total_gold,
        'total_silver': total_silver,
        'total_bronze': total_bronze,
        'total_medals': total_medals,
    }

    return render(request, 'admin/summary.html', context)

def admin_bagan_detail(request, event_pk, bagan_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first() if request.user.is_authenticated else None
    tatami = None
    if admin_tatami and admin_tatami.tatami:
        tatami = admin_tatami.tatami
    else:
        role = Role.objects.filter(user=request.user, event=event).first() if request.user.is_authenticated else None
        if role and role.tatami:
            tatami = role.tatami
        else:
            tatami = Tatami.objects.filter(event=event).first()

    if not tatami:
        tatami = Tatami.objects.create(event=event, tatami_number=1)
    bagan = Bagan.objects.get(pk=bagan_pk)
    if bagan.round_robin:
        return redirect('admin-bagan-detail-round-robin', event_pk=event_pk, bagan_pk=bagan_pk)
    all_atlets = Atlet.objects.filter(nomor_tanding=bagan.nomor_tanding)
    detail_bagans_round_1 = list(DetailBagan.objects.filter(bagan=bagan, round=1).order_by('urutan'))
    detail_bagans_round_2 = list(DetailBagan.objects.filter(bagan=bagan, round=2).order_by('urutan'))
    detail_bagans_round_3 = list(DetailBagan.objects.filter(bagan=bagan, round=3).order_by('urutan'))
    detail_bagans_round_4 = list(DetailBagan.objects.filter(bagan=bagan, round=4).order_by('urutan'))
    detail_bagan_round_5 = DetailBagan.objects.filter(bagan=bagan, round=5).first()

    all_tatamis = list(Tatami.objects.filter(event=event).select_related('detail_bagan'))
    active_tatami_map = {
        t.detail_bagan_id: t for t in all_tatamis 
        if t.detail_bagan_id and t.detail_bagan and not t.detail_bagan.selesai
    }
    for m in detail_bagans_round_1:
        m.active_on_tatami = active_tatami_map.get(m.pk) if not m.selesai else None
    for m in detail_bagans_round_2:
        m.active_on_tatami = active_tatami_map.get(m.pk) if not m.selesai else None
    for m in detail_bagans_round_3:
        m.active_on_tatami = active_tatami_map.get(m.pk) if not m.selesai else None
    for m in detail_bagans_round_4:
        m.active_on_tatami = active_tatami_map.get(m.pk) if not m.selesai else None
    if detail_bagan_round_5:
        detail_bagan_round_5.active_on_tatami = active_tatami_map.get(detail_bagan_round_5.pk) if not detail_bagan_round_5.selesai else None


    if 'REFERCHANGE' in bagan.nama_bagan:
        referchange = True
    else:
        referchange = False

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'simpan_juara':
            juara_1_pk = request.POST.get('juara_1_pk')
            juara_2_pk = request.POST.get('juara_2_pk')
            juara_3a_pk = request.POST.get('juara_3a_pk')
            juara_3b_pk = request.POST.get('juara_3b_pk')
            if juara_1_pk == '-':
                bagan.juara_1 = None
            else:
                bagan.juara_1 = Atlet.objects.filter(pk=juara_1_pk).first()
            if juara_2_pk == '-':
                bagan.juara_2 = None
            else:
                bagan.juara_2 = Atlet.objects.filter(pk=juara_2_pk).first()
            if juara_3a_pk == '-':
                bagan.juara_3a = None
            else:
                bagan.juara_3a = Atlet.objects.filter(pk=juara_3a_pk).first()
            if juara_3b_pk == '-':
                bagan.juara_3b = None
            else:
                bagan.juara_3b = Atlet.objects.filter(pk=juara_3b_pk).first()
        elif request.POST.get('submit_type') == 'generate_juara':
            if detail_bagan_round_5 and detail_bagan_round_5.atlet1:
                bagan.juara_1 = detail_bagan_round_5.atlet1
            else:
                bagan.juara_1 = None
            for db in detail_bagans_round_4:
                if db.pemenang == '1':
                    bagan.juara_2 = db.atlet2
                elif db.pemenang == '2':
                    bagan.juara_2 = db.atlet1
                else:
                    bagan.juara_2 = None
            for i, db in enumerate(detail_bagans_round_3):
                if db.pemenang == '1':
                    pemenang = db.atlet2
                elif db.pemenang == '2':
                    pemenang = db.atlet1
                else:
                    pemenang = None
                if i == 0:
                    bagan.juara_3a = pemenang
                else:
                    bagan.juara_3b = pemenang
        bagan.save()

        payload = {
            'status': 'finished',
            'kode_realtime': get_kode_realtime(detail_bagan_round_5),
            'juara_1': bagan.juara_1.nama_atlet if bagan.juara_1 else None,
            'juara_1_kode': bagan.juara_1.kode_atlet if (bagan.juara_1 and bagan.juara_1.kode_atlet) else None,
            'juara_2': bagan.juara_2.nama_atlet if bagan.juara_2 else None,
            'juara_2_kode': bagan.juara_2.kode_atlet if (bagan.juara_2 and bagan.juara_2.kode_atlet) else None,
            'juara_3a': bagan.juara_3a.nama_atlet if bagan.juara_3a else None,
            'juara_3a_kode': bagan.juara_3a.kode_atlet if (bagan.juara_3a and bagan.juara_3a.kode_atlet) else None,
            'juara_3b': bagan.juara_3b.nama_atlet if bagan.juara_3b else None,
            'juara_3b_kode': bagan.juara_3b.kode_atlet if (bagan.juara_3b and bagan.juara_3b.kode_atlet) else None,
        }
        send_to_hosted_async(payload, endpoint='api/final-result/', event=event)

        return redirect('admin-bagan-detail', event_pk=event_pk, bagan_pk=bagan_pk)

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'tatami': tatami,
        'bagan': bagan,
        'detail_bagans_round_1': detail_bagans_round_1,
        'detail_bagans_round_2': detail_bagans_round_2,
        'detail_bagans_round_3': detail_bagans_round_3,
        'detail_bagans_round_4': detail_bagans_round_4,
        'detail_bagan_round_5': detail_bagan_round_5,
        'all_atlets': all_atlets,
        'referchange': referchange,
    }

    return render(request, 'admin/bagan-detail.html', context)

def tambah_bagan(request, event_pk, nomor_tanding_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    nomor_tanding = NomorTanding.objects.filter(pk=nomor_tanding_pk).first()
    all_atlets = Atlet.objects.filter(nomor_tanding=nomor_tanding)

    round_1 = [1, 2, 3, 4, 5, 6, 7, 8]
    round_2 = [1, 2, 3, 4]
    round_3 = [1, 2]
    round_4 = [1]

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'simpan-bagan':
            rounds_data = [
                (1, request.POST.getlist('atlet_round_1_aka_pk'), request.POST.getlist('atlet_round_1_ao_pk')),
                (2, request.POST.getlist('atlet_round_2_aka_pk'), request.POST.getlist('atlet_round_2_ao_pk')),
                (3, request.POST.getlist('atlet_round_3_aka_pk'), request.POST.getlist('atlet_round_3_ao_pk')),
                (4, request.POST.getlist('atlet_round_4_aka_pk'), request.POST.getlist('atlet_round_4_ao_pk')),
            ]
            nama_bagan = request.POST.get('nama_bagan').strip().upper()

            if 'KATA' in nomor_tanding.nama_nomor_tanding:
                tipe_tanding = '1'
            else:
                tipe_tanding = '2'

            has_vr = bool(getattr(nomor_tanding, 'has_vr', False) and tipe_tanding == '2')
            new_bagan = Bagan.objects.create(event=event, nomor_tanding=nomor_tanding, tipe_tanding=tipe_tanding, nama_bagan=nama_bagan, has_vr=has_vr)

            for round_number, aka_list, ao_list in rounds_data:
                for index, (aka_pk, ao_pk) in enumerate(zip(aka_list, ao_list), start=1):
                    atlet1 = Atlet.objects.filter(pk=aka_pk).first() if aka_pk != '-' else None
                    atlet2 = Atlet.objects.filter(pk=ao_pk).first() if ao_pk != '-' else None

                    DetailBagan.objects.create(
                        bagan=new_bagan,
                        round=round_number,
                        urutan=index,
                        atlet1=atlet1,
                        atlet2=atlet2
                    )

            round_5 = DetailBagan.objects.create(bagan=new_bagan, round=5, urutan=1)
                

            messages.success(request, f'Berhasil membuat bagan: {nama_bagan}')
            return redirect('admin-dashboard', event_pk=event_pk)

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'nomor_tanding': nomor_tanding,
        'round_1': round_1,
        'round_2': round_2,
        'round_3': round_3,
        'round_4': round_4,
        'all_atlets': all_atlets,
    }

    return render(request, 'admin/tambah-bagan.html', context)

def tambah_bagan_referchange(request, event_pk, nomor_tanding_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    nomor_tanding = NomorTanding.objects.filter(pk=nomor_tanding_pk).first()
    all_atlets = Atlet.objects.filter(nomor_tanding=nomor_tanding)

    round_1 = [1]
    round_2 = [1]
    round_3 = [1]

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'simpan-bagan':
            rounds_data = [
                (1, request.POST.getlist('atlet_round_1_aka_pk'), request.POST.getlist('atlet_round_1_ao_pk')),
                (2, request.POST.getlist('atlet_round_2_aka_pk'), request.POST.getlist('atlet_round_2_ao_pk')),
                (3, request.POST.getlist('atlet_round_3_aka_pk'), request.POST.getlist('atlet_round_3_ao_pk')),
            ]
            nama_bagan = request.POST.get('nama_bagan').strip().upper()

            if 'KATA' in nomor_tanding.nama_nomor_tanding:
                tipe_tanding = '1'
            else:
                tipe_tanding = '2'

            has_vr = bool(getattr(nomor_tanding, 'has_vr', False) and tipe_tanding == '2')
            new_bagan = Bagan.objects.create(event=event, nomor_tanding=nomor_tanding, tipe_tanding=tipe_tanding, nama_bagan=nama_bagan, has_vr=has_vr)

            for round_number, aka_list, ao_list in rounds_data:
                for index, (aka_pk, ao_pk) in enumerate(zip(aka_list, ao_list), start=1):
                    atlet1 = Atlet.objects.filter(pk=aka_pk).first() if aka_pk != '-' else None
                    atlet2 = Atlet.objects.filter(pk=ao_pk).first() if ao_pk != '-' else None

                    DetailBagan.objects.create(
                        bagan=new_bagan,
                        round=round_number,
                        urutan=index,
                        atlet1=atlet1,
                        atlet2=atlet2
                    )

            round_4 = DetailBagan.objects.create(bagan=new_bagan, round=4, urutan=1)

            return redirect('admin-dashboard', event_pk=event_pk)

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'nomor_tanding': nomor_tanding,
        'round_1': round_1,
        'round_2': round_2,
        'round_3': round_3,
        'all_atlets': all_atlets,
    }

    return render(request, 'admin/tambah-bagan-referchange.html', context)

def tambah_bagan_round_robin(request, event_pk, nomor_tanding_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    nomor_tanding = NomorTanding.objects.filter(pk=nomor_tanding_pk).first()
    all_atlets = list(
        Atlet.objects.filter(nomor_tanding=nomor_tanding).order_by('pk')
    )

    if 'KATA' in nomor_tanding.nama_nomor_tanding:
        tipe_tanding = '1'
    else:
        tipe_tanding = '2'

    has_vr = bool(getattr(nomor_tanding, 'has_vr', False) and tipe_tanding == '2')
    new_bagan = Bagan.objects.create(event=event, nama_bagan=f'ROUND ROBIN {nomor_tanding.nama_nomor_tanding}', nomor_tanding=nomor_tanding, tipe_tanding=tipe_tanding, round_robin=True, has_vr=has_vr)
    
    match_lookup = {}
    for atlet_1 in all_atlets:
        for atlet_2 in all_atlets:
            key = tuple(sorted([atlet_1.pk, atlet_2.pk]))
            if key not in match_lookup:
                match = DetailBagan.objects.create(
                    bagan=new_bagan,
                    atlet1=atlet_1,
                    atlet2=atlet_2
                )
                match_lookup[key] = match

    return redirect('admin-dashboard', event_pk=event_pk)

def edit_admin_bagan_detail(request, event_pk, bagan_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = Bagan.objects.get(pk=bagan_pk)
    all_atlets = Atlet.objects.filter(nomor_tanding=bagan.nomor_tanding)
    detail_bagans_round_1 = DetailBagan.objects.filter(bagan=bagan, round=1).order_by('urutan')
    detail_bagans_round_2 = DetailBagan.objects.filter(bagan=bagan, round=2).order_by('urutan')
    detail_bagans_round_3 = DetailBagan.objects.filter(bagan=bagan, round=3).order_by('urutan')
    detail_bagans_round_4 = DetailBagan.objects.filter(bagan=bagan, round=4).order_by('urutan')
    detail_bagan_round_5 = DetailBagan.objects.filter(bagan=bagan, round=5).first()

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'simpan_nama':
            nama_bagan = request.POST.get('nama_bagan')
            if nama_bagan:
                bagan.nama_bagan = nama_bagan
                bagan.save()

        return redirect('edit-admin-bagan-detail', event_pk=event_pk, bagan_pk=bagan_pk)

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'bagan': bagan,
        'detail_bagans_round_1': detail_bagans_round_1,
        'detail_bagans_round_2': detail_bagans_round_2,
        'detail_bagans_round_3': detail_bagans_round_3,
        'detail_bagans_round_4': detail_bagans_round_4,
        'detail_bagan_round_5': detail_bagan_round_5,
        'all_atlets': all_atlets,
    }

    return render(request, 'admin/edit-bagan-detail.html', context)

def hapus_admin_bagan_detail(request, event_pk, bagan_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = get_object_or_404(Bagan, pk=bagan_pk, event=event)
    nama_bagan = bagan.nama_bagan or f"Bagan #{bagan_pk}"
    nomor_tanding = bagan.nomor_tanding
    is_bob = bool(bagan.is_bob or (nomor_tanding and getattr(nomor_tanding, 'is_bob', False)))

    bagan.delete()

    if is_bob and nomor_tanding:
        remaining_bagans = Bagan.objects.filter(event=event, nomor_tanding=nomor_tanding).exists()
        if not remaining_bagans:
            Atlet.objects.filter(event=event, nomor_tanding=nomor_tanding).delete()
            nomor_tanding.delete()

    messages.success(request, f'Berhasil menghapus bagan: {nama_bagan}')
    return redirect('admin-dashboard', event_pk=event_pk)

def admin_edit_detail_bagan(request, event_pk, bagan_pk, detailbagan_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = Bagan.objects.get(pk=bagan_pk)
    detail_bagan = DetailBagan.objects.get(pk=detailbagan_pk)
    atlets = Atlet.objects.filter(nomor_tanding=bagan.nomor_tanding)

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'atlet-simpan':
            atlet_1_pk = request.POST.get('atlet-aka')
            if atlet_1_pk != '-':
                detail_bagan.atlet1 = Atlet.objects.filter(pk=atlet_1_pk).first()
            else:
                detail_bagan.atlet1 = None
            atlet_2_pk = request.POST.get('atlet-ao')
            if atlet_2_pk != '-':
                detail_bagan.atlet2 = Atlet.objects.filter(pk=atlet_2_pk).first()
            else:
                detail_bagan.atlet2 = None
            detail_bagan.save()

            payload = {
                'status': 'edit',
                'kode_realtime': get_kode_realtime(detail_bagan),
                'atlet_aka': detail_bagan.atlet1.nama_atlet if detail_bagan.atlet1 else None,
                'atlet_ao': detail_bagan.atlet2.nama_atlet if detail_bagan.atlet2 else None,
                'utusan_aka': detail_bagan.atlet1.utusan.nama_utusan if detail_bagan.atlet1 else None,
                'utusan_ao': detail_bagan.atlet2.utusan.nama_utusan if detail_bagan.atlet2 else None,
            }
            send_to_hosted_async(payload, endpoint='api/edit-bagan/', event=event)
        
        return redirect('edit-detail-bagan', event_pk=event_pk, bagan_pk=bagan_pk, detailbagan_pk=detailbagan_pk)

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'bagan': bagan,
        'detail_bagan': detail_bagan,
        'atlets': atlets,
    }

    return render(request, 'admin/edit-detail-bagan.html', context)

def control_panel(request, event_pk, bagan_pk, detailbagan_pk, tatami_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    tatami = get_object_or_404(Tatami, pk=tatami_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = get_object_or_404(Bagan, pk=bagan_pk)
    detail_bagan = get_object_or_404(
        DetailBagan.objects.select_related(
            'bagan__nomor_tanding',
            'atlet1__perguruan', 'atlet1__utusan',
            'atlet2__perguruan', 'atlet2__utusan'
        ),
        pk=detailbagan_pk
    )
    aka_score_obj = Score.objects.filter(detail_bagan=detail_bagan, atlet=0).first()
    ao_score_obj = Score.objects.filter(detail_bagan=detail_bagan, atlet=1).first()

    if not aka_score_obj:
        aka_score_obj = Score.objects.create(detail_bagan=detail_bagan, atlet=0)
    if not ao_score_obj:
        ao_score_obj = Score.objects.create(detail_bagan=detail_bagan, atlet=1)

    nt_name = (bagan.nomor_tanding.nama_nomor_tanding or '').lower() if bagan.nomor_tanding else ''
    bagan_name = (bagan.nama_bagan or '').lower()
    is_kumite_cat = (bagan.tipe_tanding == '2') or ('kumite' in bagan_name)
    is_beregu_cat = ('beregu' in nt_name) or ('beregu' in bagan_name) or ('team' in bagan_name)
    is_kumite_beregu = is_kumite_cat and is_beregu_cat

    # If this is master match for Kumite Beregu, route to the active child bout
    if is_kumite_beregu and not detail_bagan.team:
        existing_mus = Matchup.objects.filter(bagan=bagan, detail_bagan=detail_bagan).order_by('round')
        if not existing_mus.exists():
            default_count = 3 if any(k in (nt_name + ' ' + bagan_name) for k in ['putri', 'cadet', 'junior', 'pemula', 'usia dini', '3']) else 5
            for r in range(1, default_count + 1):
                child_db = DetailBagan.objects.create(
                    bagan=bagan,
                    round=10,
                    urutan=r,
                    atlet1=detail_bagan.atlet1,
                    atlet2=detail_bagan.atlet2,
                    score1='0',
                    score2='0',
                    vr1=getattr(bagan, 'has_vr', False),
                    vr2=getattr(bagan, 'has_vr', False),
                    team=True,
                )
                Matchup.objects.create(
                    bagan=bagan,
                    detail_bagan=detail_bagan,
                    db=child_db,
                    round=r,
                )
            existing_mus = Matchup.objects.filter(bagan=bagan, detail_bagan=detail_bagan).order_by('round')

        target_mu = existing_mus.filter(db__selesai=False).first() or existing_mus.first()
        if target_mu and target_mu.db:
            return redirect('control-panel', event_pk=event_pk, bagan_pk=bagan_pk, detailbagan_pk=target_mu.db.pk, tatami_pk=tatami_pk)

    match_changed = (tatami.detail_bagan_id != detail_bagan.pk)
    if match_changed:
        tatami.detail_bagan = detail_bagan
        tatami.save(update_fields=['detail_bagan'])
        broadcast_tatami_match_update(tatami)

    mu = Matchup.objects.filter(db=detail_bagan).select_related('detail_bagan', 'detail_bagan__atlet1', 'detail_bagan__atlet2').first()
    parent_match = mu.detail_bagan if mu else None
    if parent_match:
        is_kumite_beregu = True

    all_matchups = []
    team_aka_score = 0
    team_ao_score = 0
    team_aka_lil_score = 0
    team_ao_lil_score = 0
    candidate_atlets_aka = Atlet.objects.none()
    candidate_atlets_ao = Atlet.objects.none()

    if is_kumite_beregu and parent_match:
        all_matchups = list(Matchup.objects.filter(bagan=bagan, detail_bagan=parent_match).select_related('db', 'db__atlet1', 'db__atlet2').order_by('round'))
        for m in all_matchups:
            if m.db and m.db.score1 and str(m.db.score1).isdigit():
                team_aka_lil_score += int(m.db.score1)
            if m.db and m.db.score2 and str(m.db.score2).isdigit():
                team_ao_lil_score += int(m.db.score2)
            if m.db and m.db.pemenang == '1':
                team_aka_score += 1
            elif m.db and m.db.pemenang == '2':
                team_ao_score += 1

        if parent_match.atlet1 and parent_match.atlet1.utusan:
            candidate_atlets_aka = Atlet.objects.filter(event=event, utusan=parent_match.atlet1.utusan).exclude(pk=parent_match.atlet1.pk).order_by('nama_atlet')
        if parent_match.atlet2 and parent_match.atlet2.utusan:
            candidate_atlets_ao = Atlet.objects.filter(event=event, utusan=parent_match.atlet2.utusan).exclude(pk=parent_match.atlet2.pk).order_by('nama_atlet')

    total_aka_score = team_aka_score
    total_ao_score = team_ao_score

    if request.method == 'POST':
        pemenang = request.POST.get('pemenang')
        submit_type = request.POST.get('submit_type')

        if submit_type == 'assign-bout-athletes':
            aka_pk = request.POST.get('bout_aka_atlet')
            ao_pk = request.POST.get('bout_ao_atlet')
            aka_custom = request.POST.get('bout_aka_custom_name', '').strip()
            ao_custom = request.POST.get('bout_ao_custom_name', '').strip()

            if aka_pk and aka_pk != '-':
                detail_bagan.atlet1 = Atlet.objects.filter(pk=aka_pk).first()
            elif aka_custom and parent_match and parent_match.atlet1:
                a_obj, _ = Atlet.objects.get_or_create(
                    event=event,
                    nama_atlet=aka_custom.upper(),
                    utusan=parent_match.atlet1.utusan,
                    defaults={'perguruan': parent_match.atlet1.perguruan, 'nomor_tanding': bagan.nomor_tanding}
                )
                detail_bagan.atlet1 = a_obj

            if ao_pk and ao_pk != '-':
                detail_bagan.atlet2 = Atlet.objects.filter(pk=ao_pk).first()
            elif ao_custom and parent_match and parent_match.atlet2:
                b_obj, _ = Atlet.objects.get_or_create(
                    event=event,
                    nama_atlet=ao_custom.upper(),
                    utusan=parent_match.atlet2.utusan,
                    defaults={'perguruan': parent_match.atlet2.perguruan, 'nomor_tanding': bagan.nomor_tanding}
                )
                detail_bagan.atlet2 = b_obj

            detail_bagan.save(update_fields=['atlet1', 'atlet2'])
            messages.success(request, f"Atlet untuk Partai {mu.round if mu else ''} berhasil disimpan.")
            return redirect('control-panel', event_pk=event_pk, bagan_pk=bagan_pk, detailbagan_pk=detail_bagan.pk, tatami_pk=tatami_pk)

        elif submit_type == 'add-team-bout' and parent_match:
            next_partai = len(all_matchups) + 1
            new_child = DetailBagan.objects.create(
                bagan=bagan,
                round=10,
                urutan=next_partai,
                atlet1=parent_match.atlet1,
                atlet2=parent_match.atlet2,
                score1='0',
                score2='0',
                vr1=getattr(bagan, 'has_vr', False),
                vr2=getattr(bagan, 'has_vr', False),
                team=True,
            )
            Matchup.objects.create(
                bagan=bagan,
                detail_bagan=parent_match,
                db=new_child,
                round=next_partai,
            )
            messages.success(request, f"Partai {next_partai} berhasil ditambahkan.")
            return redirect('control-panel', event_pk=event_pk, bagan_pk=bagan_pk, detailbagan_pk=new_child.pk, tatami_pk=tatami_pk)

        elif submit_type == 'finish-team-match' and parent_match:
            t_aka_score = 0
            t_ao_score = 0
            t_aka_lil = 0
            t_ao_lil = 0
            for m in all_matchups:
                if m.db and m.db.score1 and str(m.db.score1).isdigit():
                    t_aka_lil += int(m.db.score1)
                if m.db and m.db.score2 and str(m.db.score2).isdigit():
                    t_ao_lil += int(m.db.score2)
                if m.db and m.db.pemenang == '1':
                    t_aka_score += 1
                elif m.db and m.db.pemenang == '2':
                    t_ao_score += 1

            team_winner_choice = request.POST.get('team_winner')
            if team_winner_choice == 'aka':
                final_pemenang = '1'
            elif team_winner_choice == 'ao':
                final_pemenang = '2'
            else:
                if t_aka_score > t_ao_score:
                    final_pemenang = '1'
                elif t_ao_score > t_aka_score:
                    final_pemenang = '2'
                elif t_aka_lil > t_ao_lil:
                    final_pemenang = '1'
                elif t_ao_lil > t_aka_lil:
                    final_pemenang = '2'
                else:
                    final_pemenang = '1'

            final_winner = parent_match.atlet1 if final_pemenang == '1' else parent_match.atlet2

            parent_match.score1 = str(t_aka_score)
            parent_match.score2 = str(t_ao_score)
            parent_match.scorekecil1 = str(t_aka_lil)
            parent_match.scorekecil2 = str(t_ao_lil)
            parent_match.pemenang = final_pemenang
            parent_match.selesai = True
            parent_match.save()

            target_slot = None
            detailbagan_next_round = None
            if not bagan.round_robin:
                next_round_number = parent_match.round + 1
                next_round_urutan = (parent_match.urutan + 1) // 2
                detailbagan_next_round = DetailBagan.objects.filter(bagan=bagan, round=next_round_number, urutan=next_round_urutan).first()
                if detailbagan_next_round and final_winner:
                    target_slot = 'atlet1' if parent_match.urutan % 2 == 1 else 'atlet2'
                    if target_slot == 'atlet1':
                        detailbagan_next_round.atlet1 = final_winner
                    else:
                        detailbagan_next_round.atlet2 = final_winner
                    detailbagan_next_round.save()

            payload = {
                'status': 'finished',
                'pemenang': 'aka' if final_pemenang == '1' else 'ao',
                'target_slot': target_slot,
                'round': parent_match.round,
                'urutan': parent_match.urutan,
                'kode_realtime': get_kode_realtime(parent_match),
                'score_aka': parent_match.score1,
                'score_ao': parent_match.score2,
                'lil_score_aka': parent_match.scorekecil1,
                'lil_score_ao': parent_match.scorekecil2,
                'vr1': parent_match.vr1,
                'vr2': parent_match.vr2,
                'winner_atlet': final_winner.nama_atlet if final_winner else None,
                'next_kode_realtime': get_kode_realtime(detailbagan_next_round) if detailbagan_next_round else None,
                'ring_number': tatami.tatami_number if tatami else '',
            }
            send_to_hosted_async(payload, endpoint='api/result/', event=bagan.event if bagan else None)

            broadcast_match_finished(
                detail_bagan=parent_match,
                winner_atlet=final_winner,
                target_slot=target_slot,
                next_detail_bagan=detailbagan_next_round,
                tatami=tatami,
            )

            if tatami:
                tatami.detail_bagan = None
                tatami.save(update_fields=['detail_bagan'])
                broadcast_tatami_match_update(tatami)

            messages.success(request, f"Pertandingan Beregu selesai! Pemenang: {final_winner.nama_atlet} ({t_aka_score} - {t_ao_score})")
            return redirect('admin-bagan-detail', event_pk=event_pk, bagan_pk=bagan_pk)

        elif submit_type == 'kata-simpan':
            aka_scores = request.POST.getlist('akaScores')
            ao_scores = request.POST.getlist('aoScores')
            total_aka = request.POST.get('totalAka')
            total_ao = request.POST.get('totalAo')
            kata_aka = request.POST.get('kata-aka')
            kata_ao = request.POST.get('kata-ao')

            score_fields = ['score1', 'score2', 'score3', 'score4', 'score5']
        
            for i, field in enumerate(score_fields):
                if i < len(aka_scores):
                    setattr(aka_score_obj, field, aka_scores[i])
            
            for i, field in enumerate(score_fields):
                if i < len(ao_scores):
                    setattr(ao_score_obj, field, ao_scores[i])
            
            aka_score_obj.save()
            ao_score_obj.save()

            detail_bagan.score1 = total_aka
            detail_bagan.score2 = total_ao
            detail_bagan.kata1 = kata_aka
            detail_bagan.kata2 = kata_ao
        
        elif submit_type == 'kumite-simpan':
            aka_score = request.POST.get('akaScore')
            ao_score = request.POST.get('aoScore')
            aka_vr = bool(request.POST.get('aka-vr'))
            ao_vr = bool(request.POST.get('ao-vr'))

            detail_bagan.score1 = aka_score
            detail_bagan.score2 = ao_score
            detail_bagan.vr1 = aka_vr
            detail_bagan.vr2 = ao_vr

            if pemenang == 'aka':
                detail_bagan.pemenang = '1'
            elif pemenang == 'ao':
                detail_bagan.pemenang = '2'
            elif pemenang == 'seri':
                detail_bagan.pemenang = '3'
            else:
                s1 = int(aka_score) if aka_score and str(aka_score).isdigit() else 0
                s2 = int(ao_score) if ao_score and str(ao_score).isdigit() else 0
                if s1 > s2:
                    detail_bagan.pemenang = '1'
                elif s2 > s1:
                    detail_bagan.pemenang = '2'
                else:
                    detail_bagan.pemenang = '3'

            detail_bagan.selesai = True
            detail_bagan.save()

            if is_kumite_beregu and parent_match:
                next_unfinished = Matchup.objects.filter(
                    bagan=bagan,
                    detail_bagan=parent_match,
                    db__selesai=False
                ).exclude(db=detail_bagan).order_by('round').first()

                if next_unfinished and next_unfinished.db:
                    tatami.detail_bagan = next_unfinished.db
                    tatami.save(update_fields=['detail_bagan'])
                    broadcast_tatami_match_update(tatami)
                    messages.success(request, f"Partai {mu.round if mu else ''} tersimpan! Melanjutkan ke Partai {next_unfinished.round}.")
                    return redirect('control-panel', event_pk=event_pk, bagan_pk=bagan_pk, detailbagan_pk=next_unfinished.db.pk, tatami_pk=tatami_pk)
                else:
                    messages.info(request, f"Partai {mu.round if mu else ''} tersimpan. Semua partai telah dimainkan! Silakan periksa skor tim dan klik 'Selesaikan Pertandingan Beregu'.")
                    return redirect('control-panel', event_pk=event_pk, bagan_pk=bagan_pk, detailbagan_pk=detail_bagan.pk, tatami_pk=tatami_pk)

        if pemenang == 'aka':
            detail_bagan.pemenang = '1'
        elif pemenang == 'ao':
            detail_bagan.pemenang = '2'
        elif pemenang == 'seri':
            detail_bagan.pemenang = '3'
        else:
            s1 = int(detail_bagan.score1) if detail_bagan.score1 and str(detail_bagan.score1).isdigit() else 0
            s2 = int(detail_bagan.score2) if detail_bagan.score2 and str(detail_bagan.score2).isdigit() else 0
            if s1 > s2:
                detail_bagan.pemenang = '1'
            elif s2 > s1:
                detail_bagan.pemenang = '2'
            else:
                detail_bagan.pemenang = '3'

        detail_bagan.selesai = True
        detail_bagan.save()

        winner_atlet = None
        target_slot = None
        detailbagan_next_round = None
        if not bagan.round_robin and not detail_bagan.team:
            next_round_number = detail_bagan.round + 1
            next_round_urutan = (detail_bagan.urutan + 1) // 2
            detailbagan_next_round = DetailBagan.objects.filter(bagan=bagan, round=next_round_number, urutan=next_round_urutan).first()

            if detailbagan_next_round:
                if pemenang == 'aka':
                    winner_atlet = detail_bagan.atlet1
                    detail_bagan.pemenang = '1'
                elif pemenang == 'ao':
                    winner_atlet = detail_bagan.atlet2
                    detail_bagan.pemenang = '2'
                else:
                    winner_atlet = None
                    detail_bagan.pemenang = '3'

                if winner_atlet:
                    target_slot = 'atlet1' if detail_bagan.urutan % 2 == 1 else 'atlet2'
                    if target_slot == 'atlet1':
                        detailbagan_next_round.atlet1 = winner_atlet
                    else:
                        detailbagan_next_round.atlet2 = winner_atlet

                    if getattr(bagan, 'has_vr', False):
                        if next_round_number in (3, 4):
                            # Regain VR di Semifinal dan Final
                            if target_slot == 'atlet1':
                                detailbagan_next_round.vr1 = True
                            else:
                                detailbagan_next_round.vr2 = True
                        else:
                            # Babak penyisihan: pertahankan VR hanya jika tidak hangus
                            winner_had_vr = bool(detail_bagan.vr1 if pemenang == 'aka' else detail_bagan.vr2)
                            if target_slot == 'atlet1':
                                detailbagan_next_round.vr1 = winner_had_vr
                            else:
                                detailbagan_next_round.vr2 = winner_had_vr
                    else:
                        if target_slot == 'atlet1':
                            detailbagan_next_round.vr1 = False
                        else:
                            detailbagan_next_round.vr2 = False

                detail_bagan.save()
                detailbagan_next_round.save()

        if detail_bagan.round != 10:
            payload = {
                'status': 'finished',
                'round': detail_bagan.round,
                'urutan': detail_bagan.urutan,
                'kode_realtime': get_kode_realtime(detail_bagan),
                'pemenang': pemenang,
                'target_slot': target_slot,
                'score_aka': detail_bagan.score1,
                'score_ao': detail_bagan.score2,
                'kata_aka': detail_bagan.kata1,
                'kata_ao': detail_bagan.kata2,
                'vr1': detail_bagan.vr1,
                'vr2': detail_bagan.vr2,
                'next_vr1': detailbagan_next_round.vr1 if detailbagan_next_round else False,
                'next_vr2': detailbagan_next_round.vr2 if detailbagan_next_round else False,
                'winner_atlet': winner_atlet.nama_atlet if winner_atlet else None,
                'next_kode_realtime': get_kode_realtime(detailbagan_next_round) if detailbagan_next_round else None,
                'ring_number': tatami.tatami_number if tatami else '',
            }
            send_to_hosted_async(payload, endpoint='api/result/', event=detail_bagan.bagan.event if detail_bagan.bagan else None)

        broadcast_match_finished(
            detail_bagan=detail_bagan,
            winner_atlet=winner_atlet,
            target_slot=target_slot,
            next_detail_bagan=detailbagan_next_round,
            tatami=tatami,
        )

        if tatami:
            tatami.detail_bagan = None
            tatami.save(update_fields=['detail_bagan'])
            broadcast_tatami_match_update(tatami)

        return redirect('admin-bagan-detail', event_pk=event_pk, bagan_pk=bagan_pk)

    from .utils import get_athlete_kata_records, check_is_final, get_utusan_logo_url, get_round_label, get_round_of_slots, get_marquee_title
    kata_history_aka = get_athlete_kata_records(detail_bagan.atlet1, detail_bagan)
    kata_history_ao = get_athlete_kata_records(detail_bagan.atlet2, detail_bagan)
    is_final = check_is_final(detail_bagan)
    round_label = get_round_label(detail_bagan)
    round_of = get_round_of_slots(detail_bagan)
    marquee_text = get_marquee_title(detail_bagan)

    detail_data = {
        "atlet_red": detail_bagan.atlet1.nama_atlet if detail_bagan.atlet1 else None,
        "atlet_red_perguruan": detail_bagan.atlet1.perguruan.nama_perguruan if detail_bagan.atlet1 and detail_bagan.atlet1.perguruan else None,
        "atlet_red_utusan": detail_bagan.atlet1.utusan.nama_utusan if detail_bagan.atlet1 and detail_bagan.atlet1.utusan else None,
        "atlet_red_logo": get_utusan_logo_url(detail_bagan.atlet1),
        "atlet_red_kata": detail_bagan.kata1 if detail_bagan.kata1 else None,
        "atlet_red_vr": detail_bagan.vr1 if detail_bagan.vr1 else None,
        "atlet_blue": detail_bagan.atlet2.nama_atlet if detail_bagan.atlet2 else None,
        "atlet_blue_perguruan": detail_bagan.atlet2.perguruan.nama_perguruan if detail_bagan.atlet2 and detail_bagan.atlet2.perguruan else None,
        "atlet_blue_utusan": detail_bagan.atlet2.utusan.nama_utusan if detail_bagan.atlet2 and detail_bagan.atlet2.utusan else None,
        "atlet_blue_logo": get_utusan_logo_url(detail_bagan.atlet2),
        "atlet_blue_kata": detail_bagan.kata2 if detail_bagan.kata2 else None,
        "atlet_blue_vr": detail_bagan.vr2 if detail_bagan.vr2 else None,
        "tipe_tanding": bagan.tipe_tanding,
        "team": True if (is_kumite_beregu and parent_match) else None,
        "total_aka_score": total_aka_score,
        "total_ao_score": total_ao_score,
        "nomor_tanding": bagan.nomor_tanding.nama_nomor_tanding if bagan and bagan.nomor_tanding else '',
        "nama_bagan": bagan.nama_bagan if bagan else '',
        "round_label": round_label,
        "round_of": round_of,
        "marquee_text": marquee_text,
        "round": detail_bagan.round,
        "urutan": detail_bagan.urutan,
        "tatami_number": tatami.tatami_number,
        "nama_event": event.nama_event if event else '',
        "kata_history_aka": kata_history_aka,
        "kata_history_ao": kata_history_ao,
        "is_final": is_final,
    } 

    if not match_changed:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"scoring_{tatami.pk}",
                {
                    "type": "broadcast_command",
                    "message": "get_atlet",
                    "details": detail_data,
                }
            )

            async_to_sync(channel_layer.group_send)(
                f"juryroom_{tatami.pk}",
                {
                    "type": "broadcast_command",
                    "message": "get_atlet",
                    "details": detail_data,
                }
            )

            async_to_sync(channel_layer.group_send)(
                f"coachroom_{tatami.pk}",
                {
                    "type": "broadcast_command",
                    "message": "get_atlet",
                    "details": [detail_bagan.vr1, detail_bagan.vr2],
                }
            )

            async_to_sync(channel_layer.group_send)(
                f"lokata_{tatami.pk}",
                {
                    "type": "broadcast_command",
                    "message": "get_atlet",
                    "details": detail_data,
                }
            )

            async_to_sync(channel_layer.group_send)(
                f"tatamimanager_{tatami.pk}",
                {
                    "type": "broadcast_command",
                    "message": "get_atlet",
                    "details": detail_data,
                }
            )

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'bagan': bagan,
        'detail_bagan': detail_bagan,
        'aka_score': aka_score_obj,
        'ao_score': ao_score_obj,
        'tatami': tatami,
        'is_kumite_beregu': is_kumite_beregu,
        'parent_match': parent_match,
        'current_matchup': mu,
        'matchups': all_matchups,
        'team_aka_score': team_aka_score,
        'team_ao_score': team_ao_score,
        'team_aka_lil_score': team_aka_lil_score,
        'team_ao_lil_score': team_ao_lil_score,
        'candidate_atlets_aka': candidate_atlets_aka,
        'candidate_atlets_ao': candidate_atlets_ao,
    }

    return render(request, 'admin/control-panel.html', context)

def control_panel_fest(request, event_pk, tatami_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    tatami = get_object_or_404(Tatami, pk=tatami_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()

    total_aka_score = 0
    total_ao_score = 0

    detail_data = {
        "atlet_red": "Aka",
        "atlet_red_perguruan": "-",
        "atlet_red_utusan": "-",
        "atlet_red_kata": "-",
        "atlet_red_vr": None,
        "atlet_blue": "Ao",
        "atlet_blue_perguruan": "-",
        "atlet_blue_utusan": "-",
        "atlet_blue_kata": "-",
        "atlet_blue_vr": None,
        "tipe_tanding": "2",
        "team": None,
        "total_aka_score": total_aka_score,
        "total_ao_score": total_ao_score,
        "nomor_tanding": "Festival",
    } 

    group_name = f"scoring_{tatami.pk}"
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        group_name,
        {
            "type": "broadcast_command",
            "message": "get_atlet",
            "details": detail_data,
        }
    )

    async_to_sync(channel_layer.group_send)(
        f"lokata_{tatami.pk}",
        {
            "type": "broadcast_command",
            "message": "get_atlet",
            "details": detail_data,
        }
    )

    async_to_sync(channel_layer.group_send)(
        f"tatamimanager_{tatami.pk}",
        {
            "type": "broadcast_command",
            "message": "get_atlet",
            "details": detail_data,
        }
    )

    context = {
        'on': 'fest',
        'event': event,
        'admin_tatami': admin_tatami,
        'tatami': tatami,
    }

    return render(request, 'admin/control-panel-fest.html', context)

def control_panel_team(request, event_pk, bagan_pk, detailbagan_pk, tatami_pk):
    return redirect('control-panel', event_pk=event_pk, bagan_pk=bagan_pk, detailbagan_pk=detailbagan_pk, tatami_pk=tatami_pk)

@csrf_exempt
def message_retriever(request, tatami_pk):
    if request.method == 'POST':
        action = request.POST.get('action')
        details = request.POST.get('details')
        tatami = Tatami.objects.filter(pk=tatami_pk).first()
        if not tatami:
            return JsonResponse({'error': 'Tatami tidak ditemukan'}, status=404)

        group_name = f"scoring_{tatami.pk}"
        channel_layer = get_channel_layer()

        async_to_sync(channel_layer.group_send)(
            group_name,
            {
                "type": "broadcast_command",
                "message": action,
                "details": details,
            }
        )

        return JsonResponse({'status': 'ok'})
    return JsonResponse({'error': 'Invalid method'}, status=405)

def admin_atlet(request, event_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    user_role = Role.objects.filter(user=request.user).select_related('tatami', 'event').first()
    if not user_role:
        messages.error(request, "Akun Anda tidak memiliki peran yang valid.")
        return redirect('auth')
    perguruans = Perguruan.objects.filter(event=event)
    utusans = Utusan.objects.filter(event=event)
    nomor_tandings = NomorTanding.objects.filter(event=event)
    atlets = Atlet.objects.filter(event=event).select_related('perguruan', 'utusan', 'nomor_tanding').order_by('-pk')

    if request.method == 'POST':
        submit_type = request.POST.get('submit_type')

        if submit_type == 'import_atlet':
            excel_file = request.FILES.get('excel_atlet')

            if not excel_file:
                messages.error(request, "Silakan pilih file Excel.")
                return redirect('admin-atlet', event_pk=event_pk)
            
            try:
                workbook = openpyxl.load_workbook(excel_file)
                sheet = workbook.active

                # Pre-cache existing lookups to avoid repetitive queries
                perguruan_cache = {p.nama_perguruan.upper(): p for p in Perguruan.objects.filter(event=event)}
                utusan_cache = {u.nama_utusan.upper(): u for u in Utusan.objects.filter(event=event)}
                nt_cache = {nt.nama_nomor_tanding.upper(): nt for nt in NomorTanding.objects.filter(event=event)}

                created_count = 0
                priority_count = 0
                placeholder_logo = 'logo_utusan/inkanas_balikpapan.webp'

                rows_iter = sheet.iter_rows(values_only=True)
                header_row = next(rows_iter, None)
                if not header_row:
                    messages.error(request, "File Excel kosong.")
                    return redirect('admin-atlet', event_pk=event_pk)

                # Header detection map
                header_map = {}
                for idx, cell in enumerate(header_row):
                    if cell is None:
                        continue
                    h = str(cell).strip().lower()
                    if 'kta' in h or 'additional' in h or 'no. kta' in h:
                        header_map['kta'] = idx
                    elif 'nama' in h:
                        header_map['nama'] = idx
                    elif 'perguruan' in h:
                        header_map['perguruan'] = idx
                    elif 'cabang' in h or 'utusan' in h or 'kontingen' in h or 'dojo' in h:
                        header_map['utusan'] = idx
                    elif 'kelas' in h or 'nomor' in h or 'kategori' in h:
                        header_map['nomor_tanding'] = idx
                    elif 'ket' in h or 'prioritas' in h or 'seed' in h or 'priority' in h:
                        header_map['ket'] = idx
                    elif 'nik' in h:
                        header_map['nik'] = idx

                has_named_headers = 'nama' in header_map and ('nomor_tanding' in header_map or 'kelas' in header_map)

                with transaction.atomic():
                    for row in rows_iter:
                        if not row or not any(row):
                            continue

                        cells = [str(c).strip() if c is not None else '' for c in row]
                        if not any(cells):
                            continue

                        nama = ''
                        additional_code = ''
                        nik = ''
                        perguruan_name = ''
                        utusan_name = ''
                        nomor_tanding_name = ''
                        is_priority = False

                        if has_named_headers:
                            nama = cells[header_map['nama']] if header_map.get('nama') is not None and header_map['nama'] < len(cells) else ''
                            additional_code = cells[header_map['kta']] if header_map.get('kta') is not None and header_map['kta'] < len(cells) else ''
                            nik = cells[header_map['nik']] if header_map.get('nik') is not None and header_map['nik'] < len(cells) else ''
                            perguruan_name = cells[header_map['perguruan']].upper() if header_map.get('perguruan') is not None and header_map['perguruan'] < len(cells) else ''
                            utusan_name = cells[header_map['utusan']].upper() if header_map.get('utusan') is not None and header_map['utusan'] < len(cells) else ''
                            nomor_tanding_name = cells[header_map['nomor_tanding']].upper() if header_map.get('nomor_tanding') is not None and header_map['nomor_tanding'] < len(cells) else ''
                            if header_map.get('ket') is not None and header_map['ket'] < len(cells):
                                raw_ket = str(cells[header_map['ket']]).strip().upper()
                                is_priority = raw_ket in ['1', '1.0', 'YA', 'Y', 'TRUE', 'TRUE()']
                        else:
                            # Positional fallback
                            if len(cells) >= 6:
                                # 6-column INKANAS: NO. KTA AKTIF, NAMA LENGKAP, PERGURUAN, CABANG, KELAS TANDING, KET
                                additional_code = cells[0]
                                nama = cells[1]
                                perguruan_name = cells[2].upper()
                                utusan_name = cells[3].upper()
                                nomor_tanding_name = cells[4].upper()
                                raw_ket = cells[5].upper()
                                is_priority = raw_ket in ['1', '1.0', 'YA', 'Y', 'TRUE']
                            elif len(cells) == 5:
                                nama = cells[0]
                                nik = cells[1]
                                perguruan_name = cells[2].upper()
                                utusan_name = cells[3].upper()
                                nomor_tanding_name = cells[4].upper()
                            elif len(cells) == 4:
                                nama = cells[0]
                                perguruan_name = cells[1].upper()
                                utusan_name = cells[2].upper()
                                nomor_tanding_name = cells[3].upper()
                            else:
                                continue

                        if not nama:
                            continue

                        if additional_code in ['-', '', 'None', 'NONE']:
                            additional_code = ''

                        perguruan_obj = None
                        if perguruan_name:
                            if perguruan_name not in perguruan_cache:
                                perguruan_cache[perguruan_name] = Perguruan.objects.create(event=event, nama_perguruan=perguruan_name)
                            perguruan_obj = perguruan_cache[perguruan_name]

                        utusan_obj = None
                        if utusan_name:
                            if utusan_name not in utusan_cache:
                                utusan_cache[utusan_name] = Utusan.objects.create(
                                    event=event,
                                    nama_utusan=utusan_name,
                                    logo=placeholder_logo
                                )
                            utusan_obj = utusan_cache[utusan_name]
                            if not utusan_obj.logo:
                                utusan_obj.logo = placeholder_logo
                                utusan_obj.save(update_fields=['logo'])

                        nt_obj = None
                        if nomor_tanding_name:
                            if nomor_tanding_name not in nt_cache:
                                nt_cache[nomor_tanding_name] = NomorTanding.objects.create(event=event, nama_nomor_tanding=nomor_tanding_name)
                            nt_obj = nt_cache[nomor_tanding_name]

                        Atlet.objects.create(
                            event=event,
                            nama_atlet=nama.upper(),
                            nik=nik or None,
                            additional_code=additional_code or None,
                            is_priority=is_priority,
                            perguruan=perguruan_obj,
                            utusan=utusan_obj,
                            nomor_tanding=nt_obj
                        )
                        created_count += 1
                        if is_priority:
                            priority_count += 1

                msg = f"Data atlet berhasil diimport ({created_count} atlet ditambahkan"
                if priority_count > 0:
                    msg += f", {priority_count} atlet diprioritaskan untuk BYE)"
                else:
                    msg += ")"
                messages.success(request, msg)
            except Exception as e:
                messages.error(request, f"Gagal mengimport file: {str(e)}")
            return redirect('admin-atlet', event_pk=event_pk)
        
        elif submit_type == 'pull_atlet':
            success, msg = pull_athletes_from_hosted(event_pk)
            if success:
                messages.success(request, msg)
            else:
                messages.error(request, msg)
            return redirect('admin-atlet', event_pk=event_pk)

        elif submit_type == 'hapus_atlet':
            atlet_id = request.POST.get('atlet_id')
            atlet = Atlet.objects.filter(pk=atlet_id, event=event).first()
            if atlet:
                nama = atlet.nama_atlet
                atlet.delete()
                messages.success(request, f"Atlet '{nama}' berhasil dihapus.")
            else:
                messages.error(request, "Atlet tidak ditemukan.")
            return redirect('admin-atlet', event_pk=event_pk)

        elif submit_type == 'tambah_atlet':
            nama = request.POST.get('nama_atlet', '').strip().upper()
            if not nama:
                messages.error(request, "Nama atlet wajib diisi.")
                return redirect('admin-atlet', event_pk=event_pk)

            nik = request.POST.get('nik', '').strip()
            additional_code = request.POST.get('additional_code', '').strip()
            is_priority = bool(request.POST.get('is_priority'))
            Atlet.objects.create(
                event=event,
                nama_atlet=nama,
                nik=nik or None,
                additional_code=additional_code or None,
                is_priority=is_priority,
                perguruan_id=request.POST.get('perguruan') or None,
                utusan_id=request.POST.get('utusan') or None,
                nomor_tanding_id=request.POST.get('nomor_tanding') or None,
            )

            messages.success(request, f"Berhasil menambahkan atlet '{nama}'.")
            return redirect('admin-atlet', event_pk=event_pk)

    event_mapping = get_event_mapping(event.pk)
    if event_mapping and event_mapping.get('hosted_event_name'):
        event_mapping['is_mismatch'] = (event.nama_event or '').strip().lower() != event_mapping.get('hosted_event_name', '').strip().lower()

    atlets_list = list(atlets)
    total_count = len(atlets_list)
    tournament_count = 0
    festival_count = 0
    tanpa_nik_count = 0

    for a in atlets_list:
        nt_nama = (a.nomor_tanding.nama_nomor_tanding if a.nomor_tanding else '').lower()
        if 'festival' in nt_nama:
            a.kategori_tipe = 'Festival'
            festival_count += 1
        elif a.nomor_tanding and getattr(a.nomor_tanding, 'is_bob', False):
            a.kategori_tipe = 'BOB'
            tournament_count += 1
        else:
            a.kategori_tipe = 'Tournament'
            tournament_count += 1

        if 'kata' in nt_nama:
            a.disiplin = 'Kata'
        elif 'kumite' in nt_nama:
            a.disiplin = 'Kumite'
        else:
            a.disiplin = None

        if any(w in nt_nama for w in ['putra', 'pa', 'male', 'laki']):
            a.gender = 'Putra'
        elif any(w in nt_nama for w in ['putri', 'pi', 'female', 'wanita']):
            a.gender = 'Putri'
        else:
            a.gender = None

        if not a.nik:
            tanpa_nik_count += 1

    metrics = {
        'total': total_count,
        'tournament': tournament_count,
        'festival': festival_count,
        'tanpa_nik': tanpa_nik_count,
    }

    context = {
        'on': 'atlet',
        'event': event,
        'admin_tatami': user_role,
        'role': user_role,
        'atlets': atlets_list,
        'perguruans': perguruans,
        'utusans': utusans,
        'nomor_tandings': nomor_tandings,
        'event_mapping': event_mapping,
        'metrics': metrics,
    }

    return render(request, 'admin/atlet.html', context)

@require_POST
def edit_atlet_ajax(request):
    atlet_id = request.POST.get('atlet_id')
    atlet = Atlet.objects.filter(pk=atlet_id).first()
    if not atlet:
        return JsonResponse({'success': False, 'message': 'Atlet tidak ditemukan.'}, status=404)

    nama_atlet = request.POST.get('nama_atlet', '').strip().upper()
    if not nama_atlet:
        return JsonResponse({'success': False, 'message': 'Nama atlet wajib diisi.'}, status=400)

    atlet.nama_atlet = nama_atlet
    atlet.nik = request.POST.get('nik', '').strip() or None
    atlet.additional_code = request.POST.get('additional_code', '').strip() or None
    atlet.is_priority = bool(request.POST.get('is_priority') in ['1', 'true', 'True', True])
    atlet.perguruan_id = request.POST.get('perguruan') or None
    atlet.utusan_id = request.POST.get('utusan') or None
    atlet.nomor_tanding_id = request.POST.get('nomor_tanding') or None
    atlet.save()

    return JsonResponse({
        'success': True,
        'atlet_id': atlet.pk,
        'nama_atlet': atlet.nama_atlet,
        'nik': atlet.nik or '',
        'additional_code': atlet.additional_code or '',
        'is_priority': atlet.is_priority,
        'perguruan_id': atlet.perguruan_id or '',
        'perguruan_nama': atlet.perguruan.nama_perguruan if atlet.perguruan else '',
        'utusan_id': atlet.utusan_id or '',
        'utusan_nama': atlet.utusan.nama_utusan if atlet.utusan else '',
        'nomor_tanding_id': atlet.nomor_tanding_id or '',
        'nomor_tanding_nama': atlet.nomor_tanding.nama_nomor_tanding if atlet.nomor_tanding else '',
    })

def get_atlet_nik(request, atlet_pk):
    atlet = get_object_or_404(Atlet, pk=atlet_pk)
    return JsonResponse({'nik': atlet.nik})

def admin_nomor_tanding(request, event_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    role = getattr(request.user, 'role', None)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()

    if request.method == 'POST':
        submit_type = request.POST.get('submit_type')
        if submit_type == 'tambah_nomor_tanding':
            nama = request.POST.get('nomor_tanding', '').strip().upper()
            has_vr = request.POST.get('has_vr') == 'on'
            if 'KATA' in nama or 'FESTIVAL' in nama:
                has_vr = False
            if nama:
                NomorTanding.objects.create(event=event, nama_nomor_tanding=nama, has_vr=has_vr)
                messages.success(request, f"Nomor tanding '{nama}' berhasil ditambahkan.")
            else:
                messages.error(request, "Nama nomor tanding tidak boleh kosong.")

        elif submit_type == 'edit_nomor_tanding':
            pk = request.POST.get('nomor_tanding_pk')
            nama_baru = request.POST.get('nomor_tanding_nama', '').strip().upper()
            has_vr = request.POST.get('has_vr') == 'on'
            if 'KATA' in nama_baru or 'FESTIVAL' in nama_baru:
                has_vr = False
            nt = NomorTanding.objects.filter(pk=pk, event=event).first()
            if nt and nama_baru:
                nt.nama_nomor_tanding = nama_baru
                nt.has_vr = has_vr
                nt.save(update_fields=['nama_nomor_tanding', 'has_vr'])
                messages.success(request, f"Nomor tanding berhasil diubah menjadi '{nama_baru}'.")
            else:
                messages.error(request, "Gagal mengubah nomor tanding: data tidak valid.")

        elif submit_type == 'hapus':
            pk = request.POST.get('nomor_tanding_pk')
            nt = NomorTanding.objects.filter(pk=pk, event=event).first()
            if nt:
                nama = nt.nama_nomor_tanding
                nt.delete()
                messages.success(request, f"Nomor tanding '{nama}' berhasil dihapus.")
            else:
                messages.error(request, "Nomor tanding tidak ditemukan.")

        return redirect('admin-nomor-tanding', event_pk=event_pk)

    # Query dengan anotasi jumlah atlet dan bagan terkait
    nomor_tandings_qs = (
        NomorTanding.objects.filter(event=event)
        .annotate(
            jumlah_atlet=Count('atlet', distinct=True),
            jumlah_bagan=Count('bagan', distinct=True),
        )
    )

    total_count = 0
    tournament_count = 0
    festival_count = 0
    bob_count = 0
    unseeded_count = 0

    nomor_tandings = []
    for nt in nomor_tandings_qs:
        name_upper = (nt.nama_nomor_tanding or '').upper()

        # Klasifikasi kategori
        if nt.is_bob or 'BOB' in name_upper or 'BEST OF THE BEST' in name_upper:
            nt.kategori_tipe = 'bob'
            bob_count += 1
        elif 'FESTIVAL' in name_upper:
            nt.kategori_tipe = 'festival'
            festival_count += 1
        else:
            nt.kategori_tipe = 'tournament'
            tournament_count += 1

        # Disiplin
        if 'KATA' in name_upper:
            nt.disiplin = 'KATA'
        elif 'KUMITE' in name_upper:
            nt.disiplin = 'KUMITE'
        else:
            nt.disiplin = '-'

        # Gender
        if 'BEREGU' in name_upper:
            nt.gender = 'BEREGU'
        elif 'PUTRA' in name_upper:
            nt.gender = 'PUTRA'
        elif 'PUTRI' in name_upper:
            nt.gender = 'PUTRI'
        else:
            nt.gender = '-'

        if nt.jumlah_bagan == 0 and nt.kategori_tipe == 'tournament':
            unseeded_count += 1

        total_count += 1
        nomor_tandings.append(nt)

    # Urutkan berdasarkan hierarki usia, disiplin, dan kelas berat (sort_key)
    nomor_tandings.sort(key=sort_key)

    context = {
        'on': 'nomor-tanding',
        'event': event,
        'role': role,
        'admin_tatami': admin_tatami,
        'nomor_tandings': nomor_tandings,
        'total_count': total_count,
        'tournament_count': tournament_count,
        'festival_count': festival_count,
        'bob_count': bob_count,
        'unseeded_count': unseeded_count,
    }
    return render(request, 'admin/nomor-tanding.html', context)

def admin_utusan(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    utusans = Utusan.objects.filter(event=event)
    
    utusan_medals = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0})
    utusan_winners = []

    bagans = Bagan.objects.filter(event=event).exclude(is_bob=True).exclude(nomor_tanding__is_bob=True)

    for bagan in bagans:
        if bagan.juara_1 and bagan.juara_1.utusan:
            p_nama = bagan.juara_1.perguruan.nama_perguruan if bagan.juara_1.perguruan else '-'
            utusan_medals[bagan.juara_1.utusan.pk]["gold"] += 1
            utusan_winners.append(({"pk": bagan.juara_1.utusan.pk, "nama_atlet": bagan.juara_1.nama_atlet, "perguruan": p_nama, "juara": "1", "nama_bagan": bagan.nama_bagan}))
        if bagan.juara_2 and bagan.juara_2.utusan:
            p_nama = bagan.juara_2.perguruan.nama_perguruan if bagan.juara_2.perguruan else '-'
            utusan_medals[bagan.juara_2.utusan.pk]["silver"] += 1
            utusan_winners.append(({"pk": bagan.juara_2.utusan.pk, "nama_atlet": bagan.juara_2.nama_atlet, "perguruan": p_nama, "juara": "2", "nama_bagan": bagan.nama_bagan}))
        if bagan.juara_3a and bagan.juara_3a.utusan:
            p_nama = bagan.juara_3a.perguruan.nama_perguruan if bagan.juara_3a.perguruan else '-'
            utusan_medals[bagan.juara_3a.utusan.pk]["bronze"] += 1
            utusan_winners.append(({"pk": bagan.juara_3a.utusan.pk, "nama_atlet": bagan.juara_3a.nama_atlet, "perguruan": p_nama, "juara": "3a", "nama_bagan": bagan.nama_bagan}))
        if bagan.juara_3b and bagan.juara_3b.utusan:
            p_nama = bagan.juara_3b.perguruan.nama_perguruan if bagan.juara_3b.perguruan else '-'
            utusan_medals[bagan.juara_3b.utusan.pk]["bronze"] += 1
            utusan_winners.append(({"pk": bagan.juara_3b.utusan.pk, "nama_atlet": bagan.juara_3b.nama_atlet, "perguruan": p_nama, "juara": "3b", "nama_bagan": bagan.nama_bagan}))
    
    utusans = list(utusans)

    utusans.sort(key=lambda u: (
        -utusan_medals[u.pk]["gold"],
        -utusan_medals[u.pk]["silver"],
        -utusan_medals[u.pk]["bronze"],
    ))

    for utusan in utusans:
        utusan.winners = []

    for winner in utusan_winners:
        for utusan in utusans:
            if utusan.pk == winner['pk']:
                utusan.winners.append(winner)

    context = {
        'on': 'utusan',
        'event': event,
        'utusans': utusans,
        'utusan_medals': utusan_medals,
        'admin_tatami': admin_tatami,
    }
    return render(request, 'admin/utusan.html', context)

def admin_perguruan(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    perguruans = Perguruan.objects.filter(event=event)
    
    perguruan_medals = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0})
    perguruan_winners = []

    bagans = Bagan.objects.filter(event=event).exclude(is_bob=True).exclude(nomor_tanding__is_bob=True)

    for bagan in bagans:
        if bagan.juara_1 and bagan.juara_1.perguruan:
            u_nama = bagan.juara_1.utusan.nama_utusan if bagan.juara_1.utusan else '-'
            perguruan_medals[bagan.juara_1.perguruan.pk]["gold"] += 1
            perguruan_winners.append(({"pk": bagan.juara_1.perguruan.pk, "nama_atlet": bagan.juara_1.nama_atlet, "utusan": u_nama, "juara": "1", "nama_bagan": bagan.nama_bagan}))
        if bagan.juara_2 and bagan.juara_2.perguruan:
            u_nama = bagan.juara_2.utusan.nama_utusan if bagan.juara_2.utusan else '-'
            perguruan_medals[bagan.juara_2.perguruan.pk]["silver"] += 1
            perguruan_winners.append(({"pk": bagan.juara_2.perguruan.pk, "nama_atlet": bagan.juara_2.nama_atlet, "utusan": u_nama, "juara": "2", "nama_bagan": bagan.nama_bagan}))
        if bagan.juara_3a and bagan.juara_3a.perguruan:
            u_nama = bagan.juara_3a.utusan.nama_utusan if bagan.juara_3a.utusan else '-'
            perguruan_medals[bagan.juara_3a.perguruan.pk]["bronze"] += 1
            perguruan_winners.append(({"pk": bagan.juara_3a.perguruan.pk, "nama_atlet": bagan.juara_3a.nama_atlet, "utusan": u_nama, "juara": "3a", "nama_bagan": bagan.nama_bagan}))
        if bagan.juara_3b and bagan.juara_3b.perguruan:
            u_nama = bagan.juara_3b.utusan.nama_utusan if bagan.juara_3b.utusan else '-'
            perguruan_medals[bagan.juara_3b.perguruan.pk]["bronze"] += 1
            perguruan_winners.append(({"pk": bagan.juara_3b.perguruan.pk, "nama_atlet": bagan.juara_3b.nama_atlet, "utusan": u_nama, "juara": "3b", "nama_bagan": bagan.nama_bagan}))
    
    perguruans = list(perguruans)
    perguruans.sort(key=lambda u: (
        -perguruan_medals[u.pk]["gold"],
        -perguruan_medals[u.pk]["silver"],
        -perguruan_medals[u.pk]["bronze"],
    ))

    for perguruan in perguruans:
        perguruan.winners = []

    for winner in perguruan_winners:
        for perguruan in perguruans:
            if perguruan.pk == winner['pk']:
                perguruan.winners.append(winner)


    context = {
        'on': 'perguruan',
        'event': event,
        'perguruans': perguruans,
        'perguruan_medals': perguruan_medals,
        'admin_tatami': admin_tatami,
    }
    return render(request, 'admin/perguruan.html', context)

def admin_rekapan(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    days = TimetableDay.objects.filter(event=event).order_by('order')

    days_for_filter = [{'pk': d.pk, 'label': format_day_label(d)} for d in days]

    selected_day_ids = request.GET.getlist('day')
    if not selected_day_ids:
        # no filter applied yet (first visit) -> default to showing everything
        selected_day_ids = [str(d.pk) for d in days]
    selected_set = set(selected_day_ids)

    # map: nomor_tanding_id -> set of day_ids it's scheduled on, via the timetable
    nt_day_map = {}
    cells = (
        TimetableCell.objects
        .filter(row__day__event=event, nomor_tanding__isnull=False)
        .select_related('row__day')
    )
    for cell in cells:
        nt_day_map.setdefault(cell.nomor_tanding_id, set()).add(str(cell.row.day_id))

    all_bagans = (
        Bagan.objects.filter(event=event)
        .select_related(
            'nomor_tanding',
            'juara_1__perguruan', 'juara_1__utusan',
            'juara_2__perguruan', 'juara_2__utusan',
            'juara_3a__perguruan', 'juara_3a__utusan',
            'juara_3b__perguruan', 'juara_3b__utusan',
        ).order_by('kode')
    )

    bagans = []
    finished_count = 0
    for b in all_bagans:
        b.is_finished = bool(b.juara_1)
        if b.is_finished:
            finished_count += 1
        scheduled_days = nt_day_map.get(b.nomor_tanding_id)
        if not scheduled_days:
            # category isn't placed on the timetable at all yet -> always show
            bagans.append(b)
        elif scheduled_days & selected_set:
            bagans.append(b)

    total_count = len(all_bagans)
    pending_count = max(0, total_count - finished_count)

    context = {
        'on': 'rekapan',
        'event': event,
        'bagans': bagans,
        'days_for_filter': days_for_filter,
        'selected_day_ids': selected_set,
        'admin_tatami': admin_tatami,
        'total_count': total_count,
        'finished_count': finished_count,
        'pending_count': pending_count,
    }
    return render(request, 'admin/rekapan.html', context)

def admin_tatami(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)
    user_role = getattr(request.user, 'role', None)
    tatamis = Tatami.objects.filter(event=event).select_related(
        'detail_bagan__bagan__nomor_tanding',
        'detail_bagan__atlet1__perguruan',
        'detail_bagan__atlet1__utusan',
        'detail_bagan__atlet2__perguruan',
        'detail_bagan__atlet2__utusan',
    ).order_by('tatami_number')

    if request.method == 'POST':
        submit_type = request.POST.get('submit_type')

        if submit_type == 'tambah_tatami':
            last_tatami = tatamis.order_by('-tatami_number').first()
            next_number = (last_tatami.tatami_number + 1) if (last_tatami and last_tatami.tatami_number) else 1

            new_tatami = Tatami.objects.create(event=event, tatami_number=next_number)

            # Create or update Admin Tatami User and Role
            adm_username = f'admtatami{next_number}e{event_pk}'
            adm_user, _ = User.objects.get_or_create(username=adm_username)
            adm_user.set_password(adm_username)
            adm_user.save()
            Role.objects.update_or_create(
                user=adm_user,
                defaults={
                    'event': event,
                    'tatami': new_tatami,
                    'role_type': 'admin_tatami',
                }
            )

            # Create or update 7 Juries via Role
            for i in range(1, 8):
                jury_username = f'j{i}t{next_number}e{event_pk}'
                j_user, _ = User.objects.get_or_create(username=jury_username)
                j_user.set_password(jury_username)
                j_user.save()
                Role.objects.update_or_create(
                    user=j_user,
                    defaults={
                        'event': event,
                        'tatami': new_tatami,
                        'jury_number': i,
                        'role_type': 'jury',
                    }
                )

            messages.success(request, f"Sukses menambahkan Tatami {next_number} beserta 1 akun Admin Tatami dan 7 akun Juri!")
            return redirect('admin-tatami', event_pk=event_pk)

        elif submit_type == 'hapus_tatami':
            tatami = Tatami.objects.filter(pk=request.POST.get('tatami_pk'), event=event).first()
            if not tatami:
                messages.error(request, "Tatami tidak ditemukan.")
                return redirect('admin-tatami', event_pk=event_pk)

            tatami_num = tatami.tatami_number

            # 1. Delete all user accounts linked to this Tatami via Role
            for role in Role.objects.filter(tatami=tatami).select_related('user'):
                if role.user:
                    role.user.delete()

            # 2. Clean up any legacy AdminTatami or Jury records if present
            for legacy_adm in AdminTatami.objects.filter(tatami=tatami).select_related('user'):
                if legacy_adm.user:
                    legacy_adm.user.delete()
                else:
                    legacy_adm.delete()

            for legacy_jury in Jury.objects.filter(tatami=tatami).select_related('user'):
                if legacy_jury.user:
                    legacy_jury.user.delete()
                else:
                    legacy_jury.delete()

            # 3. Disassociate detail_bagan and delete Tatami
            tatami.detail_bagan = None
            tatami.save(update_fields=['detail_bagan'])
            tatami.delete()

            messages.success(request, f"Sukses menghapus Tatami {tatami_num} beserta seluruh akun terkait!")
            return redirect('admin-tatami', event_pk=event_pk)

        elif submit_type == 'reset_tatami':
            tatami = Tatami.objects.filter(pk=request.POST.get('tatami_pk'), event=event).first()
            if tatami:
                tatami.detail_bagan = None
                tatami.save(update_fields=['detail_bagan'])
                messages.success(request, f"Pertandingan pada Tatami {tatami.tatami_number} berhasil dikosongkan.")
            return redirect('admin-tatami', event_pk=event_pk)

    # Next suggested tatami number
    last_tatami = tatamis.order_by('-tatami_number').first()
    next_suggested = (last_tatami.tatami_number + 1) if (last_tatami and last_tatami.tatami_number) else 1

    context = {
        'on': 'tatami',
        'event': event,
        'admin_tatami': user_role,
        'role': user_role,
        'tatamis': tatamis,
        'next_suggested': next_suggested,
    }

    return render(request, 'admin/tatami.html', context)


def tatami_manager_entry(request):
    if request.session.get('view_only_role') == 'tatami_manager' and request.session.get('view_only_event_pk'):
        event_pk = request.session['view_only_event_pk']
        if Event.objects.filter(pk=event_pk).exists():
            tatami_pk = request.session.get('view_only_tatami_pk')
            if tatami_pk:
                return redirect(f"{reverse('tatami-manager', args=[event_pk])}?tatami={tatami_pk}")
            return redirect('tatami-manager', event_pk=event_pk)

    if request.user.is_authenticated:
        role = getattr(request.user, 'role', None)
        if role and role.event_id:
            return redirect('tatami-manager', event_pk=role.event_id)
        first_event = Event.objects.first()
        if first_event:
            return redirect('tatami-manager', event_pk=first_event.pk)

    return redirect('auth')


def broadcast_tatami_match_update(tatami):
    if not tatami:
        return
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    db = tatami.detail_bagan
    # Match is only running if present and not finished
    is_running = bool(db and not db.selesai)
    active_db = db if is_running else None
    bagan = active_db.bagan if active_db else None
    event = tatami.event

    from .utils import get_athlete_kata_records, check_is_final, get_utusan_logo_url, get_round_label, get_round_of_slots, get_marquee_title
    kata_history_aka = get_athlete_kata_records(active_db.atlet1, active_db) if (active_db and active_db.atlet1) else {}
    kata_history_ao = get_athlete_kata_records(active_db.atlet2, active_db) if (active_db and active_db.atlet2) else {}
    is_final = check_is_final(active_db) if active_db else False
    round_label = get_round_label(active_db) if active_db else ""
    round_of = get_round_of_slots(active_db) if active_db else ""
    marquee_text = get_marquee_title(active_db) if active_db else ""

    detail_data = {
        "tatami_pk": tatami.pk,
        "tatami_number": tatami.tatami_number,
        "match_pk": active_db.pk if active_db else None,
        "bagan_pk": bagan.pk if bagan else None,
        "is_running": is_running,
        "selesai": db.selesai if db else False,
        "atlet_red": active_db.atlet1.nama_atlet if (active_db and active_db.atlet1) else "-",
        "atlet_red_perguruan": active_db.atlet1.perguruan.nama_perguruan if (active_db and active_db.atlet1 and active_db.atlet1.perguruan) else "-",
        "atlet_red_utusan": active_db.atlet1.utusan.nama_utusan if (active_db and active_db.atlet1 and active_db.atlet1.utusan) else "-",
        "atlet_red_logo": get_utusan_logo_url(active_db.atlet1) if active_db else None,
        "atlet_red_kata": active_db.kata1 if active_db else "-",
        "atlet_red_vr": active_db.vr1 if active_db else None,
        "atlet_blue": active_db.atlet2.nama_atlet if (active_db and active_db.atlet2) else "-",
        "atlet_blue_perguruan": active_db.atlet2.perguruan.nama_perguruan if (active_db and active_db.atlet2 and active_db.atlet2.perguruan) else "-",
        "atlet_blue_utusan": active_db.atlet2.utusan.nama_utusan if (active_db and active_db.atlet2 and active_db.atlet2.utusan) else "-",
        "atlet_blue_logo": get_utusan_logo_url(active_db.atlet2) if active_db else None,
        "atlet_blue_kata": active_db.kata2 if active_db else "-",
        "atlet_blue_vr": active_db.vr2 if active_db else None,
        "tipe_tanding": bagan.tipe_tanding if bagan else '2',
        "team": True if (bagan and 'KUMITE BEREGU' in bagan.nama_bagan) else None,
        "total_aka_score": 0,
        "total_ao_score": 0,
        "nomor_tanding": bagan.nomor_tanding.nama_nomor_tanding if (bagan and bagan.nomor_tanding) else '',
        "nama_bagan": bagan.nama_bagan if bagan else '',
        "round_label": round_label,
        "round_of": round_of,
        "marquee_text": marquee_text,
        "round": active_db.round if active_db else None,
        "urutan": active_db.urutan if active_db else None,
        "nama_event": event.nama_event if event else '',
        "kata_history_aka": kata_history_aka,
        "kata_history_ao": kata_history_ao,
        "is_final": is_final,
        "has_vr": bool(bagan.has_vr) if bagan else False,
    }

    groups = [
        f"scoring_{tatami.pk}",
        f"juryroom_{tatami.pk}",
        f"coachroom_{tatami.pk}",
        f"lokata_{tatami.pk}",
        f"tatamimanager_{tatami.pk}",
        f"control_{tatami.pk}",
        f"admin_control_{tatami.pk}",
    ]

    for grp in groups:
        try:
            async_to_sync(channel_layer.group_send)(
                grp,
                {
                    "type": "broadcast_command",
                    "message": "get_atlet",
                    "details": detail_data,
                }
            )
        except Exception:
            pass


def broadcast_match_finished(detail_bagan, winner_atlet=None, target_slot=None, next_detail_bagan=None, tatami=None):
    if not detail_bagan:
        return
    channel_layer = get_channel_layer()
    if not channel_layer:
        return

    bagan = detail_bagan.bagan
    if not winner_atlet:
        if detail_bagan.pemenang == '1':
            winner_atlet = detail_bagan.atlet1
        elif detail_bagan.pemenang == '2':
            winner_atlet = detail_bagan.atlet2

    from .utils import get_utusan_logo_url
    finish_data = {
        "match_pk": detail_bagan.pk,
        "bagan_pk": bagan.pk if bagan else None,
        "round": detail_bagan.round,
        "urutan": detail_bagan.urutan,
        "pemenang": detail_bagan.pemenang,
        "score_aka": detail_bagan.score1 if detail_bagan.score1 is not None else "0",
        "score_ao": detail_bagan.score2 if detail_bagan.score2 is not None else "0",
        "winner_name": winner_atlet.nama_atlet if winner_atlet else "-",
        "winner_perguruan": winner_atlet.perguruan.nama_perguruan if (winner_atlet and winner_atlet.perguruan) else "-",
        "winner_utusan": winner_atlet.utusan.nama_utusan if (winner_atlet and winner_atlet.utusan) else "-",
        "winner_logo": get_utusan_logo_url(winner_atlet) if winner_atlet else None,
        "next_match_pk": next_detail_bagan.pk if next_detail_bagan else None,
        "target_slot": target_slot,
        "tatami_pk": tatami.pk if tatami else None,
    }

    groups = ["tatamimanager_all", "lokata_all"]
    if tatami:
        groups.extend([
            f"tatamimanager_{tatami.pk}",
            f"scoring_{tatami.pk}",
            f"control_{tatami.pk}",
            f"admin_control_{tatami.pk}",
            f"lokata_{tatami.pk}",
        ])

    for grp in groups:
        try:
            async_to_sync(channel_layer.group_send)(
                grp,
                {
                    "type": "broadcast_command",
                    "message": "match_finished",
                    "details": finish_data,
                }
            )
        except Exception:
            pass


def find_best_match_for_tatami(tatami, event, exclude_current=False):
    """
    Menemukan partai pertandingan (DetailBagan) terbaik berikutnya untuk sebuah Tatami.
    Aturan Prediksi Partai:
    Partai hanya eligible jika kedua atlet sudah siap (atlet1 != None dan atlet2 != None),
    belum selesai (selesai=False), dan tidak sedang aktif di tatami lain.

    Urutan Alur:
    1. Jika tatami sedang menjalankan partai (curr_m):
       Cari di bagan yang SAMA partai berikutnya yang kedua atletnya sudah siap.
       - Prioritas 1A: Partai di babak yang sama dengan urutan lebih besar (round == curr.round, urutan > curr.urutan),
         atau babak berikutnya (round > curr.round).
       - Prioritas 1B: Partai lain yang belum selesai di bagan ini yang kedua atletnya sudah siap.
    2. Jika bagan saat ini sudah selesai/tidak ada partai siap lagi:
       - Jika ada jadwal Timetable untuk tatami ini:
         Periksa nomor tanding sesuai urutan jadwal Timetable. Ambil partai pertama yang kedua atletnya siap.
       - Jika tidak ada jadwal Timetable:
         Cari di bagan-bagan event ini (dimulai dari bagan berikutnya jika curr_m ada), ambil partai pertama yang kedua atletnya siap.
    3. Jika sama sekali tidak ada partai dengan kedua atlet siap:
       Return None, "Menunggu atlet dari partai sebelumnya siap"
    """
    if not tatami or not event:
        return None, "Tatami atau event tidak valid"

    other_tatami_qs = Tatami.objects.filter(event=event)
    if not exclude_current:
        other_tatami_qs = other_tatami_qs.exclude(pk=tatami.pk)
    excluded_match_ids = set(
        other_tatami_qs.filter(detail_bagan__isnull=False).values_list('detail_bagan_id', flat=True)
    )
    if exclude_current and tatami.detail_bagan_id:
        excluded_match_ids.add(tatami.detail_bagan_id)

    curr_m = tatami.detail_bagan

    # 1. Jika tatami sedang ada partai aktif atau baru saja ada partai di bagan tertentu:
    if curr_m and curr_m.bagan and curr_m.bagan.event_id == event.pk:
        bagan_matches = list(
            DetailBagan.objects.filter(bagan=curr_m.bagan, selesai=False)
            .exclude(pk__in=excluded_match_ids)
            .select_related('bagan__nomor_tanding', 'atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan')
            .order_by('round', 'urutan')
        )

        # Cari partai di bagan yang sama setelah partai saat ini dengan kedua atlet siap
        for m in bagan_matches:
            if m.atlet1_id and m.atlet2_id:
                if (m.round > curr_m.round) or (m.round == curr_m.round and m.urutan > curr_m.urutan):
                    return m, "Partai Berikutnya di Kategori Ini (Kedua Atlet Siap)"

        # Jika tidak ada setelahnya, cari partai lain di bagan yang sama dengan kedua atlet siap
        for m in bagan_matches:
            if m.atlet1_id and m.atlet2_id:
                return m, "Partai Tersedia di Kategori Ini (Kedua Atlet Siap)"

    # 2. Cari berdasarkan jadwal Timetable Tatami ini
    scheduled_nt_ids = list(
        TimetableCell.objects.filter(tatami=tatami, nomor_tanding__isnull=False)
        .order_by('row__day__order', 'row__order')
        .values_list('nomor_tanding_id', flat=True)
    )

    if scheduled_nt_ids:
        timetable_matches = list(
            DetailBagan.objects.filter(bagan__nomor_tanding_id__in=scheduled_nt_ids, selesai=False)
            .exclude(pk__in=excluded_match_ids)
            .select_related('bagan__nomor_tanding', 'atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan')
            .order_by('round', 'urutan')
        )
        if timetable_matches:
            nt_map = {}
            for m in timetable_matches:
                nt_map.setdefault(m.bagan.nomor_tanding_id, []).append(m)

            for nt_id in scheduled_nt_ids:
                matches = nt_map.get(nt_id)
                if not matches:
                    continue
                for m in matches:
                    if m.atlet1_id and m.atlet2_id:
                        return m, "Sesuai Jadwal Timetable Tatami (Kedua Atlet Siap)"

    # 3. Cari di bagan event umum (dimulai dari bagan berikutnya jika curr_m ada)
    general_qs = (
        DetailBagan.objects.filter(
            bagan__event=event,
            selesai=False,
            atlet1__isnull=False,
            atlet2__isnull=False
        )
        .exclude(pk__in=excluded_match_ids)
        .select_related('bagan__nomor_tanding', 'atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan')
    )

    if curr_m and curr_m.bagan_id:
        next_bagan_match = general_qs.filter(bagan_id__gt=curr_m.bagan_id).order_by('bagan_id', 'round', 'urutan').first()
        if next_bagan_match:
            return next_bagan_match, "Kategori Bagan Berikutnya (Kedua Atlet Siap)"

    general_match = general_qs.order_by('bagan_id', 'round', 'urutan').first()
    if general_match:
        return general_match, "Antrean Bagan Event (Kedua Atlet Siap)"

    return None, "Semua partai pertandingan telah selesai atau menunggu pemenang babak sebelumnya"


def get_dynamic_panel_rule(active_match):
    """
    Dynamic panel requirements:
    - Kata and < Junior: 3 Juri
    - Kata and >= Junior: 5 Juri
    - Kumite and < Junior: 2 Wasit, 1 Juri, 1 Kansa (4 total)
    - Kumite and >= Junior: 6 wasit/juri (1 referee, 4 judges, 1 kansa)
    """
    if not active_match or not active_match.bagan or not active_match.bagan.nomor_tanding:
        return {
            'type': 'kumite',
            'is_junior_plus': True,
            'format_name': 'KUMITE (≥ Junior) - Standar 6 Wasit & Juri',
            'required_positions': ['referee', 'judge_1', 'judge_2', 'judge_3', 'judge_4', 'kansa'],
        }

    cat_name = (active_match.bagan.nomor_tanding.nama_nomor_tanding or '').upper()
    is_kata = 'KATA' in cat_name

    pre_junior_keywords = ['PRA USIA DINI', 'USIA DINI', 'PRA PEMULA', 'PEMULA', 'KADET', 'CADET', 'PRA-PEMULA', 'PRA-USIA DINI']
    is_pre_junior = any(k in cat_name for k in pre_junior_keywords)

    if is_kata:
        if is_pre_junior:
            return {
                'type': 'kata',
                'is_junior_plus': False,
                'format_name': 'KATA (< Junior) - Standar 3 Juri',
                'required_positions': ['judge_1', 'judge_2', 'judge_3'],
            }
        else:
            return {
                'type': 'kata',
                'is_junior_plus': True,
                'format_name': 'KATA (≥ Junior) - Standar 5 Juri',
                'required_positions': ['judge_1', 'judge_2', 'judge_3', 'judge_4', 'judge_5'],
            }
    else:
        if is_pre_junior:
            return {
                'type': 'kumite',
                'is_junior_plus': False,
                'format_name': 'KUMITE (< Junior) - Standar 2 Wasit, 1 Juri, 1 Kansa',
                'required_positions': ['referee', 'wasit_2', 'judge_1', 'kansa'],
            }
        else:
            return {
                'type': 'kumite',
                'is_junior_plus': True,
                'format_name': 'KUMITE (≥ Junior) - Standar 6 Wasit & Juri',
                'required_positions': ['referee', 'judge_1', 'judge_2', 'judge_3', 'judge_4', 'kansa'],
            }


def sync_match_wasits_to_tatami(detail_bagan, tatami):
    """
    Synchronizes the officiating crew assigned in WasitDetailBagan for a match
    into WasitTatami for the active tatami, keeping live scoring boards and panels updated.
    """
    if not detail_bagan or not tatami:
        return
    match_assignments = list(
        WasitDetailBagan.objects.filter(detail_bagan=detail_bagan).select_related('wasit')
    )
    if not match_assignments:
        return

    with transaction.atomic():
        chosen_wasit_ids = [ma.wasit_id for ma in match_assignments]
        # Any wasit currently on tatami not in match_assignments is set to 'pool'
        WasitTatami.objects.filter(event=tatami.event, tatami=tatami).exclude(wasit_id__in=chosen_wasit_ids).update(posisi='pool')
        for ma in match_assignments:
            wt = WasitTatami.objects.filter(event=tatami.event, wasit=ma.wasit).first()
            if wt:
                wt.tatami = tatami
                wt.posisi = ma.posisi
                wt.save(update_fields=['tatami', 'posisi'])
            else:
                WasitTatami.objects.create(
                    event=tatami.event,
                    tatami=tatami,
                    wasit=ma.wasit,
                    posisi=ma.posisi
                )


def auto_assign_panel_for_match(match, event):
    """
    Automated conflict-free referee assignment tailored specifically to a match's AKA and AO athletes.
    Strictly prevents wasits from the same perguruan or kab/kota as the fighters.
    """
    if not match or not match.bagan:
        return []
    panel_rule = get_dynamic_panel_rule(match)
    req_positions = panel_rule['required_positions']
    needed_count = len(req_positions)

    conflict_perguruan_ids = set()
    conflict_kab_kota = set()
    if match.atlet1:
        if match.atlet1.perguruan_id:
            conflict_perguruan_ids.add(match.atlet1.perguruan_id)
        if match.atlet1.utusan and match.atlet1.utusan.nama_utusan:
            conflict_kab_kota.add(match.atlet1.utusan.nama_utusan.strip().upper())
    if match.atlet2:
        if match.atlet2.perguruan_id:
            conflict_perguruan_ids.add(match.atlet2.perguruan_id)
        if match.atlet2.utusan and match.atlet2.utusan.nama_utusan:
            conflict_kab_kota.add(match.atlet2.utusan.nama_utusan.strip().upper())

    all_event_wasits = list(Wasit.objects.filter(event=event, is_active=True).select_related('perguruan'))
    all_tatami_assignments = {a.wasit_id: a for a in WasitTatami.objects.filter(event=event)}

    pool_1 = []  # Diff perg & kab, available
    pool_2 = []  # Diff perg & kab, on duty elsewhere (can borrow)
    pool_3 = []  # Fallback if referee numbers are limited

    for w in all_event_wasits:
        w_kab = (w.kab_kota or '').strip().upper()
        is_conflict = bool(
            (w.perguruan_id and w.perguruan_id in conflict_perguruan_ids) or
            (w_kab and w_kab in conflict_kab_kota)
        )
        wt = all_tatami_assignments.get(w.pk)
        is_available = (wt is None or wt.posisi == 'pool')

        if not is_conflict:
            if is_available:
                pool_1.append(w)
            else:
                pool_2.append(w)
        else:
            pool_3.append(w)

    chosen = []
    used_pergs = set()
    used_kabs = set()

    def try_pick(wasit_list, check_perg=True, check_kab=True):
        for w in wasit_list:
            if len(chosen) >= needed_count:
                break
            if w in chosen:
                continue
            p_id = w.perguruan_id
            w_k = (w.kab_kota or '').strip().upper()
            if check_perg and p_id and p_id in used_pergs:
                continue
            if check_kab and w_k and w_k in used_kabs:
                continue
            chosen.append(w)
            if p_id:
                used_pergs.add(p_id)
            if w_k:
                used_kabs.add(w_k)

    try_pick(pool_1, check_perg=True, check_kab=True)
    if len(chosen) < needed_count:
        try_pick(pool_1, check_perg=True, check_kab=False)
    if len(chosen) < needed_count:
        try_pick(pool_1, check_perg=False, check_kab=False)
    if len(chosen) < needed_count:
        try_pick(pool_2, check_perg=True, check_kab=False)
    if len(chosen) < needed_count:
        try_pick(pool_2, check_perg=False, check_kab=False)
    if len(chosen) < needed_count:
        try_pick(pool_3, check_perg=False, check_kab=False)

    with transaction.atomic():
        WasitDetailBagan.objects.filter(detail_bagan=match).delete()
        for idx, w in enumerate(chosen):
            pos = req_positions[idx] if idx < len(req_positions) else 'pool'
            WasitDetailBagan.objects.create(
                event=event,
                detail_bagan=match,
                wasit=w,
                posisi=pos
            )

    return chosen


def get_match_tatami_modal_context(match, event, selected_tatami=None):
    """
    Builds the detailed context for the Tatami Manager Match Referee modal.
    """
    panel_rule = get_dynamic_panel_rule(match)
    req_positions = panel_rule['required_positions']

    active_tatami = Tatami.objects.filter(event=event, detail_bagan=match).first()
    tatamis = list(Tatami.objects.filter(event=event).order_by('tatami_number'))

    assignments = list(
        WasitDetailBagan.objects.filter(detail_bagan=match)
        .select_related('wasit__perguruan')
    )
    assigned_by_pos = {a.posisi: a for a in assignments}
    assigned_wasit_ids = {a.wasit_id for a in assignments}

    conflict_perguruan_ids = set()
    conflict_kab_kota = set()
    if match.atlet1:
        if match.atlet1.perguruan_id:
            conflict_perguruan_ids.add(match.atlet1.perguruan_id)
        if match.atlet1.utusan and match.atlet1.utusan.nama_utusan:
            conflict_kab_kota.add(match.atlet1.utusan.nama_utusan.strip().upper())
    if match.atlet2:
        if match.atlet2.perguruan_id:
            conflict_perguruan_ids.add(match.atlet2.perguruan_id)
        if match.atlet2.utusan and match.atlet2.utusan.nama_utusan:
            conflict_kab_kota.add(match.atlet2.utusan.nama_utusan.strip().upper())

    pos_display_dict = dict(WasitTatami.POSISI_CHOICES)

    perg_counts = Counter(a.wasit.perguruan.nama_perguruan for a in assignments if a.wasit.perguruan)
    kab_counts = Counter((a.wasit.kab_kota or '').strip().upper() for a in assignments if a.wasit.kab_kota)

    conflict_warnings = []
    position_slots = []
    for pos_code in req_positions:
        asg = assigned_by_pos.get(pos_code)
        has_conflict = False
        conflict_reason = ''
        if asg:
            w = asg.wasit
            w_kab = (w.kab_kota or '').strip().upper()
            reasons = []
            if w.perguruan_id and w.perguruan_id in conflict_perguruan_ids:
                reasons.append(f"Perguruan sama dengan atlet ({w.perguruan.nama_perguruan})")
            if w_kab and w_kab in conflict_kab_kota:
                reasons.append(f"Asal daerah sama dengan atlet ({w_kab})")
            if w.perguruan and perg_counts[w.perguruan.nama_perguruan] > 1:
                reasons.append(f"Duplikat perguruan ({w.perguruan.nama_perguruan}) pada panel")
            if w_kab and kab_counts[w_kab] > 1:
                reasons.append(f"Duplikat daerah ({w_kab}) pada panel")
            if reasons:
                has_conflict = True
                conflict_reason = "; ".join(reasons)
                conflict_warnings.append(f"{asg.get_posisi_display()}: {w.nama_wasit} — {conflict_reason}")

        position_slots.append({
            'posisi_code': pos_code,
            'posisi_label': pos_display_dict.get(pos_code, pos_code),
            'assigned': asg,
            'has_conflict': has_conflict,
            'conflict_reason': conflict_reason,
        })

    all_tatami_assignments = {a.wasit_id: a for a in WasitTatami.objects.filter(event=event)}
    all_event_wasits = list(Wasit.objects.filter(event=event, is_active=True).select_related('perguruan').order_by('nama_wasit'))

    pool_candidates = []
    for w in all_event_wasits:
        w_kab = (w.kab_kota or '').strip().upper()
        is_same_perg = bool(w.perguruan_id and w.perguruan_id in conflict_perguruan_ids)
        is_same_kab = bool(w_kab and w_kab in conflict_kab_kota)
        is_conflict = is_same_perg or is_same_kab

        wt = all_tatami_assignments.get(w.pk)
        is_assigned_to_this_match = (w.pk in assigned_wasit_ids)
        is_on_duty_other = bool(wt and wt.posisi != 'pool')
        is_available = not is_on_duty_other

        tatami_label = f"Tatami {wt.tatami.tatami_number}" if (wt and wt.tatami) else "Pool Event"

        if is_assigned_to_this_match:
            prio_rank = 6
            prio_symbol = "✓"
            rec_badge = "primary"
            rec_label = "Ditugaskan di Partai Ini"
        elif not is_conflict and is_available:
            prio_rank = 1
            prio_symbol = "★"
            rec_badge = "success"
            rec_label = "Prioritas 1: Standby (Beda Perguruan & Daerah)"
        elif not is_conflict and is_on_duty_other:
            prio_rank = 2
            prio_symbol = "★"
            rec_badge = "lendable"
            rec_label = f"Prioritas 2: Bertugas di {tatami_label} (Bisa Pinjam)"
        elif is_conflict and is_available:
            prio_rank = 3
            prio_symbol = "▲"
            rec_badge = "warning"
            rec_label = f"Konflik: Perguruan/Daerah Sama ({w.perguruan.nama_perguruan if w.perguruan else w_kab}) - Standby"
        else:
            prio_rank = 4
            prio_symbol = "▲"
            rec_badge = "dark"
            rec_label = f"Konflik: Perguruan/Daerah Sama - Bertugas di {tatami_label}"

        w.priority_rank = prio_rank
        w.priority_badge_symbol = prio_symbol
        w.recommendation_badge = rec_badge
        w.recommendation_label = rec_label
        w.is_available = is_available
        w.is_assigned_to_this_match = is_assigned_to_this_match
        pool_candidates.append(w)

    pool_candidates.sort(key=lambda x: (x.priority_rank, x.nama_wasit))

    return {
        'match': match,
        'panel_rule': panel_rule,
        'active_tatami': active_tatami,
        'selected_tatami': selected_tatami,
        'tatamis': tatamis,
        'position_slots': position_slots,
        'pool_candidates': pool_candidates,
        'assigned_count': len(assignments),
        'is_panel_complete': len(assignments) >= len(req_positions),
        'conflict_warnings': conflict_warnings,
    }


def admin_tatami_manager(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)

    is_allowed = False
    user_role = None

    if request.user.is_authenticated:
        user_role = Role.objects.filter(user=request.user).select_related('tatami', 'event').first()
        if request.user.is_staff or request.user.is_superuser or (user_role and user_role.role_type in ('admin', 'admin_tatami')):
            is_allowed = True

    if not is_allowed:
        session_role = request.session.get('view_only_role')
        session_event = request.session.get('view_only_event_pk')
        if session_role in ('tatami_manager', 'admin_control', 'coach_sup', 'lo_kata'):
            if not session_event or session_event == event.pk:
                is_allowed = True
                request.session['view_only_event_pk'] = event.pk

    if not is_allowed:
        messages.error(request, "Silakan login terlebih dahulu untuk mengakses Tatami Manager.")
        return redirect('auth')

    is_admin = bool(
        request.user.is_authenticated and (
            request.user.is_staff or request.user.is_superuser or 
            (user_role and user_role.role_type == 'admin')
        )
    )

    tatamis = Tatami.objects.filter(event=event).select_related(
        'detail_bagan__bagan__nomor_tanding',
        'detail_bagan__atlet1__perguruan',
        'detail_bagan__atlet1__utusan',
        'detail_bagan__atlet2__perguruan',
        'detail_bagan__atlet2__utusan',
    ).order_by('tatami_number')

    tatami_pk = request.GET.get('tatami') or request.POST.get('tatami_pk')
    selected_tatami = None
    if tatami_pk:
        selected_tatami = tatamis.filter(pk=tatami_pk).first()
    if not selected_tatami and request.session.get('view_only_tatami_pk'):
        selected_tatami = tatamis.filter(pk=request.session.get('view_only_tatami_pk')).first()
    if not selected_tatami:
        selected_tatami = tatamis.first()

    all_bagans = Bagan.objects.filter(event=event).select_related('nomor_tanding').order_by('kode', 'nama_bagan')

    # Resolve selected bagan:
    # If explicitly flagged as manual selection, honor requested bagan_pk.
    # Otherwise, default to the tatami's active match bagan so reconnecting/reopening dead tabs always follows the arena.
    bagan_pk = request.GET.get('bagan')
    is_manual = request.GET.get('manual') == '1'
    selected_bagan = None
    if is_manual and bagan_pk:
        selected_bagan = all_bagans.filter(pk=bagan_pk).first()
    if not selected_bagan and selected_tatami and selected_tatami.detail_bagan and not selected_tatami.detail_bagan.selesai and selected_tatami.detail_bagan.bagan:
        selected_bagan = selected_tatami.detail_bagan.bagan
    if not selected_bagan and bagan_pk:
        selected_bagan = all_bagans.filter(pk=bagan_pk).first()
    if not selected_bagan:
        selected_bagan = all_bagans.first()

    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('ajax') == '1' or request.GET.get('ajax') == '1'

    # --- AJAX Handlers for Match Modal ---
    if is_ajax and request.GET.get('action') == 'get_match_detail':
        detailbagan_pk = request.GET.get('detailbagan_pk')
        match_obj = DetailBagan.objects.filter(pk=detailbagan_pk, bagan__event=event).select_related(
            'bagan__nomor_tanding', 'atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami'
        ).first()
        if not match_obj:
            return JsonResponse({'status': 'error', 'message': 'Partai tidak ditemukan.'}, status=404)
        modal_ctx = get_match_tatami_modal_context(match_obj, event, selected_tatami)
        html = render_to_string('admin/partials/tatami_match_modal_body.html', modal_ctx, request=request)
        winner_name = None
        if match_obj.pemenang == '1' and match_obj.atlet1:
            winner_name = match_obj.atlet1.nama_atlet
        elif match_obj.pemenang == '2' and match_obj.atlet2:
            winner_name = match_obj.atlet2.nama_atlet

        return JsonResponse({
            'status': 'success',
            'html': html,
            'match_pk': match_obj.pk,
            'category_name': str(match_obj.bagan.nomor_tanding) if match_obj.bagan and match_obj.bagan.nomor_tanding else '',
            'round': match_obj.round,
            'urutan': match_obj.urutan,
            'selesai': match_obj.selesai,
            'pemenang': match_obj.pemenang,
            'score1': match_obj.score1,
            'score2': match_obj.score2,
            'winner_name': winner_name,
        })

    if request.method == 'POST':
        submit_type = request.POST.get('submit_type')

        # --- Match-Level Referee Modal Operations ---
        if submit_type == 'assign_match_wasit':
            detailbagan_pk = request.POST.get('detailbagan_pk')
            wasit_id = request.POST.get('wasit_id')
            posisi = request.POST.get('posisi')
            match_obj = DetailBagan.objects.filter(pk=detailbagan_pk, bagan__event=event).first()
            wasit = Wasit.objects.filter(pk=wasit_id, event=event).first()

            if not match_obj or not wasit:
                return JsonResponse({'status': 'error', 'message': 'Data partai atau wasit tidak valid.'}, status=400)

            with transaction.atomic():
                WasitDetailBagan.objects.filter(detail_bagan=match_obj, posisi=posisi).exclude(wasit=wasit).delete()
                WasitDetailBagan.objects.filter(detail_bagan=match_obj, wasit=wasit).delete()
                WasitDetailBagan.objects.create(
                    event=event,
                    detail_bagan=match_obj,
                    wasit=wasit,
                    posisi=posisi
                )
                active_t = Tatami.objects.filter(event=event, detail_bagan=match_obj).first()
                if active_t:
                    sync_match_wasits_to_tatami(match_obj, active_t)

            modal_ctx = get_match_tatami_modal_context(match_obj, event, selected_tatami)
            html = render_to_string('admin/partials/tatami_match_modal_body.html', modal_ctx, request=request)
            return JsonResponse({
                'status': 'success',
                'message': f"Wasit '{wasit.nama_wasit}' berhasil ditugaskan.",
                'html': html,
                'assigned_count': modal_ctx['assigned_count'],
                'is_panel_complete': modal_ctx['is_panel_complete'],
                'match_pk': match_obj.pk,
            })

        elif submit_type == 'remove_match_wasit':
            detailbagan_pk = request.POST.get('detailbagan_pk')
            wasit_id = request.POST.get('wasit_id')
            match_obj = DetailBagan.objects.filter(pk=detailbagan_pk, bagan__event=event).first()

            if match_obj and wasit_id:
                WasitDetailBagan.objects.filter(detail_bagan=match_obj, wasit_id=wasit_id).delete()
                active_t = Tatami.objects.filter(event=event, detail_bagan=match_obj).first()
                if active_t:
                    sync_match_wasits_to_tatami(match_obj, active_t)

                modal_ctx = get_match_tatami_modal_context(match_obj, event, selected_tatami)
                html = render_to_string('admin/partials/tatami_match_modal_body.html', modal_ctx, request=request)
                return JsonResponse({
                    'status': 'success',
                    'message': "Wasit berhasil dilepas dari partai ini.",
                    'html': html,
                    'assigned_count': modal_ctx['assigned_count'],
                    'is_panel_complete': modal_ctx['is_panel_complete'],
                    'match_pk': match_obj.pk,
                })

        elif submit_type == 'auto_assign_match_panel':
            detailbagan_pk = request.POST.get('detailbagan_pk')
            match_obj = DetailBagan.objects.filter(pk=detailbagan_pk, bagan__event=event).first()
            if not match_obj:
                return JsonResponse({'status': 'error', 'message': 'Partai tidak valid.'}, status=400)

            chosen = auto_assign_panel_for_match(match_obj, event)
            active_t = Tatami.objects.filter(event=event, detail_bagan=match_obj).first()
            if active_t:
                sync_match_wasits_to_tatami(match_obj, active_t)

            modal_ctx = get_match_tatami_modal_context(match_obj, event, selected_tatami)
            html = render_to_string('admin/partials/tatami_match_modal_body.html', modal_ctx, request=request)
            return JsonResponse({
                'status': 'success',
                'message': f"Sukses menyusun {len(chosen)} wasit bebas konflik untuk partai ini!",
                'html': html,
                'assigned_count': modal_ctx['assigned_count'],
                'is_panel_complete': modal_ctx['is_panel_complete'],
                'match_pk': match_obj.pk,
            })

        elif submit_type == 'clear_match_panel':
            detailbagan_pk = request.POST.get('detailbagan_pk')
            match_obj = DetailBagan.objects.filter(pk=detailbagan_pk, bagan__event=event).first()
            if match_obj:
                WasitDetailBagan.objects.filter(detail_bagan=match_obj).delete()
                active_t = Tatami.objects.filter(event=event, detail_bagan=match_obj).first()
                if active_t:
                    sync_match_wasits_to_tatami(match_obj, active_t)

                modal_ctx = get_match_tatami_modal_context(match_obj, event, selected_tatami)
                html = render_to_string('admin/partials/tatami_match_modal_body.html', modal_ctx, request=request)
                return JsonResponse({
                    'status': 'success',
                    'message': "Seluruh penugasan wasit untuk partai ini berhasil dikosongkan.",
                    'html': html,
                    'assigned_count': 0,
                    'is_panel_complete': False,
                    'match_pk': match_obj.pk,
                })

        elif submit_type == 'set_active_match':
            detailbagan_pk = request.POST.get('detailbagan_pk')
            target_tatami_pk = request.POST.get('tatami_pk') or (selected_tatami.pk if selected_tatami else None)
            target_tatami = Tatami.objects.filter(pk=target_tatami_pk, event=event).first()
            match_obj = DetailBagan.objects.filter(pk=detailbagan_pk, bagan__event=event).first()

            if target_tatami and match_obj:
                target_tatami.detail_bagan = match_obj
                target_tatami.save(update_fields=['detail_bagan'])
                sync_match_wasits_to_tatami(match_obj, target_tatami)
                broadcast_tatami_match_update(target_tatami)
                selected_tatami = target_tatami

                modal_ctx = get_match_tatami_modal_context(match_obj, event, selected_tatami)
                html = render_to_string('admin/partials/tatami_match_modal_body.html', modal_ctx, request=request)
                if is_ajax:
                    return JsonResponse({
                        'status': 'success',
                        'message': f"Partai #{match_obj.urutan} berhasil diaktifkan ke Tatami {target_tatami.tatami_number}!",
                        'html': html,
                        'reload_bracket': True,
                        'active_tatami_number': target_tatami.tatami_number,
                        'match_pk': match_obj.pk,
                    })
                messages.success(request, f"Partai #{match_obj.urutan} berhasil diaktifkan ke Tatami {target_tatami.tatami_number}.")
                return redirect(f"{reverse('tatami-manager', args=[event_pk])}?tatami={target_tatami.pk}&bagan={match_obj.bagan_id}")

        elif submit_type == 'reset_match':
            target_tatami_pk = request.POST.get('tatami_pk') or (selected_tatami.pk if selected_tatami else None)
            target_tatami = Tatami.objects.filter(pk=target_tatami_pk, event=event).first()
            if target_tatami:
                target_tatami.detail_bagan = None
                target_tatami.save(update_fields=['detail_bagan'])
                broadcast_tatami_match_update(target_tatami)
                selected_tatami = target_tatami
                msg = f"Arena Tatami {target_tatami.tatami_number} berhasil dikosongkan dari partai berjalan."
                if is_ajax:
                    return JsonResponse({'status': 'success', 'message': msg, 'reload': True})
                messages.success(request, msg)
                return redirect(f"{reverse('tatami-manager', args=[event_pk])}?tatami={target_tatami.pk}")

        elif submit_type == 'tambah_wasit':
            nama = request.POST.get('nama_wasit', '').strip().upper()
            if not nama:
                err_msg = "Nama wasit wajib diisi."
                if is_ajax:
                    return JsonResponse({'status': 'error', 'message': err_msg}, status=400)
                messages.error(request, err_msg)
            else:
                perguruan_id = request.POST.get('perguruan') or None
                kab_kota = request.POST.get('kab_kota', '').strip()
                lisensi = request.POST.get('lisensi', '').strip()
                no_lisensi = request.POST.get('no_lisensi', '').strip()
                wasit = Wasit.objects.create(
                    event=event,
                    nama_wasit=nama,
                    perguruan_id=perguruan_id,
                    kab_kota=kab_kota or None,
                    lisensi=lisensi or None,
                    no_lisensi=no_lisensi or None,
                )
                msg = f"Wasit '{nama}' berhasil ditambahkan ke master event."
                if is_ajax:
                    return JsonResponse({'status': 'success', 'message': msg, 'reload': True})
                messages.success(request, msg)
                return redirect(f"{reverse('tatami-manager', args=[event_pk])}?tatami={selected_tatami.pk if selected_tatami else ''}")

    # --- Prepare Bagan Tournament Bracket Structure ---
    detail_bagans_round_1 = []
    detail_bagans_round_2 = []
    detail_bagans_round_3 = []
    detail_bagans_round_4 = []
    detail_bagan_round_5 = None
    referchange = False

    active_tatami_map = {
        t.detail_bagan_id: t for t in tatamis 
        if t.detail_bagan_id and t.detail_bagan and not t.detail_bagan.selesai
    }

    def annotate_match_bracket(m):
        m.active_on_tatami = active_tatami_map.get(m.pk) if not m.selesai else None
        m_wasits = list(m.wasit_assignments.all())
        m.assigned_wasit_count = len(m_wasits)
        rule = get_dynamic_panel_rule(m)
        m.required_wasit_count = len(rule['required_positions'])
        m.is_panel_complete = m.assigned_wasit_count >= m.required_wasit_count

        conflict = False
        m_pergs = set()
        if m.atlet1 and m.atlet1.perguruan_id:
            m_pergs.add(m.atlet1.perguruan_id)
        if m.atlet2 and m.atlet2.perguruan_id:
            m_pergs.add(m.atlet2.perguruan_id)
        for wa in m_wasits:
            if wa.wasit.perguruan_id and wa.wasit.perguruan_id in m_pergs:
                conflict = True
                break
        m.has_wasit_conflict = conflict
        return m

    if selected_bagan:
        referchange = 'REFERCHANGE' in selected_bagan.nama_bagan.upper()
        detail_bagans_round_1 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=1)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .prefetch_related('wasit_assignments__wasit__perguruan')
            .order_by('urutan')
        )
        detail_bagans_round_2 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=2)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .prefetch_related('wasit_assignments__wasit__perguruan')
            .order_by('urutan')
        )
        detail_bagans_round_3 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=3)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .prefetch_related('wasit_assignments__wasit__perguruan')
            .order_by('urutan')
        )
        detail_bagans_round_4 = list(
            DetailBagan.objects.filter(bagan=selected_bagan, round=4)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .prefetch_related('wasit_assignments__wasit__perguruan')
            .order_by('urutan')
        )
        detail_bagan_round_5 = (
            DetailBagan.objects.filter(bagan=selected_bagan, round=5)
            .select_related('atlet1__perguruan', 'atlet1__utusan', 'atlet2__perguruan', 'atlet2__utusan', 'assigned_tatami')
            .prefetch_related('wasit_assignments__wasit__perguruan')
            .first()
        )

        for m in detail_bagans_round_1:
            annotate_match_bracket(m)
        for m in detail_bagans_round_2:
            annotate_match_bracket(m)
        for m in detail_bagans_round_3:
            annotate_match_bracket(m)
        for m in detail_bagans_round_4:
            annotate_match_bracket(m)
        if detail_bagan_round_5:
            annotate_match_bracket(detail_bagan_round_5)

    # Master Wasit Statistics for Top Bar
    all_wasits = list(Wasit.objects.filter(event=event).select_related('perguruan').order_by('nama_wasit'))
    all_tatami_assignments = list(WasitTatami.objects.filter(event=event))
    total_wasit = len(all_wasits)
    assigned_wasit_count = len([a for a in all_tatami_assignments if a.posisi != 'pool'])
    available_wasit_count = max(0, total_wasit - assigned_wasit_count)

    perguruans = Perguruan.objects.filter(event=event).order_by('nama_perguruan')

    # Count assigned wasits per tatami
    tatami_panel_counts = Counter(a.tatami_id for a in all_tatami_assignments if a.posisi != 'pool')
    for t in tatamis:
        t.assigned_count = tatami_panel_counts.get(t.pk, 0)

    context = {
        'on': 'tatami-manager',
        'event': event,
        'role': user_role,
        'is_admin': is_admin,
        'tatamis': tatamis,
        'selected_tatami': selected_tatami,
        'all_bagans': all_bagans,
        'selected_bagan': selected_bagan,
        'detail_bagans_round_1': detail_bagans_round_1,
        'detail_bagans_round_2': detail_bagans_round_2,
        'detail_bagans_round_3': detail_bagans_round_3,
        'detail_bagans_round_4': detail_bagans_round_4,
        'detail_bagan_round_5': detail_bagan_round_5,
        'referchange': referchange,
        'perguruans': perguruans,
        'posisi_choices': WasitTatami.POSISI_CHOICES,
        'metrics': {
            'total_wasit': total_wasit,
            'assigned_wasit': assigned_wasit_count,
            'available_wasit': available_wasit_count,
            'total_tatami': len(tatamis),
            'total_bagan': len(all_bagans),
        }
    }

    return render(request, 'admin/tatami-manager.html', context)


def admin_wasit(request, event_pk):
    event = get_object_or_404(Event, pk=event_pk)

    if not request.user.is_authenticated:
        messages.error(request, "Silakan login terlebih dahulu.")
        return redirect('auth')

    user_role = Role.objects.filter(user=request.user).select_related('tatami', 'event').first()
    is_admin = bool(
        request.user.is_staff or request.user.is_superuser or 
        (user_role and user_role.role_type == 'admin')
    )
    if not is_admin:
        messages.error(request, "Akses ditolak. Halaman ini hanya untuk Administrator.")
        return redirect('auth')

    tatamis = Tatami.objects.filter(event=event).order_by('tatami_number')
    perguruans = Perguruan.objects.filter(event=event).order_by('nama_perguruan')

    if request.method == 'POST':
        submit_type = request.POST.get('submit_type')

        if submit_type == 'tambah_wasit':
            nama = request.POST.get('nama_wasit', '').strip().upper()
            if not nama:
                messages.error(request, "Nama wasit wajib diisi.")
            else:
                perguruan_id = request.POST.get('perguruan') or None
                kab_kota = request.POST.get('kab_kota', '').strip()
                lisensi = request.POST.get('lisensi', '').strip()
                no_lisensi = request.POST.get('no_lisensi', '').strip()
                wasit = Wasit.objects.create(
                    event=event,
                    nama_wasit=nama,
                    perguruan_id=perguruan_id,
                    kab_kota=kab_kota or None,
                    lisensi=lisensi or None,
                    no_lisensi=no_lisensi or None,
                )
                tatami_id = request.POST.get('tatami_id')
                posisi = request.POST.get('posisi', 'pool')
                if tatami_id:
                    target_tatami = Tatami.objects.filter(pk=tatami_id, event=event).first()
                    if target_tatami:
                        if posisi != 'pool':
                            WasitTatami.objects.filter(tatami=target_tatami, posisi=posisi).delete()
                        WasitTatami.objects.create(
                            event=event,
                            tatami=target_tatami,
                            wasit=wasit,
                            posisi=posisi
                        )
                messages.success(request, f"Wasit '{nama}' berhasil ditambahkan ke master event.")
            return redirect('admin-wasit', event_pk=event.pk)

        elif submit_type == 'edit_wasit':
            wasit_id = request.POST.get('wasit_id')
            wasit = Wasit.objects.filter(pk=wasit_id, event=event).first()
            if not wasit:
                messages.error(request, "Data wasit tidak ditemukan.")
            else:
                nama = request.POST.get('nama_wasit', '').strip().upper()
                if not nama:
                    messages.error(request, "Nama wasit tidak boleh kosong.")
                else:
                    wasit.nama_wasit = nama
                    wasit.perguruan_id = request.POST.get('perguruan') or None
                    wasit.kab_kota = request.POST.get('kab_kota', '').strip() or None
                    wasit.lisensi = request.POST.get('lisensi', '').strip() or None
                    wasit.no_lisensi = request.POST.get('no_lisensi', '').strip() or None
                    wasit.save()

                    tatami_id = request.POST.get('tatami_id')
                    posisi = request.POST.get('posisi', 'pool')
                    if tatami_id == 'unassign' or not tatami_id:
                        WasitTatami.objects.filter(event=event, wasit=wasit).delete()
                    else:
                        target_tatami = Tatami.objects.filter(pk=tatami_id, event=event).first()
                        if target_tatami:
                            if posisi != 'pool':
                                WasitTatami.objects.filter(tatami=target_tatami, posisi=posisi).exclude(wasit=wasit).delete()
                            WasitTatami.objects.filter(event=event, wasit=wasit).delete()
                            WasitTatami.objects.create(
                                event=event,
                                tatami=target_tatami,
                                wasit=wasit,
                                posisi=posisi
                            )
                    messages.success(request, f"Data wasit '{wasit.nama_wasit}' berhasil diperbarui.")
            return redirect('admin-wasit', event_pk=event.pk)

        elif submit_type == 'hapus_wasit':
            wasit_id = request.POST.get('wasit_id')
            wasit = Wasit.objects.filter(pk=wasit_id, event=event).first()
            if wasit:
                nama = wasit.nama_wasit
                wasit.delete()
                messages.success(request, f"Wasit '{nama}' berhasil dihapus dari event.")
            return redirect('admin-wasit', event_pk=event.pk)

        elif submit_type == 'assign_tatami':
            wasit_id = request.POST.get('wasit_id')
            wasit = Wasit.objects.filter(pk=wasit_id, event=event).first()
            tatami_id = request.POST.get('tatami_id')
            posisi = request.POST.get('posisi', 'pool')

            if wasit:
                if not tatami_id or tatami_id == 'unassign':
                    WasitTatami.objects.filter(event=event, wasit=wasit).delete()
                    messages.success(request, f"Wasit '{wasit.nama_wasit}' dikembalikan ke pool (unassigned).")
                else:
                    target_tatami = Tatami.objects.filter(pk=tatami_id, event=event).first()
                    if target_tatami:
                        if posisi != 'pool':
                            WasitTatami.objects.filter(tatami=target_tatami, posisi=posisi).exclude(wasit=wasit).delete()
                        WasitTatami.objects.filter(event=event, wasit=wasit).delete()
                        WasitTatami.objects.create(
                            event=event,
                            tatami=target_tatami,
                            wasit=wasit,
                            posisi=posisi
                        )
                        posisi_label = dict(WasitTatami.POSISI_CHOICES).get(posisi, posisi)
                        messages.success(request, f"Wasit '{wasit.nama_wasit}' ditugaskan ke Tatami {target_tatami.tatami_number} ({posisi_label}).")
            return redirect('admin-wasit', event_pk=event.pk)

        elif submit_type == 'import_wasit_excel':
            excel_file = request.FILES.get('excel_wasit')
            if not excel_file:
                messages.error(request, "Pilih file Excel (.xlsx) atau CSV terlebih dahulu.")
                return redirect('admin-wasit', event_pk=event.pk)

            try:
                perguruan_cache = {p.nama_perguruan.upper(): p for p in Perguruan.objects.filter(event=event)}
                tatami_cache = {str(t.tatami_number): t for t in tatamis}
                created_count = 0

                fname = excel_file.name.lower()
                rows = []
                if fname.endswith('.csv'):
                    import csv
                    decoded_file = excel_file.read().decode('utf-8-sig', errors='replace').splitlines()
                    reader = csv.reader(decoded_file)
                    next(reader, None) # Skip header
                    for r in reader:
                        rows.append(r)
                else:
                    workbook = openpyxl.load_workbook(excel_file)
                    sheet = workbook.active
                    for r in sheet.iter_rows(min_row=2, values_only=True):
                        rows.append(r)

                with transaction.atomic():
                    for row in rows:
                        if not row or not any(row):
                            continue
                        cells = [str(c).strip() if c is not None else '' for c in row]
                        nama = cells[0].upper() if len(cells) > 0 else ''
                        perguruan_name = cells[1].upper() if len(cells) > 1 else ''
                        kab_kota = cells[2] if len(cells) > 2 else ''
                        lisensi = cells[3] if len(cells) > 3 else ''
                        no_lisensi = cells[4] if len(cells) > 4 else ''
                        tatami_target = cells[5] if len(cells) > 5 else ''

                        if not nama:
                            continue

                        perguruan_obj = None
                        if perguruan_name:
                            if perguruan_name not in perguruan_cache:
                                perguruan_cache[perguruan_name] = Perguruan.objects.create(event=event, nama_perguruan=perguruan_name)
                            perguruan_obj = perguruan_cache[perguruan_name]

                        wasit = Wasit.objects.create(
                            event=event,
                            nama_wasit=nama,
                            perguruan=perguruan_obj,
                            kab_kota=kab_kota or None,
                            lisensi=lisensi or None,
                            no_lisensi=no_lisensi or None,
                        )

                        clean_tatami_num = re.sub(r'[^0-9]', '', tatami_target)
                        if clean_tatami_num and clean_tatami_num in tatami_cache:
                            target_tatami = tatami_cache[clean_tatami_num]
                            WasitTatami.objects.create(
                                event=event,
                                tatami=target_tatami,
                                wasit=wasit,
                                posisi='pool'
                            )

                        created_count += 1

                messages.success(request, f"Berhasil mengimport {created_count} wasit.")
            except Exception as e:
                messages.error(request, f"Gagal mengimport file: {str(e)}")
            return redirect('admin-wasit', event_pk=event.pk)

    # GET: Prepare listing data
    all_wasits = list(
        Wasit.objects.filter(event=event)
        .select_related('perguruan')
        .order_by('nama_wasit')
    )
    all_assignments = list(
        WasitTatami.objects.filter(event=event)
        .select_related('tatami')
    )
    assignment_map = {a.wasit_id: a for a in all_assignments}

    for w in all_wasits:
        w.assignment = assignment_map.get(w.pk)

    total_wasit = len(all_wasits)
    assigned_wasit_count = len(assignment_map)
    pool_wasit_count = total_wasit - assigned_wasit_count

    tatami_stats = []
    for t in tatamis:
        c = sum(1 for a in all_assignments if a.tatami_id == t.pk)
        tatami_stats.append({'tatami': t, 'count': c})

    context = {
        'on': 'wasit',
        'event': event,
        'tatamis': tatamis,
        'perguruans': perguruans,
        'all_wasits': all_wasits,
        'posisi_choices': WasitTatami.POSISI_CHOICES,
        'metrics': {
            'total_wasit': total_wasit,
            'assigned_wasit': assigned_wasit_count,
            'pool_wasit': pool_wasit_count,
        },
        'tatami_stats': tatami_stats,
    }

    return render(request, 'admin/wasit.html', context)


def scoring_board(request, tatami_pk):
    tatami = Tatami.objects.filter(pk=tatami_pk).select_related(
        'event',
        'detail_bagan__bagan__nomor_tanding',
        'detail_bagan__atlet1__perguruan',
        'detail_bagan__atlet1__utusan',
        'detail_bagan__atlet2__perguruan',
        'detail_bagan__atlet2__utusan',
    ).first()
    if not tatami:
        tatami = get_object_or_404(Tatami, pk=tatami_pk)

    detail_bagan = tatami.detail_bagan
    atlet_merah = detail_bagan.atlet1 if detail_bagan else None
    atlet_biru = detail_bagan.atlet2 if detail_bagan else None

    from .utils import get_utusan_logo_url, get_round_label, get_round_of_slots, get_marquee_title
    initial_marquee_text = get_marquee_title(detail_bagan) if detail_bagan else ""

    # Support AJAX get_atlet fallback
    if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.POST.get('action') == 'get_atlet':
        bagan = detail_bagan.bagan if detail_bagan else None
        nomor_tanding = bagan.nomor_tanding.nama_nomor_tanding if (bagan and bagan.nomor_tanding) else ''
        nama_bagan = bagan.nama_bagan if bagan else ''
        round_label = get_round_label(detail_bagan) if detail_bagan else ''
        round_of = get_round_of_slots(detail_bagan) if detail_bagan else ''
        marquee_text = get_marquee_title(detail_bagan) if detail_bagan else ''
        data = {
            "atlet_red": atlet_merah.nama_atlet if atlet_merah else None,
            "atlet_red_perguruan": atlet_merah.perguruan.nama_perguruan if (atlet_merah and atlet_merah.perguruan) else None,
            "atlet_red_utusan": atlet_merah.utusan.nama_utusan if (atlet_merah and atlet_merah.utusan) else None,
            "atlet_red_logo": get_utusan_logo_url(atlet_merah),
            "atlet_red_kata": detail_bagan.kata1 if (detail_bagan and detail_bagan.kata1) else None,
            "atlet_red_vr": detail_bagan.vr1 if (detail_bagan and detail_bagan.vr1) else None,
            "atlet_blue": atlet_biru.nama_atlet if atlet_biru else None,
            "atlet_blue_perguruan": atlet_biru.perguruan.nama_perguruan if (atlet_biru and atlet_biru.perguruan) else None,
            "atlet_blue_utusan": atlet_biru.utusan.nama_utusan if (atlet_biru and atlet_biru.utusan) else None,
            "atlet_blue_logo": get_utusan_logo_url(atlet_biru),
            "atlet_blue_kata": detail_bagan.kata2 if (detail_bagan and detail_bagan.kata2) else None,
            "atlet_blue_vr": detail_bagan.vr2 if (detail_bagan and detail_bagan.vr2) else None,
            "tipe_tanding": bagan.tipe_tanding if bagan else '2',
            "team": True if (bagan and 'KUMITE BEREGU' in bagan.nama_bagan) else None,
            "total_aka_score": 0,
            "total_ao_score": 0,
            "nomor_tanding": nomor_tanding,
            "nama_bagan": nama_bagan,
            "round_label": round_label,
            "round_of": round_of,
            "marquee_text": marquee_text,
            "round": detail_bagan.round if detail_bagan else 1,
            "urutan": detail_bagan.urutan if detail_bagan else 1,
            "tatami_number": tatami.tatami_number,
            "nama_event": tatami.event.nama_event if (tatami and tatami.event) else '',
        }
        return JsonResponse({'status': 'success', 'data': data})

    context = {
        'tatami': tatami,
        'detail_bagan': detail_bagan,
        'atlet_merah': atlet_merah,
        'atlet_biru': atlet_biru,
        'initial_marquee_text': initial_marquee_text,
    }
    return render(request, 'admin/scoring-board.html', context)

@require_POST
def notify_bagan_running(request, detailbagan_pk):
    detail_bagan = DetailBagan.objects.filter(pk=detailbagan_pk).first()
    if not detail_bagan:
        return JsonResponse({'success': False, 'message': 'DetailBagan tidak ditemukan'}, status=404)

    tatami_obj = Tatami.objects.filter(detail_bagan=detail_bagan).first()
    payload = {
        'status': 'running',
        'detail_bagan_id': detail_bagan.pk,
        'bagan_id': detail_bagan.bagan.pk,
        'round': detail_bagan.round,
        'urutan': detail_bagan.urutan,
        'vr1': detail_bagan.vr1,
        'vr2': detail_bagan.vr2,
        'kode_realtime': get_kode_realtime(detail_bagan),
        'ring_number': tatami_obj.tatami_number if (tatami_obj and tatami_obj.tatami_number is not None) else '',
    }
    if detail_bagan.round != 10:
        send_to_hosted_async(payload, endpoint='api/status/', event=detail_bagan.bagan.event if detail_bagan.bagan else None)
    return JsonResponse({'success': True, 'message': 'Status queued for sync'})


@require_POST
def send_bagan_result(request, detailbagan_pk):
    detail_bagan = DetailBagan.objects.filter(pk=detailbagan_pk).first()
    if not detail_bagan:
        return JsonResponse({'success': False, 'message': 'DetailBagan tidak ditemukan'}, status=404)

    payload = {
        'status': 'finished',
        'detail_bagan_id': detail_bagan.pk,
        'kode_realtime': get_kode_realtime(detail_bagan),
        'pemenang': detail_bagan.pemenang,
        'score1': detail_bagan.score1,
        'score2': detail_bagan.score2,
    }
    send_to_hosted_async(payload, endpoint='api/result/', event=detail_bagan.bagan.event if detail_bagan.bagan else None)
    return JsonResponse({'success': True, 'message': 'Result queued for sync'})

# SORT ------------------------------------------------
AGE_ORDER = [
    'pra usia dini',
    'usia dini',
    'pra pemula',
    'pemula',
    'kadet',
    'junior',
    'senior',
]
AGE_LABELS = {
    'pra usia dini': 'Pra Usia Dini', 'usia dini': 'Usia Dini',
    'pra pemula': 'Pra Pemula', 'pemula': 'Pemula',
    'kadet': 'Kadet', 'junior': 'Junior', 'senior': 'Senior',
}

def get_age_index(name):
    name_lower = name.lower()
    for i, age in enumerate(AGE_ORDER):
        if age in name_lower:
            return i
    return len(AGE_ORDER)
def get_type_index(name):
    name_lower = name.lower()
    is_kata = 'kata' in name_lower
    is_kumite = 'kumite' in name_lower
    is_beregu = 'beregu' in name_lower
    is_putra = 'putra' in name_lower
    is_putri = 'putri' in name_lower
    if is_kata and not is_beregu:
        base = 0 
    elif is_kata and is_beregu:
        base = 2 
    elif is_kumite and not is_beregu:
        base = 4 
    elif is_kumite and is_beregu:
        base = 6 
    else:
        base = 8 

    if is_putra:
        return base
    elif is_putri:
        return base + 1
    return base + 0.5

def get_weight_key(name):
    match = re.search(r'([+-])\s*(\d+)\s*kg', name.lower())
    if match:
        sign, num = match.groups()
        sign_rank = 0 if sign == '-' else 1
        return (sign_rank, int(num))
    return (0.5, 0)  # no weight class in the name (e.g. Kata categories) — neutral, doesn't disturb ordering

def split_athletes_into_pools(atlets, num_pools, group_field='perguruan'):
    """
    Distributes athletes across `num_pools` pools such that:
    1. Total athlete count in every pool differs by at most 1 (|pool_i| - |pool_j| <= 1).
    2. Priority athletes (is_priority=True) are distributed as evenly as possible across pools.
    3. Athletes from each delegation are split as evenly as possible across all pools.
    4. Remainder athletes are assigned to pools with the greatest remaining capacity,
       with randomized tie-breaking to eliminate pool bias.
    """
    total_atlets = len(atlets)
    if num_pools <= 1:
        return [list(atlets)]

    base = total_atlets // num_pools
    remainder = total_atlets % num_pools
    target_counts = [base] * num_pools
    rem_pools = list(range(num_pools))
    random.shuffle(rem_pools)
    for p in rem_pools[:remainder]:
        target_counts[p] += 1

    priority_atlets = [a for a in atlets if getattr(a, 'is_priority', False)]
    regular_atlets = [a for a in atlets if not getattr(a, 'is_priority', False)]

    pools_atlets = [[] for _ in range(num_pools)]

    # 1. Distribute priority athletes across pools first
    if priority_atlets:
        p_delegations = defaultdict(list)
        for a in priority_atlets:
            gid = getattr(a, f'{group_field}_id', None) or getattr(a, group_field, None) or f'_ind_{getattr(a, "pk", id(a))}'
            p_delegations[gid].append(a)

        p_groups = list(p_delegations.values())
        random.shuffle(p_groups)
        p_groups.sort(key=len, reverse=True)

        for p_list in p_groups:
            random.shuffle(p_list)
            for a in p_list:
                eligible_pools = [p for p in range(num_pools) if len(pools_atlets[p]) < target_counts[p]]
                if not eligible_pools:
                    eligible_pools = list(range(num_pools))
                # Sort by: fewest priority athletes in pool, fewest total athletes in pool, random tiebreak
                eligible_pools.sort(key=lambda p: (
                    sum(1 for x in pools_atlets[p] if getattr(x, 'is_priority', False)),
                    len(pools_atlets[p]),
                    random.random()
                ))
                pools_atlets[eligible_pools[0]].append(a)

    # 2. Distribute regular athletes across pools balancing delegations
    delegations = defaultdict(list)
    for a in regular_atlets:
        gid = getattr(a, f'{group_field}_id', None)
        if gid is None:
            gid = getattr(a, group_field, None)
        if gid is None:
            gid = f'_individual_{getattr(a, "pk", id(a))}'
        delegations[gid].append(a)

    for gid in delegations:
        random.shuffle(delegations[gid])

    sorted_groups = sorted(delegations.items(), key=lambda x: len(x[1]), reverse=True)
    tiered_groups = []
    for _, tier in groupby(sorted_groups, key=lambda x: len(x[1])):
        tier_list = list(tier)
        random.shuffle(tier_list)
        tiered_groups.extend(tier_list)

    for gid, a_list in tiered_groups:
        k = len(a_list)
        base_give = k // num_pools
        rem = k % num_pools

        curr = 0
        if base_give > 0:
            for p in range(num_pools):
                space = target_counts[p] - len(pools_atlets[p])
                to_add = min(base_give, max(0, space))
                if to_add > 0:
                    pools_atlets[p].extend(a_list[curr:curr + to_add])
                    curr += to_add

        remaining_athletes = a_list[curr:]
        for a in remaining_athletes:
            pool_capacities = []
            for p in range(num_pools):
                cap = target_counts[p] - len(pools_atlets[p])
                if cap > 0:
                    same_del = sum(1 for x in pools_atlets[p] if (getattr(x, f'{group_field}_id', None) or getattr(x, group_field, None)) == (getattr(a, f'{group_field}_id', None) or getattr(a, group_field, None)))
                    pool_capacities.append((same_del, -cap, random.random(), p))
            if pool_capacities:
                pool_capacities.sort()
                best_p = pool_capacities[0][3]
                pools_atlets[best_p].append(a)
            else:
                p_min = min(range(num_pools), key=lambda p: len(pools_atlets[p]))
                pools_atlets[p_min].append(a)

    return pools_atlets


def split_count_balanced(total, parts, start_index=0):
    """Split a total count into `parts` groups as evenly as possible."""
    base = total // parts
    remainder = total % parts
    splits = [base] * parts
    idx = start_index
    for _ in range(remainder):
        splits[idx] += 1
        idx = (idx + 1) % parts
    return splits


def sort_key(nomor_tanding):
    name = nomor_tanding.nama_nomor_tanding or ''
    sign_rank, weight_num = get_weight_key(name)
    return (get_age_index(name), get_type_index(name), sign_rank, weight_num, name)

QUADRANT_OF_MATCH = {1: 'Q1', 2: 'Q1', 3: 'Q2', 4: 'Q2', 5: 'Q3', 6: 'Q3', 7: 'Q4', 8: 'Q4'}
HALF_OF_MATCH = {1: 'top', 2: 'top', 3: 'top', 4: 'top', 5: 'bottom', 6: 'bottom', 7: 'bottom', 8: 'bottom'}

PRIMARY_SLOTS = {
    1: 'atlet1', 2: 'atlet2', 3: 'atlet1', 4: 'atlet2',
    5: 'atlet1', 6: 'atlet2', 7: 'atlet1', 8: 'atlet2',
}
SECONDARY_SLOTS = {
    1: 'atlet2', 2: 'atlet1', 3: 'atlet2', 4: 'atlet1',
    5: 'atlet2', 6: 'atlet1', 7: 'atlet2', 8: 'atlet1',
}

QUADRANT_MATCHES = {
    'Q1': {'outer': 1, 'inner': 2},
    'Q2': {'outer': 4, 'inner': 3},
    'Q3': {'outer': 5, 'inner': 6},
    'Q4': {'outer': 8, 'inner': 7},
}


def slot_distance(s1, s2):
    """
    Tree distance between two slots s1=(m1, slot1) and s2=(m2, slot2):
    4: Opposite halves (meet in Final)
    3: Same half, opposite quadrants (meet in Semifinal)
    2: Same quadrant, different matches (meet in Quarterfinal)
    1: Same match (Round 1 opponent - collision!)
    """
    m1, _ = s1
    m2, _ = s2
    if m1 == m2:
        return 1
    if QUADRANT_OF_MATCH[m1] == QUADRANT_OF_MATCH[m2]:
        return 2
    if HALF_OF_MATCH[m1] == HALF_OF_MATCH[m2]:
        return 3
    return 4


def slot_penalty(s1, s2):
    d = slot_distance(s1, s2)
    if d == 1:
        return 1_000_000
    if d == 2:
        return 10_000
    if d == 3:
        return 100
    return 0


def generate_balanced_slots(N):
    """
    Generates balanced slot assignments across halves and quadrants:
    - Balances Top Half and Bottom Half (|top - bot| <= 1)
    - Balances all 4 Quadrants (|q_i - q_j| <= 1)
    - When N <= 8, each athlete gets a unique match in the primary slot (no round 1 collision)
    - When N > 8, all 8 matches have 1 primary slot, and N - 8 secondary slots are balanced
    - Uses outer corner seeds first (1, 4, 5, 8) then inner seeds (2, 3, 6, 7)
    - Randomizes half and quadrant parity on odd counts to maintain uniform entropy
    """
    N = min(N, 16)
    slots = []

    # 1. Primary slots (at most 8)
    n_primary = min(N, 8)
    n_top = n_primary // 2
    n_bot = n_primary - n_top
    if n_top != n_bot and random.random() < 0.5:
        n_top, n_bot = n_bot, n_top

    q1 = n_top // 2
    q2 = n_top - q1
    if q1 != q2 and random.random() < 0.5:
        q1, q2 = q2, q1

    q3 = n_bot // 2
    q4 = n_bot - q3
    if q3 != q4 and random.random() < 0.5:
        q3, q4 = q4, q3

    q_counts = {'Q1': q1, 'Q2': q2, 'Q3': q3, 'Q4': q4}
    for q, cnt in q_counts.items():
        outer_m = QUADRANT_MATCHES[q]['outer']
        inner_m = QUADRANT_MATCHES[q]['inner']
        if cnt == 1:
            chosen_m = outer_m if random.random() < 0.5 else inner_m
            slots.append((chosen_m, PRIMARY_SLOTS[chosen_m]))
        elif cnt == 2:
            slots.append((outer_m, PRIMARY_SLOTS[outer_m]))
            slots.append((inner_m, PRIMARY_SLOTS[inner_m]))

    # 2. Secondary slots (when N > 8)
    n_sec = max(0, N - 8)
    if n_sec > 0:
        sec_top = n_sec // 2
        sec_bot = n_sec - sec_top
        if sec_top != sec_bot and random.random() < 0.5:
            sec_top, sec_bot = sec_bot, sec_top

        sq1 = sec_top // 2
        sq2 = sec_top - sq1
        if sq1 != sq2 and random.random() < 0.5:
            sq1, sq2 = sq2, sq1

        sq3 = sec_bot // 2
        sq4 = sec_bot - sq3
        if sq3 != sq4 and random.random() < 0.5:
            sq3, sq4 = sq4, sq3

        sec_counts = {'Q1': sq1, 'Q2': sq2, 'Q3': sq3, 'Q4': sq4}
        for q, cnt in sec_counts.items():
            outer_m = QUADRANT_MATCHES[q]['outer']
            inner_m = QUADRANT_MATCHES[q]['inner']
            if cnt == 1:
                # Prioritize inner matches for preliminary fight so corner seeds retain BYEs
                chosen_m = inner_m if random.random() < 0.75 else outer_m
                slots.append((chosen_m, SECONDARY_SLOTS[chosen_m]))
            elif cnt == 2:
                slots.append((inner_m, SECONDARY_SLOTS[inner_m]))
                slots.append((outer_m, SECONDARY_SLOTS[outer_m]))

    return slots


def build_bracket_in_memory(atlets, group_field='perguruan', pool=1, has_vr=False):
    """
    Builds the complete 5-round tournament bracket in memory.
    Enforces anti-collision (same group separated as far as possible in the tree),
    balanced quadrant and half separation, and subtree-aware BYE propagation.
    Returns: (matches dict, collision_count)
    """
    matches = {
        1: {u: {'atlet1': None, 'atlet2': None, 'vr1': False, 'vr2': False} for u in range(1, 9)},
        2: {u: {'atlet1': None, 'atlet2': None, 'vr1': False, 'vr2': False} for u in range(1, 5)},
        3: {u: {'atlet1': None, 'atlet2': None, 'vr1': False, 'vr2': False} for u in range(1, 3)},
        4: {1: {'atlet1': None, 'atlet2': None, 'vr1': False, 'vr2': False}},
        5: {1: {'atlet1': None, 'atlet2': None, 'vr1': False, 'vr2': False}},
    }

    if not atlets:
        if has_vr:
            for u in range(1, 3):
                matches[3][u]['vr1'] = True
                matches[3][u]['vr2'] = True
            matches[4][1]['vr1'] = True
            matches[4][1]['vr2'] = True
            if pool == 0:
                matches[1][1]['vr1'] = True
                matches[1][1]['vr2'] = True
        return matches, 0

    atlets = list(atlets[:16])

    # Separate priority athletes and regular athletes
    priority_atlets = [a for a in atlets if (getattr(a, 'is_priority', False) if not isinstance(a, dict) else a.get('is_priority', False))]
    regular_atlets = [a for a in atlets if not (getattr(a, 'is_priority', False) if not isinstance(a, dict) else a.get('is_priority', False))]

    def get_gid(a):
        gid = getattr(a, f'{group_field}_id', None)
        if gid is None:
            gid = getattr(a, group_field, None)
        if gid is None and isinstance(a, dict):
            gid = a.get(f'{group_field}_id') or a.get(group_field)
        if gid is None:
            gid = f'_individual_{getattr(a, "pk", id(a))}'
        return gid

    total_atlets = len(atlets)
    best_candidates = []
    best_score = float('inf')

    # Multi-trial optimization to maximize priority BYE placement, delegation separation, and tree balance
    num_trials = 60
    for _ in range(num_trials):
        slots = generate_balanced_slots(total_atlets)
        random.shuffle(slots)
        available = list(slots)
        assignment = {}
        placed_by_gid = defaultdict(list)
        placed_priority_slots = []
        trial_score = 0

        match_counts = Counter(m for m, _ in slots)

        def get_slot_bye_level(s):
            m, _ = s
            if match_counts[m] > 1:
                return 0  # No BYE (Round 1 fight)
            # Match m has only 1 athlete, so guaranteed at least Round 1 BYE
            paired_m = (m + 1) if (m % 2 != 0) else (m - 1)
            if match_counts.get(paired_m, 0) > 0:
                return 1  # Single BYE (advances to Quarterfinal / Round 2)
            # Check if opposing quadrant is completely empty
            half = HALF_OF_MATCH[m]
            opposing_quad_matches = [om for om in (1, 2, 3, 4, 5, 6, 7, 8) if HALF_OF_MATCH[om] == half and QUADRANT_OF_MATCH[om] != QUADRANT_OF_MATCH[m]]
            if sum(match_counts.get(om, 0) for om in opposing_quad_matches) == 0:
                return 3  # Triple BYE (advances to Final / Round 4)
            return 2  # Double BYE (advances to Semifinal / Round 3)

        # 1. Place priority athletes into highest BYE level slots first
        if priority_atlets:
            shuffled_prio = list(priority_atlets)
            random.shuffle(shuffled_prio)
            for a in shuffled_prio:
                gid = get_gid(a)
                max_bye = max(get_slot_bye_level(s) for s in available)
                candidate_slots = [s for s in available if get_slot_bye_level(s) == max_bye]

                best_p = float('inf')
                candidates = []
                for s in candidate_slots:
                    # Penalize collision with other priority athletes and same delegation
                    p_prio = sum(slot_penalty(s, prev_s) for prev_s in placed_priority_slots)
                    p_del = sum(slot_penalty(s, prev_s) for prev_s in placed_by_gid[gid])
                    p = 2 * p_prio + p_del
                    if p < best_p:
                        best_p = p
                        candidates = [s]
                    elif p == best_p:
                        candidates.append(s)

                chosen = random.choice(candidates)
                available.remove(chosen)
                assignment[a] = chosen
                placed_priority_slots.append(chosen)
                placed_by_gid[gid].append(chosen)
                trial_score += best_p
                # Penalty if priority athlete couldn't get a BYE slot
                if max_bye == 0:
                    trial_score += 500_000

        # 2. Place regular athletes balancing delegations
        if regular_atlets:
            reg_delegations = defaultdict(list)
            for a in regular_atlets:
                reg_delegations[get_gid(a)].append(a)

            groups = list(reg_delegations.items())
            random.shuffle(groups)
            groups.sort(key=lambda x: len(x[1]), reverse=True)

            for gid, a_list in groups:
                shuffled_a = list(a_list)
                random.shuffle(shuffled_a)
                for a in shuffled_a:
                    best_p = float('inf')
                    candidates = []
                    for s in available:
                        p = sum(slot_penalty(s, prev_s) for prev_s in placed_by_gid[gid])
                        if p < best_p:
                            best_p = p
                            candidates = [s]
                        elif p == best_p:
                            candidates.append(s)
                    chosen = random.choice(candidates)
                    available.remove(chosen)
                    assignment[a] = chosen
                    placed_by_gid[gid].append(chosen)
                    trial_score += best_p

        if trial_score < best_score:
            best_score = trial_score
            best_candidates = [assignment]
        elif trial_score == best_score:
            best_candidates.append(assignment)

    best_assignment = random.choice(best_candidates)

    # Populate Round 1 matches
    initial_round_1 = {}
    for a, (m, slot_field) in best_assignment.items():
        matches[1][m][slot_field] = a
        if has_vr:
            matches[1][m]['vr1' if slot_field == 'atlet1' else 'vr2'] = True
        initial_round_1[(m, slot_field)] = a

    # Count Round 1 collisions
    collision_count = 0
    for u in range(1, 9):
        a1 = matches[1][u]['atlet1']
        a2 = matches[1][u]['atlet2']
        if a1 and a2:
            g1 = getattr(a1, f'{group_field}_id', None) or getattr(a1, group_field, None)
            g2 = getattr(a2, f'{group_field}_id', None) or getattr(a2, group_field, None)
            if g1 and g2 and g1 == g2:
                collision_count += 1

    # In-memory advancement (Subtree-aware BYE propagation)
    def count_initial(slots_to_check):
        return sum(1 for slot in slots_to_check if initial_round_1.get(slot) is not None)

    # Round 1 -> 2
    for u in range(1, 9):
        target_u = (u + 1) // 2
        target_slot = 'atlet1' if u % 2 != 0 else 'atlet2'
        m1 = matches[1][u]
        if m1['atlet1'] and not m1['atlet2']:
            matches[2][target_u][target_slot] = m1['atlet1']
            if has_vr:
                matches[2][target_u]['vr1' if target_slot == 'atlet1' else 'vr2'] = True
            m1['atlet1'] = None
            m1['vr1'] = False
        elif m1['atlet2'] and not m1['atlet1']:
            matches[2][target_u][target_slot] = m1['atlet2']
            if has_vr:
                matches[2][target_u]['vr1' if target_slot == 'atlet1' else 'vr2'] = True
            m1['atlet2'] = None
            m1['vr2'] = False

    # Pre-seed Semi-Finals (Round 3) if has_vr for ALL pools
    if has_vr:
        for target_u in range(1, 3):
            matches[3][target_u]['vr1'] = True
            matches[3][target_u]['vr2'] = True

    # Round 2 -> 3
    for u in range(1, 5):
        target_u = (u + 1) // 2
        target_slot = 'atlet1' if u % 2 != 0 else 'atlet2'
        m2 = matches[2][u]

        # Check atlet1 (fed by R1 match 2u-1, opposing branch is R1 match 2u)
        if m2['atlet1']:
            opposing_slots = [(2 * u, 'atlet1'), (2 * u, 'atlet2')]
            if count_initial(opposing_slots) == 0:
                matches[3][target_u][target_slot] = m2['atlet1']
                if has_vr:
                    matches[3][target_u]['vr1' if target_slot == 'atlet1' else 'vr2'] = True
                m2['atlet1'] = None
                m2['vr1'] = False
        # Check atlet2 (fed by R1 match 2u, opposing branch is R1 match 2u-1)
        if m2['atlet2']:
            opposing_slots = [(2 * u - 1, 'atlet1'), (2 * u - 1, 'atlet2')]
            if count_initial(opposing_slots) == 0:
                matches[3][target_u][target_slot] = m2['atlet2']
                if has_vr:
                    matches[3][target_u]['vr1' if target_slot == 'atlet1' else 'vr2'] = True
                m2['atlet2'] = None
                m2['vr2'] = False

    # Pre-seed Finals (Round 4) if has_vr for ALL pools
    if has_vr:
        matches[4][1]['vr1'] = True
        matches[4][1]['vr2'] = True

    q_slots = {
        'Q1': [(m, s) for m in (1, 2) for s in ('atlet1', 'atlet2')],
        'Q2': [(m, s) for m in (3, 4) for s in ('atlet1', 'atlet2')],
        'Q3': [(m, s) for m in (5, 6) for s in ('atlet1', 'atlet2')],
        'Q4': [(m, s) for m in (7, 8) for s in ('atlet1', 'atlet2')],
    }
    r3_opposing = {
        (1, 'atlet1'): q_slots['Q2'],
        (1, 'atlet2'): q_slots['Q1'],
        (2, 'atlet1'): q_slots['Q4'],
        (2, 'atlet2'): q_slots['Q3'],
    }
    for u in (1, 2):
        target_slot = 'atlet1' if u == 1 else 'atlet2'
        m3 = matches[3][u]
        if m3['atlet1']:
            if count_initial(r3_opposing[(u, 'atlet1')]) == 0:
                matches[4][1][target_slot] = m3['atlet1']
                if has_vr:
                    matches[4][1]['vr1' if target_slot == 'atlet1' else 'vr2'] = True
                m3['atlet1'] = None
                m3['vr1'] = False
        if m3['atlet2']:
            if count_initial(r3_opposing[(u, 'atlet2')]) == 0:
                matches[4][1][target_slot] = m3['atlet2']
                if has_vr:
                    matches[4][1]['vr1' if target_slot == 'atlet1' else 'vr2'] = True
                m3['atlet2'] = None
                m3['vr2'] = False

    return matches, collision_count


def build_full_bracket(
    event, nomor_tanding, nama_bagan, pool=1,
    group_counts=None, atlets_temp=None, group_field='perguruan',
):
    """
    Runs the entire pipeline for one Bagan (one pool or the whole category).
    Builds all 5 rounds and BYE advancements in-memory, then performs a single
    bulk_create of DetailBagan objects.
    Returns: (bagan, round_5_detail_bagan, collision_count)
    """
    # Normalize athletes list if passed as 5th positional arg
    if atlets_temp is None and group_counts is not None:
        if isinstance(group_counts, list) and group_counts and hasattr(group_counts[0], 'pk'):
            atlets_temp = group_counts
        else:
            atlets_temp = []
    elif atlets_temp is None:
        atlets_temp = []

    name = (nomor_tanding.nama_nomor_tanding or '') if nomor_tanding else ''
    if 'KATA' in name.upper():
        tipe_tanding = '1'
    elif 'KUMITE' in name.upper():
        tipe_tanding = '2'
    else:
        tipe_tanding = None

    has_vr = bool(
        nomor_tanding and
        getattr(nomor_tanding, 'has_vr', False) and
        tipe_tanding == '2' and
        'festival' not in name.lower()
    )

    bagan = Bagan.objects.create(
        event=event,
        nomor_tanding=nomor_tanding,
        nama_bagan=nama_bagan,
        pool=pool,
        tipe_tanding=tipe_tanding,
        has_vr=has_vr,
    )

    bracket_data, collision_count = build_bracket_in_memory(
        atlets_temp, group_field=group_field, pool=pool, has_vr=has_vr
    )

    detail_bagans = []
    for r in range(1, 5):
        for u in sorted(bracket_data[r].keys()):
            m = bracket_data[r][u]
            detail_bagans.append(
                DetailBagan(
                    bagan=bagan,
                    round=r,
                    urutan=u,
                    atlet1=m['atlet1'],
                    atlet2=m['atlet2'],
                    vr1=m['vr1'],
                    vr2=m['vr2'],
                )
            )

    detail_bagans.append(
        DetailBagan(
            bagan=bagan,
            round=5,
            urutan=1,
            atlet1=bracket_data[5][1]['atlet1'],
            atlet2=bracket_data[5][1]['atlet2'],
            vr1=bracket_data[5][1]['vr1'],
            vr2=bracket_data[5][1]['vr2'],
        )
    )

    DetailBagan.objects.bulk_create(detail_bagans)
    round_5 = DetailBagan.objects.filter(bagan=bagan, round=5, urutan=1).first()
    return bagan, round_5, collision_count


def create_bagan_and_seed(event, nomor_tanding, nama_bagan, pool, group_counts, atlets_temp, group_field, custom_order=None, atlet_assignment1=None):
    """Backwards compatibility wrapper for external callers."""
    bagan, _, _ = build_full_bracket(event, nomor_tanding, nama_bagan, pool, group_counts, atlets_temp, group_field)
    return bagan

def get_age_group(name):
    name_lower = (name or '').lower()
    if 'pra usia dini' in name_lower:
        return 'Pra Usia Dini'
    if 'usia dini' in name_lower:
        return 'Usia Dini'
    if 'pra pemula' in name_lower:
        return 'Pra Pemula'
    if 'pemula' in name_lower:
        return 'Pemula'
    if 'kadet' in name_lower or 'cadet' in name_lower:
        return 'Kadet'
    if 'junior' in name_lower:
        return 'Junior'
    if any(k in name_lower for k in ['under-21', 'under 21', 'u-21', 'u21']):
        return 'Under-21'
    if 'senior' in name_lower:
        return 'Senior'
    if 'veteran' in name_lower:
        return 'Veteran'
    return 'Lainnya'

INDO_MONTHS = ['Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni', 'Juli',
               'Agustus', 'September', 'Oktober', 'November', 'Desember']

def format_day_label(day):
    day_number = day.order + 1
    if day.tanggal:
        t = day.tanggal
        return f"Day {day_number}, {t.day} {INDO_MONTHS[t.month - 1]} {t.year}"
    return f"Day {day_number}"

def timetable_editor(request, event_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    tatamis = Tatami.objects.filter(event=event).order_by('tatami_number')

    days = TimetableDay.objects.filter(event=event).prefetch_related('rows__cells')

    if not days.exists():
        first_day = TimetableDay.objects.create(event=event, order=0)
        days = TimetableDay.objects.filter(event=event).prefetch_related('rows__cells')

    atlet_counts = dict(
        Atlet.objects.filter(nomor_tanding__event=event)
        .values('nomor_tanding').annotate(cnt=Count('id'))
        .values_list('nomor_tanding', 'cnt')
    )
    nomor_tanding_qs = NomorTanding.objects.filter(event=event).order_by('nama_nomor_tanding')

    # Build detailed metadata per nomor_tanding
    nt_with_group = []
    nt_athletes_map = defaultdict(list)
    athlete_names = {}

    all_atlets = list(
        Atlet.objects.filter(event=event, nomor_tanding__isnull=False)
        .select_related('nomor_tanding')
        .values('id', 'nama_atlet', 'nomor_tanding_id', 'nomor_tanding__nama_nomor_tanding', 'utusan_id')
    )

    # 1. Collect individual athlete names across non-beregu categories
    individual_athletes = set()
    individual_by_utusan = defaultdict(list)
    for a in all_atlets:
        raw_name = (a['nama_atlet'] or '').strip().upper()
        nt_name = (a['nomor_tanding__nama_nomor_tanding'] or '').lower()
        if 'beregu' not in nt_name:
            norm = re.sub(r'[^A-Z0-9\s]', '', raw_name)
            norm = re.sub(r'\s+', ' ', norm).strip()
            if len(norm) >= 3:
                individual_athletes.add(norm)
                athlete_names[norm] = a['nama_atlet'].strip()
                if a.get('utusan_id'):
                    individual_by_utusan[a['utusan_id']].append(norm)

    STOP_WORDS = {'TEAM', 'DOJO', 'INKANAS', 'FORKI', 'LEMKARI', 'WADOKAI', 'KUTAI', 'SAMARINDA', 'BALIKPAPAN', 'PUTRA', 'PUTRI', 'GABUNGAN', 'CAMPURAN', 'CS', 'DAN', 'AND', 'BIN', 'BINTI'}

    # 2. Map athletes to each nomor_tanding with Beregu <-> Perorangan cross-matching
    for a in all_atlets:
        nt_id = a['nomor_tanding_id']
        raw_name = (a['nama_atlet'] or '').strip().upper()
        norm = re.sub(r'[^A-Z0-9\s]', '', raw_name)
        norm = re.sub(r'\s+', ' ', norm).strip()
        if not norm:
            continue

        if norm not in nt_athletes_map[nt_id]:
            nt_athletes_map[nt_id].append(norm)
        if norm not in athlete_names:
            athlete_names[norm] = a['nama_atlet'].strip()

        # Check if team or comma-delimited entry contains known individual athlete (full name match)
        for ind in individual_athletes:
            words = ind.split()
            if len(words) >= 2 and (ind in norm or norm in ind):
                if ind not in nt_athletes_map[nt_id]:
                    nt_athletes_map[nt_id].append(ind)

        # For callnames/nicknames inside parentheses e.g. '(FAJAR CS)', '(BIMA CS)':
        # Strictly scope to the athlete's SAME utusan (dojo) to prevent false cross-dojo conflicts!
        u_id = a.get('utusan_id')
        if u_id and u_id in individual_by_utusan:
            dojo_inds = individual_by_utusan[u_id]
            parens = re.findall(r'\((.*?)\)', raw_name)
            for p in parens:
                cleaned = re.sub(r'\bCS\b', '', p).strip()
                tokens = [t for t in re.findall(r'[A-Z0-9]+', cleaned) if len(t) >= 3 and t not in STOP_WORDS]
                for t in tokens:
                    for ind in dojo_inds:
                        ind_tokens = ind.split()
                        if t in ind_tokens:
                            if ind not in nt_athletes_map[nt_id]:
                                nt_athletes_map[nt_id].append(ind)

    festival_total_atlets = 0
    for nt in nomor_tanding_qs:
        cnt = atlet_counts.get(nt.pk, 0)
        nama_upper = nt.nama_nomor_tanding.upper()
        is_fest = 'FESTIVAL' in nama_upper
        if is_fest:
            festival_total_atlets += cnt
        is_kata = 'KATA' in nama_upper

        if is_kata:
            dur_per_match = 3.5
            discipline = 'kata'
        elif any(k in nama_upper for k in ['SENIOR', 'U-21', 'UNDER 21', 'UNDER-21']):
            dur_per_match = 6.0
            discipline = 'kumite'
        elif any(k in nama_upper for k in ['CADET', 'KADET', 'JUNIOR']):
            dur_per_match = 4.5
            discipline = 'kumite'
        else:
            dur_per_match = 4.0
            discipline = 'kumite'

        if cnt > 1:
            matches = cnt - 1
            est_dur = max(15, round(matches * dur_per_match))
        elif cnt == 1:
            matches = 0
            est_dur = 15
        else:
            matches = 0
            est_dur = 0

        nt_with_group.append({
            'pk': nt.pk,
            'nama': nt.nama_nomor_tanding,
            'age_group': get_age_group(nt.nama_nomor_tanding),
            'atlet_count': cnt,
            'matches': matches,
            'discipline': discipline,
            'est_duration_minutes': est_dur,
            'is_festival': is_fest,
        })

    ordered_labels = [
        'Pra Usia Dini', 'Usia Dini', 'Pra Pemula', 'Pemula',
        'Kadet', 'Junior', 'Under-21', 'Senior', 'Veteran', 'Lainnya'
    ]
    age_groups = [g for g in ordered_labels if any(nt['age_group'] == g for nt in nt_with_group)]

    tatami_count = tatamis.count() or 1
    festival_atlets_per_tatami = round(festival_total_atlets / tatami_count) if tatami_count else 0

    # Pre-build duration lookup from computed nt_with_group data
    nt_duration_map = {nt['pk']: nt['est_duration_minutes'] for nt in nt_with_group}

    days_data = []
    for day in days:
        cell_map = {row.id: {c.tatami_id: c for c in row.cells.all()} for row in day.rows.all()}
        tatami_columns = []
        for tatami in tatamis:
            cells_for_tatami = []
            total_col_atlets = 0
            for row in day.rows.all():
                if row.row_type == 'slot':
                    c = cell_map.get(row.id, {}).get(tatami.id)
                    if c and (c.nomor_tanding_id or c.custom_text):
                        c.is_festival = False
                        c.is_break = False
                        c.cell_time = ''
                        c.cell_title = ''
                        c.cell_duration = 15
                        c.atlet_count = 0

                        if c.nomor_tanding:
                            c.cell_title = c.nomor_tanding.nama_nomor_tanding
                            c.atlet_count = atlet_counts.get(c.nomor_tanding_id, 0)
                            c.cell_duration = nt_duration_map.get(c.nomor_tanding_id, 15) or 15
                            ct = c.custom_text or ''
                            time_m = re.search(r'(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})', ct)
                            if time_m:
                                c.cell_time = time_m.group(1).replace(' ', '')
                            else:
                                c.cell_time = ct.strip()
                            total_col_atlets += c.atlet_count
                        elif c.custom_text:
                            ct = c.custom_text.strip()
                            time_m = re.search(r'(\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2})', ct)
                            if time_m:
                                c.cell_time = time_m.group(1).replace(' ', '')
                                try:
                                    p = c.cell_time.split('-')
                                    sh, sm = map(int, p[0].split(':'))
                                    eh, em = map(int, p[1].split(':'))
                                    c.cell_duration = max(15, (eh * 60 + em) - (sh * 60 + sm))
                                except Exception:
                                    c.cell_duration = 30
                            ct_upper = ct.upper()
                            if 'FESTIVAL' in ct_upper:
                                c.is_festival = True
                                m = re.search(r'\((\d+)\)', ct)
                                if m:
                                    c.atlet_count = int(m.group(1))
                                c.cell_title = f"FESTIVAL ({c.atlet_count})" if c.atlet_count else "FESTIVAL"
                                total_col_atlets += c.atlet_count
                            elif any(k in ct_upper for k in ['ISHOMA', 'BREAK', 'ISTIRAHAT', 'JEDA']):
                                c.is_break = True
                                c.cell_title = ct.replace(f"({c.cell_time})", "").strip() if c.cell_time else ct
                            else:
                                c.cell_title = ct.replace(f"({c.cell_time})", "").strip() if c.cell_time else ct

                        cells_for_tatami.append(c)
            tatami_columns.append({
                'tatami': tatami,
                'cells': cells_for_tatami,
                'total_atlets': total_col_atlets,
            })

        days_data.append({
            'pk': day.pk,
            'label': format_day_label(day),
            'tanggal': day.tanggal.isoformat() if day.tanggal else '',
            'rows': day.rows.all(),
            'cell_map': cell_map,
            'tatami_columns': tatami_columns,
        })

    kop, _ = KopSurat.objects.get_or_create(event=event)
    kop_surat_data = {
        'logo_url': kop.logo.url if kop.logo else '',
        'nama_organisasi': kop.nama_organisasi,
        'alamat': kop.alamat,
        'kontak': kop.kontak,
    }

    keterangan, _ = EventKeterangan.objects.get_or_create(event=event)

    conflict_data = {
        'nt_athletes': dict(nt_athletes_map),
        'athlete_names': athlete_names,
    }

    context = {
        'event': event,
        'on': 'roster-maker',
        'tatamis': tatamis,
        'days_data': days_data,
        'nt_with_group': nt_with_group,
        'age_groups': age_groups,
        'kop_surat': kop_surat_data,
        'atlet_counts': atlet_counts,
        'keterangan_text': keterangan.text,
        'festival_total_atlets': festival_total_atlets,
        'festival_atlets_per_tatami': festival_atlets_per_tatami,
        'conflict_data_json': conflict_data,
        'categories_meta_json': nt_with_group,
    }
    return render(request, 'admin/timetable_editor.html', context)


@require_POST
def add_day(request, event_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    event = get_object_or_404(Event, pk=event_pk)
    next_order = TimetableDay.objects.filter(event=event).count()
    day = TimetableDay.objects.create(event=event, order=next_order)
    return JsonResponse({'success': True, 'id': day.pk, 'order': day.order, 'label': format_day_label(day)})


@require_POST
def delete_day(request, event_pk, day_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    day = get_object_or_404(TimetableDay, pk=day_pk, event_id=event_pk)
    day.delete()
    return JsonResponse({'success': True})


@require_POST
def timetable_save(request, event_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    event = get_object_or_404(Event, pk=event_pk)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    with transaction.atomic():
        for day_data in data.get('days', []):
            day = TimetableDay.objects.filter(pk=day_data.get('day_pk'), event=event).first()
            if not day:
                continue

            tanggal = day_data.get('tanggal') or None
            day.tanggal = tanggal
            day.save()

            TimetableRow.objects.filter(day=day).delete()

            cells_to_create = []
            for order, row_data in enumerate(day_data.get('rows', [])):
                row = TimetableRow.objects.create(
                    day=day, order=order,
                    row_type=row_data.get('row_type', 'slot'),
                    time_label=row_data.get('time_label', ''),
                    label_text=row_data.get('label_text', ''),
                )
                if row.row_type == 'slot':
                    for cell_data in row_data.get('cells', []):
                        tatami_id = cell_data.get('tatami_id')
                        if not tatami_id:
                            continue
                        cells_to_create.append(TimetableCell(
                            row=row,
                            tatami_id=tatami_id,
                            nomor_tanding_id=cell_data.get('nomor_tanding_id') or None,
                            custom_text=cell_data.get('custom_text', ''),
                        ))
            if cells_to_create:
                TimetableCell.objects.bulk_create(cells_to_create)

    return JsonResponse({'success': True})

@require_POST
def add_tatami(request, event_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    event = get_object_or_404(Event, pk=event_pk)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    tatami_number = data.get('tatami_number')
    if not tatami_number:
        return JsonResponse({'success': False, 'message': 'tatami_number is required'}, status=400)

    tatami = Tatami.objects.create(event=event, tatami_number=tatami_number)
    return JsonResponse({'success': True, 'id': tatami.pk, 'tatami_number': tatami.tatami_number})

@require_POST
def delete_tatami(request, event_pk, tatami_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    tatami = get_object_or_404(Tatami, pk=tatami_pk, event_id=event_pk)
    tatami.delete()  # cascades to TimetableCell rows referencing it
    return JsonResponse({'success': True})

def kop_surat_get(request, event_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    event = get_object_or_404(Event, pk=event_pk)
    kop, _ = KopSurat.objects.get_or_create(event=event)
    return JsonResponse({
        'success': True,
        'logo_url': kop.logo.url if kop.logo else '',
        'nama_organisasi': kop.nama_organisasi,
        'alamat': kop.alamat,
        'kontak': kop.kontak,
    })

@require_POST
def kop_surat_save(request, event_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    event = get_object_or_404(Event, pk=event_pk)
    kop, _ = KopSurat.objects.get_or_create(event=event)

    kop.nama_organisasi = request.POST.get('nama_organisasi', '')
    kop.alamat = request.POST.get('alamat', '')
    kop.kontak = request.POST.get('kontak', '')

    if request.POST.get('remove_logo') == 'true':
        if kop.logo:
            kop.logo.delete(save=False)
            kop.logo = None
    elif request.FILES.get('logo'):
        kop.logo = request.FILES['logo']

    kop.save()
    return JsonResponse({
        'success': True,
        'logo_url': kop.logo.url if kop.logo else '',
    })

@require_POST
def keterangan_save(request, event_pk):
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)
    event = get_object_or_404(Event, pk=event_pk)
    keterangan, _ = EventKeterangan.objects.get_or_create(event=event)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'message': 'Invalid JSON'}, status=400)

    keterangan.text = data.get('text', '')
    keterangan.save()
    return JsonResponse({'success': True})

def get_ordered_bagans_for_tatami(day, tatami):
    rows = (
        TimetableRow.objects
        .filter(day=day, row_type='slot')
        .order_by('order')
        .prefetch_related('cells')
    )

    seen_nt_ids = []
    for row in rows:
        cell = next((c for c in row.cells.all() if c.tatami_id == tatami.id), None)
        if cell and cell.nomor_tanding_id and cell.nomor_tanding_id not in seen_nt_ids:
            seen_nt_ids.append(cell.nomor_tanding_id)

    if not seen_nt_ids:
        return []

    all_bagans = list(Bagan.objects.filter(nomor_tanding_id__in=seen_nt_ids, event=day.event))
    bagans_by_nt = defaultdict(list)
    for b in all_bagans:
        bagans_by_nt[b.nomor_tanding_id].append(b)

    ordered_bagans = []
    for nt_id in seen_nt_ids:
        bagans = bagans_by_nt.get(nt_id, [])
        bagans.sort(key=lambda b: (1 if b.pool == 0 else 0, b.nama_bagan or ''))
        ordered_bagans.extend(bagans)

    return ordered_bagans

def _render_multiple_pdfs_worker(session_cookie_name, session_cookie_value, base_url, target_urls):
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

    pdf_bytes_list = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context()

        if session_cookie_value:
            context.add_cookies([{
                'name': session_cookie_name,
                'value': session_cookie_value,
                'url': base_url,
            }])

        page = context.new_page()
        for target_url in target_urls:
            try:
                page.goto(target_url, wait_until='networkidle', timeout=20000)
                pdf_bytes = page.pdf(
                    format='A4',
                    landscape=True,
                    print_background=True,
                    margin={'top': '0', 'bottom': '0', 'left': '0', 'right': '0'},
                )
                pdf_bytes_list.append(pdf_bytes)
            except Exception as e:
                logger.error(f"Error rendering PDF for {target_url}: {e}")
        browser.close()
    return pdf_bytes_list


def render_authenticated_pages_to_pdf(request, urls):
    session_cookie_value = request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    base_url = request.build_absolute_uri('/')

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            _render_multiple_pdfs_worker,
            settings.SESSION_COOKIE_NAME,
            session_cookie_value,
            base_url,
            urls,
        )
        return future.result()


def render_authenticated_page_to_pdf(request, url):
    results = render_authenticated_pages_to_pdf(request, [url])
    return results[0] if results else b''

    
def bulk_print_bagan(request, event_pk, day_pk, tatami_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    day = get_object_or_404(TimetableDay, pk=day_pk, event=event)
    tatami = get_object_or_404(Tatami, pk=tatami_pk, event=event)

    bagans = get_ordered_bagans_for_tatami(day, tatami)
    if not bagans:
        return HttpResponse('Tidak ada bagan terjadwal di tatami ini.', status=404)

    bagan_urls = [
        request.build_absolute_uri(
            reverse('admin-bagan-detail', kwargs={'event_pk': event.pk, 'bagan_pk': bagan.pk}) + '?print=1'
        )
        for bagan in bagans
    ]
    all_pdfs = render_authenticated_pages_to_pdf(request, bagan_urls)

    writer = PdfWriter()
    for pdf_bytes in all_pdfs:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        for page in reader.pages:
            writer.add_page(page)

    buffer = io.BytesIO()
    writer.write(buffer)
    buffer.seek(0)

    filename = f"Day{day.order + 1}_Tatami_{tatami.tatami_number}.pdf"
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


def timetable_call_sheet(request, event_pk, day_pk, tatami_pk):
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    day = get_object_or_404(TimetableDay, pk=day_pk, event=event)
    tatami = get_object_or_404(Tatami, pk=tatami_pk, event=event)

    cells = (
        TimetableCell.objects.filter(
            row__day=day,
            tatami=tatami,
        )
        .select_related('nomor_tanding', 'row')
        .order_by('row__order')
    )

    nt_ids = [c.nomor_tanding_id for c in cells if c.nomor_tanding_id]
    atlets_by_nt = defaultdict(list)
    if nt_ids:
        all_atlets = (
            Atlet.objects.filter(nomor_tanding_id__in=nt_ids)
            .select_related('perguruan', 'utusan')
            .order_by('nama_atlet')
        )
        for a in all_atlets:
            atlets_by_nt[a.nomor_tanding_id].append(a)

    categories = []
    total_matches = 0
    total_athletes = 0

    for c in cells:
        nt = c.nomor_tanding
        if nt:
            atlets = atlets_by_nt.get(nt.pk, [])
            match_count = max(1, len(atlets) - 1) if atlets else 0
            total_matches += match_count
            total_athletes += len(atlets)

            categories.append({
                'cell': c,
                'time_label': c.custom_text or c.row.time_label,
                'nomor_tanding': nt,
                'atlets': atlets,
                'atlet_count': len(atlets),
                'match_count': match_count,
                'is_session': False,
            })
        elif c.custom_text:
            fest_match = re.search(r'\((\d+)\)', c.custom_text)
            fest_count = int(fest_match.group(1)) if fest_match else 0
            total_athletes += fest_count
            categories.append({
                'cell': c,
                'time_label': c.custom_text or c.row.time_label,
                'nomor_tanding': None,
                'session_title': c.custom_text,
                'atlets': [],
                'atlet_count': fest_count,
                'match_count': 0,
                'is_session': True,
            })

    kop, _ = KopSurat.objects.get_or_create(event=event)
    context = {
        'event': event,
        'day': day,
        'tatami': tatami,
        'categories': categories,
        'kop_surat': kop,
        'day_label': format_day_label(day),
        'total_matches': total_matches,
        'total_athletes': total_athletes,
    }
    return render(request, 'admin/timetable_call_sheet.html', context)


def api_fetch_hosted_events(request):
    """
    API endpoint ringan untuk lazy loading daftar event publik ke dalam modal 'Hubungkan ke Event Web'.
    Mencegah halaman dashboard hang saat dimuat.
    """
    force = request.GET.get('force') == 'true'
    ok, events_or_err = fetch_hosted_events(force_refresh=force)
    if ok:
        return JsonResponse({'status': 'success', 'events': events_or_err})
    return JsonResponse({'status': 'error', 'message': str(events_or_err)}, status=502)

def sync_queue_status(request):
    """Mengembalikan informasi status antrean sinkronisasi live FIFO."""
    event_pk = request.GET.get('event_pk')
    from django.db.models import Q
    base_qs = SyncQueue.objects.all()
    if event_pk:
        event = Event.objects.filter(pk=event_pk).first()
        if event and not event.is_live_sync_enabled:
            return JsonResponse({
                'pending_count': 0,
                'failed_count': 0,
                'processing_count': 0,
                'total_unsynced': 0,
                'is_live_sync_enabled': False,
                'last_error': None,
                'last_failed_endpoint': None,
                'last_failed_retries': 0,
            })
        base_qs = base_qs.filter(Q(event_id=event_pk) | Q(event__isnull=True))
    else:
        # Hanya hitung antrean dari event yang mengaktifkan Live Sync (atau unassigned)
        base_qs = base_qs.filter(Q(event__isnull=True) | Q(event__is_live_sync_enabled=True))

    pending_count = base_qs.filter(status='pending').count()
    failed_count = base_qs.filter(status='failed').count()
    processing_count = base_qs.filter(status='processing').count()
    last_failed = base_qs.filter(status='failed').order_by('-updated_at').first()

    data = {
        'is_live_sync_enabled': True,
        'pending_count': pending_count,
        'failed_count': failed_count,
        'processing_count': processing_count,
        'total_unsynced': pending_count + failed_count + processing_count,
        'last_error': last_failed.last_error if last_failed else None,
        'last_failed_endpoint': last_failed.endpoint if last_failed else None,
        'last_failed_retries': last_failed.retry_count if last_failed else 0,
    }
    return JsonResponse(data)

@require_POST
def sync_queue_retry(request):
    """Memicu pengiriman ulang antrean tertunda secara manual."""
    from .utils import trigger_sync_queue
    trigger_sync_queue()
    return JsonResponse({'success': True, 'message': 'Proses pengiriman antrean dipicu.'})


@require_POST
def set_sync_target_view(request):
    """
    Mengubah target server sinkronisasi (Port 8001 / ambrilindo.com / Kustom)
    dan mengalihkan kembali ke halaman asal.
    """
    mode = request.POST.get('target_mode', 'local')
    custom_url = request.POST.get('custom_url', '').strip()
    redirect_url = request.POST.get('redirect_url') or request.META.get('HTTP_REFERER') or '/'
    
    success, msg = set_sync_config(mode, custom_url)
    if success:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect(redirect_url)


def sync_monitor_view(request, event_pk):
    """
    Halaman monitoring khusus antrean sinkronisasi live (send_to_hosted).
    Menampilkan visualisasi antrean FIFO, status server web, diagnostik error,
    kontrol status Live Sync (Aktif/Nonaktif), serta kontrol manual kirim ulang dan pembersihan antrean.
    """
    if not request.user.is_authenticated:
        return redirect('auth')
    event = get_object_or_404(Event, pk=event_pk)
    role = getattr(request.user, 'role', None)
    if not role:
        messages.error(request, "Akun Anda tidak memiliki peran yang valid.")
        return redirect('auth')

    if request.method == 'POST':
        submit_type = request.POST.get('submit_type')
        handlers = {
            'set_event_mapping': _handle_set_event_mapping,
            'pull_atlet': _handle_pull_atlet,
            'push_bagan': _handle_push_bagan,
            'force_sync_results': _handle_force_sync_results,
        }
        handler = handlers.get(submit_type)
        if handler:
            return handler(request, event)
        else:
            messages.warning(request, f"Aksi tidak dikenal: {submit_type}")
            return redirect('sync-monitor', event_pk=event.pk)

    status_filter = request.GET.get('status', '').strip().lower()

    # Filter antrean untuk event ini (atau item unassigned)
    from django.db.models import Q
    event_filter = Q(event=event) | Q(event__isnull=True)

    # Hitung statistik antrean
    total_count = SyncQueue.objects.filter(event_filter).count()
    failed_count = SyncQueue.objects.filter(event_filter, status='failed').count()
    pending_count = SyncQueue.objects.filter(event_filter, status__in=['pending', 'processing']).count()
    synced_count = SyncQueue.objects.filter(event_filter, status='synced').count()

    # Default tab: buka tab 'failed' jika ada error dan sync aktif, jika tidak buka 'all'
    if not status_filter:
        status_filter = 'failed' if (failed_count > 0 and event.is_live_sync_enabled) else 'all'

    # Filter query
    qs = SyncQueue.objects.filter(event_filter)
    if status_filter == 'failed':
        qs = qs.filter(status='failed').order_by('id')  # FIFO urutan tertua
    elif status_filter == 'pending':
        qs = qs.filter(status__in=['pending', 'processing']).order_by('id')
    elif status_filter == 'synced':
        qs = qs.filter(status='synced').order_by('-id')
    else:
        qs = qs.order_by('-id')

    queue_items = list(qs[:200])

    # Parsing payload menjadi data ramah pengguna
    for item in queue_items:
        p = item.payload if isinstance(item.payload, dict) else {}
        item.p_ring = p.get('ring_number') or p.get('tatami')
        item.p_round = p.get('round')
        item.p_urutan = p.get('urutan')
        item.p_winner = p.get('winner_atlet') or p.get('pemenang')
        score1 = p.get('score1')
        score2 = p.get('score2')
        if score1 is not None or score2 is not None:
            item.p_score = f"{score1 if score1 is not None else 0} - {score2 if score2 is not None else 0}"
        else:
            item.p_score = None
        item.p_kode_realtime = p.get('kode_realtime')
        item.p_bagan_id = p.get('bagan_id')
        item.p_detail_id = p.get('detail_bagan_id')
        item.p_json = json.dumps(p, indent=2, ensure_ascii=False) if p else "{}"

    event_mapping = get_event_mapping(event.pk)
    if event_mapping and event_mapping.get('hosted_event_name'):
        event_mapping['is_mismatch'] = (event.nama_event or '').strip().lower() != event_mapping.get('hosted_event_name', '').strip().lower()

    bagans = Bagan.objects.filter(event=event).order_by('nama_bagan')

    context = {
        'on': 'sync-monitor',
        'event': event,
        'role': role,
        'event_mapping': event_mapping,
        'bagans': bagans,
        'queue_items': queue_items,
        'status_filter': status_filter,
        'total_count': total_count,
        'failed_count': failed_count,
        'pending_count': pending_count,
        'synced_count': synced_count,
        'failed_sync_count': failed_count if event.is_live_sync_enabled else 0,
        'is_live_sync_enabled': event.is_live_sync_enabled,
    }
    return render(request, 'admin/sync-monitor.html', context)


@require_POST
def sync_queue_action_api(request, event_pk):
    """
    Endpoint AJAX untuk aksi-aksi manajemen antrean sinkronisasi:
    - toggle_live_sync: Mengaktifkan atau menonaktifkan Live Sync untuk event ini
    - retry_all: Memicu pemrosesan seluruh antrean tertunda
    - retry_item: Mengirim ulang satu item spesifik dan membuka antrean
    - mark_synced: Menandai item sebagai 'synced' untuk membuka gembok FIFO
    - delete_item: Menghapus item dari antrean
    - clear_synced: Membersihkan item yang sudah berhasil terkirim
    - ping_hosted: Mengetes konektivitas ke server target
    - get_status: Polling statistik untuk auto-refresh
    """
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'message': 'Unauthorized'}, status=401)

    event = get_object_or_404(Event, pk=event_pk)
    action = request.POST.get('action', '').strip()

    from .utils import send_to_hosted, trigger_sync_queue
    from .sync_service import get_hosted_base_url
    from django.db.models import Q
    import requests
    import time

    event_filter = Q(event=event) | Q(event__isnull=True)

    if action == 'toggle_live_sync':
        enable_val = request.POST.get('enable')
        if enable_val is not None:
            event.is_live_sync_enabled = str(enable_val).strip().lower() in ['true', '1', 'yes']
        else:
            event.is_live_sync_enabled = not event.is_live_sync_enabled
        event.save(update_fields=['is_live_sync_enabled'])
        if event.is_live_sync_enabled:
            trigger_sync_queue()
        status_label = 'Diaktifkan' if event.is_live_sync_enabled else 'Dinonaktifkan'
        return JsonResponse({
            'success': True,
            'is_live_sync_enabled': event.is_live_sync_enabled,
            'message': f"Sinkronisasi Live untuk event '{event.nama_event}' berhasil {status_label.lower()}."
        })

    elif action == 'retry_all':
        trigger_sync_queue()
        return JsonResponse({
            'success': True,
            'message': 'Pemrosesan antrean dipicu. Sistem sedang mencoba mengirim antrean berurutan.'
        })

    elif action == 'retry_item':
        queue_id = request.POST.get('queue_id')
        item = SyncQueue.objects.filter(pk=queue_id).first()
        if not item:
            return JsonResponse({'success': False, 'message': f'Item antrean #{queue_id} tidak ditemukan.'}, status=404)

        item.status = 'processing'
        item.save(update_fields=['status', 'updated_at'])
        success, result = send_to_hosted(item.payload, item.endpoint)
        if success:
            item.status = 'synced'
            item.last_error = None
            item.save(update_fields=['status', 'last_error', 'updated_at'])
            # Buka kembali FIFO queue agar item berikutnya langsung dikirim
            trigger_sync_queue()
            return JsonResponse({
                'success': True,
                'message': f'Item #{item.pk} berhasil dikirim ke server web!',
                'status': 'synced'
            })
        else:
            item.status = 'failed'
            item.retry_count += 1
            item.last_error = str(result)
            item.save(update_fields=['status', 'retry_count', 'last_error', 'updated_at'])
            return JsonResponse({
                'success': False,
                'message': f'Gagal mengirim #{item.pk}: {result}',
                'last_error': str(result),
                'retry_count': item.retry_count,
                'status': 'failed'
            })

    elif action == 'mark_synced':
        queue_id = request.POST.get('queue_id')
        item = SyncQueue.objects.filter(pk=queue_id).first()
        if not item:
            return JsonResponse({'success': False, 'message': f'Item antrean #{queue_id} tidak ditemukan.'}, status=404)

        item.status = 'synced'
        item.last_error = 'Ditandai terkirim secara manual oleh operator'
        item.save(update_fields=['status', 'last_error', 'updated_at'])
        # Buka blokir antrean FIFO
        trigger_sync_queue()
        return JsonResponse({
            'success': True,
            'message': f'Item #{item.pk} ditandai sebagai terkirim. Antrean dibuka.'
        })

    elif action == 'delete_item':
        queue_id = request.POST.get('queue_id')
        item = SyncQueue.objects.filter(pk=queue_id).first()
        if not item:
            return JsonResponse({'success': False, 'message': f'Item antrean #{queue_id} tidak ditemukan.'}, status=404)
        pk = item.pk
        item.delete()
        trigger_sync_queue()
        return JsonResponse({
            'success': True,
            'message': f'Item #{pk} berhasil dihapus dari antrean.'
        })

    elif action == 'clear_synced':
        deleted_count, _ = SyncQueue.objects.filter(event_filter, status='synced').delete()
        return JsonResponse({
            'success': True,
            'message': f'{deleted_count} riwayat antrean terkirim berhasil dibersihkan.'
        })

    elif action == 'clear_all':
        deleted_count, _ = SyncQueue.objects.filter(event_filter).delete()
        return JsonResponse({
            'success': True,
            'message': f'Seluruh antrean sinkronisasi ({deleted_count} item) berhasil dikosongkan.'
        })

    elif action == 'ping_hosted':
        base_url = get_hosted_base_url()
        t0 = time.time()
        try:
            r = requests.get(
                f"{base_url}/api/sync/events/",
                headers={'Authorization': f'Bearer {settings.HOSTED_API_TOKEN}'},
                timeout=5
            )
            latency_ms = int((time.time() - t0) * 1000)
            if r.status_code == 200:
                return JsonResponse({
                    'success': True,
                    'latency_ms': latency_ms,
                    'url': base_url,
                    'status_code': 200,
                    'message': f'Server Online ({latency_ms} ms)'
                })
            else:
                return JsonResponse({
                    'success': False,
                    'status_code': r.status_code,
                    'latency_ms': latency_ms,
                    'url': base_url,
                    'error': f'Server merespons HTTP {r.status_code}'
                })
        except requests.exceptions.Timeout:
            latency_ms = int((time.time() - t0) * 1000)
            return JsonResponse({
                'success': False,
                'latency_ms': latency_ms,
                'url': base_url,
                'error': 'Koneksi timeout (5 detik). Periksa sambungan internet.'
            })
        except Exception as e:
            latency_ms = int((time.time() - t0) * 1000)
            return JsonResponse({
                'success': False,
                'latency_ms': latency_ms,
                'url': base_url,
                'error': f'Gagal terhubung: {str(e)}'
            })

    elif action == 'get_status':
        total_count = SyncQueue.objects.filter(event_filter).count()
        failed_count = SyncQueue.objects.filter(event_filter, status='failed').count()
        pending_count = SyncQueue.objects.filter(event_filter, status__in=['pending', 'processing']).count()
        synced_count = SyncQueue.objects.filter(event_filter, status='synced').count()
        return JsonResponse({
            'success': True,
            'is_live_sync_enabled': event.is_live_sync_enabled,
            'total_count': total_count,
            'failed_count': failed_count,
            'pending_count': pending_count,
            'synced_count': synced_count,
        })

    return JsonResponse({'success': False, 'message': f'Aksi "{action}" tidak dikenali.'}, status=400)
