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
    """
    url = f'{settings.HOSTED_BASE_URL}/{endpoint}'
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
    Jika suatu item gagal (misal koneksi internet mati), antrean dihentikan
    agar tidak ada data babak selanjutnya yang melompati urutan di server publik.
    """
    from .models import SyncQueue

    # Cegah proses berjalan bersamaan (jaminan single-worker FIFO)
    if not _queue_lock.acquire(blocking=False):
        return

    try:
        while True:
            # Ambil item tertua (FIFO berdasarkan ID terkecil)
            item = (
                SyncQueue.objects
                .filter(status__in=['pending', 'failed'])
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

def enqueue_sync(payload, endpoint):
    """
    Menyimpan payload ke database lokal SyncQueue secara persisten,
    lalu langsung memicu pemrosesan antrean secara non-blocking.
    """
    from .models import SyncQueue
    queue_item = SyncQueue.objects.create(
        endpoint=endpoint,
        payload=payload,
        status='pending'
    )
    trigger_sync_queue()
    return queue_item

def send_to_hosted_async(payload, endpoint, on_complete=None):
    """
    Wrapper yang menyimpan request ke antrean persisten FIFO (SyncQueue)
    lalu memprosesnya di latar belakang tanpa memblokir operator tatami.
    """
    queue_item = enqueue_sync(payload, endpoint)
    if on_complete and callable(on_complete):
        try:
            on_complete(True, queue_item.pk)
        except Exception as e:
            logger.error(f"Error in on_complete callback: {e}")
    return queue_item

def _background_retry_loop():
    """Heartbeat background thread yang mencoba mengirim ulang antrean tertunda setiap 15 detik."""
    from .models import SyncQueue
    while True:
        try:
            time.sleep(15)
            has_pending = SyncQueue.objects.filter(status__in=['pending', 'failed']).exists()
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
