# sync_service.py
import os
import json
import time
import logging
import requests
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Prefetch
from django.utils.text import slugify

from .models import (
    Event, NomorTanding, Perguruan, Utusan, Atlet, Bagan, DetailBagan, Role
)
from .utils import get_kode_realtime

logger = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(settings.BASE_DIR, 'database', 'sync_target.json')

SERVER_PRESETS = {
    'local': {
        'label': 'Dev Lokal (http://127.0.0.1:8001/)',
        'url': 'http://127.0.0.1:8001',
    },
    'production': {
        'label': 'Live Production (https://www.ambrilindo.com/)',
        'url': 'https://www.ambrilindo.com',
    }
}


def get_sync_config():
    """
    Mengambil konfigurasi target server sinkronisasi.
    Default: 'local' (http://127.0.0.1:8001).
    """
    default_config = {
        'mode': 'local',
        'url': getattr(settings, 'HOSTED_BASE_URL', 'http://127.0.0.1:8001').rstrip('/'),
        'label': 'Dev Lokal (http://127.0.0.1:8001/)',
    }
    if not os.path.exists(CONFIG_FILE):
        return default_config

    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            mode = data.get('mode', 'local')
            if mode == 'production':
                return {
                    'mode': 'production',
                    'url': 'https://www.ambrilindo.com',
                    'label': 'Live Production (https://www.ambrilindo.com/)'
                }
            elif mode == 'custom':
                custom_url = (data.get('url') or '').strip().rstrip('/')
                return {
                    'mode': 'custom',
                    'url': custom_url or 'http://127.0.0.1:8001',
                    'label': f"Kustom ({custom_url})" if custom_url else 'Kustom'
                }
            else:
                return {
                    'mode': 'local',
                    'url': (data.get('url') or 'http://127.0.0.1:8001').rstrip('/'),
                    'label': 'Dev Lokal (http://127.0.0.1:8001/)'
                }
    except Exception as e:
        logger.warning(f"Gagal membaca {CONFIG_FILE}: {e}")
        return default_config


def set_sync_config(mode, custom_url=None):
    """
    Menyimpan pilihan target server sinkronisasi ke database/sync_target.json
    """
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    if mode == 'production':
        cfg = {'mode': 'production', 'url': 'https://www.ambrilindo.com'}
        label = 'Live Production (https://www.ambrilindo.com/)'
    elif mode == 'custom':
        url = (custom_url or '').strip().rstrip('/')
        if not url.startswith('http://') and not url.startswith('https://'):
            url = f"http://{url}"
        cfg = {'mode': 'custom', 'url': url}
        label = f"Kustom ({url})"
    else:
        cfg = {'mode': 'local', 'url': 'http://127.0.0.1:8001'}
        label = 'Dev Lokal (http://127.0.0.1:8001/)'

    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
        return True, f"Target server sinkronisasi berhasil diubah ke: {label}"
    except Exception as e:
        return False, f"Gagal menyimpan target server: {str(e)}"


def get_hosted_base_url():
    """
    Mengembalikan base URL aktif yang dipilih pengguna (Localhost:8001 / ambrilindo.com).
    """
    cfg = get_sync_config()
    return cfg.get('url', getattr(settings, 'HOSTED_BASE_URL', 'http://localhost:8001')).rstrip('/')


def sync_target_context_processor(request):
    """
    Context processor agar sync_config dan user role otomatis tersedia di seluruh template.
    """
    context = {
        'sync_config': get_sync_config()
    }
    if hasattr(request, 'user') and request.user.is_authenticated:
        try:
            user_role = Role.objects.filter(user=request.user).select_related('tatami', 'event').first()
            context['role'] = user_role
            context['user_role'] = user_role
        except Exception:
            pass
    return context


EVENT_MAPPING_FILE = os.path.join(settings.BASE_DIR, 'database', 'event_mapping.json')


def get_api_headers():
    return {
        'Authorization': f'Bearer {settings.HOSTED_API_TOKEN}',
        'Content-Type': 'application/json',
    }


def get_event_mapping(local_event_pk):
    """
    Mengambil konfigurasi mapping event lokal ke event di server hosted aktif.
    """
    target_mode = get_sync_config().get('mode', 'local')
    key = f"local_{local_event_pk}_{target_mode}"
    fallback_key = f"local_{local_event_pk}"

    if not os.path.exists(EVENT_MAPPING_FILE):
        return {}

    try:
        with open(EVENT_MAPPING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get(key) or data.get(fallback_key) or {}
    except Exception as e:
        logger.warning(f"Gagal membaca {EVENT_MAPPING_FILE}: {e}")
        return {}


def set_event_mapping(local_event_pk, hosted_event_id, hosted_event_name):
    """
    Menyimpan relasi event lokal ke ID event di server hosted aktif.
    """
    target_mode = get_sync_config().get('mode', 'local')
    key = f"local_{local_event_pk}_{target_mode}"

    os.makedirs(os.path.dirname(EVENT_MAPPING_FILE), exist_ok=True)
    data = {}
    if os.path.exists(EVENT_MAPPING_FILE):
        try:
            with open(EVENT_MAPPING_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            data = {}

    data[key] = {
        'hosted_event_id': int(hosted_event_id),
        'hosted_event_name': str(hosted_event_name).strip(),
        'target_mode': target_mode,
    }

    try:
        with open(EVENT_MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
        return True, f"Event lokal berhasil dihubungkan ke Event Web: '{hosted_event_name}' (ID {hosted_event_id})"
    except Exception as e:
        return False, f"Gagal menyimpan mapping event: {str(e)}"


_hosted_events_cache = {}


def fetch_hosted_events(force_refresh=False):
    """
    Menghubungi web server aktif untuk mendapatkan daftar seluruh event publik.
    Dilengkapi in-memory caching 60 detik dan fallback untuk mencegah lag.
    """
    base_url = get_hosted_base_url()
    now = time.time()
    cached = _hosted_events_cache.get(base_url)
    if not force_refresh and cached and (now - cached.get('time', 0) < 60):
        return True, cached['events']

    url = f"{base_url}/api/sync/events/"
    headers = get_api_headers()

    try:
        response = requests.get(url, headers=headers, timeout=3.5)
        response.raise_for_status()
        res_data = response.json()
        if res_data.get('status') == 'success':
            events = res_data.get('events', [])
            _hosted_events_cache[base_url] = {'time': now, 'events': events}
            return True, events
        return False, res_data.get('error', 'Gagal memuat event dari server publik')
    except requests.exceptions.RequestException as e:
        if cached and cached.get('events'):
            logger.info(f"Using cached events for {base_url} due to connection error: {e}")
            return True, cached['events']
        return False, f"Tidak dapat terhubung ke server web ({base_url}): {str(e)}"



def pull_athletes_from_hosted(event_pk):
    """
    Menarik seluruh data atlet, perguruan, utusan, dan nomor tanding
    dari server hosted (web public) ke database lokal secara IDEMPOTENT (anti-dobel).
    """
    event = Event.objects.filter(pk=event_pk).first()
    if not event:
        return False, f"Event PK {event_pk} tidak ditemukan di database lokal."

    mapping = get_event_mapping(event_pk)
    target_hosted_id = mapping.get('hosted_event_id')
    hosted_name = mapping.get('hosted_event_name')

    # Jika belum dihubungkan, coba auto-discover dari daftar event di web publik
    if not target_hosted_id:
        ok, hosted_events = fetch_hosted_events()
        if ok and isinstance(hosted_events, list):
            local_name = (event.nama_event or '').strip().lower()
            matching = [ev for ev in hosted_events if local_name in ev.get('nama_event', '').lower() or ev.get('nama_event', '').lower() in local_name]
            if len(matching) == 1:
                target_hosted_id = matching[0]['id']
                hosted_name = matching[0]['nama_event']
                set_event_mapping(event_pk, target_hosted_id, hosted_name)
                logger.info(f"Auto-mapped local event #{event_pk} to hosted event #{target_hosted_id} ('{hosted_name}')")

    if not target_hosted_id:
        return False, "Event lokal belum dihubungkan ke Event di Web Public. Silakan pilih event di tombol 'Hubungkan ke Event Web' terlebih dahulu."

    base_url = get_hosted_base_url()
    url = f"{base_url}/api/sync/export-atlet/{target_hosted_id}/"
    headers = get_api_headers()

    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal menghubungi server public saat pull_athletes: {e}")
        return False, f"Gagal koneksi ke server publik: {str(e)}"

    if data.get('status') != 'success':
        return False, data.get('error', 'Server publik mengembalikan status gagal.')

    atlets_data = data.get('atlets', [])
    created_count = 0
    updated_count = 0

    with transaction.atomic():
        # 1. Sync Perguruan
        for p_name in data.get('perguruans', []):
            if p_name:
                Perguruan.objects.get_or_create(event=event, nama_perguruan=p_name.strip().upper())

        # 2. Sync Utusan (Mendukung utusans_detail dengan URL logo)
        utusan_logo_tasks = []
        utusans_detail = data.get('utusans_detail', [])
        if utusans_detail:
            for u_info in utusans_detail:
                u_name = (u_info.get('nama_utusan') or '').strip().upper()
                logo_url = (u_info.get('logo_url') or '').strip()
                if u_name:
                    u_obj, _ = Utusan.objects.get_or_create(event=event, nama_utusan=u_name)
                    if logo_url:
                        utusan_logo_tasks.append((u_obj.pk, u_name, logo_url))
        else:
            for u_name in data.get('utusans', []):
                if u_name:
                    Utusan.objects.get_or_create(event=event, nama_utusan=u_name.strip().upper())

        # 3. Sync Nomor Tanding
        for nt_item in data.get('nomor_tandings', []):
            nt_nama = nt_item.get('nama_nomor_tanding', '').strip()
            if nt_nama:
                NomorTanding.objects.get_or_create(
                    event=event,
                    nama_nomor_tanding=nt_nama
                )

        # 4. Sync Atlet (Idempotent update_or_create)
        for a_item in atlets_data:
            nama = a_item.get('nama_atlet', '').strip()
            perguruan_name = (a_item.get('perguruan') or '').strip().upper()
            utusan_name = (a_item.get('utusan') or '').strip().upper()
            nt_name = (a_item.get('nomor_tanding') or '').strip()
            nik = (a_item.get('nik') or '').strip()

            if not nama or not nt_name:
                continue

            perguruan_obj = None
            if perguruan_name:
                perguruan_obj, _ = Perguruan.objects.get_or_create(event=event, nama_perguruan=perguruan_name)

            utusan_obj = None
            if utusan_name:
                utusan_obj, _ = Utusan.objects.get_or_create(event=event, nama_utusan=utusan_name)

            nt_obj = NomorTanding.objects.filter(event=event, nama_nomor_tanding=nt_name).first()
            if not nt_obj:
                nt_obj, _ = NomorTanding.objects.get_or_create(event=event, nama_nomor_tanding=nt_name)

            kode_atlet_val = (a_item.get('kode_atlet') or '').strip() or None

            # 1. Cari atlet yang sudah ada: prioritaskan kode_atlet unik, lalu fallback nama + utusan
            atlet_obj = None
            if kode_atlet_val:
                atlet_obj = Atlet.objects.filter(event=event, kode_atlet=kode_atlet_val).first()

            if not atlet_obj and utusan_obj:
                atlet_obj = Atlet.objects.filter(event=event, nama_atlet__iexact=nama, utusan=utusan_obj).first()

            created = False
            if atlet_obj:
                atlet_obj.nama_atlet = nama
                atlet_obj.nomor_tanding = nt_obj
                atlet_obj.perguruan = perguruan_obj
                atlet_obj.utusan = utusan_obj
                if nik:
                    atlet_obj.nik = nik
                if kode_atlet_val:
                    atlet_obj.kode_atlet = kode_atlet_val
                atlet_obj.save()
            else:
                atlet_obj = Atlet.objects.create(
                    event=event,
                    nama_atlet=nama,
                    nomor_tanding=nt_obj,
                    perguruan=perguruan_obj,
                    utusan=utusan_obj,
                    nik=nik or None,
                    kode_atlet=kode_atlet_val,
                )
                created = True

            if created:
                created_count += 1
            else:
                updated_count += 1

    # 5. Unduh Logo Utusan / Kontingen (di luar atomic block untuk mencegah SQLite write lock)
    downloaded_logos = 0
    if utusan_logo_tasks:
        headers = get_api_headers()
        for u_pk, u_name, logo_url in utusan_logo_tasks:
            try:
                u_obj = Utusan.objects.filter(pk=u_pk).first()
                if not u_obj or u_obj.logo:
                    continue
                # Download logo image (WebP teroptimasi dari server hosted)
                r = requests.get(logo_url, headers=headers, timeout=5)
                if r.status_code == 200 and r.content:
                    clean_slug = slugify(u_name) or f"dojo_{u_pk}"
                    filename = f"{clean_slug}.webp"
                    u_obj.logo.save(filename, ContentFile(r.content), save=True)
                    downloaded_logos += 1
                    logger.info(f"Berhasil mengunduh logo untuk utusan '{u_name}': {u_obj.logo.name}")
            except Exception as err:
                logger.warning(f"Gagal mengunduh logo untuk utusan '{u_name}' ({logo_url}): {err}")

    target_label = f"'{hosted_name}' (ID {target_hosted_id})" if hosted_name else f"ID #{target_hosted_id}"
    msg = f"Berhasil menarik data dari {target_label}: {created_count} atlet baru ditambahkan, {updated_count} diperbarui (Total: {len(atlets_data)} atlet)"
    if downloaded_logos:
        msg += f", {downloaded_logos} logo kontingen diunduh"
    msg += "."
    logger.info(msg)
    return True, msg


def push_bagan_to_hosted(event_pk, bagan_pks=None):
    """
    Mengirimkan seluruh struktur Bagan dan DetailBagan lokal ke server hosted.
    Mendukung idempotent upsert di web public (aman revisi TM / acak ulang).
    """
    event = Event.objects.filter(pk=event_pk).first()
    if not event:
        return False, f"Event PK {event_pk} tidak ditemukan di database lokal."

    mapping = get_event_mapping(event_pk)
    target_hosted_id = mapping.get('hosted_event_id')
    hosted_name = mapping.get('hosted_event_name')

    if not target_hosted_id:
        ok, hosted_events = fetch_hosted_events()
        if ok and isinstance(hosted_events, list):
            local_name = (event.nama_event or '').strip().lower()
            matching = [ev for ev in hosted_events if local_name in ev.get('nama_event', '').lower() or ev.get('nama_event', '').lower() in local_name]
            if len(matching) == 1:
                target_hosted_id = matching[0]['id']
                hosted_name = matching[0]['nama_event']
                set_event_mapping(event_pk, target_hosted_id, hosted_name)

    if not target_hosted_id:
        return False, "Event lokal belum dihubungkan ke Event di Web Public. Silakan pilih event di tombol 'Hubungkan ke Event Web' terlebih dahulu."

    bagans_qs = (
        Bagan.objects.filter(event=event)
        .select_related('nomor_tanding', 'juara_1', 'juara_2', 'juara_3a', 'juara_3b')
        .prefetch_related(
            Prefetch(
                'detailbagan_set',
                queryset=DetailBagan.objects.select_related(
                    'atlet1__perguruan', 'atlet1__utusan',
                    'atlet2__perguruan', 'atlet2__utusan',
                ).order_by('round', 'urutan'),
                to_attr='prefetched_details'
            )
        )
    )
    if bagan_pks is not None:
        if 'semua' in bagan_pks:
            pass  # kirim semua bagan
        elif len(bagan_pks) == 0:
            return False, "Tidak ada bagan yang dipilih untuk dikirim."
        else:
            bagans_qs = bagans_qs.filter(pk__in=bagan_pks)

    if not bagans_qs.exists():
        return False, "Tidak ada bagan yang ditemukan untuk dikirim."

    bagans_payload = []
    for bagan in bagans_qs:
        dbs_qs = getattr(bagan, 'prefetched_details', [])
        dbs_payload = []

        for db in dbs_qs:
            nama1 = db.atlet1.nama_atlet if db.atlet1 else ""
            kode1 = db.atlet1.kode_atlet if (db.atlet1 and db.atlet1.kode_atlet) else ""
            perguruan1 = db.atlet1.perguruan.nama_perguruan if (db.atlet1 and db.atlet1.perguruan) else ""
            utusan1 = db.atlet1.utusan.nama_utusan if (db.atlet1 and db.atlet1.utusan) else ""

            nama2 = db.atlet2.nama_atlet if db.atlet2 else ""
            kode2 = db.atlet2.kode_atlet if (db.atlet2 and db.atlet2.kode_atlet) else ""
            perguruan2 = db.atlet2.perguruan.nama_perguruan if (db.atlet2 and db.atlet2.perguruan) else ""
            utusan2 = db.atlet2.utusan.nama_utusan if (db.atlet2 and db.atlet2.utusan) else ""

            dbs_payload.append({
                'round': db.round,
                'urutan': db.urutan,
                'atlet1_nama': nama1,
                'atlet1_kode': kode1,
                'atlet1_perguruan': perguruan1,
                'atlet1_utusan': utusan1,
                'atlet2_nama': nama2,
                'atlet2_kode': kode2,
                'atlet2_perguruan': perguruan2,
                'atlet2_utusan': utusan2,
                'kode_realtime': get_kode_realtime(db),
                'score1': db.score1,
                'score2': db.score2,
                'scorekecil1': db.scorekecil1,
                'scorekecil2': db.scorekecil2,
                'vr1': db.vr1,
                'vr2': db.vr2,
                'kata1': db.kata1,
                'kata2': db.kata2,
                'selesai': db.selesai,
                'pemenang': db.pemenang,
            })

        bagans_payload.append({
            'kode': bagan.kode or "",
            'nama_bagan': bagan.nama_bagan,
            'nomor_tanding': bagan.nomor_tanding.nama_nomor_tanding if bagan.nomor_tanding else "",
            'is_bob': bool(bagan.is_bob or (bagan.nomor_tanding and getattr(bagan.nomor_tanding, 'is_bob', False))),
            'tipe_tanding': bagan.tipe_tanding,
            'pool': bagan.pool,
            'juara_1': bagan.juara_1.nama_atlet if bagan.juara_1 else "",
            'juara_1_kode': bagan.juara_1.kode_atlet if (bagan.juara_1 and bagan.juara_1.kode_atlet) else "",
            'juara_2': bagan.juara_2.nama_atlet if bagan.juara_2 else "",
            'juara_2_kode': bagan.juara_2.kode_atlet if (bagan.juara_2 and bagan.juara_2.kode_atlet) else "",
            'juara_3a': bagan.juara_3a.nama_atlet if bagan.juara_3a else "",
            'juara_3a_kode': bagan.juara_3a.kode_atlet if (bagan.juara_3a and bagan.juara_3a.kode_atlet) else "",
            'juara_3b': bagan.juara_3b.nama_atlet if bagan.juara_3b else "",
            'juara_3b_kode': bagan.juara_3b.kode_atlet if (bagan.juara_3b and bagan.juara_3b.kode_atlet) else "",
            'detail_bagans': dbs_payload,
        })

    is_full_sync = bool(bagan_pks is None or 'semua' in bagan_pks)
    payload = {
        'event_pk': target_hosted_id,
        'bagans': bagans_payload,
        'is_full_sync': is_full_sync,
    }

    base_url = get_hosted_base_url()
    url = f"{base_url}/api/sync/push-bagan/"
    headers = get_api_headers()

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal mengirim bagan ke server public: {e}")
        return False, f"Gagal koneksi ke server publik: {str(e)}"

    if data.get('status') != 'success':
        return False, data.get('error', 'Server publik mengembalikan error.')

    msg = data.get('message', 'Bagan berhasil dikirim ke server public.')
    logger.info(msg)
    return True, msg


def force_sync_results_to_hosted(event_pk):
    """
    Memindai seluruh partai yang sudah selesai (selesai=True) di database lokal
    lalu mengirim snapshot lengkapnya ke server hosted.
    Digunakan jika terjadi miss-sync atau setelah koneksi internet pulih.
    """
    event = Event.objects.filter(pk=event_pk).first()
    if not event:
        return False, f"Event PK {event_pk} tidak ditemukan di database lokal."

    finished_dbs = (
        DetailBagan.objects.filter(bagan__event=event, selesai=True)
        .select_related('bagan', 'atlet1', 'atlet2')
    )

    if not finished_dbs.exists():
        return False, "Belum ada pertandingan yang selesai untuk disinkronkan."

    results_payload = []
    for db in finished_dbs:
        # Hitung next_kode_realtime jika ada babak selanjutnya
        next_round_number = db.round + 1
        next_round_urutan = (db.urutan + 1) // 2
        next_db = DetailBagan.objects.filter(
            bagan=db.bagan, round=next_round_number, urutan=next_round_urutan
        ).first()

        results_payload.append({
            'kode_realtime': get_kode_realtime(db),
            'score1': db.score1,
            'score2': db.score2,
            'scorekecil1': db.scorekecil1,
            'scorekecil2': db.scorekecil2,
            'vr1': db.vr1,
            'vr2': db.vr2,
            'kata1': db.kata1,
            'kata2': db.kata2,
            'selesai': db.selesai,
            'pemenang': db.pemenang,
            'next_kode_realtime': get_kode_realtime(next_db) if next_db else None,
            'target_slot': 'atlet1' if db.urutan % 2 == 1 else 'atlet2',
        })

    mapping = get_event_mapping(event_pk)
    target_hosted_id = mapping.get('hosted_event_id')

    # Kumpulkan juga status juara 1 - 3b dari bagan yang sudah memiliki juara
    champions_payload = []
    for b in Bagan.objects.filter(event=event).select_related('juara_1', 'juara_2', 'juara_3a', 'juara_3b'):
        if b.juara_1 or b.juara_2 or b.juara_3a or b.juara_3b:
            champions_payload.append({
                'kode': b.kode or "",
                'nama_bagan': b.nama_bagan,
                'juara_1': b.juara_1.nama_atlet if b.juara_1 else "",
                'juara_1_kode': b.juara_1.kode_atlet if (b.juara_1 and b.juara_1.kode_atlet) else "",
                'juara_2': b.juara_2.nama_atlet if b.juara_2 else "",
                'juara_2_kode': b.juara_2.kode_atlet if (b.juara_2 and b.juara_2.kode_atlet) else "",
                'juara_3a': b.juara_3a.nama_atlet if b.juara_3a else "",
                'juara_3a_kode': b.juara_3a.kode_atlet if (b.juara_3a and b.juara_3a.kode_atlet) else "",
                'juara_3b': b.juara_3b.nama_atlet if b.juara_3b else "",
                'juara_3b_kode': b.juara_3b.kode_atlet if (b.juara_3b and b.juara_3b.kode_atlet) else "",
            })

    payload = {
        'event_pk': target_hosted_id or event.pk,
        'results': results_payload,
        'champions': champions_payload,
    }

    base_url = get_hosted_base_url()
    url = f"{base_url}/api/sync/force-results/"
    headers = get_api_headers()

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Gagal mengirim force sync results: {e}")
        return False, f"Gagal koneksi ke server publik: {str(e)}"

    if data.get('status') != 'success':
        return False, data.get('error', 'Server publik mengembalikan error.')

    msg = data.get('message', f"Berhasil menyinkronkan ulang {len(results_payload)} hasil pertandingan ke public.")
    logger.info(msg)
    return True, msg
