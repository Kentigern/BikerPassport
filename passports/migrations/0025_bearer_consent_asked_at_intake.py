# Consent is now asked by the volunteer at intake, for two purposes: keeping
# contact details, and using them for marketing. The old "next season"
# purpose becomes "keep contact details" — every bearer is still "pending"
# (the consent-request email was never sent), so the values carry over as-is.

import uuid

from django.db import migrations, models

CHOICES = [('pending', 'Not set'), ('granted', 'Granted'), ('declined', 'Declined')]


class Migration(migrations.Migration):

    dependencies = [
        ('passports', '0024_publicmessage_second_stamp'),
    ]

    operations = []
    for model in ('bearer', 'historicalbearer'):
        operations += [
            migrations.RenameField(model, 'next_season_consent_status', 'retention_consent_status'),
            migrations.RenameField(model, 'next_season_consent_responded_at', 'retention_consent_responded_at'),
            migrations.AlterField(
                model_name=model,
                name='retention_consent_status',
                field=models.CharField(
                    'keep contact details', max_length=10, choices=CHOICES, default='pending',
                    help_text='Permission for Make Your Mark to keep their contact details after this season.',
                ),
            ),
            migrations.AlterField(
                model_name=model,
                name='marketing_consent_status',
                field=models.CharField(
                    'use for marketing', max_length=10, choices=CHOICES, default='pending',
                    help_text='Permission to use their contact details for marketing (e.g. events, merchandise).',
                ),
            ),
            migrations.AlterField(
                model_name=model,
                name='consent_token',
                field=models.UUIDField(
                    default=uuid.uuid4, editable=False,
                    help_text="Token for the bearer's no-login link to withdraw consent.",
                    **({'unique': True} if model == 'bearer' else {'db_index': True}),
                ),
            ),
        ]
    del model
