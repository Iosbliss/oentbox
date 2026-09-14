from django.contrib import admin
from .models import ActivityEvent, Movie, ScrapeRun

admin.site.register(ActivityEvent)
admin.site.register(Movie)
admin.site.register(ScrapeRun)
