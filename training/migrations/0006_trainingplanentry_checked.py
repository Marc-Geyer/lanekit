from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('training', '0005_sessionexception_end_date_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='trainingplanentry',
            name='checked',
            field=models.BooleanField(
                default=False,
                help_text='Ticked off while executing the session; does not affect ordering.',
            ),
        ),
    ]