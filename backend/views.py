from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import *
import openpyxl
from django.db.models import Count, Q
import random
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from collections import defaultdict

def auth(request):
    events = Event.objects.all().order_by('-pk')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        event_pk = request.POST.get('event_pk')

        user = authenticate(request, username=username, password=password)
        if user is not None:
            try:
                event = Event.objects.get(pk=event_pk)
                admin_tatami = AdminTatami.objects.filter(user=user, event=event).first()
                admin = Admin.objects.filter(user=user).first()
                if admin_tatami:
                    login(request, user)
                    return redirect('admin-dashboard', event_pk=event_pk)
                elif admin:
                    login(request, user)
                    return redirect('admin-dashboard', event_pk=event_pk)
                else:
                    jury = Jury.objects.filter(event=event, user=user).first()
                    if jury:
                        login(request, user)
                        return redirect('jury-panel', tatami_pk=jury.tatami.pk)
                    else:
                        messages.error(request, "Anda tidak terdaftar sebagai Admin atau Juri untuk event ini.")
                        return redirect('auth')

            except Event.DoesNotExist:
                messages.error(request, "Event tidak ditemukan.")
                return redirect('auth')
        else:
            messages.error(request, "Username atau password salah!")
            return redirect('auth')
        
    context = {
        'events': events
    }
        
    return render(request, 'auth/auth.html', context)

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
def message_retriever_admin(request, detailbagan_pk):
    if request.method == 'POST':
        action = request.POST.get('action')
        details = request.POST.get('details')

        group_name = f"control_{detailbagan_pk}"
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

def logoutfunc(request):
    logout(request)
    return redirect('auth')

def admin_dashboard(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    nomor_tandings = NomorTanding.objects.filter(event=event)
    
    bagans = Bagan.objects.filter(event=event).order_by('-pk')
    
    # count = 0
    # for bagan in bagans:
    #     dbs = DetailBagan.objects.filter(bagan=bagan)
    #     for db in dbs:
    #         if db.atlet1:
    #             count += 1
    #         if db.atlet2:
    #             count += 1
    # print(count)

    custom_order = [1, 8, 4, 5, 2, 7, 3, 6]

    atlet_assignment1 = {
                        1: 'atlet1',
                        8: 'atlet2',
                        4: 'atlet2',
                        5: 'atlet1',
                        2: 'atlet2',
                        7: 'atlet1',
                        3: 'atlet1',
                        6: 'atlet2',
                    }

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'drawing_bagan':
            nomor_tanding_pks = request.POST.getlist('nomor_tanding_pk')
            tipe_shuffle = request.POST.get('shuffle_type')
            if 'semua' in nomor_tanding_pks:
                nomor_tanding_pks = NomorTanding.objects.filter(event=event).values_list('pk', flat=True)
            
            if tipe_shuffle in ['perguruan', 'kontingen']:
                for nomor_tanding_pk in nomor_tanding_pks:
                    nomor_tanding = NomorTanding.objects.filter(pk=nomor_tanding_pk).first()

                    if tipe_shuffle == 'perguruan':
                        group_model = Perguruan
                        group_field = 'perguruan'
                    elif tipe_shuffle == 'kontingen':
                        group_model = Utusan  # Make sure you have imported this model
                        group_field = 'utusan'

                    group_counts = list(
                        group_model.objects.annotate(
                            num_atlet=Count('atlet', filter=Q(**{f'atlet__nomor_tanding': nomor_tanding}))
                        )
                        .filter(num_atlet__gt=0)
                        .order_by('-num_atlet')
                        .values_list('id', 'num_atlet')
                    )

                    atlets_temp_all = list(Atlet.objects.filter(nomor_tanding=nomor_tanding))
                    group_counts_temp = group_counts

                    def split_count_balanced(total, parts, start_index=0):
                        base = total // parts
                        remainder = total % parts
                        splits = [base] * parts
                        idx = start_index
                        for _ in range(remainder):
                            splits[idx] += 1
                            idx = (idx + 1) % parts
                        return splits

                    group_counts_pool_a = []
                    group_counts_pool_b = []
                    group_counts_pool_c = []

                    if 0 < len(atlets_temp_all) < 17:
                        perulangan = 1
                    elif 16 < len(atlets_temp_all) < 33:
                        perulangan = 2
                    elif 32 < len(atlets_temp_all) < 49:
                        perulangan = 3

                    pools = [[] for _ in range(perulangan)]

                    for idx, (group_id, count) in enumerate(group_counts):
                        splits = split_count_balanced(count, perulangan, start_index=idx % perulangan)
                        for pool_idx, val in enumerate(splits):
                            pools[pool_idx].append((group_id, val))

                    if perulangan >= 1:
                        group_counts_pool_a = pools[0]
                    if perulangan >= 2:
                        group_counts_pool_b = pools[1]
                    if perulangan >= 3:
                        group_counts_pool_c = pools[2]

                    def assign_atlets_to_pool(atlets, group_counts_pool, field_name):
                        result = []
                        remaining_counts = {gid: count for gid, count in group_counts_pool}
                        for gid in remaining_counts:
                            for atlet in atlets[:]:
                                if getattr(atlet, field_name + '_id') == gid and remaining_counts[gid] > 0:
                                    result.append(atlet)
                                    atlets.remove(atlet)
                                    remaining_counts[gid] -= 1
                        return result

                    atlets_temp_main = atlets_temp_all.copy()
                    atlets_temp_pool_a = assign_atlets_to_pool(atlets_temp_main, group_counts_pool_a, group_field)
                    atlets_temp_pool_b = assign_atlets_to_pool(atlets_temp_main, group_counts_pool_b, group_field)
                    atlets_temp_pool_c = assign_atlets_to_pool(atlets_temp_main, group_counts_pool_c, group_field)

                    for i in range(1, perulangan + 1):
                        if perulangan > 1:
                            if i == 1:
                                nama_bagan = f'{nomor_tanding.nama_nomor_tanding} - Pool A'
                                group_counts = list(group_counts_pool_a)
                                atlets_temp = atlets_temp_pool_a
                            elif i == 2:
                                nama_bagan = f'{nomor_tanding.nama_nomor_tanding} - Pool B'
                                group_counts = list(group_counts_pool_b)
                                atlets_temp = atlets_temp_pool_b
                            elif i == 3:
                                nama_bagan = f'{nomor_tanding.nama_nomor_tanding} - Pool C'
                                group_counts = list(group_counts_pool_c)
                                atlets_temp = atlets_temp_pool_c
                            bagan = Bagan.objects.create(
                                event=event,
                                nomor_tanding=nomor_tanding,
                                nama_bagan=nama_bagan,
                            )
                        else:
                            bagan = Bagan.objects.create(
                                event=event,
                                nama_bagan=nomor_tanding.nama_nomor_tanding,
                                nomor_tanding=nomor_tanding
                            )
                            group_counts = group_counts_temp
                            atlets_temp = atlets_temp_all

                        if 'KATA' in nomor_tanding.nama_nomor_tanding:
                            bagan.tipe_tanding = '1'
                        elif 'KUMITE' in nomor_tanding.nama_nomor_tanding:
                            bagan.tipe_tanding = '2'
                        bagan.save()

                        group_index = 0

                        for urutan in custom_order:
                            detail_bagan = DetailBagan.objects.create(bagan=bagan, round=1, urutan=urutan)

                            if atlets_temp and group_index < len(group_counts):
                                assigned = False
                                while group_index < len(group_counts) and not assigned:
                                    group_id, remaining = group_counts[group_index]
                                    eligible_atlets = [a for a in atlets_temp if getattr(a, group_field + '_id') == group_id]

                                    if eligible_atlets:
                                        atlet = random.choice(eligible_atlets)
                                        target_field = atlet_assignment1.get(urutan)

                                        if target_field == 'atlet1':
                                            detail_bagan.atlet1 = atlet
                                        elif target_field == 'atlet2':
                                            detail_bagan.atlet2 = atlet

                                        detail_bagan.save()

                                        atlets_temp.remove(atlet)
                                        group_counts[group_index] = (group_id, remaining - 1)
                                        if group_counts[group_index][1] <= 0:
                                            group_index += 1

                                        assigned = True
                                    else:
                                        group_index += 1
                            else:
                                detail_bagan.save()

                        group_index = 0

                        for urutan in custom_order:
                            detail_bagan = DetailBagan.objects.get(bagan=bagan, round=1, urutan=urutan)

                            if not atlets_temp:
                                break

                            target_field = atlet_assignment1.get(urutan)

                            if target_field == 'atlet1' and detail_bagan.atlet2 is None:
                                eligible_field = 'atlet2'
                            elif target_field == 'atlet2' and detail_bagan.atlet1 is None:
                                eligible_field = 'atlet1'
                            else:
                                continue

                            assigned = False
                            while group_index < len(group_counts) and not assigned:
                                group_id, remaining = group_counts[group_index]
                                eligible_atlets = [a for a in atlets_temp if getattr(a, group_field + '_id') == group_id]

                                if eligible_atlets:
                                    atlet = random.choice(eligible_atlets)

                                    if eligible_field == 'atlet1':
                                        detail_bagan.atlet1 = atlet
                                    else:
                                        detail_bagan.atlet2 = atlet

                                    detail_bagan.save()
                                    atlets_temp.remove(atlet)

                                    group_counts[group_index] = (group_id, remaining - 1)
                                    if group_counts[group_index][1] <= 0:
                                        group_index += 1

                                    assigned = True
                                else:
                                    group_index += 1

                        
                        urutan_map = {
                            1: (1, 'atlet1'),
                            2: (1, 'atlet2'),
                            3: (2, 'atlet1'),
                            4: (2, 'atlet2'),
                            5: (3, 'atlet1'),
                            6: (3, 'atlet2'),
                            7: (4, 'atlet1'),
                            8: (4, 'atlet2'),
                        }

                        detail_bagans_round_1 = DetailBagan.objects.filter(bagan=bagan, round=1).order_by('urutan')

                        for detail_bagan in detail_bagans_round_1:
                            target = urutan_map.get(detail_bagan.urutan)
                            if not target:
                                continue

                            target_urutan, target_field = target

                            new_detail_bagan, _ = DetailBagan.objects.get_or_create(
                                bagan=bagan,
                                round=2,
                                urutan=target_urutan
                            )

                            atlet = None
                            if not detail_bagan.atlet1:
                                atlet = detail_bagan.atlet2
                                detail_bagan.atlet2 = None
                            elif not detail_bagan.atlet2:
                                atlet = detail_bagan.atlet1
                                detail_bagan.atlet1 = None

                            if atlet:
                                setattr(new_detail_bagan, target_field, atlet)

                            detail_bagan.save()
                            new_detail_bagan.save()

                        match_map = {
                            1: {'round1_urutans': (2, 1), 'round3_urutan': 1, 'slot': 'atlet1'},
                            2: {'round1_urutans': (4, 3), 'round3_urutan': 1, 'slot': 'atlet2'},
                            3: {'round1_urutans': (6, 5), 'round3_urutan': 2, 'slot': 'atlet1'},
                            4: {'round1_urutans': (8, 7), 'round3_urutan': 2, 'slot': 'atlet2'},
                        }

                        detail_bagans_round_2 = DetailBagan.objects.filter(bagan=bagan, round=2).order_by('urutan')

                        for detail_bagan in detail_bagans_round_2:
                            config = match_map.get(detail_bagan.urutan)
                            if not config:
                                continue

                            round1_a, round1_b = config['round1_urutans']
                            target_slot = config['slot']
                            new_detail_bagan, _ = DetailBagan.objects.get_or_create(
                                bagan=bagan, round=3, urutan=config['round3_urutan']
                            )

                            if not detail_bagan.atlet2:
                                target_detail = DetailBagan.objects.filter(bagan=bagan, round=1, urutan=round1_a).first()
                                if target_detail and (not target_detail.atlet1 or not target_detail.atlet2):
                                    setattr(new_detail_bagan, target_slot, detail_bagan.atlet1)
                                    detail_bagan.atlet1 = None
                            elif not detail_bagan.atlet1:
                                target_detail = DetailBagan.objects.filter(bagan=bagan, round=1, urutan=round1_b).first()
                                if target_detail and (not target_detail.atlet1 or not target_detail.atlet2):
                                    setattr(new_detail_bagan, target_slot, detail_bagan.atlet2)
                                    detail_bagan.atlet2 = None

                            detail_bagan.save()
                            new_detail_bagan.save()
                        
                        detail_bagans_round_3 = DetailBagan.objects.filter(bagan=bagan, round=3).order_by('urutan')

                        for detail_bagan in detail_bagans_round_3:
                            if detail_bagan.urutan == 1:
                                new_detail_bagan = DetailBagan.objects.filter(bagan=bagan, round=4, urutan=1).first()
                                if not new_detail_bagan:
                                    new_detail_bagan = DetailBagan.objects.create(bagan=bagan, round=4, urutan=1)

                                if not detail_bagan.atlet2:
                                    if not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=2).first().atlet1 or not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=2).first().atlet2:
                                        new_detail_bagan.atlet1 = detail_bagan.atlet1
                                        detail_bagan.atlet1 = None
                                elif not detail_bagan.atlet1:
                                    if not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=1).first().atlet1 or not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=1).first().atlet2:
                                        new_detail_bagan.atlet1 = detail_bagan.atlet2
                                        detail_bagan.atlet2 = None
                                
                                detail_bagan.save()
                                new_detail_bagan.save()

                            elif detail_bagan.urutan == 2:
                                new_detail_bagan = DetailBagan.objects.filter(bagan=bagan, round=4, urutan=1).first()
                                if not new_detail_bagan:
                                    new_detail_bagan = DetailBagan.objects.create(bagan=bagan, round=4, urutan=1)

                                if not detail_bagan.atlet2:
                                    if not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=4).first().atlet1 or not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=4).first().atlet2:
                                        new_detail_bagan.atlet2 = detail_bagan.atlet1
                                        detail_bagan.atlet1 = None
                                elif not detail_bagan.atlet1:
                                    if not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=3).first().atlet1 or not DetailBagan.objects.filter(bagan=bagan, round=2, urutan=3).first().atlet2:
                                        new_detail_bagan.atlet2 = detail_bagan.atlet2
                                        detail_bagan.atlet2 = None
                                
                                detail_bagan.save()
                                new_detail_bagan.save()
                            
                        detail_bagan_round_5 = DetailBagan.objects.create(bagan=bagan, round=5, urutan=1)

            return redirect('admin-dashboard', event_pk=event_pk)
        
        elif request.POST.get('submit_type') == 'tambah_bagan':
            nomor_tanding_pk = request.POST.get('nomor_tanding_pk')
            tipe = request.POST.get('tipe')
            if tipe == 'normal':
                return redirect('tambah-bagan', event_pk=event_pk, nomor_tanding_pk=nomor_tanding_pk)
            elif tipe == 'referchange':
                return redirect('tambah-bagan-referchange', event_pk=event_pk, nomor_tanding_pk=nomor_tanding_pk)
            elif tipe == 'round_robin':
                return redirect('tambah-bagan-round-robin', event_pk=event_pk, nomor_tanding_pk=nomor_tanding_pk)

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'nomor_tandings': nomor_tandings,
        'bagans': bagans,
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

def admin_bagan_detail(request, event_pk, bagan_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = Bagan.objects.get(pk=bagan_pk)
    if bagan.round_robin:
        return redirect('admin-bagan-detail-round-robin', event_pk=event_pk, bagan_pk=bagan_pk)
    all_atlets = Atlet.objects.filter(nomor_tanding=bagan.nomor_tanding)
    detail_bagans_round_1 = DetailBagan.objects.filter(bagan=bagan, round=1).order_by('urutan')
    detail_bagans_round_2 = DetailBagan.objects.filter(bagan=bagan, round=2).order_by('urutan')
    detail_bagans_round_3 = DetailBagan.objects.filter(bagan=bagan, round=3).order_by('urutan')
    detail_bagans_round_4 = DetailBagan.objects.filter(bagan=bagan, round=4).order_by('urutan')
    
    detail_bagan_round_5 = DetailBagan.objects.filter(bagan=bagan, round=5).first()

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
            print(juara_1_pk, juara_2_pk, juara_3a_pk, juara_3b_pk)

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

            bagan.save()

        return redirect('admin-bagan-detail', event_pk=event_pk, bagan_pk=bagan_pk)

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

            new_bagan = Bagan.objects.create(event=event, nomor_tanding=nomor_tanding, tipe_tanding=tipe_tanding, nama_bagan=nama_bagan)

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

            new_bagan = Bagan.objects.create(event=event, nomor_tanding=nomor_tanding, tipe_tanding=tipe_tanding, nama_bagan=nama_bagan)

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

    new_bagan = Bagan.objects.create(event=event, nama_bagan=f'ROUND ROBIN {nomor_tanding.nama_nomor_tanding}', nomor_tanding=nomor_tanding, tipe_tanding=tipe_tanding, round_robin=True)
    
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
        if request.POST.get('submit_type') == 'simpan_juara':
            pass

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
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = Bagan.objects.get(pk=bagan_pk)
    bagan.delete()

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

def control_panel(request, event_pk, bagan_pk, detailbagan_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = Bagan.objects.get(pk=bagan_pk)
    detail_bagan = DetailBagan.objects.get(pk=detailbagan_pk)
    aka_score_obj = Score.objects.filter(detail_bagan=detail_bagan, atlet=0).first()
    ao_score_obj = Score.objects.filter(detail_bagan=detail_bagan, atlet=1).first()
    if not aka_score_obj:
        aka_score_obj = Score.objects.create(detail_bagan=detail_bagan, atlet=0)
    if not ao_score_obj:
        ao_score_obj = Score.objects.create(detail_bagan=detail_bagan, atlet=1)
    tatami = admin_tatami.tatami
    tatami.detail_bagan = detail_bagan
    tatami.save()

    if request.method == 'POST':
        pemenang = request.POST.get('pemenang')
        if request.POST.get('submit_type') == 'kata-simpan':
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
        
        elif request.POST.get('submit_type') == 'kumite-simpan':
            aka_score = request.POST.get('akaScore')
            ao_score = request.POST.get('aoScore')

            detail_bagan.score1 = aka_score
            detail_bagan.score2 = ao_score
        
        if pemenang == 'aka':
            detail_bagan.pemenang = '1'
        elif pemenang == 'ao':
            detail_bagan.pemenang = '2'
        else:
            detail_bagan.pemenang = '3'

        detail_bagan.selesai = True
        detail_bagan.save()
        
        if not bagan.round_robin:
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
                    if detail_bagan.urutan % 2 == 1:
                        detailbagan_next_round.atlet1 = winner_atlet
                    else: 
                        detailbagan_next_round.atlet2 = winner_atlet

                detail_bagan.save()
                detailbagan_next_round.save()

        return redirect('admin-bagan-detail', event_pk=event_pk, bagan_pk=bagan_pk)

    detail_data = {
        "atlet_red": detail_bagan.atlet1.nama_atlet if detail_bagan.atlet1 else None,
        "atlet_red_perguruan": detail_bagan.atlet1.perguruan.nama_perguruan if detail_bagan.atlet1 else None,
        "atlet_red_utusan": detail_bagan.atlet1.utusan.nama_utusan if detail_bagan.atlet1 else None,
        "atlet_red_kata": detail_bagan.kata1 if detail_bagan.kata1 else None,
        "atlet_blue": detail_bagan.atlet2.nama_atlet if detail_bagan.atlet2 else None,
        "atlet_blue_perguruan": detail_bagan.atlet2.perguruan.nama_perguruan if detail_bagan.atlet2 else None,
        "atlet_blue_utusan": detail_bagan.atlet2.utusan.nama_utusan if detail_bagan.atlet2 else None,
        "atlet_blue_kata": detail_bagan.kata2 if detail_bagan.kata2 else None,
        "tipe_tanding": bagan.tipe_tanding,
        "nomor_tanding": bagan.nomor_tanding.nama_nomor_tanding,
    }

    group_name = f"scoring_{admin_tatami.tatami.pk}"
    channel_layer = get_channel_layer()

    async_to_sync(channel_layer.group_send)(
        group_name,
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
    }

    return render(request, 'admin/control-panel.html', context)

@csrf_exempt
def message_retriever(request, tatami_pk):
    if request.method == 'POST':
        action = request.POST.get('action')
        details = request.POST.get('details')
        tatami = Tatami.objects.get(pk=tatami_pk)

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
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    perguruans = Perguruan.objects.filter(event=event)
    utusans = Utusan.objects.filter(event=event)
    nomor_tandings = NomorTanding.objects.filter(event=event)
    atlets = Atlet.objects.filter(event=event).order_by('-pk')

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'import_atlet':
            excel_file = request.FILES.get('excel_atlet')

            if not excel_file:
                messages.error(request, "Silakan pilih file Excel.")
                return redirect('admin-atlet', event_pk=event_pk)
            
            try:
                workbook = openpyxl.load_workbook(excel_file)
                sheet = workbook.active

                for row in sheet.iter_rows(min_row=2, values_only=True):
                    nama, perguruan, utusan, nomor_tanding = row

                    perguruan_name = perguruan.strip().upper()
                    perguruan_obj, _ = Perguruan.objects.get_or_create(event=event, nama_perguruan=perguruan_name)

                    utusan_name = utusan.strip().upper()
                    utusan_obj, _ = Utusan.objects.get_or_create(event=event, nama_utusan=utusan_name)

                    nomor_tanding_name = nomor_tanding.strip().upper()
                    nomor_tanding_obj, _ = NomorTanding.objects.get_or_create(event=event, nama_nomor_tanding=nomor_tanding_name)

                    Atlet.objects.create(
                        event=event,
                        nama_atlet=nama,
                        perguruan=perguruan_obj,
                        utusan=utusan_obj,
                        nomor_tanding=nomor_tanding_obj
                    )

                messages.success(request, "Data atlet berhasil diimport.")
            except Exception as e:
                messages.error(request, f"Gagal mengimport file: {str(e)}")
        
        elif request.POST.get('submit_type') == 'tambah_atlet':
            nama_atlet = request.POST.get('nama_atlet')
            perguruan_pk = request.POST.get('perguruan')
            perguruan = Perguruan.objects.get(pk=perguruan_pk)
            utusan_pk = request.POST.get('utusan')
            utusan = Utusan.objects.get(pk=utusan_pk)
            nomor_tanding_pk = request.POST.get('nomor_tanding')
            nomor_tanding = NomorTanding.objects.get(pk=nomor_tanding_pk)

            Atlet.objects.create(event=event, nama_atlet=nama_atlet, perguruan=perguruan, utusan=utusan, nomor_tanding=nomor_tanding)

            messages.success(request, "Berhasil menambahkan atlet.")
            
        return redirect('admin-atlet', event_pk=event_pk)

    context = {
        'on': 'atlet',
        'event': event,
        'admin_tatami': admin_tatami,
        'atlets': atlets,
        'perguruans': perguruans,
        'utusans': utusans,
        'nomor_tandings': nomor_tandings,
    }

    return render(request, 'admin/atlet.html', context)

def admin_nomor_tanding(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    nomor_tandings = NomorTanding.objects.filter(event=event).order_by('-pk')

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'tambah_nomor_tanding':
            nama_nomor_tanding = request.POST.get('nomor_tanding').strip().upper()
            new_nomor_tanding = NomorTanding.objects.create(event=event, nama_nomor_tanding=nama_nomor_tanding)

        return redirect('admin-nomor-tanding', event_pk=event_pk)
    
    context = {
        'on': 'nomor-tanding',
        'event': event,
        'nomor_tandings': nomor_tandings,
    }
    return render(request, 'admin/nomor-tanding.html', context)

def admin_utusan(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    utusans = Utusan.objects.filter(event=event)
    
    utusan_medals = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0})

    bagans = Bagan.objects.filter(event=event)

    for bagan in bagans:
        if bagan.juara_1 and bagan.juara_1.utusan:
            utusan_medals[bagan.juara_1.utusan.pk]["gold"] += 1
        if bagan.juara_2 and bagan.juara_2.utusan:
            utusan_medals[bagan.juara_2.utusan.pk]["silver"] += 1
        if bagan.juara_3a and bagan.juara_3a.utusan:
            utusan_medals[bagan.juara_3a.utusan.pk]["bronze"] += 1
        if bagan.juara_3b and bagan.juara_3b.utusan:
            utusan_medals[bagan.juara_3b.utusan.pk]["bronze"] += 1
    
    utusans = list(utusans)
    utusans.sort(key=lambda u: (
        -utusan_medals[u.pk]["gold"],
        -utusan_medals[u.pk]["silver"],
        -utusan_medals[u.pk]["bronze"],
    ))

    context = {
        'on': 'utusan',
        'event': event,
        'utusans': utusans,
        'utusan_medals': utusan_medals,
    }
    return render(request, 'admin/utusan.html', context)

def admin_perguruan(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    perguruans = Perguruan.objects.filter(event=event)
    
    perguruan_medals = defaultdict(lambda: {"gold": 0, "silver": 0, "bronze": 0})

    bagans = Bagan.objects.filter(event=event)

    for bagan in bagans:
        if bagan.juara_1 and bagan.juara_1.perguruan:
            perguruan_medals[bagan.juara_1.perguruan.pk]["gold"] += 1
        if bagan.juara_2 and bagan.juara_2.perguruan:
            perguruan_medals[bagan.juara_2.perguruan.pk]["silver"] += 1
        if bagan.juara_3a and bagan.juara_3a.perguruan:
            perguruan_medals[bagan.juara_3a.perguruan.pk]["bronze"] += 1
        if bagan.juara_3b and bagan.juara_3b.perguruan:
            perguruan_medals[bagan.juara_3b.perguruan.pk]["bronze"] += 1
    
    perguruans = list(perguruans)
    perguruans.sort(key=lambda u: (
        -perguruan_medals[u.pk]["gold"],
        -perguruan_medals[u.pk]["silver"],
        -perguruan_medals[u.pk]["bronze"],
    ))

    context = {
        'on': 'perguruan',
        'event': event,
        'perguruans': perguruans,
        'perguruan_medals': perguruan_medals,
    }
    return render(request, 'admin/perguruan.html', context)

def admin_rekapan(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    bagans = Bagan.objects.filter(event=event)
    bagans = Bagan.objects.filter(event=event)
    context = {
        'on': 'rekapan',
        'event': event,
        'bagans': bagans,
    }
    return render(request, 'admin/rekapan.html', context)

def admin_tatami(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    tatamis = Tatami.objects.filter(event=event)

    if request.method == 'POST':
        if request.POST.get('submit_type') == 'tambah_tatami':
            last_tatami = tatamis.order_by('-tatami_number').first()
            next_number = (last_tatami.tatami_number + 1) if last_tatami else 1

            new_tatami = Tatami.objects.create(event=event, tatami_number=next_number)

            user = User.objects.create_user(username=f'admtatami{next_number}e{event_pk}', password=f'admtatami{next_number}e{event_pk}')
            new_admtatami = AdminTatami.objects.create(event=event, tatami=new_tatami, user=user)

            for i in range(1, 8):
                user = User.objects.create_user(username=f'j{i}t{next_number}e{event_pk}', password=f'j{i}t{next_number}e{event_pk}')
                new_jury = Jury.objects.create(event=event, tatami=new_tatami, user=user, jury_number=i)

            messages.success(request, f"Sukses menambahkan tatami {new_tatami}!")
            return redirect('admin-tatami', event_pk=event_pk)
        elif request.POST.get('submit_type') == 'hapus_tatami':
            tatami = Tatami.objects.filter(pk=request.POST.get('tatami_pk')).first()
            juries = Jury.objects.filter(tatami=tatami)
            adm_tatami = AdminTatami.objects.filter(tatami=tatami).first()
            adm_tatami.user.delete()
            for jury in juries:
                jury.user.delete()
            tatami.delete()
            messages.success(request, f"Sukses menghapus tatami {tatami}!")
            return redirect('admin-tatami', event_pk=event_pk)

    context = {
        'on': 'tatami',
        'event': event,
        'admin_tatami': admin_tatami,
        'tatamis': tatamis,
    }

    return render(request, 'admin/tatami.html', context)

def scoring_board(request, tatami_pk):
    tatami = Tatami.objects.get(pk=tatami_pk)
    
    context = {
        'tatami': tatami,
    }
    return render(request, 'admin/scoring-board.html', context)