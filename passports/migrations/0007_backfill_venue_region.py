from django.db import migrations

# From the legacy volunteer data-entry tool's page definitions — the physical
# passport's region groupings, by venue number range (1-296).
REGIONS = [
    (1, 80, 'Wales'),
    (81, 141, 'Cotswolds & the South West'),
    (142, 159, 'South East England'),
    (160, 177, 'East England'),
    (178, 219, 'West Midlands'),
    (220, 257, 'East Midlands'),
    (258, 285, 'North West'),
    (286, 296, 'North East'),
]


def backfill_region(apps, schema_editor):
    Venue = apps.get_model('passports', 'Venue')
    for start, end, region in REGIONS:
        Venue.objects.filter(number__gte=start, number__lte=end, category='').update(category=region)


def clear_region(apps, schema_editor):
    Venue = apps.get_model('passports', 'Venue')
    regions = [region for _, _, region in REGIONS]
    Venue.objects.filter(category__in=regions).update(category='')


class Migration(migrations.Migration):

    dependencies = [
        ('passports', '0006_venue_page_group'),
    ]

    operations = [
        migrations.RunPython(backfill_region, clear_region),
    ]
