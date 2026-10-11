from django.contrib import admin
from .models import ActivityEvent, Movie, ScrapeRun, Visit


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
	list_display = ('path', 'ip_address', 'created_at')
	list_filter = ('created_at',)
	date_hierarchy = 'created_at'
	search_fields = ('path', 'ip_address')
	readonly_fields = ('path', 'ip_address', 'user_agent', 'referer', 'created_at')

	def has_add_permission(self, request):
		return False

	def has_change_permission(self, request, obj=None):
		return False

	def has_delete_permission(self, request, obj=None):
		return False


admin.site.register(ActivityEvent)
admin.site.register(Movie)
admin.site.register(ScrapeRun)
