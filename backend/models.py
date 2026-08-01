from django.db import models, transaction # type: ignore
from django.contrib.auth.models import User # type: ignore

class Admin(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)

class Event(models.Model):
    nama_event = models.CharField(max_length=150, null=True, blank=True)

    def __str__(self):
        return f'{self.nama_event}'

class NomorTanding(models.Model):
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    nama_nomor_tanding = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f'{self.event} - {self.nama_nomor_tanding}'
    
class Perguruan(models.Model):
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    nama_perguruan = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f'{self.event} - {self.nama_perguruan}'
    
class Utusan(models.Model):
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    nama_utusan = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f'{self.event} - {self.nama_utusan}'
    
class Atlet(models.Model):
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    nama_atlet = models.CharField(max_length=50, null=True, blank=True)
    perguruan = models.ForeignKey(Perguruan, null=True, blank=True, on_delete=models.SET_NULL)
    utusan = models.ForeignKey(Utusan, null=True, blank=True, on_delete=models.SET_NULL)
    nomor_tanding = models.ForeignKey(NomorTanding, null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return f'{self.event} - {self.nama_atlet}'
        
class Bagan(models.Model):
    TIPE = [
        ('1', 'Kata'),
        ('2', 'Kumite'),
    ]
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    nama_bagan = models.CharField(max_length=100, null=True, blank=True)
    nomor_tanding = models.ForeignKey(NomorTanding, null=True, blank=True, on_delete=models.SET_NULL)
    tipe_tanding = models.CharField(max_length=20, null=True, blank=True, choices=TIPE)
    juara_1 = models.ForeignKey(Atlet, on_delete=models.SET_NULL, related_name="juara1", null=True, blank=True)
    juara_2 = models.ForeignKey(Atlet, on_delete=models.SET_NULL, related_name="juara2", null=True, blank=True)
    juara_3a = models.ForeignKey(Atlet, on_delete=models.SET_NULL, related_name="juara3a", null=True, blank=True)
    juara_3b = models.ForeignKey(Atlet, on_delete=models.SET_NULL, related_name="juara3b", null=True, blank=True)
    round_robin = models.BooleanField(default=False)
    pool = models.IntegerField(default=1)
    kode = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return f'{self.nama_bagan}'

    def save(self, *args, **kwargs):
        if not self.kode and self.event_id:
            with transaction.atomic():
                existing_codes = (
                    Bagan.objects
                    .select_for_update()
                    .filter(event=self.event)
                    .exclude(kode__isnull=True)
                    .exclude(kode='')
                    .values_list('kode', flat=True)
                )

                max_num = 0
                for code in existing_codes:
                    try:
                        num = int(code)
                        max_num = max(max_num, num)
                    except ValueError:
                        continue  # skip any non-numeric legacy kode values

                self.kode = str(max_num + 1).zfill(3)

        super().save(*args, **kwargs)
    
class DetailBagan(models.Model):
    TIPE_PEMENANG = [
        ('1', 'Aka'),
        ('2', 'Ao'),
        ('3', 'Draw')
    ]
    bagan = models.ForeignKey(Bagan, null=True, blank=True, on_delete=models.CASCADE)
    round = models.IntegerField(null=True, blank=True)
    urutan = models.IntegerField(null=True, blank=True)
    atlet1 = models.ForeignKey(Atlet, null=True, blank=True, on_delete=models.SET_NULL, related_name="atlet1")
    atlet2 = models.ForeignKey(Atlet, null=True, blank=True, on_delete=models.SET_NULL, related_name="atlet2")
    score1 = models.CharField(max_length=10, null=True, blank=True)
    score2 = models.CharField(max_length=10, null=True, blank=True)
    scorekecil1 = models.CharField(max_length=10, null=True, blank=True)
    scorekecil2 = models.CharField(max_length=10, null=True, blank=True)
    vr1 = models.BooleanField(default=False)
    vr2 = models.BooleanField(default=False)
    kata1 = models.CharField(max_length=50, null=True, blank=True, default='0 - Blank')
    kata2 = models.CharField(max_length=50, null=True, blank=True, default='0 - Blank')
    pemenang = models.CharField(null=True, blank=True, max_length=50, choices=TIPE_PEMENANG)
    hantei = models.BooleanField(default=False)
    selesai = models.BooleanField(default=False)
    team = models.BooleanField(default=False)
    kode = models.CharField(unique=True, null=True, blank=True, max_length=50)

    def __str__(self):
        return f'{self.pk} - {self.round} - {self.urutan}'
    
class Matchup(models.Model):
    bagan = models.ForeignKey(Bagan, null=True, blank=True, on_delete=models.CASCADE)
    detail_bagan = models.ForeignKey(DetailBagan, null=True, blank=True, on_delete=models.SET_NULL, related_name='detail_bagan')
    db = models.ForeignKey(DetailBagan, null=True, blank=True, on_delete=models.SET_NULL, related_name='db')
    round = models.IntegerField()
    
class Score(models.Model):
    detail_bagan = models.ForeignKey(DetailBagan, on_delete=models.CASCADE, null=True, blank=True)
    atlet = models.IntegerField(null=True, blank=True)
    score1 = models.CharField(null=True, blank=True, max_length=10, default='0.0')
    score2 = models.CharField(null=True, blank=True, max_length=10, default='0.0')
    score3 = models.CharField(null=True, blank=True, max_length=10, default='0.0')
    score4 = models.CharField(null=True, blank=True, max_length=10, default='0.0')
    score5 = models.CharField(null=True, blank=True, max_length=10, default='0.0')

    def __str__(self):
        return f'{self.detail_bagan} - {self.atlet}'
    
class Tatami(models.Model):
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    tatami_number = models.IntegerField(null=True, blank=True)
    detail_bagan = models.ForeignKey(DetailBagan, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return f'Tatami - {self.tatami_number}'

class AdminTatami(models.Model):
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    tatami = models.ForeignKey(Tatami, null=True, blank=True, on_delete=models.CASCADE)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)

    def __str__(self):
        return f'{self.user.username}'
    
class Jury(models.Model):
    event = models.ForeignKey(Event, null=True, blank=True, on_delete=models.CASCADE)
    tatami = models.ForeignKey(Tatami, null=True, blank=True, on_delete=models.CASCADE)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    jury_number = models.IntegerField(null=True, blank=True)

    def __str__(self):
        return f'{self.user.username}'

class TimetableDay(models.Model):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name='timetable_days')
    order = models.PositiveIntegerField(default=0)
    tanggal = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ['order']

class TimetableRow(models.Model):
    ROW_TYPE = [
        ('slot', 'Slot Waktu'),
        ('label', 'Label / Break'),
    ]
    day = models.ForeignKey(TimetableDay, on_delete=models.CASCADE, related_name='rows', null=True, blank=True)
    order = models.PositiveIntegerField(default=0)
    row_type = models.CharField(max_length=10, choices=ROW_TYPE, default='slot')
    time_label = models.CharField(max_length=50, blank=True)
    label_text = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['order']

class TimetableCell(models.Model):
    row = models.ForeignKey(TimetableRow, on_delete=models.CASCADE, related_name='cells')
    tatami = models.ForeignKey(Tatami, on_delete=models.CASCADE)
    nomor_tanding = models.ForeignKey(NomorTanding, on_delete=models.SET_NULL, null=True, blank=True)
    custom_text = models.CharField(max_length=200, blank=True)

    class Meta:
        unique_together = ('row', 'tatami')

class KopSurat(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='kop_surat')
    logo = models.ImageField(upload_to='kop_surat_logos/', null=True, blank=True)
    nama_organisasi = models.CharField(max_length=200, blank=True)
    alamat = models.CharField(max_length=300, blank=True)
    kontak = models.CharField(max_length=200, blank=True)

class EventKeterangan(models.Model):
    event = models.OneToOneField(Event, on_delete=models.CASCADE, related_name='keterangan')
    text = models.TextField(blank=True)


