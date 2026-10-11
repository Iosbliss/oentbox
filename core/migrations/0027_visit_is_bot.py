from django.db import migrations, models

BOT_SIGNATURES = (
	'bot', 'crawl', 'slurp', 'spider', 'facebookexternalhit',
	'twitterbot', 'linkedinbot', 'whatsapp', 'telegrambot',
	'preview', 'google-inspection', 'headlesschrome',
	'python-requests', 'python-urllib', 'curl/', 'wget/', 'httpclient',
	'java/', 'go-http-client', 'okhttp', 'axios', 'scrapy',
	'zgrab', 'masscan', 'nmap', 'nikto', 'sqlmap',
)


def backfill_is_bot(apps, schema_editor):
	Visit = apps.get_model('core', 'Visit')
	for visit in Visit.objects.filter(is_bot=False).iterator():
		ua = (visit.user_agent or '').lower()
		visit.is_bot = (not visit.user_agent) or any(sig in ua for sig in BOT_SIGNATURES)
		visit.save(update_fields=['is_bot'])


class Migration(migrations.Migration):

	dependencies = [
		('core', '0026_visit_remove_movie_movie_title_trgm_and_more'),
	]

	operations = [
		migrations.AddField(
			model_name='visit',
			name='is_bot',
			field=models.BooleanField(default=False, db_index=True),
		),
		migrations.RunPython(backfill_is_bot, migrations.RunPython.noop),
	]
