# Generated by Django 5.2.2 on 2025-06-08 23:46

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0004_admin'),
    ]

    operations = [
        migrations.CreateModel(
            name='NomorTanding',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nama_nomor_tanding', models.CharField(blank=True, max_length=50, null=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='backend.event')),
            ],
        ),
        migrations.CreateModel(
            name='Perguruan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nama_perguruan', models.CharField(blank=True, max_length=50, null=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='backend.event')),
            ],
        ),
        migrations.CreateModel(
            name='Utusan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nama_utusan', models.CharField(blank=True, max_length=50, null=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='backend.event')),
            ],
        ),
        migrations.CreateModel(
            name='Atlet',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nama_atlet', models.CharField(blank=True, max_length=50, null=True)),
                ('event', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='backend.event')),
                ('nomor_tanding', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='backend.nomortanding')),
                ('perguruan', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='backend.perguruan')),
                ('utusan', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='backend.utusan')),
            ],
        ),
    ]
