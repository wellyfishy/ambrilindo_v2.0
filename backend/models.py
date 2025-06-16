from django.db import models
from django.contrib.auth.models import User

class Admin(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)

class Event(models.Model):
    nama_event = models.CharField(max_length=100, null=True, blank=True)
    sedang_berjalan = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.nama_event} - {self.sedang_berjalan}'

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

    def __str__(self):
        return f'{self.nama_bagan}'
    
class DetailBagan(models.Model):
    bagan = models.ForeignKey(Bagan, null=True, blank=True, on_delete=models.CASCADE)
    round = models.IntegerField()
    urutan = models.IntegerField()
    atlet1 = models.ForeignKey(Atlet, null=True, blank=True, on_delete=models.SET_NULL, related_name="atlet1")
    atlet2 = models.ForeignKey(Atlet, null=True, blank=True, on_delete=models.SET_NULL, related_name="atlet2")
    score1 = models.CharField(max_length=10, null=True, blank=True)
    score2 = models.CharField(max_length=10, null=True, blank=True)
    kata1 = models.CharField(max_length=50, null=True, blank=True)
    kata2 = models.CharField(max_length=50, null=True, blank=True)
    hantei = models.BooleanField(default=False)

    def __str__(self):
        return f'{self.pk} - {self.round} - {self.urutan}'
    
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


