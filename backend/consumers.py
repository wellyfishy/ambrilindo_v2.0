from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
import json

@database_sync_to_async
def get_current_match_details(tatami_pk):
    from backend.models import Tatami, Matchup
    tatami = Tatami.objects.filter(pk=tatami_pk).select_related(
        'detail_bagan__bagan__nomor_tanding',
        'detail_bagan__atlet1__perguruan',
        'detail_bagan__atlet1__utusan',
        'detail_bagan__atlet2__perguruan',
        'detail_bagan__atlet2__utusan',
    ).first()
    if not tatami or not tatami.detail_bagan:
        return None
    detail_bagan = tatami.detail_bagan
    bagan = detail_bagan.bagan
    
    total_aka_score = 0
    total_ao_score = 0
    mu = Matchup.objects.filter(db=detail_bagan).first()
    if bagan and 'KUMITE BEREGU' in bagan.nama_bagan and mu:
        for matchup in Matchup.objects.filter(bagan=bagan, detail_bagan=mu.detail_bagan):
            if matchup.db.pemenang == '1':
                total_aka_score += 1
            elif matchup.db.pemenang == '2':
                total_ao_score += 1

    from backend.utils import get_athlete_kata_records, check_is_final

    return {
        "atlet_red": detail_bagan.atlet1.nama_atlet if detail_bagan.atlet1 else None,
        "atlet_red_perguruan": detail_bagan.atlet1.perguruan.nama_perguruan if detail_bagan.atlet1 and detail_bagan.atlet1.perguruan else None,
        "atlet_red_utusan": detail_bagan.atlet1.utusan.nama_utusan if detail_bagan.atlet1 and detail_bagan.atlet1.utusan else None,
        "atlet_red_logo": detail_bagan.atlet1.utusan.logo.url if (detail_bagan.atlet1 and detail_bagan.atlet1.utusan and detail_bagan.atlet1.utusan.logo) else None,
        "atlet_red_kata": detail_bagan.kata1 if detail_bagan.kata1 else None,
        "atlet_red_vr": detail_bagan.vr1 if detail_bagan.vr1 else None,
        "atlet_blue": detail_bagan.atlet2.nama_atlet if detail_bagan.atlet2 else None,
        "atlet_blue_perguruan": detail_bagan.atlet2.perguruan.nama_perguruan if detail_bagan.atlet2 and detail_bagan.atlet2.perguruan else None,
        "atlet_blue_utusan": detail_bagan.atlet2.utusan.nama_utusan if detail_bagan.atlet2 and detail_bagan.atlet2.utusan else None,
        "atlet_blue_logo": detail_bagan.atlet2.utusan.logo.url if (detail_bagan.atlet2 and detail_bagan.atlet2.utusan and detail_bagan.atlet2.utusan.logo) else None,
        "atlet_blue_kata": detail_bagan.kata2 if detail_bagan.kata2 else None,
        "atlet_blue_vr": detail_bagan.vr2 if detail_bagan.vr2 else None,
        "tipe_tanding": bagan.tipe_tanding if bagan else '2',
        "team": True if bagan and 'KUMITE BEREGU' in bagan.nama_bagan else None,
        "total_aka_score": total_aka_score,
        "total_ao_score": total_ao_score,
        "nomor_tanding": bagan.nomor_tanding.nama_nomor_tanding if bagan and bagan.nomor_tanding else '',
        "round": detail_bagan.round,
        "urutan": detail_bagan.urutan,
        "tatami_number": tatami.tatami_number,
        "nama_event": tatami.event.nama_event if tatami.event else '',
        "kata_history_aka": get_athlete_kata_records(detail_bagan.atlet1, detail_bagan),
        "kata_history_ao": get_athlete_kata_records(detail_bagan.atlet2, detail_bagan),
        "is_final": check_is_final(detail_bagan),
    }

class ScoreboardConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"scoring_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        # Send current match details immediately so scoring board is never blank on load/reload
        details = await get_current_match_details(self.tatami_pk)
        if details:
            await self.send(text_data=json.dumps({
                "command": "get_atlet",
                "details": details
            }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        command = data.get('command') or data.get('action')
        details = data.get('details')
        if not command:
            return

        if command == 'get_current':
            current_details = await get_current_match_details(self.tatami_pk)
            if current_details:
                await self.send(text_data=json.dumps({
                    "command": "get_atlet",
                    "details": current_details
                }))
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "broadcast_command",
                "message": command,
                "details": details,
            }
        )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))

    async def scoring_message(self, event):
        await self.broadcast_command(event)

class AdminControlConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"admin_control_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        command = data.get('command') or data.get('action')
        details = data.get('details')
        if not command:
            return

        await self.channel_layer.group_send(
            self.group_name,
            {
                "type": "broadcast_command",
                "message": command,
                "details": details,
            }
        )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))

    async def scoring_message(self, event):
        await self.broadcast_command(event)

class ControlPanelConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.event_pk = self.scope['url_route']['kwargs']['event_pk']
        self.bagan_pk = self.scope['url_route']['kwargs']['bagan_pk']
        self.detailbagan_pk = self.scope['url_route']['kwargs']['detailbagan_pk']
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"control_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.channel_layer.group_add(
            f"admin_control_{self.tatami_pk}",
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )
        await self.channel_layer.group_discard(
            f"admin_control_{self.tatami_pk}",
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        action = data.get('action') or data.get('command')
        details = data.get('details')
        target = data.get('target', 'all')
        if not action:
            return

        # Broadcast directly to scoring board in <2ms
        if target in ('all', 'scoring'):
            await self.channel_layer.group_send(
                f"scoring_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": action,
                    "details": details,
                }
            )

        # Broadcast to admin control and control panel
        if target in ('all', 'control'):
            await self.channel_layer.group_send(
                f"admin_control_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": action,
                    "details": details,
                }
            )
            await self.channel_layer.group_send(
                f"control_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": action,
                    "details": details,
                }
            )

        # Broadcast to jury room if targeted
        if target in ('all', 'jury'):
            await self.channel_layer.group_send(
                f"juryroom_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": action,
                    "details": details,
                }
            )

        # Broadcast to coach room if targeted
        if target in ('all', 'coach'):
            await self.channel_layer.group_send(
                f"coachroom_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": action,
                    "details": details,
                }
            )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))

    async def scoring_message(self, event):
        await self.broadcast_command(event)

class JuryRoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"juryroom_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))

class CoachSupervisorRoomConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"coachroom_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))


@database_sync_to_async
def update_tatami_kata(tatami_pk, atlet, kata):
    from backend.models import Tatami
    from backend.utils import get_athlete_kata_records
    tatami = Tatami.objects.filter(pk=tatami_pk).select_related(
        'detail_bagan__bagan__nomor_tanding',
        'detail_bagan__atlet1',
        'detail_bagan__atlet2',
    ).first()
    if not tatami or not tatami.detail_bagan:
        return None
    db = tatami.detail_bagan
    if atlet == 'aka':
        db.kata1 = kata
        db.save(update_fields=['kata1'])
    elif atlet == 'ao':
        db.kata2 = kata
        db.save(update_fields=['kata2'])
    return {
        'detail_bagan_pk': db.pk,
        'kata1': db.kata1,
        'kata2': db.kata2,
        'kata_history_aka': get_athlete_kata_records(db.atlet1, db),
        'kata_history_ao': get_athlete_kata_records(db.atlet2, db),
    }


class LoKataConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"lokata_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        # Send current match details immediately so LO screen is never blank on load/reload
        details = await get_current_match_details(self.tatami_pk)
        if details:
            await self.send(text_data=json.dumps({
                "command": "get_atlet",
                "details": details
            }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        command = data.get('command') or data.get('action')
        atlet = data.get('atlet')  # 'aka' or 'ao'
        kata = data.get('kata') or data.get('details')

        # Determine target athlete from command if not explicitly given
        if not atlet:
            if command == 'aka-kata-kirim':
                atlet = 'aka'
            elif command == 'ao-kata-kirim':
                atlet = 'ao'

        if atlet in ('aka', 'ao') and kata is not None:
            # 1. Update database
            res = await update_tatami_kata(self.tatami_pk, atlet, kata)

            cmd = 'aka-kata-kirim' if atlet == 'aka' else 'ao-kata-kirim'

            # 2. Broadcast to scoring board
            await self.channel_layer.group_send(
                f"scoring_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": cmd,
                    "details": kata,
                }
            )

            # 3. Broadcast to control panel
            await self.channel_layer.group_send(
                f"control_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": cmd,
                    "details": kata,
                }
            )

            # 4. Broadcast to admin control
            await self.channel_layer.group_send(
                f"admin_control_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": cmd,
                    "details": kata,
                }
            )

            # 5. Broadcast to jury room
            await self.channel_layer.group_send(
                f"juryroom_{self.tatami_pk}",
                {
                    "type": "broadcast_command",
                    "message": cmd,
                    "details": kata,
                }
            )

            # 6. Broadcast back to all LO clients on this tatami for sync
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "broadcast_command",
                    "message": "kata_updated",
                    "details": {
                        "atlet": atlet,
                        "kata": kata,
                        "command": cmd,
                        "kata_history_aka": res.get('kata_history_aka') if res else {},
                        "kata_history_ao": res.get('kata_history_ao') if res else {},
                    }
                }
            )

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))


@database_sync_to_async
def get_tatami_manager_details(tatami_pk):
    from backend.models import Tatami
    tatami = Tatami.objects.filter(pk=tatami_pk).select_related(
        'event',
        'detail_bagan__bagan__nomor_tanding',
        'detail_bagan__atlet1__perguruan',
        'detail_bagan__atlet1__utusan',
        'detail_bagan__atlet2__perguruan',
        'detail_bagan__atlet2__utusan',
    ).first()
    if not tatami:
        return None

    # Auto-assign if empty or completed just like LO!
    if not tatami.detail_bagan or tatami.detail_bagan.selesai:
        from backend.views import find_best_match_for_tatami, broadcast_tatami_match_update
        best_m, _ = find_best_match_for_tatami(tatami, tatami.event)
        if best_m:
            tatami.detail_bagan = best_m
            tatami.save(update_fields=['detail_bagan'])
            broadcast_tatami_match_update(tatami)
            tatami = Tatami.objects.filter(pk=tatami_pk).select_related(
                'event',
                'detail_bagan__bagan__nomor_tanding',
                'detail_bagan__atlet1__perguruan',
                'detail_bagan__atlet1__utusan',
                'detail_bagan__atlet2__perguruan',
                'detail_bagan__atlet2__utusan',
            ).first()

    db = tatami.detail_bagan
    bagan = db.bagan if db else None

    return {
        "tatami_pk": tatami.pk,
        "tatami_number": tatami.tatami_number,
        "match_pk": db.pk if db else None,
        "atlet_red": db.atlet1.nama_atlet if (db and db.atlet1) else "-",
        "atlet_red_perguruan": db.atlet1.perguruan.nama_perguruan if (db and db.atlet1 and db.atlet1.perguruan) else "-",
        "atlet_red_perguruan_id": db.atlet1.perguruan_id if (db and db.atlet1) else None,
        "atlet_red_utusan": db.atlet1.utusan.nama_utusan if (db and db.atlet1 and db.atlet1.utusan) else "-",
        "atlet_blue": db.atlet2.nama_atlet if (db and db.atlet2) else "-",
        "atlet_blue_perguruan": db.atlet2.perguruan.nama_perguruan if (db and db.atlet2 and db.atlet2.perguruan) else "-",
        "atlet_blue_perguruan_id": db.atlet2.perguruan_id if (db and db.atlet2) else None,
        "atlet_blue_utusan": db.atlet2.utusan.nama_utusan if (db and db.atlet2 and db.atlet2.utusan) else "-",
        "nomor_tanding": bagan.nomor_tanding.nama_nomor_tanding if (bagan and bagan.nomor_tanding) else '',
        "round": db.round if db else None,
        "urutan": db.urutan if db else None,
    }


@database_sync_to_async
def ws_set_tatami_match(tatami_pk, detailbagan_pk):
    from backend.models import Tatami, DetailBagan
    from backend.views import broadcast_tatami_match_update
    tatami = Tatami.objects.filter(pk=tatami_pk).first()
    if not tatami:
        return None
    db = DetailBagan.objects.filter(pk=detailbagan_pk).first()
    if db:
        tatami.detail_bagan = db
        tatami.save(update_fields=['detail_bagan'])
        tatami = Tatami.objects.filter(pk=tatami_pk).select_related(
            'event',
            'detail_bagan__bagan__nomor_tanding',
            'detail_bagan__atlet1__perguruan',
            'detail_bagan__atlet1__utusan',
            'detail_bagan__atlet2__perguruan',
            'detail_bagan__atlet2__utusan',
        ).first()
        broadcast_tatami_match_update(tatami)
    return tatami_pk


@database_sync_to_async
def ws_reset_tatami_match(tatami_pk):
    from backend.models import Tatami
    from backend.views import broadcast_tatami_match_update
    tatami = Tatami.objects.filter(pk=tatami_pk).first()
    if not tatami:
        return None
    tatami.detail_bagan = None
    tatami.save(update_fields=['detail_bagan'])
    broadcast_tatami_match_update(tatami)
    return tatami_pk


@database_sync_to_async
def ws_auto_assign_tatami_match(tatami_pk):
    from backend.models import Tatami
    from backend.views import find_best_match_for_tatami, broadcast_tatami_match_update
    tatami = Tatami.objects.filter(pk=tatami_pk).first()
    if not tatami:
        return None
    best_m, _ = find_best_match_for_tatami(tatami, tatami.event, exclude_current=True)
    if not best_m:
        best_m, _ = find_best_match_for_tatami(tatami, tatami.event, exclude_current=False)
    if best_m:
        tatami.detail_bagan = best_m
        tatami.save(update_fields=['detail_bagan'])
        broadcast_tatami_match_update(tatami)
    return tatami_pk


class TatamiManagerConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.tatami_pk = self.scope['url_route']['kwargs']['tatami_pk']
        self.group_name = f"tatamimanager_{self.tatami_pk}"

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name
        )
        await self.accept()

        # Send current match details immediately so TM screen is live
        details = await get_tatami_manager_details(self.tatami_pk)
        if details:
            await self.send(text_data=json.dumps({
                "command": "get_atlet",
                "details": details
            }))

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
        except Exception:
            return

        command = data.get('command') or data.get('action')
        if command == 'get_current':
            details = await get_tatami_manager_details(self.tatami_pk)
            if details:
                await self.send(text_data=json.dumps({
                    "command": "get_atlet",
                    "details": details
                }))
        elif command == 'set_match':
            detailbagan_pk = data.get('detailbagan_pk')
            if detailbagan_pk:
                await ws_set_tatami_match(self.tatami_pk, detailbagan_pk)
        elif command in ('auto_assign', 'auto_assign_next_match'):
            await ws_auto_assign_tatami_match(self.tatami_pk)
        elif command in ('reset_match', 'reset_tatami_match'):
            await ws_reset_tatami_match(self.tatami_pk)

    async def broadcast_command(self, event):
        await self.send(text_data=json.dumps({
            "command": event["message"],
            "details": event["details"]
        }))