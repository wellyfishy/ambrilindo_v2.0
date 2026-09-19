# utils.py
import time
import logging
import threading
import requests
from concurrent.futures import ThreadPoolExecutor
from django.conf import settings

logger = logging.getLogger(__name__)
_sync_executor = ThreadPoolExecutor(max_workers=3)
_queue_lock = threading.Lock()
_worker_started = False

def get_kode_realtime(detail_bagan):
    """
    Menghasilkan kode realtime unik dan deterministik untuk DetailBagan.
    Format: f"{event_code}-{bagan.pk}-{detail_bagan.pk}"
    """
    if not detail_bagan or not detail_bagan.bagan:
        return ''
    bagan = detail_bagan.bagan
    event = bagan.event
    event_code = getattr(event, 'event_code', None) or (f"EV{event.pk}" if event else "EV0")
    return f"{event_code}-{bagan.pk}-{detail_bagan.pk}"

def send_to_hosted(payload, endpoint):
    """
    Mengirim HTTP POST request ke server hosted secara sinkron.
    Menggunakan get_hosted_base_url() dinamis (pilihan user di dashboard).
    """
    from .sync_service import get_hosted_base_url
    base_url = get_hosted_base_url()
    url = f'{base_url}/{endpoint}'
    headers = {
        'Authorization': f'Bearer {settings.HOSTED_API_TOKEN}',
        'Content-Type': 'application/json',
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=5)
        response.raise_for_status()
        return True, response.json()
    except requests.exceptions.Timeout:
        logger.warning(f"send_to_hosted to {endpoint} timed out.")
        return False, 'Request timed out'
    except requests.exceptions.ConnectionError:
        logger.warning(f"send_to_hosted could not connect to {url}.")
        return False, 'Could not connect to server'
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 'unknown'
        logger.warning(f"send_to_hosted HTTP error: {status_code} for {endpoint}")
        return False, f'Server returned error: {status_code}'
    except Exception as e:
        logger.warning(f"send_to_hosted error: {str(e)}")
        return False, str(e)

def process_sync_queue():
    """
    Memproses antrean SyncQueue secara ketat FIRST-IN, FIRST-OUT (FIFO).
    Hanya memproses antrean dari event yang memiliki is_live_sync_enabled=True
    (atau antrean global tanpa event).
    Jika suatu item gagal (misal koneksi internet mati), antrean dihentikan
    agar tidak ada data babak selanjutnya yang melompati urutan di server publik.
    """
    from django.db.models import Q
    from .models import SyncQueue

    # Cegah proses berjalan bersamaan (jaminan single-worker FIFO)
    if not _queue_lock.acquire(blocking=False):
        return

    try:
        active_filter = Q(event__isnull=True) | Q(event__is_live_sync_enabled=True)
        while True:
            # Ambil item tertua aktif (FIFO berdasarkan ID terkecil)
            item = (
                SyncQueue.objects
                .filter(status__in=['pending', 'failed'])
                .filter(active_filter)
                .order_by('id')
                .first()
            )
            if not item:
                break

            item.status = 'processing'
            item.save(update_fields=['status', 'updated_at'])

            success, result = send_to_hosted(item.payload, item.endpoint)

            if success:
                item.status = 'synced'
                item.last_error = None
                item.save(update_fields=['status', 'last_error', 'updated_at'])
                logger.info(f"SyncQueue #{item.pk} to {item.endpoint} SUCCEEDED.")
                # Lanjut ke item berikutnya secara berurutan
            else:
                item.status = 'failed'
                item.retry_count += 1
                item.last_error = str(result)
                item.save(update_fields=['status', 'retry_count', 'last_error', 'updated_at'])
                logger.warning(
                    f"SyncQueue #{item.pk} to {item.endpoint} FAILED (retry {item.retry_count}): {result}. "
                    "Halting FIFO queue until connection is restored."
                )
                # PRINSIP KETAT FIFO: Berhenti di sini! Jangan kirim data setelahnya
                # sampai data ini berhasil terkirim ke server publik.
                break
    except Exception as e:
        logger.error(f"Unexpected error in process_sync_queue: {e}")
    finally:
        _queue_lock.release()

def trigger_sync_queue():
    """Memicu pemrosesan antrean di thread terpisah."""
    return _sync_executor.submit(process_sync_queue)

def enqueue_sync(payload, endpoint, event=None):
    """
    Menyimpan payload ke database lokal SyncQueue secara persisten,
    lalu langsung memicu pemrosesan antrean secara non-blocking.
    """
    from .models import SyncQueue
    queue_item = SyncQueue.objects.create(
        event=event,
        endpoint=endpoint,
        payload=payload,
        status='pending'
    )
    trigger_sync_queue()
    return queue_item

def send_to_hosted_async(payload, endpoint, event=None, on_complete=None):
    """
    Wrapper yang menyimpan request ke antrean persisten FIFO (SyncQueue)
    lalu memprosesnya di latar belakang tanpa memblokir operator tatami.
    Jika live sync dinonaktifkan untuk event ini, request diabaikan tanpa antrean.
    """
    from .models import Event, DetailBagan

    # Resolusi event jika belum diberikan eksplisit
    if event is None and isinstance(payload, dict):
        detail_id = payload.get('detail_bagan_id')
        if detail_id:
            db = DetailBagan.objects.filter(pk=detail_id).select_related('bagan__event').first()
            if db and db.bagan:
                event = db.bagan.event
        if event is None and payload.get('kode_realtime'):
            try:
                db_pk = int(str(payload['kode_realtime']).strip().split('-')[-1])
                db = DetailBagan.objects.filter(pk=db_pk).select_related('bagan__event').first()
                if db and db.bagan:
                    event = db.bagan.event
            except Exception:
                pass

    # Cek apakah live sync aktif untuk event ini (Default: False)
    if event is not None:
        if not getattr(event, 'is_live_sync_enabled', False):
            logger.debug(f"Live sync dilewati: Event #{event.pk} ('{event.nama_event}') sync dinonaktifkan.")
            if on_complete and callable(on_complete):
                try:
                    on_complete(True, None)
                except Exception as e:
                    logger.error(f"Error in on_complete callback: {e}")
            return None
    else:
        # Jika tidak ada event yang terasosiasi, periksa apakah ada event yang mengaktifkan live sync
        has_any_active_event = Event.objects.filter(is_live_sync_enabled=True).exists()
        if not has_any_active_event:
            logger.debug("Live sync dilewati: Tidak ada event aktif dengan live sync diaktifkan.")
            if on_complete and callable(on_complete):
                try:
                    on_complete(True, None)
                except Exception as e:
                    logger.error(f"Error in on_complete callback: {e}")
            return None

    queue_item = enqueue_sync(payload, endpoint, event=event)
    if on_complete and callable(on_complete):
        try:
            on_complete(True, queue_item.pk)
        except Exception as e:
            logger.error(f"Error in on_complete callback: {e}")
    return queue_item

def _background_retry_loop():
    """Heartbeat background thread yang mencoba mengirim ulang antrean tertunda setiap 15 detik."""
    from django.db.models import Q
    from .models import SyncQueue
    active_filter = Q(event__isnull=True) | Q(event__is_live_sync_enabled=True)
    while True:
        try:
            time.sleep(15)
            has_pending = SyncQueue.objects.filter(status__in=['pending', 'failed']).filter(active_filter).exists()
            if has_pending:
                process_sync_queue()
        except Exception as e:
            logger.debug(f"Background retry loop idle: {e}")

def start_sync_queue_worker():
    """Memulai worker daemon retry otomatis di background."""
    global _worker_started
    if not _worker_started:
        _worker_started = True
        t = threading.Thread(target=_background_retry_loop, daemon=True, name="SyncQueueRetryWorker")
        t.start()
        logger.info("SyncQueue persistent FIFO worker daemon started.")

def get_athlete_kata_records(atlet, current_db=None):
    """
    Mengambil riwayat kata yang pernah dimainkan atlet pada nomor tanding / bagan ini.
    Mengembalikan dict mapping string kata dan nama kata ke info babak:
    {
        "12 - Unsu": {"round": 1, "label": "Babak 1", "raw_kata": "12 - Unsu"},
        "Unsu": {"round": 1, "label": "Babak 1", ...},
    }
    """
    from .models import DetailBagan
    from django.db.models import Q
    if not atlet:
        return {}

    qs = DetailBagan.objects.filter(Q(atlet1=atlet) | Q(atlet2=atlet))
    if current_db and current_db.bagan and current_db.bagan.nomor_tanding:
        qs = qs.filter(bagan__nomor_tanding=current_db.bagan.nomor_tanding)
    elif current_db and current_db.bagan:
        qs = qs.filter(bagan=current_db.bagan)

    if current_db and current_db.pk:
        qs = qs.exclude(pk=current_db.pk)

    records = {}
    for db in qs.order_by('round', 'urutan'):
        k = None
        if db.atlet1_id == atlet.pk and db.kata1 and db.kata1.strip() and db.kata1 != '0 - Blank':
            k = db.kata1.strip()
        elif db.atlet2_id == atlet.pk and db.kata2 and db.kata2.strip() and db.kata2 != '0 - Blank':
            k = db.kata2.strip()

        if k:
            info = {
                "round": db.round or 1,
                "label": f"Babak {db.round}" if db.round else "Babak Sebelumnya",
                "raw_kata": k,
                "nama_bagan": db.bagan.nama_bagan if db.bagan else "",
                "is_current_round": False,
            }
            records[k] = info
            if ' - ' in k:
                pure = k.split(' - ', 1)[1].strip()
                if pure and pure not in records:
                    records[pure] = info

    # Also include current_db if it already has a kata chosen
    if current_db and current_db.pk:
        curr_k = None
        if current_db.atlet1_id == atlet.pk and current_db.kata1 and current_db.kata1.strip() and current_db.kata1 != '0 - Blank':
            curr_k = current_db.kata1.strip()
        elif current_db.atlet2_id == atlet.pk and current_db.kata2 and current_db.kata2.strip() and current_db.kata2 != '0 - Blank':
            curr_k = current_db.kata2.strip()

        if curr_k and curr_k not in records:
            info = {
                "round": current_db.round or 1,
                "label": f"Babak {current_db.round}" if current_db.round else "Babak 1",
                "raw_kata": curr_k,
                "nama_bagan": current_db.bagan.nama_bagan if current_db.bagan else "",
                "is_current_round": True,
            }
            records[curr_k] = info
            if ' - ' in curr_k:
                pure = curr_k.split(' - ', 1)[1].strip()
                if pure and pure not in records:
                    records[pure] = info

    return records

def get_category_pool_count(bagan):
    """Menghitung jumlah pool pada nomor tanding ini (di luar pool=0 final)."""
    if not bagan:
        return 1
    if bagan.nomor_tanding:
        from .models import Bagan
        pools = Bagan.objects.filter(nomor_tanding=bagan.nomor_tanding).exclude(pool=0)
        cnt = pools.count()
        if cnt > 0:
            return cnt
    p = getattr(bagan, 'pool', 1)
    return p if (p and p > 0) else 1

def check_is_final(detail_bagan):
    """
    Memeriksa apakah pertandingan ini adalah babak final / perebutan medali.
    Aturan:
    - 1 pool (single pool bagan): Round 4 adalah final (round >= 4)
    - 2 pools bagan: Round 5 adalah final (round >= 5)
    - 4 pools bagan: Round 6 adalah final (round >= 6)
    """
    if not detail_bagan or not detail_bagan.bagan:
        return False

    r = detail_bagan.round
    if not r:
        return False

    bagan = detail_bagan.bagan
    pool_count = get_category_pool_count(bagan)

    if pool_count <= 1:
        return r >= 4
    elif pool_count <= 2:
        return r >= 5
    else:
        return r >= 6

