import logging
import re

from django.conf import settings

from .models import Visit

logger = logging.getLogger(__name__)

BOT_PATTERNS = (
	'bot', 'crawl', 'slurp', 'spider', 'facebookexternalhit',
	'twitterbot', 'linkedinbot', 'whatsapp', 'telegrambot',
	'preview', 'google-inspection', 'headlesschrome',
	'python-requests', 'python-urllib', 'curl/', 'wget/', 'httpclient',
	'java/', 'go-http-client', 'okhttp', 'axios', 'scrapy',
	'zgrab', 'masscan', 'nmap', 'nikto', 'sqlmap',
)

# The real, user-facing pages oentbox serves (see core/urls.py). The
# server gets a constant stream of scanner probes looking for
# WordPress/Laravel/generic panels (/wp-login.php, /wp-json/, /blog/,
# /cms/, /auth/login, ...). Recording those pollutes visitor analytics
# with junk, so only whitelisted page paths are ever counted — that
# keeps the dashboard about visitors to oentbox itself.
_ALLOWED_PATH_PATTERN = (
	r'^/(?:'
	r'|index\.html|about\.html|privacy\.html|terms\.html'
	r'|youtube\.html|youtube/video\.html|browse\.html'
	r'|saved\.html|video_detail\.html|title\.html|random/)'
	r'$'
)
_ALLOWED_PATH_RE = re.compile(_ALLOWED_PATH_PATTERN)


def _visitor_ip(request):
	remote_addr = request.META.get('REMOTE_ADDR', '')
	if getattr(settings, 'BEHIND_PROXY', False):
		forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR', '')
		if forwarded_for:
			candidate = forwarded_for.split(',')[0].strip()
			if candidate:
				return candidate
		real_ip = request.META.get('HTTP_X_REAL_IP', '').strip()
		if real_ip:
			return real_ip
	return remote_addr or 'unknown'


def _is_bot(user_agent):
	if not user_agent:
		return True
	user_agent_lower = user_agent.lower()
	return any(pattern in user_agent_lower for pattern in BOT_PATTERNS)


def is_tracked_page(path):
	"""True when a path is a genuine oentbox page view."""
	return bool(_ALLOWED_PATH_RE.match(path))


def _should_skip(path):
	if not is_tracked_page(path):
		# Unknown paths are scanner probes, infrastructure, or 404s.
		return True
	skip_prefixes = ('/admin', '/dashboard', '/healthz/', '/api/')
	return any(path.startswith(prefix) for prefix in skip_prefixes)


class VisitTrackingMiddleware:
	"""Records page views to the Visit model without ever breaking a request."""

	def __init__(self, get_response):
		self.get_response = get_response

	def __call__(self, request):
		response = self.get_response(request)
		try:
			self._record_visit(request)
		except Exception as error:
			logger.warning('Visit tracking failed: %s', error)
		return response

	def _record_visit(self, request):
		if request.method != 'GET':
			return
		path = request.path
		if _should_skip(path):
			return
		user_agent = request.META.get('HTTP_USER_AGENT', '')
		Visit.objects.create(
			path=path,
			ip_address=_visitor_ip(request),
			user_agent=user_agent,
			referer=request.META.get('HTTP_REFERER', '')[:500],
			# Known automation is still counted, but flagged so the
			# analytics panel can split bot vs human traffic.
			is_bot=_is_bot(user_agent),
		)
