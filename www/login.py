from frappe import _
from frappe.www.login import get_context as get_frappe_login_context

no_cache = True


def get_context(context):
	"""Keep Frappe's login configuration and redirects, with library branding."""
	get_frappe_login_context(context)
	if context.app_name == "Frappe":
		context.app_name = _("Oring Library")
	return context
