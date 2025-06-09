from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib import messages
from .models import *
import openpyxl
from django.db.models import Count, Q
import random

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
                        return redirect('jury-panel', event_pk=event_pk)
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

def logoutfunc(request):
    logout(request)
    return redirect('auth')

def admin_dashboard(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    nomor_tandings = NomorTanding.objects.filter(event=event)
    bagans = Bagan.objects.filter(event=event)

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
                
            for nomor_tanding_pk in nomor_tanding_pks:
                nomor_tanding = NomorTanding.objects.filter(pk=nomor_tanding_pk).first()
                perguruan_counts = list(
                    Perguruan.objects.annotate(
                        num_atlet=Count('atlet', filter=Q(atlet__nomor_tanding=nomor_tanding))
                    )
                    .filter(num_atlet__gt=0)
                    .order_by('-num_atlet')
                    .values_list('id', 'num_atlet')
                )

                atlets_temp = list(Atlet.objects.filter(nomor_tanding=nomor_tanding))

                if 0 < len(atlets_temp) < 17:
                    bagan = Bagan.objects.create(
                        event=event,
                        nama_bagan=nomor_tanding.nama_nomor_tanding,
                        nomor_tanding=nomor_tanding
                    )

                    perguruan_index = 0

                    for i in custom_order:
                        detail_bagan = DetailBagan.objects.create(bagan=bagan, round=1, urutan=i)

                        if atlets_temp and perguruan_index < len(perguruan_counts):
                            assigned = False
                            while perguruan_index < len(perguruan_counts) and not assigned:
                                perguruan_id, remaining = perguruan_counts[perguruan_index]
                                eligible_atlets = [a for a in atlets_temp if a.perguruan_id == perguruan_id]

                                if eligible_atlets:
                                    atlet = random.choice(eligible_atlets)
                                    target_field = atlet_assignment1.get(i)

                                    if target_field == 'atlet1':
                                        detail_bagan.atlet1 = atlet
                                    elif target_field == 'atlet2':
                                        detail_bagan.atlet2 = atlet

                                    detail_bagan.save()

                                    atlets_temp.remove(atlet)
                                    perguruan_counts[perguruan_index] = (perguruan_id, remaining - 1)
                                    if perguruan_counts[perguruan_index][1] <= 0:
                                        perguruan_index += 1

                                    assigned = True
                                else:
                                    perguruan_index += 1
                        else:
                            detail_bagan.save()

                    perguruan_index = 0
                    
                    for i in custom_order:
                        detail_bagan = DetailBagan.objects.get(bagan=bagan, round=1, urutan=i)

                        if not atlets_temp:
                            break 

                        target_field = atlet_assignment1.get(i)

                        if target_field == 'atlet1' and detail_bagan.atlet2 is None:
                            eligible_field = 'atlet2'
                        elif target_field == 'atlet2' and detail_bagan.atlet1 is None:
                            eligible_field = 'atlet1'
                        else:
                            continue

                        assigned = False
                        while perguruan_index < len(perguruan_counts) and not assigned:
                            perguruan_id, remaining = perguruan_counts[perguruan_index]
                            eligible_atlets = [a for a in atlets_temp if a.perguruan_id == perguruan_id]

                            if eligible_atlets:
                                atlet = random.choice(eligible_atlets)

                                if eligible_field == 'atlet1':
                                    detail_bagan.atlet1 = atlet
                                else:
                                    detail_bagan.atlet2 = atlet

                                detail_bagan.save()
                                atlets_temp.remove(atlet)

                                perguruan_counts[perguruan_index] = (perguruan_id, remaining - 1)
                                if perguruan_counts[perguruan_index][1] <= 0:
                                    perguruan_index += 1

                                assigned = True
                            else:
                                perguruan_index += 1
                        
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


            return redirect('admin-dashboard', event_pk=event_pk)

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'nomor_tandings': nomor_tandings,
        'bagans': bagans,
    }

    return render(request, 'admin/dashboard.html', context)

def admin_bagan_detail(request, event_pk, bagan_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
    bagan = Bagan.objects.get(pk=bagan_pk)
    detail_bagans_round_1 = DetailBagan.objects.filter(bagan=bagan, round=1).order_by('urutan')
    detail_bagans_round_2 = DetailBagan.objects.filter(bagan=bagan, round=2).order_by('urutan')
    detail_bagans_round_3 = DetailBagan.objects.filter(bagan=bagan, round=3).order_by('urutan')
    detail_bagans_round_4 = DetailBagan.objects.filter(bagan=bagan, round=4).order_by('urutan')

    context = {
        'on': 'utama',
        'event': event,
        'admin_tatami': admin_tatami,
        'bagan': bagan,
        'detail_bagans_round_1': detail_bagans_round_1,
        'detail_bagans_round_2': detail_bagans_round_2,
        'detail_bagans_round_3': detail_bagans_round_3,
        'detail_bagans_round_4': detail_bagans_round_4,
    }

    return render(request, 'admin/bagan-detail.html', context)

def admin_atlet(request, event_pk):
    event = Event.objects.get(pk=event_pk)
    admin_tatami = AdminTatami.objects.filter(user=request.user, event=event).first()
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
            
            return redirect('admin-atlet', event_pk=event_pk)

    context = {
        'on': 'atlet',
        'event': event,
        'admin_tatami': admin_tatami,
        'atlets': atlets,
    }

    return render(request, 'admin/atlet.html', context)

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
