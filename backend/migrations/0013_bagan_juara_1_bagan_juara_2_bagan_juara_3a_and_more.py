# Generated by Django 5.2.3 on 2025-06-18 15:30

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('backend', '0012_alter_score_score1_alter_score_score2_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='bagan',
            name='juara_1',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='juara1', to='backend.atlet'),
        ),
        migrations.AddField(
            model_name='bagan',
            name='juara_2',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='juara2', to='backend.atlet'),
        ),
        migrations.AddField(
            model_name='bagan',
            name='juara_3a',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='juara3a', to='backend.atlet'),
        ),
        migrations.AddField(
            model_name='bagan',
            name='juara_3b',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='juara3b', to='backend.atlet'),
        ),
    ]
